"""Season team production and opponent production, with explicit source coverage."""
import asyncio
import datetime as dt
import json
import math
import re
from zoneinfo import ZoneInfo
import httpx
from . import db, providers

SCHEMA = """CREATE TABLE IF NOT EXISTS team_rankings_cache (
 sport TEXT NOT NULL, season INTEGER NOT NULL, season_type TEXT NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY(sport,season,season_type));"""
NFL_METRICS = {
 'pass_yds': ('Passing Yards', 'passing', 'passingYards'),
 'rec_yds': ('Receiving Yards', 'receiving', 'receivingYards'),
 'rec': ('Receptions', 'receiving', 'receptions'),
 'rush_yds': ('Rushing Yards', 'rushing', 'rushingYards'),
 'rush_att': ('Rushing Attempts', 'rushing', 'rushingAttempts'),
 'pass_td': ('Passing Touchdowns', 'passing', 'passingTouchdowns'),
 'rush_td': ('Rushing Touchdowns', 'rushing', 'rushingTouchdowns'),
 'rec_td': ('Receiving Touchdowns', 'receiving', 'receivingTouchdowns'),
 'pts': ('Points', 'passing', 'totalPoints'),
}
NBA_METRICS = {
 'pts': ('Points', 'avgPoints'), 'reb': ('Rebounds', 'avgRebounds'),
 'ast': ('Assists', 'avgAssists'), 'fg3m': ('3-Pointers Made', 'avgThreePointFieldGoalsMade'),
 'stl': ('Steals', 'avgSteals'), 'blk': ('Blocks', 'avgBlocks'),
}
COMBOS = {'pra': ('Points + Rebounds + Assists', ('pts','reb','ast')),
          'pr': ('Points + Rebounds', ('pts','reb')), 'pa': ('Points + Assists', ('pts','ast')),
          'ra': ('Rebounds + Assists', ('reb','ast'))}
SEASON_TYPES = {'regular': 2, 'postseason': 3}
_locks = {}


class NoSeasonStats(ValueError):
    """The source has no completed stats for the requested season/category."""


def empty_season(sport,season,season_type):
    return {'sport':sport,'season':season,'season_label':season_label(sport,season),'season_type':season_type,
            'teams':[],'errors':[],'no_stats':True,'expected_teams':30 if sport=='NBA' else 32,
            'updated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'source':'ESPN',
            'note':'No completed team statistics reported for this season and game type yet. Previous-season stats are kept separate. Update Rankings after results are recorded.'}


def numeric(value):
    try:
        value = float(str(value).replace(',', ''))
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def validate(sport, season, season_type):
    sport = sport.upper()
    if sport not in ('NBA', 'NFL'): raise ValueError('Choose NBA or NFL')
    if season_type not in SEASON_TYPES: raise ValueError('Choose regular season or playoffs')
    year = dt.date.today().year
    if not 2002 <= season <= year + 1: raise ValueError('Choose a valid season year')
    return sport


def metrics(sport):
    source = NFL_METRICS if sport == 'NFL' else {**NBA_METRICS, **COMBOS}
    return [{'key': key, 'label': spec[0]} for key, spec in source.items()]


def season_label(sport, season):
    return str(season) if sport == 'NFL' else f'{season-1}–{str(season)[-2:]}'


def parse_nfl_team(payload, team, season, season_type, url):
    requested = payload.get('requestedSeason') or {}
    if requested.get('year') != season or requested.get('type') != SEASON_TYPES[season_type]:
        raise ValueError('Source returned a different season')
    results = payload.get('results') or {}
    def side(categories):
        values = {cat.get('name'): {s.get('name'): numeric(s.get('value')) for s in cat.get('stats', [])} for cat in categories}
        games = values.get('general', {}).get('gamesPlayed')
        if games is None: games = values.get('passing', {}).get('teamGamesPlayed')
        if games is None or games <= 0: return {}, 0
        # Compute averages from season totals; ESPN perGameValue can be truncated.
        stats = {}
        for key, (_, category, name) in NFL_METRICS.items():
            total = values.get(category, {}).get(name)
            stats[key] = total / games if total is not None else None
        return stats, int(games)
    offense, games = side((results.get('stats') or {}).get('categories', []))
    allowed, defense_games = side(results.get('opponent') or [])
    return {'team': db.normalize_team('NFL', team['abbreviation']), 'name': team['displayName'],
            'games': games, 'defense_games': defense_games, 'offense': offense, 'allowed': allowed,
            'source_url': url}


def nba_content(text, season, season_type):
    match = re.search(r"window\[['\"]__espnfitt__['\"]\]\s*=\s*", text)
    if not match: raise ValueError('NBA statistics page format changed')
    try: content = json.JSONDecoder().raw_decode(text[match.end():])[0]['page']['content']
    except (ValueError, KeyError, TypeError): raise ValueError('NBA statistics page could not be read')
    expected = f'{season-1}-{str(season)[-2:]}'
    heading = content.get('pageHeading', '')
    kind = 'Regular Season' if season_type == 'regular' else 'Postseason'
    if expected not in heading or kind not in heading:
        raise NoSeasonStats('No NBA statistics available for the selected season yet')
    return content


def parse_nba_side(content):
    out = {}
    for row in content.get('teamStats', []):
        team = row.get('team') or {}
        if not team.get('abbrev'): continue
        raw = {s.get('name'): numeric(s.get('value')) for s in row.get('stats', [])}
        games = raw.get('gamesPlayed')
        values = {key: raw.get(spec[1]) for key, spec in NBA_METRICS.items()} if games and games > 0 else {}
        for key, (_, parts) in COMBOS.items():
            values[key] = sum(values[p] for p in parts) if all(values.get(p) is not None for p in parts) else None
        out[db.normalize_team('NBA', team['abbrev'])] = {'name': team.get('displayName', team['abbrev']), 'games': int(games or 0), 'values': values}
    return out


async def fetch_league(sport, season, season_type):
    errors = []
    async with httpx.AsyncClient(headers={'User-Agent': providers.USER_AGENT, 'Accept': 'application/json,text/html'}) as client:
        if sport == 'NBA':
            urls = [f'https://www.espn.com/nba/stats/team/_/view/{view}/season/{season}/seasontype/{SEASON_TYPES[season_type]}' for view in ('team','opponent')]
            async def read(url):
                response = await client.get(url, timeout=25, follow_redirects=True)
                response.raise_for_status()
                return parse_nba_side(nba_content(response.text, season, season_type))
            offense, defense = await asyncio.gather(*(read(url) for url in urls))
            rows = []
            for team in sorted(set(offense) | set(defense)):
                a, b = offense.get(team, {}), defense.get(team, {})
                rows.append({'team':team, 'name':a.get('name') or b.get('name'), 'games':a.get('games',0),
                             'defense_games':b.get('games',0), 'offense':a.get('values',{}), 'allowed':b.get('values',{}),
                             'source_url':urls[0], 'defense_source_url':urls[1]})
        else:
            url = f'{providers.BASE}/football/nfl/teams?limit=1000'
            league = await providers.fetch_json(client, url)
            teams = [x['team'] for x in league['sports'][0]['leagues'][0]['teams'] if not x['team'].get('isAllStar')]
            sem = asyncio.Semaphore(4)
            async def read(team):
                async with sem:
                    url = f'{providers.BASE}/football/nfl/teams/{team["id"]}/statistics?season={season}&seasontype={SEASON_TYPES[season_type]}'
                    try:
                        payload = await providers.fetch_json(client, url)
                        return parse_nfl_team(payload, team, season, season_type, url)
                    except Exception as ex:
                        errors.append(f'{team["displayName"]}: {str(ex)[:120]}')
                        return None
            rows = [r for r in await asyncio.gather(*(read(team) for team in teams)) if r is not None]
    if not rows or not any(r['games'] or r['defense_games'] for r in rows):
        raise NoSeasonStats('No completed team statistics available for this season yet. Try another season.')
    return {'sport':sport, 'season':season, 'season_label':season_label(sport, season), 'season_type':season_type,
            'updated_at':dt.datetime.now(dt.timezone.utc).isoformat(), 'teams':rows, 'errors':errors,
            'expected_teams':32 if sport=='NFL' else 30, 'source':'ESPN',
            'note':'Season averages per team game. Passing yards are gross passing yards (before sack deductions), matching player passing-yard props.' if sport=='NFL' else 'Season averages per team game. Combined categories add the displayed points, rebounds and assists averages; small rounding differences are possible.'}


async def refresh(sport, season, season_type):
    sport = validate(sport, season, season_type)
    key = (sport,season,season_type)
    async with _locks.setdefault(key, asyncio.Lock()):
        try:payload = await fetch_league(sport,season,season_type)
        except NoSeasonStats:
            # Never erase real season data when a source temporarily falls back to another page.
            previous=cached(sport,season,season_type)
            if previous and any(t.get('games',0) or t.get('defense_games',0) for t in previous['teams']):raise
            payload=empty_season(sport,season,season_type)
        if payload.get('sport')!=sport or payload.get('season')!=season or payload.get('season_type')!=season_type:
            raise ValueError('Source returned statistics for a different season or game type')
        with db.connect() as connection:
            connection.execute('INSERT INTO team_rankings_cache VALUES (?,?,?,?) ON CONFLICT(sport,season,season_type) DO UPDATE SET payload=excluded.payload', (*key,json.dumps(payload)))
        return payload


def cached(sport,season,season_type):
    sport = validate(sport,season,season_type)
    with db.connect() as connection:
        row = connection.execute('SELECT payload FROM team_rankings_cache WHERE sport=? AND season=? AND season_type=?',(sport,season,season_type)).fetchone()
    if not row:return None
    payload=json.loads(row['payload'])
    if payload.get('sport')!=sport or payload.get('season')!=season or payload.get('season_type')!=season_type:return None
    payload['needs_refresh']=sport=='NFL' and any(any(key not in t.get(view,{}) for key in ('rush_td','rec_td')) for t in payload['teams'] for view in ('offense','allowed'))
    if payload.get('no_stats'):
        try:payload['needs_refresh']=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(payload['updated_at'])).total_seconds()>=300
        except (ValueError,KeyError):payload['needs_refresh']=True
    return payload


def ranked(payload,metric='pass_yds',view='offense',order='most'):
    sport = payload['sport']
    if metric not in {m['key'] for m in metrics(sport)}: raise ValueError('Choose a category for this league')
    if view not in ('offense','allowed') or order not in ('most','fewest'): raise ValueError('Choose offense or allowed, and most or fewest')
    rows = []
    for team in payload['teams']:
        value = team.get(view,{}).get(metric)
        games = team.get('games' if view=='offense' else 'defense_games',0)
        if value is None or games <= 0: continue
        rows.append({**team,'value':value, 'sample':games})
    rows.sort(key=lambda r: ((-r['value'] if order=='most' else r['value']),r['name']))
    prior = None
    for index,row in enumerate(rows,1):
        rounded = round(row['value'],6)
        if rounded != prior: rank = index
        row['rank'] = rank; prior = rounded
        row['value'] = round(row['value'],2)
    return {**payload,'metric':metric,'view':view,'order':order,'ranked_teams':len(rows),'rows':rows,'metrics':metrics(sport)}


def config():
    now = dt.datetime.now(ZoneInfo(db.get_settings().get('timezone','America/Chicago')))
    current = {'NFL':now.year if now.month>=8 else now.year-1,'NBA':now.year+1 if now.month>=10 else now.year}
    defaults = dict(current)
    # NBA begins with the actual current season, even before its first recorded game.
    # Keep the existing football preference separate from the NBA season selector.
    with db.connect() as connection:
        for sport in ('NFL',):
            dates = [r[0] for r in connection.execute("SELECT DISTINCT game_date FROM player_logs WHERE sport=? AND season_type='regular'",(sport,))]
            years = [int(d[:4])+(sport=='NBA' and int(d[5:7])>=8) if sport=='NBA' else int(d[:4])-(int(d[5:7])<8) for d in dates if len(d)==10]
            if years: defaults[sport] = min(current[sport],max(years))
    return {'defaults':defaults,'current':current,'seasons':{sport:[{'value':year,'label':f'{year-1}–{year}' if sport=='NBA' else str(year)} for year in range(current[sport],current[sport]-4,-1)] for sport in current}}

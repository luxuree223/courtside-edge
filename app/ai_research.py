"""Local user research instructions and bounded public matchup context for AI."""
import datetime as dt
import json
import re
import httpx
from pathlib import Path
from zoneinfo import ZoneInfo
from . import db,providers,rankings,markets,covers,live,props,player_opportunities,research_scope

SCHEMA="""CREATE TABLE IF NOT EXISTS ai_research_rules (
 id INTEGER PRIMARY KEY CHECK(id=1), text TEXT NOT NULL, enabled INTEGER NOT NULL,
 updated_at TEXT NOT NULL);"""
DEFAULT_RULES="""Use FanDuel, Caesars and DraftKings only. Favor straight bets.
For a matchup, compare both teams' offense with what the opponent allows, including league ranks.
Find specific player research leads using recent games and season production. Include passing, rushing and receiving touchdowns when relevant; distinguish passer TDs from receiver TDs.
Compare the actual offered line and odds with the player's saved history when available. Show the number of games and source time.
Lead with a short assessment, then the strongest research leads, supporting numbers, and what I still need to check.
Use clear sportsbook terminology and clickable sources. Give concise reasons. Pass when evidence is insufficient; never invent a price or treat a past hit rate as a winning probability."""


def rules():
    with db.connect() as c:row=c.execute('SELECT text,enabled,updated_at FROM ai_research_rules WHERE id=1').fetchone()
    from .research_tools import master_version
    return {'text':row['text'] if row else DEFAULT_RULES,'enabled':bool(row['enabled']) if row else True,'master_version':master_version(),'master_enabled':True,
            'updated_at':row['updated_at'] if row else None,'origin':'saved' if row else 'app_defaults','starter':DEFAULT_RULES}


def save_rules(text,enabled):
    if len(text)>12000:raise ValueError('Keep your research rules under 12,000 characters.')
    with db.connect() as c:
        c.execute('INSERT INTO ai_research_rules VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET text=excluded.text,enabled=excluded.enabled,updated_at=excluded.updated_at',
                  (text.strip(),int(enabled),dt.datetime.now(dt.timezone.utc).isoformat()))
    return rules()


def normalize(text):return re.sub(r'[^a-z0-9]+',' ',str(text).lower()).strip()


def mentioned_teams(sport,text,games):
    names={}
    try:
        catalog=json.loads((Path(__file__).resolve().parent.parent/'static/teams/sources.json').read_text(encoding='utf-8'))
        names.update({key.split(':')[1]:item['name'] for key,item in catalog.items() if key.startswith(sport+':')})
    except (OSError,ValueError):pass
    for g in games:
        for side in ('home','away'):
            if g[side]!=g[side+'_abbr']:names.setdefault(g[side+'_abbr'],g[side])
    aliases={}
    for team,name in names.items():
        parts=name.split();city=' '.join(parts[:-1]);nickname=parts[-1]
        if name.endswith('Trail Blazers'):city=' '.join(parts[:-2]);nickname='Trail Blazers'
        for alias in (name,city,nickname,team):
            key=normalize(alias)
            if len(key)>=2:aliases.setdefault(key,set()).add(team)
    query=' '+normalize(text)+' ';found=set()
    for alias,teams in aliases.items():
        if alias=='no' and not re.search(r'\bNO\b',text):continue
        if len(teams)==1 and ' '+alias+' ' in query:found.update(teams)
    return found


def resolve_game(sport,game_id,question,history):
    zone=db.get_settings().get('timezone','America/Chicago');today=dt.datetime.now(ZoneInfo(zone)).date()
    dates={(today+dt.timedelta(days=i)).isoformat() for i in range(1 if sport=='NFL' else 4)}
    games=db.games_list(sport,limit=3000)
    available=[g for g in games if providers.iso_day(g['starts_at'],zone) in dates]
    named=mentioned_teams(sport,question,games)
    if not named and game_id:
        game=covers.game(sport,game_id)
        return game,'Selected game',[]
    if not named:
        for item in reversed(history):
            if item.get('role')=='user':
                named=mentioned_teams(sport,item.get('content',''),games)
                if named:break
    candidates=[g for g in available if named and named.issubset({g['home_abbr'],g['away_abbr']})]
    if len(candidates)==1:return candidates[0],'Matched teams from question or recent chat',[]
    return None,'No unique game matched',candidates[:6]


def compact_players(sport,game,question,history=()):
    window=research_scope.resolve(question,sport,history);last=window['last']
    defaults={'NFL':{'pass_yds':224.5,'rush_yds':49.5,'rec_yds':49.5},'NBA':{'pts':20.5,'reb':6.5,'ast':4.5,'fg3m':2.5}}
    selected=list(defaults[sport]);q=question.lower()
    if sport=='NFL':
        if any(w in q for w in ('receiv','reception','receiver')):selected=['rec_yds','rec_td','rec']
        elif any(w in q for w in ('rush','running back')):selected=['rush_yds','rush_td','rush_att']
        elif 'pass' in q:selected=['pass_yds','pass_td']
    out=[];before=providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago'))
    for stat in selected:
        threshold=defaults[sport].get(stat,.5 if stat.endswith('_td') else 2.5)
        rows=db.consistency(sport,[game['home_abbr'],game['away_abbr']],stat,threshold,0,100,last,season_type=game['season_type'],comparison='over',before=before,max_results=4,date_from=window['start'],date_to=window['end'],season_types=window['game_types'])
        for r in rows:
            if r['max']<=0:continue
            item={key:r[key] for key in ('player','position','team','stat','threshold','comparison','sample','requested','hits','rate','average','latest')}
            item['research_threshold_only']=True;item['research_window']=window
            item['recent_results']=[{'date':l['date'],'value':l['value'],'opponent':l['opponent']} for l in r['logs'][:5]]
            item['displayed_log_limit']=5
            item['source_urls']=list(dict.fromkeys(l['source_url'] for l in r['logs'] if l['source_url']))[:2]
            out.append(item)
    return out,last


async def context(sport,game_id,question,history,refresh_odds=False):
    zone=db.get_settings().get('timezone','America/Chicago')
    result={'sport':sport,'as_of':dt.datetime.now(ZoneInfo(zone)).isoformat(),'timezone':zone,'preferred_books':['FanDuel','Caesars','DraftKings'],'notes':[]}
    game,resolution,candidates=resolve_game(sport,game_id,question,history)
    result['game_resolution']=resolution
    if candidates:result['game_candidates']=[{k:g[k] for k in ('id','home','away','starts_at')} for g in candidates]
    window=research_scope.resolve(question,sport,history);season=window['season']
    result['research_window']=window
    team_type='postseason' if window['game_types']==['postseason'] else 'regular'
    result['team_statistics_game_type']=team_type
    cache=rankings.cached(sport,season,team_type) if window['game_types']!=['preseason'] else None
    if game:
        if window['game_types']!=['preseason'] and (not cache or cache.get('needs_refresh')):
            try:cache=await rankings.refresh(sport,season,team_type)
            except (ValueError,KeyError,TypeError,httpx.HTTPError):result['notes'].append('Team stats could not refresh; using available saved data.')
        overview=await live.overview(sport,game['id'],refresh_odds=refresh_odds)
        game=overview['game']
        result['selected_game']={k:game.get(k) for k in ('id','sport','home','away','home_abbr','away_abbr','starts_at','season_type','status','home_score','away_score','status_detail')}
        result['selected_game']['local_date']=providers.iso_day(game['starts_at'],zone)
        result['scores']={key:overview.get(key) for key in ('score_fetched_at','score_source_url','score_stale','score_error')}
        result['game_prices']={**(overview.get('prices') or {}),'quotes':(overview.get('prices') or {}).get('quotes',[])[:24] if game['status']!='final' else []}
        result['odds_note']=overview.get('odds_error')
        if game['status']!='final':result['saved_player_prop_quotes']=props.listed(sport,game['id'])['quotes'][:24]
        result['player_history_checks'],last=compact_players(sport,game,question,history)
        checks=[]
        for quote in result.get('saved_player_prop_quotes',[])[:8]:
            try:
                checked=props.history(quote['id'],last,date_from=window['start'],date_to=window['end'],season_types=window['game_types'])
                checks.append({k:v for k,v in checked.items() if k not in ('logs','players')})
            except ValueError:pass
        result['exact_prop_history_checks']=checks
        if sport=='NFL' and game['status']!='final':
            td=player_opportunities.opportunities(game['id'],last,season,season_type=team_type,date_from=window['start'],date_to=window['end'],season_types=window['game_types'])
            result['player_td_opportunities']={**{k:td.get(k) for k in ('season_label','season_type','before','note')},'rows':[{k:v for k,v in r.items() if k!='logs'} for r in td['rows'][:8]]}
        with db.connect() as c:readings=c.execute('SELECT s.id,r.payload FROM covers_snapshots s JOIN snapshot_readings r ON s.id=r.snapshot_id WHERE s.sport=? AND s.game_id=? ORDER BY s.captured_at DESC LIMIT 2',(sport,game['id'])).fetchall()
        result['snapshot_readings']=[json.loads(r['payload']) for r in readings]
    if game and providers.iso_day(game['starts_at'],zone)<dt.datetime.now(ZoneInfo(zone)).date().isoformat():
        # Current season aggregates can contain games after a requested historical matchup.
        cache=None
        result.pop('player_td_opportunities',None)
        result['notes'].append('Current team aggregates and TD screens excluded from historical-game research to avoid future information. Historical team snapshots are unavailable.')
    if cache:
        teams=cache['teams']
        if game:teams=[t for t in teams if t['team'] in (game['home_abbr'],game['away_abbr'])]
        enriched=[]
        for t in teams:
            ranks={view:{} for view in ('offense','allowed')}
            for metric in rankings.metrics(sport):
                for view in ranks:
                    table=rankings.ranked(cache,metric['key'],view)
                    row=next((r for r in table['rows'] if r['team']==t['team']),None)
                    if row:ranks[view][metric['key']]={'rank':row['rank'],'teams':table['ranked_teams']}
            enriched.append({**t,'league_ranks':ranks})
        result['team_rankings']={k:cache[k] for k in ('sport','season_label','season_type','updated_at','note') if k in cache}
        result['team_rankings'].update(teams=enriched,rank_definition='Offense #1 = most produced; allowed #1 = most allowed.')
    if not game:result['notes'].append('Use the season-scoped player_history or screen_players tools for player research.')
    # Trim whole optional blocks rather than cutting a JSON document in the middle.
    if len(json.dumps(result,ensure_ascii=False))>55000:result.pop('snapshot_readings',None)
    if len(json.dumps(result,ensure_ascii=False))>55000:result.pop('local_search',None)
    return result

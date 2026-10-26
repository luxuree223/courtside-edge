"""Source-backed individual NBA history, isolated from complete-team DVP logs.

Per-player imports must never make a partial box score look like a complete
team. Cache the source responses here; only the full-game collector writes
player_logs. Head-to-head means the same event, opposing teams, both played.
"""
import asyncio
import datetime as dt
import json
import re
from pathlib import Path
import httpx
from . import db, providers, stat_logs, player_splits

CACHE_SCHEMA='''CREATE TABLE IF NOT EXISTS player_history_cache (
 sport TEXT,player_id TEXT,season INTEGER,kind TEXT,payload TEXT,observed_at TEXT,
 PRIMARY KEY(sport,player_id,season,kind))'''
_locks={}


def candidates(name,sport='NBA',player_id=''):
    # Explicit common shorthand; other ambiguous names still require a choice.
    if sport=='NBA' and stat_logs.normal(name)=='luka' and not player_id:name='Luka Doncic'
    needle=db.player_name_key(name)
    with db.research_connect() as c:
        people=[dict(r) for r in c.execute('SELECT sport,player_id,player,position,team,game_date FROM player_search WHERE sport=?',(sport,))]
    saved=[p for p in people if (not player_id or p['player_id']==player_id) and needle in db.player_name_key(p['player'])]
    exact=[p for p in saved if db.player_name_key(p['player'])==needle]
    if exact or saved:return exact or saved
    path=Path(__file__).resolve().parents[1]/'static/teams'/f'primary-positions-{dt.date.today().year+(dt.date.today().month>=7)}.json'
    if sport=='NBA' and path.exists():
        for p in json.loads(path.read_text(encoding='utf-8')).get('players',[]):
            if (not player_id or str(p['player_id'])==player_id) and needle in db.player_name_key(p.get('name','')):
                people.append({'sport':'NBA','player_id':str(p['player_id']),'player':p['name'],'position':p['position'],'team':p['team'],'game_date':''})
    found={p['player_id']:p for p in people if (not player_id or p['player_id']==player_id) and needle in db.player_name_key(p['player'])}
    exact=[p for p in found.values() if db.player_name_key(p['player'])==needle]
    return exact or list(found.values())


def source_url(pid,year,kind):
    if not re.fullmatch(r'\d+',str(pid)):raise ValueError('A sourced ESPN player identifier is required.')
    return f'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{pid}/gamelog?season={year}&seasonType='+str({'regular':2,'postseason':3,'preseason':1}[kind])


def parse_payload(payload,person,year,kind):
    """Join stat rows to dated events, using labels rather than column offsets."""
    selected=next((f.get('value') for f in payload.get('filters',[]) if f.get('name')=='season'),None)
    if str(selected)!=str(year):raise ValueError('Player history source returned a different season.')
    from .research_index import catalog
    league_teams=set(catalog('NBA'))
    events=payload.get('events',{});labels=payload.get('labels',[]);rows={}
    for group in payload.get('seasonTypes',[]):
        title=group.get('displayName','').lower()
        group_kind='preseason' if 'preseason' in title else 'postseason' if 'playoff' in title or 'postseason' in title or 'play-in' in title else 'regular' if 'regular' in title else ''
        if group_kind!=kind:continue
        for category in group.get('categories',[]):
            for entry in category.get('events',[]):
                gid=str(entry.get('eventId',''));event=events.get(gid)
                if not event or str(event.get('id'))!=gid or not gid.isdigit():continue
                if event.get('gameResult') not in ('W','L','T'):continue
                date=providers.iso_day(event.get('gameDate'),'America/New_York')
                if not date or not f'{year-1}-07-01'<=date<f'{year}-07-01':continue
                values=dict(zip(labels,entry.get('stats',[])))
                minutes=providers.number(values.get('MIN'),None)
                if minutes is None or minutes<=0:continue
                team=db.normalize_team('NBA',(event.get('team') or {}).get('abbreviation'))
                opponent=db.normalize_team('NBA',(event.get('opponent') or {}).get('abbreviation'))
                # ESPN's regular-season group also contains All-Star events.
                if team not in league_teams or opponent not in league_teams or team==opponent:continue
                row={'sport':'NBA','player_id':person['player_id'],'player':person['player'],'position':person.get('position',''),
                     'game_id':gid,'game_date':date,'team':team,'opponent':opponent,'is_home':int(event.get('atVs')=='vs'),
                     'season_type':kind,'minutes':minutes,'source':'ESPN','source_url':f'https://www.espn.com/nba/boxscore/_/gameId/{gid}'}
                if event.get('atVs') not in ('vs','@'):continue
                for key,label in [('pts','PTS'),('reb','REB'),('ast','AST'),('stl','STL'),('blk','BLK'),('tov','TO')]:
                    row[key]=providers.number(values.get(label),None)
                for label,made,attempted in [('FG','fgm','fga'),('3PT','fg3m','fg3a')]:
                    pair=str(values.get(label,'')).split('-')
                    row[made]=providers.number(pair[0],None) if len(pair)==2 else None
                    row[attempted]=providers.number(pair[1],None) if len(pair)==2 else None
                rows[gid]=row
    options=next((f.get('options',[]) for f in payload.get('filters',[]) if f.get('name')=='season'),[])
    years=sorted({int(o['value']) for o in options if str(o.get('value','')).isdigit() and 1947<=int(o['value'])<=year},reverse=True)
    return {'format':2,'rows':list(rows.values()),'years':years}


async def fetch_season(client,person,year,kind):
    pid=person['player_id'];url=source_url(pid,year,kind)
    with db.research_connect() as c:
        c.execute(CACHE_SCHEMA)
        cached=c.execute('SELECT * FROM player_history_cache WHERE sport=? AND player_id=? AND season=? AND kind=?',('NBA',pid,year,kind)).fetchone()
    now=dt.datetime.now(dt.timezone.utc)
    ttl=900 if year>=stat_logs.search_today().year+(stat_logs.search_today().month>=7) else 30*86400
    old=json.loads(cached['payload']) if cached else None
    if old and old.get('format')!=2:cached=None;old=None
    if cached and (now-dt.datetime.fromisoformat(cached['observed_at'])).total_seconds()<ttl:return old,''
    lock=_locks.setdefault((str(db.database_path()),pid,year,kind),asyncio.Lock())
    async with lock:
        try:
            response=await client.get(url,timeout=16,follow_redirects=True);response.raise_for_status()
            result=parse_payload(response.json(),person,year,kind);result['observed_at']=now.isoformat()
            with db.research_connect() as c:
                c.execute('INSERT OR REPLACE INTO player_history_cache VALUES (?,?,?,?,?,?)',('NBA',pid,year,kind,json.dumps(result),now.isoformat()))
            return result,''
        except (httpx.HTTPError,ValueError,TypeError,KeyError):
            return old or {'rows':[],'years':[]},f'{year-1}–{str(year)[-2:]} {kind} could not be refreshed'+(' (using saved source data)' if old else '')+'.'


def matching_rows(rows,other,opp,filters,parsed):
    found={}
    today=stat_logs.search_today().isoformat()
    against={r['game_id']:r for r in other or [] if (r.get('minutes') or 0)>0}
    for row in rows:
        if row['game_date']>today or (row.get('minutes') or 0)<=0:continue
        if opp and row['opponent']!=opp:continue
        if other is not None:
            peer=against.get(row['game_id'])
            if not peer or peer['team']!=row['opponent'] or peer['opponent']!=row['team'] or peer['game_date']!=row['game_date']:continue
        if filters['venue']!='all' and bool(row['is_home'])!=(filters['venue']=='home'):continue
        found[row['game_id']]=row
    result=sorted(found.values(),key=lambda r:(r['game_date'],r['game_id']),reverse=True)
    if filters['rest']!='all':result=[r for r in player_splits.add_rest_days('NBA',result) if r['rest_days']==int(filters['rest'])]
    return result[:parsed['last']]


async def search(query,sport='auto',last=None,stat='',opponent='',season_type='regular',player_id='',season_scope='auto',venue='all',rest='all'):
    filters=player_splits.conditions(query,venue,rest)
    parsed=stat_logs.parse_search(filters['query'],sport,last,stat,opponent,season_type,season_scope)
    # NFL keeps its saved-record search; this source is an NBA game-log feed.
    if sport=='NFL':return stat_logs.search(query,sport,last,stat,opponent,season_type,player_id,season_scope,venue,rest)
    people=candidates(parsed['name'],'NBA',player_id)
    if not people or sport=='auto' and not people:
        return stat_logs.search(query,sport,last,stat,opponent,season_type,player_id,season_scope,venue,rest)
    if len(people)!=1:return {'status':'choose_player','parsed':parsed,'candidates':people[:30],'message':'Choose the player you mean.'}
    person=people[0]
    # Local imports can use arbitrary IDs. Never send those as ESPN identities.
    if not str(person['player_id']).isdigit():return stat_logs.search(query,sport,last,stat,opponent,season_type,player_id,season_scope,venue,rest)
    if parsed['stat'] and parsed['stat'] not in db.STATS['NBA']:raise ValueError('That stat does not belong to NBA.')
    peer=None;opp=''
    if parsed['opponent_text']:
        try:opp=stat_logs.opponent_code('NBA',parsed['opponent_text'])
        except ValueError:
            peers=candidates(parsed['opponent_text'])
            if len(peers)!=1:raise ValueError('Use the opposing player’s full name, or a team name such as Orlando Magic.')
            peer=peers[0]
            if peer['player_id']==person['player_id']:raise ValueError('Choose two different players.')
    scope=parsed['season_scope'];window=stat_logs.season_window('NBA',scope,parsed['season_year'])
    year=int(window['start'][:4])+1 if scope!='recent' else stat_logs.search_today().year+(stat_logs.search_today().month>=7)
    auto_career=scope=='recent' and season_scope=='auto'
    if scope=='current' and last is None and not re.search(r'\blast\s+\d+',query,re.I):parsed['last']=100
    years=[year,year-1] if scope=='recent' else [year]
    kinds=['regular','postseason','preseason'] if parsed['season_type']=='all' else [parsed['season_type']]
    rows=[];other=[] if peer else None;issues=[];searched=[];available=None
    # Saved complete-game rows supplement source gaps, never overwrite an
    # individual source response or receive the partial downloaded rows.
    with db.research_connect() as c:
        saved=[dict(r) for r in c.execute("SELECT p.* FROM player_logs p LEFT JOIN games g ON p.sport=g.sport AND p.game_id=g.id WHERE p.sport='NBA' AND p.player_id=? AND (g.id IS NULL OR g.status='final')",(person['player_id'],))]
        peer_saved=[dict(r) for r in c.execute("SELECT p.* FROM player_logs p LEFT JOIN games g ON p.sport=g.sport AND p.game_id=g.id WHERE p.sport='NBA' AND p.player_id=? AND (g.id IS NULL OR g.status='final')",(peer['player_id'],))] if peer else []
    async with httpx.AsyncClient(headers={'User-Agent':providers.USER_AGENT}) as client:
        offset=0
        while offset<len(years) and offset<40:
            y=years[offset];offset+=1;searched.append(y)
            for kind in kinds:
                own,error=await fetch_season(client,person,y,kind)
                if error:issues.append(error)
                if available is None and own['years']:available=own['years']
                start=f'{y-1}-07-01';end=f'{y}-07-01'
                rows.extend(r for r in saved if start<=r['game_date']<end and r['season_type']==kind)
                rows.extend(own['rows'])
                if peer:
                    theirs,error=await fetch_season(client,peer,y,kind)
                    if error:issues.append(peer['player']+': '+error)
                    other.extend(r for r in peer_saved if start<=r['game_date']<end and r['season_type']==kind)
                    other.extend(theirs['rows'])
            matched=matching_rows(rows,other,opp,filters,parsed)
            if len(matched)>=parsed['last']:break
            if auto_career and offset==len(years) and available:
                years.extend(y for y in available if y<min(years) and y not in years)
    matched=matching_rows(rows,other,opp,filters,parsed)
    keys=[parsed['stat']] if parsed['stat'] else list(dict(stat_logs.BOX_COLUMNS['NBA']))
    public=[stat_logs._public(r,'NBA')|{'rest_days':r.get('rest_days')} for r in matched]
    summary={}
    for key in keys:
        values=[r[key] for r in public if r[key] is not None]
        summary[key]={'known':len(values),'missing':len(public)-len(values),'total':round(sum(values),2) if values else None,'average':round(sum(values)/len(values),2) if values else None}
    window.update(label=' + '.join(f'{y-1}–{str(y)[-2:]}' for y in searched),start=f'{min(searched)-1}-07-01',end=min(window['end'],stat_logs.search_today().isoformat()+'T23:59:59'))
    return {'status':'ok','sport':'NBA','player':person,'requested':parsed['last'],'sample':len(public),'rows':public,'summary':summary,
            'columns':[{'key':k,'label':db.STATS['NBA'].get(k,dict(stat_logs.BOX_COLUMNS['NBA']).get(k,k))} for k in keys],
            'stat':parsed['stat'],'opponent':peer['player'] if peer else opp,'opponent_player':peer,'season_type':parsed['season_type'],
            'season_range':window,'conditions':filters,'conditions_note':player_splits.note(filters),'issues':issues,
            'coverage_note':' '.join(dict.fromkeys(issues)),
            'note':'Completed games, newest first. Opponent, participation and venue filters are applied before taking the last games. '+
                   ('Both players recorded minutes on opposing teams in the same game. ' if peer else '')+
                   'Individual history is downloaded from ESPN and cached separately from Defense vs Position. Missing source stats remain blank.'}


async def resolve_game(sport,game_id):
    try:return stat_logs.covers.game(sport,game_id)
    except ValueError:pass
    if sport not in ('NBA','NFL') or not re.fullmatch(r'\d+',game_id):raise ValueError('Choose a valid game.')
    url=f'{providers.BASE}/{providers.SPORT_PATH[sport]}/summary?event={game_id}'
    try:
        async with httpx.AsyncClient(headers={'User-Agent':providers.USER_AGENT}) as client:
            response=await client.get(url,timeout=18);response.raise_for_status();payload=response.json()
        header=payload.get('header',{})
        if str(header.get('id'))!=game_id:raise ValueError('Game identity mismatch.')
        competition=next(iter(header.get('competitions',[])),{})
        event={**header,'date':competition.get('date'),'status':competition.get('status'),
               'season':{'type':header.get('season',{}).get('type',2)}}
        games=providers.parse_scoreboard({'events':[event]},sport)
        if len(games)!=1:raise ValueError('Game details unavailable.')
        with db.research_connect() as c:db.save_game(c,games[0])
        return stat_logs.covers.game(sport,game_id)
    except (httpx.HTTPError,KeyError,TypeError):raise ValueError('Could not load this game from ESPN. Try again.')

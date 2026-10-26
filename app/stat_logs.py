"""Player history searches, game box scores, and dated slate leaders.
Live box scores stay outside the historical log table.
"""
import asyncio
import datetime as dt
import json
import re
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx
from . import db, providers, live, covers

BOX_COLUMNS = {
    'NBA': [('minutes','MIN'),('pts','PTS'),('reb','REB'),('ast','AST'),('fg3m','3PM'),('fg3a','3PA'),('stl','STL'),('blk','BLK'),('tov','TO'),('fgm','FGM'),('fga','FGA')],
    'NFL': [('pass_yds','Passing Yards'),('pass_td','Passing TDs'),('rush_att','Rushing Attempts'),('rush_yds','Rushing Yards'),('rush_td','Rushing TDs'),('rec','Receptions'),('targets','Targets'),('rec_yds','Receiving Yards'),('rec_td','Receiving TDs')]
}
STAT_PHRASES = {
    'pass_td': ['passing touchdowns','passing tds','passing td','pass touchdowns','pass tds','pass td'],
    'rush_td': ['rushing touchdowns','rushing tds','rushing td','rush touchdowns','rush tds','rush td'],
    'rec_td': ['receiving touchdowns','receiving tds','receiving td'],
    'pass_yds':['passing yards','passing yds','pass yards','pass yds'],
    'rush_yds':['rushing yards','rushing yds','rush yards'],
    'rec_yds':['receiving yards','receiving yds','rec yards'],
    'rush_att':['rushing attempts','rush attempts','carries'],
    'rec':['receptions','catches'], 'targets':['targets'],
    'pra':['points rebounds assists','pra'], 'pr':['points rebounds'],
    'pa':['points assists'], 'ra':['rebounds assists'],
    'pts':['points','pts'], 'reb':['rebounds','reb'], 'ast':['assists','ast'],
    'fg3m':['three pointers made','3 pointers made','three pointers','3 pointers','threes','3pm'],
    'stl':['steals'], 'blk':['blocks']
}
EXTRA_ALIASES = {'NBA': {'cavs':'CLE','mavs':'DAL','sixers':'PHI','wolves':'MIN','blazers':'POR','dubs':'GS','knicks':'NY'},
                 'NFL': {'niners':'SF','49ers':'SF','bucs':'TB','pats':'NE','jags':'JAX','commanders':'WSH'}}
_box_cache = {}
_box_locks = {}


def normal(text):
    return re.sub(r'[^a-z0-9]+', ' ', unicodedata.normalize('NFKD', str(text)).encode('ascii','ignore').decode().lower()).strip()


def is_quarterback(position):
    return str(position or '').strip().upper() in ('QB','QUARTERBACK')


def opponent_code(sport, value):
    needle=normal(value)
    if not needle:return ''
    catalog=json.loads((Path(__file__).resolve().parent.parent/'static/teams/sources.json').read_text(encoding='utf-8'))
    aliases={}
    for key,item in catalog.items():
        league,code=key.split(':')
        if league!=sport:continue
        name=item['name'];parts=name.split()
        for alias in (code,name,' '.join(parts[:-1]),parts[-1]):
            aliases.setdefault(normal(alias),set()).add(db.normalize_team(sport,code))
    for alias,code in EXTRA_ALIASES.get(sport,{}).items():aliases[alias]={code}
    direct=db.normalize_team(sport,value)
    codes={db.normalize_team(sport,k.split(':')[1]) for k in catalog if k.startswith(sport+':')}
    if direct in codes:return direct
    choices=aliases.get(needle,set())
    if len(choices)!=1:raise ValueError('Choose an opponent by full team name or abbreviation (for example CLE or Dallas Cowboys).')
    return next(iter(choices))


def search_today():
    return dt.datetime.now(ZoneInfo(db.get_settings().get('timezone','America/Chicago'))).date()


def season_window(sport,scope='recent',year=None,as_of=None):
    """Use league season years, including winter games after New Year's Day."""
    today=as_of or search_today()
    month=7 if sport=='NBA' else 3
    current=today.year-(today.month<month)
    latest=year if year is not None else current-(scope=='previous')
    first=latest-1 if scope=='recent' and year is None else latest
    label=lambda y:f'{y}–{str(y+1)[-2:]}' if sport=='NBA' else str(y)
    return {'scope':scope,'label':' + '.join(label(y) for y in range(latest,first-1,-1)),
            'start':dt.date(first,month,1).isoformat(),
            'end':min(dt.date(latest+1,month,1),today+dt.timedelta(days=1)).isoformat()}


def parse_search(query, sport='auto', last=None, stat='', opponent='', season_type='regular',season_scope='auto'):
    if not query.strip() or len(query)>250:raise ValueError('Enter a player name or a search under 250 characters.')
    if sport not in ('auto','NBA','NFL'):raise ValueError('Choose NBA, NFL or Auto.')
    text=normal(re.sub(r"[’']s\b", "", query, flags=re.I))
    text=re.sub(r'\bregualr\b','regular',text)
    inferred_scope='recent' if re.search(r'\blast\s+\d+',text) else 'current';season_year=None
    if re.search(r'\b(this|current)\s+(season|year)\b|\bseason to date\b',text):
        inferred_scope='current';text=re.sub(r'\b(this|current)\s+(season|year)\b|\bseason to date\b',' ',text)
    elif re.search(r'\b(last|previous)\s+(season|year)\b',text):
        inferred_scope='previous';text=re.sub(r'\b(last|previous)\s+(season|year)\b',' ',text)
    year=re.search(r'\b(20\d{2})(?:\s+(\d{2}|20\d{2}))?\b',text)
    if year:
        season_year=int(year[1]);inferred_scope='explicit'
        if year[2] and int(year[2])%100!=(season_year+1)%100:raise ValueError('Use consecutive season years, such as 2025–26.')
        text=text[:year.start()]+' '+text[year.end():]
    if season_scope not in ('auto','recent','current','previous'):raise ValueError('Choose a valid season range.')
    scope=inferred_scope if season_scope=='auto' else season_scope
    if season_scope!='auto':season_year=None
    league=re.search(r'\b(nba|nfl)\b',text)
    if league:
        named_sport=league[1].upper()
        if sport!='auto' and sport!=named_sport:raise ValueError('Switch to '+named_sport+' to search those players.')
        sport=named_sport;text=re.sub(r'\b(nba|nfl)\b',' ',text)
    count=re.search(r'\blast\s+(\d+)\s*(?:games?|matches?)?',text)
    n=last if last is not None else int(count[1]) if count else 10
    if not 1<=n<=100:raise ValueError('Choose between 1 and 100 games.')
    if count:text=text[:count.start()]+' '+text[count.end():]
    inferred_stat=''
    for key,phrases in STAT_PHRASES.items():
        found=next((phrase for phrase in phrases if re.search(r'\b'+re.escape(phrase)+r'\b',text)),None)
        if found:
            inferred_stat=key;text=re.sub(r'\b'+re.escape(found)+r'\b',' ',text);break
    for kind in ('regular','preseason','postseason'):
        if re.search(r'\b'+kind+r'\b',text):season_type=kind;text=re.sub(r'\b'+kind+r'(?:\s+season)?\b',' ',text)
    if 'playoffs' in text:season_type='postseason';text=text.replace('playoffs',' ')
    if season_type not in ('regular','preseason','postseason','all'):raise ValueError('Choose a valid game type.')
    text=re.sub(r'\b(show|me|find|search|for|the|in|his|her|of|stats|statistics|game|games|logs|log|please|recent|and|season)\b',' ',text)
    match=re.search(r'\b(?:vs|versus|against)\s+(.+)$',text)
    inferred_opponent=' '.join(match[1].split()) if match else ''
    if match:text=text[:match.start()]
    name=' '.join(text.split())
    if not name:raise ValueError('Include the player name, such as Dak Prescott last 8 games.')
    return {'name':name,'sport':sport,'last':n,'stat':stat or inferred_stat,'opponent_text':opponent or inferred_opponent,'season_type':season_type,'season_scope':scope,'season_year':season_year}


def _public(row, sport):
    keys=['game_id','player_id','player','position','team','opponent','game_date','is_home','season_type','source','source_url','updated_at']
    out={k:row.get(k) for k in keys}
    for stat in dict(BOX_COLUMNS[sport])|db.STATS[sport]:out[stat]=db.stat_value(row,stat)
    return out


def search(query, sport='auto', last=None, stat='', opponent='', season_type='regular', player_id='',season_scope='auto',venue='all',rest='all',season_types=None):
    from . import player_splits
    filters=player_splits.conditions(query,venue,rest)
    parsed=parse_search(filters['query'],sport,last,stat,opponent,season_type,season_scope)
    if parsed['season_scope']=='current' and last is None and not re.search(r'\blast\s+\d+',query,re.I):parsed['last']=100
    with db.research_connect() as c:
        q='SELECT sport,player_id,player,position,team,game_date FROM player_search WHERE 1=1'
        args=[]
        if parsed['sport']!='auto':q+=' AND sport=?';args.append(parsed['sport'])
        if player_id:q+=' AND player_id=?';args.append(player_id)
        needle=db.player_name_key(parsed['name'])
        candidates=[dict(r) for r in c.execute(q+' AND name_key=? ORDER BY game_date DESC LIMIT 31',[*args,needle])]
        if not candidates:candidates=[dict(r) for r in c.execute(q+' AND instr(name_key,?)>0 ORDER BY game_date DESC LIMIT 31',[*args,needle])]
        if len(candidates)!=1:
            return {'status':'choose_player' if candidates else 'not_found','parsed':parsed,'candidates':candidates[:30],
                    'message':'Choose the player you mean.' if candidates else 'No saved player matches this name. Try a full name, another sport, or sync/import game results.'}
        person=candidates[0];sport=person['sport'];stat=parsed['stat']
        if stat and stat not in db.STATS[sport]:raise ValueError('That stat does not belong to '+sport+'.')
        if sport=='NFL' and stat in ('pass_yds','pass_td') and not is_quarterback(person['position']):raise ValueError('Passing stats are shown for quarterbacks only. Choose receiving or rushing stats for this player.')
        opp=opponent_code(sport,parsed['opponent_text'])
        window=season_window(sport,parsed['season_scope'],parsed['season_year'])
        sql='''SELECT p.* FROM player_logs p LEFT JOIN games g ON p.sport=g.sport AND p.game_id=g.id
               WHERE p.sport=? AND p.player_id=? AND p.game_date>=? AND p.game_date<? AND (g.id IS NULL OR g.status='final')'''
        args=[sport,person['player_id'],window['start'],window['end']]
        if season_types:
            if not set(season_types)<=set(('regular','postseason','preseason')):raise ValueError('Choose valid game types.')
            sql+=' AND p.season_type IN ('+','.join('?' for _ in season_types)+')';args.extend(season_types)
        elif parsed['season_type']!='all':sql+=' AND p.season_type=?';args.append(parsed['season_type'])
        if opp:sql+=' AND p.opponent=?';args.append(opp)
        if sport=='NBA':sql+=' AND p.minutes>0'
        if filters['venue']!='all':sql+=' AND p.is_home=?';args.append(int(filters['venue']=='home'))
        sql+=' ORDER BY p.game_date DESC,p.game_id DESC'
        if filters['rest']=='all':sql+=' LIMIT ?';args.append(parsed['last'])
        raw=[dict(r) for r in c.execute(sql,args)]
        if filters['rest']!='all':
            raw=[r for r in player_splits.add_rest_days(sport,raw) if r['rest_days']==int(filters['rest'])][:parsed['last']]
        rows=[{**_public(r,sport),'rest_days':r.get('rest_days')} for r in raw]
    keys=[stat] if stat else [key for key in dict(BOX_COLUMNS[sport]) if sport!='NFL' or is_quarterback(person['position']) or key not in ('pass_yds','pass_td')]
    summary={}
    for key in keys:
        vals=[r[key] for r in rows if r[key] is not None]
        summary[key]={'known':len(vals),'missing':len(rows)-len(vals),'total':round(sum(vals),2) if vals else None,'average':round(sum(vals)/len(vals),2) if vals else None}
    return {'status':'ok','sport':sport,'player':person,'requested':parsed['last'],'sample':len(rows),'opponent':opp,'stat':stat,'season_type':parsed['season_type'],'season_range':window,'conditions':filters,'conditions_note':player_splits.note(filters),
            'columns':[{'key':k,'label':db.STATS[sport].get(k,dict(BOX_COLUMNS[sport]).get(k,k))} for k in keys],
            'rows':rows,'summary':summary,'note':f"Seasons searched: {window['label']}. Older seasons are not included. Saved completed games, newest first. Opponent and game type are filtered before taking the last games; NBA DNPs are excluded. A dash (—) means the source did not report that stat. Totals and averages use only reported games. Use Sync Tonight’s Results for newly finished games."}


def _fill_positions(rows,sport,date):
    missing={r['player_id'] for r in rows if not r.get('position')}
    if missing:
        with db.research_connect() as c:
            sql="SELECT player_id,position FROM player_logs WHERE sport=? AND game_date<=? AND position!='' AND player_id IN ("+','.join('?' for _ in missing)+") ORDER BY game_date DESC,game_id DESC"
            positions={}
            for r in c.execute(sql,[sport,date,*missing]):positions.setdefault(r['player_id'],r['position'])
        for row in rows:
            if not row.get('position'):row['position']=positions.get(row['player_id'],'')
    from . import position_index
    return position_index.resolve(sport,rows)


def _saved_box(game):
    with db.research_connect() as c:rows=[dict(r) for r in c.execute('SELECT * FROM player_logs WHERE sport=? AND game_id=? ORDER BY team,player',(game['sport'],game['id']))]
    return _fill_positions([_public(r,game['sport']) for r in rows],game['sport'],providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago')))


async def box_score(sport,game_id,refresh=False):
    game=covers.game(sport,game_id)
    key=(str(db.database_path()),sport,game_id)
    saved=_saved_box(game) if game['status']=='final' else []
    result={'sport':sport,'game':game,'rows':saved,'live':game['status']=='live','stale':False,'fetched_at':max((r['updated_at'] or '' for r in saved),default=None),
            'source_url':f'https://www.espn.com/{sport.lower()}/boxscore/_/gameId/{game_id}','note':'Saved completed-game stats.' if saved else 'Stats will appear once the game begins.'}
    if saved and not refresh:return result
    if game['status'] not in ('live','final'):return result
    async with _box_locks.setdefault(key,asyncio.Lock()):
        old=_box_cache.get(key)
        if old and not refresh and old['game']['status']==game['status'] and live.age(old['fetched_at'])<30:return old
        try:
            if not re.fullmatch(r'\d+',game_id):raise ValueError('No ESPN game identifier')
            url=f'{providers.BASE}/{providers.SPORT_PATH[sport]}/summary?event={game_id}'
            async with httpx.AsyncClient(headers={'User-Agent':providers.USER_AGENT}) as client:payload=await providers.fetch_json(client,url)
            if str(payload.get('header',{}).get('id',''))!=game_id:raise ValueError('Box score identity mismatch')
            parser=providers.nba_player_logs if sport=='NBA' else providers.nfl_player_logs
            game={**game,'game_date':providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago'))}
            rows=parser(payload,game)
            for r in rows:
                r['team']=db.normalize_team(sport,r['team']);r['opponent']=db.normalize_team(sport,r['opponent'])
            if any(r['team'] not in (game['home_abbr'],game['away_abbr']) for r in rows):raise ValueError('Box score teams mismatch')
            stamp=live.now().isoformat()
            result.update(rows=_fill_positions([_public({**r,'updated_at':stamp},sport) for r in rows],sport,game['game_date']),fetched_at=stamp,
                          note='Live stats can change. These are kept separate from saved completed-game history.' if result['live'] else 'Final-game stats from ESPN. Sync results to include them in saved history.')
            _box_cache[key]=result
            # Keep this cache bounded; historical logs remain in SQLite.
            if len(_box_cache)>128:_box_cache.pop(next(iter(_box_cache)))
            return result
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            fallback=old or result
            return {**fallback,'stale':True,'error':'Could not refresh this box score. Showing the last available stats.' if fallback['rows'] else 'This box score is not available from the source yet. Try Refresh Box Score.'}


async def leaders(sport, date, stat, refresh=False):
    if sport not in db.STATS or stat not in db.STATS[sport]:raise ValueError('Choose a stat for this sport.')
    dt.date.fromisoformat(date)
    board=await live.scoreboard(sport,date,force=refresh)
    games=board['games'];active=[g for g in games if g['status'] in ('live','final')]
    semaphore=asyncio.Semaphore(4)
    async def get(game):
        async with semaphore:return await box_score(sport,game['id'],refresh)
    boxes=await asyncio.gather(*(get(g) for g in active))
    rows=[];issues=[];covered=0
    for box in boxes:
        if box.get('error'):issues.append({'game_id':box['game']['id'],'message':box['error']})
        if box['rows']:covered+=1
        for r in box['rows']:
            value=db.stat_value(r,stat)
            if value is None:continue
            rows.append({**r,'value':value,'status':box['game']['status'],'stale':box['stale'],'fetched_at':box['fetched_at']})
    if sport=='NFL' and stat in ('pass_yds','pass_td'):
        rows=[r for r in _fill_positions(rows,sport,date) if is_quarterback(r['position'])]
    rows.sort(key=lambda r:(-r['value'],r['player']))
    previous=None;rank=0
    for i,r in enumerate(rows):
        if r['value']!=previous:rank=i+1
        r['rank']=rank;previous=r['value']
    return {'sport':sport,'date':date,'stat':stat,'label':db.STATS[sport][stat],'rows':rows[:100],
            'games':len(games),'completed_games':sum(g['status']=='final' for g in games),'live_games':sum(g['status']=='live' for g in games),
            'covered_games':covered,'started_games':len(active),'issues':issues,'stale':board.get('stale',False),'fetched_at':live.now().isoformat(),
            'source_url':board.get('source_url'),'note':'Daily leaders across the selected date, including live games. Live totals are unfinished. Missing box scores are excluded, not counted as zero.'}


def historical_leaders(sport, window, stat, as_of, season_type='regular',include_previous=False):
    """Completed-game leaders; take each player's played-game window before checking missing stats."""
    allowed={'NBA':{'last5':5,'last10':10},'NFL':{'last3':3,'last_week':None}}
    if sport not in allowed or window not in allowed[sport]:raise ValueError('Choose a leaders tab for the selected sport.')
    if stat not in db.STATS[sport]:raise ValueError('Choose a stat for this sport.')
    if season_type not in ('regular','postseason','preseason'):raise ValueError('Choose a game type.')
    today=dt.date.fromisoformat(as_of)
    scope=season_window(sport,'recent' if include_previous else 'current',as_of=today)
    requested=allowed[sport][window]
    start=end=None
    if window=='last_week':
        end=today-dt.timedelta(days=today.weekday()+1)
        start=end-dt.timedelta(days=6)
    with db.research_connect() as c:
        where="p.sport=? AND p.season_type=? AND p.game_date<=? AND p.game_date>=? AND (g.id IS NULL OR g.status='final')"
        args=[sport,season_type,as_of,scope['start']]
        if sport=='NBA':where+=' AND p.minutes>0'
        if start:where+=' AND p.game_date>=? AND p.game_date<=?';args.extend([start.isoformat(),end.isoformat()])
        base='SELECT p.* FROM player_logs p LEFT JOIN games g ON p.sport=g.sport AND p.game_id=g.id WHERE '+where
        if requested:
            sql='SELECT * FROM (SELECT matched.*, ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY game_date DESC,game_id DESC) AS played_number FROM ('+base+') matched) WHERE played_number<=? ORDER BY game_date DESC,game_id DESC'
            rows=[dict(r) for r in c.execute(sql,[*args,requested])]
        else:rows=[dict(r) for r in c.execute(base+' ORDER BY p.game_date DESC,p.game_id DESC',args)]
    latest=max((r['game_date'] for r in rows),default=None)
    active_after=(dt.date.fromisoformat(latest)-dt.timedelta(days=30 if sport=='NBA' else 35)).isoformat() if latest else None
    groups={}
    for row in rows:groups.setdefault(row['player_id'],[]).append(row)
    output=[];short=missing=inactive=0
    for sample in groups.values():
        if requested and sample[0]['game_date']<active_after:inactive+=1;continue
        if requested and len(sample)!=requested:short+=1
        values=[db.stat_value(r,stat) for r in sample]
        if any(v is None for v in values):missing+=1;continue
        total=sum(values);average=total/len(values)
        current=_public(sample[0],sport)
        output.append({**current,'sport':sport,'sample':len(sample),'requested':requested,'total':round(total,2),'average':round(average,2),
                       'value':average if requested else total,'first_game':sample[-1]['game_date'],'last_game':sample[0]['game_date'],
                       'status':'final','stale':False,'fetched_at':sample[0]['updated_at']})
    if sport=='NFL' and stat in ('pass_yds','pass_td'):
        output=[r for r in _fill_positions(output,sport,as_of) if is_quarterback(r['position'])]
    output.sort(key=lambda r:(-r['value'],r['player']))
    previous=None;rank=0
    for i,row in enumerate(output):
        if row['value']!=previous:rank=i+1
        row['rank']=rank;previous=row['value']
        row['value']=round(row['value'],2)
    output=_fill_positions(output[:100],sport,as_of)
    title=f'Last {requested} Games' if requested else 'Last Week'
    return {'sport':sport,'window':window,'date':as_of,'stat':stat,'label':db.STATS[sport][stat],'title':title,'rows':output,
            'season_type':season_type,'requested':requested,'ranking':'average' if requested else 'total','season_range':scope,'include_previous':include_previous,
            'range_start':start.isoformat() if start else None,'range_end':end.isoformat() if end else None,'latest_game':latest,
            'excluded_short_samples':short,'excluded_missing_stats':missing,'excluded_inactive':inactive,
            'fetched_at':live.now().isoformat(),'issues':[],'stale':False,
            'note':f"Up to {requested} completed {season_type} games per player, ranked by average. Games shown use {scope['label']}; shorter season samples remain visible. NBA games without playing time are excluded. Players must have played within {30 if sport=='NBA' else 35} days of the latest saved league game. Unreported selected stats are excluded." if requested else f'Previous Monday–Sunday, completed {season_type} games only, ranked by total. Games played are shown; players with missing selected stats are excluded. Based on saved results; sync to add newly finished games.'}

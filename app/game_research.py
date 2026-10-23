"""Selected-game players and current-season history; never invent absent games/odds."""
import asyncio,datetime as dt,time
import httpx
from . import db,covers,providers,stat_logs,props,markets

_rosters={}
NBA=[('pts','PTS'),('reb','REB'),('ast','AST'),('fg3m','3PM'),('stl','STL'),('blk','BLK'),('minutes','MIN'),('tov','TO'),('fga','FGA')]
def columns(sport,position):
    if sport=='NBA':return NBA
    p=str(position or '').upper()
    if p in ('QB','QUARTERBACK'):return [('pass_yds','Passing yards'),('pass_td','Passing TDs')]
    if p in ('RB','FB','RUNNING BACK','FULLBACK'):return [('rush_yds','Rushing yards'),('rush_td','Rushing TDs')]
    if p in ('WR','TE','WIDE RECEIVER','TIGHT END'):return [('rec_yds','Receiving yards'),('targets','Targets'),('rec_td','Receiving TDs'),('rec','Receptions')]
    return [('rec_yds','Receiving yards'),('rush_yds','Rushing yards'),('rec_td','Receiving TDs'),('rush_td','Rushing TDs')]

async def roster(sport,team_id,team):
    key=(sport,str(team_id));old=_rosters.get(key)
    if old and time.monotonic()-old[0]<600:return old[1]
    if not str(team_id).isdigit():raise ValueError('Team roster identifier unavailable')
    url=f'{providers.BASE}/{providers.SPORT_PATH[sport]}/teams/{team_id}/roster'
    async with httpx.AsyncClient(timeout=12,headers={'User-Agent':providers.USER_AGENT}) as client:
        payload=await providers.fetch_json(client,url)
    items=[]
    for group in payload.get('athletes',[]):items.extend(group.get('items',[group]))
    result=[{'player_id':str(p['id']),'player':p.get('displayName') or p.get('fullName'),
        'position':p.get('position',{}).get('abbreviation',''),'team':team}
        for p in items if p.get('id') and (p.get('displayName') or p.get('fullName'))]
    if not result:raise ValueError('No roster returned')
    _rosters[key]=(time.monotonic(),result)
    if len(_rosters)>64:_rosters.pop(next(iter(_rosters)))
    return result

async def overview(sport,game_id):
    game=covers.game(sport,game_id)
    date=providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago'))
    window=stat_logs.season_window(sport,'current',as_of=dt.date.fromisoformat(date))
    with db.connect() as c:
        logs=[dict(r) for r in c.execute('SELECT * FROM player_logs WHERE sport=? AND game_date>=? AND game_date<=? AND season_type=? ORDER BY game_date DESC,game_id DESC',(sport,window['start'],date,'regular'))]
    box=await stat_logs.box_score(sport,game_id) if game['status'] in ('live','final') else {'rows':[]}
    if game['status']=='final' and game['season_type']=='regular':
        saved={(str(r['player_id']),str(r['game_id'])) for r in logs}
        completed=[dict(r,game_id=game_id,game_date=date) for r in box['rows'] if (str(r['player_id']),game_id) not in saved]
        logs=completed+logs
    players={str(r['player_id']):dict(r) for r in box['rows']}
    issues=[];roster_note='Players recorded in this game’s box score.'
    if game['status']=='scheduled' and date>=stat_logs.search_today().isoformat():
        replies=await asyncio.gather(*(roster(sport,game[side+'_id'],game[side+'_abbr']) for side in ('away','home')),return_exceptions=True)
        for side,reply in zip(('away','home'),replies):
            if isinstance(reply,Exception):issues.append('Could not update '+game[side+'_abbr']+' roster.')
            else:players.update((p['player_id'],p) for p in reply)
        roster_note='ESPN roster; being listed does not confirm that a player will play.'
    # Use latest saved team only when the source roster/box score is unavailable.
    latest={}
    for row in logs:latest.setdefault(str(row['player_id']),row)
    covered={r['team'] for r in players.values()}
    for pid,row in latest.items():
        if row['team'] in (game['home_abbr'],game['away_abbr']) and row['team'] not in covered:players.setdefault(pid,dict(row))
    if any('roster' in s for s in issues) or not box['rows'] and game['status']!='scheduled':roster_note+=' Missing source teams use latest saved players; this may be incomplete.'
    grouped={}
    for row in logs:
        if sport=='NBA' and not (row.get('minutes') or 0)>0:continue
        grouped.setdefault(str(row['player_id']),[]).append(row)
    current={str(r['player_id']):r for r in box['rows']}
    result=[]
    for pid,person in players.items():
        if sport=='NFL' and str(person.get('position','')).upper() not in ('QB','QUARTERBACK','RB','FB','RUNNING BACK','FULLBACK','WR','TE','WIDE RECEIVER','TIGHT END'):
            if not any(person.get(k) for k in ('rec_yds','rush_yds','rec_td','rush_td')):continue
        history=grouped.get(pid,[]);cols=columns(sport,person.get('position'))
        averages={}
        for key,_ in cols:
            values=[r[key] for r in history if r.get(key) is not None]
            averages[key]=round(sum(values)/len(values),1) if values else None
        result.append({k:person.get(k,'') for k in ('player_id','player','team','position')}|{'games':len(history),'averages':averages,'current':current.get(pid),'columns':cols})
    result.sort(key=lambda p:(p['team'],-(p['averages'].get('pts') or p['averages'].get('pass_yds') or p['averages'].get('rec_yds') or p['averages'].get('rush_yds') or 0),p['player']))
    return {'game':game,'players':result,'season':window['label'],'window':window,'roster_note':roster_note,'issues':issues}

async def player(sport,game_id,player_id):
    context=await overview(sport,game_id)
    person=next((p for p in context['players'] if str(p['player_id'])==str(player_id)),None)
    if not person:raise ValueError('This player is not listed for the selected game. Refresh the game’s players.')
    game=context['game'];date=providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago'))
    sql='SELECT * FROM player_logs WHERE sport=? AND player_id=? AND season_type=? AND game_date>=? AND game_date<=?'
    if sport=='NBA':sql+=' AND minutes>0'
    with db.connect() as c:
        rows=[dict(r) for r in c.execute(sql+' ORDER BY game_date DESC,game_id DESC LIMIT 5',(sport,player_id,'regular',context['window']['start'],date))]
        quotes=[dict(r) for r in c.execute('SELECT * FROM player_prop_quotes WHERE sport=? AND game_id=? ORDER BY stat,book,side,line',(sport,game_id)) if props.name_key(r['player'])==props.name_key(person['player'])]
    # A just-finished ESPN box score may be available before the next saved sync.
    current=person['current']
    if game['status']=='final' and game['season_type']=='regular' and current and (sport!='NBA' or (current.get('minutes') or 0)>0) and not any(r['game_id']==game_id for r in rows):
        rows=[dict(current,game_id=game_id,game_date=date,is_home=person['team']==game['home_abbr'],opponent=game['away_abbr'] if person['team']==game['home_abbr'] else game['home_abbr']),*rows][:5]
    return {'game':game,'player':person,'season':context['season'],'rows':rows,'requested':5,
        'quotes':quotes,'feed_configured':bool(markets.get_key()),'issues':context['issues']}

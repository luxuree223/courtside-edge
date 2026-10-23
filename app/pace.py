"""Published NBA.com advanced team statistics. Never derive a substitute pace."""
import asyncio, datetime as dt, json, math, time
import httpx
from . import db, research_index

ENDPOINT='https://stats.nba.com/stats/leaguedashteamstats'
SOURCE='https://www.nba.com/stats/teams/advanced'
_locks={}

def parse(payload):
    sets=payload.get('resultSets',[])
    table=next((s for s in sets if s.get('name')=='LeagueDashTeamStats'),None)
    if not table or not {'TEAM_NAME','PACE','GP','OFF_RATING','DEF_RATING'}<=set(table.get('headers',[])):
        raise ValueError('NBA pace data is unavailable.')
    names=research_index.catalog('NBA'); lookup={v:k for k,v in names.items()};lookup['LA Clippers']='LAC'
    rows=[]
    for values in table.get('rowSet',[]):
        r=dict(zip(table['headers'],values));code=lookup.get(r.get('TEAM_NAME'))
        if not code:continue
        def number(key):
            value=r.get(key)
            return value if isinstance(value,(int,float)) and math.isfinite(value) else None
        rows.append(dict(team=code,name=names[code],pace=number('PACE') if (number('GP') or 0)>0 else None,games=number('GP'),offense=number('OFF_RATING'),defense=number('DEF_RATING')))
    if not rows:raise ValueError('NBA has not published pace for this selection yet.')
    rows.sort(key=lambda r:(r['pace'] is None,-(r['pace'] or 0),r['name']))
    previous=None;rank=0
    for i,r in enumerate(rows):
        if r['pace']!=previous:rank=i+1
        r['rank']=rank if r['pace'] is not None else None;previous=r['pace']
    return rows

async def rankings(season=None,season_type='regular',last=None,refresh=False):
    if season_type not in ('regular','postseason'):raise ValueError('Choose regular season or playoffs.')
    w=research_index.window('NBA',season,season_type);year=int(w['start'][:4])+1
    if last is not None and not 1<=last<=100:raise ValueError('Choose 1-100 recent games.')
    season_label=f'{year-1}-{str(year)[-2:]}'
    key=f'{year}-{season_type}-{last or 0}'
    path=db.DB_PATH.parent/'public-pace'/f'{key}.json'
    async with _locks.setdefault(key,asyncio.Lock()):
        cached=None
        try:cached=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
        if cached and not refresh and time.time()-cached['fetched_epoch']<3600:return cached
        params=dict(LastNGames=last or 0,LeagueID='00',MeasureType='Advanced',Month=0,OpponentTeamID=0,PaceAdjust='N',PerMode='PerGame',Period=0,PlusMinus='N',Rank='N',Season=season_label,SeasonType='Regular Season' if season_type=='regular' else 'Playoffs',TeamID=0)
        try:
            async with httpx.AsyncClient(timeout=25,follow_redirects=True,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.nba.com/'}) as client:
                response=await client.get(ENDPOINT,params=params);response.raise_for_status();payload=response.json()
            if payload.get('parameters',{}).get('Season')!=season_label:raise ValueError('NBA returned a different season.')
            rows=parse(payload)
            result=dict(sport='NBA',window=w,last=last,rows=rows,ranked_teams=sum(r['pace'] is not None for r in rows),source='NBA.com',source_url=SOURCE+'?Season='+season_label,fetched_epoch=time.time(),updated_at=dt.datetime.now(dt.timezone.utc).isoformat(),stale=False)
            path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(result),encoding='utf-8');temporary.replace(path)
            return result
        except (httpx.HTTPError,ValueError,KeyError):
            if cached:return dict(cached,stale=True,warning='NBA.com is unavailable. Showing the last published values retrieved for this selection.')
            raise ValueError('NBA.com pace is temporarily unavailable. Please try again shortly.')

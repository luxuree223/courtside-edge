"""Published NBA.com advanced team statistics. Never derive a substitute pace."""
import asyncio, datetime as dt, json, math, time
from pathlib import Path
import httpx, re, hashlib
from bs4 import BeautifulSoup
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

def parse_hollinger(html,year):
    soup=BeautifulSoup(html,'html.parser')
    heading=soup.find('h1')
    if not heading or f'{year-1}-{year}' not in heading.get_text():raise ValueError('Hollinger returned a different season.')
    names=research_index.catalog('NBA');rows=[]
    table=next((t for t in soup.find_all('table') if 'PACE' in t.get_text() and 'OFF EFF' in t.get_text()),None)
    if not table:raise ValueError('Hollinger pace is unavailable.')
    headers=None
    for tr in table.find_all('tr'):
        cells=tr.find_all(['td','th']);texts=[c.get_text(' ',strip=True) for c in cells]
        if 'PACE' in texts and 'TEAM' in texts:headers=texts;continue
        link=tr.find('a',href=re.compile(r'/nba/team/_/name/'))
        if not headers or not link or len(cells)!=len(headers):continue
        match=re.search(r'/name/([^/]+)',link['href']);code=db.normalize_team('NBA',match[1].upper())
        if code not in names:continue
        values=dict(zip(headers,texts))
        def value(key):
            try:
                n=float(values[key]);return n if math.isfinite(n) else None
            except (KeyError,ValueError):return None
        rows.append(dict(team=code,name=names[code],pace=value('PACE'),games=None,offense=value('OFF EFF'),defense=value('DEF EFF')))
    if not rows:raise ValueError('Hollinger has not published this season yet.')
    rows.sort(key=lambda r:(r['pace'] is None,-(r['pace'] or 0),r['name']))
    previous=None;rank=0
    for i,row in enumerate(rows):
        if row['pace']!=previous:rank=i+1
        row['rank']=rank if row['pace'] is not None else None;previous=row['pace']
    return rows

async def sync():
    results=await asyncio.gather(*(rankings(refresh=True,source=s) for s in ('nba','hollinger')),return_exceptions=True)
    return [str(r) if isinstance(r,Exception) else r.get('warning','') for r in results if isinstance(r,Exception) or r.get('stale')]

async def rankings(season=None,season_type='regular',last=None,refresh=False,source='nba'):
    if source not in ('nba','hollinger'):raise ValueError('Choose NBA.com or Hollinger.')
    if source=='hollinger' and (season_type!='regular' or last):raise ValueError('Hollinger publishes full regular-season team stats only.')
    if season_type not in ('regular','postseason'):raise ValueError('Choose regular season or playoffs.')
    w=research_index.window('NBA',season,season_type);year=int(w['start'][:4])+1
    if last is not None and not 1<=last<=100:raise ValueError('Choose 1-100 recent games.')
    season_label=f'{year-1}-{str(year)[-2:]}'
    key=f'{source}-{year}-{season_type}-{last or 0}'
    source_name='NBA.com' if source=='nba' else 'ESPN Hollinger'
    source_url=SOURCE+'?Season='+season_label if source=='nba' else f'https://www.espn.com/nba/hollinger/teamstats/_/year/{year}'
    path=db.DB_PATH.parent/'public-pace'/f'{key}.json'
    async with _locks.setdefault(key,asyncio.Lock()):
        cached=None;bundled=False
        try:cached=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
        if not cached and season_type=='regular' and not last:
            try:
                cached=json.loads((Path(__file__).resolve().parents[1]/'static'/'teams'/f'pace-{source}-{year}-regular.json').read_text(encoding='utf-8'));bundled=True
            except (OSError,ValueError):pass
        if bundled and not refresh:return dict(cached,stale=True,warning='Showing the dated '+source_name+' snapshot. Use Sync Pace to check for newer published values.')
        if cached and not bundled and not refresh and time.time()-cached['fetched_epoch']<3600:return cached
        params=dict(LastNGames=last or 0,LeagueID='00',MeasureType='Advanced',Month=0,OpponentTeamID=0,PaceAdjust='N',PerMode='PerGame',Period=0,PlusMinus='N',Rank='N',Season=season_label,SeasonType='Regular Season' if season_type=='regular' else 'Playoffs',TeamID=0)
        try:
            async with httpx.AsyncClient(timeout=25,follow_redirects=True,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.nba.com/'}) as client:
                response=await client.get(ENDPOINT,params=params) if source=='nba' else await client.get(source_url)
                response.raise_for_status()
            if source=='nba':
                payload=response.json()
                if payload.get('parameters',{}).get('Season')!=season_label:raise ValueError('NBA returned a different season.')
                rows=parse(payload)
            else:rows=parse_hollinger(response.text,year)
            result=dict(sport='NBA',window=w,last=last,rows=rows,ranked_teams=sum(r['pace'] is not None for r in rows),source=source_name,source_id=source,source_url=source_url,fetched_epoch=time.time(),updated_at=dt.datetime.now(dt.timezone.utc).isoformat(),stale=False,
                import_method='Published NBA stats response' if source=='nba' else 'Published Hollinger website table',source_sha256=hashlib.sha256(response.content).hexdigest())
            # Keep the exact public source response alongside its parsed table so
            # every imported value can be checked against what the source supplied.
            path.parent.mkdir(parents=True,exist_ok=True)
            raw=path.with_suffix('.source.json' if source=='nba' else '.source.html')
            raw.write_bytes(response.content)
            path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(result),encoding='utf-8');temporary.replace(path)
            return result
        except (httpx.HTTPError,ValueError,KeyError):
            if cached:return dict(cached,stale=True,warning=source_name+' is unavailable. Showing the last published values retrieved for this selection.')
            raise ValueError(source_name+' pace is temporarily unavailable. Please try again shortly.')

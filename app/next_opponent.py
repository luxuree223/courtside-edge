"""Resolve a team's actual next scheduled game beyond the daily picker window."""
import asyncio
import datetime as dt
import json
import httpx
from . import db,providers,live,research_index,stat_logs
_locks={}

async def lookup(sport,team,force=False):
    if sport not in ('NBA','NFL'):raise ValueError('Choose NBA or NFL.')
    team=db.normalize_team(sport,team)
    if team not in research_index.catalog(sport):raise ValueError('Choose a league team.')
    async with _locks.setdefault((sport,team),asyncio.Lock()):
        with db.connect() as c:row=c.execute('SELECT payload FROM next_team_schedule WHERE sport=? AND team=?',(sport,team)).fetchone()
        old=json.loads(row[0]) if row else None
        ttl=30 if old and (old.get('game') or {}).get('status')=='live' else 1800
        if old and not force and live.age(old['fetched_at'])<ttl:
            game=old.get('game')
            if not game or game['status']=='live' or dt.datetime.fromisoformat(game['starts_at'].replace('Z','+00:00'))>live.now():return old
        year=int(stat_logs.season_window(sport,'current')['start'][:4])+(sport=='NBA')
        url=f'{providers.BASE}/{providers.SPORT_PATH[sport]}/teams/{team.lower()}/schedule'
        try:
            async with httpx.AsyncClient(headers={'User-Agent':providers.USER_AGENT},timeout=20) as client:
                selected=None
                for season in (year,year+1):
                    games=[]
                    # The next scheduled game may be preseason or a playoff game.
                    # Check every category before advancing to the next season.
                    for kind in (2,1,3):
                        payload=await providers.fetch_json(client,url+f'?season={season}&seasontype={kind}')
                        events=payload.get('events')
                        if not isinstance(events,list):raise ValueError('No schedule returned')
                        if isinstance(payload.get('team'),dict) and db.normalize_team(sport,payload['team'].get('abbreviation',''))!=team:raise ValueError('Schedule team mismatch')
                        for event in events:
                            if not event.get('status') and event.get('competitions'):event['status']=event['competitions'][0].get('status',{})
                            if not event.get('season'):event['season']={'type':kind}
                        games.extend(providers.parse_scoreboard(payload,sport))
                    candidates=[]
                    for g in games:
                        for field in ('home_abbr','away_abbr'):g[field]=db.normalize_team(sport,g[field])
                        if team not in (g['home_abbr'],g['away_abbr']) or g['status']=='final':continue
                        begins=dt.datetime.fromisoformat(g['starts_at'].replace('Z','+00:00'))
                        if begins.tzinfo is None:begins=begins.replace(tzinfo=dt.timezone.utc)
                        if g['status']=='live' or begins>=live.now():candidates.append(g)
                    if candidates:
                        selected=min(candidates,key=lambda g:dt.datetime.fromisoformat(g['starts_at'].replace('Z','+00:00')));break
            result={'sport':sport,'team':team,'game':selected,'fetched_at':live.now().isoformat(),'source_url':url,'stale':False}
            with db.connect() as c:
                if selected:db.save_game(c,selected)
                c.execute('INSERT INTO next_team_schedule VALUES (?,?,?) ON CONFLICT(sport,team) DO UPDATE SET payload=excluded.payload',(sport,team,json.dumps(result)))
            return result
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            return {**(old or {'sport':sport,'team':team,'game':None,'source_url':url}),'stale':True,'error':'The next game could not be verified from the team schedule. Retry the schedule lookup.'}

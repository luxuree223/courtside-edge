"""Sourced roster/depth-chart positions, separate from historical game evidence."""
import asyncio, datetime as dt
import httpx
from . import db, providers

SCHEMA='''CREATE TABLE IF NOT EXISTS player_positions (
 sport TEXT,player_id TEXT,team TEXT,position TEXT,source_url TEXT,observed_at TEXT,
 PRIMARY KEY(sport,player_id,team));'''

def ensure(c,sport=None):
    c.execute(SCHEMA)
    from . import primary_positions
    if sport=='NBA':primary_positions.seed_snapshot(c)

def depth_positions(payload):
    found={}
    for chart in payload.get('depthchart',[]):
        for key,slot in chart.get('positions',{}).items():
            pos=key.upper()
            if pos not in ('PG','SG','SF','PF','C'):continue
            for p in slot.get('athletes',[]):
                if p.get('id'):found.setdefault(str(p['id']),[]).append(pos)
    # A player can be listed at several spots. Keep every verified label.
    return {pid:'/'.join(dict.fromkeys(values)) for pid,values in found.items()}

async def refresh(sport,teams=None):
    with db.research_connect() as c:
        ensure(c,sport)
        if teams is None:
            teams={str(r[0]):r[1] for r in c.execute('SELECT home_id,home_abbr FROM games WHERE sport=? UNION SELECT away_id,away_abbr FROM games WHERE sport=?',(sport,sport)) if str(r[0]).isdigit()}
    limit=asyncio.Semaphore(5);issues=[];count=0
    async with httpx.AsyncClient(timeout=18,headers={'User-Agent':providers.USER_AGENT}) as client:
        async def team(tid,abbr):
            nonlocal count
            async with limit:
                base=f'{providers.BASE}/{providers.SPORT_PATH[sport]}/teams/{tid}'
                try:
                    roster=await providers.fetch_json(client,base+'/roster');items=[]
                    for group in roster.get('athletes',[]):items.extend(group.get('items',[group]))
                    precise={};primary_url=''
                    if sport=='NBA':
                        from . import primary_positions
                        code=db.normalize_team(sport,abbr)
                        with db.research_connect() as c:
                            ensure(c,sport);cached={r['player_id']:dict(r) for r in c.execute("SELECT * FROM player_positions WHERE sport='NBA' AND team=?",(code,))}
                        cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=1)).isoformat()
                        needs=[p for p in items if str(p.get('id','')) not in cached or cached[str(p.get('id',''))]['observed_at']<cutoff]
                        if needs:
                            primary_url=primary_positions.secondary_roster_url(code)
                            try:
                                response=await client.get(primary_url);response.raise_for_status()
                                precise=primary_positions.parse_secondary_roster(response.text,primary_positions.season())
                            except Exception:issues.append(abbr+': primary-position source unavailable; using verified cached positions')
                    stamp=dt.datetime.now(dt.timezone.utc).isoformat();rows=[]
                    for p in items:
                        pid=str(p.get('id',''))
                        if sport=='NBA':
                            # Retain a fresh verified primary assignment. Secondary
                            # roster pages fill missing/stale records, never depth roles.
                            prior=cached.get(pid)
                            if prior and prior['observed_at']>=cutoff:continue
                            pos=precise.get(primary_positions.name_key(p.get('displayName',''))) or precise.get(primary_positions.name_key(p.get('fullName','')))
                            source=primary_url
                            if not pos and not prior:issues.append(abbr+': primary position unverified for '+p.get('displayName',pid))
                        else:pos=(p.get('position') or {}).get('abbreviation','');source=base+'/roster'
                        if pid and pos:rows.append((sport,pid,db.normalize_team(sport,abbr),pos,source,stamp))
                    with db.research_connect() as c:
                        ensure(c,sport);c.executemany('INSERT OR REPLACE INTO player_positions VALUES (?,?,?,?,?,?)',rows)
                        # Search catalogue metadata is current; historical box rows stay intact.
                        year=dt.date.today().year-(dt.date.today().month<(7 if sport=='NBA' else 3))
                        for _,pid,code,pos,_,_ in rows:
                            c.execute("UPDATE player_search SET position=? WHERE sport=? AND player_id=? AND team=?",(pos,sport,pid,code))
                    count+=len(rows)
                except Exception:issues.append(abbr+': roster unavailable')
        await asyncio.gather(*(team(tid,abbr) for tid,abbr in teams.items()))
    return {'players':count,'issues':issues}

def resolve(sport,people):
    with db.research_connect() as c:
        ensure(c,sport);indexed={(r['player_id'],r['team']):dict(r) for r in c.execute('SELECT * FROM player_positions WHERE sport=?',(sport,))}
    for p in people:
        item=indexed.get((str(p['player_id']),db.normalize_team(sport,p['team'])))
        current=dt.date.today();year=current.year-(current.month<(7 if sport=='NBA' else 3))
        start=f'{year}-{7 if sport=="NBA" else 3:02d}-01'
        if p.get('game_date') and p['game_date']<start:continue
        if item and (sport=='NBA' or not p.get('position') or p['position'] in ('G','F')):
            p['position']=item['position'];p['position_source_url']=item['source_url'];p['position_observed_at']=item['observed_at']
    return people

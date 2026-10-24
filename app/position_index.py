"""Sourced roster/depth-chart positions, separate from historical game evidence."""
import asyncio, datetime as dt
import httpx
from . import db, providers

SCHEMA='''CREATE TABLE IF NOT EXISTS player_positions (
 sport TEXT,player_id TEXT,team TEXT,position TEXT,source_url TEXT,observed_at TEXT,
 PRIMARY KEY(sport,player_id,team));'''

def ensure(c,sport=None):
    c.execute(SCHEMA)
    c.execute('''CREATE TABLE IF NOT EXISTS position_proposals (
      sport TEXT,player_id TEXT,team TEXT,position TEXT,source_url TEXT,observed_at TEXT,
      PRIMARY KEY(sport,player_id,team));''')
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
    from .research_index import catalog
    league_teams=catalog(sport)
    with db.research_connect() as c:
        ensure(c,sport)
        if teams is None:
            teams={str(r[0]):r[1] for r in c.execute('SELECT home_id,home_abbr FROM games WHERE sport=? UNION SELECT away_id,away_abbr FROM games WHERE sport=?',(sport,sport)) if str(r[0]).isdigit()}
        teams={tid:abbr for tid,abbr in teams.items() if db.normalize_team(sport,abbr) in league_teams}
        # A transfer does not erase a verified primary position. Conflicting
        # published assignments still require the new team's roster to resolve.
        by_player={}
        for row in c.execute('SELECT * FROM player_positions WHERE sport=? ORDER BY observed_at DESC',(sport,)):
            by_player.setdefault(row['player_id'],[]).append(dict(row))
        fallback={pid:rows[0] for pid,rows in by_player.items() if len({r['position'] for r in rows})==1}
    limit=asyncio.Semaphore(5);profile_limit=asyncio.Semaphore(1);issues=[];count=0
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
                            except Exception:pass  # Keep sourced cached records; report only actual gaps below.
                    stamp=dt.datetime.now(dt.timezone.utc).isoformat();rows=[]
                    for p in items:
                        pid=str(p.get('id',''))
                        if sport=='NBA':
                            # Retain a fresh verified primary assignment. Secondary
                            # roster pages fill missing/stale records, never depth roles.
                            prior=cached.get(pid) or fallback.get(pid)
                            if prior and pid not in cached:
                                rows.append((sport,pid,code,prior['position'],prior['source_url'],prior['observed_at']))
                            pos=precise.get(primary_positions.name_key(p.get('displayName',''))) or precise.get(primary_positions.name_key(p.get('fullName','')))
                            source=primary_url
                            if prior:
                                # Never change the research classification just because
                                # a second roster feed describes a different role today.
                                if pos and pos!=prior['position']:
                                    with db.research_connect() as c:
                                        c.execute('INSERT OR REPLACE INTO position_proposals VALUES (?,?,?,?,?,?)',(sport,pid,code,pos,source,stamp))
                                continue
                            if not prior:
                                async with profile_limit:
                                    profile=await primary_positions.lookup_profile(client,p.get('displayName') or p.get('fullName',''))
                                # A generic G/F, a depth-chart slot or an unsupported
                                # secondary-feed label cannot establish a primary role.
                                pos=profile['position'] if profile else None
                                if profile:source=profile['source_url']
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
    by_player={}
    for item in indexed.values():by_player.setdefault(item['player_id'],[]).append(item)
    for p in people:
        item=indexed.get((str(p['player_id']),db.normalize_team(sport,p['team'])))
        if item is None and sport=='NBA':
            candidates=by_player.get(str(p['player_id']),[])
            if candidates and len({r['position'] for r in candidates})==1:
                item=max(candidates,key=lambda r:r['observed_at'])
        current=dt.date.today();year=current.year-(current.month<(7 if sport=='NBA' else 3))
        start=f'{year}-{7 if sport=="NBA" else 3:02d}-01'
        if p.get('game_date') and p['game_date']<start:continue
        if item and (sport=='NBA' or not p.get('position') or p['position'] in ('G','F')):
            p['position']=item['position'];p['position_source_url']=item['source_url'];p['position_observed_at']=item['observed_at']
        elif sport=='NBA':
            # Even an exact-looking box-score PG/SG label is not a verified primary
            # assignment. Missing evidence must never flow into position averages.
            raw=str(p.get('position') or '').upper()
            p['position_family']='G' if raw in ('G','PG','SG') else 'F' if raw in ('F','SF','PF') else None
            p['position']='';p['position_unverified']=True
    return people


def directory(position=None):
    """Auditable public assignments, including the source of each selected label."""
    import json
    from pathlib import Path
    from . import primary_positions
    path=Path(__file__).resolve().parents[1]/'static/teams'/f'primary-positions-{primary_positions.season()}.json'
    snapshot=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'players':[]}
    names={str(p['player_id']):p.get('name') for p in snapshot['players']}
    with db.research_connect() as c:
        ensure(c,'NBA')
        rows=[dict(r) for r in c.execute("SELECT * FROM player_positions WHERE sport='NBA' AND position IN ('PG','SG','SF','PF','C') ORDER BY team,player_id")]
        for r in c.execute("SELECT player_id,max(player) name FROM player_search WHERE sport='NBA' GROUP BY player_id"):
            names[r['player_id']]=names.get(r['player_id']) or r['name']
    return [{**r,'name':names.get(r['player_id']) or 'Player '+r['player_id']} for r in rows if not position or r['position']==position]

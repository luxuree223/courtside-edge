"""Confirmed NBA starting positions, reconciled to final ESPN box-score identities.

Starting positions belong to a game, never to a player's season-wide profile.
No depth-chart inference, fantasy eligibility expansion or G/F guessing is used.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from . import db, primary_positions

POSITIONS={'PG','SG','SF','PF','C'}
FIELDS=('minutes','pts','reb','ast','fg3m','stl','blk','fgm','fga','oreb','dreb','tov')
_snapshot_cache={}
SCHEMA='''CREATE TABLE IF NOT EXISTS nba_game_lineups (
 game_id TEXT,team TEXT,player_id TEXT,starter INTEGER NOT NULL,position TEXT,
 nba_player_id TEXT,source_url TEXT,source_timestamp TEXT,observed_at TEXT,
 PRIMARY KEY(game_id,team,player_id));
 CREATE TABLE IF NOT EXISTS nba_lineup_checks (
 game_id TEXT,team TEXT,game_date TEXT,verified INTEGER NOT NULL,reason TEXT,
 nba_game_id TEXT,source_url TEXT,source_hash TEXT,stats_hash TEXT,points REAL,
 observed_at TEXT,PRIMARY KEY(game_id,team));'''


def source_url(date):
    day=dt.date.fromisoformat(date)
    return f'https://stats.nba.com/js/data/leaders/00_daily_lineups_{day:%Y%m%d}.json'


def stats_hash(rows):
    values=[{'player_id':str(r['player_id']),**{k:float(r[k]) if isinstance(r.get(k),(int,float)) else None for k in FIELDS}} for r in rows]
    values.sort(key=lambda r:r['player_id'])
    return hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def ensure(c,seed=True):
    for statement in SCHEMA.split(';'):
        if statement.strip():c.execute(statement)
    if not seed:return
    # The source package carries only verified public lineup metadata, no user data.
    path=Path(__file__).resolve().parents[1]/'static/teams'/f'starting-lineups-{primary_positions.season()}.json'
    if not path.exists():return
    c.execute('CREATE TABLE IF NOT EXISTS lineup_snapshot_versions(version TEXT PRIMARY KEY)')
    modified=path.stat().st_mtime_ns
    cached=_snapshot_cache.get(path)
    if not cached or cached[0]!=modified:_snapshot_cache[path]=(modified,json.loads(path.read_text(encoding='utf-8')))
    payload=_snapshot_cache[path][1];version=payload['observed_at']
    if c.execute('SELECT 1 FROM lineup_snapshot_versions WHERE version=?',(version,)).fetchone():return
    for row in payload.get('checks',[]):
        columns=('game_id','team','game_date','verified','reason','nba_game_id','source_url','source_hash','stats_hash','points','observed_at')
        c.execute('INSERT OR IGNORE INTO nba_lineup_checks VALUES ('+','.join('?' for _ in columns)+')',tuple(row.get(k) for k in columns))
    for row in payload.get('players',[]):
        columns=('game_id','team','player_id','starter','position','nba_player_id','source_url','source_timestamp','observed_at')
        c.execute('INSERT OR IGNORE INTO nba_game_lineups VALUES ('+','.join('?' for _ in columns)+')',tuple(row.get(k) for k in columns))
    c.execute('INSERT INTO lineup_snapshot_versions VALUES (?)',(version,))


async def fetch_day(client,date):
    response=await client.get(source_url(date),timeout=18,follow_redirects=True)
    response.raise_for_status();payload=response.json()
    if not isinstance(payload.get('games'),list):raise ValueError('NBA confirmed-lineup feed is unavailable.')
    return payload,hashlib.sha256(response.content).hexdigest()


def _box_people(summary,team):
    found={}
    for section in (summary.get('boxscore') or {}).get('players',[]):
        if db.normalize_team('NBA',(section.get('team') or {}).get('abbreviation'))!=team:continue
        for category in section.get('statistics',[]):
            for entry in category.get('athletes',[]):
                athlete=entry.get('athlete') or {};pid=str(athlete.get('id',''))
                if not pid:continue
                if not isinstance(entry.get('starter'),bool):raise ValueError('Actual starter flag unavailable in final box score.')
                found[pid]={'id':pid,'name':athlete.get('displayName') or athlete.get('fullName',''),'starter':entry['starter']}
    if len([p for p in found.values() if p['starter']])!=5:raise ValueError('Final box score does not identify exactly five starters.')
    return found


def reconcile(game,summary,logs,payload,source_hash='',error=''):
    """Persist a verified lineup only when source, participants and scoring agree."""
    from .providers import iso_day
    date=game.get('game_date') or iso_day(game['starts_at'],'America/New_York')
    stamp=dt.datetime.now(dt.timezone.utc).isoformat();url=source_url(date);issues=[]
    pair=(db.normalize_team('NBA',game['away_abbr']),db.normalize_team('NBA',game['home_abbr']))
    matches=[g for g in payload.get('games',[]) if
        (db.normalize_team('NBA',g.get('awayTeam',{}).get('teamAbbreviation')),db.normalize_team('NBA',g.get('homeTeam',{}).get('teamAbbreviation')))==pair]
    with db.research_connect() as c:
        ensure(c)
        for side,feed_side in [('away','awayTeam'),('home','homeTeam')]:
            team=db.normalize_team('NBA',game[side+'_abbr']);rows=[r for r in logs if db.normalize_team('NBA',r['team'])==team]
            people={};nba_game_id='';reason='';entries=[];points=None;verified=False
            try:
                if error:raise ValueError(error)
                if len(matches)!=1:raise ValueError('No unique NBA lineup for this date and matchup.')
                nba_game=matches[0];nba_game_id=str(nba_game.get('gameId',''))
                people=_box_people(summary,team)
                starters={pid:p for pid,p in people.items() if p['starter']}
                nba_players=nba_game[feed_side].get('players',[])
                lineup=[p for p in nba_players if p.get('position')]
                if len(lineup)!=5 or {p['position'] for p in lineup}!=POSITIONS:
                    raise ValueError('NBA feed does not provide five distinct starting positions.')
                if any(p.get('lineupStatus')!='Confirmed' for p in lineup):raise ValueError('NBA starting positions are projected, not confirmed.')
                lookup={}
                for p in starters.values():lookup.setdefault(primary_positions.name_key(p['name']),[]).append(p)
                assigned={}
                for p in lineup:
                    names=lookup.get(primary_positions.name_key(p.get('playerName','')),[])
                    if len(names)!=1:raise ValueError('Confirmed NBA lineup does not match the actual box-score starters.')
                    pid=names[0]['id']
                    if pid in assigned:raise ValueError('Duplicate starter identity in lineup source.')
                    source_time=p.get('timestamp','')
                    try:
                        observed=dt.datetime.fromisoformat(source_time.replace('Z','+00:00'))
                        if observed.tzinfo is None:observed=observed.replace(tzinfo=dt.timezone.utc)
                        source_day=observed.astimezone(ZoneInfo('America/New_York')).date()
                        if source_day!=dt.date.fromisoformat(date):raise ValueError()
                    except (TypeError,ValueError):raise ValueError('Lineup timestamp does not match the requested game date.')
                    assigned[pid]=p
                if set(assigned)!=set(starters):raise ValueError('Starter identities do not match the final box score.')
                if not rows or len({r['player_id'] for r in rows})!=len(rows):raise ValueError('Player box score is empty or duplicated.')
                if any(r.get('pts') is None for r in rows):raise ValueError('Player points are missing from the box score.')
                points=sum(r['pts'] for r in rows);expected=game.get(side+'_score')
                if expected is None or abs(points-float(expected))>.001:raise ValueError('Player points do not reconcile to the final team score.')
                if not set(starters)<=set(str(r['player_id']) for r in rows):raise ValueError('A starter is missing from the saved player statistics.')
                for pid,p in people.items():
                    nba=assigned.get(pid,{})
                    entries.append((str(game['id']),team,pid,int(p['starter']),nba.get('position',''),str(nba.get('personId','')),url,nba.get('timestamp',''),stamp))
                verified=True
            except (ValueError,KeyError) as exc:reason=str(exc)
            # Replace a final game's evidence atomically. A failed current source
            # cannot erase previously verified evidence for identical statistics.
            prior=c.execute('SELECT * FROM nba_lineup_checks WHERE game_id=? AND team=?',(str(game['id']),team)).fetchone()
            digest=stats_hash(rows)
            expected=game.get(side+'_score')
            if not verified and prior and prior['verified'] and prior['stats_hash']==digest and expected is not None and prior['points']==float(expected):continue
            if not verified:issues.append(team+': '+reason)
            c.execute('DELETE FROM nba_game_lineups WHERE game_id=? AND team=?',(str(game['id']),team))
            if entries:c.executemany('INSERT INTO nba_game_lineups VALUES (?,?,?,?,?,?,?,?,?)',entries)
            c.execute('INSERT OR REPLACE INTO nba_lineup_checks VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (str(game['id']),team,date,int(verified),reason,nba_game_id,url,source_hash,digest,points,stamp))
    return issues


def resolve(people):
    if not people:return people
    with db.research_connect() as c:
        ensure(c)
        ids=list({str(p.get('game_id','')) for p in people if p.get('game_id')})
        if not ids:return people
        checks={};indexed={}
        for offset in range(0,len(ids),400):
            batch=ids[offset:offset+400];marks=','.join('?' for _ in batch)
            checks.update({(r['game_id'],r['team']):dict(r) for r in c.execute("SELECT n.*,g.status AS game_status,CASE WHEN g.home_abbr=n.team THEN g.home_score ELSE g.away_score END AS final_score FROM nba_lineup_checks n LEFT JOIN games g ON g.sport='NBA' AND g.id=n.game_id WHERE n.game_id IN ("+marks+')',batch)})
            indexed.update({(r['game_id'],r['team'],r['player_id']):dict(r) for r in c.execute('SELECT * FROM nba_game_lineups WHERE game_id IN ('+marks+')',batch)})
    grouped={}
    for p in people:grouped.setdefault((str(p.get('game_id','')),db.normalize_team('NBA',p['team'])),[]).append(p)
    for key,rows in grouped.items():
        check=checks.get(key)
        valid=check and check['verified'] and check['stats_hash']==stats_hash(rows) and check['game_status']=='final' and check['points']==check['final_score']
        for p in rows:
            p['lineup_verified']=bool(valid)
            if not valid:
                p['lineup_issue']=(check.get('reason') if check and not check['verified'] else 'Saved statistics or final score changed after lineup reconciliation.' if check else 'Confirmed starting positions have not been reconciled for this game.')
                continue
            item=indexed.get((*key,str(p['player_id'])))
            if not item:
                p['lineup_verified']=False;p['lineup_issue']='Player is absent from the reconciled box score.';continue
            p['is_starter']=bool(item['starter'])
            p['lineup_source_url']=item['source_url']
            if item['starter']:
                p['primary_position']=p.get('position','')
                p['position']=item['position'];p['position_source_url']=item['source_url'];p['position_basis']='Confirmed starting position'
                p.pop('position_unverified',None);p.pop('position_family',None)
            else:p['position_basis']='Primary bench position'
    return people


def saved_game_verified(game_id):
    """An old saved game can be skipped only after its current rows were checked."""
    with db.research_connect() as c:
        ensure(c)
        checks=[dict(r) for r in c.execute("SELECT n.*,g.status AS game_status,CASE WHEN g.home_abbr=n.team THEN g.home_score ELSE g.away_score END AS final_score FROM nba_lineup_checks n LEFT JOIN games g ON g.sport='NBA' AND g.id=n.game_id WHERE n.game_id=?",(str(game_id),))]
        if len(checks)!=2 or not all(r['verified'] for r in checks):return False
        rows=[dict(r) for r in c.execute("SELECT * FROM player_logs WHERE sport='NBA' AND game_id=?",(str(game_id),))]
    return all(check['game_status']=='final' and check['points']==check['final_score'] and check['stats_hash']==stats_hash([r for r in rows if r['team']==check['team']]) for check in checks)


def complete_score(game,rows):
    """A replacement box score must contain both complete scoring rosters."""
    for side in ('away','home'):
        team=db.normalize_team('NBA',game[side+'_abbr'])
        people=[r for r in rows if db.normalize_team('NBA',r['team'])==team]
        score=game.get(side+'_score')
        if not people or score is None or any(p.get('pts') is None for p in people):return False
        if abs(sum(p['pts'] for p in people)-float(score))>.001:return False
        if len({str(p['player_id']) for p in people})!=len(people):return False
    return True

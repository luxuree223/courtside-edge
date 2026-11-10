"""Compact public position evidence, retained with an account's cloud document.

The tracker export format remains unchanged. This archive contains no bets,
settings, keys, or tokens. Restoring evidence never certifies different box-score
statistics: the existing game-specific score/hash checks still apply on every use.
"""
import base64
import datetime as dt
import hashlib
import json
import zlib
from . import db, starting_lineups, primary_positions, position_index, research_ready

CHECKS=('game_id','team','game_date','verified','reason','nba_game_id','source_url','source_hash','stats_hash','points','observed_at')
PLAYERS=('game_id','team','player_id','starter','position','nba_player_id','source_url','source_timestamp','observed_at')
POSITIONS=('sport','player_id','team','position','source_url','observed_at')
MAX_ENCODED=350_000


def capture():
    year=primary_positions.season();start=f'{year-1}-07-01';end=f'{year}-07-01'
    with db.research_connect() as c:
        starting_lineups.ensure(c);position_index.ensure(c,'NBA')
        checks=[list(r) for r in c.execute('SELECT '+','.join(CHECKS)+' FROM nba_lineup_checks WHERE verified=1 AND game_date>=? AND game_date<? ORDER BY game_id,team',(start,end))]
        players=[list(r) for r in c.execute('SELECT '+','.join('p.'+k for k in PLAYERS)+''' FROM nba_game_lineups p
            JOIN nba_lineup_checks n ON n.game_id=p.game_id AND n.team=p.team
            WHERE n.verified=1 AND n.game_date>=? AND n.game_date<? ORDER BY p.game_id,p.team,p.player_id''',(start,end))]
        positions=[list(r) for r in c.execute("SELECT "+','.join(POSITIONS)+" FROM player_positions WHERE sport='NBA' AND position IN ('PG','SG','SF','PF','C') ORDER BY player_id,team")]
    data={'version':1,'season':year,'checks':checks,'players':players,'positions':positions,
          'checked_at':research_ready.status().get('checked_at')}
    value=base64.b64encode(zlib.compress(json.dumps(data,separators=(',',':'),allow_nan=False).encode(),9)).decode('ascii')
    if len(value)>MAX_ENCODED:raise ValueError('The saved position archive exceeds its cloud size limit.')
    return value


def fingerprint(value):return hashlib.sha256((value or '').encode()).hexdigest()


def restore(value):
    if not value:return
    if not isinstance(value,str) or len(value)>MAX_ENCODED:raise ValueError('Invalid position archive size.')
    inflater=zlib.decompressobj()
    raw=inflater.decompress(base64.b64decode(value,validate=True),8_000_001)
    if len(raw)>8_000_000 or not inflater.eof:raise ValueError('Invalid position archive.')
    data=json.loads(raw)
    if data.get('version')!=1:return
    # Keep the preceding season's verified game assignments too. They are
    # historical evidence and remain valid when the calendar rolls over.
    if not isinstance(data.get('season'),int) or not 2002<=data['season']<=primary_positions.season():raise ValueError('Invalid archived season.')
    checks=data.get('checks',[]);players=data.get('players',[]);positions=data.get('positions',[])
    if len(checks)>4000 or len(players)>100000 or len(positions)>3000:raise ValueError('Invalid position archive count.')
    valid={}
    for row in checks:
        if len(row)!=len(CHECKS):raise ValueError('Invalid archived game check.')
        item=dict(zip(CHECKS,row));day=dt.date.fromisoformat(item['game_date'])
        if not f'{data["season"]-1}-07-01'<=day.isoformat()<f'{data["season"]}-07-01':raise ValueError('Invalid archived season.')
        if item['verified']!=1 or not isinstance(item['stats_hash'],str) or len(item['stats_hash'])!=64:raise ValueError('Invalid archived evidence.')
        if item['source_url']!=starting_lineups.source_url(day.isoformat()) and not (
            str(item['source_url']).startswith('https://www.nba.com/game/') and str(item['source_url']).endswith('-'+str(item['nba_game_id'])+'/box-score')):raise ValueError('Invalid archived lineup source.')
        valid[(item['game_id'],item['team'])]=row
    grouped={}
    for row in players:
        if len(row)!=len(PLAYERS):raise ValueError('Invalid archived player.')
        item=dict(zip(PLAYERS,row));key=(item['game_id'],item['team'])
        if key not in valid or item['starter'] not in (0,1):raise ValueError('Invalid archived player game.')
        if item['starter'] and item['position'] not in starting_lineups.POSITIONS:raise ValueError('Invalid archived starting position.')
        if item['source_url']!=valid[key][CHECKS.index('source_url')]:raise ValueError('Invalid archived player source.')
        grouped.setdefault(key,[]).append(row)
    for key,rows in grouped.items():
        starters=[r for r in rows if r[PLAYERS.index('starter')]]
        if len(starters)!=5 or {r[PLAYERS.index('position')] for r in starters}!=starting_lineups.POSITIONS:raise ValueError('Invalid archived starting five.')
        if len({r[PLAYERS.index('player_id')] for r in rows})!=len(rows):raise ValueError('Duplicate archived player.')
    if set(grouped)!=set(valid):raise ValueError('Incomplete archived lineups.')
    for row in positions:
        if len(row)!=len(POSITIONS) or row[0]!='NBA' or row[3] not in starting_lineups.POSITIONS or not str(row[4]).startswith('https://'):raise ValueError('Invalid archived primary position.')
    # Validate the entire archive before changing any public metadata. Never
    # replace newer local evidence with an older cloud observation.
    with db.research_connect() as c:
        starting_lineups.ensure(c);position_index.ensure(c,'NBA')
        for key,row in valid.items():
            old=c.execute('SELECT verified,observed_at FROM nba_lineup_checks WHERE game_id=? AND team=?',key).fetchone()
            if old and (old['verified'] or old['observed_at']>=row[-1]):continue
            c.execute('INSERT OR REPLACE INTO nba_lineup_checks VALUES ('+','.join('?' for _ in CHECKS)+')',row)
            c.execute('DELETE FROM nba_game_lineups WHERE game_id=? AND team=?',key)
            c.executemany('INSERT INTO nba_game_lineups VALUES ('+','.join('?' for _ in PLAYERS)+')',grouped[key])
        for row in positions:
            c.execute('INSERT OR IGNORE INTO player_positions VALUES (?,?,?,?,?,?)',row)
        checked=data.get('checked_at')
        if checked:
            try:dt.datetime.fromisoformat(checked.replace('Z','+00:00'))
            except (ValueError,AttributeError):return
            research_ready.ensure(c)
            c.execute('INSERT OR IGNORE INTO research_readiness VALUES (1,?)',(checked,))

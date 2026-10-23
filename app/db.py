"""SQLite persistence and derived betting/game-log analytics."""
import sqlite3, os, math, csv, io, json, datetime, statistics, unicodedata, re
from contextlib import contextmanager
from pathlib import Path
from contextvars import ContextVar

DB_PATH = Path(os.environ.get('EDGE_DB_PATH', str(Path(__file__).resolve().parent.parent / 'data' / 'edge.sqlite3')))
PROFILE_PATH=ContextVar('courtside_profile_path',default=None)

def database_path():return PROFILE_PATH.get() or DB_PATH

@contextmanager
def research_connect():
    # Only public sports records are shared. Tracker/settings/quotes/keys keep
    # using connect() in the authenticated person's private database.
    token=PROFILE_PATH.set(None) if os.environ.get('EDGE_FIREBASE_ENABLED')=='1' else None
    try:
        with connect() as connection:yield connection
    finally:
        if token is not None:PROFILE_PATH.reset(token)


@contextmanager
def connect():
    path=database_path();path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=25)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=25000')
    db.execute('PRAGMA journal_mode=WAL')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bets (
  id INTEGER PRIMARY KEY AUTOINCREMENT, placed_at TEXT NOT NULL,
  sport TEXT NOT NULL DEFAULT 'NBA', market TEXT NOT NULL,
  selection TEXT NOT NULL, odds INTEGER NOT NULL,
  stake REAL NOT NULL CHECK(stake>0), status TEXT NOT NULL DEFAULT 'pending',
  payout REAL NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
  sportsbook TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS games (
 id TEXT NOT NULL, sport TEXT NOT NULL, starts_at TEXT NOT NULL,
 home_id TEXT DEFAULT '', home TEXT NOT NULL, home_abbr TEXT NOT NULL,
 away_id TEXT DEFAULT '', away TEXT NOT NULL, away_abbr TEXT NOT NULL,
 home_score INTEGER, away_score INTEGER, status TEXT NOT NULL,
 season_type TEXT NOT NULL DEFAULT 'regular', updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(id,sport)
);
CREATE TABLE IF NOT EXISTS player_logs (
 sport TEXT NOT NULL, game_id TEXT NOT NULL, player_id TEXT NOT NULL,
 player TEXT NOT NULL, team TEXT NOT NULL, opponent TEXT NOT NULL, position TEXT NOT NULL DEFAULT '',
 game_date TEXT NOT NULL, is_home INTEGER NOT NULL DEFAULT 0,
 season_type TEXT NOT NULL DEFAULT 'regular', minutes REAL DEFAULT 0,
 pts REAL DEFAULT 0, reb REAL DEFAULT 0, ast REAL DEFAULT 0, fg3m REAL DEFAULT 0,
 stl REAL DEFAULT 0, blk REAL DEFAULT 0, fga REAL DEFAULT 0,
 oreb REAL DEFAULT 0, dreb REAL DEFAULT 0, tov REAL DEFAULT 0,
 rec REAL DEFAULT 0, rec_yds REAL DEFAULT 0, targets REAL DEFAULT 0,
 rush_att REAL DEFAULT 0, rush_yds REAL DEFAULT 0,
 pass_yds REAL DEFAULT 0, pass_td REAL DEFAULT 0, rush_td REAL, rec_td REAL,
 source TEXT NOT NULL DEFAULT 'ESPN', updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(sport,game_id,player_id)
);
CREATE INDEX IF NOT EXISTS logs_lookup ON player_logs(sport,team,game_date DESC);
CREATE INDEX IF NOT EXISTS logs_byplayer ON player_logs(sport,player_id,game_date DESC);
CREATE INDEX IF NOT EXISTS logs_player_season ON player_logs(sport,player_id,season_type,game_date DESC,game_id DESC);
CREATE INDEX IF NOT EXISTS logs_position_window ON player_logs(sport,season_type,game_date DESC,opponent,position);
CREATE TABLE IF NOT EXISTS player_search (
 sport TEXT NOT NULL, player_id TEXT NOT NULL, player TEXT NOT NULL,
 name_key TEXT NOT NULL, position TEXT NOT NULL DEFAULT '', team TEXT NOT NULL,
 game_date TEXT NOT NULL, PRIMARY KEY(sport,player_id)
);
CREATE INDEX IF NOT EXISTS player_search_name ON player_search(sport,name_key);
CREATE TABLE IF NOT EXISTS team_logs (
 sport TEXT NOT NULL, game_id TEXT NOT NULL, team TEXT NOT NULL, opponent TEXT NOT NULL,
 game_date TEXT NOT NULL, is_home INTEGER NOT NULL DEFAULT 0,
 season_type TEXT NOT NULL DEFAULT 'regular', pts REAL DEFAULT 0,
 opp_pts REAL DEFAULT 0, fga REAL DEFAULT 0, fta REAL DEFAULT 0,
 oreb REAL DEFAULT 0, tov REAL DEFAULT 0, possessions REAL,
 PRIMARY KEY(sport,game_id,team)
);
CREATE TABLE IF NOT EXISTS sync_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT DEFAULT CURRENT_TIMESTAMP,
 sport TEXT, date_from TEXT, date_to TEXT, result TEXT, games INTEGER DEFAULT 0,
 players INTEGER DEFAULT 0, errors TEXT DEFAULT ''
);
'''

SEED_BETS = []

SCHEMA_VERSION = 11

def backup_database():
    """SQLite's backup API includes committed WAL records, unlike copying one file."""
    path=database_path()
    if not path.exists():return None
    folder=path.parent/'backups';folder.mkdir(exist_ok=True)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=folder/f'edge-before-upgrade-{stamp}.sqlite3'
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as source:
        with sqlite3.connect(target) as dest:source.backup(dest)
    return target

def init_db(seed=True):
    path=database_path();existing=path.exists() and path.stat().st_size>0
    version=0
    if existing:
        with sqlite3.connect(path) as connection:
            version=connection.execute('PRAGMA user_version').fetchone()[0]
        if version<SCHEMA_VERSION:backup_database()
    with connect() as db:
        db.executescript(SCHEMA)
        from . import markets
        db.executescript(markets.SCHEMA)
        from . import rankings, ai, props, live, ai_research, research_tools, leader_slates
        db.executescript(rankings.SCHEMA)
        db.executescript(ai.SCHEMA)
        db.executescript(props.SCHEMA)
        db.executescript(live.SCHEMA)
        db.executescript(ai_research.SCHEMA)
        db.executescript(research_tools.SCHEMA)
        db.executescript(leader_slates.SCHEMA)
        from . import position_index
        db.executescript(position_index.SCHEMA)
        from . import accounts
        db.executescript(accounts.SCHEMA)
        db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)', ('starting_bankroll','0'))
        db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)', ('unit_size','1'))
        db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)', ('timezone','America/Chicago'))
        if 'position' not in [r[1] for r in db.execute('PRAGMA table_info(player_logs)')]:
            db.execute("ALTER TABLE player_logs ADD COLUMN position TEXT NOT NULL DEFAULT ''")
        for table,columns in {
            'team_logs':{'game_minutes':'REAL','source_url':"TEXT NOT NULL DEFAULT ''"},
            'player_logs':{'source_url':"TEXT NOT NULL DEFAULT ''",'rush_td':'REAL','rec_td':'REAL'},
            'market_quotes':{'commence_time':"TEXT NOT NULL DEFAULT ''",'provider_updated_at':"TEXT NOT NULL DEFAULT ''",'observed_game_state':"TEXT NOT NULL DEFAULT 'unknown'",'batch_id':"TEXT NOT NULL DEFAULT ''"},
        }.items():
            present={r[1] for r in db.execute(f'PRAGMA table_info({table})')}
            for name,kind in columns.items():
                if name not in present:db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
        db.execute('''CREATE TABLE IF NOT EXISTS covers_snapshots (
            id TEXT PRIMARY KEY, sport TEXT NOT NULL, game_id TEXT NOT NULL,
            source_url TEXT NOT NULL, captured_at TEXT NOT NULL, method TEXT NOT NULL,
            filename TEXT NOT NULL, note TEXT NOT NULL DEFAULT '')''')
        db.execute('''CREATE TABLE IF NOT EXISTS covers_game_odds (
            sport TEXT NOT NULL,game_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(sport,game_id))''')
        if version<8:
            # One migration scan; searches subsequently use the compact catalogue.
            people={}
            for row in db.execute('SELECT sport,player_id,player,position,team,game_date FROM player_logs ORDER BY game_date DESC,game_id DESC'):
                person=people.setdefault((row['sport'],row['player_id']),dict(row))
                if not person['position'] and row['position']:person['position']=row['position']
            _save_player_search(db,people.values())
        db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        if seed and not existing and db.execute('SELECT COUNT(*) FROM bets').fetchone()[0] == 0:
            db.executemany('INSERT INTO bets(placed_at,sport,market,selection,odds,stake,status,payout,note,sportsbook) VALUES (?,?,?,?,?,?,?,?,?,?)', SEED_BETS)
            db.execute("INSERT INTO settings(key,value) VALUES ('seeded_bets','1')")


def get_settings():
    with connect() as db:
        return {r['key']: r['value'] for r in db.execute('SELECT * FROM settings')}

def save_settings(values):
    allowed = {'starting_bankroll', 'unit_size', 'timezone', 'bankroll_adjustment'}
    if 'timezone' in values:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:ZoneInfo(values['timezone'])
        except (ZoneInfoNotFoundError,ValueError):raise ValueError('Choose a valid timezone')
    if 'starting_bankroll' in values and (float(values['starting_bankroll']) < 0 or not math.isfinite(float(values['starting_bankroll']))):
        raise ValueError('Invalid bankroll')
    if 'bankroll_adjustment' in values and not math.isfinite(float(values['bankroll_adjustment'])):raise ValueError('Enter a valid balance adjustment.')
    if 'unit_size' in values and (float(values['unit_size']) <= 0 or not math.isfinite(float(values['unit_size']))):
        raise ValueError('Invalid unit size')
    with connect() as db:
        for k,v in values.items():
            if k in allowed: db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (k,str(v)))

def all_bets():
    with connect() as db:
        return [dict(r) for r in db.execute('SELECT * FROM bets ORDER BY placed_at DESC,id DESC')]

def bet_summary():
    bets = all_bets()
    st=get_settings(); unit=float(st.get('unit_size','1')); starting=float(st.get('starting_bankroll','0'))
    adjustment=float(st.get('bankroll_adjustment','0'))
    settled=[b for b in bets if b['status']!='pending']
    profit=sum(b['payout']-b['stake'] for b in settled)
    risk=sum(b['stake'] for b in settled)
    wins=sum(b['payout'] > b['stake'] for b in settled)
    losses=sum(b['payout'] < b['stake'] for b in settled)
    pushes=sum(b['payout'] == b['stake'] for b in settled)
    pending_risk=sum(b['stake'] for b in bets if b['status']=='pending')
    running=starting
    trajectory=[{'date':'Start','balance':round(running,2)}]
    for b in sorted(settled,key=lambda x:(x['placed_at'],x['id'])):
        running += b['payout']-b['stake']
        trajectory.append({'date':b['placed_at'],'balance':round(running,2)})
    if adjustment:trajectory.append({'date':datetime.datetime.now(datetime.timezone.utc).date().isoformat(),'balance':round(running+adjustment,2)})
    return dict(starting_bankroll=starting, bankroll_adjustment=adjustment, unit=unit, profit=round(profit,2),
        units=round(profit/unit,3), settled_risk=round(risk,2),roi=round(profit/risk*100,1) if risk else 0,
        wins=wins, losses=losses, pushes=pushes, pending=sum(b['status']=='pending' for b in bets),
        pending_risk=round(pending_risk,2), bankroll=round(starting+profit+adjustment,2),
        available=round(starting+profit+adjustment-pending_risk,2), trajectory=trajectory,
        cashouts=sum(b['status']=='cashed_out' for b in bets))

def upsert_bet(data, bet_id=None):
    fields=['placed_at','sport','market','selection','odds','stake','status','payout','note','sportsbook']
    status=str(data.get('status','pending'))
    if status not in ('won','lost','pending','push','cashed_out'): raise ValueError('Invalid status')
    odds=int(data['odds']); stake=float(data['stake']); payout=float(data.get('payout') or 0)
    if odds == 0 or abs(odds)<100: raise ValueError('American odds must be +100 or greater, or -100 or less')
    if stake<=0 or payout<0 or not all(map(math.isfinite,[stake,payout])): raise ValueError('Invalid stake or payout')
    if status=='lost': payout=0.0
    if status=='push': payout=stake
    if status=='pending': payout=0.0
    if status=='won' and payout==0: payout=round(stake*(1+ (odds/100 if odds>0 else 100/abs(odds))),2)
    vals=dict(data);vals.update(odds=odds,stake=stake,payout=payout,status=status)
    row=[vals.get(k,'') for k in fields]
    with connect() as db:
        if bet_id is None:
            cur=db.execute('INSERT INTO bets('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')',row)
            return cur.lastrowid
        cur=db.execute('UPDATE bets SET '+','.join(f'{f}=?' for f in fields)+' WHERE id=?',row+[bet_id])
        if not cur.rowcount: raise KeyError('Bet not found')
        return bet_id

def delete_bet(bet_id):
    with connect() as db:
        cur=db.execute('DELETE FROM bets WHERE id=?',(bet_id,))
        if not cur.rowcount:raise KeyError('Bet not found')

def bets_csv():
    output=io.StringIO();rows=all_bets()
    w=csv.writer(output);w.writerow(['Date','Sport','Market','Selection','Odds','Stake','Status','Payout','Profit','Units','Note','Sportsbook'])
    unit=float(get_settings()['unit_size'])
    for b in rows:
        profit=0 if b['status']=='pending' else round(b['payout']-b['stake'],2)
        w.writerow([b['placed_at'],b['sport'],b['market'],b['selection'],b['odds'],b['stake'],b['status'],b['payout'],profit,round(profit/unit,3),b['note'],b['sportsbook']])
    return output.getvalue()

GAME_FIELDS=['id','sport','starts_at','home_id','home','home_abbr','away_id','away','away_abbr','home_score','away_score','status','season_type']
LOG_FIELDS=['sport','game_id','player_id','player','team','opponent','position','game_date','is_home','season_type','minutes','pts','reb','ast','fg3m','stl','blk','fga','oreb','dreb','tov','rec','rec_yds','targets','rush_att','rush_yds','pass_yds','pass_td','rush_td','rec_td','source','source_url']
TEAM_FIELDS=['sport','game_id','team','opponent','game_date','is_home','season_type','pts','opp_pts','fga','fta','oreb','tov','possessions','game_minutes','source_url']

def normalize_team(sport,value):
    text=str(value or '').strip().upper()
    aliases={'NBA':{'GSW':'GS','NYK':'NY','NOP':'NO','SAS':'SA','UTA':'UTAH','WAS':'WSH'},
             'NFL':{'LA':'LAR','JAC':'JAX','WSH':'WAS'}}
    return aliases.get(sport,{}).get(text,text)

def save_game(db,g):
    g=dict(g)
    for key in ('home_abbr','away_abbr'):g[key]=normalize_team(g['sport'],g[key])
    old=db.execute('SELECT * FROM games WHERE id=? AND sport=?',(g['id'],g['sport'])).fetchone()
    if old:
        g=dict(g)
        for side in ('home','away'):
            if g.get(side)==g.get(side+'_abbr') and old[side]:g[side]=old[side]
        if len(g.get('starts_at',''))==10 and len(old['starts_at'])>10:g['starts_at']=old['starts_at']
    db.execute('INSERT INTO games ('+','.join(GAME_FIELDS)+') VALUES ('+','.join('?' for _ in GAME_FIELDS)+') ON CONFLICT(id,sport) DO UPDATE SET '+','.join(f'{f}=excluded.{f}' for f in GAME_FIELDS if f not in ('id','sport'))+',updated_at=CURRENT_TIMESTAMP', [g.get(f) for f in GAME_FIELDS])

def save_logs(db, logs):
    logs=[{**row,'team':normalize_team(row['sport'],row['team']),'opponent':normalize_team(row['sport'],row['opponent'])} for row in logs]
    stmt='INSERT INTO player_logs ('+','.join(LOG_FIELDS)+') VALUES ('+','.join('?' for _ in LOG_FIELDS)+') ON CONFLICT(sport,game_id,player_id) DO UPDATE SET '+','.join(f'{f}=COALESCE(excluded.{f},player_logs.{f})' if f in ('rush_td','rec_td') else "position=CASE WHEN excluded.position IS NULL OR TRIM(excluded.position)='' THEN player_logs.position ELSE excluded.position END" if f=='position' else f'{f}=excluded.{f}' for f in LOG_FIELDS if f not in ('sport','game_id','player_id'))+',updated_at=CURRENT_TIMESTAMP'
    db.executemany(stmt, [[r.get(f,'' if f=='source_url' else None) for f in LOG_FIELDS] for r in logs])
    people=[]
    for sport,pid in {(r['sport'],r['player_id']) for r in logs}:
        person=dict(db.execute('SELECT sport,player_id,player,position,team,game_date FROM player_logs WHERE sport=? AND player_id=? ORDER BY game_date DESC,game_id DESC LIMIT 1',(sport,pid)).fetchone())
        if not person['position']:
            position=db.execute("SELECT position FROM player_logs WHERE sport=? AND player_id=? AND TRIM(COALESCE(position,''))!='' ORDER BY game_date DESC,game_id DESC LIMIT 1",(sport,pid)).fetchone()
            person['position']=position['position'] if position else ''
        people.append(person)
    _save_player_search(db,people)

def save_team_logs(db, rows):
    rows=[{**row,'team':normalize_team(row['sport'],row['team']),'opponent':normalize_team(row['sport'],row['opponent'])} for row in rows]
    stmt='INSERT INTO team_logs ('+','.join(TEAM_FIELDS)+') VALUES ('+','.join('?' for _ in TEAM_FIELDS)+') ON CONFLICT(sport,game_id,team) DO UPDATE SET '+','.join(f'{f}=excluded.{f}' for f in TEAM_FIELDS if f not in ('sport','game_id','team'))
    db.executemany(stmt, [[r.get(f,'' if f=='source_url' else None) for f in TEAM_FIELDS] for r in rows])

def games_list(sport='NBA', start=None, end=None, limit=100):
    with research_connect() as db:
        q='SELECT * FROM games WHERE sport=?';params=[sport]
        if start:q+=' AND substr(starts_at,1,10)>=?';params.append(start)
        if end:q+=' AND substr(starts_at,1,10)<=?';params.append(end)
        q+=' ORDER BY starts_at DESC LIMIT ?';params.append(limit)
        return [dict(r) for r in db.execute(q,params)]

def data_counts():
    with research_connect() as db:
        stats={}
        for sport in ['NBA','NFL']:
            games=db.execute('SELECT COUNT(*) FROM games WHERE sport=? AND status=?',(sport,'final')).fetchone()[0]
            logs=db.execute('SELECT COUNT(*),MAX(game_date),MIN(game_date) FROM player_logs WHERE sport=?',(sport,)).fetchone()
            stats[sport]={'games':games,'player_logs':logs[0],'latest':logs[1], 'earliest':logs[2]}
            stats[sport]['seasons']=[dict(r) for r in db.execute('SELECT season_type,COUNT(*) AS player_logs FROM player_logs WHERE sport=? GROUP BY season_type',(sport,))]
            stats[sport]['games_without_player_logs']=db.execute('''SELECT COUNT(*) FROM games g WHERE g.sport=? AND g.status='final'
                AND NOT EXISTS (SELECT 1 FROM player_logs p WHERE p.sport=g.sport AND p.game_id=g.id)''',(sport,)).fetchone()[0]
        stats['syncs']=[dict(r) for r in db.execute('SELECT * FROM sync_runs ORDER BY id DESC LIMIT 8')]
        backups=sorted((database_path().parent/'backups').glob('*.sqlite3'))
        stats['backup']={'available':bool(backups),'latest':backups[-1].name if backups else None}
        last_success=db.execute("SELECT value FROM settings WHERE key='last_nightly_success'").fetchone()
        stats['automatic_updates']={'enabled':os.environ.get('EDGE_AUTO_SYNC','1')=='1','last_success':last_success[0] if last_success else None}
        return stats

STATS={'NBA':{'pts':'Points','reb':'Rebounds','ast':'Assists','pra':'Points + rebounds + assists','pr':'Points + rebounds','pa':'Points + assists','ra':'Rebounds + assists','fg3m':'3-pointers made','stl':'Steals','blk':'Blocks'},
       'NFL':{'rec':'Receptions','rec_yds':'Receiving yards','targets':'Targets','rush_att':'Rushing attempts','rush_yds':'Rushing yards','pass_yds':'Passing yards','pass_td':'Passing TDs','rush_td':'Rushing TDs','rec_td':'Receiving TDs'}}

COMBOS={'pra':('pts','reb','ast'),'pr':('pts','reb'),'pa':('pts','ast'),'ra':('reb','ast')}

def stat_value(row,stat):
    fields=COMBOS.get(stat,(stat,))
    if any(row.get(f) is None for f in fields):return None
    return sum(float(row[f]) for f in fields)

def player_name_key(value):
    text=unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().casefold()
    return re.sub(r'[^a-z0-9]+','',text)


def _save_player_search(connection,people):
    connection.executemany('''INSERT INTO player_search(sport,player_id,player,name_key,position,team,game_date)
        VALUES (?,?,?,?,?,?,?) ON CONFLICT(sport,player_id) DO UPDATE SET
        player=excluded.player,name_key=excluded.name_key,position=excluded.position,team=excluded.team,game_date=excluded.game_date''',
        [(p['sport'],p['player_id'],p['player'],player_name_key(p['player']),p['position'] or '',p['team'],p['game_date']) for p in people])


def consistency(sport='NBA', teams=None, stat='pts', threshold=20, min_rate=50, max_rate=100, n=10, venue='all', season_type='regular', min_minutes=0, max_results=120, comparison='at_least', opponent='', before=None, season=None, player='',date_from=None,date_to=None,season_types=None):
    sport=sport.upper()
    if stat not in STATS.get(sport,{}): raise ValueError('Unsupported stat')
    if not 1<=n<=100 or not 0<=min_rate<=max_rate<=100:raise ValueError('Invalid filters')
    if comparison not in ('at_least','over'):raise ValueError('Choose at least or over')
    if venue not in ('all','home','away') or season_type not in ('regular','preseason','postseason'):raise ValueError('Invalid game filters')
    if not math.isfinite(threshold) or threshold<0 or not math.isfinite(min_minutes) or min_minutes<0:raise ValueError('Enter valid amounts')
    if before:datetime.date.fromisoformat(before)
    if len(player)>150:raise ValueError('Keep player names under 150 characters.')
    player_query=player_name_key(player)
    if player.strip() and not player_query:return []
    reached=lambda v:v>=threshold if comparison=='at_least' else v>threshold
    with research_connect() as db:
        kinds=season_types or [season_type]
        query='SELECT * FROM player_logs WHERE sport=? AND season_type IN ('+','.join('?' for _ in kinds)+')';params=[sport,*kinds]
        # Select players by their latest known team, then include their prior team logs.
        # A traded player's old team must not make them appear on the old roster.
        teams=[normalize_team(sport,v) for v in teams or [] if v.strip()]
        latest_query='SELECT player_id,team,position FROM player_logs WHERE sport=?'
        latest_args=[sport]
        if before:latest_query+=' AND game_date<?';latest_args.append(before)
        latest_query+=' ORDER BY game_date DESC,game_id DESC'
        latest={};positions={}
        for row in db.execute(latest_query,latest_args):
            latest.setdefault(row['player_id'],row['team'])
            if row['position']:positions.setdefault(row['player_id'],row['position'])
        if before:query+=' AND game_date<?';params.append(before)
        if date_from:query+=' AND game_date>=?';params.append(date_from)
        if date_to:query+=' AND game_date<?';params.append(date_to)
        if opponent:query+=' AND opponent=?';params.append(normalize_team(sport,opponent))
        if season:
            if not 2002<=season<=2100:raise ValueError('Choose a valid season')
            if sport=='NBA':start,end=f'{season-1}-07-01',f'{season}-07-01'
            else:start,end=f'{season}-03-01',f'{season+1}-03-01'
            query+=' AND game_date>=? AND game_date<?';params.extend([start,end])
        if venue=='home':query+=' AND is_home=1'
        if venue=='away':query+=' AND is_home=0'
        if sport=='NBA' and min_minutes>0:query+=' AND minutes>=?';params.append(min_minutes)
        query+=' ORDER BY game_date DESC,game_id DESC'
        rows=[dict(r) for r in db.execute(query,params)]
    groups={}
    for r in rows:
        key=r['player_id']
        if teams and latest.get(key) not in teams:continue
        if sport=='NBA' and (r['minutes'] or 0)<=0:continue
        if stat_value(r,stat) is None:continue
        if len(groups.get(key,[]))<n: groups.setdefault(key,[]).append(r)
    out=[]
    for k,rs in groups.items():
        if player_query and player_query not in player_name_key(rs[0]['player']):continue
        values=[stat_value(r,stat) for r in rs]
        hits=sum(reached(v) for v in values)
        rate=round(hits/len(values)*100,1)
        if not min_rate<=hits/len(values)*100<=max_rate:continue
        out.append({'player':rs[0]['player'],'player_id':k,'position':positions.get(k,''),'team':latest.get(k,rs[0]['team']),'stat':stat,'threshold':threshold,'comparison':comparison,'requested':n,'latest':rs[0]['game_date'],
                    'hits':hits,'sample':len(values),'rate':rate,'average':round(statistics.mean(values),1),
                    'median':round(statistics.median(values),1),'min':min(values),'max':max(values),
                    'logs':[{'date':r['game_date'],'opponent':r['opponent'],'home':bool(r['is_home']),
                            'value':round(v,1),'hit':reached(v),'minutes':r.get('minutes',0),
                            'team':r['team'],'source':r['source'],'source_url':r['source_url'],'saved_at':r['updated_at']} for r,v in zip(rs,values)]})
    return sorted(out,key=lambda r:(-r['rate'],-r['sample'],-r['average'],r['player']))[:max_results]

def threshold_ladder(sport,player_id,stat,n=10,season_type='regular'):
    if stat not in STATS.get(sport,{}):raise ValueError('Unsupported stat')
    if not 1<=n<=100:raise ValueError('Choose 1 to 100 games')
    with research_connect() as db:
        rs=[dict(r) for r in db.execute('SELECT * FROM player_logs WHERE sport=? AND player_id=? AND season_type=? ORDER BY game_date DESC', (sport,player_id,season_type))]
    vals=[stat_value(r,stat) for r in rs if stat_value(r,stat) is not None and (sport!='NBA' or (r['minutes'] or 0)>0)][:n]
    if not vals:return []
    maxima=max(vals)
    step=5 if stat in ('pts','pra','rec_yds','rush_yds','pass_yds') else 1
    return [{'threshold':int(x),'hits':sum(v>=x for v in vals),'sample':len(vals),'rate':round(sum(v>=x for v in vals)/len(vals)*100,1)} for x in range(step, int(maxima)+step,step)]

def nba_matchup(home,away,last=10,season_type='regular',before=None,date_from=None,date_to=None,season_types=None):
    if before:datetime.date.fromisoformat(before)
    with research_connect() as db:
        def team(abbr):
            kinds=season_types or [season_type]
            sql="SELECT * FROM team_logs WHERE sport='NBA' AND team=? AND season_type IN ("+','.join('?' for _ in kinds)+')';args=[abbr,*kinds]
            if before:sql+=' AND game_date<?';args.append(before)
            if date_from:sql+=' AND game_date>=?';args.append(date_from)
            if date_to:sql+=' AND game_date<?';args.append(date_to)
            sql+=' ORDER BY game_date DESC LIMIT ?';args.append(last)
            rs=[dict(r) for r in db.execute(sql,args)]
            if not rs:return {'abbr':abbr,'games':0}
            mean=lambda key:round(statistics.mean(float(r[key]) for r in rs if r[key] is not None),1) if any(r[key] is not None for r in rs) else None
            return {'abbr':abbr,'games':len(rs),'points':mean('pts'),'allowed':mean('opp_pts'),'possessions':mean('possessions')}
        return {'home':team(home),'away':team(away)}


def defense_vs_position(team,last=10,season_type='regular',before=None,date_from=None,date_to=None,season_types=None):
    """Historical points/rebounds/assists allowed by a team to *opposing* NBA positions.
    Sums contributions per position per opposing game, then averages over available games.
    Unclassified player logs are excluded, and partial classification is noted.
    """
    if before:datetime.date.fromisoformat(before)
    with research_connect() as db:
        cutoff=' AND game_date<?' if before else ''
        cutoff+=(' AND game_date>=?' if date_from else '')+(' AND game_date<?' if date_to else '')
        kinds=season_types or [season_type];kind_sql='season_type IN ('+','.join('?' for _ in kinds)+')'
        args=[team,*kinds]+([before] if before else [])+([date_from] if date_from else [])+([date_to] if date_to else [])+[last]
        days=[r['game_id'] for r in db.execute("SELECT game_id FROM team_logs WHERE sport='NBA' AND team=? AND "+kind_sql+cutoff+" ORDER BY game_date DESC LIMIT ?",args)]
        if not days:
            days=[r['game_id'] for r in db.execute("SELECT DISTINCT game_id,game_date FROM player_logs WHERE sport='NBA' AND opponent=? AND "+kind_sql+cutoff+" ORDER BY game_date DESC LIMIT ?",args)]
        if not days:return {'team':team,'games':0,'positions':[],'classified_games':0}
        query="SELECT game_id, position, pts,reb,ast FROM player_logs WHERE sport='NBA' AND opponent=? AND "+kind_sql+" AND game_id IN ("+','.join('?'*len(days))+")"
        rows=[dict(r) for r in db.execute(query,[team,*kinds,*days])]
    grouped={};seen=set()
    for r in rows:
        pos=str(r['position'] or '').upper()
        if pos not in ('PG','SG','SF','PF','C'):continue
        seen.add(r['game_id'])
        totals=grouped.setdefault(pos,{}).setdefault(r['game_id'],{'pts':0.,'reb':0.,'ast':0.})
        for key in ('pts','reb','ast'):totals[key]+=r[key] or 0
    result=[]
    for pos,games in grouped.items():
        # Only compute an average when at least one classified opponent of that position exists.
        result.append({'position':pos,'games':len(games),
                       **{key:round(statistics.mean(v[key] for v in games.values()),1) for key in ('pts','reb','ast')}})
    result.sort(key=lambda x:['PG','SG','SF','PF','C'].index(x['position']))
    return {'team':team,'games':len(days),'classified_games':len(seen),'positions':result}

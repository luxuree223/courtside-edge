"""Persist the displayed leaders slate until a later game day finishes and syncs."""
import datetime as dt
import json
from zoneinfo import ZoneInfo
from . import db, providers, live

SCHEMA='''CREATE TABLE IF NOT EXISTS retained_leader_slates (
 sport TEXT PRIMARY KEY, game_date TEXT NOT NULL, payload TEXT NOT NULL,
 synced_at TEXT NOT NULL);'''


def local_today():
    return dt.datetime.now(ZoneInfo(db.get_settings().get('timezone','America/Chicago'))).date()


def saved(sport):
    with db.research_connect() as c:row=c.execute('SELECT * FROM retained_leader_slates WHERE sport=?',(sport,)).fetchone()
    return {**dict(row),'payload':json.loads(row['payload'])} if row else None


def capture_day(sport,date,games=None):
    """Called only after a successful results sync (or first-install history bootstrap).
    Never publish an unfinished, empty or partially downloaded slate, or regress dates.
    """
    if sport not in ('NBA','NFL'):raise ValueError('Choose NBA or NFL.')
    chosen=dt.date.fromisoformat(date)
    if chosen>local_today():return False
    zone=db.get_settings().get('timezone','America/Chicago')
    if games is None:
        with db.research_connect() as c:games=[dict(r) for r in c.execute('SELECT * FROM games WHERE sport=?',(sport,))]
    games=[dict(g) for g in games if g['sport']==sport and providers.iso_day(g['starts_at'],zone)==date]
    if not games or any(g['status']!='final' for g in games):return False
    ids={str(g['id']) for g in games}
    stamp=live.now().isoformat()
    with db.research_connect() as c:
        old=c.execute('SELECT game_date FROM retained_leader_slates WHERE sport=?',(sport,)).fetchone()
        if old and old['game_date']>date:return False
        query='SELECT * FROM player_logs WHERE sport=? AND game_id IN ('+','.join('?' for _ in ids)+') ORDER BY game_id,player_id'
        rows=[dict(r) for r in c.execute(query,[sport,*sorted(ids)])]
        if {r['game_id'] for r in rows}!=ids:return False
        payload=json.dumps({'games':games,'rows':rows},separators=(',',':'))
        c.execute('''INSERT INTO retained_leader_slates(sport,game_date,payload,synced_at) VALUES (?,?,?,?)
            ON CONFLICT(sport) DO UPDATE SET game_date=excluded.game_date,payload=excluded.payload,synced_at=excluded.synced_at
            WHERE excluded.game_date>=retained_leader_slates.game_date''',(sport,date,payload,stamp))
    return True


def bootstrap(sport):
    """An upgrade starts with the newest fully saved night, without downloading or dating it as today."""
    existing=saved(sport)
    if existing:return existing
    zone=db.get_settings().get('timezone','America/Chicago');today=local_today().isoformat()
    with db.research_connect() as c:
        games=[dict(r) for r in c.execute('SELECT * FROM games WHERE sport=? ORDER BY starts_at DESC',(sport,))]
        ids={r[0] for r in c.execute('SELECT DISTINCT game_id FROM player_logs WHERE sport=?',(sport,))}
    groups={}
    for game in games:
        day=providers.iso_day(game['starts_at'],zone)
        if day<=today:groups.setdefault(day,[]).append(game)
    for date,slate in sorted(groups.items(),reverse=True):
        if all(g['status']=='final' and g['id'] in ids for g in slate) and capture_day(sport,date,slate):return saved(sport)
    return None


def leaders(sport,stat):
    if sport not in db.STATS or stat not in db.STATS[sport]:raise ValueError('Choose a stat for this sport.')
    snapshot=bootstrap(sport)
    date=snapshot['game_date'] if snapshot else None
    payload=snapshot['payload'] if snapshot else {'games':[],'rows':[]}
    from . import stat_logs
    rows=[]
    for raw in payload['rows']:
        value=db.stat_value(raw,stat)
        if value is None:continue
        row=stat_logs._public(raw,sport)
        rows.append({**row,'sport':sport,'value':value,'status':'final','stale':False,'fetched_at':snapshot['synced_at']})
    if sport=='NFL' and stat in ('pass_yds','pass_td') and date:
        rows=[r for r in stat_logs._fill_positions(rows,sport,date) if stat_logs.is_quarterback(r['position'])]
    rows.sort(key=lambda r:(-r['value'],r['player']))
    previous=None;rank=0
    for i,row in enumerate(rows):
        if row['value']!=previous:rank=i+1
        row['rank']=rank;previous=row['value']
    rows=stat_logs._fill_positions(rows[:100],sport,date) if date else []
    keep='a later football day finishes and its results sync' if sport=='NFL' else 'the next completed NBA night is synced'
    note=f'Showing {date} until {keep}. Midnight, a page refresh, or Refresh Leaders will not switch game days.' if date else 'No completed game night is synced yet. Use Sync Tonight’s Results after games finish.'
    games=len(payload['games'])
    return {'sport':sport,'stat':stat,'label':db.STATS[sport][stat],'date':date,'rows':rows,
            'games':games,'completed_games':games,'live_games':0,'covered_games':games,'started_games':games,
            'issues':[],'stale':False,'retained':True,'slate_synced_at':snapshot['synced_at'] if snapshot else None,
            'fetched_at':snapshot['synced_at'] if snapshot else None,'retention_note':note,
            'note':'Completed-game stats saved by results sync. The same game day is used for every category. Live box scores remain available in Pick a Game.'}

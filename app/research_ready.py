"""Shared research freshness; browser navigation never requires another full sync."""
import datetime as dt
from . import db


def ensure(c):
    c.execute('CREATE TABLE IF NOT EXISTS research_readiness (id INTEGER PRIMARY KEY, checked_at TEXT NOT NULL)')


def finish():
    with db.research_connect() as c:
        ensure(c)
        c.execute('INSERT OR REPLACE INTO research_readiness VALUES (1,?)',(dt.datetime.now(dt.timezone.utc).isoformat(),))


def status():
    with db.research_connect() as c:
        ensure(c)
        marker=c.execute('SELECT checked_at FROM research_readiness WHERE id=1').fetchone()
        # Only this season's public records establish readiness.
        now=dt.date.today();start=f'{now.year-(now.month<7)}-07-01'
        rows=c.execute("SELECT sport,count(*) FROM player_logs WHERE game_date>=? GROUP BY sport",(start,)).fetchall()
    counts={r[0]:r[1] for r in rows};stamp=marker[0] if marker else None
    age=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(stamp)).total_seconds() if stamp else None
    return {'ready':sum(counts.values())>0,'checked_at':stamp,'needs_update':age is None or age>3600}

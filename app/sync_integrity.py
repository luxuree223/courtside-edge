"""Evidence that a saved NFL summary contains both complete offensive rosters.

A single saved player is not proof that a game's download finished. Receipts
bind the source-validated roster to its saved statistics and final scores.
"""
import hashlib
import json
from . import db

FIELDS=('player_id','team','opponent','game_date','season_type','position',
        'rec','rec_yds','targets','rush_att','rush_yds','pass_yds','pass_td','rush_td','rec_td')


def ensure(c):
    c.execute('''CREATE TABLE IF NOT EXISTS nfl_summary_checks (
      game_id TEXT PRIMARY KEY, stats_hash TEXT NOT NULL, home_score INTEGER,
      away_score INTEGER, observed_at TEXT DEFAULT CURRENT_TIMESTAMP)''')


def digest(rows):
    # SQLite defaults omitted statistical fields to zero. Hash that same saved
    # representation, retaining explicit nulls rather than inventing reports.
    values=[{k:(str(r[k]) if k=='player_id' else float(r[k]) if isinstance(r.get(k),(int,float))
                   else r.get(k,0 if k not in FIELDS[:6] else '')) for k in FIELDS} for r in rows]
    values.sort(key=lambda r:(r['team'],r['player_id']))
    return hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def complete(summary,game,rows):
    """Reconcile passing, receiving and rushing to ESPN's team box score."""
    from .providers import number
    boxes=(summary.get('boxscore') or {})
    for side in ('home','away'):
        team=db.normalize_team('NFL',game[side+'_abbr'])
        people=[r for r in rows if db.normalize_team('NFL',r['team'])==team]
        if not people or game.get(side+'_score') is None:return False
        sections=[s for s in boxes.get('players',[]) if db.normalize_team('NFL',s.get('team',{}).get('abbreviation'))==team]
        totals=[s for s in boxes.get('teams',[]) if db.normalize_team('NFL',s.get('team',{}).get('abbreviation'))==team]
        if len(sections)!=1 or len(totals)!=1:return False
        stats={s.get('name'):s.get('displayValue') for s in totals[0].get('statistics',[])}
        required={'passing':{'YDS','TD'},'rushing':{'CAR','YDS','TD'},'receiving':{'REC','YDS','TD'}}
        for name,fields in required.items():
            categories=[s for s in sections[0].get('statistics',[]) if s.get('name')==name]
            if len(categories)!=1:return False
            category=categories[0];labels=category.get('labels',[])
            if not fields<=set(labels):return False
            for player in category.get('athletes',[]):
                values=player.get('stats') or []
                if not (player.get('athlete') or {}).get('id'):return False
                if any(labels.index(k)>=len(values) or number(values[labels.index(k)],None) is None for k in fields):return False
        rush_yards=number(stats.get('rushingYards'),None)
        rush_attempts=number(stats.get('rushingAttempts'),None)
        net_pass=number(stats.get('netPassingYards'),None)
        sacks=str(stats.get('sacksYardsLost','')).split('-')
        sack_yards=number(sacks[-1],None) if len(sacks)==2 else None
        if any(v is None for v in (rush_yards,rush_attempts,net_pass,sack_yards)):return False
        expected={'rush_yds':rush_yards,'rush_att':rush_attempts,'pass_yds':net_pass+sack_yards,'rec_yds':net_pass+sack_yards}
        if any(abs(sum(r.get(k) or 0 for r in people)-v)>.001 for k,v in expected.items()):return False
    return len({str(r['player_id']) for r in rows})==len(rows)


def record(c,game):
    ensure(c)
    rows=[dict(r) for r in c.execute("SELECT * FROM player_logs WHERE sport='NFL' AND game_id=?",(game['id'],))]
    c.execute('INSERT OR REPLACE INTO nfl_summary_checks(game_id,stats_hash,home_score,away_score) VALUES (?,?,?,?)',
              (game['id'],digest(rows),game.get('home_score'),game.get('away_score')))


def saved(game):
    with db.research_connect() as c:
        ensure(c)
        receipt=c.execute('SELECT * FROM nfl_summary_checks WHERE game_id=?',(game['id'],)).fetchone()
        if not receipt or any(receipt[k]!=game.get(k) for k in ('home_score','away_score')):return False
        rows=[dict(r) for r in c.execute("SELECT * FROM player_logs WHERE sport='NFL' AND game_id=?",(game['id'],))]
    return bool(rows) and receipt['stats_hash']==digest(rows)

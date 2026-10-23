"""Season roster positions, never emergency depth-chart eligibility."""
import json,re,datetime as dt
from pathlib import Path
from bs4 import BeautifulSoup
from . import db

NBA_POSITIONS={'PG','SG','SF','PF','C'}
REFERENCE_CODES={'BKN':'BRK','PHX':'PHO','GS':'GSW','NY':'NYK','NO':'NOP','SA':'SAS','UTAH':'UTA','WSH':'WAS','CHA':'CHO'}


def season():
    now=dt.date.today()
    return now.year+(now.month>=7)


def roster_url(team,year):
    return f'https://www.basketball-reference.com/teams/{REFERENCE_CODES.get(team,team)}/{year}.html'


def name_key(name):
    name=re.sub(r'\s+(?:Jr\.?|Sr\.?|II|III|IV)$','',str(name).strip(),flags=re.I)
    key=db.player_name_key(name)
    # The Detroit roster sources use Ron and Ronald for the same player.
    return {'ronaldholland':'ronholland'}.get(key,key)


def secondary_roster_url(team):
    directory=json.loads((Path(__file__).resolve().parent.parent/'static/teams/primary-roster-sources.json').read_text(encoding='utf-8'))
    return directory[team]


def parse_secondary_roster(html,year):
    soup=BeautifulSoup(html,'html.parser')
    if f'{year-1}-{str(year)[-2:]}' not in (soup.title.get_text() if soup.title else ''):
        raise ValueError('Position source returned a different season.')
    found={}
    for table in soup.select('table'):
        headings=[x.get_text(' ',strip=True).upper() for x in table.select('thead th')]
        if 'POS' not in headings or 'PLAYER' not in headings:continue
        column=headings.index('POS')
        for row in table.select('tbody tr'):
            cells=row.find_all('td',recursive=False)
            player=row.select_one('.CellPlayerName--long a')
            if player and len(cells)>column:
                pos=cells[column].get_text(strip=True)
                if pos in NBA_POSITIONS:found[name_key(player.get_text(strip=True))]=pos
    if len(found)<5:raise ValueError('Primary-position roster unavailable.')
    return found


def parse_roster(html,year):
    soup=BeautifulSoup(html,'html.parser')
    if f'{year-1}-{str(year)[-2:]}' not in (soup.title.get_text() if soup.title else ''):
        raise ValueError('Position source returned a different season.')
    table=soup.select_one('table#roster')
    if table is None:raise ValueError('Primary-position roster unavailable.')
    found={}
    for row in table.select('tbody tr'):
        player=row.select_one('[data-stat="player"] a')
        position=row.select_one('[data-stat="pos"]')
        if not player or not position:continue
        pos=position.get_text(strip=True)
        if pos not in NBA_POSITIONS:continue
        key=name_key(player.get_text(strip=True))
        if key in found and found[key]!=pos:raise ValueError('Ambiguous primary-position roster.')
        found[key]=pos
    if len(found)<5:raise ValueError('Incomplete primary-position roster.')
    return found


def seed_snapshot(connection):
    """Public, dated fallback when the roster source cannot be reached by a host."""
    connection.execute('CREATE TABLE IF NOT EXISTS position_index_sources(name TEXT PRIMARY KEY,version TEXT)')
    # Remove the old emergency-role expansion once; never edit original box scores.
    marker='nba-primary-only-v1'
    if not connection.execute('SELECT 1 FROM position_index_sources WHERE name=?',(marker,)).fetchone():
        connection.execute("DELETE FROM player_positions WHERE sport='NBA' AND (source_url LIKE '%/depthcharts' OR position IN ('G','F') OR position LIKE '%/%')")
        connection.execute('INSERT INTO position_index_sources VALUES (?,?)',(marker,'1'))
    path=Path(__file__).resolve().parent.parent/'static/teams'/f'primary-positions-{season()}.json'
    if not path.exists():return
    snapshot=json.loads(path.read_text(encoding='utf-8'));version=snapshot['observed_at']
    marker='nba-primary-snapshot-'+str(snapshot['season'])
    prior=connection.execute('SELECT version FROM position_index_sources WHERE name=?',(marker,)).fetchone()
    if prior and prior[0]==version:return
    for row in snapshot['players']:
        if row['position'] not in NBA_POSITIONS:continue
        values=('NBA',str(row['player_id']),row['team'],row['position'],row['source_url'],row.get('observed_at') or version)
        connection.execute('INSERT OR IGNORE INTO player_positions VALUES (?,?,?,?,?,?)',values)
        connection.execute("UPDATE player_search SET position=? WHERE sport='NBA' AND player_id=? AND team=?",(row['position'],str(row['player_id']),row['team']))
    connection.execute('INSERT OR REPLACE INTO position_index_sources VALUES (?,?)',(marker,version))

"""Season roster positions, never emergency depth-chart eligibility."""
import json,re,datetime as dt,time
from pathlib import Path
from bs4 import BeautifulSoup
from . import db

NBA_POSITIONS={'PG','SG','SF','PF','C'}
PROFILE_POSITIONS={'Point Guard':'PG','Shooting Guard':'SG','Small Forward':'SF','Power Forward':'PF','Center':'C'}
_profile_cache={}
_directory_cache={}
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


def profile_position(html):
    """Accept an explicit single primary position, never multi-position eligibility."""
    soup=BeautifulSoup(html,'html.parser');meta=soup.select_one('#meta')
    if not meta:return None
    for p in meta.select('p'):
        text=p.get_text(' ',strip=True)
        if 'Position:' not in text:continue
        value=re.split(r'▪|Shoots:',text.split('Position:',1)[1])[0].strip()
        return PROFILE_POSITIONS.get(value)
    return None


async def lookup_profile(client,name):
    """Public identity directory fallback for new signings missing from team rosters."""
    key=name_key(name);now=time.monotonic();cached=_profile_cache.get(key)
    if cached and now-cached[0]<(86400 if cached[1] else 3600):return cached[1]
    words=re.sub(r'\s+(?:Jr\.?|Sr\.?|II|III|IV)$','',name.strip(),flags=re.I).split()
    letter=name_key(words[-1])[:1] if words else ''
    if not re.fullmatch('[a-z]',letter):return None
    try:
        directory=_directory_cache.get(letter)
        if not directory or now-directory[0]>86400:
            response=await client.get(f'https://www.basketball-reference.com/players/{letter}/');response.raise_for_status()
            soup=BeautifulSoup(response.text,'html.parser');links={}
            for a in soup.select('table#players [data-stat="player"] a[href]'):
                href=a.get('href','')
                if re.fullmatch(r'/players/[a-z]/[a-z0-9]+\.html',href):
                    links.setdefault(name_key(a.get_text(strip=True)),set()).add(href)
            directory=(now,links);_directory_cache[letter]=directory
        matches=directory[1].get(key,set())
        result=None
        if len(matches)==1:
            url='https://www.basketball-reference.com'+next(iter(matches))
            response=await client.get(url);response.raise_for_status();pos=profile_position(response.text)
            if pos:result={'position':pos,'source_url':url}
        _profile_cache[key]=(now,result)
        return result
    except Exception:
        _profile_cache[key]=(now,None)
        return None


def secondary_roster_url(team):
    directory=json.loads((Path(__file__).resolve().parent.parent/'static/teams/primary-roster-sources.json').read_text(encoding='utf-8'))
    return directory['PHO' if team=='PHX' else team]


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
    marker='nba-primary-snapshot-v2-'+str(snapshot['season'])
    prior=connection.execute('SELECT version FROM position_index_sources WHERE name=?',(marker,)).fetchone()
    if prior and prior[0]==version:return
    # Old secondary-only additions outside the reviewed directory must be
    # reverified from a single-position profile before entering the metrics.
    connection.execute("DELETE FROM player_positions WHERE sport='NBA' AND source_url LIKE '%cbssports.com%'")
    for row in snapshot['players']:
        if row['position'] not in NBA_POSITIONS:continue
        values=('NBA',str(row['player_id']),row['team'],row['position'],row['source_url'],row.get('observed_at') or version)
        # Repair all teams' assignments overwritten by the old live-roster path.
        # The season directory is the authoritative assignment, not the last feed fetched.
        connection.execute('INSERT OR REPLACE INTO player_positions VALUES (?,?,?,?,?,?)',values)
        connection.execute("UPDATE player_search SET position=? WHERE sport='NBA' AND player_id=? AND team=?",(row['position'],str(row['player_id']),row['team']))
    connection.execute('INSERT OR REPLACE INTO position_index_sources VALUES (?,?)',(marker,version))

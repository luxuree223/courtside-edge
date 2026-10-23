"""Explicit public-source imports with real dates and shared ESPN identifiers."""
import csv
import io
import datetime
import httpx
from . import db, providers

NFL_SCHEDULE='https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'
NFL_PLAYERS='https://github.com/nflverse/nflverse-data/releases/download/players/players.csv'

async def download(client,url):
    # Limit the actual transfer, not just the decoded payload after it is in memory.
    async with client.stream('GET',url,timeout=90,follow_redirects=True) as response:
        response.raise_for_status()
        chunks=[];size=0
        async for chunk in response.aiter_bytes():
            size+=len(chunk)
            if size>90*1024*1024:raise ValueError('Source file exceeds 90 MB')
            chunks.append(chunk)
        return b''.join(chunks)

def csv_rows(raw):return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))

def import_nfl(raw,schedule_raw,players_raw,season,source_url):
    schedule={r['game_id']:r for r in csv_rows(schedule_raw) if r['season']==str(season)}
    if not schedule:raise ValueError('No schedule is published for that NFL season yet.')
    player_ids={r['gsis_id']:r['espn_id'] for r in csv_rows(players_raw) if r.get('gsis_id') and r.get('espn_id')}
    # Validate and normalize all player rows before writing the schedule.
    result=providers.ingest_csv(raw,'NFL',source='nflverse',source_url=source_url,schedule=schedule,player_ids=player_ids)
    with db.research_connect() as connection:
        for row in schedule.values():
            date=row['gameday']
            datetime.date.fromisoformat(date)
            home_score=providers.number(row.get('home_score'),None)
            away_score=providers.number(row.get('away_score'),None)
            final=home_score is not None and away_score is not None
            db.save_game(connection,{'id':row.get('espn') or 'nflverse:'+row['game_id'],'sport':'NFL',
                # Source supplies date and Eastern local kickoff, not a UTC timestamp.
                'starts_at':date,'home_id':'','away_id':'','home':row['home_team'],'away':row['away_team'],
                'home_abbr':row['home_team'],'away_abbr':row['away_team'],
                'home_score':home_score,'away_score':away_score,'status':'final' if final else 'scheduled',
                'season_type':'regular' if row['game_type']=='REG' else 'preseason' if row['game_type']=='PRE' else 'postseason'})
    result.update(games=len(schedule),note='Real schedule dates; player and game IDs matched to ESPN. Unmatched rows are skipped. Historical betting lines were not imported.')
    return result

async def import_season(sport,season):
    if sport=='NBA':
        url=f'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_player_boxscores/player_box_{season}.csv'
    elif sport=='NFL':
        url=f'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv'
    else:raise ValueError('Choose NBA or NFL')
    async with httpx.AsyncClient(headers={'User-Agent':providers.USER_AGENT}) as client:
        raw=await download(client,url)
        if sport=='NBA':return providers.ingest_csv(raw,'NBA',source='hoopR / ESPN',source_url=url)
        schedule_raw=await download(client,NFL_SCHEDULE)
        players_raw=await download(client,NFL_PLAYERS)
        return import_nfl(raw,schedule_raw,players_raw,season,url)

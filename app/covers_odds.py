"""Conservative adapter for the public Covers matchup odds tables.

Only signed American sportsbook prices are accepted. Prediction-market percentages,
props, page navigation tickers, and other games are excluded.
"""
import datetime
import json
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import httpx
from . import db,covers,providers,markets

BOOKS=('FanDuel','Caesars','DraftKings')
ALIASES={'JAC':'JAX','LA':'LAR','WSH':'WAS','GS':'GSW','NY':'NYK','NO':'NOP','SA':'SAS','UTAH':'UTA'}
def team_key(value):return ALIASES.get(value.upper(),value.upper())

def local_day(game):
    stamp=datetime.datetime.fromisoformat(game['starts_at'].replace('Z','+00:00'))
    if stamp.tzinfo:
        from zoneinfo import ZoneInfo
        stamp=stamp.astimezone(ZoneInfo(db.get_settings().get('timezone','America/Chicago')))
    return stamp.date()

def parse_odds(html,game,source_url):
    soup=BeautifulSoup(html,'html.parser')
    title=soup.title.get_text(' ',strip=True) if soup.title else ''
    day=local_day(game);expected=f'{day:%B} {day.day}, {day.year}'
    if expected.lower() not in title.lower() or game['sport'].lower() not in title.lower():
        raise ValueError('Covers date or league does not match the selected game. No prices were saved.')
    quotes=[];found=set();seen_markets=set()
    for article in soup.select('article.card'):
        heading=article.find('h2')
        kind={'Moneyline':'h2h','Spread':'spreads','Total':'totals'}.get(heading.get_text(' ',strip=True) if heading else '')
        if not kind:continue
        table=article.select_one('table.compareOddsTable')
        if not table:continue
        headers=[h.get_text(' ',strip=True).upper() for h in table.select('thead th')][1:]
        if kind=='totals':
            if headers!=['OVER','UNDER']:continue
            # The Game Odds caption identifies the matchup for totals, whose headers lack teams.
            captions=[c.get_text(' ',strip=True) for c in article.select('caption')]
            if not any(game['home'].lower() in c.lower() and game['away'].lower() in c.lower() for c in captions):
                # Exact team headers on the other full-game tables can establish identity.
                other=[team_key(h.get_text(strip=True)) for h in soup.select('article[id="1"] table.compareOddsTable thead th')][1:]
                if set(other)!={team_key(game['home_abbr']),team_key(game['away_abbr'])}:continue
        elif len(headers)!=2 or set(map(team_key,headers))!={team_key(game['home_abbr']),team_key(game['away_abbr'])}:
            continue
        seen_markets.add(kind)
        for row in table.select('tbody > tr'):
            logo=row.select_one('th img[alt]')
            label=logo.get('alt','').lower() if logo else ''
            book=next((b for b in BOOKS if markets.norm(b) in markets.norm(label)),None)
            if not book:continue
            found.add(book)
            cells=row.find_all('td',recursive=False)
            if len(cells)!=2:continue
            for header,cell in zip(headers,cells):
                price=cell.select_one('.oddsSideOddsText')
                text=price.get_text(strip=True).replace('\u2212','-') if price else ''
                if not re.fullmatch(r'[+-]\d{3,6}',text):continue
                try:american=markets.valid_odds(text)
                except ValueError:continue
                point=None
                if kind!='h2h':
                    line=cell.select_one('.oddsSideLineText')
                    raw=line.get_text(strip=True).replace('\u2212','-') if line else ''
                    if kind=='totals':raw=re.sub(r'^[ouOU]\s*','',raw)
                    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?',raw):continue
                    point=float(raw)
                selection=header.title() if kind=='totals' else game['home'] if team_key(header)==team_key(game['home_abbr']) else game['away']
                quotes.append({'book':book,'market':kind,'selection':selection,'point':point,'price':american})
    if not seen_markets:raise ValueError('Covers did not return recognizable odds tables for these teams. No prices were saved.')
    return {'quotes':quotes,'missing_books':[b for b in BOOKS if not any(q['book']==b for q in quotes)],
            'source_url':source_url,'title':title,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'provider_updated_at':None,'game_state':'unverified',
            'note':'Read from the public Covers page. Its sportsbook update time and overtime rules were not supplied. Confirm the full wager at the book. These are saved observations, not a prediction or a closing line.'}

async def get_page(client,url):
    # Fixed Covers host, no redirects, no arbitrary URLs or credentials.
    response=await client.get(url,follow_redirects=False,timeout=25)
    if response.status_code!=200:raise ValueError('Covers did not allow this request. No prices were guessed; open the page or try later.')
    if len(response.content)>5*1024*1024:raise ValueError('Covers returned an unexpectedly large page.')
    return response.text

async def find_matchup(client,game):
    html=await get_page(client,f'https://www.covers.com/sports/{game["sport"].lower()}/matchups')
    soup=BeautifulSoup(html,'html.parser')
    for card in soup.select('article.gamebox'):
        home=team_key(card.get('data-home-team-shortname',''));away=team_key(card.get('data-away-team-shortname',''))
        if home!=team_key(game['home_abbr']) or away!=team_key(game['away_abbr']):continue
        link=card.select_one('a.matchup-btn-link[href]')
        if link:return covers.validate_url(urljoin('https://www.covers.com',link['href']),game['sport'])
    raise ValueError('No matching game was found on Covers’ current schedule. Paste this game’s Covers matchup link. Dates and teams will be checked before saving.')

def saved(sport,game_id):
    with db.connect() as c:row=c.execute('SELECT payload FROM covers_game_odds WHERE sport=? AND game_id=?',(sport,game_id)).fetchone()
    return json.loads(row[0]) if row else None

async def refresh(sport,game_id,source_url=''):
    game=covers.game(sport,game_id)
    previous=saved(sport,game_id)
    # A short cache limits requests. The UI always shows the observation time.
    if previous and (datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(previous['observed_at'])).total_seconds()<120:
        if not source_url or covers.validate_url(source_url,sport)==previous['source_url'].removesuffix('/odds'):return {**previous,'cached':True}
    try:
        async with httpx.AsyncClient(headers={'User-Agent':providers.USER_AGENT}) as client:
            base=covers.validate_url(source_url,sport) if source_url else await find_matchup(client,game)
            odds_url=base+'/odds'
            payload=parse_odds(await get_page(client,odds_url),game,odds_url)
    except httpx.HTTPError:raise ValueError('Covers is unavailable right now. Your saved observations remain available with their original timestamps.')
    with db.connect() as c:
        c.execute('INSERT INTO covers_game_odds(sport,game_id,payload) VALUES (?,?,?) ON CONFLICT(sport,game_id) DO UPDATE SET payload=excluded.payload',(sport,game_id,json.dumps(payload)))
    return payload

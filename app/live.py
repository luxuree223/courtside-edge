"""Cached public scores and game-specific saved sportsbook quotes."""
import asyncio, datetime as dt, json, math, re
from zoneinfo import ZoneInfo
import httpx
from . import db,providers,markets,covers,covers_odds,props

SCHEMA="""CREATE TABLE IF NOT EXISTS live_scoreboards (
 sport TEXT NOT NULL, game_date TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(sport,game_date));
 CREATE TABLE IF NOT EXISTS game_market_snapshots (
 sport TEXT NOT NULL,game_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(sport,game_id));"""
_locks={}
_price_locks={}

def now():return dt.datetime.now(dt.timezone.utc)
def age(stamp):
    try:return (now()-dt.datetime.fromisoformat(stamp.replace('Z','+00:00'))).total_seconds()
    except (ValueError,TypeError,AttributeError):return float('inf')

def saved_board(sport,date):
    with db.connect() as c:row=c.execute('SELECT payload FROM live_scoreboards WHERE sport=? AND game_date=?',(sport,date)).fetchone()
    return json.loads(row[0]) if row else None

async def scoreboard(sport,date,force=False):
    if sport not in providers.SPORT_PATH:raise ValueError('Choose NBA or NFL.')
    chosen=dt.date.fromisoformat(date)
    async with _locks.setdefault((sport,date),asyncio.Lock()):
        old=saved_board(sport,date)
        if old and not force and age(old['fetched_at'])<25:return {**old,'cached':True,'stale':False}
        url=f'{providers.BASE}/{providers.SPORT_PATH[sport]}/scoreboard?dates={chosen:%Y%m%d}&limit=1000'
        try:
            async with httpx.AsyncClient(headers={'User-Agent':providers.USER_AGENT}) as client:payload=await providers.fetch_json(client,url)
            if not isinstance(payload,dict) or 'events' not in payload:raise ValueError('Scoreboard format changed')
            rows=providers.parse_scoreboard(payload,sport);stamp=now().isoformat()
            references={r['game_id']:r for r in providers.scoreboard_betting_lines(payload,sport)}
            for game in rows:
                for key in ('home_abbr','away_abbr'):game[key]=db.normalize_team(sport,game[key])
                game.update(score_fetched_at=stamp,score_source_url=url)
                if game['id'] in references:game['espn_reference']=references[game['id']]
            result={'games':rows,'source_url':url,'fetched_at':stamp,'stale':False}
            with db.connect() as c:
                for game in rows:db.save_game(c,game)
                c.execute('INSERT INTO live_scoreboards VALUES (?,?,?) ON CONFLICT(sport,game_date) DO UPDATE SET payload=excluded.payload',(sport,date,json.dumps(result)))
            return result
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            if old:return {**old,'stale':True,'error':'Score update unavailable. Showing the last saved scores.'}
            games=[g for g in db.games_list(sport,limit=3000) if providers.iso_day(g['starts_at'],db.get_settings().get('timezone','America/Chicago'))==date]
            return {'games':games,'source_url':url,'fetched_at':None,'stale':True,'error':'Score update unavailable. Showing saved game data.'}

def saved_prices(sport,game_id):
    with db.connect() as c:row=c.execute('SELECT payload FROM game_market_snapshots WHERE sport=? AND game_id=?',(sport,game_id)).fetchone()
    return json.loads(row[0]) if row else None

def parse_prices(payload,game):
    if not isinstance(payload,dict) or not props.same_event(payload,game):raise ValueError('The odds feed did not match this game and date.')
    result=[]
    for book in payload.get('bookmakers',[]):
        title=props.BOOKS.get(book.get('key'))
        if not title:continue
        for market in book.get('markets',[]):
            kind=market.get('key')
            if kind not in ('h2h','spreads','totals'):continue
            for outcome in market.get('outcomes',[]):
                name=outcome.get('name','')
                if kind=='totals':
                    if name not in ('Over','Under'):continue
                elif markets.norm(name) not in (markets.norm(game['home']),markets.norm(game['away'])):continue
                try:
                    raw=float(outcome.get('price'))
                    if not math.isfinite(raw) or raw!=int(raw):continue
                    price=markets.valid_odds(raw)
                    point=None if kind=='h2h' else float(outcome['point'])
                    if point is not None and not math.isfinite(point):continue
                except (ValueError,TypeError,KeyError):continue
                result.append({'book':title,'market':kind,'selection':name,'point':point,'price':price,
                               'provider_updated_at':market.get('last_update') or book.get('last_update')})
    return result

async def fetch_prices(game):
    key=markets.get_key()
    if not key:raise ValueError('Connect your odds key in Find Value for your three books.')
    base=markets.ODDS_HOST+'/v4/sports/'+markets.LEAGUES[game['sport']]
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r=await client.get(base+'/events',params={'apiKey':key});r.raise_for_status();events=r.json()
            if not isinstance(events,list):raise ValueError('Odds event list unavailable.')
            matches=[e for e in events if props.same_event(e,game)]
            if len(matches)!=1:raise ValueError('This game is no longer available or could not be matched in the odds feed.')
            identity=str(matches[0].get('id',''))
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',identity):raise ValueError('Invalid odds event identifier.')
            r=await client.get(base+'/events/'+identity+'/odds',params={'apiKey':key,'markets':'h2h,spreads,totals','bookmakers':','.join(props.BOOKS),'oddsFormat':'american'})
            r.raise_for_status();quotes=parse_prices(r.json(),game)
    except httpx.HTTPStatusError as ex:raise ValueError('Odds source refused the request ('+str(ex.response.status_code)+'). Check quota and access in Find Value.') from None
    except httpx.HTTPError:raise ValueError('Could not update sportsbook prices. Saved observations remain available.') from None
    return {'quotes':quotes,'source':'TheOddsAPI','source_url':'https://the-odds-api.com/','observed_at':now().isoformat(),
            'observed_game_state':game['status'],'note':'Saved sportsbook observations. Game status at retrieval does not certify that every book quote is an in-play market.'}

def fallback_prices(game):
    existing=covers_odds.saved(game['sport'],game['id'])
    if existing and existing.get('quotes'):
        return {**existing,'source':'Covers.com','observed_game_state':'unknown'}
    date=providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago'))
    # Legacy odds may have stored UTC game dates. Require exact teams and the selected game's local/UTC dates.
    with db.connect() as c:
        rows=[dict(r) for r in c.execute('SELECT * FROM market_quotes WHERE sport=? AND game_date IN (?,?) AND market IN (?,?,?)',(game['sport'],date,game['starts_at'][:10],'h2h','spreads','totals'))]
    rows=[q for q in rows if q['book'] in props.BOOKS.values() and markets.norm(q['home'])==markets.norm(game['home']) and markets.norm(q['away'])==markets.norm(game['away'])]
    quotes=[{'book':q['book'],'market':q['market'],'selection':q['selection'],'point':float(q['point_key']) if q['point_key'] else None,'price':q['price'],'provider_updated_at':q.get('provider_updated_at') or None} for q in rows]
    return {'quotes':quotes,'observed_at':max((q['updated_at'].replace(' ','T')+'Z' for q in rows),default=None),
            'observed_game_state':'unknown','source':'Saved quotes','note':'Saved observations; original game phase is unknown. Refresh prices for a new observation.'}

async def overview(sport,game_id,refresh_odds=False):
    game=covers.game(sport,game_id);date=providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago'))
    board=await scoreboard(sport,date)
    current=next((g for g in board['games'] if g['id']==game_id),game)
    prices=saved_prices(sport,game_id);error=''
    if refresh_odds and markets.get_key() and current['status']!='final':
        async with _price_locks.setdefault((sport,game_id),asyncio.Lock()):
            prices=saved_prices(sport,game_id)
            if not prices or age(prices.get('observed_at'))>=120:
                try:
                    fresh=await fetch_prices(current)
                    if fresh['quotes']:
                        prices=fresh
                        with db.connect() as c:c.execute('INSERT INTO game_market_snapshots VALUES (?,?,?) ON CONFLICT(sport,game_id) DO UPDATE SET payload=excluded.payload',(sport,game_id,json.dumps(prices)))
                        rows=[{'sport':sport,'home':game['home'],'away':game['away'],'game_date':date,'market':q['market'],'selection':q['selection'],'point':q['point'],'book':q['book'],'price':q['price'],'source':'TheOddsAPI','provider_updated_at':q['provider_updated_at'],'commence_time':game['starts_at'],'observed_game_state':current['status']} for q in fresh['quotes']]
                        markets.save_quotes(rows)
                    else:error='No prices returned at your three books. Saved quotes may be off the board.'
                except ValueError as ex:error=str(ex)
    if not prices:prices=fallback_prices(current)
    if current['status']=='final':error='Game finished. Any prices below are saved observations, not an available betting market.'
    return {'game':current,'score_fetched_at':board.get('fetched_at'),'score_source_url':board.get('source_url'),'score_stale':board.get('stale',False),'score_error':board.get('error',''),
            'prices':prices,'odds_error':error,'odds_connected':bool(markets.get_key())}

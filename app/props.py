"""Game-specific player quotes and exact-line historical checks, separate from wagers."""
import datetime as dt
import hashlib
import math
import re
import unicodedata
from urllib.parse import urlsplit
import httpx
from . import db, markets, providers, covers

SCHEMA = """CREATE TABLE IF NOT EXISTS player_prop_quotes (
 id TEXT PRIMARY KEY,sport TEXT NOT NULL,game_id TEXT NOT NULL,
 player TEXT NOT NULL,stat TEXT NOT NULL,side TEXT NOT NULL,line REAL NOT NULL,
 price INTEGER NOT NULL,book TEXT NOT NULL,source TEXT NOT NULL,source_url TEXT NOT NULL,
 observed_at TEXT NOT NULL,provider_updated_at TEXT);
 CREATE INDEX IF NOT EXISTS props_by_game ON player_prop_quotes(sport,game_id);"""
BOOKS={'fanduel':'FanDuel','draftkings':'DraftKings','williamhill_us':'Caesars'}
MARKETS={'NBA':{'pts':'player_points','reb':'player_rebounds','ast':'player_assists','fg3m':'player_threes',
 'pra':'player_points_rebounds_assists','pr':'player_points_rebounds','pa':'player_points_assists',
 'ra':'player_rebounds_assists','stl':'player_steals','blk':'player_blocks'},
 'NFL':{'rec':'player_receptions','rec_yds':'player_reception_yds','rush_yds':'player_rush_yds',
 'rush_att':'player_rush_attempts','pass_yds':'player_pass_yds','pass_td':'player_pass_tds',
 'rush_td':'player_rush_tds','rec_td':'player_reception_tds'}}


def name_key(value):
    text=unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().lower()
    parts=re.findall(r'[a-z0-9]+',text)
    if parts and parts[-1] in ('jr','sr','ii','iii','iv'):parts.pop()
    return ''.join(parts)


def game_players(game):
    cutoff=providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago'))
    with db.connect() as c:
        rows=c.execute('SELECT player_id,player,team,position,game_date FROM player_logs WHERE sport=? AND game_date<? ORDER BY game_date DESC,game_id DESC',(game['sport'],cutoff)).fetchall()
    latest={}
    for row in rows:
        player=latest.setdefault(row['player_id'],dict(row))
        if not player['position'] and row['position']:player['position']=row['position']
    return sorted([r for r in latest.values() if r['team'] in (game['home_abbr'],game['away_abbr'])],key=lambda r:r['player'])


def match_player(quote,players):
    matches=[p for p in players if name_key(p['player'])==name_key(quote['player'])]
    return matches[0] if len(matches)==1 else None


def public_quote(quote,players):
    found=match_player(quote,players)
    return {**quote,'player_id':found['player_id'] if found else None,'team':found['team'] if found else None,'position':found['position'] if found else '',
            'history_available':bool(found),'label':'Entered by you' if quote['source']=='manual' else 'Odds feed'}


def validate_quote(game,player,stat,side,line,price,book,source_url=''):
    if stat not in MARKETS[game['sport']]:raise ValueError('Choose a supported prop for this sport.')
    if side not in ('Over','Under'):raise ValueError('Choose Over or Under.')
    try:line=float(line)
    except (ValueError,TypeError):raise ValueError('Enter a valid prop line.')
    if not math.isfinite(line) or line<0 or line>10000:raise ValueError('Enter a valid prop line.')
    if not player.strip() or len(player)>150:raise ValueError('Choose or enter the player name.')
    if book not in BOOKS.values():raise ValueError('Choose FanDuel, Caesars or DraftKings.')
    try:
        if not math.isfinite(float(price)) or float(price)!=int(float(price)):raise ValueError()
    except (ValueError,TypeError,OverflowError):raise ValueError('Enter whole-number American odds such as -110.')
    if source_url:
        u=urlsplit(source_url)
        if u.scheme!='https' or not u.hostname or u.username or u.password:raise ValueError('Use an https source link without account details.')
    return {'sport':game['sport'],'game_id':game['id'],'player':player.strip(),'stat':stat,'side':side,
            'line':line,'price':markets.valid_odds(price),'book':book,'source_url':source_url[:500]}


def save(quote,source='manual',provider_updated_at=None):
    quote={**quote,'source':source,'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'provider_updated_at':provider_updated_at}
    key='|'.join(str(quote[k]) for k in ('sport','game_id','player','stat','side','line','book','source'))
    quote['id']=hashlib.sha256(key.encode()).hexdigest()[:32]
    columns=['id','sport','game_id','player','stat','side','line','price','book','source','source_url','observed_at','provider_updated_at']
    with db.connect() as c:
        c.execute('INSERT INTO player_prop_quotes ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+') ON CONFLICT(id) DO UPDATE SET price=excluded.price,observed_at=excluded.observed_at,provider_updated_at=excluded.provider_updated_at,source_url=excluded.source_url',[quote[k] for k in columns])
    return quote


def history_window(game,include_previous=False):
    from .stat_logs import season_window
    date=dt.date.fromisoformat(providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago')))
    return season_window(game['sport'],'recent' if include_previous else 'current',as_of=date)


def listed(sport,game_id,include_previous=False):
    game=covers.game(sport,game_id);players=game_players(game)
    with db.connect() as c:rows=[dict(r) for r in c.execute('SELECT * FROM player_prop_quotes WHERE sport=? AND game_id=? ORDER BY player,stat,line,book,side',(sport,game_id))]
    quotes=[public_quote(row,players) for row in rows]
    before=providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago'))
    for quote,counts in zip(quotes,recent_counts(game,quotes,before,include_previous)):quote['recent']=counts
    return {'quotes':quotes,'players':players,'feed_configured':bool(markets.get_key()),'history_before':before,'history_season_type':game['season_type'],
            'history_window':history_window(game,include_previous),'include_previous':include_previous,
            'books':list(BOOKS.values()),'note':'Player matches use names and their latest saved team before game day. This is not a verified active roster.'}


def recent_counts(game,quotes,before,include_previous=False):
    """One read for all exact lines; windows include unknown stats, never future games."""
    ids={q['player_id'] for q in quotes if q.get('player_id')}
    groups={pid:[] for pid in ids}
    if ids:
        with db.connect() as c:
            start=history_window(game,include_previous)['start']
            rows=c.execute("SELECT p.* FROM player_logs p LEFT JOIN games g ON g.sport=p.sport AND g.id=p.game_id WHERE p.sport=? AND p.season_type=? AND p.game_date<? AND p.game_date>=? AND (g.id IS NULL OR g.status='final') AND p.player_id IN ("+','.join('?' for _ in ids)+') ORDER BY p.game_date DESC,p.game_id DESC',(game['sport'],game['season_type'],before,start,*ids))
            for r in rows:
                if game['sport']=='NBA' and (r['minutes'] or 0)<=0:continue
                if len(groups[r['player_id']])<10:groups[r['player_id']].append(dict(r))
    cache={};out=[]
    for q in quotes:
        key=(q.get('player_id'),q['stat'],q['side'],q['line'])
        if key not in cache:
            result={}
            for n in (5,10):
                window=groups.get(q.get('player_id'),[])[:n]
                values=[v for r in window if (v:=db.stat_value(r,q['stat'])) is not None]
                hits=sum(v>q['line'] if q['side']=='Over' else v<q['line'] for v in values)
                pushes=sum(v==q['line'] for v in values)
                result['last'+str(n)]={'requested':n,'games':len(window),'sample':len(values),'hits':hits,'pushes':pushes,
                                      'missing':len(window)-len(values),'rate':round(100*hits/len(values),1) if values else None}
            cache[key]=result
        out.append(cache[key])
    return out


def same_event(event,game):
    return (markets.norm(event.get('home_team'))==markets.norm(game['home']) and
            markets.norm(event.get('away_team'))==markets.norm(game['away']) and
            providers.iso_day(event.get('commence_time',''),db.get_settings().get('timezone','America/Chicago'))==providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago')))


def parse_event(payload,game,stats):
    if not isinstance(payload,dict):raise ValueError('The prop feed returned an unexpected response. No prices were saved.')
    if not same_event(payload,game):raise ValueError('The prop feed returned a different game or date. No prices were saved.')
    reverse={value:key for key,value in MARKETS[game['sport']].items() if key in stats}
    result=[]
    for book in payload.get('bookmakers',[]):
        label=BOOKS.get(book.get('key'))
        if not label:continue
        for market in book.get('markets',[]):
            stat=reverse.get(market.get('key'))
            if not stat:continue
            for outcome in market.get('outcomes',[]):
                if not outcome.get('description') or outcome.get('point') is None:continue
                try:quote=validate_quote(game,outcome['description'],stat,outcome.get('name'),outcome['point'],outcome.get('price'),label,'https://the-odds-api.com/')
                except ValueError:continue
                result.append((quote,market.get('last_update')))
    return result


async def refresh(sport,game_id,stat='',include_previous=False):
    game=covers.game(sport,game_id)
    if sport not in MARKETS:raise ValueError('Choose NBA or NFL.')
    stats=[stat] if stat else list(MARKETS[sport])
    if any(s not in MARKETS[sport] for s in stats):raise ValueError('Choose a supported prop category.')
    key=markets.get_key()
    if not key:raise ValueError('Connect your odds API key in Find Value for automatic player props. Prop coverage depends on your plan. You can enter a sportsbook line below now.')
    base=markets.ODDS_HOST+'/v4/sports/'+markets.LEAGUES[sport]
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response=await client.get(base+'/events',params={'apiKey':key});response.raise_for_status();events=response.json()
            if not isinstance(events,list):raise ValueError('The odds service returned an unexpected game list.')
            matches=[event for event in events if same_event(event,game)]
            if len(matches)!=1:raise ValueError('This game could not be matched uniquely in the prop feed. No prices were guessed.')
            event_id=str(matches[0].get('id',''))
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',event_id):raise ValueError('The odds service returned an invalid game identifier.')
            response=await client.get(base+'/events/'+event_id+'/odds',params={'apiKey':key,'markets':','.join(MARKETS[sport][s] for s in stats),'bookmakers':','.join(BOOKS),'oddsFormat':'american'})
            response.raise_for_status();quotes=parse_event(response.json(),game,stats)
    except httpx.HTTPStatusError as ex:
        raise ValueError('The odds provider refused the prop request ('+str(ex.response.status_code)+'). Check the key, quota and player-prop access on your plan.') from None
    except (httpx.HTTPError,TypeError,KeyError):raise ValueError('The player-prop feed is unavailable. Your saved lines remain available.') from None
    # Replace only successful returned coverage, leaving manually entered lines intact.
    # An empty feed may mean temporarily off-board; saved observations stay visible with timestamps.
    if quotes:
        with db.connect() as c:
            c.execute('DELETE FROM player_prop_quotes WHERE sport=? AND game_id=? AND source=? AND stat IN ('+','.join('?' for _ in stats)+')',(sport,game_id,'TheOddsAPI',*stats))
            for quote,updated in quotes:
                source='TheOddsAPI';observed=dt.datetime.now(dt.timezone.utc).isoformat()
                identity=hashlib.sha256('|'.join(str(quote[k]) for k in ('sport','game_id','player','stat','side','line','book')).encode()).hexdigest()[:32]
                cols=['id','sport','game_id','player','stat','side','line','price','book','source','source_url','observed_at','provider_updated_at']
                values={'id':identity,**quote,'source':source,'observed_at':observed,'provider_updated_at':updated}
                c.execute('INSERT OR REPLACE INTO player_prop_quotes ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',[values[k] for k in cols])
    return {**listed(sport,game_id,include_previous),'received':len(quotes),'message':f'{len(quotes)} player-prop prices received.' if quotes else 'No prices returned for this category at your three books. Saved observations remain below; they may be off the board.'}


def history(quote_id,n=10,season_type='regular',player_id='',date_from=None,date_to=None,season_types=None,include_previous=False):
    if not 1<=n<=100:raise ValueError('Choose 1 to 100 past games.')
    if season_type not in ('regular','preseason','postseason'):raise ValueError('Choose regular season, preseason or playoffs.')
    with db.connect() as c:row=c.execute('SELECT * FROM player_prop_quotes WHERE id=?',(quote_id,)).fetchone()
    if not row:raise ValueError('Saved prop not found.')
    quote=dict(row);game=covers.game(quote['sport'],quote['game_id']);players=game_players(game)
    matched=match_player(quote,players)
    if player_id:
        matched=next((p for p in players if p['player_id']==player_id),None)
        if not matched:raise ValueError('Choose a saved player from this game’s teams.')
    cutoff=providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago'))
    if date_from is None:date_from=history_window(game,include_previous)['start']
    if not matched:return {'quote':quote,'unmatched':True,'players':players,'message':'No unique saved player matched this name. Choose the correct saved player to check history.'}
    with db.connect() as c:
        kinds=season_types or [season_type]
        sql='SELECT * FROM player_logs WHERE sport=? AND player_id=? AND season_type IN ('+','.join('?' for _ in kinds)+') AND game_date<?'
        args=[quote['sport'],matched['player_id'],*kinds,cutoff]
        if date_from:sql+=' AND game_date>=?';args.append(date_from)
        if date_to:sql+=' AND game_date<?';args.append(date_to)
        rows=[dict(r) for r in c.execute(sql+' ORDER BY game_date DESC,game_id DESC',args)]
    logs=[];window_games=0;missing_stats=0
    for row in rows:
        if quote['sport']=='NBA' and (row['minutes'] or 0)<=0:continue
        if window_games>=n:break
        window_games+=1
        value=db.stat_value(row,quote['stat'])
        if value is None:missing_stats+=1;continue
        result='push' if value==quote['line'] else 'hit' if (value>quote['line'] if quote['side']=='Over' else value<quote['line']) else 'miss'
        logs.append({'date':row['game_date'],'opponent':row['opponent'],'value':value,'result':result,'minutes':row['minutes'],'source':row['source'],'source_url':row['source_url']})
    hits=sum(r['result']=='hit' for r in logs);pushes=sum(r['result']=='push' for r in logs);sample=len(logs)
    return {'quote':quote,'player':matched,'manual_player_match':bool(player_id),'requested':n,'window_games':window_games,'missing_stats':missing_stats,'sample':sample,'hits':hits,'pushes':pushes,'misses':sample-hits-pushes,
            'rate':round(100*hits/sample,1) if sample else None,'settled_rate':round(100*hits/(sample-pushes),1) if sample>pushes else None,
            'logs':logs,'before':cutoff,'season_type':'+'.join(kinds),'game_types':kinds,'message':'These are past results against this one line, not historical closing lines or a forecast.'}

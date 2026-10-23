"""Explicit per-account odds-provider selection. Keys never leave server storage."""
import datetime as dt
import httpx
from . import db, markets, providers

HOST='https://api.sportsgameodds.com/v2'
STATS={'points':'pts','rebounds':'reb','assists':'ast','threePointersMade':'fg3m','three_pointers_made':'fg3m',
 'steals':'stl','blocks':'blk','points+rebounds+assists':'pra','points+rebounds':'pr','points+assists':'pa','rebounds+assists':'ra',
 'passing_yards':'pass_yds','passing_touchdowns':'pass_td','rushing_yards':'rush_yds','rushing_touchdowns':'rush_td',
 'receiving_yards':'rec_yds','receiving_touchdowns':'rec_td','receptions':'rec','rushing_attempts':'rush_att'}
BOOKS={'fanduel':'FanDuel','draftkings':'DraftKings','caesars':'Caesars'}

def selected():
    with db.connect() as c:r=c.execute("SELECT value FROM settings WHERE key='odds_provider'").fetchone()
    return r[0] if r and r[0] in ('theoddsapi','sportsgameodds') else 'theoddsapi'

def key(provider='sportsgameodds'):
    if provider=='theoddsapi':return markets.get_key()
    with db.connect() as c:r=c.execute('SELECT value FROM bookmaker_keys WHERE provider=?',(provider,)).fetchone()
    return r[0] if r else ''

def status():return {'selected':selected(),'providers':[{'id':p,'name':name,'connected':bool(key(p))} for p,name in [('theoddsapi','The Odds API'),('sportsgameodds','SportsGameOdds')]]}

def configure(provider,api_key=''):
    if provider not in ('theoddsapi','sportsgameodds'):raise ValueError('Choose a supported odds source.')
    if api_key:
        import re
        if not re.fullmatch(r'[a-zA-Z0-9_-]{12,250}',api_key):raise ValueError('Enter the API key issued by this provider.')
        with db.connect() as c:c.execute('INSERT OR REPLACE INTO bookmaker_keys VALUES (?,?)',(provider,api_key))
    with db.connect() as c:c.execute("INSERT OR REPLACE INTO settings VALUES ('odds_provider',?)",(provider,))
    return status()

def same_game(event,game):
    teams=event.get('teams') or {};zone=db.get_settings().get('timezone','America/Chicago')
    def code(side):
        value=(teams.get(side,{}).get('names') or {}).get('short','')
        return db.normalize_team(game['sport'],value)
    return code('home')==db.normalize_team(game['sport'],game['home_abbr']) and code('away')==db.normalize_team(game['sport'],game['away_abbr']) and providers.iso_day((event.get('status') or {}).get('startsAt'),zone)==providers.iso_day(game['starts_at'],zone)

def parse(event,game,stats):
    from . import props
    if not same_game(event,game):raise ValueError('SportsGameOdds returned a different game or date. No prices were saved.')
    rows=[];people=event.get('players') or {}
    for odd in (event.get('odds') or {}).values():
        stat=STATS.get(odd.get('statID'));person=people.get(odd.get('statEntityID'))
        if not person or stat not in stats or odd.get('periodID')!='game' or odd.get('betTypeID')!='ou' or odd.get('ended') or odd.get('cancelled'):continue
        side={'over':'Over','under':'Under'}.get(odd.get('sideID'))
        for book,quote in (odd.get('byBookmaker') or {}).items():
            if book not in BOOKS or not quote.get('available',False) or quote.get('overUnder') is None:continue
            try:q=props.validate_quote(game,person.get('name') or ' '.join([person.get('firstName',''),person.get('lastName','')]),stat,side,quote['overUnder'],quote.get('odds'),BOOKS[book],quote.get('deeplink') or 'https://sportsgameodds.com/')
            except ValueError:continue
            rows.append((q,quote.get('lastUpdatedAt')))
    return rows

async def refresh(game,stats,include_previous=False):
    from . import props
    api_key=key()
    if not api_key:raise ValueError('Add your SportsGameOdds key in Settings → Odds sources.')
    zone=db.get_settings().get('timezone','America/Chicago');date=dt.date.fromisoformat(providers.iso_day(game['starts_at'],zone))
    params={'leagueID':game['sport'],'oddsAvailable':'true','startsAfter':(date-dt.timedelta(days=1)).isoformat(),'startsBefore':(date+dt.timedelta(days=2)).isoformat(),'limit':50}
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response=await client.get(HOST+'/events',params=params,headers={'x-api-key':api_key});response.raise_for_status();data=response.json()
    except httpx.HTTPError:raise ValueError('SportsGameOdds could not supply these props. Check the key, coverage and request allowance; saved quotes remain available.')
    matches=[e for e in data.get('data',[]) if same_game(e,game)]
    if len(matches)!=1:raise ValueError('This game could not be matched uniquely in SportsGameOdds. No prices were guessed.')
    quotes=parse(matches[0],game,stats)
    for q,stamp in quotes:props.save(q,'SportsGameOdds',stamp)
    return {**props.listed(game['sport'],game['id'],include_previous),'received':len(quotes),'message':f'{len(quotes)} SportsGameOdds player-prop prices received.'}

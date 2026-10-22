"""Bookmaker price comparisons, saved team lines, and plain-English research.
Free-source odds are optional. Never invent odds or promote a price gap as proven EV.
"""
import datetime, json, math, os, re, statistics
from collections import defaultdict
import httpx
from . import db

ODDS_HOST='https://api.the-odds-api.com'
LEAGUES={'NBA':'basketball_nba','NFL':'americanfootball_nfl'}

SCHEMA='''
CREATE TABLE IF NOT EXISTS bookmaker_keys (provider TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS market_quotes (
  sport TEXT NOT NULL, event_key TEXT NOT NULL, game_date TEXT NOT NULL,
  home TEXT NOT NULL, away TEXT NOT NULL, market TEXT NOT NULL,
  selection TEXT NOT NULL, point_key TEXT NOT NULL DEFAULT '',
  book TEXT NOT NULL, price INTEGER NOT NULL, source TEXT NOT NULL DEFAULT 'manual',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(sport,event_key,market,selection,point_key,book)
);
CREATE INDEX IF NOT EXISTS market_quotes_by_sport ON market_quotes(sport,game_date);
CREATE TABLE IF NOT EXISTS game_betting_lines (
  sport TEXT NOT NULL, game_id TEXT NOT NULL, home_spread REAL, total_line REAL,
  source TEXT NOT NULL DEFAULT 'manual', saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(sport,game_id)
);
'''

def init_market_tables():
    with db.connect() as conn:conn.executescript(SCHEMA)

def set_key(api_key):
    k=str(api_key or '').strip()
    if not 12<=len(k)<=250 or not re.fullmatch(r'[\w-]+',k):raise ValueError('Enter the API key from your odds provider.')
    with db.connect() as conn:
        conn.execute('INSERT INTO bookmaker_keys(provider,value) VALUES (?,?) ON CONFLICT(provider) DO UPDATE SET value=excluded.value',('theoddsapi',k))

def get_key():
    if os.environ.get('EDGE_ODDS_API_KEY') and (db.PROFILE_PATH.get() is None or os.environ.get('EDGE_SHARED_PROVIDER_KEYS')=='1'):return os.environ['EDGE_ODDS_API_KEY']
    with db.connect() as conn:
        r=conn.execute('SELECT value FROM bookmaker_keys WHERE provider=?',('theoddsapi',)).fetchone()
        return r[0] if r else ''

def key_status():
    with db.connect() as conn:
        r=conn.execute('SELECT COUNT(*),MAX(updated_at) FROM market_quotes').fetchone()
    return {'connected':bool(get_key()),'saved_prices':r[0],'last_saved':r[1],'provider':'TheOddsAPI','free_markets':'NBA and NFL moneylines (subject to provider plan)'}

def norm(s):
    return re.sub(r'[^a-z0-9]+','',str(s or '').lower())

def event_key(sport, home, away, game_date):
    return f'{sport}:{game_date[:10]}:{norm(home)}:{norm(away)}'

def valid_odds(price):
    try:
        x=int(price)
        if x==0 or abs(x)<100 or abs(x)>100000:raise ValueError()
        return x
    except (ValueError,TypeError,OverflowError):raise ValueError('Enter American odds such as +120 or -110')

def probability(american):
    a=valid_odds(american)
    return 100/(100+a) if a>0 else -a/(100-a)

def decimal_odds(american):
    a=valid_odds(american)
    return 1+a/100 if a>0 else 1+100/-a

def point_text(p):
    if p is None or p=='':return ''
    try:
        if not math.isfinite(float(p)):raise ValueError()
        return str(round(float(p),3)).rstrip('0').rstrip('.') if '.' in str(round(float(p),3)) else str(int(float(p)))
    except (ValueError,TypeError):raise ValueError('Enter a valid line number')

def game_context(sport,home,away,date,commence_time='',games=None):
    from . import providers
    if games is None:
        with db.connect() as c:games=[dict(r) for r in c.execute('SELECT * FROM games WHERE sport=?',(sport,))]
    zone=db.get_settings().get('timezone','America/Chicago')
    found=[g for g in games if norm(g['home'])==norm(home) and norm(g['away'])==norm(away) and date in (g['starts_at'][:10],providers.iso_day(g['starts_at'],zone))]
    if commence_time:
        day=providers.iso_day(commence_time,zone)
        found=[g for g in found if providers.iso_day(g['starts_at'],zone)==day]
    if len(found)!=1:return None
    return {**found[0],'local_date':providers.iso_day(found[0]['starts_at'],zone)}

def save_quotes(quotes):
    if len(quotes)>10000:raise ValueError('Too many odds rows')
    valid=[];batch=datetime.datetime.now(datetime.timezone.utc).isoformat()
    for q in quotes:
        sport=str(q.get('sport','')).upper()
        if sport not in LEAGUES:continue
        home=str(q.get('home','')).strip()[:110];away=str(q.get('away','')).strip()[:110]
        when=str(q.get('game_date',''))[:10]
        if not home or not away or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',when):continue
        market=str(q.get('market','h2h'))[:55]
        selection=str(q.get('selection',''))[:150]
        book=str(q.get('book',''))[:80]
        if not book or not selection:continue
        point=point_text(q.get('point'))
        price=valid_odds(q.get('price'))
        valid.append((sport,event_key(sport,home,away,when),when,home,away,market,selection,point,book,price,
                      str(q.get('source','manual'))[:45],str(q.get('commence_time') or ''),str(q.get('provider_updated_at') or ''),str(q.get('observed_game_state') or (game_context(sport,home,away,when,q.get('commence_time','')) or {}).get('status','unknown')),batch if q.get('source')=='TheOddsAPI' else ''))
    with db.connect() as conn:
        conn.executemany('''INSERT INTO market_quotes(sport,event_key,game_date,home,away,market,selection,point_key,book,price,source,commence_time,provider_updated_at,observed_game_state,batch_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sport,event_key,market,selection,point_key,book)
            DO UPDATE SET price=excluded.price,source=excluded.source,commence_time=excluded.commence_time,provider_updated_at=excluded.provider_updated_at,observed_game_state=excluded.observed_game_state,batch_id=excluded.batch_id,updated_at=CURRENT_TIMESTAMP''',valid)
    return len(valid)

def flatten_api_odds(payload, sport):
    """Accept both new normalized /odds/ and legacy-compatible bookmaker structures."""
    events=payload.get('data',[]) if isinstance(payload,dict) else payload
    if isinstance(events,dict):events=events.get('events',events.get('data',[]))
    if not isinstance(events,list):raise ValueError('Odds provider returned an unexpected format')
    out=[]
    for game in events:
        if not isinstance(game,dict):continue
        home=game.get('home_team') or game.get('home')
        away=game.get('away_team') or game.get('away')
        commence=(game.get('start_time') or game.get('commence_time') or game.get('commenceTime') or '')
        from . import providers
        date=providers.iso_day(commence,db.get_settings().get('timezone','America/Chicago'))
        if not home or not away or not date:continue
        # New API shape: event.markets[].books[].outcomes[]
        for market in game.get('markets',[]) or []:
            kind=market.get('market') or market.get('key') or ''
            for book in market.get('books',[]) or market.get('bookmakers',[]) or []:
                name=book.get('book') or book.get('title') or book.get('key')
                for o in book.get('outcomes',[]) or []:
                    selection=o.get('name','')
                    if o.get('description'):selection+=' · '+str(o['description'])
                    out.append({'sport':sport,'home':home,'away':away,'game_date':date,'market':kind,'selection':selection,
                         'point':o.get('point'),'book':name,'price':o.get('price'),'source':'TheOddsAPI','commence_time':commence,'provider_updated_at':market.get('last_update') or book.get('last_update','')})
        # Old API shape: event.bookmakers[].markets[].outcomes[]
        for book in game.get('bookmakers',[]) or []:
            name=book.get('title') or book.get('key')
            for market in book.get('markets',[]) or []:
                for o in market.get('outcomes',[]) or []:
                    selection=o.get('name','')
                    if o.get('description'):selection+=' · '+str(o['description'])
                    out.append({'sport':sport,'home':home,'away':away,'game_date':date,'market':market.get('key',''),
                                'selection':selection,'point':o.get('point'),'book':name,'price':o.get('price'),'source':'TheOddsAPI','commence_time':commence,'provider_updated_at':market.get('last_update') or book.get('last_update','')})
    return out

async def fetch_live_odds(sport, markets='h2h'):
    sport=sport.upper()
    if sport not in LEAGUES:raise ValueError('Choose NBA or NFL')
    key=get_key()
    if not key:raise ValueError('Connect a free odds API key first in Find Value. No sportsbook prices have been guessed.')
    from . import live
    from zoneinfo import ZoneInfo
    date=datetime.datetime.now(ZoneInfo(db.get_settings().get('timezone','America/Chicago'))).date().isoformat()
    await live.scoreboard(sport,date)
    async with httpx.AsyncClient(timeout=24,follow_redirects=True) as client:
        try:
            response=await client.get(ODDS_HOST+'/v4/sports/'+LEAGUES[sport]+'/odds/',params={'apiKey':key,'markets':markets,'regions':'us','oddsFormat':'american'})
            response.raise_for_status()
            payload=response.json()
        except httpx.HTTPStatusError as e:
            code=e.response.status_code
            raise ValueError('Odds provider refused the request ('+str(code)+'). Your plan may not include this market, your key may be invalid, or your free limit may be reached.')
        except httpx.HTTPError:raise ValueError('Could not reach the sportsbook-odds service. Try again later.')
    try:quotes=flatten_api_odds(payload,sport)
    except (ValueError,KeyError) as ex:raise ValueError(str(ex))
    saved=save_quotes(quotes)
    return {'sport':sport,'saved':saved,'events':len({event_key(sport,q['home'],q['away'],q['game_date']) for q in quotes}),
            'message':'Prices updated from participating sportsbooks.' if saved else 'No supported sportsbook prices were returned. Games may be off the board.'}

def compare(sport='NBA', limit=100, books=None, include_finished=False):
    sport=sport.upper()
    from zoneinfo import ZoneInfo
    today=datetime.datetime.now(ZoneInfo(db.get_settings().get('timezone','America/Chicago'))).date()
    with db.connect() as conn:
        quotes=[dict(r) for r in conn.execute('''SELECT * FROM market_quotes WHERE sport=?
          AND game_date>=? ORDER BY game_date,home,market,selection''',(sport,(today-datetime.timedelta(days=1)).isoformat()))]
    groups=defaultdict(list)
    if books:
        preferred={norm(book) for book in books}
        quotes=[q for q in quotes if norm(q['book']) in preferred]
    end=today+datetime.timedelta(days=3 if sport=='NBA' else 0)
    with db.connect() as c:games=[dict(r) for r in c.execute('SELECT * FROM games WHERE sport=?',(sport,))]
    prepared=[]
    for q in quotes:
        context=game_context(sport,q['home'],q['away'],q['game_date'],q.get('commence_time',''),games)
        q={**q,'game_status':context['status'] if context else 'unknown'}
        if context:q.update(event_key=sport+':'+context['id'],game_date=context['local_date'])
        if not include_finished and q['game_status']=='final':continue
        if not include_finished and not today.isoformat()<=q['game_date']<=end.isoformat():continue
        prepared.append(q)
    latest_batches={}
    for q in prepared:
        if q['source']=='TheOddsAPI' and q.get('batch_id'):
            k=(q['event_key'],q['market']);latest_batches[k]=max(latest_batches.get(k,''),q['batch_id'])
    quotes=[q for q in prepared if q['source']!='TheOddsAPI' or not latest_batches.get((q['event_key'],q['market'])) or q.get('batch_id')==latest_batches[(q['event_key'],q['market'])]]
    for q in quotes:groups[(q['event_key'],q['market'],q['selection'],q['point_key'])].append(q)
    rows=[]
    for (event,market,selection,point),prices in groups.items():
        by_book={}
        for q in prices:
            if q['book'] not in by_book or q['updated_at']>by_book[q['book']]['updated_at']:by_book[q['book']]=q
        prices=list(by_book.values())
        best=max(prices,key=lambda x:decimal_odds(x['price']))
        other=sorted(prices,key=lambda x:decimal_odds(x['price']),reverse=True)
        g={'sport':sport,'event_key':event,'home':best['home'],'away':best['away'],'game_date':best['game_date'],
           'market':market,'selection':selection,'point':point,'best_book':best['book'],'best_price':best['price'],
           'other_books':len(prices),'difference':round(decimal_odds(best['price'])-decimal_odds(other[-1]['price']),3),
           'books':[{'book':p['book'],'price':p['price'],'updated_at':p['updated_at'],'provider_updated_at':p.get('provider_updated_at','')} for p in other],
           'game_status':best['game_status'],'observed_game_state':best.get('observed_game_state','unknown'),'provider_updated_at':best.get('provider_updated_at',''),
           'value_type':'price_only','market_edge_pct':None,'fair_probability':None,'updated_at':best['updated_at']}
        # Estimate a consensus moneyline from *complete* two-way markets; exclude the best book.
        if market=='h2h' and best['game_status'] not in ('live','final'):
            event_rows=[r for r in quotes if r['event_key']==event and r['market']=='h2h']
            books=defaultdict(dict)
            for r in event_rows:books[r['book']][norm(r['selection'])]=r['price']
            h=norm(best['home']);a=norm(best['away']);side=norm(selection)
            if side in (h,a):
                probs=[]
                for book,opts in books.items():
                    if book==best['book'] or h not in opts or a not in opts:continue
                    denom=probability(opts[h])+probability(opts[a])
                    if denom<=0:continue
                    probs.append(probability(opts[side])/denom)
                if len(probs)>=2:
                    fair=statistics.median(probs)
                    edge=100*(fair*decimal_odds(best['price'])-1)
                    g.update(fair_probability=round(fair*100,1),market_edge_pct=round(edge,1),
                             value_type='possible_value' if edge>=1 else 'no_clear_value',reference_books=len(probs))
        rows.append(g)
    rows.sort(key=lambda q:(q['value_type']!='possible_value',-(q['market_edge_pct'] if q['market_edge_pct'] is not None else -999),-q['difference']))
    return {'sport':sport,'count':len(rows),'results':rows[:limit],
            'note':'These comparisons are based on saved prices, which may change. A possible price advantage is not proof of a profitable bet.'}

def save_game_line(sport,game_id,home_spread=None,total_line=None,source='manual'):
    if home_spread in ('',None) and total_line in ('',None):raise ValueError('Enter a spread or game total')
    spread=float(home_spread) if home_spread not in ('',None) else None
    total=float(total_line) if total_line not in ('',None) else None
    if spread is not None and not -100<spread<100:raise ValueError('Check the spread amount')
    if total is not None and not 0<total<500:raise ValueError('Check the over/under amount')
    with db.connect() as conn:
        if not conn.execute('SELECT 1 FROM games WHERE sport=? AND id=?',(sport,game_id)).fetchone():raise ValueError('Choose a saved game')
        if source!='manual':
            existing=conn.execute('SELECT source FROM game_betting_lines WHERE sport=? AND game_id=?',(sport,game_id)).fetchone()
            if existing and existing[0]=='manual':return
        conn.execute('''INSERT INTO game_betting_lines(sport,game_id,home_spread,total_line,source) VALUES(?,?,?,?,?)
          ON CONFLICT(sport,game_id) DO UPDATE SET home_spread=COALESCE(excluded.home_spread,game_betting_lines.home_spread),
          total_line=COALESCE(excluded.total_line,game_betting_lines.total_line),source=excluded.source''',
          (sport,game_id,spread,total,source))

def game_trends(sport='NFL',team='',last=10,venue='all',date_from=None,date_to=None,season_types=None):
    sport=sport.upper();last=int(last);team=team.upper()
    if sport not in LEAGUES or not 1<=last<=100:raise ValueError('Choose NBA/NFL and 1–100 games')
    with db.connect() as conn:
        sql='''SELECT g.*,l.home_spread,l.total_line,l.source AS line_source,
                 tl.possessions AS saved_possessions FROM games g
                 LEFT JOIN game_betting_lines l ON l.game_id=g.id AND l.sport=g.sport
                 LEFT JOIN team_logs tl ON tl.sport=g.sport AND tl.game_id=g.id AND tl.team=?
                 WHERE g.sport=? AND g.status='final'
                 AND (g.home_abbr=? OR g.away_abbr=?)''';args=[team,sport,team,team]
        kinds=season_types or ['regular'];sql+=' AND g.season_type IN ('+','.join('?' for _ in kinds)+')';args.extend(kinds)
        if venue=='home':sql+=' AND g.home_abbr=?';args.append(team)
        if venue=='away':sql+=' AND g.away_abbr=?';args.append(team)
        if date_from:sql+=' AND substr(g.starts_at,1,10)>=?';args.append(date_from)
        if date_to:sql+=' AND substr(g.starts_at,1,10)<?';args.append(date_to)
        sql+=' ORDER BY g.starts_at DESC LIMIT ?';args.append(last)
        games=[dict(r) for r in conn.execute(sql,args)]
    wins=losses=ats_wins=ats_losses=ats_push=overs=unders=total_push=0
    scored=[];allowed=[];details=[];possessions=[]
    for g in games:
        home=g['home_abbr']==team
        pts=g['home_score'] if home else g['away_score'];opp=g['away_score'] if home else g['home_score']
        if pts is None or opp is None:continue
        scored.append(pts);allowed.append(opp)
        if g.get('saved_possessions') is not None:possessions.append(float(g['saved_possessions']))
        wins+=pts>opp;losses+=pts<opp
        line=g['home_spread'] if home else -g['home_spread'] if g['home_spread'] is not None else None
        ats=None;ou=None
        if line is not None:
            margin=pts-opp+line
            ats='W' if margin>.0001 else 'L' if margin<-.0001 else 'P'
            ats_wins+=ats=='W';ats_losses+=ats=='L';ats_push+=ats=='P'
        if g['total_line'] is not None:
            delta=pts+opp-g['total_line'];ou='Over' if delta>.0001 else 'Under' if delta<-.0001 else 'Push'
            overs+=ou=='Over';unders+=ou=='Under';total_push+=ou=='Push'
        details.append({'date':g['starts_at'][:10],'game_id':g['id'],'opponent':g['away_abbr'] if home else g['home_abbr'],
                        'home':home,'score':f'{pts}-{opp}','spread':line,'ats':ats,'total_line':g['total_line'],'total_result':ou})
    return {'sport':sport,'team':team,'games':len(details),'wins':wins,'losses':losses,
            'win_rate':round(wins/len(details)*100,1) if details else None,
            'points_for':round(statistics.mean(scored),1) if scored else None,
            'points_against':round(statistics.mean(allowed),1) if allowed else None,
            'estimated_possessions':round(statistics.mean(possessions),1) if possessions else None,
            'pace_games':len(possessions),
            'ats_wins':ats_wins,'ats_losses':ats_losses,'ats_pushes':ats_push,
            'ats_with_lines':ats_wins+ats_losses+ats_push,
            'over':overs,'under':unders,'total_pushes':total_push,
            'totals_with_lines':overs+unders+total_push,'details':details}

def saved_team_names(sport='NFL'):
    with db.connect() as conn:
        rs=conn.execute('''SELECT home_abbr AS t FROM games WHERE sport=? UNION SELECT away_abbr AS t FROM games WHERE sport=? ORDER BY t''',(sport,sport)).fetchall()
    return [r[0] for r in rs if r[0]]

def question_answer(question,sport='NBA'):
    """Free read-only question search; explicitly not a general-purpose AI model."""
    s=question.lower().strip();sport=sport.upper()
    if sport not in LEAGUES:sport='NBA'
    if any(k in s for k in ['find value','best odds','best price','different books','which book','market value']):
        info=compare(sport)
        relevant=[q for q in info['results'] if q['value_type']=='possible_value']
        if not info['results']:
            return {'answer':f'No saved {sport} sportsbook prices to compare yet. Connect your free odds key in Find Value, then click Get Latest Prices. I will not invent odds.','results':[], 'type':'odds'}
        ranked=relevant if relevant else info['results']
        lines=[f"{r['selection']} ({r['away']} @ {r['home']}): {r['best_price']:+d} at {r['best_book']}"+ (f" · possible market edge {r['market_edge_pct']:+.1f}%" if r['market_edge_pct'] is not None else f" · {r['other_books']} book(s) compared") for r in ranked[:5]]
        return {'answer':('Possible price advantages from saved sportsbook quotes:' if relevant else 'Best available prices found; no verified edge yet:')+'\n'+'\n'.join(lines)+'\nThese are price comparisons, not guaranteed value. Check the timestamp and lines in the book.', 'results':ranked[:5], 'type':'odds'}
    if any(w in s for w in ['against the spread','cover the spread','ats','over under','over/under','team trends']):
        team=next((x for x in saved_team_names(sport) if re.search(r'\b'+re.escape(x.lower())+r'\b',s)),None)
        if not team:return {'answer':'Which team? Try: "How are the CLE doing against the spread in their last 10 games?"','results':[],'type':'team'}
        m=re.search(r'last\s+(\d+)',s);last=min(int(m.group(1)),100) if m else 10
        t=game_trends(sport,team,last)
        if not t['games']:return {'answer':f'No completed regular-season {sport} games saved for {team} yet.','results':[],'type':'team'}
        msg=f"{team} won {t['wins']} of its last {t['games']} saved games."
        if t['ats_with_lines']:msg+=f" It covered the spread {t['ats_wins']} times, missed {t['ats_losses']} times, pushed {t['ats_pushes']} times in the {t['ats_with_lines']} games with saved spreads."
        else:msg+=' No historical spreads have been saved for these games yet, so ATS cannot be calculated honestly.'
        return {'answer':msg,'results':[t],'type':'team'}
    if any(w in s for w in ['point','rebound','assist','reception','catch','yard','target','rush','touchdown','3-pointer','three pointer']):
        if sport=='NBA':
            options={'rebound':'reb','assist':'ast','3-pointer':'fg3m','three pointer':'fg3m','point':'pts'}
        else:options={'rushing touchdown':'rush_td','receiving touchdown':'rec_td','passing touchdown':'pass_td','rushing td':'rush_td','receiving td':'rec_td','passing td':'pass_td','receiving yard':'rec_yds','passing yard':'pass_yds','rushing yard':'rush_yds','rush attempt':'rush_att','target':'targets','reception':'rec','catch':'rec','touchdown':'pass_td','yard':'rec_yds'}
        stat=next((v for k,v in options.items() if k in s), 'pts' if sport=='NBA' else 'rec_yds')
        num=re.search(r'(\d+(?:\.\d+)?)\s*\+?\s*(?:or more)?\s*(?:receiving|passing|rushing|points?|rebounds?|assists?|yards?|receptions?|catches|targets?|touchdowns?)',s)
        threshold=float(num.group(1)) if num else (20 if stat=='pts' else 50 if stat.endswith('yds') else 5)
        m=re.search(r'last\s+(\d+)',s);last=min(max(int(m.group(1)),1),100) if m else 10
        m=re.search(r'(\d+)\s*%',s);rate=min(int(m.group(1)),100) if m else 50
        rs=db.consistency(sport,None,stat,threshold,rate,100,last,'all','regular',0,7)
        if not rs:return {'answer':f'No {sport} players in your saved games reached {threshold:g}+ {db.STATS[sport][stat]} at least {rate}% of their last {last} games. Try updating game results or lowering the percentage.','results':[], 'type':'players'}
        names=', '.join(f"{r['player']} {r['hits']}/{r['sample']} ({r['rate']}%)" for r in rs[:5])
        return {'answer':f"For {threshold:g}+ {db.STATS[sport][stat]} in the last {last} saved games: {names}. These are past results, not tonight's win probabilities.",'results':rs[:7], 'type':'players'}
    return {'answer':'I can search your saved player stats, team spread records, and sportsbook prices. Try "Find value", "Which players caught 5+ passes in the last 10 games?", or "How is CLE against the spread?"','results':[],'type':'help'}

"""Evidence-first prop research and league-wide team trend screens."""
import datetime as dt
from . import db,props,markets,rankings,stat_logs,providers,research_index,live

def league_trends(sport,last=5,venue='all',include_previous=False):
    if sport not in ('NBA','NFL') or venue not in ('all','home','away') or not 1<=last<=100:raise ValueError('Choose a sport, venue and 1–100 games.')
    w=stat_logs.season_window(sport,'recent' if include_previous else 'current');rows=[]
    def streak(details,kind,value):
        count=0
        for d in details:
            result=d.get(kind)
            if result!=value:break
            count+=1
        return count
    for code,name in research_index.catalog(sport).items():
        all_results=markets.game_trends(sport,code,last,venue,w['start'],w['end'])
        if not all_results['games']:continue
        home=markets.game_trends(sport,code,last,'home',w['start'],w['end'])
        away=markets.game_trends(sport,code,last,'away',w['start'],w['end'])
        details=[]
        for d in all_results['details']:
            a,b=map(float,d['score'].split('-'));details.append({**d,'result':'W' if a>b else 'L' if a<b else 'T'})
        signals=[]
        for view,label in ((home,'at home'),(away,'on the road')):
            if view['games']>=3 and view['wins']/view['games']>=.7:signals.append(f"Won {view['wins']} of {view['games']} {label}")
        for key,value,label in (('result','W','wins'),('total_result','Over','overs'),('total_result','Under','unders'),('ats','W','spread covers')):
            n=streak(details,key,value)
            if n>=3:signals.append(f'{n} consecutive {label}')
        rows.append({**all_results,'name':name,'home_record':f"{home['wins']}–{home['losses']}",'home_games':home['games'],
                     'away_record':f"{away['wins']}–{away['losses']}",'away_games':away['games'],'signals':signals,'details':details})
    rows.sort(key=lambda r:(-len(r['signals']),-(r['win_rate'] or 0),-r['games'],r['name']))
    return {'sport':sport,'window':w,'last':last,'venue':venue,'rows':rows,'note':'Records use completed regular-season games in the selected seasons. Home and road records use up to the requested number of games at each venue. A highlighted trend needs at least 3 games. Totals and spread records use saved lines only; missing lines interrupt a streak and never count as wins or losses.'}

def prop_opportunities(sport,stat='',game_id='',include_previous=False):
    if sport not in ('NBA','NFL'):raise ValueError('Choose NBA or NFL.')
    if stat and stat not in props.MARKETS[sport]:raise ValueError('Choose a supported prop category.')
    day=stat_logs.search_today().isoformat();games=[]
    for g in db.games_list(sport,limit=3000):
        if g['status'] not in ('scheduled','live'):continue
        if game_id:
            if g['id']!=game_id:continue
        elif providers.iso_day(g['starts_at'],db.get_settings().get('timezone','America/Chicago'))!=day:continue
        games.append(g)
    leads=[];coverage=[]
    for game in games:
        data=props.listed(sport,game['id'],include_previous);quotes=[q for q in data['quotes'] if not stat or q['stat']==stat]
        coverage.append({'game':game,'quotes':len(quotes)})
        grouped={}
        for q in quotes:
            key=(q.get('player_id') or props.name_key(q['player']),q['stat'],q['side'],q['line'])
            bybook=grouped.setdefault(key,{})
            if q['book'] not in bybook or q['observed_at']>bybook[q['book']]['observed_at']:bybook[q['book']]=q
        players={p['player_id']:p for p in data['players']}
        with db.research_connect() as c:
            ids=[p for p in players]
            history=[dict(r) for r in c.execute("SELECT p.* FROM player_logs p LEFT JOIN games g ON g.sport=p.sport AND g.id=p.game_id WHERE p.sport=? AND p.season_type=? AND p.game_date>=? AND p.game_date<? AND (g.id IS NULL OR g.status='final') AND p.player_id IN ("+','.join('?' for _ in ids)+') ORDER BY p.game_date DESC,p.game_id DESC',(sport,game['season_type'],data['history_window']['start'],data['history_before'],*ids))] if ids else []
        byplayer={}
        for row in history:
            if row['player_id'] in players and (sport!='NBA' or (row['minutes'] or 0)>0):byplayer.setdefault(row['player_id'],[]).append(row)
        for (pid,metric,side,line),offers in grouped.items():
            best=max(offers.values(),key=lambda q:markets.decimal_odds(q['price']))
            if not best.get('player_id'):continue
            recent=best['recent']['last10'];sample=recent['sample']
            if not sample:continue
            implied=100*markets.probability(best['price']);gap=recent['rate']-implied
            # A descriptive history/price screen, not a calibrated forecast.
            if recent['rate']<60 or gap<8:continue
            player=players[pid];rows=byplayer.get(pid,[])[:10]
            values=[db.stat_value(r,metric) for r in rows if db.stat_value(r,metric) is not None]
            minutes=[r['minutes'] for r in rows if r.get('minutes') is not None and r['minutes']>0]
            fd=offers.get('FanDuel');age=live.age(best['observed_at']);risks=[]
            if sample<5:risks.append(f'Only {sample} games with reported stats in this season window.')
            if age>900:risks.append('This saved price is over 15 minutes old; refresh it before judging the bet.')
            if recent['missing']:risks.append(f"{recent['missing']} recent games did not report this stat.")
            if game['status']=='live':risks.append('Game is live; this saved quote may be a pregame price.')
            risks.append('Active status, starting role and any minutes restriction still need checking.')
            opponent=game['away_abbr'] if player['team']==game['home_abbr'] else game['home_abbr']
            leads.append({'game':game,'player':best['player'],'player_id':pid,'position':player['position'],'team':player['team'],'opponent':opponent,
                'stat':metric,'side':side,'line':line,'quote_id':best['id'],'book':best['book'],'price':best['price'],
                'fanduel_price':fd['price'] if fd else None,'offers':list(offers.values()),'observed_at':best['observed_at'],'source_url':best['source_url'],
                'last5':best['recent']['last5'],'last10':recent,'average':round(sum(values)/len(values),2) if values else None,
                'average_minutes':round(sum(minutes)/len(minutes),1) if minutes else None,'price_break_even_pct':round(implied,1),
                'history_minus_break_even':round(gap,1),'evidence_level':'Early-season watchlist' if sample<5 else 'Research lead',
                'risks':risks,'estimated_probability':None,'expected_value':None,'price_stale':age>900})
    leads.sort(key=lambda q:(q['price_stale'],q['last10']['sample']<5,-q['last10']['sample'],-q['history_minus_break_even']))
    unique=[];seen=set()
    for row in leads:
        key=(row['game']['id'],row['player_id'],row['stat'])
        if key in seen:continue
        seen.add(key);unique.append(row)
    # Add actual season matchup context to the shortlist, never a guessed edge.
    context={};season=int(stat_logs.season_window(sport,'current')['start'][:4])+(sport=='NBA')
    for lead in unique[:20]:
        pos=lead['position'];key=(pos,lead['stat'])
        if pos in research_index.POSITIONS[sport]:
            if key not in context:context[key]=research_index.defense(sport,pos,lead['stat'],season)
            row=next((r for r in context[key]['rows'] if r['team']==lead['opponent']),None)
            if row:lead['position_matchup']=row
        lead['research_window']=stat_logs.season_window(sport,'recent' if include_previous else 'current')
    return {'sport':sport,'date':day,'leads':unique[:20],'coverage':coverage,'include_previous':include_previous,
            'note':'Shortlist screen: at least 60% of reported recent games cleared this exact line, and that historical rate exceeds the offered price’s break-even rate by at least 8 percentage points. This comparison is descriptive, not tonight’s win probability or proven mispricing. Early-season samples stay labeled. Prices, roles and injuries need a fresh check; no validated forecast or expected value is claimed.'}

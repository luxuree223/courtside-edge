"""Read-only natural-language statistics queries; no model or sportsbook charges."""
import re
from . import db, stat_logs, research_index, player_splits

def answer(question,sport='NBA'):
    text=stat_logs.normal(question);sport=sport.upper()
    if sport not in ('NBA','NFL'):raise ValueError('Choose NBA or NFL.')
    analytical=bool(re.search(r'\b(averag\w*|top|leader\w*|most|scorer\w*)\b',text))
    if not analytical:
        # Reuse the indexed player-log parser for named history/situation queries.
        if len(question)>250:return None
        try:d=stat_logs.search(question,sport)
        except ValueError:return None
        if d.get('status')!='ok':return None
        cols=d['columns'];person=d['player'];summary=d['summary']
        values=[f"{c['label']}: {summary[c['key']]['average']:g} per game" for c in cols if summary[c['key']]['average'] is not None]
        return {'type':'index','results':[dict(person,sport=sport,player_id=person['player_id'],average=None,games=d['sample'])],
            'answer':person['player']+' · '+d['season_range']['label']+' · '+str(d['sample'])+' completed games\n'+'\n'.join(values)+'\n'+d['conditions_note']}
    stat='pts' if re.search(r'\b(scorer|scoring)\b',text) else ''
    for key,phrases in stat_logs.STAT_PHRASES.items():
        if key not in db.STATS[sport]:continue
        if any(re.search(r'\b'+re.escape(phrase)+r'\b',text) for phrase in phrases):stat=key;break
    if not stat:return {'type':'index','results':[],'answer':'Which stat should I compare? For example: Lakers players averaging 2 threes or more this season, or the 76ers top scorer in the last 3 games.'}
    aliases={}
    for code,name in research_index.catalog(sport).items():
        for alias in (name,code,name.split()[-1]):aliases[stat_logs.normal(alias)]=code
    aliases.update(stat_logs.EXTRA_ALIASES.get(sport,{}))
    found=[(len(alias),code) for alias,code in aliases.items() if re.search(r'\b'+re.escape(alias)+r'\b',text)]
    team=max(found)[1] if found else ''
    last_match=re.search(r'\blast\s+(\d+)\s*(?:regular season\s*)?games?\b',text)
    last=int(last_match[1]) if last_match else None
    if last and not 1<=last<=100:raise ValueError('Choose 1–100 recent games.')
    # Explicit this season always wins; last N may extend only when needed.
    scope='recent' if last and 'this season' not in text else 'current'
    explicit=re.search(r'\b(20\d{2})(?:\s*(?:-|to|–)\s*(20\d{2}|\d{2}))?\s*(?:season)?\b',text)
    w=stat_logs.season_window(sport,'explicit' if explicit else scope,int(explicit[1]) if explicit else None);types=['regular']
    if re.search(r'\b(including|include)\b.*\b(playoffs|postseason|post season)\b',text):types.append('postseason')
    if re.search(r'\b(including|include)\b.*\b(preseason|pre season)\b',text):types.append('preseason')
    w['game_types']=types
    rows=research_index.logs(sport,w,team=team);filters=player_splits.conditions(question)
    names={r['player_id']:stat_logs.normal(r['player']) for r in rows}
    matches={pid for pid,name in names.items() if re.search(r'\b'+re.escape(name)+r'\b',text)}
    if not matches:
        matches={pid for pid,name in names.items() if len(name.split()[-1])>=4 and re.search(r'\b'+re.escape(name.split()[-1])+r'\b',text)}
    if matches:rows=[r for r in rows if r['player_id'] in matches]
    if filters['venue']!='all':rows=[r for r in rows if bool(r['is_home'])==(filters['venue']=='home')]
    if filters['rest']!='all':rows=[r for r in player_splits.add_rest_days(sport,rows) if r['rest_days']==int(filters['rest'])]
    groups={}
    for r in rows:
        if sport=='NBA' and (r.get('minutes') or 0)<=0:continue
        groups.setdefault(r['player_id'],[]).append(r)
    threshold=re.search(r'(\d+(?:\.\d+)?)\s*(?:threes?|3 pointers?|points?|rebounds?|assists?|steals?|blocks?|passing yards|receiving yards|rushing yards|touchdowns?|receptions?|catches|targets?)\s*(?:or more|and up|at least|\+)',text)
    if not threshold:threshold=re.search(r'(?:at least|averaging)\s+(\d+(?:\.\d+)?)',text)
    minimum=float(threshold[1]) if threshold else None
    result=[]
    for pid,history in groups.items():
        selected=history[:last] if last else history
        values=[db.stat_value(r,stat) for r in selected if db.stat_value(r,stat) is not None]
        if not values:continue
        avg=sum(values)/len(values)
        if minimum is not None and avg<minimum:continue
        r=selected[0];result.append({'player_id':pid,'player':r['player'],'position':r['position'],'team':r['team'],'sport':sport,'average':round(avg,2),'total':sum(values),'games':len(selected),'reported':len(values),'stat':stat})
    result.sort(key=lambda r:(-r['average'],-r['games'],r['player']))
    if re.search(r'\btop scorer\b',text):result=result[:1]
    else:result=result[:50]
    window=f'last {last} completed games per player' if last else 'this season'
    description=f'{sport} · '+(team+' · ' if team else '')+window+' · '+' + '.join(types)
    lines=[f"{r['player']} ({r['team']}, {r['position'] or 'position unverified'}): {r['average']:g} {db.STATS[sport][stat]} per game · {r['reported']} games with this stat" for r in result]
    return {'type':'index','results':result,'window':w,'answer':description+'\n'+('\n'.join(lines) if lines else 'No saved player records match this query. Sync results or adjust the filters.')+'\nUses chronological completed games and reported stats only. Missing results are not zeroes.'}

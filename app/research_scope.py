"""Owner's research window, resolved from user wording rather than model defaults."""
import re
from . import stat_logs


def resolve(question,sport,history=(),today=None):
    today=today or stat_logs.search_today()
    # A dated matchup is not an instruction to change the statistical season.
    text=re.sub(r'\b20\d{2}-\d{2}-\d{2}\b','',question.lower())
    kinds=[]
    for kind,pattern in [('regular',r'\bregular[ -]season\b'),('preseason',r'\bpre[ -]?season\b'),('postseason',r'\bpost[ -]?season\b|\bplayoffs?\b')]:
        if re.search(pattern,text):kinds.append(kind)
    if re.search(r'\ball (?:game (?:types|categories)|categories|games)\b',text):kinds=['regular','preseason','postseason']
    elif kinds and re.search(r'\b(?:including|include|with)\b',text) and 'regular' not in kinds:kinds.insert(0,'regular')
    count=re.search(r'\b(?:last|past|previous)\s+(\d+)\s*(?:(?:regular[ -]season|playoff|postseason|preseason)\s+)?(?:games?\b)?',text)
    current=bool(re.search(r'\b(?:this|current)\s+(?:season|year)\b|\bseason[ -]to[ -]date\b',text))
    previous=bool(re.search(r'\b(?:last|previous)\s+(?:season|year)\b',text))
    year=re.search(r'\b(20\d{2})(?:[–—/-](\d{2}|20\d{2}))?\b',text)
    if count and not 1<=int(count[1])<=100:raise ValueError('Choose 1 to 100 past games.')
    if year and year[2] and int(year[2])%100!=(int(year[1])+1)%100:raise ValueError('Use consecutive season years, such as 2025–26.')
    # Preserve an explicitly requested window for a clear follow-up, never from an assistant answer.
    if not (count or current or previous or year or kinds) and re.search(r'^\s*(?:what about|how about|and\b)|\bsame (?:sample|window|period)\b',text):
        for item in reversed(history):
            if item.get('role')!='user':continue
            prior=resolve(item.get('content',''),sport,today=today)
            if prior['explicit']:
                return {**prior,'origin':'user follow-up'}
            break
    scope='explicit' if year else 'current' if current else 'previous' if previous else 'recent' if count else 'current'
    window=stat_logs.season_window(sport,scope,int(year[1]) if year else None,today)
    # NBA's database/ESPN convention is the ending year; NFL uses the starting year.
    season=int(window['start'][:4])+(sport=='NBA')+(scope=='recent')
    return {**window,'season':season,'last':int(count[1]) if count else 100,
            'game_types':kinds or ['regular'],
            'explicit':bool(count or current or previous or year or kinds),'last_explicit':bool(count),
            'origin':'user request' if count or current or previous or year or kinds else 'owner default',
            'description':(f"Last {int(count[1])} completed games, newest first" if count else f"Season to date: {window['label']}")+' · '+' + '.join({'regular':'Regular season','preseason':'Preseason','postseason':'Playoffs'}[k] for k in (kinds or ['regular'])),
            'note':'Use only the allowed game types. Take the chronological newest N games; use the previous season only if this season cannot fill N. Never force a fixed split across seasons. Without an explicit last-N request, missing current-season games never trigger an older-season fallback. Label seasons actually included, game types and actual sample. A historical hit rate is not a forecast.'}

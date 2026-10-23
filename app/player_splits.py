"""Home/road and team rest-day filters, applied before a last-N limit."""
import bisect
import datetime as dt
import re
from . import db,providers

def conditions(query,venue='all',rest='all'):
    text=query;explicit_venue=venue!='all';explicit_rest=rest!='all'
    if re.search(r'\b(?:on the road|road games?|away games?|on the road)\b',text,re.I):
        if not explicit_venue:venue='away'
        text=re.sub(r'\b(?:on the road|road games?|away games?)\b',' ',text,flags=re.I)
    elif re.search(r'\b(?:at home|home games?)\b',text,re.I):
        if not explicit_venue:venue='home'
        text=re.sub(r'\b(?:at home|home games?)\b',' ',text,flags=re.I)
    if re.search(r'\b(?:back[ -]to[ -]backs?|b2b)\b',text,re.I):
        if not explicit_rest:rest='0'
        text=re.sub(r'\b(?:back[ -]to[ -]backs?|b2b)\b',' ',text,flags=re.I)
    match=re.search(r'\b(\d+)\s*(?:days?|nights?)\s*(?:of\s*)?(?:rest|off)\b',text,re.I)
    if match:
        if not explicit_rest:rest=match[1]
        text=text[:match.start()]+' '+text[match.end():]
    text=re.sub(r'\b(?:on|with|after|when|playing|played)\b',' ',text,flags=re.I)
    if venue not in ('all','home','away'):raise ValueError('Choose home, road, or all games.')
    if rest!='all' and (not str(rest).isdigit() or not 0<=int(rest)<=30):raise ValueError('Choose 0–30 full days of rest.')
    return {'query':' '.join(text.split()),'venue':venue,'rest':str(rest)}

def add_rest_days(sport,rows):
    if not rows:return rows
    start=(dt.date.fromisoformat(min(r['game_date'] for r in rows))-dt.timedelta(days=60)).isoformat()
    end=max(r['game_date'] for r in rows);calendar={}
    zone=db.get_settings().get('timezone','America/Chicago')
    with db.research_connect() as c:
        for g in c.execute("SELECT home_abbr,away_abbr,starts_at FROM games WHERE sport=? AND status='final' AND starts_at>=? AND starts_at<?",(sport,start,end+'T23:59:59')):
            date=providers.iso_day(g['starts_at'],zone)
            for team in (g['home_abbr'],g['away_abbr']):calendar.setdefault(team,set()).add(date)
        for r in c.execute("SELECT DISTINCT p.team,p.game_date FROM player_logs p LEFT JOIN games g ON g.sport=p.sport AND g.id=p.game_id WHERE p.sport=? AND p.game_date>=? AND p.game_date<=? AND (g.id IS NULL OR g.status='final')",(sport,start,end)):
            calendar.setdefault(r['team'],set()).add(r['game_date'])
    calendar={k:sorted(v) for k,v in calendar.items()}
    for row in rows:
        days=calendar.get(row['team'],[]);i=bisect.bisect_left(days,row['game_date'])
        row['rest_days']=(dt.date.fromisoformat(row['game_date'])-dt.date.fromisoformat(days[i-1])).days-1 if i else None
    return rows

def note(filters):
    place={'all':'All venues','home':'Home games only','away':'Road games only'}[filters['venue']]
    rest=filters['rest']
    return place+(' · All rest schedules' if rest=='all' else ' · Back-to-backs (0 full days off)' if rest=='0' else f' · Exactly {rest} full days off')+'. Rest uses the team’s previous completed game, including other game types; missing prior schedule stays unknown.'

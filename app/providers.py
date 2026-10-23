"""Best-effort public ESPN collection plus historical CSV ingestion.
No fabricated data. ESPN endpoints are unofficial: failures are surfaced, not suppressed.
"""
from . import db as store
import httpx, datetime, csv, io, re, math, asyncio, json
from zoneinfo import ZoneInfo

BASE='https://site.api.espn.com/apis/site/v2/sports'
SPORT_PATH={'NBA':'basketball/nba','NFL':'football/nfl'}
USER_AGENT='CourtsideEdge/0.1 (personal stats collection)'

def number(x,default=0):
    try:
        if x is None or x in ('','--','-'):return default
        s=str(x).replace(',','').replace('%','').strip()
        if ':' in s:
            parts=s.split(':');return float(parts[0])+float(parts[1])/60 if len(parts)==2 else default
        if re.fullmatch(r'-?\d+\.\d+|-?\d+',s):return float(s)
        value=float(s)
        return value if math.isfinite(value) else default
    except (TypeError,ValueError):return default

def season_label(value):
    try:
        v=int(value)
        return {1:'preseason',2:'regular',3:'postseason',4:'postseason',5:'postseason'}.get(v,'regular')
    except Exception:return 'regular'

def iso_day(value,timezone='America/Chicago'):
    text=str(value or '')
    if len(text)>10:
        try:
            stamp=datetime.datetime.fromisoformat(text.replace('Z','+00:00'))
            if stamp.tzinfo:return stamp.astimezone(ZoneInfo(timezone)).date().isoformat()
        except (ValueError,KeyError):pass
    return text[:10]

def parse_scoreboard(payload,sport):
    games=[]
    for evt in payload.get('events',[]):
        comps=evt.get('competitions',[])
        if not comps:continue
        comp=comps[0]; competitors=comp.get('competitors',[])
        home=next((t for t in competitors if t.get('homeAway')=='home'),None)
        away=next((t for t in competitors if t.get('homeAway')=='away'),None)
        if not home or not away:continue
        h=home.get('team') or {};a=away.get('team') or {}
        status=evt.get('status') or {}
        state=status.get('type') or {}
        completed=bool(state.get('completed'))
        started=completed or state.get('state')=='in'
        kind=season_label((evt.get('season') or payload.get('leagues',[{}])[0].get('season') or {}).get('type',2))
        # ESPN labels the Cup final as type 2 despite its separate competition
        # marker. Preserve the box score without counting it as regular season.
        notes=' '.join(str(n.get('headline','')) for n in comp.get('notes',[]) if isinstance(n,dict))
        if sport=='NBA' and (comp.get('type') or {}).get('abbreviation')=='CC' and re.search(r'NBA Cup.*Championship',notes,re.I):kind='other'
        def score(side):
            value=number(side.get('score'),None)
            return int(value) if started and value is not None else None
        games.append({'id':str(evt.get('id')),'sport':sport,'starts_at':evt.get('date') or comp.get('date',''),
          'home_id':str(h.get('id','')),'home':h.get('displayName') or h.get('name',''),'home_abbr':h.get('abbreviation',''),
          'away_id':str(a.get('id','')),'away':a.get('displayName') or a.get('name',''),'away_abbr':a.get('abbreviation',''),
          'home_score':score(home),'away_score':score(away),
          'clock':status.get('displayClock'),'period':status.get('period'),
          'status_detail':state.get('shortDetail') or state.get('detail') or state.get('description',''),
          'status':'final' if completed else 'live' if state.get('state')=='in' else 'scheduled',
          'season_type':kind})
    return games

def scoreboard_betting_lines(payload,sport):
    """Only save ESPN spread/total references when the favorite can be identified."""
    out=[]
    for evt in payload.get('events',[]):
        comps=evt.get('competitions') or []
        if not comps:continue
        comp=comps[0]; teams=comp.get('competitors') or []
        home=next((x for x in teams if x.get('homeAway')=='home'),None)
        away=next((x for x in teams if x.get('homeAway')=='away'),None)
        if not home or not away:continue
        ha=(home.get('team') or {}).get('abbreviation','').upper()
        aa=(away.get('team') or {}).get('abbreviation','').upper()
        raw=comp.get('odds') or []
        if isinstance(raw,dict):raw=[raw]
        for item in raw[:1]:
            if not isinstance(item,dict):continue
            details=str(item.get('details') or '').upper()
            m=re.search(r'\b([A-Z]{2,4})\s+(-?\d+(?:\.\d+)?)\b',details)
            spread=None
            if m:
                alias=m.group(1);value=float(m.group(2))
                if alias==ha:spread=value
                elif alias==aa:spread=-value
            total=number(item.get('overUnder'),None)
            if spread is not None or total is not None:
                out.append({'sport':sport,'game_id':str(evt.get('id')),'home_spread':spread,'total_line':total})
    return out

def nba_player_logs(payload,game):
    out=[]; teams=payload.get('boxscore',{}).get('players',[])
    for section in teams:
        t=section.get('team',{});team=t.get('abbreviation','')
        other=game['away_abbr'] if team==game['home_abbr'] else game['home_abbr']
        for category in section.get('statistics',[]):
            labels=[str(l).upper().strip() for l in category.get('labels',[])]
            for entry in category.get('athletes',[]):
                athlete=entry.get('athlete') or {}
                if not athlete.get('id'):continue
                arr=entry.get('stats') or []
                stats={label:arr[i] for i,label in enumerate(labels) if i<len(arr)}
                if not stats or entry.get('didNotPlay'):continue
                row={'sport':'NBA','game_id':game['id'],'player_id':str(athlete['id']),
                    'player':athlete.get('displayName') or athlete.get('fullName',''),
                    'team':team,'opponent':other,'position':(athlete.get('position') or {}).get('abbreviation',''), 'game_date':game.get('game_date') or iso_day(game['starts_at']),
                    'is_home':int(team==game['home_abbr']),'season_type':game['season_type'],
                    'source':'ESPN','source_url':f'{BASE}/basketball/nba/summary?event={game["id"]}','minutes':number(stats.get('MIN'),None),
                    'pts':number(stats.get('PTS'),None),'reb':number(stats.get('REB'),None),
                    'ast':number(stats.get('AST'),None),'fg3m':number(str(stats.get('3PT','')).split('-')[0],None),
                    'stl':number(stats.get('STL')),'blk':number(stats.get('BLK')),
                    'fgm':number(str(stats.get('FG','')).split('-')[0],None),
                    'fga':number(str(stats.get('FG','')).split('-')[-1],None),
                    'oreb':number(stats.get('OREB')),'dreb':number(stats.get('DREB')),
                    'tov':number(stats.get('TO'))}
                if row['minutes']==0 and entry.get('didNotPlay'):continue
                out.append(row)
    return list({(r['game_id'],r['player_id']):r for r in out}.values())

def nba_team_logs(payload,game):
    rows=[]
    for item in (payload.get('boxscore') or {}).get('teams',[]):
        t=item.get('team') or {}; abbr=t.get('abbreviation','')
        stats={}
        for s in item.get('statistics',[]):
            name=str(s.get('name','')).lower()
            v=s.get('displayValue') or s.get('value')
            stats[name]=v
        def get(*keys):
            for key in keys:
                if key.lower() in stats:return number(stats[key.lower()])
            return 0
        def split_pair(key,idx):
            raw=str(stats.get(key,'0-0'))
            return number(raw.split('-')[idx]) if '-' in raw else 0
        fga=get('fieldGoalsAttempted','fieldGoalsAttempts') or split_pair('fieldgoalsmade-fieldgoalsattempted',1) or split_pair('fieldgoalsmade-fieldgoalsattempted',1)
        fta=get('freeThrowsAttempted') or split_pair('freethrowsmade-freethrowsattempted',1)
        oreb=get('offensiveRebounds');tov=get('totalTurnovers','turnovers')
        required=('offensiverebounds' in stats and any(k in stats for k in ('totalturnovers','turnovers'))
                  and any(k in stats for k in ('freethrowsattempted','freethrowsmade-freethrowsattempted')))
        possessions=round(fga-oreb+tov+.44*fta,1) if fga and required else None
        home=abbr==game['home_abbr']
        rows.append({'sport':'NBA','game_id':game['id'],'team':abbr,
        'opponent':game['away_abbr'] if home else game['home_abbr'],
        'game_date':game.get('game_date') or iso_day(game['starts_at']),'is_home':int(home),
        'season_type':game['season_type'],'pts':game['home_score'] if home else game['away_score'],
        'opp_pts':game['away_score'] if home else game['home_score'],
        'fga':fga,'fta':fta,'oreb':oreb,'tov':tov,'possessions':possessions,
        'source_url':f'{BASE}/basketball/nba/summary?event={game["id"]}'})
    # Some ESPN summary payloads omit team-stat rows; preserve scoring data either way
    if not rows:
        for home in [True,False]:
            rows.append({'sport':'NBA','game_id':game['id'],
               'team':game['home_abbr'] if home else game['away_abbr'],
               'opponent':game['away_abbr'] if home else game['home_abbr'],
               'game_date':game.get('game_date') or iso_day(game['starts_at']),'is_home':int(home),'season_type':game['season_type'],
               'pts':game['home_score'] if home else game['away_score'],
               'opp_pts':game['away_score'] if home else game['home_score'],
               'possessions':None})
    return rows

def nfl_player_logs(payload,game):
    out={}
    for team_box in (payload.get('boxscore') or {}).get('players',[]):
        team=(team_box.get('team') or {}).get('abbreviation','')
        other=game['away_abbr'] if team==game['home_abbr'] else game['home_abbr']
        for category in team_box.get('statistics',[]):
            name=(category.get('name') or category.get('displayName') or '').lower()
            labels=[str(l).upper() for l in category.get('labels',[])]
            for entry in category.get('athletes',[]):
                athlete=entry.get('athlete') or {}; pid=str(athlete.get('id',''))
                if not pid:continue
                row=out.setdefault(pid,{'sport':'NFL','game_id':game['id'],'player_id':pid,
                  'player':athlete.get('displayName') or athlete.get('fullName',''),
                  'team':team,'opponent':other,'position':(athlete.get('position') or {}).get('abbreviation',''), 'game_date':game.get('game_date') or iso_day(game['starts_at']),
                  'is_home':int(team==game['home_abbr']),'season_type':game['season_type'],'source':'ESPN',
                  'source_url':f'{BASE}/football/nfl/summary?event={game["id"]}'})
                values=entry.get('stats') or []
                s={l:values[i] for i,l in enumerate(labels) if i<len(values)}
                if 'receiv' in name:
                    row['rec']=number(s.get('REC'));row['rec_yds']=number(s.get('YDS'));row['targets']=number(s.get('TGTS',s.get('TGT')))
                    row['rec_td']=number(s.get('TD'),None)
                elif 'rush' in name:
                    row['rush_att']=number(s.get('CAR'));row['rush_yds']=number(s.get('YDS'))
                    row['rush_td']=number(s.get('TD'),None)
                elif 'pass' in name:
                    row['pass_yds']=number(s.get('YDS'));row['pass_td']=number(s.get('TD'))
        # A complete team category establishes zero for its other listed players.
        # Missing categories/TD columns remain unknown, never fabricated zeroes.
        for fragment,field in [('rush','rush_td'),('receiv','rec_td')]:
            def complete_category(category):
                labels=[str(x).upper() for x in category.get('labels',[])]
                if fragment not in (category.get('name') or category.get('displayName') or '').lower() or 'TD' not in labels:return False
                index=labels.index('TD');athletes=category.get('athletes') or []
                return bool(athletes) and all(len(a.get('stats') or [])>index and number(a['stats'][index],None) is not None for a in athletes)
            complete=any(complete_category(c) for c in team_box.get('statistics',[]))
            if complete:
                for row in out.values():
                    if row['team']==team and field not in row:row[field]=0
    return list(out.values())

async def fetch_json(client,url):
    for attempt in range(3):
        try:
            res=await client.get(url,timeout=18,follow_redirects=True)
            if res.status_code==429 or res.status_code>=500:
                if attempt<2:
                    delay=number(res.headers.get('Retry-After'),2**attempt)
                    await asyncio.sleep(min(max(delay,0),8));continue
            res.raise_for_status()
            return res.json()
        except (httpx.TimeoutException,httpx.NetworkError):
            if attempt==2:raise
            await asyncio.sleep(2**attempt)

async def sync_dates(sport,start,end,include_scheduled=True,skip_saved=False,progress=None):
    if sport not in SPORT_PATH:raise ValueError('Unsupported sport')
    a=datetime.date.fromisoformat(start);b=datetime.date.fromisoformat(end)
    if b<a or (b-a).days>31:raise ValueError('Date range must be 1–32 days')
    total_games=total_logs=0;errors=[]
    async with httpx.AsyncClient(headers={'User-Agent':USER_AGENT,'Accept':'application/json'}) as client:
        for day in (a+datetime.timedelta(days=i) for i in range((b-a).days+1)):
            stamp=day.strftime('%Y%m%d')
            day_error_start=len(errors)
            try:
                payload=await fetch_json(client,f'{BASE}/{SPORT_PATH[sport]}/scoreboard?dates={stamp}&limit=1000')
                games=parse_scoreboard(payload,sport)
                timezone=store.get_settings().get('timezone','America/Chicago')
                for game in games:game['game_date']=iso_day(game['starts_at'],timezone)
                with store.research_connect() as db:
                    for g in games: store.save_game(db,g)
                from . import markets
                for line in scoreboard_betting_lines(payload,sport):
                    try: markets.save_game_line(**line,source='ESPN listed line')
                    except ValueError: pass
                for g in games:
                    if g['status']!='final':continue
                    if skip_saved and day<datetime.date.today()-datetime.timedelta(days=2):
                        with store.research_connect() as saved:
                            exists=saved.execute('SELECT 1 FROM player_logs WHERE sport=? AND game_id=? LIMIT 1',(sport,g['id'])).fetchone()
                        if exists and sport=='NBA':
                            with store.research_connect() as saved:
                                incomplete=saved.execute("SELECT 1 FROM player_logs WHERE sport='NBA' AND game_id=? AND fgm IS NULL LIMIT 1",(g['id'],)).fetchone()
                            if incomplete:exists=None
                        if exists:continue
                    # An empty or partial game summary must not overwrite existing logs
                    try:
                        summary=await fetch_json(client,f'{BASE}/{SPORT_PATH[sport]}/summary?event={g["id"]}')
                        logs=nba_player_logs(summary,g) if sport=='NBA' else nfl_player_logs(summary,g)
                        teams=nba_team_logs(summary,g) if sport=='NBA' else []
                        if logs:
                            with store.research_connect() as db:
                                store.save_logs(db,logs)
                                if teams:store.save_team_logs(db,teams)
                            total_logs+=len(logs)
                        else: errors.append(f'{g["id"]}: no player statistics available yet')
                    except Exception as ex:
                        errors.append(f'{g["id"]}: {str(ex)[:130]}')
                    await asyncio.sleep(.12)
                total_games+=len(games)
                if len(errors)==day_error_start:
                    from . import leader_slates
                    leader_slates.capture_day(sport,day.isoformat(),games)
            except Exception as ex:
                errors.append(f'{day}: {str(ex)[:140]}')
            if progress:progress(day.isoformat())
            await asyncio.sleep(.12)
    with store.research_connect() as db:
        db.execute('INSERT INTO sync_runs(sport,date_from,date_to,result,games,players,errors) VALUES (?,?,?,?,?,?,?)',
          (sport,start,end, 'error' if errors and total_logs==0 else 'partial' if errors else 'success',total_games,total_logs,'\n'.join(errors[:30])))
    return {'sport':sport,'games':total_games,'player_logs':total_logs,'errors':errors[:30],'from':start,'to':end}

# CSV ingest helpers
NBA_MAP={'player_id':['player_id','athlete_id','espn_id'], 'player':['player','player_name','athlete_display_name','athlete_name','player_display_name'],
 'game_id':['game_id','event_id','espn_game_id'], 'position':['position','athlete_position_abbreviation','athlete_position','player_position'], 'team':['team','team_abbreviation','team_abbr'],
 'opponent':['opponent','opponent_team_abbreviation','opponent_abbreviation','opponent_abbr'],
 'game_date':['game_date','date','game_date_utc','start_date'], 'minutes':['minutes','min'],
 'pts':['pts','points'],'reb':['reb','rebounds','total_rebounds'],'ast':['ast','assists'],
 'fg3m':['fg3m','three_point_field_goals_made','three_pointers_made'],
 'stl':['stl','steals'],'blk':['blk','blocks'],'fgm':['fgm','field_goals_made'],'fga':['fga','field_goals_attempted'],
 'oreb':['oreb','offensive_rebounds'],'dreb':['dreb','defensive_rebounds'],'tov':['tov','turnovers'],
 'is_home':['is_home','home','home_away']}
NFL_MAP={'player_id':['player_id','player_id_gsis','gsis_id','athlete_id'],
 'player':['player','player_display_name','display_name','player_name'],
 'game_id':['game_id','gameid'],'team':['team','recent_team','team_abbreviation'],
 'opponent':['opponent','opponent_team'], 'position':['position','position_group'], 'game_date':['game_date','date','gameday'],
 'rec':['rec','receptions'],'rec_yds':['rec_yds','receiving_yards'],
 'targets':['targets'],'rush_att':['rush_att','carries','rushing_attempts'],'rush_yds':['rush_yds','rushing_yards'],
 'pass_yds':['pass_yds','passing_yards'],'pass_td':['pass_td','passing_tds'],
 'rush_td':['rush_td','rushing_tds'],'rec_td':['rec_td','receiving_tds'],
 'is_home':['is_home']}

def ingest_csv(raw,sport,season_type='regular',source='CSV import',source_url='',schedule=None,player_ids=None):
    if sport not in ['NBA','NFL']: raise ValueError('Unsupported sport')
    if len(raw)>90*1024*1024: raise ValueError('CSV too large (90MB maximum)')
    try: text=raw.decode('utf-8-sig')
    except UnicodeDecodeError: raise ValueError('CSV must be UTF-8')
    reader=csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:raise ValueError('CSV is empty')
    headers={h.strip().lower():h for h in reader.fieldnames if h}
    mapping=NBA_MAP if sport=='NBA' else NFL_MAP
    def get(row,key):
        for alias in mapping.get(key, [key]):
            h=headers.get(alias.lower())
            if h and row.get(h) not in ('',None):return str(row[h]).strip()
        return ''
    if not any(k in headers for k in mapping['player']):raise ValueError('Missing player name column: '+', '.join(mapping['player']))
    if not any(k in headers for k in mapping['team']):raise ValueError('Missing team abbreviation column')
    if not any(k in headers for k in mapping['game_id']) and not all(k in headers for k in ['season','week']):
        raise ValueError('Missing game_id column. For NFL weekly stats, include season and week.')
    if season_type not in ('regular','preseason','postseason'):raise ValueError('Invalid season type')
    out=[];skipped=0;games={}
    for i,r in enumerate(reader):
        name=get(r,'player');team=get(r,'team').upper();player_id=get(r,'player_id') or name.lower().replace(' ','-')
        game_id=get(r,'game_id');date=iso_day(get(r,'game_date'))
        matched=(schedule or {}).get(game_id)
        if sport=='NFL' and matched:
            date=matched['gameday'];game_id=matched.get('espn') or 'nflverse:'+game_id
            r=dict(r);r['is_home']=str(int(team==matched['home_team']))
            headers['is_home']='is_home'
            if player_ids is not None:
                if player_id not in player_ids:skipped+=1;continue
                player_id=player_ids[player_id]
        # A weekly number cannot establish the date a game was actually played.
        try:datetime.date.fromisoformat(date)
        except ValueError:skipped+=1;continue
        if sport=='NBA' and str(r.get(headers.get('did_not_play','did_not_play'),'')).lower() in ('true','1'):
            skipped+=1;continue
        if not (name and team and game_id and date):skipped+=1;continue
        # filter out summary or malformed rows
        source_season=str(r.get(headers.get('season_type','season_type'),'')).strip().lower()
        if source_season in ('1','preseason','pre-season','pre season'):row_season='preseason'
        elif source_season in ('2','regular','regular season','regular-season','reg'):row_season='regular'
        elif source_season in ('3','4','5','post','postseason','post-season','playoffs','post season','play-in','playin'):row_season='postseason'
        else:row_season=season_type
        vals={'sport':sport,'game_id':game_id,'player_id':player_id,'player':name,'team':team,
              'opponent':get(r,'opponent').upper(),'position':get(r,'position').upper(),'game_date':date,
              'season_type':row_season,'source':source,'source_url':source_url,'is_home':int(get(r,'is_home').lower() in ('1','true','yes','home'))}
        numeric=[k for k in mapping if k not in ('player_id','player','game_id','team','opponent','game_date','is_home','position')]
        for k in numeric:vals[k]=number(get(r,k),None)
        out.append(vals)
        if sport=='NBA' and all(key in headers for key in ('team_score','opponent_team_score','home_away')):
            home=vals['is_home'];own=get(r,'team');opp=get(r,'opponent')
            score=number(r.get(headers['team_score']),None);other=number(r.get(headers['opponent_team_score']),None)
            if score is not None and other is not None and own and opp:
                games[game_id]={'id':game_id,'sport':sport,'starts_at':r.get(headers.get('game_date_time',''),date),
                    'home_id':'','away_id':'','home':own if home else opp,'away':opp if home else own,
                    'home_abbr':own if home else opp,'away_abbr':opp if home else own,
                    'home_score':score if home else other,'away_score':other if home else score,
                    'status':'final','season_type':row_season}
    if not out:raise ValueError(f'No valid player rows found. {skipped} skipped. Check required columns and dates.')
    with store.research_connect() as db:
        store.save_logs(db,out)
        for game in games.values():store.save_game(db,game)
    return {'imported':len(out),'skipped':skipped,'sport':sport,'games':len(games),'source':source,'source_url':source_url}

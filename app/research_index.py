"""Indexed, season-scoped entity search and observed defense against positions.

These are descriptive saved box-score statistics, never projected probabilities.
Positions are the source's roster labels, not tracking of on-court assignments.
"""
import json
import re
import datetime as dt
from pathlib import Path
from . import db, stat_logs, providers

POSITIONS = {'NFL':['QB','RB','FB','WR','TE'], 'NBA':['G','F','C','PG','SG','SF','PF']}
ALIASES = {'TIGHT END':'TE','TIGHT ENDS':'TE','WIDE RECEIVER':'WR','WIDE RECEIVERS':'WR',
           'RUNNING BACK':'RB','RUNNING BACKS':'RB','QUARTERBACK':'QB','GUARD':'G',
           'FORWARD':'F','CENTER':'C','POINT GUARD':'PG','SHOOTING GUARD':'SG',
           'SMALL FORWARD':'SF','POWER FORWARD':'PF','FULLBACK':'FB'}
GROUPS = {'G':{'G','PG','SG'},'F':{'F','SF','PF'},'C':{'C'}}


def catalog(sport):
    data=json.loads((Path(__file__).resolve().parent.parent/'static/teams/sources.json').read_text(encoding='utf-8'))
    return {db.normalize_team(sport,k.split(':')[1]):v['name'] for k,v in data.items() if k.startswith(sport+':')}


def window(sport,season=None,season_type='regular'):
    if sport not in POSITIONS:raise ValueError('Choose NBA or NFL.')
    if season_type not in ('regular','preseason','postseason'):raise ValueError('Choose a game type.')
    if season is not None and not 2002<=season<=2100:raise ValueError('Choose a valid season.')
    w=stat_logs.season_window(sport,'explicit' if season else 'current',season-(sport=='NBA') if season else None)
    return {**w,'game_types':[season_type]}


def logs(sport,w,team='',player_id=''):
    """Season/type filters run in SQLite before records leave the database."""
    kinds=w['game_types']
    where='p.sport=? AND p.game_date>=? AND p.game_date<? AND p.season_type IN ('+','.join('?' for _ in kinds)+") AND (g.id IS NULL OR g.status='final')"
    args=[sport,w['start'],w['end'],*kinds]
    if team:where+=' AND p.team=?';args.append(team)
    if player_id:where+=' AND p.player_id=?';args.append(player_id)
    with db.connect() as c:
        # Some ESPN summaries omit positions. Reuse only a position recorded on
        # or before this game, never current catalogue metadata from the future.
        resolved="""COALESCE(NULLIF(TRIM(p.position),''),(SELECT prior.position FROM player_logs prior
            WHERE prior.sport=p.sport AND prior.player_id=p.player_id AND prior.game_date<=p.game_date
            AND TRIM(COALESCE(prior.position,''))!='' ORDER BY prior.game_date DESC,prior.game_id DESC LIMIT 1),'')"""
        rows=[dict(r) for r in c.execute('SELECT p.*,'+resolved+' AS resolved_position FROM player_logs p LEFT JOIN games g ON g.sport=p.sport AND g.id=p.game_id WHERE '+where+' ORDER BY p.game_date DESC,p.game_id DESC',args)]
        for r in rows:
            r['position_from_prior_log']=not bool(str(r.get('position') or '').strip()) and bool(r['resolved_position'])
            r['position']=r.pop('resolved_position')
    names=catalog(sport)
    return [r for r in rows if db.normalize_team(sport,r['team']) in names and db.normalize_team(sport,r['opponent']) in names]


def activity(row,sport):
    keys=['minutes','pts','reb','ast','fg3m','stl','blk','tov','fga'] if sport=='NBA' else [k for k,_ in stat_logs.BOX_COLUMNS['NFL']]
    return any(isinstance(row.get(k),(int,float)) and row[k]!=0 for k in keys)


def position_match(value,position,sport):
    tokens=set(re.split(r'[/,\s-]+',ALIASES.get(str(value or '').strip().upper(),str(value or '').strip().upper())))-{''}
    target=GROUPS.get(position,{position}) if sport=='NBA' else {position}
    if tokens & target:return True
    # A generic G cannot establish whether the player is a PG or SG.
    if not tokens or (sport=='NBA' and ((position in ('PG','SG') and 'G' in tokens) or (position in ('PF','SF') and 'F' in tokens))):return None
    return False


def defense(sport,position,stat,season=None,season_type='regular',research_window=None,_observations=None):
    w=research_window or window(sport,season,season_type)
    if sport not in POSITIONS:raise ValueError('Choose NBA or NFL.')
    position=ALIASES.get(position.upper().strip(),position.upper().strip())
    if position not in POSITIONS[sport]:raise ValueError('Choose a supported player position.')
    if stat not in db.STATS[sport]:raise ValueError('Choose a stat for this sport.')
    names=catalog(sport);games={};zone=db.get_settings().get('timezone','America/Chicago')
    with db.connect() as c:
        query="SELECT * FROM games WHERE sport=? AND status='final' AND season_type IN ("+','.join('?' for _ in w['game_types'])+') AND starts_at>=? AND starts_at<?'
        upper=(dt.date.fromisoformat(w['end'])+dt.timedelta(days=1)).isoformat()
        for item in c.execute(query,[sport,*w['game_types'],w['start'],upper]):
            g=dict(item);date=providers.iso_day(g['starts_at'],zone)
            if any(db.normalize_team(sport,g[side+'_abbr']) not in names for side in ('home','away')):continue
            if not w['start']<=date<w['end']:continue
            for code in (g['home_abbr'],g['away_abbr']):games[(db.normalize_team(sport,code),g['id'])]={'date':date,'rows':[]}
    for r in (_observations if _observations is not None else logs(sport,w)):
        code=db.normalize_team(sport,r['opponent'])
        if code not in names or db.normalize_team(sport,r['team']) not in names:continue
        games.setdefault((code,r['game_id']),{'date':r['game_date'],'rows':[]})['rows'].append(r)
    by_team={code:[] for code in names}
    for (team,gid),g in games.items():by_team.setdefault(team,[]).append((gid,g))
    result=[]
    for team,entries in by_team.items():
        entries.sort(key=lambda x:(x[1]['date'],x[0]),reverse=True)
        if w.get('last_explicit'):entries=entries[:w['last']]
        total=complete_total=0;known=covered=unknown_stat=unknown_position=0;sources=set();urls=set()
        for gid,g in entries:
            if not g['rows']:continue
            covered+=1;game_total=0;uncertain=False
            for r in g['rows']:
                match=position_match(r.get('position'),position,sport);value=db.stat_value(r,stat)
                if sport=='NBA' and r.get('minutes')==0 and not activity(r,sport):continue
                sources.add(r.get('source') or 'Unspecified saved source')
                if str(r.get('source_url','')).startswith('https://'):urls.add(r['source_url'])
                if match is None and (value is None or value!=0):unknown_position+=1;uncertain=True
                if match is True:
                    if value is None:unknown_stat+=1;uncertain=True
                    else:game_total+=value
            total+=game_total
            if not uncertain:known+=1;complete_total+=game_total
        result.append({'team':team,'name':names.get(team,team),'total':round(total,3) if covered else None,
                       'average':round(complete_total/known,3) if known else None,'usable_games':known,
                       'games_with_logs':covered,'expected_games':len(entries),'missing_stat_rows':unknown_stat,
                       'unclassified_rows':unknown_position,'partial':known<len(entries),
                       'sources':sorted(sources),'source_urls':sorted(urls)[:5]})
    result.sort(key=lambda r:(r['average'] is None,-(r['average'] or 0),r['name']))
    previous=None;rank=0
    for i,r in enumerate(result):
        if r['average'] is None:r['rank']=None;continue
        if r['average']!=previous:rank=i+1
        r['rank']=rank;previous=r['average']
    return {'sport':sport,'position':position,'stat':stat,'label':db.STATS[sport][stat],
            'window':w,'rows':result,'ranked_teams':sum(r['rank'] is not None for r in result),
            'note':'Most allowed per usable game, from saved opponent player box scores. Coverage is observed records, not a guarantee of a complete box score. Games with missing stats or unresolved positions are excluded from averages, not counted as zero. Totals include reported values even in partial games. If a source omits a position, the last saved position on or before that game is used. NBA G includes G/PG/SG; F includes F/SF/PF. Hybrid roster labels may appear in more than one position view. No precise position is inferred from G/F labels. Historical context, not a betting forecast.'}


def defense_table(sport,position,stat,season=None,season_type='regular'):
    w=window(sport,season,season_type);observed=logs(sport,w)
    keys=list(db.STATS[sport])
    if sport=='NFL':keys=[k for k in keys if k not in ('pass_yds','pass_td') or position.upper()=='QB']
    if stat not in keys:stat=keys[0]
    tables={key:defense(sport,position,key,research_window=w,_observations=observed) for key in keys}
    base=tables[stat]
    lookup={key:{r['team']:r for r in table['rows']} for key,table in tables.items()}
    return {**base,'columns':[{'key':key,'label':db.STATS[sport][key]} for key in keys],
        'rows':[{**row,'stats':{key:{k:lookup[key][row['team']][k] for k in ('average','total','rank','usable_games','expected_games','partial')} for key in keys}} for row in base['rows']]}


def summary(rows,sport):
    columns=[(k,label) for k,label in stat_logs.BOX_COLUMNS[sport]]
    out={}
    for key,label in columns:
        values=[r[key] for r in rows if isinstance(r.get(key),(int,float))]
        out[key]={'label':label,'total':round(sum(values),3) if values else None,'average':round(sum(values)/len(values),3) if values else None,'reported':len(values),'games':len(rows)}
    return out


def search(sport,q,season=None,season_type='regular',entity='',entity_id=''):
    w=window(sport,season,season_type)
    if not q.strip() or len(q)>150:raise ValueError('Enter a player or team name under 150 characters.')
    if entity not in ('','team','player'):raise ValueError('Choose a player or team.')
    if not entity_id and re.search(r'\b(?:this season|last\s+\d+|on the road|road games?|at home|back[ -]to[ -]backs?|\d+\s+days?\s+(?:of\s+)?(?:rest|off))\b',q,re.I):
        data=stat_logs.search(q,sport,season_type=season_type)
        if data['status']=='ok':
            person=data['player']
            return {'sport':sport,'window':{**data['season_range'],'game_types':[data['season_type']]},'status':'ok',
                'entity':{'kind':'player','id':person['player_id'],'name':person['player'],'position':person['position']},
                'columns':data['columns'],'summary':{k:{**v,'reported':v['known'],'games':data['sample']} for k,v in data['summary'].items()},
                'rows':data['rows'],'games':data['sample'],'note':data['note']+' '+data['conditions_note']}
    names=catalog(sport);needle=db.player_name_key(q);candidates=[]
    if not needle:raise ValueError('Enter a player or team name.')
    if entity!='player':
        try:exact=stat_logs.opponent_code(sport,q)
        except ValueError:exact=''
        for code,name in names.items():
            if (entity=='team' and entity_id==code) or (not entity_id and (exact==code or needle in db.player_name_key(name))):candidates.append({'kind':'team','id':code,'name':name})
    if entity!='team':
        with db.connect() as c:
            if entity_id:people=c.execute('SELECT * FROM player_search WHERE sport=? AND player_id=?',(sport,entity_id)).fetchall()
            else:people=c.execute('SELECT * FROM player_search WHERE sport=? AND name_key LIKE ? ORDER BY name_key LIMIT 30',(sport,'%'+needle+'%')).fetchall()
        candidates.extend({'kind':'player','id':r['player_id'],'name':r['player'],'position':r['position'],'team':r['team']} for r in people)
    base={'sport':sport,'window':w,'candidates':candidates}
    if len(candidates)!=1:return {**base,'status':'choose' if candidates else 'not_found'}
    chosen=candidates[0];rows=logs(sport,w,chosen['id'] if chosen['kind']=='team' else '',chosen['id'] if chosen['kind']=='player' else '')
    if chosen['kind']=='player':rows=[r for r in rows if r['player_id']==chosen['id'] and (sport!='NBA' or activity(r,sport))]
    by_player={}
    for r in rows:
        if not activity(r,sport):continue
        record=by_player.setdefault(r['player_id'],{'id':r['player_id'],'name':r['player'],'position':r['position'],'team':r['team'],'rows':[]})
        record['rows'].append(r)
    players=[{**{k:v for k,v in p.items() if k!='rows'},'games':len(p['rows']),'stats':summary(p['rows'],sport)} for p in by_player.values()]
    players.sort(key=lambda p:(-((p['stats'].get('pts' if sport=='NBA' else 'rec_yds') or {}).get('total') or 0),p['name']))
    if chosen['kind']=='player':
        position=rows[0]['position'] if rows else chosen.get('position','');chosen={**chosen,'position':position}
        cols=[{'key':k,'label':label} for k,label in stat_logs.BOX_COLUMNS[sport] if not(sport=='NFL' and k in ('pass_yds','pass_td') and not stat_logs.is_quarterback(position))]
        return {**base,'status':'ok','entity':chosen,'columns':cols,'summary':summary(rows,sport),'rows':rows[:100],'games':len(rows),'note':'Saved completed games in the selected season and game type. Unreported values remain blank; each average uses only reported games.'}
    with db.connect() as c:
        upper=(dt.date.fromisoformat(w['end'])+dt.timedelta(days=1)).isoformat()
        all_games=[dict(r) for r in c.execute('SELECT * FROM games WHERE sport=? AND (home_abbr=? OR away_abbr=?) AND season_type=? AND starts_at>=? AND starts_at<? ORDER BY starts_at DESC',(sport,chosen['id'],chosen['id'],season_type,w['start'],upper))]
        zone=db.get_settings().get('timezone','America/Chicago')
        all_games=[g for g in all_games if w['start']<=providers.iso_day(g['starts_at'],zone)<w['end']]
    return {**base,'status':'ok','entity':chosen,'players':players,'games':all_games,'recorded_games':len({r['game_id'] for r in rows}),'note':'Players shown recorded activity in at least one saved game this season. Select a game for its box score. Live scores appear in Pick a Game; season totals here use completed saved games.'}

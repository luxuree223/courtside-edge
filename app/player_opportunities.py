"""Descriptive NFL TD production against the scheduled opponent's allowance."""
import datetime as dt
import math
from . import db, providers, rankings, covers

TD_MARKETS = {
 'pass_td': ('Passing Touchdowns', 'pass_yds', 'Passing Yards'),
 'rush_td': ('Rushing Touchdowns', 'rush_yds', 'Rushing Yards'),
 'rec_td': ('Receiving Touchdowns', 'pass_yds', 'Passing Yards'),
}


def known(value):
    return isinstance(value, (float,int)) and math.isfinite(value) and value >= 0


def participates(rows, stat):
    fields = {'pass_td':('pass_yds',),'rush_td':('rush_att','rush_yds'),'rec_td':('rec','targets')}[stat]
    return any(any(known(r.get(f)) and r[f]>0 for f in fields) for r in rows)


def build(payload, game, logs, n, season, season_type,season_types=None):
    if not 1 <= n <= 100:raise ValueError('Choose 1 to 100 past games.')
    cutoff=providers.iso_day(game['starts_at'],db.get_settings().get('timezone','America/Chicago'))
    output={'rows':[],'last':n,'season':season,'season_label':str(season),'season_type':'+'.join(season_types or [season_type]),'rankings_game_type':season_type,'before':cutoff,
            'rankings_updated_at':payload.get('updated_at') if payload else None,
            'note':'Past TD production and opponent allowance are research signals. Season ranks cover saved players, not a verified complete league roster. Latest saved team is not a confirmed active roster. No win probability or betting edge is calculated.'}
    if game['status']=='final':return {**output,'message':'Finished game. No active player opportunities.'}
    if not payload:return {**output,'message':'Update Team Stats to load opponent rankings.'}
    # Cut off every input before game day, including latest team membership.
    logs=sorted([r for r in logs if r.get('sport')=='NFL' and r['game_date']<cutoff],key=lambda r:(r['game_date'],r['game_id']),reverse=True)
    latest={};groups={}
    for row in logs:
        latest.setdefault(row['player_id'],row)
        if row['season_type'] in (season_types or [season_type]):groups.setdefault(row['player_id'],[]).append(row)
    start,end=f'{season}-03-01',f'{season+1}-03-01'
    season_rows={pid:[r for r in rows if start<=r['game_date']<end] for pid,rows in groups.items()}
    season_ranks={};defenses={}
    for stat,(_,yards,_) in TD_MARKETS.items():
        leaders=[]
        for pid,rows in season_rows.items():
            valid=[r for r in rows if known(r.get(stat))]
            if len(valid)>=3 and len(valid)>=.8*len(rows) and participates(rows,stat):
                leaders.append({'id':pid,'total':sum(r[stat] for r in valid)})
        leaders.sort(key=lambda r:(-r['total'],r['id']))
        previous=None;rank=0
        for index,item in enumerate(leaders,1):
            if item['total']!=previous:rank=index
            season_ranks[stat,item['id']]={'rank':rank,'players':len(leaders)};previous=item['total']
        for field in (stat,yards):
            if field in defenses:continue
            rows=[]
            for team in payload['teams']:
                value=team.get('allowed',{}).get(field)
                if known(value) and (team.get('defense_games') or 0)>0:rows.append({'team':team['team'],'value':value,'games':team['defense_games'],'source_url':team.get('defense_source_url') or team.get('source_url','')})
            rows.sort(key=lambda r:(-r['value'],r['team']));previous=None;rank=0
            average=sum(r['value'] for r in rows)/len(rows) if rows else 0
            for index,item in enumerate(rows,1):
                if round(item['value'],6)!=previous:rank=index
                item.update(rank=rank,teams=len(rows),high=len(rows)>=26 and rank<=len(rows)//3 and item['value']>average and item['games']>=3)
                previous=round(item['value'],6)
            defenses[field]={r['team']:r for r in rows}
    for pid,rows in groups.items():
        membership=latest[pid];team=db.normalize_team('NFL',membership['team'])
        if team not in (game['home_abbr'],game['away_abbr']):continue
        if (dt.date.fromisoformat(cutoff)-dt.date.fromisoformat(membership['game_date'])).days>45:continue
        opponent=game['away_abbr'] if team==game['home_abbr'] else game['home_abbr']
        for stat,(label,yards,yard_label) in TD_MARKETS.items():
            if not participates(rows,stat):continue
            defense=defenses.get(stat,{}).get(opponent);yard_defense=defenses.get(yards,{}).get(opponent)
            if not ((defense or {}).get('high') or (yard_defense or {}).get('high')):continue
            window=rows[:n];recent=[r for r in window if known(r.get(stat))];season_logs=[r for r in season_rows[pid] if known(r.get(stat))]
            scoring=sum(r[stat]>0 for r in recent);total=sum(r[stat] for r in recent)
            season_total=sum(r[stat] for r in season_logs);rank=season_ranks.get((stat,pid))
            recent_signal=len(recent)>=3 and len(recent)>=.8*len(window) and scoring>=2
            season_signal=bool(rank and rank['rank']<=max(3,math.ceil(rank['players']*.1)) and season_total>=2)
            if not (recent_signal or season_signal):continue
            output['rows'].append({'player_id':pid,'player':membership['player'],'team':team,'opponent':opponent,'position':membership.get('position',''),
                'stat':stat,'label':label,'recent_total':total,'recent_scoring_games':scoring,'recent_games':len(recent),'window_games':len(window),'missing_recent':len(window)-len(recent),
                'season_total':season_total,'season_games':len(season_logs),'season_missing':len(season_rows[pid])-len(season_logs),'season_rank':rank,
                'recent_signal':recent_signal,'season_signal':season_signal,'defense_td':defense,'defense_yards':yard_defense,'yard_label':yard_label,
                'signal':'TD allowance matchup' if (defense or {}).get('high') else 'Yardage matchup / TD trend',
                'logs':[{'date':r['game_date'],'opponent':r['opponent'],'tds':r[stat],'source':r['source'],'source_url':r.get('source_url','')} for r in recent]})
    output['rows'].sort(key=lambda r:(r['signal']!='TD allowance matchup',-r['recent_scoring_games'],-r['recent_total'],-r['season_total'],r['player'],r['stat']))
    output['total']=len(output['rows'])
    output['message']='No players meet the current TD production and opponent-allowance rules.' if not output['rows'] else ''
    return output


def opportunities(game_id,n=10,season=None,season_type='regular',date_from=None,date_to=None,season_types=None):
    game=covers.game('NFL',game_id)
    season=season or rankings.config()['defaults']['NFL']
    rankings.validate('NFL',season,season_type)
    with db.connect() as connection:
        sql="SELECT * FROM player_logs WHERE sport='NFL'";args=[]
        if date_from:sql+=' AND game_date>=?';args.append(date_from)
        if date_to:sql+=' AND game_date<?';args.append(date_to)
        logs=[dict(r) for r in connection.execute(sql,args)]
    return build(rankings.cached('NFL',season,season_type),game,logs,n,season,season_type,season_types)

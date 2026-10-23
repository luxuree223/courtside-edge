/* Descriptive matchup screening, independent of prices and win probabilities. */
const matchupLogic=(()=>{
 const categories={NFL:['pass_yds','rec_yds','rec','rush_yds','rush_att','pass_td','rush_td','rec_td','pts'],NBA:['pts','reb','ast','fg3m','stl','blk','pra','pr','pa','ra']};
 function teamCode(sport,code){const aliases={NBA:{GSW:'GS',NYK:'NY',NOP:'NO',SAS:'SA',UTA:'UTAH',WAS:'WSH'},NFL:{LA:'LAR',JAC:'JAX',WSH:'WAS'}};const value=String(code||'').toUpperCase();return aliases[sport]?.[value]||value}
 const valid=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0;
 function league(teams,view,metric){
  const countKey=view==='offense'?'games':'defense_games';
  const rows=teams.filter(t=>valid(t[view]?.[metric])&&valid(t[countKey])&&t[countKey]>0).map(t=>({team:t.team,value:t[view][metric],games:t[countKey],name:t.name}));
  rows.sort((a,b)=>b.value-a.value||a.team.localeCompare(b.team));
  let previous=null,rank=0;
  rows.forEach((r,index)=>{const rounded=Math.round(r.value*1e6)/1e6;if(rounded!==previous)rank=index+1;r.rank=rank;previous=rounded});
  return {rows,index:new Map(rows.map(r=>[r.team,r])),average:rows.length?rows.reduce((sum,r)=>sum+r.value,0)/rows.length:0};
 }
 function compareSignals(a,b){return a.balance-b.balance||a.rankSum-b.rankSum||a.metric.localeCompare(b.metric)}
 function scan(payload,games,dates,metric='all'){
  const sport=payload?.sport,expected=sport==='NFL'?32:30,minGames=sport==='NFL'?3:5;
  const result={groups:[],gamesChecked:0,minGames,unavailableCategories:[],expectedTeams:expected};
  if(!categories[sport])return result;
  dates=dates.slice(0,sport==='NFL'?1:4);
  const teams=[...new Map((payload.teams||[]).map(t=>{const team=teamCode(sport,t.team);return [team,{...t,team}]})).values()];
  const byTeam=new Map(teams.map(t=>[t.team,t])),indexes=new Map();
  for(const key of categories[sport].filter(key=>metric==='all'||key===metric)){
   const offense=league(teams,'offense',key),allowed=league(teams,'allowed',key);
   if(Math.min(offense.rows.length,allowed.rows.length)<Math.ceil(expected*.8)){result.unavailableCategories.push(key);continue}
   indexes.set(key,{offense,allowed});
  }
  const seen=new Set();
  for(const game of games||[]){
   if(game.sport!==sport||!['scheduled','live'].includes(game.status)||!dates.includes(game.game_day)||!game.id||seen.has(game.id))continue;
   seen.add(game.id);result.gamesChecked++;
   const home=teamCode(sport,game.home_abbr),away=teamCode(sport,game.away_abbr);
   if(home===away)continue;
   for(const [team,opponent] of [[home,away],[away,home]]){
    if(!byTeam.has(team)||!byTeam.has(opponent))continue;
    const signals=[];
    for(const [key,{offense,allowed}] of indexes){
     const a=offense.index.get(team),b=allowed.index.get(opponent);
     if(!a||!b||a.games<minGames||b.games<minGames)continue;
     const offenseCut=Math.floor(offense.rows.length/3),allowedCut=Math.floor(allowed.rows.length/3);
     if(a.rank>offenseCut||b.rank>allowedCut||a.value<=offense.average||b.value<=allowed.average)continue;
     signals.push({metric:key,offense:a,allowed:b,offenseTeams:offense.rows.length,allowedTeams:allowed.rows.length,
      standout:a.rank<=Math.floor(offense.rows.length/4)&&b.rank<=Math.floor(allowed.rows.length/4),
      balance:Math.max(a.rank/offense.rows.length,b.rank/allowed.rows.length),rankSum:a.rank/offense.rows.length+b.rank/allowed.rows.length});
    }
    if(signals.length){signals.sort(compareSignals);result.groups.push({game,team:byTeam.get(team),opponent:byTeam.get(opponent),signals})}
   }
  }
  result.groups.sort((a,b)=>compareSignals(a.signals[0],b.signals[0])||a.game.starts_at.localeCompare(b.game.starts_at)||a.team.team.localeCompare(b.team.team));
  return result;
 }
 function teamComparison(payload,game){
  const sport=payload?.sport;
  if(!categories[sport]||game?.sport!==sport)return {rows:[],away:null,home:null};
  const teams=[...new Map((payload.teams||[]).map(t=>{const team=teamCode(sport,t.team);return [team,{...t,team}]})).values()];
  const away=teamCode(sport,game.away_abbr),home=teamCode(sport,game.home_abbr);
  const rows=categories[sport].map(metric=>{
   const offense=league(teams,'offense',metric),allowed=league(teams,'allowed',metric);
   const cell=(index,team)=>{const row=index.index.get(team);return row?{...row,total:index.rows.length}:null};
   return {metric,away:{offense:cell(offense,away),allowed:cell(allowed,away)},home:{offense:cell(offense,home),allowed:cell(allowed,home)}};
  });
  return {rows,away:teams.find(t=>t.team===away)||null,home:teams.find(t=>t.team===home)||null};
 }
 return {scan,teamComparison};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=matchupLogic;

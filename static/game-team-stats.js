function teamGameCoverage(team){const a=team.games,b=team.defense_games;if(a===b&&a!==null&&a!==undefined)return a+' '+(a===1?'game':'games');return 'Available records: offense '+(a??'—')+' · allowed '+(b??'—')}
/* Selected-game season context; separate from live scores and sportsbook prices. */
const gameTeamChoices=new Map(),gameTeamRecords=new Map();
let gameTeamConfig=null,gameTeamConfigPromise=null,gameTeamConfigError='';
function gameTeamKey(game=state.selectedGame){return game?game.sport+':'+game.id:''}
function gameTeamChoice(game=state.selectedGame){return gameTeamChoices.get(gameTeamKey(game))}
function gameTeamStatsPanel(){return `<div id="game-team-stats" class="game-team-stats" data-game-key="${esc(gameTeamKey())}">${gameTeamStatsBody()}</div>`}
function gameTeamStatsBody(){
 const game=state.selectedGame;if(!game)return '';
 const choice=gameTeamChoice(),key=choice?[game.sport,choice.season,choice.type].join(':'):'',record=gameTeamRecords.get(key);
 const data=record?.data||rankCache.get(key);
 const heading=`<div class="card-head"><div><div class="eyebrow">TEAM MATCHUP</div><h3>Team Stats & League Ranks</h3></div><button class="btn btn-small" data-action="refresh-team-stats" ${record?.loading||!gameTeamConfig&&!gameTeamConfigError?'disabled':''}>${record?.loading?'Updating Stats…':'Refresh Team Stats'}</button></div>`;
 if(!choice||!gameTeamConfig)return heading+(gameTeamConfigError?`<p class="note-box" role="alert">${esc(gameTeamConfigError)} Refresh Team Stats tries again.</p>`:'<p class="muted" role="status">Loading team stats…</p>');
 const labels=game.sport==='NFL'?[['pass_yds','Passing Yards'],['rush_yds','Rushing Yards'],['rec','Receptions'],['rec_yds','Receiving Yards'],['rush_att','Rushing Attempts'],['pass_td','Passing Touchdowns'],['rush_td','Rushing Touchdowns'],['rec_td','Receiving Touchdowns'],['pts','Points']]:nbaStats;
 const label=metric=>labels.find(([key])=>key===metric)?.[1]||metric;
 const controls=`<div class="game-team-controls">${field('Stats season',select('game-team-season',gameTeamConfig.seasons[game.sport].map(s=>[s.value,s.label]),choice.season))}${field('Stats game type',select('game-team-type',[['regular','Regular season'],['postseason','Playoffs']],choice.type))}</div>`;
 const error=record?.error?`<p class="note-box" role="alert">${esc(record.error)}${data?' Saved stats remain below.':''}</p>`:'';
 if(!data)return heading+controls+error+(record?.loading?'<p class="muted" role="status">Getting team and opponent season stats…</p>':'<p class="muted">No saved stats for this season. Refresh Team Stats checks the source.</p>');
 const comparison=matchupLogic.teamComparison(data,game);
 const highlights=matchupLogic.scan(data,[{...game,game_day:gameDay(game)}],selectableGameDates(game.sport));
 const edges=new Set(highlights.groups.flatMap(group=>group.signals.map(s=>group.team.team+':'+s.metric)));
 const stale=!data.updated_at||Date.now()-Date.parse(data.updated_at)>86400000;
 const names={away:game.away_abbr,home:game.home_abbr};
 const cell=(row,side,view)=>{
  const item=row[side][view];if(!item)return '<td><span class="muted">Unavailable</span></td>';
  const producer=view==='offense'?comparison[side]:comparison[side==='away'?'home':'away'];
  const highlighted=edges.has(producer?.team+':'+row.metric);
  return `<td class="${highlighted?'team-stat-match':''}"><strong>${num(item.value,1)}</strong><small>#${item.rank} of ${item.total}${view==='allowed'?' most allowed':''}</small>${highlighted&&view==='offense'?'<span class="team-stat-flag">Favorable matchup</span>':''}</td>`;
 };
 const teamHeader=side=>{const team=comparison[side],source=team?.source_url,defenseSource=team?.defense_source_url;return `<th scope="colgroup" colspan="2"><div class="team-stats-name">${teamLogo(game.sport,names[side])}<span>${esc(side==='away'?game.away:game.home)}<small>${team?teamGameCoverage(team):'Team stats unavailable'}${source?` · <a target="_blank" rel="noopener noreferrer" href="${esc(safeSource(source))}">${defenseSource?'Offense':'Source'} ↗</a>`:''}${defenseSource?` · <a target="_blank" rel="noopener noreferrer" href="${esc(safeSource(defenseSource))}">Allowed ↗</a>`:''}</small></span></div></th>`};
 return heading+controls+error+`<p class="field-help">${esc(data.season_label)} ${choice.type==='regular'?'regular season':'playoffs'} · All stats per game · ${stale?'Saved stats over 24 hours old · ':''}Updated ${data.updated_at?esc(new Date(data.updated_at).toLocaleString()):'time unavailable'}.${game.season_type==='preseason'?' Selected game is preseason; these are season stats.':''}</p>
 <p class="field-help">Offense #1 = most produced. Allowed #1 = most allowed. Highlighted cells pair strong production with high opponent allowance.</p>
 <div class="table-scroller game-team-scroll" tabindex="0" role="region" aria-label="Team stats and league ranks for ${esc(game.away)} and ${esc(game.home)}"><table class="table game-team-table"><thead><tr><th class="team-stat-category" scope="col" rowspan="2">STAT / GAME</th>${teamHeader('away')}${teamHeader('home')}</tr><tr><th scope="col">OFFENSE</th><th scope="col">ALLOWED</th><th scope="col">OFFENSE</th><th scope="col">ALLOWED</th></tr></thead><tbody>${labels.map(([metric])=>comparison.rows.find(r=>r.metric===metric)).filter(Boolean).map(row=>`<tr><th class="team-stat-category" scope="row">${esc(label(row.metric))}</th>${cell(row,'away','offense')}${cell(row,'away','allowed')}${cell(row,'home','offense')}${cell(row,'home','allowed')}</tr>`).join('')}</tbody></table></div>
 ${data.errors?.length?`<p class="field-help">${data.errors.length} team updates were unavailable. Ranks use teams with a reported value in each category.</p>`:''}
 <p class="field-help">${esc(data.note||'Season averages from saved team statistics.')} Season averages are separate from this game’s live score.</p>${tdPanel()}`;
}
function paintGameTeamStats(){const host=document.querySelector('#game-team-stats');if(host&&host.dataset.gameKey===gameTeamKey())host.innerHTML=gameTeamStatsBody()}
function paintGameTeamRecord(key){const choice=gameTeamChoice();if(choice&&[state.selectedGame.sport,choice.season,choice.type].join(':')===key){paintGameTeamStats();return true}return false}
async function loadGameTeamStats(force=false){
 const game=state.selectedGame;if(!game)return;
 const selectedKey=gameTeamKey(game);
 try{
  if(!gameTeamConfig){
   if(!gameTeamConfigPromise)gameTeamConfigPromise=req('/rankings/config').then(data=>(gameTeamConfig=data)).finally(()=>{gameTeamConfigPromise=null});
   await gameTeamConfigPromise;gameTeamConfigError='';
  }
  let choice=gameTeamChoices.get(selectedKey);
  if(!choice){choice={season:gameTeamConfig.defaults[game.sport],type:game.season_type==='postseason'?'postseason':'regular'};gameTeamChoices.set(selectedKey,choice)}
  const key=[game.sport,choice.season,choice.type].join(':'),existing=gameTeamRecords.get(key);
  if(existing?.loading){paintGameTeamStats();return}
  let cached=rankCache.get(key)||existing?.data;
  if(cached&&!force){gameTeamRecords.set(key,{data:cached});if(paintGameTeamRecord(key))loadTDOpportunities();return}
  const record={data:cached,loading:true,error:''};gameTeamRecords.set(key,record);paintGameTeamStats();
  const params=new URLSearchParams({sport:game.sport,season:choice.season,season_type:choice.type,metric:game.sport==='NFL'?'pass_yds':'pts',view:'offense',order:'most'});
  try{
   let data=await req('/rankings'+(force?'/refresh':'')+'?'+params,force?{method:'POST'}:{});
   if(data.missing||data.needs_refresh){if(!data.missing)cached=data;data=await req('/rankings/refresh?'+params,{method:'POST'})}
   gameTeamRecords.set(key,{data});rankCache.set(key,data);
  }catch(e){gameTeamRecords.set(key,{data:cached,error:'Could not update team stats: '+e.message})}
  if(paintGameTeamRecord(key))loadTDOpportunities(force);
 }catch(e){gameTeamConfigError='Could not load team stats: '+e.message;if(gameTeamKey()===selectedKey)paintGameTeamStats()}
}
document.addEventListener('click',e=>{if(e.target.closest('[data-action="refresh-team-stats"]'))loadGameTeamStats(true)});
document.addEventListener('change',e=>{
 if(!['f-game-team-season','f-game-team-type'].includes(e.target.id)||!state.selectedGame)return;
 const choice=gameTeamChoice();if(!choice)return;
 if(e.target.id==='f-game-team-season')choice.season=Number(e.target.value);else choice.type=e.target.value;
 paintGameTeamStats();loadGameTeamStats();
});

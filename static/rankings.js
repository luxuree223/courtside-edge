/* Team rankings: production beside opponent production, with no implied projection. */
let rankSport='NFL',rankSeason=null,rankType='regular',rankMetric='pass_yds',rankView='offense',rankOrder='most';
let rankConfig=null,rankData=null,rankLoading=false,rankError='',rankTeam='',rankOpponent='',rankRequest=0;
const rankCache=new Map();
let highlightCategory='all';
function rankKey(){return [rankSport,rankSeason,rankType].join(':')}
function rankMetrics(){return rankSport==='NFL'?[...nflStats.filter(([key])=>key!=='targets'),['pts','Points']]:nbaStats}
function rankLabel(metric){return rankMetrics().find(([key])=>key===metric)?.[1]||metric}
function rankingValue(team,view,metric=rankMetric){const value=team?.[view]?.[metric];return typeof value==='number'&&Number.isFinite(value)?value:null}
function orderedTeams(view=rankView,order=rankOrder,metric=rankMetric){
 const rows=(rankData?.teams||[]).filter(t=>rankingValue(t,view,metric)!==null&&t[view==='offense'?'games':'defense_games']>0);
 rows.sort((a,b)=>(order==='most'?rankingValue(b,view,metric)-rankingValue(a,view,metric):rankingValue(a,view,metric)-rankingValue(b,view,metric))||a.name.localeCompare(b.name));
 let previous=null,rank=0;
 return rows.map((team,index)=>{const value=Math.round(rankingValue(team,view,metric)*1e6)/1e6;if(value!==previous)rank=index+1;previous=value;return {...team,rank,value}});
}
function teamRank(team,view,metric=rankMetric){const rows=orderedTeams(view,'most',metric),item=rows.find(r=>r.team===team);return item?'#'+item.rank+' of '+rows.length:'Unavailable'}
function rankGames(){const dates=selectableGameDates(rankSport);return (state.games[rankSport]||[]).filter(g=>dates.includes(gameDay(g))&&g.status!=='final').sort((a,b)=>a.starts_at.localeCompare(b.starts_at))}
function rankNextGame(team){const record=nextGames.get(rankSport+':'+team);return record?.game||null}
function rankOther(game,team){return game?.home_abbr===team?game.away_abbr:game?.home_abbr}
function rankNumber(value){return value===null?'Unavailable':num(value,1)}
function rankOpportunities(){if(!rankData)return '';if(rankData.no_stats)return `<details class="card pad"><summary>Matchup Opportunities · No season stats yet</summary>${rankOpportunitiesBody()}</details>`;const result=matchupLogic.scan(rankData,(state.games[rankSport]||[]).map(g=>({...g,game_day:gameDay(g)})),selectableGameDates(rankSport),highlightCategory);return result.groups.length?`<section class="card pad matchup-opportunities" id="matchup-opportunities">${rankOpportunitiesBody()}</section>`:`<details class="card pad matchup-opportunities"><summary>Matchup Opportunities · No matches available</summary><div id="matchup-opportunities">${rankOpportunitiesBody()}</div></details>`}
function rankOpportunitiesBody(){
 if(!rankData)return '';
 if(rankData.no_stats)return `<div class="card-head"><h2>Matchup Opportunities</h2></div>${empt('No '+esc(rankData.season_label)+' stats yet','This season starts empty. Matchup highlights will appear after enough completed games are recorded. Choose an earlier stats season above for historical context.')}`;
 const games=(state.games[rankSport]||[]).map(g=>({...g,game_day:gameDay(g)}));
 const result=matchupLogic.scan(rankData,games,selectableGameDates(rankSport),highlightCategory),groups=result.groups;
 const checks=selectableGameDates(rankSport).map(date=>scheduleChecks.get(rankSport+':'+date));
 const checking=checks.some(c=>c?.running),failed=checks.some(c=>!c||c.failed);
 const windowLabel=rankSport==='NFL'?'today':`today through ${day(selectableGameDates(rankSport).at(-1))}`;
 const row=(signal,group)=>`<tr><td><strong>${esc(rankLabel(signal.metric))}</strong>${signal.standout?'<span class="small green">Both in top quarter</span>':''}</td><td><strong>${num(signal.offense.value,1)}</strong><span class="small">#${signal.offense.rank} of ${signal.offenseTeams}</span></td><td><strong>${num(signal.allowed.value,1)}</strong><span class="small">#${signal.allowed.rank} most allowed of ${signal.allowedTeams}</span></td><td><button class="link-btn" data-action="highlight-players" data-game-id="${esc(group.game.id)}" data-team="${esc(group.team.team)}" data-stat="${signal.metric}">${rankSport==='NFL'&&signal.metric==='pts'?'Game odds':'Check players'} →</button></td></tr>`;
 const item=group=>{
  const signal=group.signals[0],game=group.game;
  return `<article class="matchup-opportunity"><div class="row-between"><span class="tag ${signal.standout?'win':''}">${rankConfig?.current?.[rankSport]&&rankSeason<rankConfig.current[rankSport]?'PRIOR-SEASON CONTEXT':signal.standout?'STANDOUT MATCHUP':'MATCHUP TO RESEARCH'}</span><span class="small">${esc(gameDateLabel(gameDay(game)))} · ${game.status==='live'?'LIVE':esc(gameStatusText(game))}${game.season_type==='preseason'?' · PRESEASON':''}</span></div>
  <h3>${teamLogo(rankSport,group.team.team)}${esc(group.team.name)}<span class="muted">offense</span></h3><p class="opponent-heading">vs ${teamLogo(rankSport,group.opponent.team)}<strong>${esc(group.opponent.name)}</strong> defense</p>
  <p class="field-help">${signal.offense.games} team games · ${signal.allowed.games} opponent games · ${esc(rankData.season_label)} ${rankType==='regular'?'regular season':'playoffs'}</p>
  <div class="table-scroller"><table class="table opportunity-stats"><thead><tr><th>CATEGORY</th><th>${esc(group.team.team)} / GAME</th><th>${esc(group.opponent.team)} ALLOWED / GAME</th><th>RESEARCH</th></tr></thead><tbody>${group.signals.slice(0,3).map(s=>row(s,group)).join('')}</tbody></table></div>
  ${group.signals.length>3?`<details class="more-matchup-stats"><summary>${group.signals.length-3} more matching categories</summary><div class="table-scroller"><table class="table opportunity-stats"><tbody>${group.signals.slice(3).map(s=>row(s,group)).join('')}</tbody></table></div></details>`:''}
  <button class="link-btn compare-highlight" data-action="highlight-compare" data-team="${esc(group.team.team)}" data-opponent="${esc(group.opponent.team)}" data-stat="${signal.metric}">Compare these teams →</button></article>`;
 };
 return `<div class="card-head"><div><div class="eyebrow">OFFENSE MEETS DEFENSE</div><h2>Matchup Opportunities</h2></div>${field('Matchup category',select('highlight-category',[['all','All bet categories'],...rankMetrics()],highlightCategory))}</div>
 <p class="field-help">These matchups pair an offense and the opposing defense that both rank in the top third for the same stat: the offense produces more, and the defense allows more, than the league average. ${result.gamesChecked} active ${rankSport} game${result.gamesChecked===1?'':'s'} checked · ${windowLabel}.</p>
 ${rankConfig?.current?.[rankSport]&&rankSeason<rankConfig.current[rankSport]?`<p class="note-box">Using ${esc(rankData.season_label)} stats as historical context for these games. These are not current-season results.</p>`:''}
 ${checking?'<p class="field-help" role="status">Checking the schedule…</p>':failed?'<p class="note-box">Some schedules could not update. Highlights use saved games and may be out of date.</p>':''}
 ${groups.length?`<div class="matchup-opportunity-grid">${groups.slice(0,6).map(item).join('')}</div>${groups.length>6?`<details class="more-matchups"><summary>Show ${groups.length-6} more team matchups</summary><div class="matchup-opportunity-grid">${groups.slice(6).map(item).join('')}</div></details>`:''}`:empt(checking?'Checking matchups…':!result.gamesChecked?'No active games in this window':'No matchups meet this rule',!result.gamesChecked?'NFL checks today; NBA checks today and the next three days.':`Both teams need at least ${result.minGames} games, above-average numbers and top-third ranks in the same category. Try All bet categories or update the rankings.`)}
 <details class="opportunity-rules"><summary>How highlights are picked</summary><p>Both production and opponent allowance must rank in the top third and be above the league average. Standout means both rank in the top quarter. Each team needs at least ${result.minGames} games; a category needs stats for at least 80% of the league. Ranks use available teams and share ties. Matchups are ordered by the stronger balance of the two ranks, without counting related categories as separate evidence.</p><p>These are ${esc(rankData.season_label)} ${rankType==='regular'?'regular-season':'playoff'} team averages. They may come from a different season than the scheduled game. Live-game highlights do not adjust for the current score or time. Check the player’s role, actual prop line and odds before deciding; a matchup highlight is not a win probability or a proven betting edge.</p>${result.unavailableCategories.length?`<p>Not enough league data: ${result.unavailableCategories.map(k=>esc(rankLabel(k))).join(', ')}.</p>`:''}</details>`;
}
function rankColumns(){return rankSport==='NFL'?[['pts','Points'],['pass_yds','Passing Yards'],['rush_yds','Rushing Yards'],['rec','Receptions'],['rec_yds','Receiving Yards'],['rush_att','Rushing Attempts'],['pass_td','Passing TDs'],['rush_td','Rushing TDs'],['rec_td','Receiving TDs']]:rankMetrics()}
function rankingTable(){
 const allowed=rankView==='allowed',columns=rankColumns(),rows=orderedTeams();
 if(!rows.length)return empt(rankData?.no_stats?'No '+esc(rankData.season_label)+' stats yet':'No stats for this category',rankData?.no_stats?'Stats will appear after games are completed and reported. Previous seasons stay available in the selector above.':'Try another category or season.');
 return `<p class="field-help">All stats are per game${allowed?' allowed to opponents':''}. Click a column heading to sort. Sorted by <strong>${esc(rankLabel(rankMetric))}</strong>, ${rankOrder==='most'?'highest':'lowest'} first. Scroll across for all categories.</p>
 <div class="table-scroller ranking-scroll" tabindex="0" role="region" aria-label="${rankSport} ${allowed?'defense':'offense'} rankings. Scroll horizontally for all stats."><table class="table ranking-table"><thead><tr><th class="rank-position" scope="col">RANK</th><th class="rank-team-column" scope="col">TEAM</th><th scope="col"><abbr title="Games played">GP</abbr></th>${columns.map(([key,label])=>`<th scope="col" class="${key===rankMetric?'rank-sorted':''}" aria-sort="${key===rankMetric?(rankOrder==='most'?'descending':'ascending'):'none'}"><button class="rank-sort" data-action="rank-sort" data-stat="${key}" aria-label="Sort by ${esc(label)}${allowed?' allowed':''}">${esc(label)}${key===rankMetric?(rankOrder==='most'?' ↓':' ↑'):''}</button></th>`).join('')}</tr></thead>
 <tbody>${rows.map(r=>`<tr class="${rankTeam===r.team?'ranking-selected':''}"><td class="rank-position"><span class="rank-number">${r.rank}</span></td><td class="rank-team-column"><div class="rank-team-cell">${teamLogo(rankSport,r.team)}<div><button class="link-btn ranking-team" data-action="rank-team" data-team="${esc(r.team)}">${esc(r.name)}</button><a class="small" target="_blank" rel="noopener noreferrer" href="${esc(safeSource(allowed?(r.defense_source_url||r.source_url):r.source_url))}">Source ↗</a></div></div></td><td>${r[allowed?'defense_games':'games']}</td>${columns.map(([key])=>`<td class="${key===rankMetric?'rank-sorted':''}">${rankingValue(r,rankView,key)===null?'<span class="muted" title="Unavailable">—</span>':num(rankingValue(r,rankView,key),1)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function rankComparison(){
 const teams=rankData?.teams||[],a=teams.find(t=>t.team===rankTeam);
 if(!a)return '';
 const next=rankNextGame(a.team),other=rankOpponent||rankOther(next,a.team),b=teams.find(t=>t.team===other);
 const choices=[['','Next scheduled opponent'],...teams.filter(t=>t.team!==a.team).sort((x,y)=>x.name.localeCompare(y.name)).map(t=>[t.team,t.name])];
 const category=rankLabel(rankMetric),produced=rankingValue(a,'offense'),allowed=rankingValue(b,'allowed');
 const cell=(name,value,sub)=>`<div class="ranking-stat"><span>${esc(name)}</span><strong>${rankNumber(value)}<small>/ game</small></strong><p>${esc(sub)}</p></div>`;
 return `<section class="card pad ranking-comparison"><div class="card-head"><div><div class="eyebrow">OFFENSE VS OPPONENT</div><h2 class="ranking-matchup-title">${teamLogo(rankSport,a.team)}${esc(a.name)}${b?'<span class="muted">vs</span>'+teamLogo(rankSport,b.team)+esc(b.name):''}</h2></div><div class="ranking-compare-controls">${field('Team',select('rank-team',teams.slice().sort((x,y)=>x.name.localeCompare(y.name)).map(t=>[t.team,t.name]),rankTeam))}${field('Compare with',select('rank-opponent',choices,rankOpponent))}${b?'<button class="btn btn-primary" data-action="swap-rank-teams">⇄ Swap teams</button>':''}</div></div>
 ${!rankOpponent&&next?`<p class="muted">${esc(gameDateLabel(gameDay(next)))} · ${esc(day(gameDay(next)))} · ${next.season_type==='preseason'?'Upcoming game is preseason. ':''}Rankings below use ${esc(rankData.season_label)} ${rankType==='regular'?'regular season':'playoff'} stats.</p>`:rankOpponent?'<p class="muted">Manual team comparison</p>':`<p class="muted">${esc(nextGameMessage(rankSport,a.team))}</p>`}
 <div class="ranking-pair">${cell(a.name+' · '+category,produced,teamRank(a.team,'offense')+' · highest production')}${cell((b?.name||'Opponent')+' · '+category+' Allowed',allowed,b?teamRank(b.team,'allowed')+' · most allowed':'Checking this team’s next scheduled game…')}</div>
 ${b&&produced!==null&&allowed!==null?`<p class="ranking-readout">${esc(a.name)} average <strong>${rankNumber(produced)}</strong> ${esc(category.toLowerCase())} per game. ${esc(b.name)} allow <strong>${rankNumber(allowed)}</strong> per game.</p>`:''}
 <details class="finder-more"><summary>Compare all bet categories</summary><div class="table-scroller"><table class="table"><thead><tr><th>CATEGORY</th><th>${esc(a.team)} PER GAME</th><th>OFFENSE RANK</th><th>${esc(b?.team||'OPPONENT')} ALLOWED / GAME</th><th>MOST ALLOWED RANK</th></tr></thead><tbody>${rankMetrics().map(([key,label])=>`<tr><td>${esc(label)}</td><td>${rankNumber(rankingValue(a,'offense',key))}</td><td>${teamRank(a.team,'offense',key)}</td><td>${rankNumber(rankingValue(b,'allowed',key))}</td><td>${b?teamRank(b.team,'allowed',key):'Unavailable'}</td></tr>`).join('')}</tbody></table></div></details>
 ${next&&!rankOpponent?`<button class="btn btn-primary" data-action="rank-players" data-game-id="${esc(next.id)}" style="margin-top:18px">Find players in this game →</button>`:''}</section>`;
}
function keepRankingScroll(paint){
 const old=document.querySelector('.ranking-scroll'),position=old?{left:old.scrollLeft,top:old.scrollTop}:null;
 paint();
 const current=document.querySelector('.ranking-scroll');
 if(current&&position){current.scrollLeft=position.left;current.scrollTop=position.top;}
}
function rankingsPage(){
 const rows=orderedTeams(),category=rankLabel(rankMetric),allowed=rankView==='allowed',total=rankData?.expected_teams||(rankSport==='NFL'?32:30);
 const options=(rankConfig?.seasons?.[rankSport]||[]).map(x=>[x.value,x.label]);
 const stale=rankData?.updated_at&&Date.now()-Date.parse(rankData.updated_at)>86400000;
 return pageHead('TEAM RESEARCH','Rankings','See which teams produce the most—and which opponents allow the most. Choose the same category you’re researching on your sportsbook.',`<button class="btn" data-page="value">Defense vs Position →</button><button class="btn" data-action="rank-refresh" ${rankLoading?'disabled':''}>${rankLoading?'Updating…':'↻ Update Rankings'}</button>`)
 +`<div class="row-between" style="align-items:end;margin-bottom:20px;gap:20px;flex-wrap:wrap"><div class="select-tabs stats-sport-switch" role="group" aria-label="Rankings sport"><button type="button" data-action="rank-sport" data-sport="NFL" aria-pressed="${rankSport==='NFL'}" class="${rankSport==='NFL'?'active':''}">NFL</button><button type="button" data-action="rank-sport" data-sport="NBA" aria-pressed="${rankSport==='NBA'}" class="${rankSport==='NBA'?'active':''}">NBA</button></div>${field(rankSport+' stats season',select('rank-season',options,rankSeason))}</div>`+rankOpportunities()+`<section class="card pad"><div class="card-head"><h2>Offense & defense</h2></div>
 <div class="ranking-filters">${field('Bet category',select('rank-metric',rankMetrics(),rankMetric))}${field('Show',select('rank-view',[['offense','Offense — produced'],['allowed','Defense — allowed']],rankView))}${field('Sort',select('rank-order',[['most',allowed?'Most allowed first':'Highest first'],['fewest',allowed?'Fewest allowed first':'Lowest first']],rankOrder))}${field('Game type',select('rank-type',[['regular','Regular season'],['postseason','Playoffs']],rankType))}</div>
 <p class="field-help">${allowed?(rankOrder==='most'?'#1 gives up the most in the selected category.':'#1 gives up the fewest in the selected category.'):'Offense ranks each team’s production per game.'} Team totals include all players.</p></section>
 ${rankLoading?'<p class="note-box" role="status">Updating team and opponent statistics…</p>':''}${rankError?`<p class="note-box" role="alert">${esc(rankError)}${rankData?' Saved rankings remain below.':''}</p>`:''}
 ${rankData?`<div class="ranking-source"><span>${esc(rankData.season_label)} · ${rankType==='regular'?'Regular season':'Playoffs'} · ${rows.length} of ${total} teams · ${stale?'Saved data over 24 hours old · ':''}Fetched ${new Date(rankData.updated_at).toLocaleString()}</span><span>Source: ESPN</span></div>${rankData.errors?.length?`<details class="note-box"><summary>Some teams could not update (${rankData.errors.length})</summary>${rankData.errors.map(e=>`<p>${esc(e)}</p>`).join('')}</details>`:''}`:''}
 ${rankData?card(`${rankSport} ${allowed?'Defense':'Offense'} Rankings`,rankingTable(),'<span class="tag">PER GAME'+(allowed?' ALLOWED':'')+'</span>'):!rankLoading?card('Team rankings',empt('No rankings loaded','Press Update Rankings to get this season’s team and opponent statistics.')):''}
 ${rankComparison()}
 ${rankData?`<p class="footer-note">${esc(rankData.note)} Team averages provide matchup context; they are not individual player projections or a forecast. ${rankData.teams[0]?.source_url?`<a href="${esc(safeSource(rankData.teams[0].source_url))}" target="_blank" rel="noopener noreferrer">View source ↗</a>`:''}</p>`:''}`;
}
async function loadRankings(force=false){
 const request=++rankRequest;
 rankLoading=true;rankError='';if(['rankings','value'].includes(state.page))render();
 try{
   if(!rankConfig)rankConfig=await req('/rankings/config');
   if(request!==rankRequest)return;
   if(!rankSeason)rankSeason=rankConfig.defaults[rankSport];
   if(typeof loadPositionRanks==='function')loadPositionRanks();
   const key=rankKey(),params=new URLSearchParams({sport:rankSport,season:rankSeason,season_type:rankType,metric:rankMetric,view:rankView,order:rankOrder});
   if(rankData&&(rankData.sport!==rankSport||rankData.season!==rankSeason||rankData.season_type!==rankType))rankData=null;
   let data=rankCache.get(key);
   if(data?.no_stats&&Date.now()-Date.parse(data.updated_at)>=300000)data=null;
   if(!data||force){
     data=force?await req('/rankings/refresh?'+params,{method:'POST'}):await req('/rankings?'+params);
     if(data.missing||data.needs_refresh){if(!data.missing){rankCache.set(key,data);rankData=data}data=await req('/rankings/refresh?'+params,{method:'POST'})}
     rankCache.set(key,data);
   }
   if(request!==rankRequest)return;
   if(data.sport!==rankSport||data.season!==rankSeason||data.season_type!==rankType)throw new Error('The source returned a different season. Previous-season stats were not substituted.');
   rankData=data;
   if(!data.teams.some(t=>t.team===rankTeam))rankTeam=(rankSport==='NFL'&&data.teams.some(t=>t.team==='DAL')?'DAL':orderedTeams()[0]?.team)||'';
   if(rankTeam)loadNextGame(rankSport,rankTeam);
 }catch(e){if(request===rankRequest)rankError=e.message}
 finally{if(request===rankRequest){rankLoading=false;if(['rankings','value'].includes(state.page))render()}}
}
document.addEventListener('click',async e=>{
 const button=e.target.closest('[data-action]');if(!button)return;
 const action=button.dataset.action;
 if(action==='swap-rank-teams'){const other=rankOpponent||rankOther(rankNextGame(rankTeam),rankTeam);if(other){rankOpponent=rankTeam;rankTeam=other;render()}}
 if(action==='rank-refresh')await Promise.all([loadRankings(true),loadSelectableGames(true)]);
 if(action==='rank-sort'){const metric=button.dataset.stat;rankOrder=rankMetric===metric&&rankOrder==='most'?'fewest':'most';rankMetric=metric;render()}
 if(action==='rank-sport'){
   rankSport=button.dataset.sport;rankSeason=rankConfig?.defaults[rankSport]||null;rankMetric=rankSport==='NFL'?'pass_yds':'pts';highlightCategory='all';rankTeam='';rankOpponent='';rankData=rankCache.get(rankKey())||null;
   state.sport=rankSport;rememberLeague(rankSport);loadSelectableGames();await loadRankings();
 }
 if(action==='rank-team'){rankTeam=button.dataset.team;rankOpponent='';loadNextGame(rankSport,rankTeam);render();document.querySelector('.ranking-comparison')?.scrollIntoView({block:'start',behavior:'smooth'})}
 if(action==='highlight-compare'){rankTeam=button.dataset.team;rankOpponent=button.dataset.opponent;rankMetric=button.dataset.stat;render();document.querySelector('.ranking-comparison')?.scrollIntoView({block:'start',behavior:'smooth'})}
 if(action==='rank-players'||action==='highlight-players'){
   const game=(state.games[rankSport]||[]).find(g=>g.id===button.dataset.gameId);if(!game)return;if(!selectableGameDates(rankSport).includes(gameDay(game))){state.sport=rankSport;state.selectedGame=game;state.scheduleDate=gameDay(game);state.page='matchups';render();loadGameOverview(false);return}
   state.sport=rankSport;rememberLeague(rankSport);restoreFinder(rankSport);state.selectedGame=game;state.matchup=game.home_abbr+','+game.away_abbr;state.customTeams='';state.results=null;state.matchupIntel=null;
   const metric=button.dataset.stat||rankMetric,stat=Object.hasOwn(statDefaults[rankSport],metric)?metric:rankSport==='NFL'?'rec_yds':'pts';
   if(action==='highlight-players'&&!(rankSport==='NFL'&&metric==='pts')){state.customTeams=button.dataset.team;state.matchup=state.customTeams}
   state.filters.stat=stat;state.filters.threshold=storedStat(stat)??statDefaults[rankSport][stat];state.filters.before=gameDay(game);
   state.page=rankSport==='NFL'?'nfl':'consistency';await loadSnapshots();render();loadGameOverview(true);window.scrollTo(0,0);
   if(action==='highlight-players'&&state.customTeams)notify('Showing '+state.customTeams+' players · '+rankLabel(stat));
 }
});
document.addEventListener('change',e=>{
 const id=e.target.id;
 if(id==='f-highlight-category'){highlightCategory=e.target.value;const host=document.querySelector('#matchup-opportunities');if(host)host.innerHTML=rankOpportunitiesBody()}
 if(id==='f-rank-team'){rankTeam=e.target.value;rankOpponent='';loadNextGame(rankSport,rankTeam);render()}
 if(id==='f-rank-metric'){rankMetric=e.target.value;render()}
 if(id==='f-rank-view'){rankView=e.target.value;rankOrder='most';render()}
 if(id==='f-rank-order'){rankOrder=e.target.value;render()}
 if(id==='f-rank-opponent'){rankOpponent=e.target.value;render()}
 if(id==='f-rank-season'||id==='f-rank-type'){
   if(id==='f-rank-season')rankSeason=Number(e.target.value);else rankType=e.target.value;
   rankData=rankCache.get(rankKey())||null;rankOpponent='';loadRankings();
 }
});

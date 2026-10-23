/* Player TD trends tied to the selected opponent, without paid odds requests. */
const tdRecords=new Map();
const tdOpenGames=new Set();
let tdLast=10,tdCategory='all',tdSort='recent',tdExpanded='';
function tdKey(){const choice=gameTeamChoice();return choice&&state.selectedGame?[gameTeamKey(),choice.season,choice.type,tdLast].join(':'):''}
function tdPanel(){if(state.selectedGame?.sport!=='NFL')return '';return `<details class="td-opportunities" id="td-opportunities" data-game-key="${esc(gameTeamKey())}" ${tdOpenGames.has(gameTeamKey())?'open':''}><summary>Player TD Opportunities <span id="td-count">${tdCount()}</span></summary><div id="td-opportunities-body">${tdBody()}</div></details>`}
function tdCount(){if(state.selectedGame?.status==='final')return 'Finished game';const data=tdRecords.get(tdKey())?.data;return data?data.rows.filter(r=>tdCategory==='all'||r.stat===tdCategory).length+' matches'+(tdCategory==='all'?'':' of '+data.rows.length+' total'):'Checking saved player stats…'}
function tdBody(){
 const record=tdRecords.get(tdKey()),data=record?.data;
 const controls=`<div class="td-controls">${field('TD category',select('td-category',[['all','All TD categories'],['pass_td','Passing Touchdowns'],['rush_td','Rushing Touchdowns'],['rec_td','Receiving Touchdowns']],tdCategory))}${field('Past games',`<input class="input" id="td-last" type="number" min="1" max="100" step="1" value="${tdLast}">`)}${field('Sort players by',select('td-sort',[['recent','Recent TD total'],['season','Season TD total']],tdSort))}<button class="btn btn-small" data-action="refresh-td-players" ${record?.loading?'disabled':''}>${record?.loading?'Checking…':'Check Players'}</button></div>`;
 if(state.selectedGame?.status==='final')return '<p class="muted">Finished game. Active player opportunities are not shown.</p>';
 const error=record?.error?`<p class="note-box" role="alert">${esc(record.error)}${data?' Saved checks remain below.':''}</p>`:'';
 if(!data)return controls+error+`<p class="muted">${record?.loading?'Comparing saved TD production with opponent allowance…':'Check Players compares saved game logs with this season’s team stats.'}</p>`;
 const rows=data.rows.filter(r=>tdCategory==='all'||r.stat===tdCategory).slice().sort((a,b)=>tdSort==='season'?b.season_total-a.season_total||b.recent_total-a.recent_total:b.recent_total-a.recent_total||b.season_total-a.season_total);
 const defense=(d,label)=>d?`<strong>${num(d.value,1)}</strong> ${esc(label)} / game<small>#${d.rank} most allowed of ${d.teams} · ${d.games} games</small>`:`<span class="muted">${esc(label)} unavailable</span>`;
 return controls+error+`<p class="field-help">${esc(data.season_label)} ${data.season_type==='regular'?'regular season':'playoffs'} · Results before ${esc(data.before)} · Recent windows may span seasons. Receivers score receiving TDs; passing TDs are credited to the passer.</p>
 ${rows.length?`<div class="table-scroller"><table class="table td-player-table"><thead><tr><th>PLAYER / CATEGORY</th><th>RECENT TDs</th><th>SEASON TDs</th><th>OPPONENT ALLOWS</th><th>PAST GAMES</th></tr></thead><tbody>${rows.map(r=>{
 const key=r.player_id+':'+r.stat;
 return `<tr><td><strong>${playerLabel(r.player,r.position)}</strong><small>${teamLogo('NFL',r.team)} ${esc(r.team)} · ${esc(r.label)}</small><span class="td-player-signal">${esc(r.signal)}</span></td><td><strong>${r.recent_total} TDs</strong><small>Scored in ${r.recent_scoring_games} of ${r.recent_games} known games</small><small>${r.window_games} of ${data.last} games available${r.missing_recent?' · '+r.missing_recent+' missing TD stats':''}</small></td><td><strong>${r.season_total} TDs</strong><small>${r.season_games} games${r.season_missing?' · '+r.season_missing+' missing':''}</small><small>${r.season_rank?'#'+r.season_rank.rank+' of '+r.season_rank.players+' saved players':'Season rank unavailable'}${r.season_signal?' · top season TD group':''}</small></td><td><strong>${esc(r.opponent)}</strong><div>${defense(r.defense_td,r.label+' allowed')}</div><div class="td-yards">${defense(r.defense_yards,r.yard_label+' allowed')}</div></td><td><button class="link-btn" data-action="td-player-history" data-player-key="${esc(key)}">${tdExpanded===key?'Hide games ↑':'See games →'}</button><button class="link-btn" data-action="td-props" data-stat="${r.stat}">Check prop lines →</button></td></tr>
 ${tdExpanded===key?`<tr><td colspan="5"><div class="td-logs">${r.logs.map(l=>`<div class="prop-log ${l.tds>0?'hit':'miss'}"><small>${esc(day(l.date))} · ${esc(l.opponent)}</small><strong>${l.tds} ${l.tds===1?'TD':'TDs'}</strong><a href="${esc(safeSource(l.source_url))}" target="_blank" rel="noopener noreferrer">${esc(l.source)} ↗</a></div>`).join('')}</div><p class="field-help">These are actual ${esc(r.label.toLowerCase())} in saved games, not historical prop lines or a forecast.</p></td></tr>`:''}`;
 }).join('')}</tbody></table></div>`:`<p class="note-box">${esc(data.message||'No players meet the rules in this TD category.')} Missing TD logs need a season import; missing opponent fields need Refresh Team Stats.</p>`}
 <details class="opportunity-rules"><summary>How player opportunities are picked</summary><p>The opponent must rank in the top third for this TD category or its related yardage allowed, with at least three games and stats for 80% of the league. Players need TDs in at least two of three or more recent games, or at least two season TDs and a top-10% rank (at least the top three) among saved players. Latest saved activity must be within 45 days of game day. Missing stats are excluded and counted. A yardage matchup is labeled separately from a TD-allowance matchup.</p><p>${esc(data.note)}</p></details>`;
}
function paintTDPanel(){const host=document.querySelector('#td-opportunities-body');if(host){host.innerHTML=tdBody();document.querySelector('#td-count').textContent=tdCount()}}
async function loadTDOpportunities(force=false){
 if(state.selectedGame?.sport!=='NFL'||!gameTeamChoice())return;
 const key=tdKey(),prior=tdRecords.get(key);if(prior?.loading||!force&&prior?.data&&Date.now()-prior.fetched<180000)return;
 const game=state.selectedGame,choice={...gameTeamChoice()};tdRecords.set(key,{...prior,loading:true,error:''});paintTDPanel();
 try{const data=await req('/game/player-opportunities?'+new URLSearchParams({game_id:game.id,last:tdLast,season:choice.season,season_type:choice.type}));tdRecords.set(key,{data,fetched:Date.now()})}
 catch(e){tdRecords.set(key,{...prior,error:'Player comparison unavailable: '+e.message})}
 if(key===tdKey())paintTDPanel();
}
document.addEventListener('click',e=>{
 const summary=e.target.closest('#td-opportunities > summary');if(summary){const panel=summary.parentElement;if(panel.open)tdOpenGames.delete(panel.dataset.gameKey);else tdOpenGames.add(panel.dataset.gameKey);return}
 const button=e.target.closest('[data-action]');if(!button)return;
 if(button.dataset.action==='refresh-td-players'){
  const n=Number(document.querySelector('#td-last')?.value);if(!Number.isInteger(n)||n<1||n>100)return notify('Choose 1 to 100 past games.',true);
  tdLast=n;tdExpanded='';loadTDOpportunities(true);
 }
 if(button.dataset.action==='td-player-history'){tdExpanded=tdExpanded===button.dataset.playerKey?'':button.dataset.playerKey;paintTDPanel()}
 if(button.dataset.action==='td-props'){propScope();propView.open=true;propView.category=button.dataset.stat;const panel=document.querySelector('#game-player-props');if(panel){panel.open=true;paintProps();loadGameProps(false);panel.scrollIntoView({block:'start',behavior:'smooth'})}}
});
document.addEventListener('toggle',e=>{if(e.target.id==='td-opportunities'&&e.target.isConnected){if(e.target.open)tdOpenGames.add(e.target.dataset.gameKey);else tdOpenGames.delete(e.target.dataset.gameKey)}},true);
document.addEventListener('change',e=>{if(e.target.id==='f-td-category'){tdCategory=e.target.value;paintTDPanel()}if(e.target.id==='f-td-sort'){tdSort=e.target.value;paintTDPanel()}});

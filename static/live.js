/* Public-score polling is independent of sportsbook-credit refreshes. */
const liveBoards=new Map(),gameOverviews=new Map();
let scorePollRunning=false;
function localTime(stamp){if(!stamp)return 'Not updated';const value=stamp.includes('T')?stamp:stamp.replace(' ','T')+'Z';return new Date(value).toLocaleTimeString('en-US',{timeZone:state.settings?.timezone||'America/Chicago',hour:'numeric',minute:'2-digit',second:'2-digit'})}
function signedLine(point){const n=Number(point);return n===0?'PK':(n>0?'+':'')+n}
function gameStatusText(game){
 if(game.status==='live')return game.status_detail||((game.clock||'')+(game.period?' · Q'+game.period:''))||'In progress';
 if(game.status==='final')return game.status_detail||'Final';
 return new Date(game.starts_at).toLocaleTimeString('en-US',{timeZone:state.settings?.timezone||'America/Chicago',hour:'numeric',minute:'2-digit'});
}
function liveScoreNote(){
 const board=liveBoards.get(state.sport+':'+state.scheduleDate);
 return `<span class="${board?.stale?'yellow':'muted'}">${board?.stale?'Score update unavailable · showing saved data. ':''}Scores: ESPN${board?.fetched_at?' · Updated '+localTime(board.fetched_at):' · waiting for update'} · Checks every 30 seconds while this page is open.</span>`;
}
function gameOverviewPanel(){return state.selectedGame?`<section class="card pad game-overview" id="game-overview">${gameOverviewBody()}</section>`:''}
function gameOverviewBody(){
 const game=state.selectedGame;if(!game)return '';
 const record=gameOverviews.get(state.sport+':'+game.id),data=record?.data,prices=data?.prices,quotes=prices?.quotes||[];
 const score=(side)=>game[side+'_score']===null||game[side+'_score']===undefined?'—':game[side+'_score'];
 const phase=game.status==='live'?'LIVE':game.status==='final'?'FINAL':'UPCOMING';
 const scoreStamp=game.score_fetched_at||data?.score_fetched_at;
 const observed=prices?.observed_at;
 const old=observed&&Date.now()-Date.parse(observed)>900000;
 const phaseAtFetch=prices?.observed_game_state;
 const quotePhase=phaseAtFetch==='live'?'Retrieved during play':phaseAtFetch==='scheduled'?'Retrieved before play':phaseAtFetch==='final'?'Retrieved after final':'Original game phase unknown';
 const format=q=>q.market==='totals'?`${esc(q.selection)} ${q.point} <strong>${odds(q.price)}</strong>`:`${esc(q.selection===game.home?game.home_abbr:q.selection===game.away?game.away_abbr:q.selection)} ${q.market==='spreads'?signedLine(q.point)+' ':''}<strong>${odds(q.price)}</strong>`;
 const cell=(book,market)=>{const rows=quotes.filter(q=>q.book===book&&q.market===market);return rows.length?rows.map(q=>`<div class="game-price-line">${format(q)}${q.provider_updated_at?`<small>Book updated ${localTime(q.provider_updated_at)}</small>`:''}</div>`).join(''):'<span class="muted">Unavailable</span>'};
 return `<div class="card-head"><div><div class="eyebrow">SELECTED GAME</div><h2>${esc(game.away)} at ${esc(game.home)}</h2></div><span class="tag ${game.status==='live'?'pending':game.status==='final'?'win':''}">${phase}</span></div>
 <div class="selected-score"><div>${teamLogo(state.sport,game.away_abbr)}<span>${esc(game.away_abbr)} · AWAY</span><strong>${score('away')}</strong></div><div class="selected-clock">${esc(gameStatusText(game))}<small>${day(gameDay(game))}</small></div><div>${teamLogo(state.sport,game.home_abbr)}<span>${esc(game.home_abbr)} · HOME</span><strong>${score('home')}</strong></div></div>
 <p class="field-help ${data?.score_stale?'yellow':''}">${data?.score_error?esc(data.score_error)+' ':''}Score updated ${localTime(scoreStamp)} · <a href="${esc(safeSource(game.score_source_url||data?.score_source_url))}" target="_blank" rel="noopener noreferrer">ESPN source ↗</a></p>
 ${gameTeamStatsPanel()}
 ${game.status==='final'?'<p class="note-box">Final score. Sportsbook prices for finished games are not shown here.</p>':`
 <div class="row-between game-price-head"><h3>Moneyline · Spread · Over/Under</h3><button class="btn btn-small" data-action="refresh-game-prices" ${record?.loading?'disabled':''}>${record?.loading?'Loading prices…':'Refresh Prices'}</button></div>
 ${record?.error||data?.odds_error?`<p class="note-box">${esc(record?.error||data.odds_error)}</p>`:''}
 ${quotes.length?`<div class="table-scroller"><table class="table game-price-table"><thead><tr><th>BOOK</th><th>MONEYLINE</th><th>SPREAD</th><th>OVER / UNDER TOTAL</th></tr></thead><tbody>${['FanDuel','Caesars','DraftKings'].filter(book=>quotes.some(q=>q.book===book)).map(book=>`<tr><td><strong>${book}</strong></td><td>${cell(book,'h2h')}</td><td>${cell(book,'spreads')}</td><td>${cell(book,'totals')}</td></tr>`).join('')}</tbody></table></div><p class="field-help">${old?'Saved over 15 minutes ago · ':''}${esc(prices.source||'Saved prices')} · Retrieved ${localTime(observed)} · ${quotePhase}. ${esc(prices.note||'Check availability at the book.')}</p>`:record?.loading?'<p class="muted">Getting the game’s available sportsbook prices…</p>':'<p class="muted">No usable quotes saved for your three books. Refresh Prices checks the connected odds feed.</p>'}
 <p class="field-help">Scores refresh automatically. Prices refresh when you select a game or press Refresh Prices, with a two-minute cache to limit odds-feed credits.</p>`}`;
}
function newestGame(old,current){const oldTime=Date.parse(old?.score_fetched_at||''),newTime=Date.parse(current?.score_fetched_at||'');return Number.isFinite(oldTime)&&(!Number.isFinite(newTime)||oldTime>newTime)?{...current,...old}:{...old,...current}}
function paintGameOverview(){const host=document.querySelector('#game-overview');if(host){const stats=host.querySelector('#game-team-stats');host.innerHTML=gameOverviewBody();if(stats?.dataset.gameKey===gameTeamKey())host.querySelector('#game-team-stats')?.replaceWith(stats);if(state.selectedGame?.status==='final')paintTDPanel()}}
async function loadGameOverview(refreshPrices=true){
 const game=state.selectedGame;if(!game)return;
 loadGameTeamStats();
 const sport=state.sport,key=sport+':'+game.id;
 if(gameOverviews.get(key)?.loading)return;
 const record={...(gameOverviews.get(key)||{}),loading:true,error:''};gameOverviews.set(key,record);paintGameOverview();
 try{
   const data=await req('/game/overview?'+new URLSearchParams({sport,game_id:game.id}),refreshPrices?{method:'POST'}:{});
   gameOverviews.set(key,{data,loading:false});
   if(state.sport!==sport||state.selectedGame?.id!==game.id)return;
   state.selectedGame=newestGame(state.selectedGame,data.game);state.games[sport]=(state.games[sport]||[]).map(g=>g.id===game.id?newestGame(g,data.game):g);paintGameOverview();
 }catch(e){gameOverviews.set(key,{...record,loading:false,error:e.message});if(state.sport===sport&&state.selectedGame?.id===game.id)paintGameOverview()}
}
async function refreshLiveScores(){
 if(scorePollRunning||document.hidden)return;
 const page=state.page;if(!['matchups','consistency','nfl','value','rankings'].includes(page))return;
 const sport=page==='value'?researchSport:page==='rankings'?rankSport:state.sport;
 const date=page==='matchups'?state.scheduleDate:['value','rankings'].includes(page)?todayGameDate():state.selectedGame?gameDay(state.selectedGame):todayGameDate();
 scorePollRunning=true;
 try{
   const data=await req('/scoreboard?'+new URLSearchParams({sport,date}));liveBoards.set(sport+':'+date,data);
   const phases=rows=>JSON.stringify(rows.filter(g=>gameDay(g)===date).map(g=>[g.id,g.status]).sort());
   const phasesChanged=phases(state.games[sport]||[])!==phases(data.games);
   state.games[sport]=[...data.games,...(state.games[sport]||[]).filter(g=>gameDay(g)!==date)];
   if(state.selectedGame?.sport===sport){const current=data.games.find(g=>g.id===state.selectedGame.id);if(current){state.selectedGame=newestGame(state.selectedGame,current);const record=gameOverviews.get(sport+':'+current.id);if(record?.data){record.data.score_stale=data.stale;record.data.score_error=data.error;record.data.score_fetched_at=data.fetched_at}}paintGameOverview();if(typeof loadBoxScore==='function'&&$('#boxscore-slot'))loadBoxScore()}
   if(state.page==='matchups'&&state.sport===sport&&state.scheduleDate===date){const host=$('#games-board');if(host)host.innerHTML=matchupCards();const note=$('#score-board-note');if(note)note.innerHTML=liveScoreNote()}
   if(state.page==='rankings'&&rankSport===sport){const check=scheduleChecks.get(sport+':'+date),failed=!!(data.stale||data.error),failureChanged=check?.failed!==failed;if(!check?.running)scheduleChecks.set(sport+':'+date,{finished:Date.now(),failed});const host=$('#matchup-opportunities');if(host&&(phasesChanged||failureChanged))host.innerHTML=rankOpportunitiesBody()}
   if(state.page==='value'&&researchSport===sport){const refreshed=await req('/odds/compare?'+new URLSearchParams({sport,books:'FanDuel,Caesars,DraftKings'}));if(state.page==='value'&&researchSport===sport){oddsData=refreshed;const host=$('#best-prices-host');if(host)host.innerHTML=bestPricesPanel()}}
 }catch{const note=$('#score-board-note');if(note)note.textContent='Score update unavailable. Showing saved scores.'}
 finally{scorePollRunning=false;if(state.page==='matchups'&&(state.sport!==sport||state.scheduleDate!==date))refreshLiveScores()}
}
setInterval(refreshLiveScores,30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshLiveScores()});
document.addEventListener('click',e=>{if(e.target.closest('[data-action="refresh-game-prices"]'))loadGameOverview(true)});
document.addEventListener('keydown',e=>{const card=e.target.closest('.game-card[data-action="pick-game"]');if(card&&(e.key==='Enter'||e.key===' ')){e.preventDefault();card.click()}});

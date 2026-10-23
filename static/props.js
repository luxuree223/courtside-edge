/* Exact sportsbook props beside the existing player finder. */
let propView={key:'',open:false,data:null,busy:false,message:'',quoteId:'',history:null,last:10,kind:'regular',category:'',book:'all',playerMatch:'',includePrevious:false,sort:'player',direction:'asc'};
function propSortHeader(key,label){const active=propView.sort===key;return `<th aria-sort="${active?(propView.direction==='desc'?'descending':'ascending'):'none'}"><button type="button" class="prop-sort-button" data-action="sort-props" data-key="${key}">${label} <span aria-hidden="true">${active?(propView.direction==='desc'?'↓':'↑'):'↕'}</span></button></th>`}
function propHitCell(q,key){const h=q.recent?.[key];if(!q.player_id)return '<td class="prop-hit-count"><small>Player match needed</small></td>';if(!h?.sample)return '<td class="prop-hit-count"><small>No usable games</small></td>';return `<td class="prop-hit-count"><strong>${h.hits} / ${h.sample}</strong><small>${pct(h.rate)}${h.missing?' of known stats':''}</small>${h.games<h.requested?`<small>Only ${h.games} of ${h.requested} games saved</small>`:''}${h.missing?`<small>${h.missing} missing stat${h.missing===1?'':'s'}</small>`:''}${h.pushes?`<small>${h.pushes} push${h.pushes===1?'':'es'}</small>`:''}</td>`}
function propCategories(){return (state.sport==='NBA'?nbaStats:nflStats).filter(([key])=>key!=='targets')}
function propScope(){
 const key=state.selectedGame?state.sport+':'+state.selectedGame.id:'';
 if(key!==propView.key)propView={key,open:false,data:null,busy:false,message:'',quoteId:'',history:null,last:state.filters.last||10,kind:state.filters.season_type||'regular',category:propCategories().some(([key])=>key===state.filters.stat)?state.filters.stat:propCategories()[0][0],book:'all',playerMatch:'',includePrevious:false,sort:'player',direction:'asc'};
 return key;
}
function gamePropsPanel(){
 propScope();
 return `<details class="card pad game-props" id="game-player-props" ${propView.open?'open':''}><summary><span>Game Player Props</span><small>${state.selectedGame?'Lines, odds & past results':'Select a game to see its props'}</small></summary><div id="game-props-body">${propsBody()}</div></details>`;
}
function propsBody(){
 if(!state.selectedGame)return '<p class="muted">Choose a game above. Its player props and past-game checks will appear here.</p>';
 const data=propView.data,rows=propSort.sort((data?.quotes||[]).filter(q=>(!propView.category||q.stat===propView.category)&&(propView.book==='all'||q.book===propView.book)),propView.sort||'player',propView.direction||'asc');
 const stale=stamp=>Date.now()-Date.parse(stamp)>900000;
 const sport=state.sport.toLowerCase(),kind=state.sport==='NBA'?'basketball':'football';
 return `<p class="muted prop-game">${esc(state.selectedGame.away)} at ${esc(state.selectedGame.home)} · ${day(gameDay(state.selectedGame))}</p>
 ${historyScopeSwitch("prop-include-previous",propView.includePrevious,data?.history_window?.label)}<div class="prop-controls">${field('Prop category',select('prop-category',[['','All saved categories'],...propCategories()],propView.category))}${field('Sportsbook',select('prop-book',[['all','All available books'],...['FanDuel','Caesars','DraftKings'].filter(book=>data?.quotes?.some(q=>q.book===book)).map(book=>[book,book])],propView.book))}<button class="btn btn-primary" data-action="refresh-props" ${propView.busy?'disabled':''}>${propView.busy?'Loading…':'Get Latest Props'}</button></div>
 <p class="field-help">Click a player to check this exact Over or Under line. Updates use odds-feed credits; all categories cost more than one category.</p>
 <div class="head-actions"><a class="link-btn" href="https://www.covers.com/sport/${kind}/${sport}/player-props" target="_blank" rel="noopener noreferrer">Open Covers player props ↗</a>${!data?.feed_configured?'<button class="link-btn" data-page="value">Connect odds feed →</button>':''}</div>
 ${propView.message?`<p class="note-box" role="status">${esc(propView.message)}</p>`:''}
 ${data&&!data.feed_configured?'<p class="field-help">Automatic lines need your odds API key and player-prop coverage. You can enter a line from FanDuel, Caesars or DraftKings below.</p>':''}
 <div id="prop-history">${propHistoryPanel()}</div>
 ${rows.length?`<div class="table-scroller"><table class="table props-table"><thead><tr>${propSortHeader('player','PLAYER · CLICK TO CHECK')}${propSortHeader('prop','PROP')}${propSortHeader('book','BOOK')}${propSortHeader('odds','ODDS')}${propSortHeader('last5','LAST 5')}${propSortHeader('last10','LAST 10')}${propSortHeader('time','SOURCE / TIME')}</tr></thead><tbody>${rows.map(q=>`<tr class="${q.id===propView.quoteId?'prop-selected':''}"><td><button class="link-btn prop-player" data-action="check-prop" data-id="${esc(q.id)}">${playerLabel(q.player,q.position)} →</button><small class="small">${esc(q.team||'Player match needed')}</small></td><td>${esc(q.side)} ${q.line} ${esc(statName(q.stat,state.sport))}</td><td>${esc(q.book)}</td><td><strong>${odds(q.price)}</strong></td>${propHitCell(q,'last5')}${propHitCell(q,'last10')}<td><small>${esc(q.label)} · ${new Date(q.observed_at).toLocaleString()}${stale(q.observed_at)?' · Saved over 15 minutes ago':''}</small>${q.provider_updated_at?`<small class="small">Book updated: ${new Date(q.provider_updated_at).toLocaleString()}</small>`:''}${q.source_url?`<a class="small" href="${esc(safeSource(q.source_url))}" target="_blank" rel="noopener noreferrer">Open source ↗</a>`:''}</td></tr>`).join('')}</tbody></table></div>`:data?'<p class="prop-empty">No saved props match these filters. Get Latest Props or enter the line you see in your book.</p>':propView.busy?'<p class="muted">Loading saved props…</p>':''}
 <p class="field-help">Last 5 / Last 10 check this exact Over or Under line using ${esc(data?.history_season_type||state.selectedGame.season_type)} games before ${esc(data?.history_before||gameDay(state.selectedGame))}. ${propView.includePrevious?"The previous season is included only when needed to fill the requested games.":"Only this season is counted, even when fewer than 5 or 10 games have been played."} Missing stats and unavailable games are shown; pushes are separate from hits. Click a column heading to sort.</p><details class="finder-more prop-manual"><summary>Enter a line from your sportsbook</summary><p class="field-help">Copy the exact player, line and odds. This saves a research quote, with an “Entered by you” label.</p><div class="finder-extra-grid">
 ${field('Player',`<input class="input" id="prop-player" list="prop-player-list" placeholder="Choose or type a player"><datalist id="prop-player-list">${(data?.players||[]).map(p=>`<option value="${esc(p.player)}">${esc(p.team)}</option>`).join('')}</datalist>`)}
 ${field('Bet type',select('prop-stat',propCategories(),propView.category||propCategories()[0][0]))}
 ${field('Side',select('prop-side',[['Over','Over'],['Under','Under']],'Over'))}
 ${field('Line',`<input class="input" type="number" min="0" step="any" id="prop-line" placeholder="Example: 2.5">`)}
 ${field('American odds',`<input class="input" type="number" id="prop-price" step="1" placeholder="Example: -110">`)}
 ${field('Sportsbook',select('prop-manual-book',[['FanDuel','FanDuel'],['Caesars','Caesars'],['DraftKings','DraftKings']],propView.book==='all'?'FanDuel':propView.book))}
 ${field('Source link (optional)',`<input class="input" type="url" id="prop-source" placeholder="https://…">`)}
 </div><button class="btn btn-primary" data-action="save-prop" style="margin-top:16px">Save Line & Check Player →</button></details>
 <p class="field-help">${esc(data?.note||'Only actual feed prices or lines you enter are listed. Missing prices stay unavailable.')} Screenshot readings are not imported as verified sportsbook prices.</p>`;
}
function propHistoryPanel(){
 const h=propView.history;if(!h)return '';
 const q={...h.quote,position:h.player?.position||h.quote.position};
 const controls=`<div class="prop-history-controls">${field('Past games',`<input class="input" id="prop-last" type="number" min="1" max="100" step="1" value="${propView.last}">`)}${field('Game type',select('prop-kind',[['regular','Regular season'],['preseason','Preseason'],['postseason','Playoffs']],propView.kind))}<button class="btn btn-small" data-action="recheck-prop">Check Again</button></div>`;
 return `<section class="prop-history-card"><div class="card-head"><div><div class="eyebrow">EXACT LINE CHECK</div><h3>${playerLabel(q.player,q.position)} · ${esc(q.side)} ${q.line} ${esc(statName(q.stat,state.sport))}</h3><p>${esc(q.book)} · ${odds(q.price)} · ${q.source==='manual'?'Entered by you':'Saved feed quote'}</p></div><button class="link-btn" data-action="close-prop">Close ×</button></div>${controls}
 ${h.missing_stats?`<p class="field-help">${h.missing_stats} of the last ${h.window_games} played games have missing stats. They are excluded from the hit rate, not counted as misses.</p>`:''}
 ${h.unmatched?`<p class="note-box">${esc(h.message)}</p>${field('Match to saved player',select('prop-match',[['','Choose the correct player'],...(h.players||[]).map(p=>[p.player_id,p.player+' · '+p.team])],propView.playerMatch))}<p class="field-help">Choose only if this is the same player. Names are never matched by guessing.</p>`:`${h.manual_player_match?`<p class="note-box">You matched this quote to ${esc(h.player.player)}.</p>`:''}
 ${h.sample?`<div class="prop-hit-summary"><strong>${h.hits} of ${h.sample}</strong><span>games cleared this ${esc(q.side.toLowerCase())} line · ${pct(h.rate)} of games</span>${h.pushes?`<small>${h.pushes} push${h.pushes===1?'':'es'} · ${h.misses} miss${h.misses===1?'':'es'}. Pushes are separate from hits and misses.</small>`:''}</div>${h.sample<h.requested?`<p class="field-help">Only ${h.sample} of ${h.requested} requested games have usable saved stats.</p>`:''}
 <div class="prop-game-logs">${h.logs.map(l=>`<div class="prop-log ${l.result}"><small>${day(l.date)} · ${esc(l.opponent)}</small><strong>${l.value}</strong><span>${l.result==='hit'?'✓ Cleared':l.result==='push'?'= Push':'× Missed'}</span>${l.source_url?`<a href="${esc(safeSource(l.source_url))}" target="_blank" rel="noopener noreferrer">${esc(l.source||'Source')} ↗</a>`:''}</div>`).join('')}</div><p class="field-help">${propView.kind==='regular'?'Regular season':propView.kind==='postseason'?'Playoff':'Preseason'} games before ${esc(h.before)} · Latest saved game: ${esc(h.logs[0].date)}. Same line checked against every game; individual historical closing lines may have differed.</p>`:'<p class="note-box">No usable saved games for this player and game type. Update Game Results or choose another game type.</p>'}
 <p class="field-help">Past results describe this sample. They do not establish the chance of winning this prop.</p>`}</section>`;
}
function paintProps(){const body=document.querySelector('#game-props-body');if(body)body.innerHTML=propsBody()}
async function loadGameProps(refresh=false){
 const key=propScope();if(!key||propView.busy)return;
 const sport=state.sport,game=state.selectedGame,category=propView.category,includePrevious=propView.includePrevious;
 propView.busy=true;propView.message='';paintProps();
 try{
   const data=await req('/props'+(refresh?'/refresh':'')+'?'+new URLSearchParams({sport,game_id:game.id,include_previous:!!includePrevious,...(refresh?{stat:category}:{})}),refresh?{method:'POST'}:{});
   if(propView.key!==key||propView.includePrevious!==includePrevious)return;
   propView.data=data;propView.message=data.message||'';
 }catch(e){if(propView.key===key)propView.message=e.message}
 finally{if(propView.key===key){propView.busy=false;paintProps();if(propView.includePrevious!==includePrevious)loadGameProps()}}
}
let propHistoryRequest=0;
async function checkProp(id,playerMatch=''){
 const key=propScope(),count=Number(document.querySelector('#prop-last')?.value??propView.last);
 if(!Number.isInteger(count)||count<1||count>100)return notify('Choose 1 to 100 past games.',true);
 propView.last=count;propView.kind=document.querySelector('#f-prop-kind')?.value||propView.kind;
 const request=++propHistoryRequest;propView.quoteId=id;propView.playerMatch=playerMatch;
 try{
   const h=await req('/props/'+encodeURIComponent(id)+'/history?'+new URLSearchParams({last:propView.last,season_type:propView.kind,player_id:playerMatch,include_previous:!!propView.includePrevious}));
   if(request!==propHistoryRequest||propView.key!==key||propView.quoteId!==id)return;
   propView.history=h;paintProps();document.querySelector('#prop-history')?.scrollIntoView({block:'nearest',behavior:'smooth'});
 }catch(e){notify(e.message,true)}
}
async function saveManualProp(){
 const game=state.selectedGame;if(!game)return;
 const player=$('#prop-player')?.value.trim(),line=$('#prop-line')?.value,price=$('#prop-price')?.value;
 if(!player||line===''||price==='')return notify('Enter the player, line and odds.',true);
 const key=propScope(),stat=$('#f-prop-stat').value;
 const body={sport:state.sport,game_id:game.id,player,stat,side:$('#f-prop-side').value,line:Number(line),price:Number(price),book:$('#f-prop-manual-book').value,source_url:$('#prop-source').value.trim()};
 try{
   const saved=await req('/props/manual',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   if(propView.key!==key)return;
   propView.category=stat;propView.book='all';await loadGameProps();await checkProp(saved.id);notify('Research line saved.');
 }catch(e){notify(e.message,true)}
}
document.addEventListener('toggle',e=>{
 if(e.target.id!=='game-player-props')return;
 propScope();propView.open=e.target.open;
 if(propView.open&&!propView.data)loadGameProps();
},true);
document.addEventListener('click',async e=>{
 const button=e.target.closest('[data-action]');if(!button)return;
 if(button.dataset.action==='refresh-props')await loadGameProps(true);
 if(button.dataset.action==='sort-props'){const key=button.dataset.key;if(!['player','prop','book','odds','last5','last10','time'].includes(key))return;propView.direction=propView.sort===key?(propView.direction==='asc'?'desc':'asc'):['odds','last5','last10','time'].includes(key)?'desc':'asc';propView.sort=key;paintProps()}
 if(button.dataset.action==='check-prop')await checkProp(button.dataset.id);
 if(button.dataset.action==='save-prop')await saveManualProp();
 if(button.dataset.action==='close-prop'){propView.history=null;propView.quoteId='';paintProps()}
 if(button.dataset.action==='recheck-prop')await checkProp(propView.quoteId,propView.playerMatch);
});
document.addEventListener('change',e=>{
 if(e.target.id==='prop-include-previous'){propView.includePrevious=e.target.checked;propView.data=null;propView.history=null;propHistoryRequest++;paintProps();loadGameProps()}
 if(e.target.id==='f-prop-category'){propView.category=e.target.value;paintProps()}
 if(e.target.id==='f-prop-book'){propView.book=e.target.value;paintProps()}
 if(e.target.id==='prop-last'){
   const n=Number(e.target.value);if(!Number.isInteger(n)||n<1||n>100)return notify('Choose 1 to 100 past games.',true);
   propView.last=n;checkProp(propView.quoteId,propView.playerMatch);
 }
 if(e.target.id==='f-prop-kind'){propView.kind=e.target.value;checkProp(propView.quoteId,propView.playerMatch)}
 if(e.target.id==='f-prop-match'&&e.target.value)checkProp(propView.quoteId,e.target.value);
});

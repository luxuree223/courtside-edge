/* Research preferences and optional screenshot evidence; no external account access. */
function needed(amount,comparison){return comparison==='over'?Math.floor(Number(amount))+1:Math.ceil(Number(amount))}
function safeSource(value){try{const u=new URL(value);return u.protocol==='https:'?u.href:'#'}catch{return '#'}}
function healthPanel(){
 const d=state.data||{};
 return card('Data Health',`<div class="stack">${['NBA','NFL'].map(sport=>`<div class="status-row"><div><strong>${sport} · ${d[sport]?.games_without_player_logs||0} saved final games missing player logs</strong><small>${(d[sport]?.seasons||[]).map(s=>`${s.season_type}: ${s.player_logs.toLocaleString()} player logs`).join(' · ')}</small></div></div>`).join('')}<p class="muted">${d.backup?.available?'Automatic backup saved before the database upgrade.':'A backup will be saved automatically before upgrading an existing database.'} Backups live in data/backups. Copy the whole data folder to include your saved Covers images.</p><p class="muted">Automatic updates: ${d.automatic_updates?.enabled?'enabled while this app is running':'off for this session'}. Last successful nightly update: ${esc(d.automatic_updates?.last_success||'not recorded yet')}. Failed nightly updates retry while the app remains open.</p></div>`);
}
function gameDay(game){
 if(game.starts_at.length===10)return game.starts_at;
 try{return new Intl.DateTimeFormat('en-CA',{timeZone:state.settings?.timezone||'America/Chicago',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(game.starts_at))}catch{return game.starts_at.slice(0,10)}
}
function todayGameDate(){return gameDay({starts_at:new Date().toISOString()})}
function selectableGameDates(sport=state.sport){
 const first=todayGameDate();
 return Array.from({length:sport==='NBA'?4:1},(_,offset)=>{const d=new Date(first+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+offset);return d.toISOString().slice(0,10)});
}
function scheduleOffset(date,offset){const d=new Date(date+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+offset);return d.toISOString().slice(0,10)}
function validScheduleDate(date){const dates=selectableGameDates();return /^\d{4}-\d{2}-\d{2}$/.test(date)&&!Number.isNaN(Date.parse(date+'T12:00:00Z'))&&date<=dates.at(-1)?date:dates[0]}
function setScheduleDate(date){state.scheduleDate=validScheduleDate(date);state.selectedGame=null;render();refreshLiveScores();}
function gameDateLabel(date){const dates=selectableGameDates('NBA');return date===dates[0]?'Today':date===dates[1]?'Tomorrow':day(date)}
const scheduleChecks=new Map();
async function loadSelectableGames(force=false){
 const sport=state.sport,dates=selectableGameDates(sport);
 const pending=dates.filter(date=>{const prior=scheduleChecks.get(sport+':'+date);return !prior||(!prior.running&&(force||Date.now()-prior.finished>=300000))});
 if(!pending.length)return;
 const note=document.getElementById('game-schedule-note');
 if(note)note.textContent='Checking available games…';
 pending.forEach(date=>scheduleChecks.set(sport+':'+date,{running:true}));
 const responses=await Promise.allSettled(pending.map(date=>req('/schedule/refresh?'+new URLSearchParams({sport,date}),{method:'POST'})));
 let failed=false;
 responses.forEach((result,index)=>{
   const date=pending[index],key=sport+':'+date;
   if(result.status==='fulfilled'){
     if(result.value.stale||result.value.error)failed=true;
     state.games[sport]=[...result.value.games,...(state.games[sport]||[]).filter(g=>gameDay(g)!==date)];
     scheduleChecks.set(key,{finished:Date.now(),failed:!!(result.value.stale||result.value.error)});
   }else{failed=true;scheduleChecks.delete(key)}
 });
 if(state.sport!==sport||todayGameDate()!==dates[0])return;
 const picker=document.getElementById('f-matchup');
 if(picker){
   picker.innerHTML=matchOptions().map(([value,label])=>`<option value="${esc(value)}">${esc(label)}</option>`).join('');
   picker.value=state.selectedGame&&dates.includes(gameDay(state.selectedGame))?state.selectedGame.id:'';
 }
 if(state.page==='matchups'||state.page==='rankings')render();
 const status=document.getElementById('game-schedule-note');
 if(status)status.textContent=failed?'Some schedules could not update. Showing saved games.':(state.games[sport]||[]).some(g=>dates.includes(gameDay(g)))?'':'No '+sport+' games scheduled '+(sport==='NFL'?'today.':'today or in the next 3 days.');
}
function storedStat(stat){try{return JSON.parse(localStorage.getItem('courtside-lines-'+state.sport)||'{}')[stat]}catch{return undefined}}
function rememberStat(stat,value){if(!Number.isFinite(value))return;try{const values=JSON.parse(localStorage.getItem('courtside-lines-'+state.sport)||'{}');values[stat]=value;localStorage.setItem('courtside-lines-'+state.sport,JSON.stringify(values))}catch{}}
function saveFinder(){try{localStorage.setItem('courtside-finder-'+state.sport,JSON.stringify(state.filters));rememberStat(state.filters.stat,state.filters.threshold)}catch{}}
function restoreFinder(sport){
 const stat=sport==='NBA'?'pts':'rec_yds';
 let saved={};try{saved=JSON.parse(localStorage.getItem('courtside-finder-'+sport)||'{}')}catch{}
 state.filters={stat,threshold:statDefaults[sport][stat],last:10,min_rate:50,max_rate:100,venue:'all',season_type:'regular',min_minutes:0,price:'',comparison:'at_least',opponent:'',season:'',before:'',...saved};
 if(!Object.hasOwn(statDefaults[sport],state.filters.stat)||(state.filters.stat==='targets'&&!state.filters.include_research)){state.filters.stat=stat;state.filters.threshold=statDefaults[sport][stat]}
}
async function refreshSchedule(){
 if(state.busy)return;
 state.scheduleDate=validScheduleDate($('#schedule-date')?.value||state.scheduleDate);
 await op('refresh-schedule',async()=>{
   const selected=state.sport,date=state.scheduleDate;
   const response=await req('/schedule/refresh?'+new URLSearchParams({sport:selected,date}),{method:'POST'});
   state.games[selected]=[...response.games,...state.games[selected].filter(g=>gameDay(g)!==date)];
   scheduleChecks.set(selected+':'+date,{finished:Date.now()});
   state.scheduleLoaded=true;
   notify(response.games.length?`${response.games.length} ${selected} games found for ${date}.`:'The source lists no games for this date.');
 });
}
async function loadSnapshots(){
 const game=state.selectedGame,sport=state.sport;
 state.snapshots=[];state.snapshotMessage='';state.coversOdds=null;state.coversMessage='';state.coversInput='';
 if(!game)return;
 try{const [snapshots,quotes]=await Promise.all([req('/covers/snapshots?'+new URLSearchParams({sport,game_id:game.id})),req('/covers/odds?'+new URLSearchParams({sport,game_id:game.id}))]);if(state.sport===sport&&state.selectedGame?.id===game.id){state.snapshots=snapshots;state.coversOdds=quotes}}
 catch(e){if(state.sport===sport&&state.selectedGame?.id===game.id)state.snapshotMessage=e.message}
}
function coversPricesPanel(){
 const d=state.coversOdds;
 const rows=d?.quotes||[];
 const groups=new Map();
 for(const q of rows){const key=JSON.stringify([q.market,q.selection,q.point]);const group=groups.get(key)||[];group.push(q);groups.set(key,group)}
 return `<h3>Covers.com game odds</h3><p class="muted">Your books: <strong>FanDuel · Caesars · DraftKings</strong>. Moneyline, spread and over/under. Each different line stays separate.</p>
 <button class="btn btn-primary" data-action="covers-prices">Get Covers Odds</button>
 ${state.coversMessage?`<p class="note-box" role="status">${esc(state.coversMessage)}</p>`:''}
 ${d?`<p class="muted">Observed ${new Date(d.observed_at).toLocaleString()} · ${esc(d.game_state)} · <a href="${esc(d.source_url)}" target="_blank" rel="noopener noreferrer">Covers odds page ↗</a></p>
 ${groups.size?`<div class="table-scroller"><table class="table"><thead><tr><th>EXACT SELECTION</th><th>FANDUEL</th><th>CAESARS</th><th>DRAFTKINGS</th></tr></thead><tbody>${[...groups.values()].map(group=>{const first=group[0],pay=q=>q.price>0?1+q.price/100:1+100/-q.price,best=Math.max(...group.map(pay));return `<tr><td>${esc(({h2h:'Moneyline',spreads:'Spread',totals:'Total'})[first.market])} · ${esc(first.selection)} ${first.point!==null?first.point:''}</td>${['FanDuel','Caesars','DraftKings'].map(book=>{const q=group.find(q=>q.book===book);return `<td>${q?odds(q.price)+(group.length>1&&pay(q)===best?'<small class="small green">Best shown price · check rules</small>':''):'Unavailable'}</td>`}).join('')}</tr>`}).join('')}</tbody></table></div>`:'<p class="note-box">Covers returned the game page, but no usable American-odds quotes for your three books. No prices were inferred from percentages or other books.</p>'}
 <small class="muted">${esc(d.note)}${d.missing_books?.length?' Missing books: '+esc(d.missing_books.join(', '))+'.':''}</small>`:'<p class="muted">No Covers odds saved for this game yet. The app tries to match it automatically; you can also paste its Covers link below.</p>'}`;
}
async function readCoversPrices(){
 if(!state.selectedGame)return;
 const source_url=$('#covers-url')?.value||state.coversOdds?.source_url?.replace(/\/odds$/,'')||'';
 state.coversInput=source_url;
 try{state.coversOdds=await req('/covers/odds/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sport:state.sport,game_id:state.selectedGame.id,source_url})});state.coversMessage=''}
 catch(e){state.coversMessage=e.message}
}
function snapshotContents(){
 const game=state.selectedGame;
 if(!game)return '';
 const sport=state.sport.toLowerCase(),kind=state.sport==='NBA'?'basketball':'football';
 return `<section class="card pad covers-panel"><div class="card-head"><div><div class="eyebrow">SELECTED GAME · ${esc(gameDay(game))}</div><h2>${esc(game.away)} @ ${esc(game.home)}</h2></div><span class="tag">${esc(game.season_type)}</span></div>
 ${coversPricesPanel()}<div class="divider"></div><h3>Covers.com snapshot</h3><p class="muted">Keep a picture of this game's matchup research. Screenshots are saved on this PC and can become out of date.</p>
 <div class="head-actions"><a class="btn" href="https://www.covers.com/sports/${sport}/matchups" target="_blank" rel="noopener noreferrer">Open Covers matchups ↗</a><a class="btn" href="https://www.covers.com/sport/${kind}/${sport}/league-trends" target="_blank" rel="noopener noreferrer">Covers team trends ↗</a></div>
 <div class="snapshot-form">${field('Covers matchup link (optional for odds — we try to find it)',`<input class="input" id="covers-url" type="url" placeholder="https://www.covers.com/sport/${kind}/${sport}/matchup/12345" value="${esc(state.coversInput||state.coversOdds?.source_url?.replace(/\/odds$/,'')||state.snapshots[0]?.source_url||'')}">`)}
 <div class="head-actions"><button class="btn btn-primary" data-action="capture-covers">Take Snapshot</button><small class="muted">Optional browser setup required once.</small></div>
 <details><summary>Or attach a screenshot you took yourself</summary><p class="muted">Open the game on Covers, take a screenshot, then choose it here. Uploaded images are labeled as supplied by you; the app does not verify their contents.</p>
 ${field('Screenshot (PNG, JPG, WebP — up to 12 MB)',`<input id="covers-file" class="input" type="file" accept="image/png,image/jpeg,image/webp">`)}
 ${field('What does it show? (optional)',`<input id="covers-note" class="input" maxlength="300" placeholder="Matchup overview, injuries, team trends…">`)}<button class="btn" data-action="upload-covers">Save Screenshot</button></details></div>
 ${state.snapshotMessage?`<p class="note-box" role="status">${esc(state.snapshotMessage)}</p>`:''}
 <label class="finder-line-option"><input type="checkbox" id="ai-auto-read" ${aiAutoRead?'checked':''}> Read new snapshots with AI (sends image to OpenAI; uses API credits)</label><p class="field-help">Or use Read Snapshot with AI on an image below. Connect your key in <button class="link-btn" data-page="ask">Ask Courtside</button>.</p><div class="snapshot-gallery">${state.snapshots.map(s=>`<figure><a href="${s.image_url}" target="_blank" rel="noopener"><img loading="lazy" src="${s.image_url}" alt="Covers snapshot for ${esc(game.away)} at ${esc(game.home)}"></a><figcaption><strong>${s.method==='automatic'?'Captured':'Uploaded · contents not verified'}</strong> ${new Date(s.captured_at).toLocaleString()}<br><a target="_blank" rel="noopener noreferrer" href="${esc(s.source_url)}">Open source page ↗</a>${s.note?`<p>${esc(s.note)}</p>`:''}<div class="head-actions"><a class="btn btn-small" target="_blank" rel="noopener noreferrer" href="${esc(s.source_url)}">Open Covers page ↗</a><button class="btn btn-small" data-action="read-snapshot-ai" data-snapshot-id="${esc(s.id)}">Read Snapshot with AI</button></div><div data-reading-id="${esc(s.id)}">${aiReadingPanel(s.analysis)}</div></figcaption></figure>`).join('')||'<p class="muted">No saved snapshot for this game yet.</p>'}</div>
 <small class="muted">A capture timestamp records when the image was saved, not when a sportsbook changed its price. Covers consensus is betting interest, not a projected win chance. Captures do not fill missing game logs or certify an edge.</small></section>`;
}
async function captureCovers(){
 if(!state.selectedGame)return;
 const source_url=$('#covers-url').value;
 state.coversInput=source_url;
 await op('capture-covers',async()=>{
   try{
     await req('/covers/capture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sport:state.sport,game_id:state.selectedGame.id,source_url})});
     await loadSnapshots();notify('Covers snapshot saved.');setTimeout(maybeReadNewSnapshot,0);
   }catch(e){state.snapshotMessage=e.message;throw e}
 });
}
async function uploadCovers(){
 if(!state.selectedGame)return;
 const file=$('#covers-file')?.files?.[0];
 if(!file){notify('Choose a screenshot first.',true);return}
 const form=new FormData();form.append('sport',state.sport);form.append('game_id',state.selectedGame.id);form.append('source_url',$('#covers-url').value);form.append('note',$('#covers-note').value);form.append('file',file);
 await op('upload-covers',async()=>{await req('/covers/upload',{method:'POST',body:form});await loadSnapshots();notify('Covers screenshot saved.');setTimeout(maybeReadNewSnapshot,0);});
}

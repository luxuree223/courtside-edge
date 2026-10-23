/* Optional AI features: server-held credentials; escaped output; no wager actions. */
let aiStatus=null,aiBusy=false,aiAutoRead=false,aiChat={NBA:[],NFL:[]},aiDraft='';
let aiContext={NBA:null,NFL:null},aiSessionGeneration=0;
try{const saved=JSON.parse(sessionStorage.getItem('courtside-chat-v1')||'null');if(saved){for(const sport of ['NBA','NFL']){aiChat[sport]=(saved.chat?.[sport]||[]).filter(m=>['user','assistant'].includes(m.role)&&typeof m.content==='string').slice(-20);aiContext[sport]=saved.context?.[sport]||null}aiDraft=typeof saved.draft==='string'?saved.draft:''}}catch{}
function saveAIChat(){try{sessionStorage.setItem('courtside-chat-v1',JSON.stringify({chat:aiChat,context:aiContext,draft:aiDraft}))}catch{}}
function aiComposer(followup=false){const game=aiContext[askSport]?.game||(state.selectedGame?.sport===askSport?state.selectedGame:null);return `<section class="card pad ai-chat ${followup?'ai-followup':''}" id="ai-composer">${followup?'<h2>Ask a follow-up</h2><p class="field-help">Keep going below. Courtside remembers this conversation.</p>':''}<div class="grid-2" style="align-items:end">${field('Sport hint',select('ask-sport',[['NBA','NBA'],['NFL','NFL']],askSport))}${field(followup?'Your follow-up':'Ask a question',`<textarea id="f-question" class="input" rows="3" maxlength="4000" placeholder="${followup?'What about his receiving yards instead?':'Find the best player props for Dallas'}">${esc(aiDraft)}</textarea>`)}</div>${game?`<p class="field-help">Game context: ${esc(game.away)} at ${esc(game.home)} · ${day(gameDay(game))}. Name another game or player to change topics.</p>`:''}<div class="head-actions" style="margin-top:16px"><button class="btn btn-primary" data-action="ask-ai" ${!aiStatus?.configured||aiBusy?'disabled':''}>${aiBusy?'Thinking…':followup?'Send Follow-up →':'Ask AI →'}</button><button class="btn" data-action="ask-courtside">Search the Stats Index (free)</button>${followup?'<button class="link-btn" data-action="ai-clear-chat">New conversation</button>':''}</div><p class="field-help">Search the Stats Index understands questions such as “Lakers players averaging 2 threes or more this season” and “76ers top scorer in the last 3 games.” It searches saved records without AI charges. This regular season by default. “Last 10” uses the newest 10 regular-season games, reaching into last season only if needed. Ask to include playoffs or preseason. Enter to send · Shift+Enter for a new line. Research can use connected data services and odds-feed credits. Sources and missing information appear in the answer.</p></section>`}
let aiRules=null,aiRulesDraft=null,aiRulesEnabled=true,aiRulesOpen=false;
function aiRulesPanel(){return `<details class="card pad" id="ai-research-rules" ${aiRulesOpen?'open':''}><summary>Research methodology · Master engine active</summary><p class="field-help">Your complete NBA/NFL master engine is applied by the server on every answer. Add your own research preferences here; they stay saved on this PC.</p><label for="ai-rules-text">Additional research instructions</label><textarea class="input" rows="6" maxlength="12000" id="ai-rules-text">${esc(aiRulesDraft??aiRules?.text??'')}</textarea><label class="field-help"><input type="checkbox" id="ai-rules-enabled" ${aiRulesEnabled?'checked':''}> Apply these additional instructions</label><div class="head-actions"><button class="btn btn-primary" data-action="ai-save-rules">Save Research Instructions</button><button class="btn" data-action="ai-starter-rules">Use Starter Preferences</button></div><p class="field-help">Master version ${esc(aiRules?.master_version||'loading…')}. Disabling additional instructions keeps the master engine active. Research answers and tool names are saved locally; chat history stays in this tab.</p></details>`}
try{aiAutoRead=localStorage.getItem('courtside-ai-auto-read')==='true'}catch{}
function aiConfigPanel(){
 const configured=aiStatus?.configured;
 if(aiStatus?.shared_managed)return `<details class="card pad ai-settings"><summary>AI connection · ${configured?'Ready for all accounts':'Temporarily unavailable'}</summary><p class="muted">${configured?'Courtside’s shared AI connection is ready. You can ask questions and read screenshots without adding an API key.':'The site owner needs to finish connecting AI on the server. Search the Stats Index is still available.'}</p><p class="field-help">Model: ${esc(aiStatus.model)}. The site owner covers API usage. The key stays on the server and cannot be viewed or changed from your account. Your chat and tracker stay in your own account.</p></details>`;
 return `<details class="card pad ai-settings" ${configured?'':'open'}><summary>AI connection · ${configured?'Configured':'Add your API key'}</summary><p class="muted">Use your OpenAI API key for chat and image reading. API usage has separate billing. <a href="https://developers.openai.com/api/docs/quickstart" target="_blank" rel="noopener noreferrer">Open API setup ↗</a>. Your key is stored encrypted for this Windows account and is never shown again.</p>
 <div class="grid-2">${field('OpenAI API key',`<input class="input" id="ai-key" type="password" autocomplete="off" placeholder="${configured?'Leave blank to keep saved key':'Paste API key here'}">`)}${field('OpenAI model',`<input class="input" id="ai-model" value="${esc(aiStatus?.model||'gpt-6-astra')}">`)}</div><button class="btn btn-primary" data-action="ai-connect" style="margin-top:16px">Save AI Connection</button><p class="field-help">Setup saves your key locally. Chat sends your question and relevant saved sports research. Read Snapshot sends that image to OpenAI. Bets, bankroll and API keys are excluded from the research context.</p></details>`;
}
function aiReadingPanel(analysis){
 if(!analysis)return '';
 const r=analysis.reading;
 const list=items=>items?.length?`<ul>${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'<p class="muted">None clearly visible.</p>';
 return `<div class="ai-reading"><div class="row-between"><strong>AI snapshot reading</strong><span class="tag">${esc(r.game_match==='matches'?'TEAMS & DATE READ':r.game_match==='different'?'GAME MISMATCH':'GAME / DATE UNCLEAR')}</span></div><p>${esc(r.summary)}</p>
 ${r.markets.length?`<div class="table-scroller"><table class="table"><thead><tr><th>BOOK</th><th>MARKET / SELECTION</th><th>LINE</th><th>ODDS</th></tr></thead><tbody>${r.markets.map(q=>`<tr><td>${esc(q.sportsbook)}</td><td>${esc(q.market)} · ${esc(q.selection)}<small class="small">Visible text: ${esc(q.visible_text)}</small></td><td>${esc(q.line)}</td><td>${esc(q.odds)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="muted">No readable sportsbook lines found in this image.</p>'}
 <details><summary>Injuries & trends</summary><h4>Injuries</h4>${list(r.injuries)}<h4>Trends</h4>${list(r.trends)}</details>
 ${r.unclear.length?`<div class="note-box"><strong>Check these details</strong>${list(r.unclear)}</div>`:''}
 <small class="muted">AI transcription · ${esc(analysis.model)} · Read ${new Date(analysis.read_at).toLocaleString()}. Image captured ${new Date(analysis.captured_at).toLocaleString()}. Check against the image and sportsbook; these are not verified live odds.</small></div>`;
}
async function getAIStatus(){try{const results=await Promise.all([req('/ai/status'),req('/ai/rules')]);aiStatus=results[0];aiRules=results[1];if(aiRulesDraft===null)aiRulesEnabled=aiRules.enabled;if(state.page==='ask')render()}catch{}}
async function saveAIConnection(){
 const key=$('#ai-key')?.value||'',model=$('#ai-model')?.value||'';
 try{aiStatus=await req('/ai/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key,model})});render();notify('AI connection saved. Your first request will check access to the model.')}catch(e){notify(e.message,true)}
}
async function readSnapshotAI(id,quiet=false){
 if(aiBusy)return;
 aiBusy=true;
 try{
   notify('Reading screenshot with AI…');
   const result=await req('/covers/snapshots/'+encodeURIComponent(id)+'/read',{method:'POST'});
   const snapshot=state.snapshots.find(s=>s.id===id);if(snapshot)snapshot.analysis=result;
   const panel=document.querySelector('[data-reading-id="'+id+'"]');if(panel)panel.innerHTML=aiReadingPanel(result);
   if(!quiet)notify('AI reading saved. Check unclear details against the image.');
 }catch(e){notify(e.message,true)}finally{aiBusy=false;const button=document.querySelector('[data-snapshot-id="'+id+'"]');if(button){button.disabled=false;button.textContent='Read Snapshot with AI'}}
}
async function maybeReadNewSnapshot(){if(!aiAutoRead)return;const snapshot=state.snapshots.find(s=>!s.analysis);if(snapshot)await readSnapshotAI(snapshot.id)}
async function askAI(){
 const question=$('#f-question')?.value.trim()||'';
 askSport=$('#f-ask-sport')?.value||askSport;
 if(question.length<3)return notify('Type a question first.',true);
 if(aiBusy)return;
 aiBusy=true;aiDraft=question;
 const generation=aiSessionGeneration,history=aiChat[askSport],sport=askSport,context=history.length?aiContext[sport]:null,requestSport=context?.sport||sport,game=context?.game||(state.selectedGame?.sport===requestSport?state.selectedGame:null);
 const button=document.querySelector('[data-action="ask-ai"]');if(button){button.disabled=true;button.textContent='Thinking…'}
 try{
   const response=await req('/ai/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,sport:requestSport,game_id:game?.id||'',history:history.slice(-8).map(({role,content})=>({role,content:content.slice(0,6000)}))})});
   if(generation!==aiSessionGeneration)return;
   aiChat[sport]=[...history,{role:'user',content:question},{role:'assistant',content:response.answer,model:response.model,research:response.context,researchId:response.research_id,master:response.rules_applied?.master_version,researchWindow:response.research_window}].slice(-20);aiContext[sport]={sport:response.sport||requestSport,game:response.matched_game||null};if(aiDraft===question)aiDraft='';saveAIChat();
 }catch(e){notify(e.message,true)}finally{aiBusy=false;if(state.page==='ask'){render();document.querySelector('.ai-conversation')?.lastElementChild?.scrollIntoView({block:'start',behavior:'smooth'})}}
}
document.addEventListener('click',async e=>{
 const button=e.target.closest('[data-action]');if(!button)return;
 if(button.dataset.action==='ai-connect')await saveAIConnection();
 if(button.dataset.action==='read-snapshot-ai'){if(aiBusy)return notify('An AI request is already running.',true);button.disabled=true;button.textContent='Reading…';await readSnapshotAI(button.dataset.snapshotId)}
 if(button.dataset.action==='ask-ai')await askAI();
 if(button.dataset.action==='ai-save-rules'){try{aiRulesDraft=$('#ai-rules-text').value;aiRules=await req('/ai/rules',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:aiRulesDraft,enabled:aiRulesEnabled})});notify('Research instructions saved. They apply to every new AI answer.')}catch(e){notify(e.message,true)}}
 if(button.dataset.action==='ai-starter-rules'){aiRulesDraft=aiRules?.starter||'';aiRulesOpen=true;render()}
 if(button.dataset.action==='ai-clear-chat'){if(aiBusy)return notify('Wait for this answer before starting a new conversation.',true);aiChat[askSport]=[];aiContext[askSport]=null;aiDraft='';saveAIChat();render()}
});
document.addEventListener('change',e=>{if(e.target.id==='ai-auto-read'){aiAutoRead=e.target.checked;try{localStorage.setItem('courtside-ai-auto-read',String(aiAutoRead))}catch{}}});

document.addEventListener('input',e=>{if(e.target.id==='f-question'){aiDraft=e.target.value;saveAIChat()}});
document.addEventListener('keydown',async e=>{if(e.target.id==='f-question'&&e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();await askAI()}});
document.addEventListener('input',e=>{if(e.target.id==='ai-rules-text')aiRulesDraft=e.target.value});
document.addEventListener('change',e=>{if(e.target.id==='ai-rules-enabled')aiRulesEnabled=e.target.checked});
document.addEventListener('toggle',e=>{if(e.target.id==='ai-research-rules')aiRulesOpen=e.target.open},true);
document.addEventListener('change',e=>{if(e.target.id==='f-ask-sport'){askSport=e.target.value;askResult=null;render()}});

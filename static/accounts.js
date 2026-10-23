const accountView={configured:false,user:null,mode:'login',busy:false};
function clearAccountResearch(){
 if(typeof gameResearch!=='undefined')Object.assign(gameResearch,{key:'',data:null,player:null,playerId:'',request:gameResearch.request+1,playerRequest:gameResearch.playerRequest+1,loading:false,playerLoading:false});
 if(typeof propView!=='undefined')Object.assign(propView,{key:'',data:null,history:null,quoteId:'',open:false});
 if(typeof gameOverviews!=='undefined')gameOverviews.clear();
 if(typeof entityView!=='undefined')Object.assign(entityView,{data:null,request:entityView.request+1,loading:false});
 if(typeof oddsSourcesView!=='undefined')oddsSourcesView=null;
 if(typeof oddsData!=='undefined')oddsData=null;
 if(typeof aiStatus!=='undefined')aiStatus=null;
 if(typeof jsonBackupView!=='undefined')Object.assign(jsonBackupView,{data:null,preview:null,busy:false});
}
function accountButton(){const b=document.querySelector('#account-action');if(b)b.textContent=accountView.user?`${accountView.user.name} · Sign out`:'Set up / Sign in'}
function signupUnitFields(value=''){return `<label for="account-unit">Your unit size ($)</label><input class="input" id="account-unit" type="number" inputmode="decimal" min="0.01" max="1000000" step="0.01" value="${esc(value)}" placeholder="Enter your amount" aria-describedby="unit-explainer" required><div class="note-box" id="unit-explainer"><strong>What is a unit?</strong><p>A unit is the dollar amount you use as your standard bet size. If you choose $5, then 1 unit (1u) is $5 and a 2-unit bet is $10. Choose your own amount; you can change it later in Settings.</p></div>`}
function showAccountForm(mode='login',message=''){
 accountView.mode=mode;document.querySelector('.app-shell').hidden=true;
 const setup=mode==='setup',register=mode==='register',host=document.querySelector('#account-screen');host.hidden=false;
 host.innerHTML=`<section class="card pad account-card"><div class="eyebrow">COURTSIDE EDGE</div><h1>${setup?'Protect your account':register?'Create your account':'Welcome back'}</h1><p>${setup?'Your existing bets and settings will stay with this owner account.':register?'Choose a username, password and unit size to get started. Your bets and money settings stay in your own account.':'Sign in to pick up where you left off.'}</p><form id="account-form" class="stack"><label for="account-name">Username</label><input class="input" id="account-name" autocomplete="username" required maxlength="60"><label for="account-password">Password</label><input class="input" id="account-password" type="password" autocomplete="${mode==='login'?'current-password':'new-password'}" required minlength="10" maxlength="256"><p class="field-help">Use at least 10 characters. Keep your password private.</p>${setup&&accountView.setup_code_required?'<label for="account-setup-code">Owner setup code</label><input class="input" id="account-setup-code" type="password" autocomplete="off" required>':''}${register||setup?signupUnitFields(setup?state.settings?.unit_size??'':''):''}<button class="btn btn-primary" type="submit">${setup?'Create owner account':register?'Create account & get started':'Sign in'}</button></form><p class="note-box" id="account-message" role="status">${esc(message||'Saved bets and settings stay with your account when you close the browser. Signing out also saves a personal backup.')}</p>${!setup?`<button class="link-btn" data-account-mode="${register?'login':'register'}">${register?'Already have an account? Sign in':'New here? Create an account'}</button>`:''}${!accountView.configured&&!accountView.setup_required?'<button class="link-btn" id="account-cancel">Back to this local app</button>':''}</section>`;
}
async function startCourtside(){restoreFinder(state.sport);if(accountView.user)await loginSyncGate();await load();state.gameWindowDate=todayGameDate();render();watchCollection();accountButton();document.querySelector('#account-screen').hidden=true;document.querySelector('.app-shell').hidden=false}
async function bootstrapAuth(){try{if(typeof bootstrapCloudAuth==='function'&&await bootstrapCloudAuth())return;Object.assign(accountView,await req('/auth/status'));accountButton();if(accountView.setup_required)showAccountForm("setup");else if(accountView.configured&&!accountView.user)showAccountForm('register');else await startCourtside()}catch(err){showAccountForm('login',err.message)}}
async function signOutWithBackup(){
 if(typeof cloudSession!=='undefined'&&cloudSession.enabled)return cloudSignOut();
 if(accountView.busy)return;accountView.busy=true;const button=document.querySelector('#account-action');if(button)button.textContent='Saving your backup…';
 try{
  const response=await fetch('/api/auth/logout',{method:'POST'});if(!response.ok){const d=await response.json();throw new Error(d.detail||'Backup failed. You are still signed in.')}
  const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=response.headers.get('Content-Disposition')?.match(/filename="?([^";]+)"?/)?.[1]||'Courtside_Backup.zip';a.textContent='Download your backup';a.className='btn btn-primary';
  try{sessionStorage.clear();for(const key of Object.keys(localStorage))if(key.startsWith('courtside-')&&!key.includes('theme'))localStorage.removeItem(key)}catch{}
  clearAccountResearch();accountView.user=null;Object.assign(state,{dashboard:null,settings:null,bets:[],data:null,results:null,snapshots:[],selectedGame:null,page:'dashboard'});document.querySelector('#main').innerHTML='';document.querySelector('#modal-root').innerHTML='';
  if(typeof aiSessionGeneration!=='undefined')aiSessionGeneration++;if(typeof aiChat!=='undefined'){aiChat.NBA=[];aiChat.NFL=[]}if(typeof aiContext!=='undefined'){aiContext.NBA=null;aiContext.NFL=null}if(typeof aiDraft!=='undefined')aiDraft='';
  showAccountForm('login','You’re signed out. A verified backup is saved. If your browser did not download it automatically, use the button below. Keep this personal file private.');document.querySelector('.account-card').appendChild(a);a.click();accountButton();
 }catch(err){notify(err.message,true);accountButton()}finally{accountView.busy=false}
}
function sharingPanel(){const cloud=typeof cloudSession!=='undefined'&&cloudSession.enabled;return `<section class="card pad"><h2>Your account</h2><p>${accountView.user?`Signed in as <strong>${esc(accountView.user.name)}</strong>. Your betting tracker, settings and keys belong to this account.`:'Set up your owner account before sharing access. Your existing data will remain yours.'}</p><div class="head-actions"><button class="btn" id="account-settings-action">${accountView.user?'Sign out & back up':'Set up sign-in'}</button></div>${typeof jsonBackupButtons==='function'?jsonBackupButtons():''}<p class="field-help">${cloud?'Bets, bankroll, unit size and timezone are saved in your Firebase account. Friends sign up with an email, password and unit size.':'Friends can open the hosted website and create their own account with a username, password and unit size.'} Everyone has a separate tracker. Keep your personal backup and data folder private.</p></section>`}
document.addEventListener('click',async e=>{
 if(e.target.closest('#account-action,#account-settings-action')){if(accountView.user)await signOutWithBackup();else showAccountForm(accountView.configured?'login':'setup')}
 const mode=e.target.closest('[data-account-mode]');if(mode)showAccountForm(mode.dataset.accountMode);
 if(e.target.closest('#account-cancel')){document.querySelector('#account-screen').hidden=true;document.querySelector('.app-shell').hidden=false}
});
document.addEventListener('submit',async e=>{
 if(e.target.id!=='account-form')return;e.preventDefault();if(accountView.busy)return;accountView.busy=true;
 try{const mode=accountView.mode,unit=Number(document.querySelector('#account-unit')?.value);if((mode==='register'||mode==='setup')&&(!Number.isFinite(unit)||unit<.01||unit>1000000||Math.abs(Math.round(unit*100)-unit*100)>1e-7))throw new Error('Enter your unit size in dollars and cents, such as 5 or 10.');const user=await req('/auth/'+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.querySelector('#account-name').value,password:document.querySelector('#account-password').value,...(mode==='register'||mode==='setup'?{unit_size:unit}:{}),setup_code:document.querySelector('#account-setup-code')?.value||''})});accountView.user=user;accountView.configured=true;sessionStorage.clear();location.reload()}
 catch(err){document.querySelector('#account-message').textContent=err.message}finally{accountView.busy=false}
});


let loginSyncRequest=0;
function paintLoginSync(status,message=''){
 const host=document.querySelector('#account-screen');host.hidden=false;document.querySelector('.app-shell').hidden=true;
 const done=status.completed_days||0,total=status.total_days||1,pct=Math.min(99,Math.round(done/total*100));
 host.innerHTML=`<section class="card pad account-card sync-gate"><div class="eyebrow">UPDATING YOUR RESEARCH</div><h1>Syncing NBA & NFL stats</h1><p role="status" aria-live="polite">${esc(message||status.message||'Connecting to ESPN…')}</p><progress max="100" value="${status.running===false&&!status.failed?100:pct}" aria-label="Season sync progress"></progress><p>${done} of ${status.total_days||0} game days checked · ${(status.player_logs||0).toLocaleString()} player logs downloaded</p><p class="field-help">The first sync rebuilds this season’s records. Later sign-ins check missing games and recent corrections. Your tracker remains saved separately.</p>${status.errors?.length?`<details><summary>${status.errors.length} source issues</summary>${status.errors.map(x=>`<p>${esc(x)}</p>`).join('')}</details>`:''}${status.running===false&&status.failed===true?'<button class="btn btn-primary" data-action="retry-login-sync">Retry sync</button><button class="btn" data-action="finish-login-sync">Open app with available stats</button>':''}<button class="link-btn" data-action="sync-signout">Sign out</button></section>`;
}
async function loginSyncGate(){
 ++loginSyncRequest;let status={running:true,message:'Starting this season’s sync…'};paintLoginSync(status);
 await new Promise(resolve=>{loginSyncResolve=resolve;});
}
let loginSyncResolve=null;
async function runLoginSync(){
 const generation=loginSyncRequest;
 try{
  let status=await req('/data/login-sync',{method:'POST'});
  while(generation===loginSyncRequest){paintLoginSync(status);if(!status.running){if(status.failed!==true&&status.outcome!=='failed'){if(status.errors?.length)notify('Sync finished. Some source records are unavailable; those gaps stay labeled.');if(typeof clearPositionCache==='function')clearPositionCache();loginSyncResolve?.();loginSyncResolve=null}return}await new Promise(r=>setTimeout(r,1200));status=await req('/data/collection-status')}
 }catch(error){if(generation===loginSyncRequest)paintLoginSync({running:false,failed:true,errors:[error.message]},'The stats update could not finish. Retry, or open the app with the records currently available.')}
}
const beginLoginSync=loginSyncGate;
loginSyncGate=async function(){const pending=beginLoginSync();runLoginSync();return pending};
document.addEventListener('click',e=>{const a=e.target.closest('[data-action]')?.dataset.action;if(a==='retry-login-sync')runLoginSync();if(a==='finish-login-sync'){loginSyncResolve?.();loginSyncResolve=null}if(a==='sync-signout'){loginSyncRequest++;signOutWithBackup()}});

let oddsSourcesView=null;
function oddsSourcesPanel(){return `<section class="card pad"><h2>Odds sources</h2><p>Choose the provider to use when refreshing player props. ESPN remains the source for game results and player stats.</p><div class="form-grid">${field('Provider',select('odds-source',[['theoddsapi','The Odds API'],['sportsgameodds','SportsGameOdds']],oddsSourcesView?.selected||'theoddsapi'))}${field('API key',`<input class="input" id="odds-source-key" type="password" autocomplete="off" placeholder="Paste a key, or leave blank to keep the saved key">`)}</div><p class="field-help">Keys stay in your account on this server and are excluded from JSON backups and shareable project ZIPs. Provider coverage and request limits apply.</p><button class="btn btn-primary" data-action="save-odds-source">Save odds source</button><p>${(oddsSourcesView?.providers||[]).map(p=>esc(p.name)+': '+(p.connected?'Connected':'No key saved')).join(' · ')}</p></section>`}
document.addEventListener('click',async e=>{if(e.target.closest('[data-action="save-odds-source"]')){try{oddsSourcesView=await req('/odds/sources',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:document.querySelector('#f-odds-source').value,key:document.querySelector('#odds-source-key').value})});render();notify('Odds provider saved. Refresh a game’s props to check available prices.')}catch(error){notify(error.message,true)}}});

/* Optional Firebase email/password sign-in. No password is stored in the browser. */
const cloudSession={enabled:false,config:null,tokens:null,busy:false,mode:'register'};
function cloudStore(tokens){cloudSession.tokens=tokens;try{if(tokens)sessionStorage.setItem('courtside-cloud-auth',JSON.stringify(tokens));else sessionStorage.removeItem('courtside-cloud-auth')}catch{}}
async function cloudSetCookie(){const r=await fetch('/api/cloud/session',{method:'POST',headers:{Authorization:'Bearer '+cloudSession.tokens.idToken}});if(!r.ok)throw new Error('Cloud sign-in could not be established. Retry signing in.')}
async function cloudIdentity(action,body){
 const r=await fetch('https://identitytoolkit.googleapis.com/v1/accounts:'+action+'?'+new URLSearchParams({key:cloudSession.config.apiKey}),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),d=await r.json();
 if(!r.ok){const code=d.error?.message||'';throw new Error(code.includes('EMAIL_EXISTS')?'That email already has an account. Sign in instead.':code.includes('INVALID_LOGIN_CREDENTIALS')||code.includes('EMAIL_NOT_FOUND')||code.includes('INVALID_PASSWORD')?'The email or password is incorrect.':code.includes('WEAK_PASSWORD')?'Use a stronger password with at least 10 characters.':code.includes('INVALID_EMAIL')?'Enter a valid email address.':'Cloud sign-in failed. Check the connection and Firebase email/password setup.')}
 return d;
}
async function cloudHeaders(){
 const v=cloudSession;if(!v.enabled||!v.tokens)return {};
 if(Date.now()>=v.tokens.expiresAt-60000){
  const r=await fetch('https://securetoken.googleapis.com/v1/token?'+new URLSearchParams({key:v.config.apiKey}),{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'refresh_token',refresh_token:v.tokens.refreshToken})}),d=await r.json();
  if(!r.ok){cloudStore(null);showCloudForm('login','Your sign-in expired. Sign in again.');throw new Error('Sign in again to continue.')}
  cloudStore({idToken:d.id_token,refreshToken:d.refresh_token,expiresAt:Date.now()+Number(d.expires_in)*1000});
  await cloudSetCookie();
 }
 return {Authorization:'Bearer '+v.tokens.idToken};
}
function showCloudForm(mode='register',message=''){
 const onboarding=mode==='onboard',register=mode==='register';cloudSession.mode=mode;document.querySelector('.app-shell').hidden=true;const host=document.querySelector('#account-screen');host.hidden=false;
 host.innerHTML=`<section class="card pad account-card"><div class="eyebrow">COURTSIDE EDGE · CLOUD ACCOUNT</div><h1>${onboarding?'Choose your unit size':register?'Create your account':'Welcome back'}</h1><p>Your saved bets and money settings belong to your account. They are available when you sign in from another device.</p><form id="cloud-account-form" class="stack">${onboarding?'':`<label for="cloud-email">Email</label><input class="input" id="cloud-email" type="email" autocomplete="username" required><label for="cloud-password">Password</label><input class="input" id="cloud-password" type="password" minlength="10" maxlength="256" autocomplete="${register?'new-password':'current-password'}" required>`}${register||onboarding?signupUnitFields():''}<button class="btn btn-primary" type="submit">${onboarding?'Finish setup':register?'Create account & get started':'Sign in'}</button></form><p id="cloud-account-message" role="status">${esc(message)}</p>${onboarding?'':`<button class="link-btn" data-cloud-mode="${register?'login':'register'}">${register?'Already have an account? Sign in':'New here? Create an account'}</button>`}</section>`;
}
async function bootstrapCloudAuth(){
 const d=await req('/cloud/config');if(!d.enabled)return false;Object.assign(cloudSession,{enabled:true,config:d.firebase});
 try{cloudSession.tokens=JSON.parse(sessionStorage.getItem('courtside-cloud-auth')||'null')}catch{}
 if(!cloudSession.tokens){showCloudForm();return true}
 try{await cloudHeaders();await cloudSetCookie();const status=await req('/auth/status');Object.assign(accountView,status);if(status.onboarding_required)showCloudForm('onboard');else await startCourtside()}catch(err){showCloudForm('login',err.message)}return true;
}
async function cloudSignOut(){
 if(cloudSession.busy)return;cloudSession.busy=true;
 try{
  const download=await saveJSONBackup();const result=await fetch('/api/cloud/signout',{method:'POST'});if(!result.ok)throw new Error('Sign-out could not be confirmed. Retry.');cloudStore(null);sessionStorage.clear();accountView.user=null;state.dashboard=null;state.bets=[];state.settings=null;state.snapshots=[];state.selectedGame=null;state.page='dashboard';document.querySelector('#main').innerHTML='';document.querySelector('#modal-root').innerHTML='';
  if(typeof aiSessionGeneration!=='undefined')aiSessionGeneration++;if(typeof aiChat!=='undefined')aiChat={NBA:[],NFL:[]};if(typeof aiContext!=='undefined')aiContext={NBA:null,NFL:null};if(typeof aiDraft!=='undefined')aiDraft='';
  showCloudForm('login','You’re signed out. Keep your JSON backup private. If it did not download, use the link below.');document.querySelector('.account-card').appendChild(download);accountButton();
 }catch(err){notify(err.message,true)}finally{cloudSession.busy=false}
}
document.addEventListener('click',e=>{const mode=e.target.closest('[data-cloud-mode]');if(mode&&!cloudSession.busy)showCloudForm(mode.dataset.cloudMode)});
document.addEventListener('submit',async e=>{
 if(e.target.id!=='cloud-account-form')return;e.preventDefault();if(cloudSession.busy)return;cloudSession.busy=true;
 try{
  const mode=cloudSession.mode,unit=Number(document.querySelector('#account-unit')?.value);
  if(mode!=='login'&&(!Number.isFinite(unit)||unit<.01||unit>1e6||Math.abs(Math.round(unit*100)-unit*100)>1e-7))throw new Error('Enter your unit size in dollars and cents.');
  if(mode!=='onboard'){
   const result=await cloudIdentity(mode==='register'?'signUp':'signInWithPassword',{email:document.querySelector('#cloud-email').value.trim(),password:document.querySelector('#cloud-password').value,returnSecureToken:true});
   cloudStore({idToken:result.idToken,refreshToken:result.refreshToken,expiresAt:Date.now()+Number(result.expiresIn)*1000});
   await cloudSetCookie();
  }
  const status=await req('/auth/status');Object.assign(accountView,status);
  if(status.onboarding_required){if(mode==='login'){showCloudForm('onboard');return}await req('/cloud/onboard',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({unit_size:unit})})}
  const tokens=cloudSession.tokens;sessionStorage.clear();cloudStore(tokens);location.reload();
 }catch(err){document.querySelector('#cloud-account-message').textContent=err.message}finally{cloudSession.busy=false}
});

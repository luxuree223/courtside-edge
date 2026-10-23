/* Homepage money editor. Balance corrections never become wager profits. */
let moneyEditorSaving=false,moneyEditorReturnFocus=null;
function homeMoneyDialog(){
 const s=state.dashboard.summary;
 moneyEditorReturnFocus=document.activeElement;
 document.querySelector('#modal-root').innerHTML=`<div class="modal-backdrop" id="money-backdrop"><section class="modal money-editor" role="dialog" aria-modal="true" aria-labelledby="money-editor-title"><div class="row-between"><h2 id="money-editor-title">Edit your betting money</h2><button class="btn btn-small" type="button" data-action="close-money" aria-label="Close money editor">✕</button></div><form id="home-money-form" class="stack">
 <div class="field"><label for="home-starting-money">Starting amount ($)</label><input class="input" id="home-starting-money" name="starting_bankroll" type="number" inputmode="decimal" min="0" max="1000000000000" step="0.01" required value="${esc(Number(s.starting_bankroll).toFixed(2))}"><small class="field-help">The amount you began tracking with. Changing it updates the current amount below.</small></div>
 <div class="field"><label for="home-current-money">Current betting money ($)</label><input class="input" id="home-current-money" name="current_bankroll" type="number" inputmode="decimal" min="0" max="1000000000000" step="0.01" required value="${esc(Number(s.bankroll).toFixed(2))}"><small class="field-help">The total you have now, including money tied up in pending bets. Edit this to correct your balance or account for money added or withdrawn.</small></div>
 <div class="field"><label for="home-unit-size">Your unit size ($)</label><input class="input" id="home-unit-size" name="unit_size" type="number" inputmode="decimal" min="0.01" max="1000000" step="0.01" required value="${esc(Number(s.unit).toFixed(2))}"><small class="field-help">Your standard bet amount: a $5 unit means 1u = $5.</small></div>
 <p class="note-box">Your saved bets and their wins or losses stay the same. A current-balance correction is saved separately from betting profit.</p><p id="home-money-error" role="alert"></p><div class="modal-actions"><button class="btn" type="button" data-action="close-money">Cancel</button><button class="btn btn-primary" type="submit">Save amounts</button></div></form></section></div>`;
 document.querySelector('#home-starting-money')?.focus();
}
function closeHomeMoney(){if(moneyEditorSaving)return;document.querySelector('#modal-root').innerHTML='';moneyEditorReturnFocus?.focus?.()}
function updateHomeMoneyPreview(){
 const input=document.querySelector('#home-starting-money'),current=document.querySelector('#home-current-money');
 if(!input||!current||input.value==='')return;
 const s=state.dashboard.summary;
 current.value=(Math.round((Number(input.value)+Number(s.profit)+Number(s.bankroll_adjustment||0))*100)/100).toFixed(2);
}
async function saveHomeMoney(form){
 if(moneyEditorSaving)return;
 const data={timezone:state.settings?.timezone||'America/Chicago'};
 for(const key of ['starting_bankroll','current_bankroll','unit_size']){
  const raw=form.elements.namedItem(key).value,value=Number(raw);
  if(String(raw).trim()===''||!Number.isFinite(value)||value<(key==='unit_size'?0.01:0)||value>(key==='unit_size'?1e6:1e12)||Math.abs(value*100-Math.round(value*100))>1e-5)throw new Error('Enter valid dollar amounts with no more than two decimal places.');
  data[key]=value;
 }
 moneyEditorSaving=true;
 const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
 try{
  await req('/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  document.querySelector('#modal-root').innerHTML='';
  try{await refresh();notify('Your betting money and starting amount are saved.')}catch{notify('Your amounts were saved, but the page could not refresh. Reload to see them.',true)}
  document.querySelector('[data-action="edit-home-money"]')?.focus();
 }finally{moneyEditorSaving=false;buttons.forEach(b=>b.disabled=false)}
}
document.addEventListener('click',e=>{const action=e.target.closest('[data-action]')?.dataset.action;if(action==='edit-home-money')homeMoneyDialog();if(action==='close-money'||e.target.id==='money-backdrop')closeHomeMoney()});
document.addEventListener('input',e=>{if(e.target.id==='home-starting-money')updateHomeMoneyPreview()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.querySelector('#home-money-form'))closeHomeMoney()});
document.addEventListener('submit',async e=>{if(e.target.id!=='home-money-form')return;e.preventDefault();try{await saveHomeMoney(e.target)}catch(error){const box=document.querySelector('#home-money-error');if(box)box.textContent=error.message;else notify(error.message,true)}});

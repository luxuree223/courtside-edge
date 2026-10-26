/* Browser/Android Back follows research screens. No account or key data is stored. */
const researchNavigation=(()=>{
 const storageKey='courtside-navigation-v1',entries=new Map();
 let active='',route='',restoring=false,ready=false;
 const copy=value=>JSON.parse(JSON.stringify(value));
 const stateKeys=['page','sport','scheduleDate','selectedGame','matchup','customTeams','finderMode','filters','results','resultSort','expanded'];
 function context(){return {state:Object.fromEntries(stateKeys.map(k=>[k,copy(state[k]??null)])),entity:copy(entityView),logs:copy(logView),player:copy(gameResearch),scroll:window.scrollY||0};}
 function routeKey(){return JSON.stringify([state.page,state.sport,
  ['matchups','consistency','nfl','game-log-box'].includes(state.page)?state.selectedGame?.id:'',
  ['consistency','nfl'].includes(state.page)?state.finderMode:'',
  state.page==='search'?entityView.query:'',state.page==='logs'?[logView.mode,logView.leaderWindow,logView.query]:'',
  ['consistency','nfl'].includes(state.page)&&gameResearch.key===state.sport+':'+state.selectedGame?.id?gameResearch.playerId:'']);}
 function persist(){try{const recent=[...entries].slice(-10);let size=0;const bounded=[];for(const entry of recent.reverse()){const text=JSON.stringify(entry);if(size+text.length>1500000)continue;size+=text.length;bounded.unshift(entry);}sessionStorage.setItem(storageKey,JSON.stringify(bounded));}catch{}}
 function save(){if(!active)return;entries.set(active,context());persist();}
 function cancelRequests(){entityView.request++;logView.request++;logView.leaderRequest++;gameResearch.request++;gameResearch.playerRequest++;if(typeof finderRequest!=='undefined')finderRequest++;}
 function restore(value){
  cancelRequests();Object.assign(state,copy(value.state));state.finderLoading=false;
  for(const [target,saved] of [[entityView,value.entity],[logView,value.logs],[gameResearch,value.player]]){
   const counters=Object.fromEntries(Object.entries(target).filter(([k])=>/request$/i.test(k)));
   Object.assign(target,copy(saved),counters);
   for(const key of Object.keys(target))if(/loading$/i.test(key))target[key]=false;
  }
 }
 function loadStored(){try{for(const [id,value] of JSON.parse(sessionStorage.getItem(storageKey)||'[]'))entries.set(id,value);}catch{}}
 function track(){
  if(restoring)return;
  const next=routeKey();
  if(!ready){ready=true;loadStored();const prior=history.state;if(prior?.courtsideNavigation&&entries.has(prior.id)){active=prior.id;restore(entries.get(active));route=routeKey();return;}}
  if(!active||next!==route){
   // The old entry already contains its last rendered view. Only its scroll
   // comes from the old DOM at this point, since actions have changed state.
   if(active&&entries.has(active))entries.get(active).scroll=window.scrollY||0;
   active=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,9);route=next;
   const data={courtsideNavigation:true,id:active};
   if(!history.state?.courtsideNavigation)history.replaceState(data,'',location.href);
   else history.pushState(data,'',location.href);
  }
 }
 const draw=render;
 render=function(){track();const result=draw.apply(this,arguments);if(!restoring)save();return result;};
 window.addEventListener('popstate',event=>{
  const id=event.state?.courtsideNavigation?event.state.id:'';const value=entries.get(id);if(!value)return;
  restoring=true;active=id;restore(value);route=routeKey();
  try{render();}finally{restoring=false;}
  requestAnimationFrame(()=>window.scrollTo({top:value.scroll||0,behavior:'instant'}));
  // Completed responses live in the snapshot. Resume only interrupted loads.
  if(state.page==='search'&&!entityView.data&&entityView.query)runEntitySearch();
  if(state.page==='logs'&&logView.mode==='players'&&!logView.data&&logView.query)searchGameLogs();
  if(state.page==='game-log-box')loadBoxScore();
  if(['consistency','nfl'].includes(state.page)&&gameResearch.playerId&&!gameResearch.player)openGamePlayer(gameResearch.playerId,false);
 });
 window.addEventListener('pagehide',save);
 window.addEventListener('scroll',()=>{if(active&&entries.has(active))entries.get(active).scroll=window.scrollY||0;},{passive:true});
 return {checkpoint(){track();save();},save,routeKey};
})();

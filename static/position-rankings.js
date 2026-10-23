/* Position defense uses opponent box scores, independently of ESPN team totals. */
const positionView={period:'season',sport:'',position:'TE',stat:'rec_td',data:null,key:'',loading:false,error:'',request:0,sort:'average',dir:-1};
function positionChoices(sport){return sport==='NFL'?['QB','RB','FB','WR','TE']:['PG','SG','SF','PF','C']}
function positionKey(){return [rankSport,rankSeason,rankType,positionView.position,positionView.stat,'full',positionView.period].join(':')}
function positionRows(){return [...(positionView.data?.rows||[])].sort((a,b)=>{const k=positionView.sort;if(k==='name')return a.name.localeCompare(b.name)*positionView.dir;if(a[k]===null)return b[k]===null?0:1;if(b[k]===null)return -1;return (a[k]-b[k])*positionView.dir||a.name.localeCompare(b.name)})}
async function loadPositionRanks(){
 const v=positionView;if(!rankSeason)return;
 if(v.sport!==rankSport||!positionChoices(rankSport).includes(v.position)){v.sport=rankSport;v.position=rankSport==='NFL'?'TE':'PG';v.stat=rankSport==='NFL'?'rec_td':'pts'}
 const key=positionKey(),request=++v.request;v.key=key;v.data=null;v.loading=true;v.error='';if(['rankings','value'].includes(state.page))render();
 try{const data=await req('/rankings/positions'+'/full'+'?'+new URLSearchParams({sport:rankSport,season:rankSeason,season_type:rankType,position:v.position,stat:v.stat,period:v.period}));if(request===v.request&&key===positionKey())v.data=data}
 catch(err){if(request===v.request)v.error=err.message}
 finally{if(request===v.request){v.loading=false;if(['rankings','value'].includes(state.page))render()}}
}
document.addEventListener('change',e=>{if(e.target.id==='f-position-period'){positionView.period=e.target.value;loadPositionRanks()}if(e.target.id==='f-position-filter'){positionView.position=e.target.value;loadPositionRanks()}if(e.target.id==='f-position-stat'){positionView.stat=e.target.value;loadPositionRanks()}});
document.addEventListener('click',e=>{const el=e.target.closest('[data-action]');if(!el)return;if(el.dataset.action==='position-jump')document.querySelector('#position-defense')?.scrollIntoView({block:'start',behavior:'smooth'});if(el.dataset.action==='position-refresh')loadPositionRanks();if(el.dataset.action==='position-sort'){const v=positionView;v.dir=v.sort===el.dataset.key?-v.dir:el.dataset.key==='name'?1:-1;v.sort=el.dataset.key;render()}});

function positionPeriodSelect(){return field('Games to include',select('position-period',[['season','Selected season'],['days5','Last 5 days'],['days14','Last 14 days'],['games28','Last 28 games per team']],positionView.period))}
function defensePositionPage(){return pageHead('OPPONENT RESEARCH','Defense vs Position','See what each team allows to players at a specific position.')+`<section class="card pad"><div class="ranking-filters defense-season-controls"><div class="select-tabs">${['NBA','NFL'].map(s=>`<button data-action="rank-sport" data-sport="${s}" class="${s===rankSport?'active':''}">${s}</button>`).join('')}</div>${field('Stats season',select('rank-season',(rankConfig?.seasons?.[rankSport]||[]).map(s=>[s.value,s.label]),rankSeason))}${field('Game type',select('rank-type',[['regular','Regular season'],['postseason','Playoffs']],rankType))}</div></section><div id="position-defense">${positionRankPanel()}</div>`}

/* Pure, stable prop sorting: odds by payout; absent histories always last. */
(function(root){
 const number=v=>v===null||v===undefined||!Number.isFinite(Number(v))?null:Number(v);
 const decimal=v=>{v=number(v);return v===null||!v?null:v>0?1+v/100:1+100/-v};
 function value(q,key){
  if(key==='odds')return decimal(q.price);
  if(key==='last5'||key==='last10')return number(q.recent?.[key]?.rate);
  if(key==='time'){const t=Date.parse(q.provider_updated_at||q.observed_at);return Number.isFinite(t)?t:null}
  return String(q[key]||'').toLocaleLowerCase();
 }
 function sort(rows,key='player',direction='asc'){
  const sign=direction==='desc'?-1:1;
  return [...rows].sort((a,b)=>{
   if(key==='prop'){const label=(a.stat||'').localeCompare(b.stat||'')||(a.side||'').localeCompare(b.side||'');return sign*(label||Number(a.line)-Number(b.line))||(a.player||'').localeCompare(b.player||'')}
   const x=value(a,key),y=value(b,key);
   if(x===null||y===null){if(x!==y)return x===null?1:-1}
   const difference=typeof x==='number'&&typeof y==='number'?x-y:String(x??'').localeCompare(String(y??''));
   return sign*difference||(a.player||'').localeCompare(b.player||'')||(a.id||'').localeCompare(b.id||'');
  });
 }
 root.propSort={sort,decimal};if(typeof module!=='undefined')module.exports=root.propSort;
})(typeof window!=='undefined'?window:globalThis);

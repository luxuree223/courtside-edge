/* Small escaped Markdown renderer. Raw HTML and unsafe link protocols stay text. */
(function(root){
 const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function inline(s){
  const tokens=[];
  s=String(s).replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/gi,(all,label,url)=>{
   try{const u=new URL(url);if(!['http:','https:'].includes(u.protocol)||u.username||u.password)return all}catch{return all}
   const index=tokens.push(`<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(label)}</a>`)-1;return '\u0000'+index+'\u0000';
  });
  return escape(s).replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>').replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/\u0000(\d+)\u0000/g,(_,i)=>tokens[+i]||'');
 }
 function render(text){
  const lines=String(text).slice(0,60000).split(/\r?\n/),out=[];let list=false;
  const close=()=>{if(list){out.push('</ul>');list=false}};
  for(let i=0;i<lines.length;i++){
   let line=lines[i];if(!line.trim()){close();continue}
   if(/^\s*\|.*\|\s*$/.test(line)&&/^\s*\|[\s:|\-]+\|\s*$/.test(lines[i+1]||'')){
    close();const cells=v=>v.trim().slice(1,-1).split('|').map(x=>inline(x.trim()));
    out.push('<div class="table-scroller"><table class="table"><thead><tr>'+cells(line).map(x=>'<th>'+x+'</th>').join('')+'</tr></thead><tbody>');i++;
    while(/^\s*\|.*\|\s*$/.test(lines[i+1]||'')){i++;out.push('<tr>'+cells(lines[i]).map(x=>'<td>'+x+'</td>').join('')+'</tr>')}
    out.push('</tbody></table></div>');continue;
   }
   const heading=line.match(/^#{1,6}\s+(.+)/);if(heading){close();out.push('<h3>'+inline(heading[1])+'</h3>');continue}
   const item=line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)/);if(item){if(!list){out.push('<ul>');list=true}out.push('<li>'+inline(item[1])+'</li>');continue}
   close();out.push('<p>'+inline(line)+'</p>');
  }close();return out.join('');
 }
 root.aiMarkdown=render;if(typeof module!=='undefined')module.exports={render,inline};
})(typeof window!=='undefined'?window:globalThis);

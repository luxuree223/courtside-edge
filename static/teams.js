/* Local ESPN artwork; text remains readable if an image is unavailable. */
function teamLogo(sport,code){
 const aliases={NBA:{GSW:'GS',NYK:'NY',NOP:'NO',SAS:'SA',UTA:'UTAH',WAS:'WSH'},NFL:{LA:'LAR',JAC:'JAX',WSH:'WAS'}};
 const league=String(sport||'').toUpperCase(),raw=String(code||'').trim().toUpperCase(),team=aliases[league]?.[raw]||raw;
 if(!['NBA','NFL'].includes(league)||!/^[A-Z]{2,4}$/.test(team))return '';
 return `<span class="team-logo" aria-hidden="true"><img src="/static/teams/${league.toLowerCase()}/${team.toLowerCase()}.png" alt="" width="40" height="40" loading="lazy" decoding="async"></span>`;
}
document.addEventListener('error',e=>{if(e.target.matches?.('.team-logo img'))e.target.parentElement.classList.add('logo-unavailable')},true);

/* Extra research screens for Courtside Edge. This works with locally saved verified data. */
const BOOK_MARKETS=[['h2h','Moneyline'],['spreads','Spread'],['totals','Total Points'],['player_points','Points'],['player_rebounds','Rebounds'],['player_assists','Assists'],['player_receptions','Receptions'],['player_receiving_yards','Receiving Yards']];
function bookMarketsFor(sport){return BOOK_MARKETS.filter(([key])=>['h2h','spreads','totals'].includes(key)||(sport==='NBA'?['player_points','player_rebounds','player_assists'].includes(key):['player_receptions','player_receiving_yards'].includes(key)))}
function lastChosenLeague(){try{return localStorage.getItem('courtside-last-league')==='NFL'?'NFL':'NBA'}catch{return 'NBA'}}
let researchSport=lastChosenLeague(),researchMarket='h2h',trendSport='NFL',trendTeam='',trendLast=10,trendVenue='all',trendData=null,oddsData=null,oddsStatus=null,askResult=null,askSport=lastChosenLeague();
function researchText(s){return esc(String(s||''))}
function bestPricesPanel(){const prices=(oddsData?.results||[]).filter(x=>x.market===researchMarket&&x.game_status!=='final');return card('Best Prices Found',prices.length?`<div class="table-scroller"><table class="table"><thead><tr><th>GAME / SELECTION</th><th>MARKET</th><th>BEST BOOK</th><th>BEST ODDS</th><th>BOOKS CHECKED</th><th>PRICE CHECK</th></tr></thead><tbody>${prices.map(x=>`<tr><td><strong>${researchText(x.selection)}</strong><small class="small">${researchText(x.away)} @ ${researchText(x.home)} · ${researchText(x.game_date)}</small><small class="small ${x.game_status==='live'?'yellow':''}">${x.game_status==='live'?'LIVE GAME · SAVED PRICE':x.game_status==='scheduled'?'UPCOMING GAME':'GAME STATUS UNVERIFIED'}</small></td><td>${researchText(marketLabel(x.market))}${x.point!==''&&x.point!==null&&x.point!==undefined?' '+researchText(x.market==='spreads'?signedLine(x.point):x.point):''}</td><td>${researchText(x.best_book)}</td><td><strong class="green">${odds(x.best_price)}</strong></td><td><details><summary style="cursor:pointer;color:var(--accent)">${x.other_books} books ▾</summary><div style="padding-top:8px">${x.books.map(b=>`<div style="margin:3px 0;white-space:nowrap">${researchText(b.book)}: ${odds(b.price)}</div>`).join('')}</div></details></td><td>${x.value_type==='possible_value'?`<span class="tag win">POSSIBLE PRICE EDGE +${x.market_edge_pct}%</span><small class="small">Based on ${x.reference_books} other books, not a prediction</small>`:x.value_type==='no_clear_value'?`<span class="tag">No clear edge</span>`:`<span class="tag pending">Best price only</span>`}<small class="small">Retrieved ${localTime(x.updated_at)}${x.provider_updated_at?' · Book updated '+localTime(x.provider_updated_at):' · Book update time unavailable'}</small></td></tr>`).join('')}</tbody></table></div>`:empt('No active saved prices for these filters','Finished games are excluded. Refresh prices to check your selected market. NFL shows today; NBA shows today plus the next three days.'),`<span class="tag">${prices.length} OPTIONS</span>`);}
function findValuePage(){const r=oddsData||{results:[]},connected=oddsStatus?.connected;
 let prices=(r.results||[]).filter(x=>x.market===researchMarket);
 return pageHead('CHECK SPORTSBOOKS','Find Value','Compare the prices from different sportsbooks. See the best price first, then decide if the bet is worth researching.')
 +`<section class="card pad"><p class="note-box">For Covers.com moneyline, spreads and over/under, <button class="link-btn" data-page="matchups">pick a game →</button>. Its saved quotes appear below that selected game.</p><div class="card-head"><h2>FanDuel · Caesars · DraftKings</h2><span class="tag">SAVED ODDS · ${researchSport}</span></div>
 <div class="grid-2" style="margin:0 0 14px">${field('Which sport?',select('value-sport',[['NBA','NBA'],['NFL','NFL']],researchSport))}${field('What prices?',select('value-market',BOOK_MARKETS.filter(x=>['h2h','spreads','totals'].includes(x[0])),researchMarket))}</div>
 <div class="head-actions"><button class="btn btn-primary" data-action="scan-value">⌕ Find Value / Compare Books</button><button class="btn" data-action="show-saved-odds">See Saved Prices</button></div>
 <div class="note-box" style="margin-top:15px">Free sportsbook data usually covers <strong>moneyline odds</strong> for NBA and NFL. Available markets and request limits depend on your plan. Player props may need a paid feed; you can also enter quotes yourself. Prices can change at any moment. Finished games are excluded; live games are labeled. Score/status checks do not use odds-feed credits.</div></section>
 <section class="card pad" style="margin:18px 0"><div class="card-head"><h2>Connect Your Odds Source</h2><span class="tag ${connected?'win':'pending'}">${connected?'CONNECTED':'NOT CONNECTED'}</span></div>
 <p class="muted" style="font-size:12px;line-height:1.7">To search real books automatically, get a free key from <a target="_blank" rel="noopener" href="https://the-odds-api.com/">TheOddsAPI</a> and paste it here once. Your key stays on this computer; it is not shown on screen after saving.</p>
 <div class="head-actions" style="margin-top:12px;align-items:stretch"><input type="password" autocomplete="off" id="free-odds-key" class="input" style="max-width:400px" placeholder="Paste your free odds key"><button class="btn" data-action="save-odds-key">Connect</button></div>
 <small class="muted">No key? You can still save lines from your sportsbook below and compare them. No odds are invented.</small></section>
 <div id="best-prices-host">${bestPricesPanel()}</div>
 <section class="card pad" style="margin-top:18px"><div class="card-head"><h2>Add a Sportsbook Price Yourself</h2><span class="tag">OPTIONAL</span></div><p class="muted" style="font-size:12px;line-height:1.6">Useful for FanDuel player props when the free odds feed doesn't include them. Add the same bet from another book to compare payouts.</p>
 <div class="form-grid" style="margin-top:17px">
 ${field('Sport',select('manual-sport',[['NBA','NBA'],['NFL','NFL']],researchSport))}
 ${field('Game date',`<input class="input" type="date" id="m-date" value="${today()}">`)}
 ${field('Home team',`<input class="input" id="m-home" placeholder="Cleveland Cavaliers">`)}
 ${field('Away team',`<input class="input" id="m-away" placeholder="Los Angeles Lakers">`)}
 ${field('Bet type',select('manual-market',bookMarketsFor(researchSport),'h2h'))}
 ${field('Which player or team?',`<input class="input" id="m-selection" placeholder="Cleveland Cavaliers">`)}
 ${field('Number on the line (if any)',`<input class="input" id="m-point" type="number" step="0.5" placeholder="25.5">`)}
 ${field('Sportsbook',`<select class="input" id="m-book"><option>FanDuel</option><option>Caesars</option><option>DraftKings</option></select>`)}
 ${field('Odds',`<input class="input" id="m-price" type="number" placeholder="-110">`)}
 </div><button class="btn btn-primary" style="margin-top:16px" data-action="save-manual-odds">Save This Price</button></section>
 <div class="note-box" style="margin-top:15px">A <strong>better price</strong> is not automatically a good bet. We only show a possible market advantage when at least two other sportsbooks have both sides of the moneyline available. The model is a rough market comparison, not a guarantee.</div>`;
}
function marketLabel(v){return ({h2h:'Moneyline',spreads:'Spread',totals:'Total Points',player_points:'Points',player_rebounds:'Rebounds',player_assists:'Assists',player_receptions:'Receptions',player_receiving_yards:'Receiving Yards'})[v]||v}
function trendPage(){const t=trendData;
 const opts=[['','Choose a team'],...[...new Set((state.games[trendSport]||[]).flatMap(g=>[g.home_abbr,g.away_abbr]))].sort().map(x=>[x,x])];
 const finalGames=(state.games[trendSport]||[]).filter(g=>g.status==='final'&&g.season_type==='regular');
 return pageHead('TEAM BETTING RESEARCH','Team Trends','See how often a team wins, covers the spread, or goes over the total. Only games with saved betting lines count for spread and over/under records.')
 +`<section class="card pad"><div class="card-head"><h2>Pick a Team</h2><span class="tag">REGULAR SEASON</span></div><div class="form-grid">
 ${field('Sport',select('trend-sport',[['NFL','NFL'],['NBA','NBA']],trendSport))}
 ${field('Team',select('trend-team',opts,trendTeam))}
 ${field('How many past games?',`<input class="input" type="number" min="1" max="100" step="1" value="${trendLast}" id="f-trend-last">`)}
 ${field('Home or away?',select('trend-venue',[['all','All games'],['home','Home only'],['away','Away only']],trendVenue))}
 </div><button class="btn btn-primary" style="margin-top:17px" data-action="check-team">Show Team Trends</button></section>
 ${t?`<div class="grid-4" style="margin-top:16px">${statCard('GAME RECORD',t.wins+'–'+t.losses,t.games+' games checked')}${statCard('SPREAD RECORD',t.ats_with_lines?`${t.ats_wins}–${t.ats_losses}–${t.ats_pushes}`:'No spread data',`${t.ats_with_lines} of ${t.games} games have saved spreads`)}${statCard('OVER / UNDER',t.totals_with_lines?`${t.over} over / ${t.under} under`:'No total data',`${t.totals_with_lines} games with a saved total`)}${statCard('AVERAGE SCORE',t.points_for===null?'—':t.points_for+'–'+t.points_against,'Past regular-season games')}</div>
 ${card('Game by Game',t.details.length?`<div class="table-scroller"><table class="table"><thead><tr><th>DATE</th><th>OPPONENT</th><th>SCORE</th><th>SPREAD</th><th>COVERED?</th><th>OVER / UNDER</th></tr></thead><tbody>${t.details.map(g=>`<tr><td>${researchText(g.date)}</td><td>${g.home?'vs':'@'} ${researchText(g.opponent)}</td><td>${researchText(g.score)}</td><td>${g.spread===null?'Not saved':g.spread>0?'+'+g.spread:g.spread}</td><td>${g.ats===null?'Unknown':g.ats==='W'?'<span class="green">YES</span>':g.ats==='P'?'PUSH':'NO'}</td><td>${g.total_result||'Unknown'}</td></tr>`).join('')}</tbody></table></div>`:empt('No games saved','Update regular-season game results first.'))}
 ${t.sport==='NBA'?`<div class="note-box" style="margin-top:15px"><strong>Estimated pace:</strong> ${t.estimated_possessions===null?'Not enough team stats saved to calculate it.':t.estimated_possessions+' possessions per game (from '+t.pace_games+' saved games)'} · This is an estimate, not NBA.com adjusted pace.</div>`:''}<div class="note-box" style="margin-top:15px">${t.ats_with_lines===0?'No spreads are saved yet, so we cannot calculate this team’s against-the-spread record.':'Spread records only use games with an actual saved spread.'} Showing ${t.games} completed games. We never count missing spreads as wins or losses.</div>`:''}
 <section class="card pad" style="margin-top:20px"><div class="card-head"><h2>Add a Past Game’s Betting Line</h2><span class="tag">OPTIONAL</span></div><p class="muted" style="font-size:12px;line-height:1.6">The game results tell us who won. To know if a team <strong>covered the spread</strong>, we also need the sportsbook spread from before the game. If you have one, save it here.</p>
 ${field('Which game?',select('line-game',[['','Choose a finished game'],...finalGames.map(g=>[g.id,`${g.away_abbr} @ ${g.home_abbr} · ${day(g.starts_at)}`])],''),'wide')}
 <div class="grid-2" style="margin-top:12px">${field('Home team spread (example: -4.5)',`<input id="f-line-spread" type="number" step="0.5" class="input" placeholder="-4.5">`)}${field('Total points line (example: 225.5)',`<input id="f-line-total" type="number" step="0.5" class="input" placeholder="225.5">`)}</div>
 <button class="btn" data-action="save-past-line" style="margin-top:14px">Save Game Line</button></section>`;
}
function askPage(){const q=askResult,history=aiChat[askSport]||[];
 return pageHead('YOUR RESEARCH HELPER','Ask Courtside','Talk through matchups, team rankings, player stats and saved Covers readings.')
 +aiConfigPanel()+aiRulesPanel()+(history.length?'':aiComposer())+`
 ${history.length?`<section class="card pad ai-conversation">${history.map(m=>`<article class="ai-message ${m.role}"><strong>${m.role==='user'?'You':'Courtside AI'}</strong>${m.model?`<small class="muted"> · ${esc(m.model)}</small>`:''}${m.researchWindow?`<p class="field-help">Research window: ${esc(m.researchWindow.description)}</p>`:''}<div class="ai-answer">${m.role==='assistant'?aiMarkdown(m.content):`<p>${esc(m.content).replace(/\n/g,'<br>')}</p>`}</div>${m.research?`<details><summary>Research checked · ${m.research.length} tool calls</summary><ul>${m.research.map(t=>`<li>${esc(t.tool.replace(/_/g,' '))}${t.ok?'':' · unavailable'}</li>`).join('')}</ul><small class="muted">Saved research #${esc(m.researchId)} · Master ${esc(m.master)}</small></details>`:''}</article>`).join('')}</section>`:''}
 ${history.length?aiComposer(true):''}${q?card('Saved Stats Search',`<p class="research-answer">${researchText(q.answer).replace(/\n/g,'<br>')}</p>`):''}`;
}
async function researchLoad(){try{[oddsStatus,oddsData]=await Promise.all([req('/odds/status'),req('/odds/compare?'+new URLSearchParams({sport:researchSport,books:'FanDuel,Caesars,DraftKings'}))]);render()}catch(e){notify(e.message,true)}}
async function scanOdds(){let market=$('#f-value-market')?.value||'h2h';researchMarket=market;researchSport=$('#f-value-sport')?.value||researchSport;try{
 const r=await req('/odds/refresh?'+new URLSearchParams({sport:researchSport,market}),{method:'POST'});oddsData=await req('/odds/compare?'+new URLSearchParams({sport:researchSport,books:'FanDuel,Caesars,DraftKings'}));oddsStatus=await req('/odds/status');render();notify(`${r.saved} sportsbook prices saved from ${r.events} games.`);
 }catch(e){notify(e.message,true)}}
async function saveOddsKey(){try{let key=$('#free-odds-key')?.value||'';oddsStatus=await req('/odds/key',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key})});render();notify('Odds source connected. Press Find Value to check participating books.')}catch(e){notify(e.message,true)}}
async function manualOdds(){try{const sport=$('#f-manual-sport')?.value||researchSport;
 const body={sport,game_date:$('#m-date').value,home:$('#m-home').value,away:$('#m-away').value,market:$('#f-manual-market').value,
 selection:$('#m-selection').value,book:$('#m-book').value,price:Number($('#m-price').value),point:$('#m-point').value===''?null:Number($('#m-point').value)};
 await req('/odds/manual',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});researchSport=sport;oddsData=await req('/odds/compare?sport='+sport+'&books=FanDuel,Caesars,DraftKings');render();notify('Sportsbook price saved and compared.');
 }catch(e){notify(e.message,true)}}
async function checkTeam(){try{trendSport=$('#f-trend-sport')?.value||trendSport;trendTeam=$('#f-trend-team')?.value||'';trendLast=Number($('#f-trend-last')?.value||10);trendVenue=$('#f-trend-venue')?.value||'all';if(!trendTeam)throw new Error('Choose a team first');trendData=await req('/teams/trends?'+new URLSearchParams({sport:trendSport,team:trendTeam,last:trendLast,venue:trendVenue}));render()}catch(e){notify(e.message,true)}}
async function savePastLine(){try{const game=$('#f-line-game')?.value;if(!game)throw new Error('Choose a finished game');const s=$('#f-line-spread').value,t=$('#f-line-total').value;
 if(!s&&!t)throw new Error('Enter the spread or total from before the game');await req('/teams/line',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sport:trendSport,game_id:game,home_spread:s===''?null:Number(s),total_line:t===''?null:Number(t)})});await checkTeam();notify('Past game line saved.')}catch(e){notify(e.message,true)}}
async function askCourtside(){const text=$('#f-question')?.value||'';askSport=$('#f-ask-sport')?.value||askSport;if(text.length<3)return notify('Type a question first',true);
 try{const answer=await req('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:text,sport:askSport})});askResult=answer;render();notify('Searched saved research and odds.')}catch(e){notify(e.message,true)}}
document.addEventListener('click',async e=>{
 const el=e.target.closest('[data-action]');if(!el)return;
 switch(el.dataset.action){
 case 'scan-value':await scanOdds();break;
 case 'show-saved-odds':researchSport=$('#f-value-sport')?.value||researchSport;researchMarket=$('#f-value-market')?.value||researchMarket;try{oddsData=await req('/odds/compare?sport='+researchSport+'&books=FanDuel,Caesars,DraftKings');render()}catch(e){notify(e.message,true)}break;
 case 'save-odds-key':await saveOddsKey();break;
 case 'save-manual-odds':await manualOdds();break;
 case 'check-team':await checkTeam();break;
 case 'save-past-line':await savePastLine();break;
 case 'ask-courtside':await askCourtside();break;
 case 'ask-example':$('#f-question').value=el.dataset.text;if(el.dataset.text.includes('receiving')){$('#f-ask-sport').value='NFL'}break;
 }
});
document.addEventListener('change',async e=>{
 if(e.target.id==='f-trend-sport'){trendSport=e.target.value;trendTeam='';trendData=null;render()}
 if(e.target.id==='f-value-market'){researchMarket=e.target.value;render()}
 if(e.target.id==='f-value-sport'){researchSport=e.target.value;oddsData=await req('/odds/compare?sport='+researchSport+'&books=FanDuel,Caesars,DraftKings');render()}
});

document.addEventListener('change',e=>{if(e.target.id==='f-manual-sport'){const picker=$('#f-manual-market');picker.innerHTML=bookMarketsFor(e.target.value).map(([key,label])=>`<option value="${key}">${esc(label)}</option>`).join('')}});

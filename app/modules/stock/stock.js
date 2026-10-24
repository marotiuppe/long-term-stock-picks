/* One stock: call, plan, price history, forecast, official close and news. Symbol comes from ?symbol=TCS. */
cur=(new URLSearchParams(location.search).get('symbol')||'').trim().toUpperCase();
$('app').classList.add('stk');
const parentOf=s=>s&&s.exchange=='BSE'?['bse','/bse.html','BSE stocks']:s&&s.etf?['etfs','/etfs.html','ETFs']:['stocks','/stocks.html','NSE stocks'];
const backLink=p=>`<a class="back" href="${p[1]}">${ic('arrow-left','sm')}${p[2]}</a>`;
function stockPage(){const sym=cur,s=D.stocks.find(x=>x.symbol==sym),par=parentOf(s);open=s?sym:null;
 Shell.setActive(par[0],true);Shell.setBack(par[1]);Shell.setTitle(sym||'Stock');document.title=(sym||'Stock')+' | Long-Term Stock Picks';
 if(!s){$('app').innerHTML=backLink(par)+`<section class="card"><div class="card-b">${empty('inbox',(sym?esc(sym):'No symbol')+' not found','This symbol is not in the latest scan. It may be misspelt, thinly traded, too new, or listed only on BSE. Try the NSE stocks list and search by name.','<a class="btn" href="/stocks.html">Go to NSE stocks</a>')}</div></section>`;return}
 const p=s.forecast[hz],h=hname(hz);
 const head=ph(`${esc(s.symbol)}${s.etf?' <span class="etf">ETF</span>':''}${s.exchange=='BSE'?' <span class="etf">BSE</span>':''}`,esc(s.name||''),`<button class="btn pri" type="button" id="addh">${ic('plus','sm')}${window.Mine&&Mine.pos[sym]?'Add more shares':'Add to my holdings'}</button><span id="share-host"></span>`,TABS);
 const kp='<div class="kpis">'
  +kpi('wallet','Price','₹'+f(s.price),'as of '+dt(s.asof))
  +kpi('circle-check','<span data-term="call">Call</span>',`<span class="vd ${s.verdict}">${VL[s.verdict]}</span>`,`setup score ${s.score}`)
  +kpi('trending-up',`<span data-term="typical">Typical</span> over ${h}`,`${pc(p.p50)}`,`${arrow(p.p50)} ${f(p.pgain*100,0)}% chance of gain`)
  +kpi('triangle-alert','<span data-term="stop-loss">Stop-loss</span>','₹'+f(s.stop),`${f(s.stopPct*100,0)}% below the price`)+'</div>';
 const X=DET[sym];let body;
 if(!X){body='<div class="card"><div class="card-b"><div class="load"><i></i>Loading chart…</div></div></div>';fetchDet(sym)}
 else if(!X.series)body=`<div class="card"><div class="card-b">${empty('triangle-alert','Chart data could not be loaded','Chart and plan data could not be loaded for this stock. Try again later.')}</div></div>`;
 else body=null;
 const o=(n,h)=>`<div class="sc-i" style="--o:${n}">${h}</div>`,D_=body===null?detailParts(M(sym)):null;
 const sizing=`<section class="card" aria-label="Position sizing"><div class="card-h"><div><h2>Position sizing</h2></div></div>${SET}</section>`;
 const main=D_?o(2,D_.price)+o(3,D_.fc)+o(5,D_.hor)+o(11,'<section id="calc-host" aria-label="What if calculator"></section>')+o(13,'<section id="notes-host" aria-label="Your notes"></section>')
  :o(2,body)+o(11,'<section id="calc-host" aria-label="What if calculator"></section>')+o(13,'<section id="notes-host" aria-label="Your notes"></section>');
 const side=(D_?o(1,D_.plan):'')+o(4,'<section class="card" id="mypos" aria-label="My position"></section>')+o(6,'<section id="why-host" aria-label="About this stock, from the data"></section>')
  +(D_?o(7,D_.off)+o(8,D_.why)+o(9,D_.news):'')+o(10,sizing)+o(12,'<section id="pa-host" aria-label="Price alerts"></section>');
 /* Wide screens: charts and forecast on the left; the plan, your position and the reasons on the right. Narrow: one column, plan first. */
 $('app').innerHTML=backLink(par)+head+kp+`<div class="stk-cols dtl"><div class="sc-main">${main}</div><div class="sc-side">${side}</div></div>`;
 bindSet();tabs();
 if(window.Holdings){const reload=()=>{const b=$('addh');if(b)b.lastChild.textContent=Mine.pos[sym]?'Add more shares':'Add to my holdings'};
  $('addh').onclick=()=>Holdings.openLotForm({symbol:sym,name:s.name,price:s.price,side:'buy',onSaved:()=>{Holdings.mountPosition($('mypos'),sym,s.name,s.price,reload).then(reload)}});
  Holdings.mountPosition($('mypos'),sym,s.name,s.price,reload).then(()=>{if(window.PriceChart)document.querySelectorAll('.pc[data-sym]').forEach(PriceChart.redraw);window.refreshForecastChart&&refreshForecastChart()})}
 mountChart();mountExtras(s)}
/* Feature modules (why.js, calc.js, ...) each expose window.<Name>.mount(host, symbol, {stock, horizon}). A broken module must not break the page. */
function mountExtras(s){[['Why','why-host'],['Share','share-host'],['Calc','calc-host'],['PriceAlerts','pa-host'],['Notes','notes-host']].forEach(([k,id])=>{
  const h=$(id);if(h&&window[k]&&window[k].mount){try{window[k].mount(h,s.symbol,{stock:s,horizon:hz})}catch(e){console.error(k,e)}}})}
startPage({
 boot(){$('app').innerHTML=(cur?`<h1>${esc(cur)}</h1>`:'')+SK},
 build(){},
 update:stockPage
});

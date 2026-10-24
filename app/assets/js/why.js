/* "Why this stock was picked": renders the /api/why payload (all numbers are computed server side by why.py) into #why-host.
   Why.mount(host, symbol, {stock, horizon}) is idempotent: the payload is cached per symbol and the newest host is always the one drawn into.
   Why.line(stock) is pure (price facts from scan fields only) and is used by the list rows. Describes the past, never predicts. */
(function(root){
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const num=v=>typeof v=='number'&&isFinite(v);
/* One line from the scan row: where the price sits against its 52-week high and 20-day average, and RSI. No network. */
function line(s){
 if(!s||!num(s.price)||s.price<=0)return '';
 const o=[];
 if(num(s.hi52)&&s.hi52>0){const d=(1-s.price/s.hi52)*100;o.push(d<0.5?'At its 52-week high':d.toFixed(0)+'% below 52-week high')}
 if(num(s.sma20)&&s.sma20>0){const g=(s.price/s.sma20-1)*100;o.push(Math.abs(g)<0.5?'At 20-day avg':Math.abs(g).toFixed(0)+'% '+(g>0?'above':'below')+' 20-day avg')}
 if(num(s.rsi))o.push('RSI '+Math.round(s.rsi));
 return o.join(' · ')}
const ic=(n,z)=>root.Shell&&Shell.icon?Shell.icon(n,z||'sm'):'';
const gl=(k,l)=>root.Glossary&&k?Glossary.term(k,l):esc(l);
const dtf=s=>{try{return new Date(s+'T00:00:00').toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'})}catch(e){return s}};
const chip=st=>`<span class="why-chip k-${esc(st.key)}">${ic(st.icon)}<span>${esc(st.label)}</span></span>`;
const row=r=>`<div class="why-r${r.na?' na':''}"><dt>${gl(r.term,r.label)}</dt><dd><span class="v">${esc(r.value)}</span>${r.note?`<small>${esc(r.note)}</small>`:''}</dd></div>`;
const card=c=>`<article class="why-c" aria-labelledby="wc-${esc(c.id)}"><header><span class="why-i">${ic(c.icon,'')}</span><h3 id="wc-${esc(c.id)}">${esc(c.title)}</h3>${chip(c.status)}</header>
 <p class="why-h">${esc(c.headline)}</p>${c.rows.length?`<dl>${c.rows.map(row).join('')}</dl>`:''}${c.note?`<p class="why-n">${esc(c.note)}</p>`:''}<p class="why-s">Source: ${esc(c.source)}</p></article>`;
const risk=r=>`<li>${ic(r.icon)}<div><b>${esc(r.title)}</b><span>${esc(r.text)}</span></div></li>`;
function skeleton(){return '<section class="card why" aria-busy="true"><div class="card-h"><div><h2>About this stock, from the data</h2></div></div><div class="card-b"><div class="why-sk"><div class="sk"></div><div class="sk"></div><div class="why-g"><div class="sk tall"></div><div class="sk tall"></div><div class="sk tall"></div></div></div></div></section>'}
function failed(msg){return `<section class="card why"><div class="card-h"><div><h2>About this stock, from the data</h2></div></div><div class="card-b"><div class="why-err" role="alert">${ic('triangle-alert')}<span>${esc(msg)}</span><button class="btn" type="button" data-why-retry>${ic('refresh-cw')}Try again</button></div></div></section>`}
function view(d){
 const c=d.cards||[],risks=d.risks||[];
 const srcs=(d.sources||[]).map(s=>`<li>${esc(s.label)}, ${s.asof?(/^\d{4}-\d\d-\d\d$/.test(s.asof)?(s.stale?'last fetched ':'as of ')+esc(dtf(s.asof)):esc(s.asof)):'date not available'}</li>`).join('');
 return `<section class="card why" aria-labelledby="why-t"><div class="card-h"><div><h2 id="why-t">${d.verdict=='BUY'?'Why this stock is on the Buy list':'About this stock, from the data'}</h2><p>What the data shows and what could go wrong, from the figures this app has. It describes the past.</p></div></div>
 <div class="card-b"><p class="why-sum">${esc(d.summary)}</p>
 ${d.priceError?`<p class="why-note">${ic('info')}<span>${esc(d.priceError)} Price-based cards are limited.</span></p>`:''}
 ${d.etf?`<p class="why-note">${ic('info')}<span>This is an ETF or fund. It has no company results, so only the price-based cards are shown.</span></p>`:''}
 <p class="why-now${d.whyNow&&d.whyNow.fired?' on':''}">${ic('clock')}<span><b>Why now?</b> ${esc(d.whyNow?d.whyNow.text:'')}</span></p>
 <h3 class="why-sec">What the data shows</h3><div class="why-g">${c.map(card).join('')}</div>
 <section class="why-risks" aria-labelledby="why-rk"><h3 class="why-sec" id="why-rk">What could go wrong</h3>
  ${risks.length?`<ul class="why-rl">${risks.map(risk).join('')}</ul>`:`<p class="why-none">${ic('info')}<span>${esc(d.noRisks||'No flags from the data we have, which is limited.')}</span></p>`}
  <dl class="why-nas">${(d.risksNa||[]).map(r=>`<div class="why-r na"><dt>${esc(r.label)}</dt><dd><span class="v">${esc(r.value)}</span><small>${esc(r.note)}</small></dd></div>`).join('')}</dl>
  ${(d.limits||[]).length?`<ul class="why-lim">${d.limits.map(l=>`<li>${esc(l)}</li>`).join('')}</ul>`:''}</section>
 <footer class="why-f"><b>Sources</b><ul>${srcs}</ul><p>${esc(d.disclaimer||'For research and education. Not investment advice.')} The scan signal has no proven predictive edge.</p></footer></div></section>`}
const CACHE={},HOSTS={};
function draw(sym){const h=HOSTS[sym],C=CACHE[sym];if(!h||!C||!h.isConnected)return;
 h.innerHTML=C.state=='ok'?view(C.data):C.state=='err'?failed(C.msg):skeleton();
 h.onclick=e=>{if(e.target.closest('[data-why-retry]')){delete CACHE[sym];mount(h,sym)}};
 if(root.Glossary&&Glossary.enhance)try{Glossary.enhance(h)}catch(e){}}
function load(sym){const C=CACHE[sym]={state:'load'};
 fetch('/api/why?sym='+encodeURIComponent(sym)).then(r=>r.json().then(j=>({ok:r.ok,j})).catch(()=>({ok:false,j:{}}))).then(({ok,j})=>{
  if(CACHE[sym]!==C)return;
  if(ok&&j&&j.cards){C.state='ok';C.data=j}else{C.state='err';C.msg=(j&&j.error)||'The explanation could not be loaded.'}draw(sym)})
 .catch(()=>{if(CACHE[sym]!==C)return;C.state='err';C.msg='The explanation could not be loaded. Check the connection.';draw(sym)})}
function mount(host,sym){if(!host||!sym)return;HOSTS[sym]=host;if(!CACHE[sym])load(sym);draw(sym)}
const api={mount,line,_t:{line,view}};
root.Why=api;if(typeof module!='undefined'&&module.exports)module.exports=api;
})(typeof window!='undefined'?window:globalThis);

/* Settings: which alert rules are on and their thresholds, targets and review levels per stock, notifications, your data. */
const RULE_GROUPS=[['Consider adding',['add_drop','add_pe','add_weight']],['Consider reviewing or trimming',['trim_conc','trim_gain_val','trim_fund','trim_loss','review_level']],['Information',['info_results','info_dividend','info_corp']]];
const RULE_FIELDS={add_drop:[['pct','Fire when the price is at least','% below your average buy price',1,90]],
 add_pe:[['margin','Fire when the P/E is at least','% below its own average',1,90]],
 add_weight:[['tol','Fire when the share is more than','points under the target weight',0.5,50]],
 trim_conc:[['pct','Fire when one stock is at least','% of your portfolio',5,95]],
 trim_gain_val:[['gain','Fire when the gain is at least','% on your average buy price',5,1000],['premium','and the P/E is at least','% above its own average',5,500]],
 trim_loss:[['below_avg','Fire when below the 200-day average and at least','% under your average buy price',1,90]],
 info_dividend:[['days','Show for','days after the ex-dividend date',1,365]],
 info_corp:[['days','Show for','days after a split or bonus',1,365]]};
const NOTES={trim_fund:'Compares the last three quarters and the same quarter a year earlier, so a normal seasonal dip is not flagged. No threshold to set.',
 review_level:'Uses the review level you set for each stock below. Nothing fires for a stock without one.',
 info_results:'Shown for 30 days after a newer quarter appears in the data. Nothing is shown the first time a stock is checked.',
 add_weight:'Uses the target weight you set for each stock below. Nothing fires for a stock without one.',
 add_pe:'Needs four recent quarters of EPS and at least three fiscal years of EPS and prices. Without them the rule is skipped and says why.'};
let RULES=null,DEFS=null,META=null,STOCKS={},HELD=[];
const hint=(t)=>t?`<p class="rl-n">${esc(t)}</p>`:'';

function ruleRow(k){const m=META[k],r=RULES[k],fs=RULE_FIELDS[k]||[];
 return `<li class="rl" data-r="${k}"><div class="rl-h"><div class="rl-t"><b>${esc(m.title)}</b><span>${esc(m.text)}</span></div>
  <button type="button" class="tglb" role="switch" aria-checked="${r.on}" aria-label="${esc(m.title)}: ${r.on?'on':'off'}" data-on="${k}"><span class="tgl"></span></button></div>
  ${fs.length?`<div class="rl-f">${fs.map(f=>`<label class="rl-i"><span>${f[1]}</span><input type="number" inputmode="decimal" step="any" min="${f[3]}" max="${f[4]}" value="${r[f[0]]}" data-k="${k}" data-f="${f[0]}" aria-label="${esc(m.title)}: ${f[1]} ${f[2]}"><span>${f[2]}</span></label>`).join('')}</div>`:''}
  ${hint(NOTES[k])}<p class="rl-e" role="alert" id="re-${k}"></p></li>`}

function drawRules(){const el=$('rules');
 el.innerHTML=RULE_GROUPS.map(g=>`<h3 class="rl-g">${g[0]}</h3><ul class="rll">${g[1].map(ruleRow).join('')}</ul>`).join('');
 el.querySelectorAll('[data-on]').forEach(b=>b.onclick=()=>save(b.dataset.on,'on',!RULES[b.dataset.on].on));
 el.querySelectorAll('input[data-k]').forEach(i=>i.onchange=()=>save(i.dataset.k,i.dataset.f,i.value))}

function save(rule,field,value){const prev=JSON.stringify(RULES),next=JSON.parse(prev);
 next[rule][field]=field=='on'?value:Number(value);
 const e=$('re-'+rule);if(e)e.textContent='';
 return Holdings.api('PUT','/api/rules',{rules:next}).then(r=>{RULES=r.rules;drawRules();Holdings.say('Saved');if(window.Attention)Attention.load(true).catch(()=>{})})
  .catch(err=>{const el=$('re-'+rule);if(el)el.textContent=err.message;drawRules();const e2=$('re-'+rule);if(e2)e2.textContent=err.message})}

function stocksHtml(){
 if(!HELD.length)return `<div class="empty"><div class="ico">${ic('briefcase')}</div><b>No holdings yet</b><span>Targets, review levels and sector labels appear here for the stocks you hold.</span><a class="btn pri" href="/portfolio.html">${ic('plus','sm')}Add a holding</a></div>`;
 return `<ul class="sts">${HELD.map(h=>{const s=STOCKS[h.symbol]||{};return `<li><form class="st-f" data-s="${esc(h.symbol)}" novalidate><div class="st-n"><a href="/stock.html?symbol=${encodeURIComponent(h.symbol)}">${esc(h.symbol)}</a><span>${esc(h.name||'')}</span></div>
  <label class="st-i"><span>Target weight (%)</span><input inputmode="decimal" name="target_weight" value="${s.target_weight??''}" placeholder="none"></label>
  <label class="st-i"><span>Review level (₹)</span><input inputmode="decimal" name="review_price" value="${s.review_price??''}" placeholder="none"></label>
  <label class="st-i"><span>Sector</span><input name="sector" maxlength="40" value="${esc(s.sector||'')}" placeholder="your label" list="sectors"></label>
  <button class="btn" type="submit">Save</button><p class="st-m" role="status"></p></form></li>`}).join('')}</ul><datalist id="sectors">${[...new Set(Object.values(STOCKS).map(x=>x.sector).filter(Boolean))].map(x=>`<option value="${esc(x)}">`).join('')}</datalist>`}

function bindStocks(){document.querySelectorAll('.st-f').forEach(f=>f.onsubmit=e=>{e.preventDefault();const sym=f.dataset.s,v=n=>f.elements[n].value.trim(),m=f.querySelector('.st-m');
 m.textContent='';m.className='st-m';
 Holdings.api('PUT','/api/rules',{stock:{symbol:sym,target_weight:v('target_weight')===''?null:Holdings.num(v('target_weight')),review_price:v('review_price')===''?null:Holdings.num(v('review_price')),sector:v('sector')}})
  .then(r=>{STOCKS=r.stocks;m.textContent='Saved';Holdings.say(sym+' saved');if(window.Mine)Mine.load(true).catch(()=>{});if(window.Attention)Attention.load(true).catch(()=>{})})
  .catch(err=>{m.textContent=err.message;m.className='st-m bad'})})}

function notifyHtml(){const ok=!!window.Notification,on=Attention.notifyOn(),perm=ok?Notification.permission:'unsupported';
 return `<div class="rl-h"><div class="rl-t"><b>Browser notifications</b><span>One quiet, silent notification when new alerts appear while the app is open. Off by default.${perm=='denied'?' Notifications are blocked in the browser settings.':''}${!ok?' This browser does not support notifications.':''}</span></div>
  <button type="button" class="tglb" id="nt" role="switch" aria-checked="${on}" aria-label="Browser notifications: ${on?'on':'off'}" ${ok&&perm!='denied'?'':'disabled'}><span class="tgl"></span></button></div><p class="rl-e" role="alert" id="nt-e"></p>`}

startPage({needsData:false,
 boot(){$('app').innerHTML=ph('Settings','Choose which alerts you see and when they fire. For research and education. Not investment advice.')+SK;
  Promise.all([Holdings.api('GET','/api/rules'),Mine.load().catch(()=>null)]).then(([r])=>{
   RULES=r.rules;DEFS=r.defaults;META=r.meta;STOCKS=r.stocks;
   HELD=r.held.map(sy=>({symbol:sy,name:(Mine.pos[sy]||{}).name}));
   $('app').innerHTML=ph('Settings','Choose which alerts you see and when they fire. For research and education. Not investment advice.')
    +`<section class="card" aria-labelledby="h-rules"><div class="card-h"><div><h2 id="h-rules">Alert rules</h2><p>Each rule is a prompt to look again, never an instruction to buy or sell. Every alert shows the rule that fired and the numbers behind it. Changes save as you make them.</p></div><button class="btn" type="button" id="reset">Reset to defaults</button></div><div class="card-b" id="rules"></div></section>`
    +`<section class="card" aria-labelledby="h-st"><div class="card-h"><div><h2 id="h-st">Your stocks</h2><p>Optional per-stock targets used by the rules above. The sector label is yours, so the portfolio can be split by sector.</p></div></div><div class="card-b">${stocksHtml()}</div></section>`
    +`<section class="card" aria-labelledby="h-nt"><div class="card-h"><div><h2 id="h-nt">Notifications</h2></div></div><div class="card-b" id="nt-box">${notifyHtml()}</div></section>`
    +`<section class="card" aria-labelledby="h-dt"><div class="card-h"><div><h2 id="h-dt">Your data</h2><p>Stored on this computer. Keep a copy: export your transactions and settings, and import them back any time.</p></div></div><div class="card-b"><div class="pf-data"><a class="btn" href="/api/export.csv" download="my-transactions.csv">Export transactions (CSV)</a><a class="btn" href="/api/export" download="my-portfolio.json">Export everything (JSON)</a><button class="btn" type="button" id="imp">${ic('upload','sm')}Import a file</button></div></div></section>`;
   drawRules();bindStocks();
   $('reset').onclick=()=>Holdings.api('PUT','/api/rules',{rules:DEFS}).then(r=>{RULES=r.rules;drawRules();Holdings.say('Rules reset to the defaults')});
   $('imp').onclick=()=>Holdings.openImport(()=>{});
   const nt=$('nt');if(nt)nt.onclick=()=>{const on=Attention.notifyOn(),e=$('nt-e');e.textContent='';
    (on?Promise.resolve(Attention.disableNotifications()):Attention.enableNotifications()).then(()=>{$('nt-box').innerHTML=notifyHtml();$('nt').onclick=nt.onclick}).catch(err=>{e.textContent=err.message})};
  }).catch(e=>{$('app').innerHTML=ph('Settings','')+`<div class="card"><div class="card-b">${empty('triangle-alert','Could not load your settings',esc(e.message),'<button class="btn" type="button" onclick="location.reload()">Try again</button>')}</div></div>`})},
 build(){},update(){}});

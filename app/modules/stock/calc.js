/* calc.js: "What if I had invested" card: lump sum, SIP and compounding illustration. Pure maths in _t (unit-tested under node). */
(function(root,fac){const m=fac(root);if(typeof module=='object'&&module.exports)module.exports=m;else root.Calc=m})(typeof window!='undefined'?window:this,function(root){
const DAY=864e5,ok=Number.isFinite;
const ms=s=>Date.UTC(+s.slice(0,4),+s.slice(5,7)-1,+s.slice(8,10));
const iso=t=>new Date(t).toISOString().slice(0,10);
const days=(a,b)=>Math.round((ms(b)-ms(a))/DAY);
const dim=(y,m)=>new Date(Date.UTC(y,m,0)).getUTCDate();   // m is 1-12
function addYears(s,n){const y=+s.slice(0,4)+n,m=+s.slice(5,7),d=+s.slice(8,10);return iso(Date.UTC(y,m-1,Math.min(d,dim(y,m))))}
function addDays(s,n){return iso(ms(s)+n*DAY)}
function ymd(y,m,d){return iso(Date.UTC(y,m-1,Math.min(d,dim(y,m))))}
/* first index with d[i] >= s (d sorted ascending ISO strings), or -1 */
function firstOnOrAfter(d,s){let lo=0,hi=d.length;while(lo<hi){const m=(lo+hi)>>1;if(d[m]<s)lo=m+1;else hi=m}return lo<d.length?lo:-1}
/* keep only rows with a real positive close */
function clean(b){if(!b||!Array.isArray(b.d)||!Array.isArray(b.c))return{d:[],c:[]};const d=[],c=[];
 for(let i=0;i<b.d.length;i++){const v=+b.c[i];if(typeof b.d[i]=='string'&&ok(v)&&v>0&&(!d.length||b.d[i]>d[d.length-1])){d.push(b.d[i].slice(0,10));c.push(v)}}return{d,c}}
const TOL=7;   // days of slack when judging whether history reaches back to a target date
/* periods the history covers: [{k:'1',years:1,start:'YYYY-MM-DD'}...,{k:'max'}] */
function periods(d){if(d.length<20)return[];const last=d[d.length-1],o=[];
 [1,3,5,10].forEach(y=>{const t=addYears(last,-y);if(d[0]<=addDays(t,TOL))o.push({k:String(y),years:y,start:t})});
 o.push({k:'max',years:null,start:d[0]});return o}
function pickPeriod(d,k){const p=periods(d);return p.find(x=>x.k==k)||p[p.length-1]||null}
function maxDrawdown(c,i0=0){let pk=-Infinity,dd=0;for(let i=i0;i<c.length;i++){if(c[i]>pk)pk=c[i];const x=c[i]/pk-1;if(x<dd)dd=x}return dd}
function rolling1y(d,c,i0=0){let best=null,worst=null,j=i0;
 for(let i=i0;i<d.length;i++){const t=addYears(d[i],1);while(j<d.length&&d[j]<t)j++;if(j>=d.length)break;const r=c[j]/c[i]-1;if(best==null||r>best)best=r;if(worst==null||r<worst)worst=r}
 return best==null?null:{best,worst}}
const cagr=(a,b,dd)=>dd>=365&&a>0&&b>0?Math.pow(b/a,365/dd)-1:null;
function lump(d,c,start,amount){if(!(amount>0)||!d.length)return null;const i0=firstOnOrAfter(d,start);if(i0<0||i0>=d.length-1)return null;
 const n=d.length-1,val=amount/c[i0]*c[n],dd=days(d[i0],d[n]);
 return{startDate:d[i0],endDate:d[n],days:dd,invested:amount,value:val,gain:val-amount,gainPct:val/amount-1,cagr:cagr(amount,val,dd),maxDD:maxDrawdown(c,i0),roll:rolling1y(d,c,i0)}}
/* XIRR: flows [{t:days from first flow, a:amount}], Newton from a guess, bisection fallback. Returns null when there is no solution. */
function xirr(fl){if(!fl||fl.length<2)return null;const npv=r=>{let s=0;for(const x of fl)s+=x.a/Math.pow(1+r,x.t/365);return s};
 if(!fl.some(x=>x.a<0)||!fl.some(x=>x.a>0))return null;
 const dnpv=r=>{let s=0;for(const x of fl)s-=x.a*(x.t/365)/Math.pow(1+r,x.t/365+1);return s};
 let r=0.1;for(let i=0;i<50;i++){const f=npv(r),g=dnpv(r);if(!ok(f)||!ok(g)||g==0)break;const nr=r-f/g;if(!ok(nr)||nr<=-0.999999)break;if(Math.abs(nr-r)<1e-10){if(Math.abs(npv(nr))<1e-6*Math.max(1,Math.abs(fl[0].a)))return nr;break}r=nr}
 let lo=-0.9999,hi=1000,flo=npv(lo),fhi=npv(hi);if(!ok(flo)||!ok(fhi)||flo*fhi>0)return null;
 for(let i=0;i<300;i++){const mid=(lo+hi)/2,fm=npv(mid);if(!ok(fm))return null;if(fm*flo<=0){hi=mid;fhi=fm}else{lo=mid;flo=fm}if(hi-lo<1e-12)break}
 return(lo+hi)/2}
/* SIP: buy `amount` on the first trading day on or after `day` of each month, from `start` to the last bar. */
function sip(d,c,start,amount,day){if(!(amount>0)||!d.length)return null;day=Math.min(28,Math.max(1,Math.round(+day||1)));
 const buys=[];let y=+start.slice(0,4),m=+start.slice(5,7);const last=d[d.length-1];
 for(let g=0;g<1300;g++){const t=ymd(y,m,day);if(t>last)break;if(t>=start){const i=firstOnOrAfter(d,t);if(i<0)break;if(!buys.length||buys[buys.length-1]<i)buys.push(i)}if(++m>12){m=1;y++}}
 if(buys.length<2)return null;
 let units=0,inv=0,p=0,worst=0,worstPct=0,worstDate=null;const n=d.length-1,fl=[];
 for(let i=buys[0];i<=n;i++){if(p<buys.length&&buys[p]==i){units+=amount/c[i];inv+=amount;fl.push({t:days(d[buys[0]],d[i]),a:-amount});p++}
  const u=units*c[i]-inv;if(u<worst){worst=u;worstPct=u/inv;worstDate=d[i]}}
 const val=units*c[n],dd=days(d[buys[0]],d[n]);fl.push({t:dd,a:val});
 return{startDate:d[buys[0]],endDate:d[n],days:dd,count:buys.length,invested:inv,value:val,gain:val-inv,gainPct:val/inv-1,xirr:dd>=90?xirr(fl):null,worstUnder:worst<0?{amt:worst,pct:worstPct,date:worstDate}:null}}
/* compounding illustration. rate is annual percent (0-30), years 1-40. Monthly deposits at the start of each month, monthly rate = (1+a)^(1/12)-1. */
function compound(mode,amount,ratePct,years){amount=+amount;ratePct=+ratePct;years=+years;
 if(!(amount>0)||!ok(amount)||!(ratePct>=0&&ratePct<=30)||!(years>=1&&years<=40))return null;
 const a=ratePct/100;let inv,fv;
 if(mode=='lump'){inv=amount;fv=amount*Math.pow(1+a,years)}
 else{const n=Math.round(years*12),rm=Math.pow(1+a,1/12)-1;inv=amount*n;fv=rm==0?inv:amount*(Math.pow(1+rm,n)-1)/rm*(1+rm)}
 return ok(fv)?{invested:inv,value:fv,gain:fv-inv,mult:fv/inv}:null}
const _t={addYears,addDays,ymd,days,firstOnOrAfter,clean,periods,pickPeriod,maxDrawdown,rolling1y,lump,sip,xirr,compound,cagr};
if(typeof document=='undefined'||!root||!root.document)return{_t};

/* ---------- UI ---------- */
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const inr=n=>ok(n)?'₹'+Math.round(n).toLocaleString('en-IN'):'–';
const pct=(x,d=1)=>ok(x)?(x>=0?'+':'−')+Math.abs(x*100).toLocaleString('en-IN',{minimumFractionDigits:d,maximumFractionDigits:d})+'%':'–';
const sg=n=>ok(n)?(n>=0?'+':'−')+inr(Math.abs(n)):'–';
const cl=n=>n>=0?'up':'dn';
const dfmt=s=>new Date(s+'T00:00:00').toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'});
const KEY='calcState',DEF={tab:'lump',amt:100000,sipAmt:10000,day:1,per:'5',cMode:'sip',cAmt:10000,rate:12,yrs:10};
let S=Object.assign({},DEF);
try{const v=JSON.parse(localStorage.getItem(KEY));if(v&&typeof v=='object')for(const k in DEF)if(typeof v[k]==typeof DEF[k])S[k]=v[k]}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(S))}catch(e){}};
const CACHE={};
function load(sym){if(CACHE[sym])return CACHE[sym];
 const get=s=>fetch('/api/chart?sym='+encodeURIComponent(s)).then(r=>{if(!r.ok)throw new Error('http '+r.status);return r.json()}).then(clean);
 const p=Promise.all([get(sym),get('^NSEI').catch(()=>null)]).then(([a,b])=>({s:a,n:b&&b.d.length>=20?b:null}));
 CACHE[sym]=p;p.catch(()=>{delete CACHE[sym]});return p}

const num=(id,label,val,extra='')=>`<div class="cc-f"><label for="${id}">${label}</label><input id="${id}" type="number" inputmode="decimal" value="${val<0?'':esc(val)}" ${extra}></div>`;   // -1 is the internal "cleared or invalid" marker: show an empty field
const bar=(label,v,mx,inv,cls)=>`<div class="cc-b"><span class="cc-bl">${label}</span><span class="cc-bt"><i class="${cls}" style="width:${mx>0?Math.max(2,Math.min(100,v/mx*100)):0}%"></i><u style="left:${mx>0?Math.min(100,inv/mx*100):0}%" title="Amount invested"></u></span><b>${inr(v)}</b></div>`;

function tbl(rows,hasN,sym){return `<table class="mini cc-t"><caption class="sr">Results for ${esc(sym)}${hasN?' and the Nifty 50':''}</caption><thead><tr><th scope="col"></th><th scope="col">${esc(sym)}</th>${hasN?'<th scope="col">Nifty 50</th>':''}</tr></thead><tbody>${rows.map(r=>`<tr><th scope="row">${r[0]}</th>${r.slice(1,hasN?3:2).map(x=>`<td>${x==null?'–':x}</td>`).join('')}</tr>`).join('')}</tbody></table>`}
const gainCell=(r,i)=>r?`<span class="${cl(r.gain)}">${sg(r.gain)} (${pct(r.gainPct)})</span>`:null;

function lumpHTML(sym,a,n,per,amt){
 if(!(amt>0)||!ok(amt)||amt>1e10)return '<p class="cc-msg dn" role="alert">Enter an amount above 0.</p>';
 const r=lump(a.d,a.c,per.start,amt);if(!r)return '<p class="cc-msg">Not enough history in this period to calculate.</p>';
 const q=n?lump(n.d,n.c,r.startDate,amt):null;
 const rl=x=>x&&x.roll?`${pct(x.roll.best)} / ${pct(x.roll.worst)}`:null;
 const rows=[['Invested',inr(amt),q&&inr(amt)],['Value today',inr(r.value),q&&inr(q.value)],['Gain',gainCell(r),q&&gainCell(q)],
  ['CAGR (per year)',r.cagr==null?'n/a, under 1 year':pct(r.cagr),q&&(q.cagr==null?'n/a':pct(q.cagr))],
  ['Worst fall from a peak',`<span class="dn">${pct(r.maxDD)}</span>`,q&&`<span class="dn">${pct(q.maxDD)}</span>`],
  ['Best / worst 1-year',rl(r)||'n/a, under 2 years',q&&(rl(q)||'n/a')]];
 return summary(sym,r,tbl(rows,!!q,sym),[['Stock',r.value],['Nifty 50',q&&q.value]],amt,!!q,`${dfmt(r.startDate)} to ${dfmt(r.endDate)} (${(r.days/365.25).toFixed(1)} years). Bought on the first trading day on or after the start.`,n)}
function sipHTML(sym,a,n,per,amt){
 if(!(amt>0)||!ok(amt)||amt>1e9)return '<p class="cc-msg dn" role="alert">Enter a monthly amount above 0.</p>';
 const r=sip(a.d,a.c,per.start,amt,S.day);if(!r)return '<p class="cc-msg">Not enough history in this period for at least two monthly instalments.</p>';
 const q=n?sip(n.d,n.c,r.startDate,amt,S.day):null;
 const ud=x=>x&&(x.worstUnder?`<span class="dn">${sg(x.worstUnder.amt)} (${pct(x.worstUnder.pct)})</span><div class="sm mu">${dfmt(x.worstUnder.date)}</div>`:'Never below amount invested');
 const rows=[['Instalments',r.count,q&&q.count],['Total invested',inr(r.invested),q&&inr(q.invested)],['Value today',inr(r.value),q&&inr(q.value)],['Gain',gainCell(r),q&&gainCell(q)],
  ['XIRR (per year)',r.xirr==null?'n/a, under 3 months':pct(r.xirr),q&&(q.xirr==null?'n/a':pct(q.xirr))],
  ['Deepest under water',ud(r),q&&ud(q)]];
 return summary(sym,r,tbl(rows,!!q,sym),[['Stock',r.value],['Nifty 50',q&&q.value]],r.invested,!!q,`${r.count} instalments of ${inr(amt)}, ${dfmt(r.startDate)} to ${dfmt(r.endDate)}. Each is bought on the first trading day on or after day ${Math.min(28,S.day)} of the month.`,n)}
function summary(sym,r,table,vals,inv,hasN,range,n){const mx=Math.max(...vals.map(v=>v[1]||0),inv);
 return `<p class="cc-note"><b>Past performance, not a prediction.</b> ${range}</p>${table}
 <div class="cc-bars" role="group" aria-label="Value today compared with the amount invested">${bar(esc(sym),vals[0][1],mx,inv,'s')}${hasN?bar('Nifty 50',vals[1][1],mx,inv,'n'):''}<p class="hint">Bar length is value today; the tick marks the amount invested.</p></div>
 ${hasN?'':'<p class="hint">Nifty 50 history was not available, so only the stock is shown.</p>'}
 <p class="hint">Yahoo Finance daily prices adjusted for splits and dividends, as of ${dfmt(r.endDate)}. Ignores taxes, brokerage and fund or index costs.</p>`}
function compHTML(){const r=compound(S.cMode,S.cAmt,S.rate,S.yrs);
 if(!(S.cAmt>0))return '<p class="cc-msg dn" role="alert">Enter an amount above 0.</p>';
 if(!(S.rate>=0&&S.rate<=30))return '<p class="cc-msg dn" role="alert">Return must be between 0 and 30 percent a year.</p>';
 if(!(S.yrs>=1&&S.yrs<=40))return '<p class="cc-msg dn" role="alert">Years must be between 1 and 40.</p>';
 if(!r)return '<p class="cc-msg dn" role="alert">These numbers are too large to show.</p>';
 return `<p class="cc-note"><b>Illustration only, not a forecast. The return rate is your assumption, not data.</b></p>
 <div class="cc-k"><div><span>You invest</span><b>${inr(r.invested)}</b></div><div><span>Grows to</span><b>${inr(r.value)}</b></div><div><span>Gain</span><b class="up">${sg(r.gain)}</b></div><div><span>Multiple</span><b>${r.mult.toLocaleString('en-IN',{maximumFractionDigits:2})}x</b></div></div>
 ${bar('Invested',r.invested,r.value,r.invested,'n')}${bar('Future value',r.value,r.value,r.invested,'s')}
 <p class="hint">${S.cMode=='lump'?'One amount invested today':'Deposits at the start of each month'}, ${S.rate}% a year compounded, ${S.yrs} years. Real returns vary and can be negative. Ignores taxes and inflation.</p>`}

function mount(host,sym,opts){
 if(!host)return;const tabs=[['lump','Lump sum'],['sip','Monthly SIP'],['comp','Compounding calculator']];
 host.innerHTML=`<section class="card cc" aria-label="What if I had invested"><div class="card-h"><div><h2>What if I had invested</h2><p>See what ${esc(sym)} would have done for you, or try a compounding illustration.</p></div></div><div class="card-b">
 <div class="seg" role="group" aria-label="Calculator type" id="cc-tabs">${tabs.map(t=>`<button type="button" class="tab ${t[0]==S.tab?'on':''}" data-t="${t[0]}" aria-pressed="${t[0]==S.tab}">${t[1]}</button>`).join('')}</div>
 <div class="cc-in" id="cc-in"></div><div id="cc-out" aria-live="polite" aria-atomic="true"></div>
 <p class="hint cc-d">For research and education. Not investment advice.</p></div></section>`;
 const $=id=>host.querySelector('#'+id);let data=null,state='load',gen=0;
 const per=()=>data&&data.s.d.length?pickPeriod(data.s.d,S.per):null;
 function inputs(){const P=data?periods(data.s.d):[],ps=P.length?`<div><label id="cc-pl">Start</label><div class="seg" role="group" aria-labelledby="cc-pl">${P.map(p=>{const lab=p.k=='max'?'Max':p.k+(p.k=='1'?' year':' years');return `<button type="button" class="tab ${p.k==(per()||{}).k?'on':''}" data-per="${p.k}" aria-pressed="${p.k==(per()||{}).k}">${lab}</button>`}).join('')}</div></div>`:'';
  $('cc-in').innerHTML=S.tab=='lump'?num('cc-a','Amount (₹)',S.amt,'min="1" step="1000"')+ps
   :S.tab=='sip'?num('cc-a','Monthly amount (₹)',S.sipAmt,'min="1" step="500"')+`<div class="cc-f"><label for="cc-day">Day of month</label><select id="cc-day">${Array.from({length:28},(_,i)=>`<option value="${i+1}" ${i+1==S.day?'selected':''}>${i+1}</option>`).join('')}</select></div>`+ps
   :`<div class="cc-f"><label for="cc-m">Investing</label><select id="cc-m"><option value="sip" ${S.cMode=='sip'?'selected':''}>Every month</option><option value="lump" ${S.cMode=='lump'?'selected':''}>One lump sum</option></select></div>`+num('cc-a',S.cMode=='sip'?'Monthly amount (₹)':'Amount (₹)',S.cAmt,'min="1" step="500"')+num('cc-r','Assumed return (% a year, 0 to 30)',S.rate,'min="0" max="30" step="0.5"')+num('cc-y','Years (1 to 40)',S.yrs,'min="1" max="40" step="1"');
  const A=$('cc-a');A.oninput=()=>{const v=parseFloat(A.value);if(S.tab=='lump')S.amt=ok(v)?v:0;else if(S.tab=='sip')S.sipAmt=ok(v)?v:0;else S.cAmt=ok(v)?v:0;save();out()};
  const dd=$('cc-day');if(dd)dd.onchange=()=>{S.day=+dd.value;save();out()};
  const cm=$('cc-m');if(cm)cm.onchange=()=>{S.cMode=cm.value;save();inputs();out()};
  const r=$('cc-r');if(r)r.oninput=()=>{const v=parseFloat(r.value);S.rate=ok(v)?v:-1;save();out()};
  const y=$('cc-y');if(y)y.oninput=()=>{const v=parseFloat(y.value);S.yrs=ok(v)?v:0;save();out()};
  host.querySelectorAll('[data-per]').forEach(b=>b.onclick=()=>{S.per=b.dataset.per;save();inputs();out();const nb=host.querySelector(`[data-per="${S.per}"]`);nb&&nb.focus()})}
 function out(){const o=$('cc-out');
  if(S.tab=='comp'){o.innerHTML=compHTML();return}
  if(state=='load'){o.innerHTML='<div class="sk" style="width:60%;height:20px"></div><div class="sk" style="width:90%"></div><div class="sk" style="width:75%"></div>';return}
  if(state=='err'){o.innerHTML='<div class="empty"><b>Could not load price history</b><span>Check your connection and try again.</span><button type="button" class="btn" id="cc-retry">Retry</button></div>';$('cc-retry').onclick=go;return}
  const p=per();if(!p){o.innerHTML='<div class="empty"><b>Not enough price history</b><span>This listing is too new for a meaningful what-if. Come back after a few weeks of trading.</span></div>';return}
  const n=data.n&&data.n.d[0]<=addDays(p.start,TOL)?data.n:null;
  o.innerHTML=S.tab=='lump'?lumpHTML(sym,data.s,n,p,S.amt):sipHTML(sym,data.s,n,p,S.sipAmt)}
 function go(){const g=++gen;state='load';out();load(sym).then(d=>{if(g!=gen)return;data=d;state='ok';inputs();out()}).catch(()=>{if(g!=gen)return;state='err';out()})}
 host.querySelectorAll('#cc-tabs .tab').forEach(b=>b.onclick=()=>{S.tab=b.dataset.t;save();host.querySelectorAll('#cc-tabs .tab').forEach(x=>{x.classList.toggle('on',x==b);x.setAttribute('aria-pressed',x==b)});inputs();out()});
 inputs();out();go()}
return{mount,_t}});

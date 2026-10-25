/* Code every page shares: formatters, scan loading and status line, horizon tabs, the stock detail view and its charts.
   Page scripts (index.js, stocks.js, ...) call startPage({boot, build, update}) and rely on the globals below. */
Shell.mount();
const $=id=>document.getElementById(id);
const ic=Shell.icon;
const H=[['1d','1 day'],['2d','2 days'],['5d','5 days'],['10d','10 days'],['1m','1 month'],['3m','3 months'],['6m','6 months']];
const SHORT_NOTE='Very short horizons are mostly noise: the likely range is wide and the chance of gain stays close to 50%. The Buy, Wait and Watch call is still judged on the 1-month outlook, not on this horizon.';
const pg=document.body.dataset.page;
const hzOK=k=>H.some(h=>h[0]==k);
function startHz(){const m=location.hash.match(/hz=(1d|2d|5d|10d|1m|3m|6m)/);if(m)return m[1];try{const v=localStorage.getItem('hz');if(hzOK(v))return v}catch(e){}return '1m'}
let D=null,hz=startHz(),open=null,cur=null,LIM=[100000,3000];const DET={},FETCH={};
try{const v=JSON.parse(localStorage.getItem('lt'));if(v&&isFinite(v[0])&&isFinite(v[1]))LIM=[+v[0],+v[1]]}catch(e){}
const f=(n,d=2)=>n.toLocaleString('en-IN',{minimumFractionDigits:d,maximumFractionDigits:d});
const pc=(n,d=1)=>`${n>=0?'+':''}${f(n*100,d)}%`;
const pcc=n=>`<span class="${n>=0?'up':'dn'}">${pc(n)}</span>`;
const dt=(s,w=1)=>new Date(s+'T00:00:00').toLocaleDateString('en-IN',{weekday:w?'short':undefined,day:'numeric',month:'short',year:'numeric'});
const ds=s=>new Date(s+'T00:00:00').toLocaleDateString('en-IN',{day:'numeric',month:'short'});
const hb=s=>{const w=D.holidayWarnings&&D.holidayWarnings[s.slice(0,4)];return w?` <span class="dn" title="${w=='missing'?'No NSE holiday list for this year, so exchange holidays are ignored':'NSE has not published this year\'s holidays yet, so the date may be off by a day'}">${w=='missing'?'(no holiday list)':'(provisional)'}</span>`:''}
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const hname=k=>H.find(h=>h[0]==k)[1];
const VL={BUY:'Buy',WAIT:'Wait',WATCH:'Watch',DOWNTREND:'Downtrend'};
const ph=(h1,sub,act='',row='')=>`<div class="ph"><div><h1>${h1}</h1>${sub?`<p class="sub0">${sub}</p>`:''}</div>${act?`<div class="ph-act">${act}</div>`:''}</div>${row?`<div class="ph-row">${row}</div>`:''}`;
const kpi=(icon,label,val,sub,cls='')=>`<div class="card kpi"><div class="kpi-l">${ic(icon)}${label}</div><div class="kpi-v ${cls}">${val}</div><div class="kpi-s">${sub||''}</div></div>`;
const arrow=n=>ic(n>=0?'arrow-up-right':'arrow-down-right','sm');
const empty=(icon,title,text,extra='')=>`<div class="empty"><div class="ico">${ic(icon)}</div><b>${title}</b><span>${text}</span>${extra}</div>`;
const TABS='<div class="seg" id="tabs" role="group" aria-label="Holding period"></div><p class="hint" id="hzn" role="note"></p>';
const SET='<div class="set"><div><label for="bud">Budget (₹)</label><input id="bud" type="number" inputmode="numeric" min="0" step="1000"></div><div><label for="ml">Max loss per stock (₹)</label><input id="ml" type="number" inputmode="numeric" min="0" step="500"></div><p class="hint">Shares to buy are the smaller of what your max loss allows at the stop-loss and what your budget buys.</p></div>';
const SK='<div class="card"><div class="card-b"><div class="sk" style="width:40%;height:24px"></div><div class="sk" style="width:85%"></div><div class="sk" style="width:70%"></div><div class="sk" style="width:78%"></div></div></div>';
const DISC='For education only. Not investment advice, and not a recommendation to buy, sell or hold any stock or ETF. We are not responsible for your decisions or for any loss. Forecasts are historical base rates for stocks that looked similar in the past, scaled to each stock\'s own volatility. They are <b>not guarantees</b>. Past patterns can fail, and any stock can fall further than the likely range. Check the stop-loss and never invest money you cannot afford to lose.';

function tabs(){const t=$('tabs');if(!t)return;const a=document.activeElement,keep=a&&a.dataset&&a.classList.contains('tab')?a.dataset.h:null;
 t.innerHTML=H.map(h=>`<button class="tab ${h[0]==hz?'on':''}" data-h="${h[0]}" aria-pressed="${h[0]==hz}" aria-label="${h[1]}" title="${h[1]}">${h[0].toUpperCase()}</button>`).join('');
 t.querySelectorAll('.tab').forEach(b=>{b.onclick=()=>{hz=b.dataset.h;writeHz();PAGE.update()};if(b.dataset.h==keep)b.focus()});
 const n=$('hzn');if(n)n.textContent=['1d','2d','5d'].includes(hz)?SHORT_NOTE:''}
const hzHash=()=>hz=='1m'?'':'#hz='+hz;
function writeHz(){try{localStorage.setItem('hz',hz)}catch(e){}try{history.replaceState(null,'',location.pathname+location.search+hzHash())}catch(e){}}
const kindOf=s=>s.etf?'ETF':s.exchange=='BSE'?'BSE':'NSE';
const ord={BUY:0,WAIT:1,WATCH:2,DOWNTREND:3};
const byRank=(a,b)=>ord[a.verdict]-ord[b.verdict]||rk(b)-rk(a);
function rk(s){const p=s.forecast[hz];return p.p50/Math.max(p.p90-p.p10,1e-6)}
function M(sym){const s=D.stocks.find(x=>x.symbol==sym),X=DET[sym];
 return s&&X?Object.assign({},s,X,{buyDate:s.verdict=='BUY'?D.buyDate:null,sellDates:D.sellDates}):null}
async function fetchDet(sym){if(DET[sym]||FETCH[sym])return;FETCH[sym]=1;
 const bh=fetch('/api/bhav?sym='+encodeURIComponent(sym)).then(r=>r.ok?r.json():{}).catch(()=>({}));
 try{const r=await fetch('/api/stock?sym='+encodeURIComponent(sym));if(!r.ok)throw 0;DET[sym]=await r.json()}catch(e){DET[sym]={why:[],series:null}}
 DET[sym].bhav=await bh;
 delete FETCH[sym];if(pg=='stock'&&cur==sym)PAGE.update();else if(open==sym&&D&&$('tb'))table()}
function official(s){const B=s.bhav||{},ex=['NSE','BSE'].filter(e=>B[e]);
 if(!ex.length)return '<div class="ft">Official NSE/BSE prices: not in the latest exchange file.</div>';
 const vol=n=>n>=1e7?f(n/1e7,2)+' crore':n>=1e5?f(n/1e5,1)+' lakh':f(n,0);   // Indian grouping, short enough for the narrow column
 const dates=[...new Set(ex.map(e=>B[e].date))],same=dates.length==1;
 const rows=ex.map(e=>{const x=B[e],ch=x.prev_close?(x.close/x.prev_close-1)*100:null;
  return `<tr><th scope="row">${e}${same?'':`<div class="sm">${esc(ds(x.date))}</div>`}</th><td>₹${f(x.close)}<div class="sm mu">${f(x.low)} – ${f(x.high)}</div></td><td class="${ch==null?'mu':ch>=0?'up':'dn'}">${ch==null?'':(ch>=0?'+':'')+f(ch,2)+'%'}</td><td class="mu" title="${f(x.volume,0)} shares">${vol(x.volume)}</td></tr>`}).join('');
 return `<h3>Official exchange close</h3><div class="of"><table class="mini off"><caption class="sr">Official close, day change, low to high range and volume on each exchange</caption><tr><th scope="col">Exchange</th><th scope="col">Close, low – high</th><th scope="col">Day</th><th scope="col">Volume</th></tr>${rows}</table></div><div class="ft">${same?`As of ${esc(dt(dates[0],0))}. `:''}From the exchanges' own end-of-day files (bhavcopy). The chart and forecast use Yahoo prices.</div>`}
function detailParts(s){const p=s.forecast[hz],b=LIM[0],m=LIM[1],risk=s.price-s.stop;
 const q=Math.max(0,Math.min(Math.floor(m/risk),Math.floor(b/s.price)));
 const plan=s.verdict=='BUY'?`<div><span>Buy</span><b>${dt(s.buyDate)}${hb(s.buyDate)} (next session)</b></div><div><span>Sell or review</span><b>${dt(s.sellDates[hz])}${hb(s.sellDates[hz])}</b></div>`
  :s.verdict=='WAIT'?`<div><span>Buy</span><b>only on a dip to about ₹${f(s.sma20)}</b></div><div><span>If bought ${dt(D.today,0)}</span><b>review ${dt(s.sellDates[hz],0)}${hb(s.sellDates[hz])}</b></div>`
  :`<div><span>Buy</span><b>not now</b></div><div><span>If you buy anyway</span><b>review ${dt(s.sellDates[hz],0)}${hb(s.sellDates[hz])}</b></div>`;
 const fr=H.map(h=>{const x=s.forecast[h[0]];return `<tr><td>${h[1]}</td><td>${pcc(x.p50)}</td><td class="mu">${pc(x.p10,0)} / ${pc(x.p90,0)}</td><td>${f(x.pgain*100,0)}%</td><td class="mu">${f(x.n,0)}</td></tr>`}).join('');
 const nw=(s.news||[]);const hasNews=s.news!=null;
  const price=`<section class="dsec"><h3>Price history</h3><div class="pc" data-sym="${esc(s.symbol)}"></div></section>`;
 const fc=`<section class="dsec"><h3>Forecast over ${hname(hz)}</h3><div class="cw" id="cw" style="min-height:300px"></div><div class="leg"><span><i style="background:var(--tx)"></i>Price (adjusted)</span><span><i style="background:var(--am)"></i>50-day average</span><span><i style="background:var(--s200)"></i>200-day average</span><span><i style="background:var(--ac)"></i>Forecast, with 50% and 80% ranges shaded</span><span><i style="background:var(--dn)"></i>Stop-loss</span><span id="leg-my"${(window.MY_POS&&MY_POS[s.symbol])?'':' hidden'}><i style="height:0;background:none;border-top:2px dotted var(--tx)"></i>Your average buy price</span></div>${chartTable(s)}</section>`;
 const planS=`<section class="dsec"><h3>Plan</h3><div class="pl"><div><span data-term="call">Call</span><b><span class="vd ${s.verdict}">${VL[s.verdict]}</span></b></div>${plan}
 <div><span><span data-term="stop-loss">Stop-loss</span> (sell if it closes below)</span><b class="dn">₹${f(s.stop)}</b></div>
 <div><span>Position size</span><b>${q?`${f(q,0)} shares, ₹${f(q*s.price,0)}, max loss ₹${f(q*risk,0)}`:'does not fit your limits'}</b></div>
 <div><span data-term="setup-score">Setup score</span><b>${s.score}</b></div></div>
 <p class="mu" style="margin:12px 0 0">${esc(s.note)}</p></section>`;
 const off=`<section class="dsec">${official(s)}</section>`;
 const why=`<section class="dsec"><h3>Why</h3><ul data-gloss-auto>${s.why.map(w=>`<li class="${w[0]=='up'?'up':w[0]=='down'?'dn':''}">${esc(w[1])}</li>`).join('')}</ul></section>`;
 const hor=`<section class="dsec"><h3>Forecast by horizon</h3><table class="mini"><tr><th><span data-term="horizon">Horizon</span></th><th><span data-term="typical">Typical</span></th><th><span data-term="likely-range">Low / high*</span></th><th><span data-term="chance-of-gain">Gain odds</span></th><th>Samples</th></tr>${fr}</table><div class="ft">*10th and 90th percentile outcomes.</div></section>`;
 const news=`<section class="dsec"><h3>News from the last 14 days</h3><div class="nw">${hasNews?(nw.length?nw.slice(0,4).map(x=>`<div><span class="tg ${x.tag}">${x.tag}</span><a href="${esc(x.link)}" target="_blank" rel="noopener">${esc(x.title)}</a></div>`).join(''):'<div class="mu">No headlines found.</div>'):'<div class="mu">News is checked for the 40 highest-scoring stocks only.</div>'}</div></section>`;
 return {price,fc,plan:planS,off,why,hor,news}}
function detail(s){const d=detailParts(s);
 return `<div class="grid dtl"><div class="dcol span-8">${d.price}${d.fc}</div>
 <div class="dcol span-4">${pg=='stock'?'':`<p style="margin:0"><a href="/stock.html?symbol=${encodeURIComponent(s.symbol)}">Open full page for ${esc(s.symbol)}</a></p>`}${d.plan}${d.off}${d.why}${d.hor}${d.news}</div></div>`}

function k0(s){const S=s.series,last=new Date(S.d[S.d.length-1]).getTime(),sell=new Date(s.sellDates[hz]+'T00:00:00').getTime(),
 span=Math.max(120*864e5,2.5*(sell-last));let k=0;while(k<S.d.length-2&&last-new Date(S.d[k]).getTime()>span)k++;return k}
const CM={};
function ticks(mn,mx,n){const st0=(mx-mn)/n,mag=Math.pow(10,Math.floor(Math.log10(st0))),r=st0/mag,st=(r<=1?1:r<=2?2:r<=2.5?2.5:r<=5?5:10)*mag,o=[];
 for(let v=Math.ceil(mn/st)*st;v<=mx+1e-9;v+=st)o.push(v);return{v:o,dec:st%1===0?0:(st*10)%1===0?1:2}}
function chart(s,W){const Ht=W<480?300:340,L=W<480?44:52,R=W<480?10:14,T=12,B=26,K=k0(s),S0=s.series,S={d:S0.d.slice(K),c:S0.c.slice(K),s50:S0.s50.slice(K),s200:S0.s200.slice(K)},
 t0=new Date(S.d[0]).getTime(),last=new Date(S.d[S.d.length-1]).getTime(),
 sell=new Date(s.sellDates[hz]+'T00:00:00').getTime(),t1=sell+(sell-last)*0.04,p=s.forecast[hz];
 const N=24,cone=[];for(let k=0;k<=N;k++){const fr=k/N,t=last+(sell-last)*fr,r=Math.sqrt(fr);
  cone.push({t,lo:s.price*(1+p.p10*r),l2:s.price*(1+p.p25*r),m:s.price*(1+p.p50*r),h2:s.price*(1+p.p75*r),hi:s.price*(1+p.p90*r)})}
 let mn=Math.min(...S.c,...S.s200,s.stop,cone[N].lo),mx=Math.max(...S.c,...S.s50,cone[N].hi);const my=window.MY_POS&&MY_POS[s.symbol];if(my){mn=Math.min(mn,my.avg);mx=Math.max(mx,my.avg)}const pad=(mx-mn)*.06;mn-=pad;mx+=pad;
 const X=t=>L+(t-t0)/(t1-t0)*(W-L-R),Y=v=>T+(1-(v-mn)/(mx-mn))*(Ht-T-B);
 const line=a=>S.d.map((d,i)=>`${X(new Date(d).getTime()).toFixed(1)},${Y(a[i]).toFixed(1)}`).join(' ');
 const band=(a,b)=>cone.map(c=>`${X(c.t).toFixed(1)},${Y(c[a]).toFixed(1)}`).join(' ')+' '+cone.slice().reverse().map(c=>`${X(c.t).toFixed(1)},${Y(c[b]).toFixed(1)}`).join(' ');
 const tk=ticks(mn,mx,W<480?4:5);let g='';tk.v.forEach(v=>{g+=`<line class="gl" x1="${L}" x2="${W-R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"/><text class="ax" x="${L-6}" y="${(Y(v)+4).toFixed(1)}" text-anchor="end">${f(v,tk.dec)}</text>`});
 const m0=new Date(t0),every=(t1-t0>400*864e5||W<480)?2:1;let mo=new Date(m0.getFullYear(),m0.getMonth()+1,1);
 while(mo.getTime()<t1){const x=X(mo.getTime());if(mo.getMonth()%every==0)g+=`<text class="ax" x="${x.toFixed(1)}" y="${Ht-8}" text-anchor="middle">${mo.toLocaleDateString('en-IN',{month:'short',year:'2-digit'})}</text>`;mo=new Date(mo.getFullYear(),mo.getMonth()+1,1)}
 const myLine=my?`<line x1="${L}" x2="${W-R}" y1="${Y(my.avg).toFixed(1)}" y2="${Y(my.avg).toFixed(1)}" stroke="var(--tx)" stroke-width="1.5" stroke-dasharray="2 4"/><text x="${L+4}" y="${(Y(my.avg)-5).toFixed(1)}" class="ax hl2" style="fill:var(--tx)">your average ₹${f(my.avg)}</text>`:'';
 const buyT=new Date((s.buyDate||D.today)+'T00:00:00').getTime();
 const vl=(t,c,l,dash)=>`<line x1="${X(t)}" x2="${X(t)}" y1="${T}" y2="${Ht-B}" stroke="${c}" stroke-width="1.5" ${dash?'stroke-dasharray="4 3"':''}/><text class="ax hl2" x="${X(t)-4}" y="${T+10}" text-anchor="end" style="fill:${c}">${l}</text>`;
 const dot=(x,y,c)=>`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="${c}" stroke="var(--card)" stroke-width="2"/>`;
 CM[s.symbol]={W,X,Y,L,R,S,last,sell,t0,t1,p,price:s.price,t:null};
 return `<div class="tip" id="tp-${s.symbol}" role="status" aria-live="off"></div><svg class="ch" id="ch-${s.symbol}" viewBox="0 0 ${W} ${Ht}" width="${W}" height="${Ht}" data-s="${s.symbol}" tabindex="0" role="img" aria-label="Price history and ${hname(hz)} forecast for ${s.symbol}. Use the left and right arrow keys to read values.">${g}
 <polygon points="${band('lo','hi')}" fill="var(--band1)"/><polygon points="${band('l2','h2')}" fill="var(--band2)"/>
 <polyline points="${line(S.s200)}" fill="none" stroke="var(--s200)" stroke-width="1.5" stroke-linejoin="round"/><polyline points="${line(S.s50)}" fill="none" stroke="var(--am)" stroke-width="1.5" stroke-linejoin="round"/>
 <polyline points="${line(S.c)}" fill="none" stroke="var(--tx)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
 <polyline points="${cone.map(c=>`${X(c.t).toFixed(1)},${Y(c.m).toFixed(1)}`).join(' ')}" fill="none" stroke="var(--ac)" stroke-width="2" stroke-dasharray="5 3"/>
 <line x1="${X(last)}" x2="${X(t1)}" y1="${Y(s.stop)}" y2="${Y(s.stop)}" stroke="var(--dn)" stroke-width="1.5" stroke-dasharray="6 4"/><text x="${W-R}" y="${(Y(s.stop)-5).toFixed(1)}" text-anchor="end" class="ax hl2" style="fill:var(--dn)">stop ₹${f(s.stop)}</text>
 ${myLine}${vl(buyT,'var(--up)',s.buyDate?'Buy':'If bought',s.buyDate?0:1)}${vl(sell,'var(--ac)','Sell',0)}
 ${dot(X(last),Y(s.price),'var(--tx)')}<text x="${(X(last)-9).toFixed(1)}" y="${(Y(s.price)-11).toFixed(1)}" text-anchor="end" class="ax hl2" style="fill:var(--tx);font-weight:600">₹${f(s.price)}</text>
 ${dot(X(sell),Y(cone[N].m),'var(--ac)')}
 <line id="hv-${s.symbol}" y1="${T}" y2="${Ht-B}" stroke="var(--mu)" stroke-width="1" style="display:none"/><circle id="hd-${s.symbol}" r="5" fill="var(--tx)" stroke="var(--card)" stroke-width="2" style="display:none"/>
 <rect x="${L}" y="${T}" width="${W-L-R}" height="${Ht-T-B}" fill="transparent" class="hit"/></svg>`}

function mountChart(){if(window.PriceChart)document.querySelectorAll('.pc[data-sym]').forEach(h=>PriceChart.mount(h));
 const cw=document.getElementById('cw');if(!cw||!open)return;const s=M(open);if(!s||!s.series)return;
 cw.innerHTML=chart(s,Math.max(300,Math.min(900,Math.round(cw.clientWidth)||600)));chartHover()}

function tipRows(tp,head,rows){tp.textContent='';const h=document.createElement('div');h.className='th';h.textContent=head;tp.appendChild(h);
 rows.forEach(r=>{const d=document.createElement('div'),k=document.createElement('i'),v=document.createElement('b'),l=document.createElement('span');d.className='tr';
  k.style.background=r[2];v.textContent=r[1];l.textContent=r[0];d.append(k,v,l);tp.appendChild(d)})}

function chartHover(){const svg=document.querySelector('svg.ch');if(!svg)return;const sym=svg.dataset.s,m=CM[sym],s=M(sym);if(!m||!s)return;
 const hv=$('hv-'+sym),hd=$('hd-'+sym),tp=$('tp-'+sym),p=m.p;
 const hide=()=>{hv.style.display='none';hd.style.display='none';tp.textContent=''};
 const show=t=>{m.t=t;let x,y,head,rows;
  if(t<=m.last){let k=0,b=1e18;m.S.d.forEach((d,i)=>{const dd=Math.abs(new Date(d).getTime()-t);if(dd<b){b=dd;k=i}});
   x=m.X(new Date(m.S.d[k]).getTime());y=m.Y(m.S.c[k]);head=dt(m.S.d[k],0);hd.setAttribute('fill','var(--tx)');
   rows=[['Price','₹'+f(m.S.c[k]),'var(--tx)'],['50-day average','₹'+f(m.S.s50[k]),'var(--am)'],['200-day average','₹'+f(m.S.s200[k]),'var(--s200)']]}
  else{const fr=Math.min(1,(t-m.last)/(m.sell-m.last)),r2=Math.sqrt(fr),tt=m.last+(m.sell-m.last)*fr,med=m.price*(1+p.p50*r2);
   x=m.X(tt);y=m.Y(med);head=dt(new Date(tt).toISOString().slice(0,10),0)+' (forecast)';hd.setAttribute('fill','var(--ac)');
   rows=[['Typical',`₹${f(med)} (${pc(p.p50*r2)})`,'var(--ac)'],['Likely range',`₹${f(m.price*(1+p.p10*r2))} to ₹${f(m.price*(1+p.p90*r2))}`,'var(--band2)']]}
  hv.setAttribute('x1',x);hv.setAttribute('x2',x);hv.style.display='';hd.setAttribute('cx',x);hd.setAttribute('cy',y);hd.style.display='';
  tipRows(tp,head,rows)};
 svg.onpointermove=e=>{const r=svg.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*m.W;show(m.t0+(x-m.L)/(m.W-m.L-m.R)*(m.t1-m.t0))};
 svg.onpointerleave=hide;svg.onblur=hide;svg.onfocus=()=>show(m.t==null?m.last:m.t);
 svg.onkeydown=e=>{const dir=e.key=='ArrowRight'?1:e.key=='ArrowLeft'?-1:0;
  if(e.key=='Home'){e.preventDefault();return show(m.t0)}if(e.key=='End'){e.preventDefault();return show(m.sell)}
  if(!dir)return;e.preventDefault();const span=m.t<=m.last?864e5*2:(m.sell-m.last)/20;show(Math.max(m.t0,Math.min(m.sell,(m.t==null?m.last:m.t)+dir*span)))}}

function chartTable(s){const K=k0(s),S=s.series,n=S.d.length-K,step=Math.max(1,Math.floor(n/8)),idx=[];for(let i=S.d.length-1;i>=K&&idx.length<9;i-=step)idx.unshift(i);
 const p=s.forecast[hz],last=new Date(S.d[S.d.length-1]).getTime(),sell=new Date(s.sellDates[hz]+'T00:00:00').getTime();
 const hist=idx.map(i=>`<tr><td>${dt(S.d[i],0)}</td><td>₹${f(S.c[i])}</td><td>₹${f(S.s50[i])}</td><td>₹${f(S.s200[i])}</td></tr>`).join('');
 const fc=[.25,.5,.75,1].map(fr=>{const r=Math.sqrt(fr),t=last+(sell-last)*fr;return `<tr><td>${dt(new Date(t).toISOString().slice(0,10),0)}</td><td>₹${f(s.price*(1+p.p50*r))}</td><td>₹${f(s.price*(1+p.p10*r))}</td><td>₹${f(s.price*(1+p.p90*r))}</td></tr>`}).join('');
 return `<details class="more"><summary>Show chart data as a table</summary><table class="mini"><caption class="mu">Price history (sampled)</caption><tr><th>Date</th><th>Price</th><th>50-day</th><th>200-day</th></tr>${hist}</table>
 <table class="mini"><caption class="mu">Forecast over ${hname(hz)}</caption><tr><th>Date</th><th>Typical</th><th>Low</th><th>High</th></tr>${fc}</table></details>`}

window.refreshForecastChart=function(){const sym=pg=='stock'?cur:open,cw=$('cw'),s=sym&&M(sym);if(!cw||!s||!s.series)return;cw.innerHTML=chart(s,Math.max(300,Math.min(900,Math.round(cw.clientWidth)||600)));chartHover();const l=$('leg-my');if(l)l.hidden=!(window.MY_POS&&MY_POS[sym])};
function bindSet(){const b=$('bud'),m=$('ml');if(!b)return;b.value=LIM[0];m.value=LIM[1];b.oninput=m.oninput=size}
function size(){LIM=[+$('bud').value,+$('ml').value];try{localStorage.setItem('lt',JSON.stringify(LIM))}catch(e){}
 if(!D)return;if(pg=='stock'){const X=DET[cur];if(X&&X.series){const c=$('app').querySelector('.dtl');if(c){const t=document.createElement('div');t.innerHTML=detail(M(cur));c.replaceWith(t.firstChild);mountChart()}}}else if($('tb'))table()}

/* ---------- scan data, status line, page lifecycle ---------- */
let PAGE=null,built=false,loadTimer=null,wasRefreshing=false;
function startPage(p){PAGE=p;Shell.setSearchSource(()=>D&&D.stocks);if(window.Mine)Mine.load().catch(()=>{});built=p.needsData===false;   // pages that do not read the scan (portfolio) are built by boot()
 if(p.boot)p.boot();load();unreadBadge()}
function onData(){if(!built){PAGE.build();built=true}PAGE.update()}
function metaErr(msg){const m=$('meta');m.classList.remove('load');m.classList.add('err');m.textContent=msg}
function loadFailed(msg){metaErr(msg);if(!built)$('app').innerHTML=`<div class="card"><div class="card-b">${empty('triangle-alert','Could not load the data',esc(msg),'<button class="btn" id="retry" type="button">Try again</button>')}</div></div>`;const b=$('retry');if(b)b.onclick=()=>{$('meta').className='load';$('meta').innerHTML='<i></i>Loading…';load(false)}}
async function load(force){
 clearTimeout(loadTimer);
 try{const d=await (await fetch('/api/scan'+(force==='full'?'?force=full':force?'?force':''))).json();
 if(d.status==='loading'){$('meta').className='load';$('meta').innerHTML=`<i></i>${d.phase||'Starting'}… ${d.total>1?f(d.done,0)+' of '+f(d.total,0):''} (the first run of the day takes a few minutes)`;return loadTimer=setTimeout(()=>load(false),2000)}
 if(d.status==='error')return loadFailed('Server error: '+d.error);
 D=d;$('rf').classList.toggle('spin',!!d.refreshing);
 const pr=d.progress&&d.progress.total>1?` ${d.progress.phase}: ${f(d.progress.done,0)} of ${f(d.progress.total,0)}.`:'';
 $('meta').className=d.refreshing?'load':'';$('meta').textContent=`Prices as of ${dt(D.stocks[0].asof)}. Plan dates start ${dt(D.buyDate)}. Scanned ${D.generated}, refreshed daily at 11 pm IST.${d.refreshing?' Refreshing in the background…'+pr:''}`;
 if(d.upToDate){const u=document.createElement('span');u.textContent=' Already up to date: these are the prices from the last market close, and nothing newer exists yet. ';
  const b=document.createElement('button');b.type='button';b.className='chip';b.textContent='Re-download anyway';
  b.onclick=()=>{$('rf').classList.add('spin');$('meta').className='load';$('meta').innerHTML='<i></i>Re-downloading…';load('full')};u.appendChild(b);$('meta').appendChild(u)}
 if(d.staleSince||d.refreshError){const w=document.createElement('b');w.className='dn';w.textContent=' '+(d.staleSince?`Data may be old: the newest prices are older than ${dt(d.staleSince,0)}.`:'')+(d.refreshError?` Last refresh failed (${d.refreshError}), showing the previous scan.`:'');$('meta').appendChild(w)}
 onData();
 if(wasRefreshing&&!d.refreshing)document.dispatchEvent(new Event('scan:updated'));   // a scan finished: pages that read prices on their own (portfolio) reload
 wasRefreshing=!!d.refreshing;
 if(d.refreshing)loadTimer=setTimeout(()=>load(false),3000)}
 catch(e){$('rf').classList.remove('spin');loadFailed('Could not load data: '+e+'. Check that the server is running, then select Refresh data.')}}
$('rf').onclick=()=>{$('rf').classList.add('spin');$('meta').className='load';$('meta').innerHTML='<i></i>Refreshing…';load(true)};
// unread alert count on the Portfolio nav item (same endpoint the portfolio page uses)
function unreadBadge(){Session.fetch('/api/me',{credentials:'same-origin'}).then(r=>/json/i.test(r.headers.get('content-type')||'')?r.json().then(j=>({ok:r.ok,j})):null).then(x=>{if(x&&x.ok&&Array.isArray(x.j.holdings))Shell.setBadge('portfolio',Number(x.j.unread)||0)}).catch(()=>{})}
let rz;addEventListener('resize',()=>{clearTimeout(rz);rz=setTimeout(()=>{const cw=$('cw'),m=open&&CM[open];if(cw&&(!m||Math.abs(cw.clientWidth-m.W)>8))mountChart()},150)});

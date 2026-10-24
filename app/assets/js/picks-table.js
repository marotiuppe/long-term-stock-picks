/* The sortable, filterable, paginated stock table and everything around it (CSV export, list import), shared by the
   Home, NSE stocks, ETFs and BSE pages. Each of those pages calls listPage({...}) once. Needs common.js. */
let flt='BUY',exf='ALL',sortK=null,sortD=1,q='',pn=0,psz=25,jump=false,dense=false;
try{const v=+localStorage.getItem('psz');if([25,50,100].includes(v))psz=v;dense=localStorage.getItem('dense')=='1'}catch(e){}
const EXL=[['ALL','All'],['NSE','NSE'],['BSE','BSE'],['ETF','ETFs']];
const pool=()=>pg=='etfs'?D.stocks.filter(s=>s.etf):pg=='bse'?D.stocks.filter(s=>s.exchange=='BSE'):pg=='home'?D.stocks.filter(s=>exf=='ALL'||kindOf(s)==exf):D.stocks.filter(s=>s.exchange!='BSE');
function chips(){const P=pool(),c=P.reduce((a,s)=>(a[s.verdict]=(a[s.verdict]||0)+1,a),{});
 if($('exch')){const n=D.stocks.reduce((a,s)=>(a[kindOf(s)]=(a[kindOf(s)]||0)+1,a),{});
  $('exch').innerHTML=EXL.map(e=>`<button class="chip ${e[0]==exf?'on':''}" data-x="${e[0]}" aria-pressed="${e[0]==exf}">${e[1]} ${f(e[0]=='ALL'?D.stocks.length:n[e[0]]||0,0)}</button>`).join('')+'<span class="sep" aria-hidden="true"></span>';
  document.querySelectorAll('.chip[data-x]').forEach(b=>b.onclick=()=>{exf=b.dataset.x;open=null;pn=0;chips();table()})}
 $('chips').innerHTML=['ALL','BUY','WAIT','WATCH','DOWNTREND'].map(k=>`<button class="chip ${k==flt?'on':''}" data-k="${k}" aria-pressed="${k==flt}">${k==='ALL'?'All '+P.length:VL[k]+' '+(c[k]||0)}</button>`).join('');
 document.querySelectorAll('.chip[data-k]').forEach(b=>b.onclick=()=>{flt=b.dataset.k;open=null;pn=0;chips();table()})}
const SORTS={nm:(a,b)=>a.symbol.localeCompare(b.symbol),vd:byRank,pr:(a,b)=>a.price-b.price,
 ob:(a,b)=>a.forecast[hz].p10-b.forecast[hz].p10,ty:(a,b)=>a.forecast[hz].p50-b.forecast[hz].p50,
 g:(a,b)=>a.forecast[hz].pgain-b.forecast[hz].pgain,s:(a,b)=>a.stopPct-b.stopPct};
const SORT_FIRST={nm:1,vd:1};   // text and call sort A to Z / best first on the first click, numbers largest first
function list(){const t=q.trim().toLowerCase();return pool().filter(s=>s.forecast[hz]&&(flt=='ALL'||s.verdict==flt)&&(!t||s.symbol.toLowerCase().includes(t)||(s.name||'').toLowerCase().includes(t)))
 .sort(sortK?(a,b)=>sortD*SORTS[sortK](a,b)||byRank(a,b):byRank)}
function pickSort(k){if(sortK!=k){sortK=k;sortD=SORT_FIRST[k]?1:-1}else if(sortD==(SORT_FIRST[k]?1:-1))sortD=-sortD;else sortK=null;
 open=null;pn=0;table();const b=document.querySelector(`th[data-k="${k}"] .sb`);if(b)b.focus()}
function thead(){const C=[['nm','Stock',''],['vd','Call','','call'],['pr','Price','pr'],['ob',`Likely range over ${hname(hz)}`,'ob','likely-range'],['ty','Typical','ty','typical'],['g','Chance of gain','hd','chance-of-gain'],['s','Stop-loss','hd','stop-loss']];
 return '<tr class="hr">'+C.map(c=>`<th class="${c[2]}" data-k="${c[0]}" aria-sort="${sortK==c[0]?(sortD>0?'ascending':'descending'):'none'}"><button class="sb" type="button" title="Sort by ${c[1].toLowerCase()}">${c[3]?`<span data-term="${c[3]}">${c[1]}</span>`:c[1]}<span class="ar">${ic(sortK==c[0]?(sortD>0?'arrow-up':'arrow-down'):'chevrons-up-down')}</span></button></th>`).join('')+'</tr>'}
/*csv*/
const csvCell=v=>{v=v==null?'':String(v);if(/^[=+\-@\t\r]/.test(v)&&isNaN(v))v="'"+v;return /[",\n]/.test(v)||v!==v.trim()?'"'+v.replace(/"/g,'""')+'"':v};
function toCsv(L){const r2=n=>Math.round(n*100)/100,pct=n=>r2(n*100),h=hname(hz);
 const head=['Symbol','Name','Call','Price (₹)','Stop-loss (₹)','Stop-loss (%)',`Typical gain over ${h} (%)`,'Likely low, p10 (%)','Likely high, p90 (%)','Chance of gain (%)','Buy date','Sell or review date','Exchange'];
 const rows=L.map(s=>{const p=s.forecast[hz];return [s.symbol,s.name||'',VL[s.verdict],r2(s.price),r2(s.stop),pct(-s.stopPct),pct(p.p50),pct(p.p10),pct(p.p90),Math.round(p.pgain*100),s.verdict=='BUY'?D.buyDate:'',D.sellDates[hz],s.etf?'ETF':s.exchange||'NSE']});
 return '\ufeff'+[head,...rows].map(r=>r.map(csvCell).join(',')).join('\r\n')+'\r\n'}
function downloadCsv(){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([toCsv(list())],{type:'text/csv;charset=utf-8'}));a.download=`${pg=='etfs'?'etf':'stock'}-picks-${hz}-${flt.toLowerCase()}-${D.today}.csv`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
/*endcsv*/
/*imp*/
const nk=s=>String(s==null?'':s).toLowerCase().replace(/[^a-z0-9]/g,'');
const SYMOK=/^[A-Z0-9&-]{1,20}$/,CODEOK=/^[0-9]{5,6}$/,CTRL=/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/g;
const IMPF={
 etf:{symbol:['symbol','tradingsymbol','scripsymbol','securitysymbol'],name:['securityname','name','schemename','fundname','companyname','nameofcompany'],underlying:['underlying','underlyingasset','underlyingindex','underlyingindexasset','benchmark','benchmarkindex'],issuer:['issuer','issuername','amc','fundhouse']},
 bse:{code:['securitycode','sccode','scripcode','scripcd','fininstrmid'],symbol:['securityid','scid','scripid','symbol','tckrsymb','scripsymbol'],name:['securityname','scname','scripname','issuername','companyname','fininstrmnm','name'],group:['group','scgroup','sctysrs'],type:['type','sctype','securitytype','instrument'],status:['status','scstatus']}};
const BSE_EQ_GROUPS=['A','B','T','X','XT','Z','ZP','M','MT','P','R','S'],BSE_EQ_TYPES=['Q','EQ','EQUITY','EQUITIES'];
function parseCsv(text){text=String(text||'').replace(/^﻿/,'');
 const first=text.split(/\r?\n/).filter(l=>l.trim()).slice(0,10).join('\n'),cnt=c=>first.split(c).length-1;
 let dl=',',best=cnt(',');for(const c of ['\t',';','|'])if(cnt(c)>best){best=cnt(c);dl=c}
 const rows=[];let row=[],cell='',inq=false;
 for(let i=0;i<text.length;i++){const c=text[i];
  if(inq){if(c=='"'){if(text[i+1]=='"'){cell+='"';i++}else inq=false}else cell+=c}
  else if(c=='"'&&cell==='')inq=true;
  else if(c==dl){row.push(cell);cell=''}
  else if(c=='\n'||c=='\r'){if(c=='\r'&&text[i+1]=='\n')i++;row.push(cell);cell='';rows.push(row);row=[]}
  else cell+=c}
 if(cell!==''||row.length){row.push(cell);rows.push(row)}
 return rows.filter(r=>r.some(x=>x.trim()!==''))}
function detect(hdr,kind){const h=hdr.map(nk),used=new Set(),m={};
 for(const [f,c] of Object.entries(IMPF[kind])){m[f]=-1;for(const k of c){const i=h.findIndex((x,j)=>x==k&&!used.has(j));if(i>=0){m[f]=i;used.add(i);break}}}
 return m}
function findHeader(t,kind){for(let i=0;i<Math.min(10,t.length);i++){const m=detect(t[i],kind);if(m.symbol>=0||m.code>=0)return i}return 0}
function buildRows(t,hi,map,kind,all){const out=[],skip={},seen=new Set(),sk=r=>{skip[r]=(skip[r]||0)+1};
 const body=t.slice(hi+1),g=(r,k)=>map[k]>=0&&map[k]!=null&&r[map[k]]!=null?String(r[map[k]]).replace(CTRL,' ').trim():'';
 for(const r of body){let sym=g(r,'symbol').toUpperCase(),code=kind=='bse'?g(r,'code'):'';
  if(kind=='bse'&&!all){
   if(map.status>=0&&!/^active$/i.test(g(r,'status'))){sk('not active');continue}
   if(map.type>=0&&!BSE_EQ_TYPES.includes(g(r,'type').toUpperCase())){sk('not equity');continue}
   if(map.group>=0&&!BSE_EQ_GROUPS.includes(g(r,'group').toUpperCase())){sk('not equity');continue}}
  if(code&&!CODEOK.test(code)){sk('bad code');continue}
  if(code&&!SYMOK.test(sym))sym=code;
  if(!sym&&code)sym=code;
  if(!sym){sk('blank symbol');continue}
  if(!SYMOK.test(sym)){sk('invalid symbol');continue}
  const key=code||sym;if(seen.has(key)){sk('duplicate');continue}seen.add(key);
  const o={symbol:sym,name:g(r,'name').slice(0,120)};
  if(code)o.code=code;
  if(kind=='etf'){const u=g(r,'underlying').slice(0,120),i=g(r,'issuer').slice(0,120);if(u)o.underlying=u;if(i)o.issuer=i}
  out.push(o)}
 return{rows:out,skipped:skip,total:body.length}}
/*endimp*/
const SKL={'not active':'status not active','not equity':'group or type not equity','bad code':'security code not 5 or 6 digits','blank symbol':'no symbol','invalid symbol':'unusual characters in symbol','duplicate':'duplicate'};
const FLD={etf:[['symbol','Symbol'],['name','Name'],['underlying','Underlying'],['issuer','Issuer']],bse:[['code','Security code'],['symbol','Security id / symbol'],['name','Security name'],['group','Group'],['type','Type'],['status','Status']]};
let IMP={},IM=null;
const imKind=()=>pg=='etfs'?'etf':'bse';
function importBox(kind){const etf=kind=='etf';
 return `<section class="card imp" aria-labelledby="imph"><h2 id="imph">Import ${etf?'an ETF list':'a BSE list'}</h2>
 <p class="mu">${etf?'Download the ETF list from the NSE website yourself, in your browser, then pick the CSV here.':'Download the scrip list or the daily bhavcopy from the BSE website yourself, in your browser, then pick the CSV here.'} The file is read inside this page and is never uploaded. Only the cleaned rows (symbol, name and a few labels) are saved on this computer. This app never fetches anything from the exchange websites. Prices for imported symbols come from Yahoo Finance. Personal use only.</p>
 <p class="ack">Source: file you downloaded from the exchange website, for personal, non-commercial use. Not redistributed.</p>
 <div class="row"><div><label for="imf">CSV file</label><input id="imf" type="file" accept=".csv,text/csv"></div></div>
 <label for="imt">Or paste the CSV text</label><textarea id="imt" spellcheck="false" placeholder="${etf?'Symbol,Name,Underlying,Issuer':'Security Code,Security Id,Security Name,Group'}"></textarea>
 <div class="row"><button class="btn" id="imr" type="button">Read pasted text</button></div>
 <div id="imm" aria-live="polite"></div><div id="imst" class="msg" role="status"></div><div id="imcur" class="msg mu"></div></section>`}
function imCur(){const el=$('imcur');if(!el)return;const k=imKind(),s=IMP[k];
 if(!s){el.textContent='Nothing stored yet.';return}
 el.innerHTML=`Stored: ${f(s.count,0)} rows, imported ${esc(new Date(s.importedAt).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'}))}. <button class="chip" id="imx" type="button">Clear stored list</button>`;
 $('imx').onclick=async()=>{try{const r=await fetch('/api/import/list?kind='+k,{method:'DELETE'});if(!r.ok)throw new Error((await r.json()).error||r.status);
  await impLoad();$('imst').textContent='Stored list cleared. Re-scanning without it…';load(false)}catch(e){$('imst').innerHTML='<span class="dn">Could not clear: '+esc(e.message)+'</span>'}}}
async function impLoad(){try{const r=await fetch('/api/import/list');if(r.ok)IMP=await r.json()}catch(e){}
 imCur();if(D&&$('tb'))table()}
function bseEmpty(){const s=IMP.bse;return s?`None of the ${f(s.count,0)} imported BSE rows is in the scan. Rows whose symbol is already on NSE are left out, and the rest must pass the same quality checks. If you just imported, wait for the refresh to finish.`:'No BSE-only stocks passed the quality checks in the last scan. They load automatically from the exchange file, so check that the scan finished or try Refresh.'}
function imRead(text){const kind=imKind(),t=parseCsv(text);
 if(t.length<2){IM=null;$('imm').innerHTML='<p class="msg dn">No rows found. Use a CSV file with a header line.</p>';return}
 const h=findHeader(t,kind);IM={kind,t,h,map:detect(t[h],kind),all:false};imRender()}
function imRender(){const a=document.activeElement,keep=a&&a.id&&$('imm').contains(a)?a.id:null,{kind,t,h,map}=IM,hd=t[h],R=buildRows(t,h,map,kind,IM.all),ok=R.rows.length,skipped=R.total-ok;
 const sel=FLD[kind].map(([k,l])=>`<div><label for="imc-${k}">${l}</label><select id="imc-${k}" data-f="${k}"><option value="-1">(none)</option>${hd.map((x,i)=>`<option value="${i}"${map[k]==i?' selected':''}>${esc(x.trim()||'column '+(i+1))}</option>`).join('')}</select></div>`).join('');
 const why=Object.entries(R.skipped).map(([k,n])=>`${f(n,0)} ${SKL[k]||k}`).join(', ');
 const noSym=kind=='bse'?(map.symbol<0&&map.code<0):map.symbol<0,tooMany=ok>5000,blocked=noSym||!ok||tooMany;
 const filt=kind=='bse'&&(map.group>=0||map.type>=0||map.status>=0);
 const cols=kind=='bse'?['symbol','code','name']:['symbol','name','underlying'];
 const pv=R.rows.slice(0,10).map(r=>`<tr>${cols.map(c=>`<td>${esc(r[c]||'')}</td>`).join('')}</tr>`).join('');
 $('imm').innerHTML=`<h3 style="margin:14px 0 4px;font-size:15px">Check the columns</h3><div class="row">${sel}</div>
 ${filt?`<label class="ck"><input type="checkbox" id="ima"${IM.all?' checked':''}> Include all rows (do not keep only equity rows that are active)</label>`:(kind=='bse'?'<p class="mu">No group, type or status column found, so every row is kept.</p>':'')}
 <p class="msg">Read ${f(R.total,0)} rows: ${f(ok,0)} kept${skipped?`, ${f(skipped,0)} skipped (${esc(why)})`:''}.${tooMany?' <b class="dn">Too many rows: at most 5,000 can be saved.</b>':''}${noSym?' <b class="dn">Pick the symbol column to continue.</b>':''}</p>
 ${ok?`<div class="pv"><table><caption class="mu" style="text-align:left">Preview, first ${Math.min(10,ok)} of ${f(ok,0)} rows</caption><tr>${cols.map(c=>`<th>${c=='code'?'Code':c[0].toUpperCase()+c.slice(1)}</th>`).join('')}</tr>${pv}</table></div>`:''}
 <div class="row"><button class="btn pri" id="imsave" type="button"${blocked?' disabled':''}>Save ${f(ok,0)} rows</button></div>`;
 $('imm').querySelectorAll('select[data-f]').forEach(s=>s.onchange=()=>{IM.map[s.dataset.f]=+s.value;imRender()});
 if($('ima'))$('ima').onchange=e=>{IM.all=e.target.checked;imRender()};
 $('imsave').onclick=imSave;if(keep&&$(keep))$(keep).focus()}
async function imSave(){if(!IM)return;const R=buildRows(IM.t,IM.h,IM.map,IM.kind,IM.all);$('imst').textContent='Saving…';
 try{const r=await fetch('/api/import/list',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:IM.kind,rows:R.rows})}),j=await r.json();
  if(!r.ok)throw new Error(j.error||r.status);
  IM=null;$('imm').innerHTML='';await impLoad();
  $('imst').textContent=`Saved ${f(j.count,0)} rows.${Object.keys(j.skipped||{}).length?' The server also skipped '+Object.entries(j.skipped).map(([k,n])=>n+' '+k.replace('_',' ')).join(', ')+'.':''} Re-scanning to include them (cached prices are reused)…`;load(false)}
 catch(e){$('imst').innerHTML='<span class="dn">Not saved: '+esc(e.message)+'</span>'}}
function impBind(){IM=null;$('imf').onchange=async e=>{const fl=e.target.files[0];if(!fl)return;
  if(fl.size>5e6){$('imm').innerHTML='<p class="msg dn">That file is over 5 MB. Use the list file, not a full data archive.</p>';return}
  try{imRead(await fl.text())}catch(x){$('imm').innerHTML='<p class="msg dn">Could not read that file.</p>'}};
 $('imr').onclick=()=>imRead($('imt').value);impLoad()}
function openStock(sym){open=open==sym?null:sym;table();if(open)fetchDet(open)}
function bar(p,lo,hi){const X=v=>(v-lo)/(hi-lo)*100;
 return `<div class="rb" role="img" aria-label="Likely range ${pc(p.p10)} to ${pc(p.p90)}, typical ${pc(p.p50)}"><i class="z" style="left:${X(0).toFixed(1)}%"></i><i class="rg" style="left:${X(p.p10).toFixed(1)}%;width:${(X(p.p90)-X(p.p10)).toFixed(1)}%"></i><i class="md" style="left:${X(p.p50).toFixed(1)}%"></i></div><div class="rt">${pc(p.p10,0)} to ${pc(p.p90,0)}</div>`}
function table(){const L0=list(),all=L0.length,pages=Math.max(1,Math.ceil(all/psz)),what=pg=='etfs'?'ETFs':pg=='bse'?'BSE stocks':pg=='home'?({NSE:'NSE stocks',BSE:'BSE stocks',ETF:'ETFs'}[exf]||'stocks and ETFs'):'stocks';if(jump&&open){const i=L0.findIndex(s=>s.symbol==open);if(i>=0)pn=Math.floor(i/psz)}jump=false;pn=Math.max(0,Math.min(pn,pages-1));const L=L0.slice(pn*psz,pn*psz+psz);
 if($('cnt'))$('cnt').textContent=all?`Showing ${f(pn*psz+1,0)} to ${f(pn*psz+L.length,0)} of ${f(all,0)} ${what}. Select a row for the chart, plan and news. Select a column heading to sort.`:'';
 const lo=L.length?Math.min(0,...L.map(s=>s.forecast[hz].p10)):-.1,hi=L.length?Math.max(0,...L.map(s=>s.forecast[hz].p90)):.1,sp=Math.max(hi-lo,1e-6);
 $('tb').innerHTML=thead()+
 L.map(s=>{const p=s.forecast[hz];
  const pln=s.verdict=='BUY'?`<span class="up">Buy ${ds(D.buyDate)}, sell ${ds(D.sellDates[hz])}${hb(D.sellDates[hz])}</span>`:s.verdict=='WAIT'?`<span class="mu">Buy near ₹${f(s.sma20)}</span>`:'';
  return `<tr class="r" data-s="${s.symbol}" tabindex="0" role="button" aria-expanded="${open==s.symbol}"><td class="nm"><b>${esc(s.symbol)}</b>${heldTag(s.symbol)}${pg=='home'&&kindOf(s)=='NSE'?'<span class="etf">NSE</span>':''}${s.etf?'<span class="etf">ETF</span>':''}${s.exchange=='BSE'?'<span class="etf">BSE</span>':''}<div class="sub">${esc(s.name||'')}${s.underlying?' · '+esc(s.underlying):''}</div>${window.Why&&Why.line&&Why.line(s)?`<div class="wl">${esc(Why.line(s))}</div>`:''}${qadd(s,'d')}<span class="mp">₹${f(s.price)}</span>${pln?`<div class="pln">${pln}</div>`:''}</td>
  <td><span class="vd ${s.verdict}">${VL[s.verdict]}</span><span class="mt">${pcc(p.p50)}</span>${qadd(s,'m')}</td><td class="pr">₹${f(s.price)}</td><td class="ob">${bar(p,lo-sp*.03,hi+sp*.03)}</td><td class="ty">${pcc(p.p50)}</td><td class="hd">${f(p.pgain*100,0)}%</td><td class="hd">₹${f(s.stop)} <span class="mu">(−${f(s.stopPct*100,0)}%)</span></td></tr>`+
  (open==s.symbol?`<tr class="d"><td colspan="7">${M(s.symbol)&&M(s.symbol).series?detail(M(s.symbol)):'<div class="load"><i></i>Loading chart…</div>'}</td></tr>`:'')}).join('')||`<tr><td colspan="7" class="empty-c">${empty('inbox','Nothing to show',pg=='etfs'&&!pool().length?'No ETFs passed the quality checks in the last scan.':pg=='bse'&&!pool().length?bseEmpty():'No stocks match. Pick another call above or clear the search.'  )}</td></tr>`;
 pager(all,pages);
 document.querySelectorAll('.qadd').forEach(b=>{b.onclick=e=>{e.stopPropagation();Holdings.openLotForm({symbol:b.dataset.q,name:b.dataset.n,price:+b.dataset.p,side:'buy'})};b.onkeydown=e=>e.stopPropagation()});
 const act=sym=>Shell.isMobile()?location.href='/stock.html?symbol='+encodeURIComponent(sym):openStock(sym);   // on a phone a row opens the stock's own page
 document.querySelectorAll('th[data-k] .sb').forEach(b=>b.onclick=()=>pickSort(b.closest('th').dataset.k));
 document.querySelectorAll('tr.r').forEach(r=>{r.onclick=()=>act(r.dataset.s);r.onkeydown=e=>{if(e.key=='Enter'||e.key==' '){e.preventDefault();act(r.dataset.s)}}});
 mountChart()}

const heldTag=sym=>window.Mine&&Mine.pos[sym]?`<span class="heldtag" title="You hold ${Mine.pos[sym].qty} share${Mine.pos[sym].qty==1?'':'s'}">Held</span>`:'';
const qadd=(s,where)=>window.Holdings?`<button type="button" class="qadd ${where}" data-q="${esc(s.symbol)}" data-n="${esc(s.name||'')}" data-p="${s.price}" aria-label="${Mine.pos[s.symbol]?'Add more shares of':'Add'} ${esc(s.symbol)} ${Mine.pos[s.symbol]?'':'to my holdings'}" title="${Mine.pos[s.symbol]?'Add more shares':'Add to my holdings'}">${ic('plus','sm')}</button>`:'';
function pager(all,pages){const el=$('pgn');if(!el)return;if(!all){el.innerHTML='';return}
 const a=pn*psz+1,b=Math.min(all,(pn+1)*psz);
 el.innerHTML=`<label class="pgn-r">Rows per page <select id="psz">${[25,50,100].map(n=>`<option${n==psz?' selected':''}>${n}</option>`).join('')}</select></label>
 <div class="pgn-r"><span class="pgn-n" aria-live="polite">${f(a,0)} to ${f(b,0)} of ${f(all,0)}</span><button class="btn" id="pp" type="button" aria-label="Previous page"${pn?'':' disabled'}>${ic('chevron-left','sm')}</button><button class="btn" id="pnx" type="button" aria-label="Next page"${pn<pages-1?'':' disabled'}>${ic('chevron-right','sm')}</button></div>`;
 $('psz').onchange=e=>{psz=+e.target.value;pn=0;open=null;try{localStorage.setItem('psz',psz)}catch(x){}table()};
 const go=d=>{pn+=d;open=null;table();const w=$('cnt');if(w)w.scrollIntoView({block:'nearest'})};
 $('pp').onclick=()=>go(-1);$('pnx').onclick=()=>go(1)}

/* ---------- KPI tiles and side cards for list pages ---------- */
function listKpis(){const el=$('kpis');if(!el)return;if(pg=='home'&&window.holdingsKpis&&window.Mine&&Mine.has()){el.innerHTML=holdingsKpis();return}const P=pool().filter(s=>s.forecast[hz]),B=P.filter(s=>s.verdict=='BUY').sort(byRank),top=B[0],h=hname(hz),tp=top&&top.forecast[hz];
 const med=P.length?P.map(s=>s.forecast[hz].p50).sort((a,b)=>a-b)[P.length>>1]:null;
 el.innerHTML=kpi('list','Scored here',f(P.length,0),'liquid names that passed the checks')
  +kpi('circle-check','Buy calls',f(B.length,0),P.length?`${f(B.length/P.length*100,0)}% of this list`:'')
  +kpi('star','Top pick',top?`<a href="/stock.html?symbol=${encodeURIComponent(top.symbol)}">${esc(top.symbol)}</a>`:'None',top?`${arrow(tp.p50)} ${pc(tp.p50)} typical over ${h}`:'No Buy calls right now')
  +kpi('percent','Median outcome',med==null?'-':pc(med),`typical, across this list over ${h}`)}
function mixCard(){const el=$('mix');if(!el)return;const P=pool(),c=P.reduce((a,s)=>(a[s.verdict]=(a[s.verdict]||0)+1,a),{}),n=P.length||1,ks=['BUY','WAIT','WATCH','DOWNTREND'];
 el.innerHTML=`<div class="card-h"><div><h2>Calls across this list</h2><p>How the ${f(P.length,0)} scored names split by call.</p></div></div>
 <div class="card-b"><div class="dist" role="img" aria-label="${ks.map(k=>VL[k]+' '+(c[k]||0)).join(', ')}">${ks.map(k=>c[k]?`<i class="${k}" style="flex:${c[k]}"></i>`:'').join('')}</div>
 <ul class="dist-l">${ks.map(k=>`<li><i class="sw ${k}"></i><span>${VL[k]}</span><b>${f(c[k]||0,0)}</b><span class="mu">${f((c[k]||0)/n*100,0)}%</span></li>`).join('')}</ul></div>`}
function topCard(){const el=$('top');if(!el)return;const B=pool().filter(s=>s.forecast[hz]&&s.verdict=='BUY').sort(byRank).slice(0,5);
 el.innerHTML=`<div class="card-h"><div><h2>Top picks</h2><p>Best-ranked Buy calls over ${hname(hz)}.</p></div></div><div class="card-b">${B.length?'<ol class="rank">'+B.map(s=>{const p=s.forecast[hz];return `<li><div class="nm2"><a href="/stock.html?symbol=${encodeURIComponent(s.symbol)}">${esc(s.symbol)}</a><div>${esc(s.name||'')}</div></div><div class="vv">${pcc(p.p50)}<div>${pc(p.p10,0)} to ${pc(p.p90,0)}</div></div></li>`}).join('')+'</ol>':empty('inbox','No Buy calls right now','Nothing passes every check today. That is a normal result.')}</div>`}

/* ---------- page assembly ---------- */
const TBL='<div class="cnt" id="cnt" aria-live="polite"></div><div class="tw"><table id="tb"></table></div><div class="pgn" id="pgn"></div>';
const BAR=ex=>`<div class="bar"><div class="chiprow">${ex?'<span id="exch" role="group" aria-label="Filter by exchange"></span>':''}<span id="chips" role="group" aria-label="Filter by call"></span></div><span class="grow"></span><input id="q" type="search" aria-label="Search symbol or company" placeholder="Search symbol or company"><button class="ibtn fbtn" id="fbtn" type="button" aria-label="Sort and rows" aria-haspopup="dialog">${ic('sliders')}<span class="fbl">Sort</span></button><button class="chip" id="dn" type="button" aria-pressed="false">Compact rows</button></div>`;
let flt0='BUY';
/* Phone: sorting (the column headings are gone) and rows per page live in a bottom sheet. */
function openFilters(){
 const SO=[['','Best call first'],['nm','Symbol, A to Z'],['pr','Price'],['ty','Typical outcome'],['g','Chance of gain'],['ob','Likely low end'],['s','Stop-loss']];
 Shell.sheet({title:'Sort and rows',html:`<div class="sort-sheet"><label for="fs">Sort by</label><select id="fs">${SO.map(o=>`<option value="${o[0]}"${(sortK||'')==o[0]?' selected':''}>${o[1]}</option>`).join('')}</select>
  <label id="fol">Order</label><div class="seg" role="group" aria-labelledby="fol"><button class="tab ${sortD>0?'on':''}" type="button" data-d="1" aria-pressed="${sortD>0}">Ascending</button><button class="tab ${sortD<0?'on':''}" type="button" data-d="-1" aria-pressed="${sortD<0}">Descending</button></div>
  <label for="fp">Rows per page</label><select id="fp">${[25,50,100].map(n=>`<option${n==psz?' selected':''}>${n}</option>`).join('')}</select>
  <div class="row2"><button class="btn" id="fr" type="button">Reset</button><button class="btn pri" id="fd" type="button">Done</button></div></div>`,
  onOpen:(b,api)=>{const $b=id=>b.querySelector('#'+id),seg=()=>b.querySelectorAll('.seg .tab').forEach(t=>{const on=+t.dataset.d==sortD;t.classList.toggle('on',on);t.setAttribute('aria-pressed',on)}),redo=()=>{pn=0;open=null;table()};
   $b('fs').onchange=e=>{const k=e.target.value;if(k==''){sortK=null}else{sortK=k;sortD=SORT_FIRST[k]?1:-1}seg();redo()};
   b.querySelectorAll('.seg .tab').forEach(t=>t.onclick=()=>{sortD=+t.dataset.d;seg();if(sortK)redo()});
   $b('fp').onchange=e=>{psz=+e.target.value;try{localStorage.setItem('psz',psz)}catch(x){}redo()};
   $b('fr').onclick=()=>{flt=flt0;exf='ALL';sortK=null;sortD=1;q='';if($('q'))$('q').value='';chips();redo();api.close()};
   $b('fd').onclick=()=>api.close()}})}
/* c: {h1, sub, table, tdesc, home, sizing, imp}. */
function listPage(c){
 startPage({
  boot(){$('app').innerHTML=ph(c.h1,c.sub)+SK},
  build(){open=null;q='';pn=0;exf='ALL';sortK=null;flt=flt0=c.home||pg=='etfs'||pg=='bse'?'ALL':'BUY';
   const side=c.home?`<section class="card" id="alloc"></section>`:`<section class="card"><div class="card-h"><div><h2>Position sizing</h2><p>Your limits set the share counts in every plan.</p></div></div>${SET}</section>`;
   const lead=c.home?`<section class="card" id="rel" aria-live="polite"></section>`:`<section class="card" id="mix"></section>`;
   const tcard=`<section class="card" aria-labelledby="th2"><div class="card-h"><div><h2 id="th2">${c.table}</h2><p>${c.tdesc}</p></div></div>${BAR(c.home)}${TBL}</section>`;
   /* Home: the working list (track record, then the table) on the left; what to act on (top picks, attention, allocation) on the right. */
   const body=c.home?`<div class="home-cols"><div class="hc-main">${lead}${tcard}</div><div class="hc-side"><section class="card" id="top"></section><section class="card" id="attn"></section>${side}</div></div>`
    :`<div class="home-cols"><div class="hc-main">${tcard}</div><div class="hc-side">${lead}${side}</div></div>`;
   $('app').innerHTML=ph(c.h1,c.sub,'<button class="btn" id="csv" type="button" aria-label="Download CSV">'+ic('download','sm')+'<span class="txt">Download CSV</span></button>',TABS)
    +'<div class="kpis" id="kpis"></div>'
    +body
    +(c.imp?importBox(c.imp):'');
   if(pg=='stocks'){const m=location.hash.match(/open=([^&]+)/);if(m){try{open=decodeURIComponent(m[1])}catch(e){}flt='ALL';jump=true}}
   bindSet();
   $('q').oninput=e=>{q=e.target.value;pn=0;if(D)table()};
   $('csv').onclick=()=>{if(D)downloadCsv()};
   $('fbtn').onclick=openFilters;
   const dn=$('dn');dn.setAttribute('aria-pressed',dense);dn.classList.toggle('on',dense);$('tb').closest('.tw').classList.toggle('dense',dense);
   dn.onclick=()=>{dense=!dense;try{localStorage.setItem('dense',dense?'1':'0')}catch(e){}dn.setAttribute('aria-pressed',dense);dn.classList.toggle('on',dense);$('tb').closest('.tw').classList.toggle('dense',dense)};
   if(c.imp)impBind();
   if(c.home&&window.Attention)Attention.mountFeed($('attn'));
   if(!window.__mineBound){window.__mineBound=1;document.addEventListener('mine:update',()=>{if(D&&$('tb')){listKpis();table();if(window.renderAlloc)renderAlloc()}})}},
  update(){tabs();if(c.home){rel();if(window.renderAlloc)renderAlloc()}listKpis();mixCard();topCard();chips();table();if(open&&!DET[open])fetchDet(open)}
 })}

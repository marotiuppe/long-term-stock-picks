/* Share menu for the stock page: Copy link, Share (when the browser has it), Print / Save as PDF. Share.mount(host, symbol, {stock}) is idempotent. Shares a link only, never price or advice text. */
(function(root){
const link=(origin,sym)=>String(origin||'').replace(/\/+$/,'')+'/stock/'+encodeURIComponent(String(sym||'').trim().toUpperCase());
const title=sym=>String(sym||'').trim().toUpperCase()+' on Long-Term Stock Picks';
const api={link,title};root.Share=api;
if(typeof module!='undefined'&&module.exports)module.exports=api;
if(typeof document=='undefined')return;
const E=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ico=(n,p)=>`<svg class="ic sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${p}</svg>`;
const I={share:'<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/>',
 copy:'<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
 print:'<path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>'};
let toastT=0;
function say(msg){let l=document.getElementById('share-live');if(!l){l=document.createElement('div');l.id='share-live';l.className='sr';l.setAttribute('role','status');l.setAttribute('aria-live','polite');document.body.appendChild(l)}
 l.textContent='';setTimeout(()=>{l.textContent=msg},30);
 let t=document.getElementById('share-toast');if(!t){t=document.createElement('div');t.id='share-toast';t.className='share-toast';t.setAttribute('aria-hidden','true');document.body.appendChild(t)}
 t.textContent=msg;t.classList.add('on');clearTimeout(toastT);toastT=setTimeout(()=>t.classList.remove('on'),2200)}
function copyText(txt){
 const fb=()=>{const a=document.createElement('textarea');a.value=txt;a.setAttribute('readonly','');a.style.cssText='position:fixed;left:-9999px;top:0;opacity:0';document.body.appendChild(a);a.select();let ok=false;try{ok=document.execCommand('copy')}catch(_){}a.remove();return ok};
 if(navigator.clipboard&&navigator.clipboard.writeText&&window.isSecureContext)return navigator.clipboard.writeText(txt).then(()=>true,()=>fb());
 return Promise.resolve(fb())}
function mount(host,sym){if(!host||!sym)return;sym=String(sym).toUpperCase();
 const url=link(location.origin,sym),can=!!navigator.share;
 /* print-only footer, kept outside the host so re-renders of the header cannot lose it */
 let pf=document.getElementById('print-foot');if(!pf){pf=document.createElement('div');pf.id='print-foot';pf.className='print-only';document.body.appendChild(pf)}
 pf.innerHTML=`<p>For research and education. Not investment advice.</p><p>${E(sym)} on Long-Term Stock Picks: ${E(url)}</p><p>Printed <span id="print-date"></span></p>`;
 const setDate=()=>{const d=document.getElementById('print-date');if(d)d.textContent=new Date().toLocaleString('en-IN',{dateStyle:'medium',timeStyle:'short'})};setDate();
 if(!window.__sharePrint){window.__sharePrint=1;window.addEventListener('beforeprint',setDate)}
 if(host.dataset.sh==sym&&host.firstChild)return;host.dataset.sh=sym;
 host.className='share';
 host.innerHTML=`<button type="button" class="btn" aria-haspopup="menu" aria-expanded="false">${ico('s',I.share)}<span>Share</span></button><div class="share-m" role="menu" aria-label="Share ${E(sym)}" hidden>`
  +`<button type="button" role="menuitem" data-a="copy">${ico('c',I.copy)}Copy link</button>`
  +(can?`<button type="button" role="menuitem" data-a="share">${ico('s',I.share)}Share…</button>`:'')
  +`<button type="button" role="menuitem" data-a="print">${ico('p',I.print)}Print / Save as PDF</button></div>`;
 const b=host.firstChild,m=host.lastChild,items=()=>[...m.querySelectorAll('[role=menuitem]')];
 const shut=f=>{if(m.hidden)return;m.hidden=true;b.setAttribute('aria-expanded','false');if(f)b.focus()};
 const show=()=>{m.hidden=false;b.setAttribute('aria-expanded','true');items()[0].focus()};
 b.onclick=()=>m.hidden?show():shut(true);
 host.onkeydown=e=>{if(e.key=='Escape'){shut(true);return}if(m.hidden){if(e.key=='ArrowDown'&&e.target===b){e.preventDefault();show()}return}
  const L=items(),i=L.indexOf(document.activeElement);if(e.key=='ArrowDown'){e.preventDefault();L[(i+1)%L.length].focus()}else if(e.key=='ArrowUp'){e.preventDefault();L[(i-1+L.length)%L.length].focus()}else if(e.key=='Tab')shut(false)};
 m.onclick=e=>{const a=e.target.closest('[data-a]');if(!a)return;const k=a.dataset.a;shut(true);
  if(k=='copy')copyText(url).then(ok=>say(ok?'Link copied':'Could not copy. Copy the address from the browser bar.'));
  else if(k=='share')navigator.share({title:title(sym),url}).catch(()=>{});
  else if(k=='print')setTimeout(()=>window.print(),50)};
 if(!window.__shareOut){window.__shareOut=1;document.addEventListener('click',e=>{document.querySelectorAll('.share').forEach(h=>{if(!h.contains(e.target)){const mm=h.querySelector('.share-m');if(mm&&!mm.hidden){mm.hidden=true;h.firstChild.setAttribute('aria-expanded','false')}}})})}}
api.mount=mount;
})(typeof window!='undefined'?window:globalThis);

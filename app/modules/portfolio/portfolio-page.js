/* Portfolio page: header and the holdings, watchlist and alerts view from portfolio.js. Does not need the market scan. */
startPage({needsData:false,
 boot(){$('app').innerHTML=ph('My portfolio','Holdings, watchlist and alerts. Read-only: nothing here places orders.','<button class="btn pri" type="button" id="pf-add">'+ic('plus','sm')+'Add a holding</button>')+'<div id="pfhost"></div>';
  if(window.PF)PF.mount($('pfhost'));
  if(!$('fab')){const b=document.createElement('button');b.id='fab';b.type='button';b.className='fab';b.setAttribute('aria-label','Add a holding');b.innerHTML=ic('plus');
   b.onclick=()=>PF.add();document.body.appendChild(b)}
  const a=$('pf-add');if(a)a.onclick=()=>PF.add()},
 build(){},update(){}
});

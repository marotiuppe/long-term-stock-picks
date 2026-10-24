/* Dashboard: your holdings (value, profit or loss, today), what needs your attention, then the track record, top picks and the full list. */
function rel(){const t=D.track[hz];if(!t){$('rel').textContent='No track record for this horizon.';return}
 const edge=(t.hit-t.all_hit)*100,me=(t.median-t.all_median)*100,h=hname(hz),bl=D.baseline&&D.baseline[hz];
 const head=edge>=5?`<p class="hl good">Over ${h}, buy-grade picks have beaten a random stock.</p>`
  :edge>=2?`<p class="hl">Over ${h}, buy-grade picks have a small lead on a random stock.</p>`
  :`<p class="hl none">Over ${h}, buy-grade picks have not beaten a random stock.</p>`;
 const rows=[['Buy-grade picks',t.hit,1],['Any stock',t.all_hit,0]].concat(bl?[['Nifty index (NIFTYBEES)',bl.pgain,0]]:[]);
 $('rel').innerHTML=`${head}
 <p class="lede">${f(t.hit*100,0)}% of buy-grade picks rose, against ${f(t.all_hit*100,0)}% of all stocks. Treat the forecast below as the market's base rate, not a promise.</p>
 <div class="cmp" role="img" aria-label="Share of cases that rose over ${h}: ${rows.map(x=>x[0]+' '+f(x[1]*100,0)+'%').join(', ')}">${rows.map(x=>`<div class="cmp-r ${x[2]?'main':''}"><span>${x[0]}</span><div class="cmp-t"><i style="width:${(x[1]*100).toFixed(1)}%"></i></div><b>${f(x[1]*100,0)}%</b></div>`).join('')}</div>
 <p class="hint" style="margin-top:8px">Share of cases that rose over ${h}.</p>
 <div class="figs">
  <div class="fig"><b>${edge>=0?'+':''}${f(edge,1)} pts</b><span>hit-rate edge</span></div>
  <div class="fig"><b>${pc(t.median)}</b><span>median pick, ${pc(t.all_median)} for any stock</span></div>
  <div class="fig"><b class="dn">${pc(t.worst10)}</b><span>or worse in the worst 10% of picks</span></div>
 </div>
 ${bl?`<p class="mu" id="bl">Just buying the Nifty index (NIFTYBEES) typically gives ${pc(bl.p50)} over ${h}, and it has risen in ${f(bl.pgain*100,0)}% of similar past cases. A historical base rate, not a promise.</p>`:''}
 <details class="more"><summary>How this was tested</summary><p class="mu">Tested only on a held-out period, ${t.start} to ${t.end}, that the forecasts were not built from (with a gap so no windows overlap): ${f(t.all_n,0)} stock-dates, but because windows overlap that is only about ${f(t.all_effective_n,0)} independent samples (${f(t.effective_n,0)} for buy-grade picks). The hit-rate edge was ${edge>=0?'+':''}${f(edge,1)} pts, 95% interval ${f(t.edge_lo*100,1)} to ${f(t.edge_hi*100,1)} pts${t.edge_lo<=0&&t.edge_hi>=0?', so the edge is not distinguishable from zero':''}; the median edge was ${me>=0?'+':''}${f(me,1)} pts. Only stocks still listed today are included (survivorship), which flatters every figure. Stocks in a downtrend (weak score) rose ${f(t.weak_hit*100,0)}% of the time (median ${pc(t.weak_median)}), so a Downtrend tag is a caution flag, not a proven loser. Most NSE stocks rose with the market in this period. Use the dates, stop-loss and range to manage risk rather than expecting a pick to beat the rest. <a href="/api/track-record" target="_blank" rel="noopener">Read the full test report</a> (rebuilt with every scan).</p></details>`}

listPage({home:true,h1:'Long-term stock picks',sub:'Liquid NSE and BSE shares and ETFs to buy and hold for 10 days to 6 months.',
 table:'All stocks and ETFs',tdesc:'Every NSE share, BSE-only share and ETF that passed the quality checks. Filter by exchange or call, search, or sort by any column.'});

/* KPI tiles for the stocks the user owns. Every change carries a sign and an arrow, never colour alone. */
function holdingsKpis(){const m=Mine.summary,I=Holdings.inr,sg=Holdings.signedInr,sp=Holdings.signedPct,tone=n=>n>0?'good':n<0?'bad':'';
 const pnl=m.pnl_pct==null?'':sp(m.pnl_pct)+' on what you invested'+(m.realized?' · realised '+sg(m.realized):'');
 return kpi('wallet','Total invested',I(m.invested),m.count+(m.count==1?' holding':' holdings'))
  +kpi('briefcase','Current value',I(m.value),m.unpriced.length?m.unpriced.join(', ')+' without a price':'at the latest close')
  +kpi('trending-up','Total P&L',arrow(m.pnl)+sg(m.pnl),pnl,tone(m.pnl))
  +kpi('clock','Today\'s change',m.day_abs==null?'-':arrow(m.day_abs)+sg(m.day_abs),m.day_abs==null?'previous close not available':sp(m.day_pct)+' since the last close',tone(m.day_abs))}
/* Allocation by stock, with a link to the full portfolio. */
function renderAlloc(){const el=$('alloc');if(!el||!window.Allocation)return;
 const P=(Mine.me&&Mine.me.positions)||[];
 if(!P.length){el.innerHTML=`<div class="card-h"><div><h2>Allocation</h2><p>How your holdings split by value.</p></div></div><div class="card-b"><div class="empty"><div class="ico">${ic('chart-pie')}</div><b>No holdings yet</b><span>Your allocation appears once you add a holding.</span><button class="btn" type="button" id="al-add">${ic('plus','sm')}Add a holding</button></div></div>`;
  const b=$('al-add');if(b)b.onclick=()=>Holdings.openLotForm({side:'buy'});return}
 const rows=P.filter(p=>p.value>0).map(p=>({label:p.symbol,value:p.value}));
 el.innerHTML=`<div class="card-h"><div><h2>Allocation</h2><p>Share of current value, by stock.</p></div><a class="btn sm" href="/portfolio.html">Portfolio</a></div><div class="card-b">${Allocation.html(rows,{by:'stock',centerTop:Holdings.inr(Mine.summary.value),centerBottom:'current value'})}</div>`;
 Allocation.bind(el)}

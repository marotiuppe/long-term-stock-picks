/* Live check: how the saved forecasts did against the real closing prices. The numbers come from /api/live-check, worked out on the server. */
let LC = null, lcHz = null;
const pct0 = x => f(x * 100, 0) + '%';
const span = r => r && r.lo != null ? `${pct0(r.lo)} to ${pct0(r.hi)}` : '';

function lcTabs() {
  return `<div class="seg lc-seg" role="group" aria-label="Forecast period">${LC.horizons.map(h =>
    `<button class="tab ${h.hz === lcHz ? 'on' : ''}" data-h="${h.hz}" aria-pressed="${h.hz === lcHz}">${esc(h.label)}</button>`).join('')}</div>`;
}

function lcBody(h) {
  if (!h.n) {
    return `<div class="card"><div class="card-b">${empty('circle-check', 'Nothing checked yet', esc(h.note))}</div></div>`;
  }
  const buy = h.buy;
  const kpis = kpi('circle-check', 'Closed inside the range', pct0(h.inside.rate), `Promised: about ${pct0(LC.expectedInside)}. Likely true value ${span(h.inside)}`)
    + kpi('trending-up', 'Rose', pct0(h.rose.rate), `Forecasts said ${pct0(h.predictedRise)} on average. Likely true value ${span(h.rose)}`)
    + kpi('star', 'Buy calls that rose', buy ? pct0(buy.rate) : '-', buy ? `${f(buy.n, 0)} Buy forecasts checked. All stocks: ${pct0(h.rose.rate)}` : 'No Buy call has been checked yet')
    + kpi('percent', 'Average real change', pc(h.avgChange), `Forecast middle case: ${pc(h.avgMiddle)}`);
  const rows = h.daily.map(d => `<tr><td>${dt(d.asof)}</td><td>${f(d.n, 0)}</td><td>${pct0(d.inside)}</td><td>${pct0(d.rose)}</td>`
    + `<td>${pct0(d.predictedRise)}</td><td>${pc(d.avgChange)}</td><td>${d.buyRose == null ? '-' : pct0(d.buyRose)}</td></tr>`).join('');
  return `<div class="kpis">${kpis}</div>`
    + `<section class="card lc-note" aria-live="polite">${ic('info')}<p>${esc(h.note)}</p></section>`
    + `<section class="card"><div class="card-h"><div><h2>Day by day</h2><p>Each row is one night's forecasts, checked once their date had passed. ${h.waiting ? f(h.waiting, 0) + ' more are waiting for their date.' : ''}</p></div></div>`
    + `<div class="tw lc-tw"><table><thead><tr><th>Forecast made on</th><th>Checked</th><th>Inside range</th><th>Rose</th><th>Forecast chance</th><th>Real change</th><th>Buy calls rose</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

function lcDraw() {
  const h = LC.horizons.find(x => x.hz === lcHz) || LC.horizons[0];
  $('app').innerHTML = ph('Live check', 'How the forecasts did against the real closing prices. Saved and checked automatically every night.')
    + `<div class="lc-stack">${lcTabs()}${lcBody(h)}`
    + `<section class="card"><div class="card-h"><h2>How to read this</h2></div><div class="card-b"><ul class="lc-how">`
    + `<li><b>Inside the range.</b> Each forecast has a low and a high case (the 10th and 90th percentile). About 8 in 10 real prices should land between them. Much lower means the ranges are too narrow; much higher, too wide.</li>`
    + `<li><b>Rose.</b> The forecast also gives a chance of a rise. Over many forecasts the share that really rose should be close to the average chance. The scan's day-to-day moves are mostly noise at short periods, so expect about half.</li>`
    + `<li><b>Buy calls.</b> A Buy label is only worth something if those stocks rose more often than all stocks. This is the honest test of that.</li>`
    + `<li><b>Prices are adjusted</b> for splits and dividends, so a split cannot look like a crash. The forecast is the close on the scan date against the close that many trading days later.</li>`
    + `<li><b>The market moves everything on a day.</b> A thousand forecasts from one day are close to one data point, so the number of days matters more. The note above says when there is too little to tell.</li></ul>`
    + `<p class="mu" style="margin-top:12px">${DISC}</p></div></section></div>`;
  document.querySelectorAll('.lc-seg .tab').forEach(b => { b.onclick = () => { lcHz = b.dataset.h; lcDraw(); }; });
}

startPage({
  needsData: false,
  boot() {
    $('app').innerHTML = ph('Live check', 'How the forecasts did against the real closing prices. Saved and checked automatically every night.') + SK;
    fetch('/api/live-check').then(r => { if (!r.ok) throw new Error('The server answered ' + r.status); return r.json(); }).then(d => {
      LC = d;
      lcHz = (d.horizons.find(h => h.n) || d.horizons[0]).hz;
      lcDraw();
    }).catch(e => {
      $('app').innerHTML = ph('Live check', '') + `<div class="card"><div class="card-b">${empty('triangle-alert', 'Could not load the live check', esc(e.message))}</div></div>`;
    });
  },
  update() {}
});

/* About page: data check, method and disclaimer. */
function dq(){const n=D.stocks.length,x=D.excluded,sk=Object.values(x).reduce((a,b)=>a+b,0);
 return `<p><b>Data check.</b> ${f(D.universe,0)} NSE shares read from NSE's own list; ${f(n,0)} passed quality checks and are scored (price ≥ ₹${f(D.minPrice,0)}, average daily trading ≥ ₹${f(D.minValue/1e7,0)} crore, 5 years of history, no data glitches). Skipped ${f(sk,0)}: ${x.illiquid} too thinly traded, ${x.thin} too cheap or too new, ${x.suspect} with suspect price jumps, ${x.nodata+x.stale} with no or stale data. Thin stocks are skipped because their prices are unreliable and you may not be able to exit at your stop-loss. ${D.imports&&(D.imports.etf||D.imports.bse)?`Also scanned from the exchanges' official end-of-day and ETF files (plus any list you imported yourself): ${f(D.imports.etf,0)} ETFs and ${f(D.imports.bse,0)} BSE-only stocks${D.imports.bseDuplicate?`, with ${f(D.imports.bseDuplicate,0)} BSE rows left out because the symbol is already on NSE`:''}.`:'The exchange files for ETFs and BSE-only stocks could not be read this time, so only NSE shares and the built-in ETFs were scanned.'}</p>
 <p>Prices come from Yahoo Finance, free and delayed, adjusted for splits and dividends. Latest bar ${dt(D.stocks[0].asof)}. Benchmark (Nifty 50) ${D.benchmark?'loaded':'<b class="dn">unavailable, so relative strength is ignored</b>'}. Dates use NSE's holiday list${D.holidaysChecked?`, last checked ${dt(D.holidaysChecked,0)}`:''}.${Object.keys(D.holidayWarnings||{}).length?` <b class="dn">${Object.entries(D.holidayWarnings).map(([y,w])=>w=='missing'?`No holiday list for ${y}, so holidays that year are ignored.`:`${y} holidays are provisional until NSE publishes them.`).join(' ')} Dates may be off by a day.</b>`:''}${D.holidayAlert?` <b class="dn">${D.holidayAlert}.</b>`:''} News comes from Google News and only makes a call more cautious. Today's names are used for the history test, so delisted stocks are missing and results look better than reality. Updated ${D.generated}.</p>`}

const gl=()=>window.Glossary?`<ul class="gl-list">${Glossary.entries().map(e=>`<li id="gl-${e.key}"><b>${esc(e.term)}</b><p>${esc(e.def)}</p>${e.use?`<p class="mu">${esc(e.use)}</p>`:''}</li>`).join('')}</ul>`:'';

startPage({
 boot(){$('app').innerHTML=ph('About','How the picks are made, where the data comes from and what it cannot tell you.')+SK},
 build(){$('app').innerHTML=ph('About','How the picks are made, where the data comes from and what it cannot tell you.')
  +`<div class="grid ab-grid"><div class="span-8 ab-col" style="display:flex;flex-direction:column;gap:24px">
   <section class="card ab-data"><div class="card-h"><h2>Data and method</h2></div><div class="card-b"><div class="ft" id="dq"></div></div></section>
   <section class="card ab-how"><div class="card-h"><h2>How the picks are made</h2></div><div class="card-b pgp"><p>Each share gets a 0 to 100 score from trend and momentum (6-month and 3-month return, price against the 200-day average, 50-day against 200-day, distance from the 52-week high, strength against the Nifty 50). The forecast shows what stocks with a similar score did over the next 1, 2, 5, 10, 20, 60 and 126 trading days, scaled to the stock's own volatility. The stop-loss is 2.5 times the 14-day average true range, limited to 7% to 15% below the price.</p></div></section></div>
   <div class="span-4 ab-col" style="display:flex;flex-direction:column;gap:24px">
   <section class="card ab-read"><div class="card-h"><h2>How to read a call</h2></div><div class="card-b"><ul class="legend-list" style="grid-template-columns:1fr">
    <li><span class="vd BUY">Buy</span><span>Strong score, beats the all-stock base rate, price not stretched, no negative news.</span></li>
    <li><span class="vd WAIT">Wait</span><span>Strong score, but the price is stretched or headlines are negative. Wait for a dip.</span></li>
    <li><span class="vd WATCH">Watch</span><span>Mixed picture, not enough edge.</span></li>
    <li><span class="vd DOWNTREND">Downtrend</span><span>The trend is down. A caution flag, not a proven loser.</span></li></ul>
    <p class="mu" style="margin-top:12px">Every figure is a historical base rate for similar-looking stocks, not a promise.</p></div></section>
   <section class="card ab-disc"><div class="card-h"><h2>Disclaimer</h2></div><div class="card-b"><div class="ft">${DISC}</div></div></section></div></div>
   <section class="card" id="glossary"><div class="card-h"><h2>Glossary</h2></div><div class="card-b"><p class="mu" style="margin-bottom:12px">Plain-language meanings of the terms used here. They explain what a measure is, not what a price will do.</p>${gl()}</div></section>`},
 update(){$('dq').innerHTML=dq()}
});

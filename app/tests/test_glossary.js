// Run with node: glossary dictionary, term() escaping, auto-link segments and Share link building.
const assert = require('assert'), path = require('path');
const G = require(path.join(__dirname, '..', 'assets', 'js', 'glossary.js'));
const S = require(path.join(__dirname, '..', 'modules', 'stock', 'share.js'));
const REQ = 'rsi stop-loss sma50 sma200 drawdown hi52 pe eps margin liquidity volatility cagr nifty dividend split momentum pe-history setup-score chance-of-gain likely-range buy-call wait-call watch-call downtrend-call horizon bollinger adjusted-close volume sip xirr lump-sum etf ex-dividend bonus market-cap debt-to-equity roe roce promoter-holding pledged-shares book-value pb operating-income ttm benchmark base-rate held-out-test survivorship-bias average-cost concentration allocation rebased call typical'.split(' ');
REQ.forEach(k => assert(G.has(k), 'missing ' + k));
const E = G.entries();
assert(E.length >= 53);
E.forEach(e => {
  assert(e.term && e.def, e.key);
  assert(e.def.length <= 260 && e.use.length <= 260, 'too long ' + e.key);
  assert(!/[<>]/.test(e.term + e.def + e.use), 'html in ' + e.key);
  assert(/[.]$/.test(e.def), 'sentence end ' + e.key);
  assert(!/\b(?<!not mean the price )b(will (rise|fall|go up)|guarantee[sd]? (a|you)|you should (buy|sell))\b/i.test(e.def + e.use), 'advice ' + e.key);
});
['roe', 'roce', 'promoter-holding', 'pledged-shares', 'book-value'].forEach(k => assert(/does not show it yet/.test(G.define(k).use), k));
assert.strictEqual(G.define('pb').term, G.define('book-value').term);
// term(): escaping, unknown keys, prototype keys
assert.strictEqual(G.term('nope', '<b>x</b>&'), '&lt;b&gt;x&lt;/b&gt;&amp;');
assert.strictEqual(G.term('__proto__', 'a'), 'a');
assert.strictEqual(G.term('constructor', 'a'), 'a');
const h = G.term('rsi', '<i>RSI</i>');
assert(/^<button type="button" class="gl-t" data-term="rsi">&lt;i&gt;RSI&lt;\/i&gt;<\/button>$/.test(h), h);
assert(G.term('rsi').includes('>RSI<'));
// auto-link: first occurrence only, text preserved
const seen = {}, seg = t => G.segments(t, seen);
let a = seg('Price below its 200-day average (₹1,200.00)');
assert.strictEqual(a.map(x => x.t).join(''), 'Price below its 200-day average (₹1,200.00)');
assert.deepStrictEqual(a.filter(x => x.k).map(x => x.k), ['sma200']);
a = seg('Another 200-day average mention');
assert(!a.some(x => x.k), 'second occurrence must not link');
a = G.segments('Stretched (RSI 82, +9% vs 20-day average); 50-day average above 200-day; 5% from the 52-week high', {});
assert.deepStrictEqual(a.filter(x => x.k).map(x => x.k).sort(), ['hi52', 'rsi', 'sma50']);
assert.strictEqual(a.map(x => x.t).join(''), 'Stretched (RSI 82, +9% vs 20-day average); 50-day average above 200-day; 5% from the 52-week high');
assert.strictEqual(G.segments('nothing here', {}).length, 1);
// Share
assert.strictEqual(S.link('https://x.test/', 'tcs'), 'https://x.test/stock/TCS');
assert.strictEqual(S.link('http://localhost:8000', ' M&M '), 'http://localhost:8000/stock/M%26M');
assert.strictEqual(S.title('tcs'), 'TCS on Long-Term Stock Picks');
console.log('ok');

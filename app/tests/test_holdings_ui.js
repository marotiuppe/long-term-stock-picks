const assert = require('assert');
const h = require('../assets/js/holdings.js');

// quantity from an amount: whole shares only, with the leftover reported
assert.deepStrictEqual(h.qtyFromAmount(10000, 3500), { qty: 2, left: 3000 });
assert.deepStrictEqual(h.qtyFromAmount('1,00,000', 2500), { qty: 40, left: 0 });
assert.strictEqual(h.qtyFromAmount(100, 3500).qty, 0);
assert.strictEqual(h.qtyFromAmount(0, 10).qty, 0);
assert.strictEqual(h.qtyFromAmount(10, 0).qty, 0);

// Indian grouping and signs
assert.strictEqual(h.inr(1234567.5), '₹12,34,568');
assert.strictEqual(h.inr(1234567.5, 2), '₹12,34,567.50');
assert.strictEqual(h.inr(-1500, 0), '-₹1,500');
assert.strictEqual(h.inr(null), '-');
assert.strictEqual(h.signedInr(2000), '+₹2,000');
assert.strictEqual(h.signedInr(-2000), '-₹2,000');
assert.strictEqual(h.signedInr(0), '₹0');
assert.strictEqual(h.signedPct(3.456), '+3.5%');
assert.strictEqual(h.signedPct(-0.04, 1), '-0.0%');
assert.strictEqual(h.num('₹ 1,23,456.50'), 123456.5);
assert.ok(isNaN(h.num('abc')) && isNaN(h.num('')) && isNaN(h.num(null)) && isNaN(h.num(true)));

const T = '2026-10-24';
const ok = { symbol: 'TCS', side: 'buy', mode: 'qty', qty: '10', price: '3500.50', date: '2026-10-01', fees: '20', note: '' };
let r = h.checkLot(ok, { today: T });
assert.deepStrictEqual(r.errors, {});
assert.strictEqual(r.gross, 35005); assert.strictEqual(r.total, 35025);            // charges are part of what you invested

// amount mode works out the quantity
r = h.checkLot(Object.assign({}, ok, { mode: 'amount', amount: '10000', price: '3500', qty: '' }), { today: T });
assert.deepStrictEqual(r.errors, {}); assert.strictEqual(r.qty, 2); assert.strictEqual(r.left, 3000); assert.strictEqual(r.total, 7020);
r = h.checkLot(Object.assign({}, ok, { mode: 'amount', amount: '100', price: '3500' }), { today: T });
assert.ok(/less than the price of one share/.test(r.errors.amount));

// every field has a clear message
const bad = (patch, key, re, ctx) => { const e = h.checkLot(Object.assign({}, ok, patch), ctx || { today: T }).errors[key]; assert.ok(e && re.test(e), key + ': ' + e); };
bad({ qty: '' }, 'qty', /Enter the number/);
bad({ qty: '0' }, 'qty', /more than 0/);
bad({ qty: '-5' }, 'qty', /more than 0/);
bad({ qty: '2.5' }, 'qty', /whole number/);
bad({ qty: '99999999999' }, 'qty', /too large/);
bad({ price: '' }, 'price', /Enter the price/);
bad({ price: '0' }, 'price', /more than 0/);
bad({ price: '99999999' }, 'price', /too large/);
bad({ date: '' }, 'date', /Pick the date/);
bad({ date: '2026-10-25' }, 'date', /future/);
bad({ date: '1980-01-01' }, 'date', /past/);
bad({ date: '24/10/2026' }, 'date', /look like/);
bad({ fees: '-1' }, 'fees', /negative/);
bad({ fees: 'abc' }, 'fees', /number/);
bad({ fees: '90000' }, 'fees', /too high/);
bad({ symbol: 'bad sym!' }, 'symbol', /valid symbol/);
bad({ note: 'x'.repeat(201) }, 'note', /too long/);
assert.deepStrictEqual(h.checkLot(Object.assign({}, ok, { date: T }), { today: T }).errors, {});   // today is fine

// a sale: cannot exceed what is held, shows the realised P&L against the average cost
const sell = Object.assign({}, ok, { side: 'sell', qty: '4', price: '3700', fees: '15' });
r = h.checkLot(sell, { today: T, held: 10, avg: 3500 });
assert.deepStrictEqual(r.errors, {}); assert.strictEqual(r.total, 4 * 3700 - 15); assert.strictEqual(r.realized, 4 * 200 - 15);
bad({ side: 'sell', qty: '11' }, 'qty', /You hold 10 shares of TCS, so you cannot sell 11/, { today: T, held: 10, avg: 3500 });
bad({ side: 'sell', qty: '1' }, 'qty', /You hold 0 shares/, { today: T, held: 0, avg: null });
console.log('holdings ui helpers ok');

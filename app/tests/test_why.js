const assert=require('assert');const W=require('../assets/js/why.js');
assert.strictEqual(W.line({price:96,hi52:100,sma20:100,rsi:61.6}),'4% below 52-week high · 4% below 20-day avg · RSI 62');
assert.strictEqual(W.line({price:100,hi52:100,sma20:95}),'At its 52-week high · 5% above 20-day avg');
assert.strictEqual(W.line({}),'');assert.strictEqual(W.line(null),'');assert.strictEqual(W.line({price:10}),'');
const h=W._t.view({summary:'<b>x</b>',cards:[{id:'a',icon:'info',title:'T<',status:{key:'good',label:'Healthy',icon:'info'},headline:'h',rows:[{label:'L',value:'<img>',na:false}],source:'s'}],risks:[],noRisks:'No flags from the data we have, which is limited.',risksNa:[],sources:[]});
assert(!h.includes('<img>')&&!h.includes('<b>x</b>')&&h.includes('&lt;img&gt;')&&h.includes('limited'));
console.log('ok');

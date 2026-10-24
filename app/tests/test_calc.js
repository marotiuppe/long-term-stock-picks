const assert=require('assert');const {_t:T}=require('../modules/stock/calc.js');
const near=(a,b,e=1e-6)=>assert(Math.abs(a-b)<=e,a+' vs '+b);
// period start / calendar
assert.strictEqual(T.addYears('2026-10-24',-1),'2025-10-24');assert.strictEqual(T.addYears('2024-02-29',1),'2025-02-28');
assert.strictEqual(T.firstOnOrAfter(['2025-01-01','2025-01-03','2025-01-06'],'2025-01-04'),2);// weekend -> Monday
assert.strictEqual(T.firstOnOrAfter(['2025-01-01'],'2025-01-04'),-1);
const mk=(n,start,fn)=>{const d=[],c=[];let t=Date.parse(start);for(let i=0;i<n;i++){const x=new Date(t+i*864e5);d.push(x.toISOString().slice(0,10));c.push(fn(i))}return{d,c}};
const long=mk(800,'2024-01-01',i=>100+i);
let P=T.periods(long.d).map(p=>p.k);assert.deepStrictEqual(P,['1','max']);                // 800 days: 1y yes, 3y no
assert.deepStrictEqual(T.periods(mk(10,'2025-01-01',i=>1).d),[]);                          // too short
assert.strictEqual(T.pickPeriod(long.d,'10').k,'max');
// lump: 100 -> 150 over 2 years -> exactly (1.5)^(1/2)-1
const l=T.lump(['2024-01-01','2025-01-01','2026-01-01'],[100,120,150],'2023-06-01',1000);
near(l.value,1500);near(l.gainPct,.5);near(l.cagr,Math.pow(1.5,365/731)-1,1e-9);
// drawdown 100,200,100,150 -> -50%
near(T.maxDrawdown([100,200,100,150]),-.5);near(T.maxDrawdown([1,2,3]),0);
// rolling 1y
const rr=T.rolling1y(['2024-01-01','2025-01-01','2026-01-01'],[100,150,120]);near(rr.best,.5);near(rr.worst,-.2);
assert.strictEqual(T.rolling1y(['2025-01-01','2025-06-01'],[1,2]),null);
// xirr: -1000 at t0, +1100 at 365 -> 10%
near(T.xirr([{t:0,a:-1000},{t:365,a:1100}]),.1,1e-8);
near(T.xirr([{t:0,a:-1000},{t:730,a:1210}]),.1,1e-8);
near(T.xirr([{t:0,a:-1000},{t:365,a:500}]),-.5,1e-8);                                      // bisection-range loss
assert.strictEqual(T.xirr([{t:0,a:-1}]),null);assert.strictEqual(T.xirr([{t:0,a:-1},{t:5,a:-1}]),null);
// SIP on flat prices: gain 0, xirr ~0
const flat=mk(400,'2024-01-01',()=>50);const s0=T.sip(flat.d,flat.c,'2024-01-01',1000,1);
assert.strictEqual(s0.count,14);near(s0.invested,14000);near(s0.value,14000,1e-6);near(s0.xirr,0,1e-6);assert.strictEqual(s0.worstUnder,null);
// SIP hand fixture: buys 1 Jan @100 and 1 Feb @50, end price 100 -> units 10+20=30 -> 3000 on 2000
const d=['2024-01-01','2024-01-15','2024-02-01','2024-02-15'],c=[100,80,50,100];
const s1=T.sip(d,c,'2024-01-01',1000,1);near(s1.value,3000);near(s1.invested,2000);assert.strictEqual(s1.count,2);
// underwater: on 2024-02-01 units 30*50=1500 vs invested 2000 -> -500
near(s1.worstUnder.amt,-500);near(s1.worstUnder.pct,-.25);
// SIP buy day on weekend/holiday rolls forward; day 5 with gap
const g=T.sip(['2024-01-08','2024-02-07','2024-03-06'],[10,10,10],'2024-01-01',100,5);assert.strictEqual(g.count,3);assert.strictEqual(g.startDate,'2024-01-08');
assert.strictEqual(T.sip(['2024-01-01','2024-01-02'],[1,1],'2024-01-01',100,1),null);        // <2 instalments
// compounding
near(T.compound('lump',1000,10,2).value,1210);near(T.compound('lump',1000,0,5).value,1000);
const c1=T.compound('sip',1000,0,1);near(c1.value,12000);near(c1.invested,12000);
const c2=T.compound('sip',1000,12,1);near(c2.value,1000*(Math.pow(1.12,1)-1)/(Math.pow(1.12,1/12)-1)*Math.pow(1.12,1/12),1e-6);
{let v=0;const rm=Math.pow(1.12,1/12)-1;for(let i=0;i<120;i++)v=(v+10000)*(1+rm);near(T.compound('sip',10000,12,10).value,v,1e-3);near(v,2240358.9,1)}  // month-by-month simulation                                       // known annuity-due figure (monthly-equivalent 12% EAR)
// invalid input never gives NaN
[['lump',0,12,5],['lump',-5,12,5],['lump',NaN,12,5],['lump',1000,31,5],['lump',1000,-1,5],['sip',1000,12,0],['sip',1000,12,41],['sip','x',12,5]].forEach(a=>assert.strictEqual(T.compound(...a),null));
assert.strictEqual(T.lump([],[],'2024-01-01',100),null);assert.strictEqual(T.lump(['2024-01-01','2025-01-01'],[1,2],'2024-01-01',0),null);
assert.strictEqual(T.lump(['2024-01-01','2025-01-01'],[1,2],'2025-06-01',100),null);
// clean drops bad rows
const cc=T.clean({d:['2024-01-01','2024-01-02','2024-01-03','2024-01-03'],c:[1,null,'x',2]});assert.deepStrictEqual(cc.d,['2024-01-01','2024-01-03']);
console.log('ok');

/* Glossary: plain-language tooltips. Glossary.term(key,label) -> HTML, Glossary.enhance(root) wires [data-term]; [data-gloss-auto] links the first mention of a few phrases. Explains terms; never predicts or advises. */
(function(root){
const G={
'rsi':['RSI','A 0 to 100 gauge of how fast the price rose or fell over the last 14 days. Above about 70 means it rose fast, below about 30 means it fell fast.','The Why list mentions it when the price looks stretched in the short term. A high RSI does not mean the price will fall.'],
'stop-loss':['Stop-loss','A price at which you decide to sell to cap a loss. Example: bought at ₹100 with a stop at ₹90 means you leave if it closes below ₹90.','Set at 2.5 times the stock\'s 14-day average daily move, kept between 7% and 15% below the price. It is a plan, not a guarantee: a price can gap past it.'],
'sma50':['50-day average','The average closing price of the last 50 trading days. It smooths out daily noise and shows the medium-term trend.','A 50-day average above the 200-day one counts as a long-term uptrend in the Why list.'],
'sma200':['200-day average','The average closing price of the last 200 trading days (about 10 months). Many investors treat it as the line between a long-term uptrend and downtrend.','The app notes whether the price is above or below it. This describes the past, not the next move.'],
'drawdown':['Drawdown','How far a price has fallen from its previous high. If a stock went from ₹200 to ₹150, the drawdown is 25%.','Shows how deep past falls were, so you can judge how much of a dip you can sit through.'],
'hi52':['52-week high','The highest price in the last year. Being close to it means the stock has been strong recently.','The app shows how far the price is below it and counts being near it as a strength signal.'],
'pe':['P/E ratio','Price divided by yearly profit per share. A P/E of 20 means you pay ₹20 for each ₹1 of yearly profit. Lower is not always better, since fast-growing firms often have higher P/E.','Shown only where the data source provides it.'],
'eps':['EPS (earnings per share)','The company\'s profit divided by its number of shares. If a company earns ₹100 crore and has 10 crore shares, EPS is ₹10.','Used to work out P/E.'],
'margin':['Profit margin','The share of each ₹100 of sales the company keeps as profit. A 12% margin means ₹12 profit per ₹100 sold.','Shown only where the data source provides it.'],
'liquidity':['Liquidity','How easily you can buy or sell without moving the price. Thinly traded shares may not sell at your stop-loss.','The app skips shares with low average daily trading value so listed prices stay reliable.'],
'volatility':['Volatility','How much a price jumps around day to day. A volatile stock can rise or fall a lot in a short time.','Forecast ranges are scaled to each stock\'s own volatility, so a jumpy stock gets a wider range.'],
'cagr':['CAGR','Compound annual growth rate: the steady yearly rate that would turn a start value into the end value. ₹100 becoming ₹200 in 5 years is about 15% a year.','Used for long-period growth numbers. Real returns are never this smooth.'],
'nifty':['Nifty 50','An index of 50 large Indian companies on the NSE. It is the usual yardstick for how the Indian market is doing.','Used as the benchmark: the app checks whether a stock held up better or worse than the Nifty.'],
'dividend':['Dividend','A part of profit a company pays out to shareholders, in cash per share. A ₹5 dividend on 100 shares pays you ₹500.','Prices here are adjusted for dividends, so history is comparable.'],
'split':['Stock split','A company cuts each share into several, so the price falls but total value stays the same. A 1:2 split turns one ₹1,000 share into two ₹500 shares.','Prices are adjusted for splits, so charts do not show fake crashes.'],
'momentum':['Momentum','The tendency of recent winners to keep doing a little better than recent losers for a while. It is a tendency seen in history, not a rule.','Part of the setup score: 6-month and 3-month returns and trend strength.'],
'pe-history':['P/E history','How the P/E ratio has changed over the years. It shows if the market is paying more or less for each ₹1 of profit than before.','Shown only where the data source provides it.'],
'call':['Call','The app\'s one-word label for a stock: Buy, Wait, Watch or Downtrend. It comes from fixed rules applied to the setup score, price, trend and news.','It is a screening label, not advice and not a prediction.'],
'typical':['Typical outcome','The middle result (median) of what similar stocks did over the chosen period: half did better, half did worse.','A historical figure for look-alike setups. Any single stock can land far from it.'],
'setup-score':['Setup score','A 0 to 100 number for how strong a stock\'s trend and momentum look today. It is not a rating of the business.','Built from 6-month and 3-month return, price against the 200-day average, 50-day against 200-day, distance from the 52-week high and strength against the Nifty. It has no proven edge on its own.'],
'chance-of-gain':['Chance of gain','Out of past stocks with a similar setup, the share that were higher after the chosen period. 60% means 6 of 10 were up.','A historical base rate, not a promise for this stock.'],
'likely-range':['Likely range','The span between the 10th and 90th percentile of past outcomes: 1 in 10 did worse than the low end and 1 in 10 did better than the high end.','Outcomes outside the range do happen, and the loss side can be larger.'],
'buy-call':['Buy call','The app\'s label for a strong setup score that beats the all-stock base rate, with the price not stretched and no negative news.','It is a screening label, not advice. Read the reasons first.'],
'wait-call':['Wait call','A strong setup, but the price looks stretched or headlines are negative. The app suggests waiting for a dip.','A label from fixed rules, not a prediction.'],
'watch-call':['Watch call','A mixed picture without enough edge over the all-stock average.','Keep it on a list and check back later.'],
'downtrend-call':['Downtrend call','The long-term trend is down. A caution flag, not proof that the price will keep falling.','Stocks in downtrends can and do recover.'],
'horizon':['Horizon','How long you plan to hold, for example 10 days, 1 month, 3 months or 6 months.','The forecast and typical outcome change with the horizon you pick. Longer periods give wider ranges.'],
'bollinger':['Bollinger Bands','Two lines drawn above and below a moving average, set by recent volatility. The price stays between them most of the time.','Touching a band is not a signal to buy or sell by itself.'],
'adjusted-close':['Adjusted close','The closing price corrected for splits, bonus issues and dividends so old prices compare fairly with today\'s.','All charts and returns use adjusted prices.'],
'volume':['Volume','How many shares changed hands in a day. High volume means many people were trading.','Used to judge how liquid a stock is.'],
'sip':['SIP','Systematic investment plan: investing a fixed amount, such as ₹5,000, every month regardless of the price.','You buy more shares when prices are low and fewer when high. It does not remove the risk of loss.'],
'xirr':['XIRR','Your yearly return when you invested at different dates, such as monthly SIPs. It treats each payment by its date.','Compare it with CAGR, which assumes one start and one end.'],
'lump-sum':['Lump sum','Investing the whole amount at once instead of spreading it over months.','The what-if calculator can compare it with spreading the money out.'],
'etf':['ETF','Exchange-traded fund: a basket of shares, such as the Nifty 50, that trades on the exchange like one share.','ETFs are marked with an ETF tag in this app.'],
'ex-dividend':['Ex-dividend date','The cut-off date: you must own the share before it to get the next dividend. The price usually drops by about the dividend amount that day.','Adjusted prices smooth this drop out.'],
'bonus':['Bonus shares','Free extra shares given to existing holders, such as 1 for every 2 held. The price adjusts down, so total value stays the same at first.','Prices are adjusted for bonus issues.'],
'market-cap':['Market cap','Share price times number of shares: what the market values the whole company at. Large caps are bigger, usually steadier firms.','This app does not rank by market cap.'],
'debt-to-equity':['Debt-to-equity','Money owed divided by the owners\' money in the business. A ratio of 2 means ₹2 of debt for each ₹1 of equity. High debt makes a firm riskier in bad times.','This app does not show it yet.'],
'roe':['ROE','Return on equity: yearly profit as a share of the owners\' money in the business. 15% means ₹15 profit for each ₹100 of equity.','This app does not show it yet.'],
'roce':['ROCE','Return on capital employed: yearly operating profit as a share of all money (equity plus debt) used in the business.','This app does not show it yet.'],
'promoter-holding':['Promoter holding','The share of the company owned by its founders or controlling group. A falling share is worth a look.','This app does not show it yet.'],
'pledged-shares':['Pledged shares','Shares that promoters have put up as security for loans. If the price falls, lenders can sell them, which adds pressure.','This app does not show it yet.'],
'book-value':['Book value (P/B)','The company\'s assets minus debts, per share. P/B is the price divided by it: a P/B of 2 means paying ₹2 for each ₹1 of net assets.','This app does not show it yet.'],
'operating-income':['Operating income','Profit from the main business before interest and tax. It shows how the core work is doing.','Shown only where the data source provides it.'],
'ttm':['TTM','Trailing twelve months: the latest four quarters added up, so seasonal swings do not mislead.','Used for P/E and other yearly figures where shown.'],
'benchmark':['Benchmark','A yardstick to compare against, here the Nifty 50. Beating it means doing better than the market.','Used to measure a stock\'s relative strength.'],
'base-rate':['Base rate','How often something happened across all stocks, with no special filter. If 52% of all stocks were up after a month, that is the base rate.','A Buy call needs the stock\'s own chance of gain to beat it by a margin.'],
'held-out-test':['Held-out test','A check on data kept aside while the rules were built, so the rules could not be fitted to it. It is a fairer test than one on data used for building.','The "How this was tested" figures come from this kind of test.'],
'survivorship-bias':['Survivorship bias','Using only companies still listed today leaves out the ones that failed, so past results look better than they really were.','This app uses today\'s listed names, so its history numbers are flattered.'],
'average-cost':['Average cost','What you paid per share on average across all your buys. Buy 10 at ₹100 and 10 at ₹120 and your average cost is ₹110.','Used to work out your gain or loss on holdings.'],
'concentration':['Concentration','How much of your money sits in one stock or sector. If one share is 40% of your portfolio, its fall hurts a lot.','Shown so you can see if one holding dominates.'],
'allocation':['Allocation','How your money is split across stocks, ETFs or sectors, for example 60% large companies and 40% ETFs.','Shown on the portfolio page.'],
'rebased':['Rebased to 100','Both lines start at 100 on the same day so you can compare their growth directly. A line at 130 is up 30%.','Used when the Nifty is drawn on the same chart as a stock.']
};
G['pb']=G['book-value'];
const AUTO=[[/\b200-day average\b/i,'sma200'],[/\b50-day average\b/i,'sma50'],[/\b52-week high\b/i,'hi52'],[/\bRSI\b/,'rsi'],[/\bstop-loss\b/i,'stop-loss'],[/\bdrawdown\b/i,'drawdown'],[/\bvolatility\b/i,'volatility'],[/\bNifty( 50)?\b/,'nifty'],[/\bdividends?\b/i,'dividend']];
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const has=k=>typeof k=='string'&&Object.prototype.hasOwnProperty.call(G,k);
const term=(k,label)=>has(k)?`<button type="button" class="gl-t" data-term="${esc(k)}">${esc(label==null?G[k][0]:label)}</button>`:esc(label==null?k:label);
const entries=()=>Object.keys(G).filter(k=>k!='pb').map(k=>({key:k,term:G[k][0],def:G[k][1],use:G[k][2]||''}));
/* Split text into plain and linked segments; each key is linked once (first occurrence). `seen` is shared across calls. */
function segments(text,seen){seen=seen||{};let out=[{t:text}];
 AUTO.forEach(([re,k])=>{if(seen[k])return;for(let i=0;i<out.length;i++){const sg=out[i];if(sg.k)continue;const m=re.exec(sg.t);if(!m)continue;seen[k]=1;
  const a=sg.t.slice(0,m.index),b=sg.t.slice(m.index+m[0].length),r=[];if(a)r.push({t:a});r.push({t:m[0],k});if(b)r.push({t:b});out.splice(i,1,...r);break}});
 return out}
const api={term,entries,has,esc,segments,define:k=>has(k)?{term:G[k][0],def:G[k][1],use:G[k][2]||''}:null};
root.Glossary=api;
if(typeof module!='undefined'&&module.exports)module.exports=api;
if(typeof document=='undefined'||!document.addEventListener)return;
/* ---- popover: one shared element, event delegation on document ---- */
let pop=null,cur=null,pinned=false,tmr=0,raf=0;
const trig=n=>n&&n.closest&&n.closest('[data-term]');
const passive=el=>!!el.parentNode&&!!el.parentNode.closest('button,a');   /* inside another control: hover only, never steal its click */
function mkPop(){if(pop)return pop;pop=document.createElement('div');pop.id='gl-pop';pop.className='gl-pop';pop.setAttribute('role','tooltip');pop.hidden=true;document.body.appendChild(pop);
 pop.addEventListener('pointerenter',()=>clearTimeout(tmr));pop.addEventListener('pointerleave',()=>{if(!pinned)sched()});return pop}
function place(){if(!cur||!pop||pop.hidden)return;const r=cur.getBoundingClientRect(),vw=document.documentElement.clientWidth,vh=window.innerHeight,m=8;
 pop.style.maxWidth=Math.min(300,vw-2*m)+'px';pop.style.left='0px';pop.style.top='0px';const w=pop.offsetWidth,h=pop.offsetHeight;
 const x=Math.min(Math.max(m,r.left+r.width/2-w/2),vw-w-m);let y=r.bottom+6,up=false;if(y+h>vh-m&&r.top-h-6>=m){y=r.top-h-6;up=true}else if(y+h>vh-m)y=Math.max(m,vh-h-m);
 pop.style.left=x+'px';pop.style.top=y+'px';pop.dataset.pos=up?'up':'down'}
function open(el,pin){const k=el.getAttribute('data-term');if(!has(k))return;clearTimeout(tmr);if(cur&&cur!==el)unlink();
 mkPop();const d=G[k];pop.innerHTML=`<b>${esc(d[0])}</b><span>${esc(d[1])}</span>${d[2]?`<span class="gl-u"><i>How this app uses it:</i> ${esc(d[2])}</span>`:''}`;
 cur=el;pinned=!!pin;el.setAttribute('aria-describedby','gl-pop');pop.hidden=false;place()}
function unlink(){if(cur)cur.removeAttribute('aria-describedby')}
function close(){clearTimeout(tmr);unlink();cur=null;pinned=false;if(pop)pop.hidden=true}
function sched(){clearTimeout(tmr);tmr=setTimeout(()=>{if(!pinned)close()},150)}
document.addEventListener('pointerover',e=>{if(e.pointerType=='touch')return;const t=trig(e.target);if(!t)return;if(t!==cur&&!pinned)open(t,false);else if(t===cur)clearTimeout(tmr)},true);
document.addEventListener('pointerout',e=>{if(e.pointerType=='touch'||pinned)return;const t=trig(e.target);if(t&&t===cur&&!(e.relatedTarget&&t.contains(e.relatedTarget)))sched()},true);
document.addEventListener('focusin',e=>{const t=trig(e.target);if(!t||passive(t)||pinned)return;let vis=true;try{vis=t.matches(':focus-visible')}catch(_){}if(vis)open(t,false)});
document.addEventListener('focusout',e=>{const t=trig(e.target);if(t&&t===cur)close()});
document.addEventListener('click',e=>{const t=trig(e.target);
 if(t&&!passive(t)){e.preventDefault();e.stopPropagation();if(cur===t&&pinned)close();else open(t,true);return}
 if(cur&&!(pop&&pop.contains(e.target)))close()},true);
document.addEventListener('keydown',e=>{if(e.key=='Escape'&&cur){const t=cur;close();if(document.activeElement!==t&&t.focus&&!passive(t))t.focus()}});
['resize','scroll'].forEach(n=>window.addEventListener(n,()=>{if(!cur)return;cancelAnimationFrame(raf);raf=requestAnimationFrame(place)},{passive:true,capture:true}));
/* ---- enhance ---- */
const done=new WeakMap();
function autoLink(c){const txt=c.textContent;if(done.get(c)===txt)return;const seen={};
 const w=document.createTreeWalker(c,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentNode.closest('[data-term],a,button,script,style')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT}),L=[];
 while(w.nextNode())L.push(w.currentNode);
 L.forEach(n=>{const s=segments(n.nodeValue,seen);if(s.length<2)return;const f=document.createDocumentFragment();
  s.forEach(g=>{if(g.k){const b=document.createElement('button');b.type='button';b.className='gl-t';b.setAttribute('data-term',g.k);b.textContent=g.t;f.appendChild(b)}else f.appendChild(document.createTextNode(g.t))});
  n.parentNode.replaceChild(f,n)});
 done.set(c,c.textContent)}
function enhance(r){r=r||document;if(!r.querySelectorAll)return;
 const list=[...(r.matches&&r.matches('[data-term]')?[r]:[]),...r.querySelectorAll('[data-term]')];
 list.forEach(el=>{if(el.__gl)return;el.__gl=1;if(!has(el.getAttribute('data-term')))return;el.classList.add('gl-t');
  if(passive(el))el.classList.add('gl-p');else if(el.tagName!='BUTTON'){el.tabIndex=0;el.setAttribute('role','button')}});
 [...(r.matches&&r.matches('[data-gloss-auto]')?[r]:[]),...r.querySelectorAll('[data-gloss-auto]')].forEach(autoLink)}
api.enhance=enhance;
let mo=null,pend=0;
function observe(){if(!window.MutationObserver||mo)return;
 mo=new MutationObserver(()=>{if(pend)return;pend=setTimeout(()=>{pend=0;enhance(document.body)},120)});mo.observe(document.body,{childList:true,subtree:true})}
const boot=()=>{enhance(document.body);observe()};
if(document.readyState=='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})(typeof window!='undefined'?window:globalThis);

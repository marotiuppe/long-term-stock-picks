/* Price history chart on Apache ECharts (global `echarts`, vendored): zoom and pan (dataZoom inside + slider, buttons, pinch), timeframe chips,
   line/area or candles, volume, 50- and 200-day averages, 52-week high and low, Bollinger bands, Nifty 50 comparison rebased to 100,
   full screen, theme-aware. Data from /api/chart (daily bars, oldest first). Pure helpers are exported on `_t` for node tests. */
(() => {
  const RANGES = [['1M', 21], ['3M', 63], ['6M', 126], ['1Y', 252], ['3Y', 756], ['5Y', 1260], ['Max', 1e9]];
  const TYPES = [['area', 'Line'], ['candle', 'Candles']];
  const OVERS = [['sma50', '50-day average'], ['sma200', '200-day average'], ['hl52', '52-week high / low'], ['bb', 'Bollinger bands'],
                 ['vol', 'Volume'], ['cmp', 'Compare with Nifty 50']];
  const DEF = { range: '1Y', type: 'area', on: { sma50: false, sma200: false, hl52: false, bb: false, vol: true, cmp: false } };
  const NIFTY = '^NSEI', MIN_BARS = 20, WEEK52 = 252;

  let prefs = loadPrefs();
  function loadPrefs() {
    try {
      const p = JSON.parse(localStorage.getItem('pcprefs'));
      if (p) {
        const range = p.range == 'All' ? 'Max' : p.range, type = p.type == 'line' ? 'area' : p.type;
        return { range: RANGES.some(r => r[0] == range) ? range : DEF.range, type: TYPES.some(t => t[0] == type) ? type : DEF.type,
                 on: Object.assign({}, DEF.on, p.on) };
      }
    } catch (e) { /* storage blocked or empty: defaults */ }
    return JSON.parse(JSON.stringify(DEF));
  }
  function savePrefs() { try { localStorage.setItem('pcprefs', JSON.stringify(prefs)); } catch (e) { /* ignore */ } }

  // ---------- pure helpers (also exported for tests) ----------
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = (n, d = 2) => n.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
  const vol = n => n >= 1e7 ? fmt(n / 1e7, 2) + ' crore' : n >= 1e5 ? fmt(n / 1e5, 1) + ' lakh' : fmt(n, 0);
  const compactVol = n => n >= 1e7 ? +(n / 1e7).toFixed(1) + 'Cr' : n >= 1e5 ? +(n / 1e5).toFixed(1) + 'L' : n >= 1e3 ? +(n / 1e3).toFixed(0) + 'K' : String(n);
  const signed = (n, d = 2) => (n >= 0 ? '+' : '−') + fmt(Math.abs(n), d);
  const arrow = n => n >= 0 ? '▲' : '▼';
  const axisFmt = v => Math.abs(v) >= 1000 ? fmt(v, 0) : fmt(v, Math.abs(v) >= 100 ? 0 : 2);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const rangeCount = k => RANGES.find(r => r[0] == k)[1];

  function sma(a, w) {
    const o = new Array(a.length).fill(null);
    let s = 0;
    for (let i = 0; i < a.length; i++) {
      s += a[i];
      if (i >= w) s -= a[i - w];
      if (i >= w - 1) o[i] = s / w;
    }
    return o;
  }

  function bollinger(a, w = 20, k = 2) {
    const mid = sma(a, w), up = mid.slice(), lo = mid.slice();
    for (let i = w - 1; i < a.length; i++) {
      let v = 0;
      for (let j = i - w + 1; j <= i; j++) v += (a[j] - mid[i]) ** 2;
      const sd = Math.sqrt(v / w);
      up[i] = mid[i] + k * sd;
      lo[i] = mid[i] - k * sd;
    }
    return { mid, up, lo };
  }

  // The other series on this series' dates, carrying the last known value forward (null before its first bar).
  function align(dates, other) {
    const m = new Map(other.d.map((d, i) => [d, other.c[i]]));
    let last = null;
    return dates.map(d => { if (m.has(d)) last = m.get(d); return last; });
  }

  // Visible window as [first index, last index] for a timeframe key; the last bar is always the right edge.
  const rangeWindow = (key, n) => [Math.max(0, n - rangeCount(key)), n - 1];
  // Which timeframe chip matches a window ('' when none): the right edge must be at the latest bar, the left edge within a bar or so.
  function matchRange(win, n) {
    const tol = Math.max(1, Math.round(n / 2000));
    if (!win || win[1] < n - 1 - tol) return '';
    for (const [k, cnt] of RANGES) {
      if (cnt >= n && k != 'Max') continue;       // a range longer than the history is the same as Max
      if (Math.abs(win[0] - Math.max(0, n - cnt)) <= tol) return k;
    }
    return '';
  }
  // Zoom around the window centre; factor < 1 zooms in. At least 5 bars (or all, if fewer), at most all.
  function zoomWindow(win, n, factor) {
    const span = win[1] - win[0] + 1, ns = clamp(Math.round(span * factor), Math.min(5, n), n);
    const s = clamp(Math.round((win[0] + win[1]) / 2 - (ns - 1) / 2), 0, n - ns);
    return [s, s + ns - 1];
  }
  // Rolling 52-week (last 252 bars) high and low from the bars' highs and lows.
  function window52(h, l, n = WEEK52) {
    const a = Math.max(0, h.length - n);
    let hi = -Infinity, lo = Infinity, ihi = a, ilo = a;
    for (let i = a; i < h.length; i++) { if (h[i] > hi) { hi = h[i]; ihi = i; } if (l[i] < lo) { lo = l[i]; ilo = i; } }
    return { hi, lo, ihi, ilo };
  }
  // Rebase a series to 100 at index i0 (or its first value after that, for a series that starts late).
  function rebase(a, i0) {
    let b = null;
    for (let i = Math.max(0, i0); i < a.length; i++) if (a[i] != null) { b = a[i]; break; }
    return a.map(v => v == null || !b ? null : v / b * 100);
  }
  const pctSince = (a, i, s) => (a[i] / a[s] - 1) * 100;

  const dateText = (iso, long) => {
    const d = new Date(iso + 'T00:00:00');
    return isNaN(d) ? iso : d.toLocaleDateString('en-IN', long ? { day: 'numeric', month: 'short', year: 'numeric' } : { day: 'numeric', month: 'short' });
  };
  const monthText = iso => {
    const d = new Date(iso + 'T00:00:00');
    return isNaN(d) ? iso : d.toLocaleDateString('en-IN', { month: 'short', year: '2-digit' });
  };

  function candles(D) { return D.d.map((_, i) => [D.o[i], D.c[i], D.l[i], D.h[i]]); }   // ECharts order: open, close, low, high

  // tooltip body for one bar: date, OHLC, volume, and % change since the start of the visible range (plus the Nifty when comparing)
  function tipHtml(inst, i) {
    const D = inst.data, s = inst.win[0], P = inst.prefs || prefs, cmp = !!(P.on.cmp && inst.nal);
    const row = (l, v, cls) => `<div class="r"><span>${l}</span><b${cls ? ` class="${cls}"` : ''}>${v}</b></div>`;
    const chg = p => `${arrow(p)} ${signed(p)}%`;
    const sp = pctSince(D.c, i, s);
    let h = `<div class="th">${dateText(D.d[i], 1)}</div>` +
      row('Open', '₹' + fmt(D.o[i])) + row('High', '₹' + fmt(D.h[i])) + row('Low', '₹' + fmt(D.l[i])) + row('Close', '₹' + fmt(D.c[i])) +
      row('Volume', vol(D.v[i])) + row('Since start of range', chg(sp), sp >= 0 ? 'up' : 'dn');
    if (cmp) {
      const nr = rebase(inst.nal, s), sr = rebase(D.c, s);
      if (nr[i] != null) h += row(esc(inst.sym) + ' (start = 100)', fmt(sr[i], 1)) + row('Nifty 50 (start = 100)', fmt(nr[i], 1), nr[i] >= 100 ? 'up' : 'dn');
    } else {
      if (P.on.sma50 && inst.ind.sma50[i] != null) h += row('50-day average', '₹' + fmt(inst.ind.sma50[i]));
      if (P.on.sma200 && inst.ind.sma200[i] != null) h += row('200-day average', '₹' + fmt(inst.ind.sma200[i]));
    }
    return h;
  }
  // plain-text reading of one bar for the live region
  function readout(inst, i) {
    const D = inst.data, sp = pctSince(D.c, i, inst.win[0]);
    return `${dateText(D.d[i], 1)}: open ${fmt(D.o[i])}, high ${fmt(D.h[i])}, low ${fmt(D.l[i])}, close ${fmt(D.c[i])}, ` +
      `${signed(sp)}% since the start of the range, volume ${vol(D.v[i])}`;
  }

  // ---------- ECharts option (pure: reads inst + colours, touches no DOM) ----------
  function buildOption(inst, C) {
    const D = inst.data, P = inst.prefs || prefs, n = D.c.length, s = inst.win[0], e = inst.win[1], W = inst.W || 600, H = inst.H || 340;
    const small = W < 480, cmp = !!(P.on.cmp && inst.nal), type = cmp ? 'area' : P.type;
    const left = small ? 48 : 58, right = small ? 10 : 18, top = 10, sliderH = small ? 30 : 26, axisH = 20, bottomZone = sliderH + 12 + axisH;
    const showVol = !!P.on.vol, volH = showVol ? Math.max(44, Math.round(H * .16)) : 0, gap = showVol ? 10 : 0;
    const mainH = Math.max(80, H - top - bottomZone - volH - gap);
    const grids = [{ left, right, top, height: mainH }];
    if (showVol) grids.push({ left, right, top: top + mainH + gap, height: volH });
    const alpha = (c, a) => { try { return echarts.color.modifyAlpha(c, a); } catch (er) { return c; } };
    const last = grids.length - 1;
    const dlab = v => { const span = inst.win[1] - inst.win[0], iso = D.d[v] || v; return span > 1000 ? String(iso).slice(0, 4) : span > 130 ? monthText(iso) : dateText(iso); };
    const xAxis = grids.map((_, i) => ({
      type: 'category', gridIndex: i, data: D.d, boundaryGap: true, axisTick: { show: false }, splitLine: { show: false },
      axisLine: { lineStyle: { color: C.bd } },
      axisLabel: { show: i == last, color: C.mu, hideOverlap: true, formatter: (v) => dlab(v) },
      axisPointer: { label: { show: i == last, formatter: p => dateText(p.value, 1), backgroundColor: C.tx, color: C.card } },
    }));
    const axLabel = p => cmp ? fmt(p.value, 1) : '₹' + fmt(p.value);
    const yAxis = [{
      type: 'value', scale: true, gridIndex: 0, splitNumber: small ? 4 : 5, axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: C.bd, opacity: .7 } }, axisLabel: { color: C.mu, formatter: v => cmp ? fmt(v, 0) : axisFmt(v) },
      axisPointer: { label: { formatter: axLabel, backgroundColor: C.tx, color: C.card } },
    }];
    if (showVol) yAxis.push({
      type: 'value', gridIndex: 1, splitNumber: 2, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
      axisLabel: { color: C.mu, formatter: compactVol }, axisPointer: { label: { show: false } },
    });

    // marks on the main series: 52-week high and low, the user's average buy price and their buys and sales
    const ml = [], mp = [];
    if (P.on.hl52 && !cmp) {
      const w = window52(D.h, D.l);
      ml.push({ yAxis: w.hi, label: { formatter: '52-week high ₹' + fmt(w.hi), position: 'insideEndTop' }, lineStyle: { color: C.up, type: 'dashed', width: 1.2 } },
              { yAxis: w.lo, label: { formatter: '52-week low ₹' + fmt(w.lo), position: 'insideEndBottom' }, lineStyle: { color: C.dn, type: 'dashed', width: 1.2 } });
    }
    const my = !cmp && inst.my;
    if (my) {
      ml.push({ yAxis: my.avg, label: { formatter: 'Your average ₹' + fmt(my.avg), position: 'insideStartTop' }, lineStyle: { color: C.tx, type: 'dashed', width: 1.5 } });
      (my.lots || []).forEach(l => {
        const i = D.d.findIndex(d => d >= l.date);
        if (i < 0 || l.date < D.d[0]) return;
        const buy = l.side == 'buy';
        mp.push({ coord: [D.d[i], D.c[i]], symbol: 'triangle', symbolSize: 12, symbolRotate: buy ? 0 : 180, symbolOffset: [0, buy ? 12 : -12],
                  itemStyle: { color: buy ? C.ac : C.blue, borderColor: C.card, borderWidth: 1.5 }, name: (buy ? 'Bought ' : 'Sold ') + l.qty });
      });
    }
    const px = type == 'candle'
      ? { id: 'px', name: inst.sym, type: 'candlestick', data: inst.cand || (inst.cand = candles(D)), large: true, largeThreshold: 600,
          // up days hollow, down days filled: direction never depends on colour alone
          itemStyle: { color: C.card, color0: C.dn, borderColor: C.up, borderColor0: C.dn, borderWidth: 1.3 } }
      : { id: 'px', name: inst.sym, type: 'line', data: cmp ? rebase(D.c, s) : D.c, showSymbol: false, sampling: 'lttb', z: 3,
          lineStyle: { width: 2, color: C.ac }, itemStyle: { color: C.ac }, emphasis: { disabled: true },
          areaStyle: cmp ? undefined : { color: C.ac, opacity: .12 } };
    px.xAxisIndex = 0; px.yAxisIndex = 0; px.animation = false;
    const lab = { color: C.tx, fontSize: 11, backgroundColor: alpha(C.card, .8), padding: [1, 4], borderRadius: 3 };
    if (ml.length) px.markLine = { silent: true, symbol: 'none', animation: false, label: lab, data: ml };
    if (mp.length) px.markPoint = { silent: true, animation: false, data: mp };
    const line = (id, name, data, color, extra) => Object.assign({ id, name, type: 'line', data, showSymbol: false, xAxisIndex: 0, yAxisIndex: 0, animation: false,
      lineStyle: { width: 1.5, color }, itemStyle: { color }, emphasis: { disabled: true }, silent: true }, extra);
    const series = [px];
    if (cmp) series.push(line('nifty', 'Nifty 50', rebase(inst.nal, s), C.blue, { lineStyle: { width: 2, color: C.blue, type: 'dashed' }, silent: false }));
    else {
      if (P.on.sma200) series.push(line('sma200', '200-day average', inst.ind.sma200, C.s200));
      if (P.on.sma50) series.push(line('sma50', '50-day average', inst.ind.sma50, C.amber));
      if (P.on.bb) series.push(line('bbu', 'Bollinger upper', inst.ind.bb.up, C.blue, { lineStyle: { width: 1, color: C.blue, type: 'dotted', opacity: .8 } }),
                               line('bbl', 'Bollinger lower', inst.ind.bb.lo, C.blue, { lineStyle: { width: 1, color: C.blue, type: 'dotted', opacity: .8 } }));
    }
    if (showVol) series.push({ id: 'vol', name: 'Volume', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: D.v, large: true, animation: false, silent: true,
      itemStyle: { color: C.mu, opacity: .45 } });

    return {
      animation: false, backgroundColor: 'transparent', textStyle: { fontFamily: C.font, fontSize: 11, color: C.mu },
      grid: grids, xAxis, yAxis, series,
      axisPointer: { link: [{ xAxisIndex: 'all' }], snap: true },
      tooltip: {
        trigger: 'axis', confine: true, className: 'pc-tt', backgroundColor: C.card, borderColor: C.bd, borderWidth: 1, padding: 0,
        textStyle: { color: C.tx, fontSize: 12 }, extraCssText: 'box-shadow:0 6px 20px rgba(0,0,0,.18);border-radius:8px;',
        axisPointer: { type: 'cross', snap: true, lineStyle: { color: C.mu, type: 'dashed', width: 1 }, crossStyle: { color: C.mu, type: 'dashed', width: 1 } },
        // stay inside the chart box (and so the viewport): beside the cursor, flipped to its left near the right edge, pinned to the top
        position: (pt, _p, _d, _r, size) => {
          const w = size.contentSize[0], vw = size.viewSize[0], x = pt[0] + 16 + w > vw ? pt[0] - w - 16 : pt[0] + 16;
          return [clamp(x, 0, Math.max(0, vw - w)), 6];
        },
        formatter: params => {
          const p = Array.isArray(params) ? params[0] : params;
          if (!p || p.dataIndex == null) return '';
          if (inst.onTip) inst.onTip(p.dataIndex);
          return tipHtml(inst, p.dataIndex);
        },
      },
      dataZoom: [
        { type: 'inside', xAxisIndex: grids.map((_, i) => i), filterMode: 'filter', startValue: s, endValue: e, minValueSpan: Math.min(5, n - 1),
          zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false, throttle: 30 },
        { type: 'slider', xAxisIndex: grids.map((_, i) => i), filterMode: 'filter', startValue: s, endValue: e, minValueSpan: Math.min(5, n - 1),
          height: sliderH, bottom: 6, left, right, brushSelect: false, showDetail: !small, throttle: 30,
          borderColor: C.bd, backgroundColor: 'transparent', fillerColor: alpha(C.ac, .16), handleSize: small ? '110%' : '100%',
          handleStyle: { color: C.card, borderColor: C.ac, borderWidth: 1.5 }, moveHandleStyle: { color: C.ac, opacity: .35 },
          dataBackground: { lineStyle: { color: C.mu, opacity: .6 }, areaStyle: { color: C.mu, opacity: .12 } },
          selectedDataBackground: { lineStyle: { color: C.ac }, areaStyle: { color: C.ac, opacity: .2 } },
          textStyle: { color: C.mu, fontSize: 11 }, labelFormatter: (v) => dateText(D.d[Math.round(v)] || D.d[0], 1) },
      ],
    };
  }

  // ---------- data ----------
  const loads = new Map(), KEEP = 12, indCache = new WeakMap();   // full histories are large: keep the most recent few, always the Nifty
  function getData(sym) {
    if (!loads.has(sym)) {
      while (loads.size >= KEEP) { const old = [...loads.keys()].find(k => k != NIFTY); if (old === undefined) break; loads.delete(old); }
      loads.set(sym, fetch('/api/chart?sym=' + encodeURIComponent(sym)).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
        .catch(e => { loads.delete(sym); throw e; }));
    }
    return loads.get(sym);
  }
  const indicators = d => { let x = indCache.get(d); if (!x) indCache.set(d, x = { sma50: sma(d.c, 50), sma200: sma(d.c, 200), bb: bollinger(d.c, 20, 2) }); return x; };

  // ---------- DOM, state and behaviour (browser only) ----------
  const INSTS = new Set();
  const $q = (el, s) => el.querySelector(s);
  const themeColors = el => {
    const cs = getComputedStyle(el), g = (n, d) => cs.getPropertyValue(n).trim() || d;
    return { card: g('--card', '#fff'), tx: g('--text', '#0f172a'), mu: g('--text-muted', '#64748b'), bd: g('--border', '#e2e8f0'),
      ac: g('--ac', g('--accent', '#14b8a6')), up: g('--up', '#15803d'), dn: g('--dn', '#b91c1c'), amber: g('--pc-amber', '#b45309'),
      s200: g('--s200', '#94a3b8'), blue: g('--pc-blue', '#64748b'), font: cs.fontFamily || 'sans-serif' };
  };

  function dispose(inst) {
    if (inst.dead) return;
    inst.dead = true; INSTS.delete(inst);
    try { inst.ro && inst.ro.disconnect(); } catch (e) { /* ignore */ }
    if (inst.fs) leaveFs(inst, true);
    if (inst.off) inst.off();
    cancelAnimationFrame(inst.raf);
    try { inst.chart && inst.chart.dispose(); } catch (e) { /* ignore */ }
    if (inst.host._pc === inst) inst.host._pc = null;
  }
  const sweep = () => INSTS.forEach(i => { if (!i.host.isConnected) dispose(i); });

  function render(inst) {
    if (inst.dead || !inst.data) return;
    const cv = inst.cv;
    if (!cv.clientWidth || !cv.clientHeight) return;
    if (!inst.chart) {
      inst.chart = echarts.init(cv, null, { renderer: 'canvas' });
      inst.chart.on('datazoom', ev => queueZoom(inst, ev));
      inst.chart.on('globalout', () => { inst.cur = null; setHead(inst); });
    } else inst.chart.resize();
    inst.W = cv.clientWidth; inst.H = cv.clientHeight;
    inst.my = window.MY_POS && window.MY_POS[inst.sym] || null;   // the user's own position, when they hold this stock
    inst.chart.setOption(buildOption(inst, themeColors(inst.host)), true);
    updateUi(inst);
  }

  function setHead(inst) {
    const D = inst.data, s = inst.win[0], i = inst.cur != null ? inst.cur : inst.win[1], host = inst.host;
    const c = D.c[i], ch = c - D.c[s], p = pctSince(D.c, i, s);
    $q(host, '.pc-px').textContent = '₹' + fmt(c);
    const el = $q(host, '.pc-ch');
    el.className = 'pc-ch ' + (ch >= 0 ? 'up' : 'dn');
    const span = inst.rk == 'Max' ? 'all time' : inst.rk ? 'past ' + inst.rk : 'since ' + dateText(D.d[s], 1);
    el.textContent = `${arrow(ch)} ${signed(ch)} (${signed(p)}%) ${span}`;
    $q(host, '.pc-as').textContent = inst.cur != null ? dateText(D.d[i], 1) : 'as of ' + dateText(D.d[D.d.length - 1], 1);
  }

  function legend(inst) {
    const P = inst.prefs, cmp = !!(P.on.cmp && inst.nal), l = [];
    if (cmp) l.push(`<span><i style="background:var(--ac)"></i>${esc(inst.sym)}</span>`, '<span><i class="dash"></i>Nifty 50 (dashed)</span>');
    else {
      if (P.type == 'candle') l.push('<span><i class="hol"></i>Up day (hollow)</span>', '<span><i class="sol"></i>Down day (filled)</span>');
      if (P.on.sma50) l.push('<span><i style="background:var(--pc-amber)"></i>50-day average</span>');
      if (P.on.sma200) l.push('<span><i style="background:var(--s200)"></i>200-day average</span>');
      if (P.on.bb) l.push('<span><i class="dot"></i>Bollinger bands (20 days, 2 deviations)</span>');
      if (P.on.hl52) l.push('<span><i class="dash up"></i>52-week high</span>', '<span><i class="dash dn"></i>52-week low</span>');
      if (inst.my) { l.push('<span><i class="dash tx"></i>Your average buy price</span>'); if (inst.my.lots && inst.my.lots.length) l.push('<span><i class="tri"></i>Your buys</span>', '<span><i class="tri dn"></i>Your sales</span>'); }
    }
    return l.join('');
  }

  function updateUi(inst) {
    const host = inst.host, P = inst.prefs;
    host.querySelectorAll('button[data-k]').forEach(b => {
      const [kind, key] = b.dataset.k.split(':');
      let on = null;
      if (kind == 'r') on = inst.rk == key; else if (kind == 't') on = P.type == key; else if (kind == 'o') on = !!P.on[key];
      if (on !== null) { b.setAttribute('aria-pressed', on); b.classList.toggle('on', on); }
    });
    const cmp = !!(P.on.cmp && inst.nal);
    inst.note = inst.noteMsg || (cmp ? 'Comparing with the Nifty 50: both lines start at 100 at the left edge of the visible range.' +
      (P.type == 'candle' ? ' Candles are replaced by a line while comparing.' : '') : '');
    const note = $q(host, '.pc-note'); note.textContent = inst.note; note.hidden = !inst.note;
    $q(host, '.leg').innerHTML = legend(inst);
    $q(host, '.pc-cv').setAttribute('aria-label', `${inst.sym} price chart, ${inst.rk == 'Max' ? 'all history' : inst.rk || 'custom range'}: ` +
      `from ₹${fmt(inst.data.c[inst.win[0]])} to ₹${fmt(inst.data.c[inst.win[1]])}, ${signed(pctSince(inst.data.c, inst.win[1], inst.win[0]))}%. ` +
      'Use the left and right arrow keys to read each day, plus and minus to zoom.');
    setHead(inst);
    if ($q(host, '.pc-table').open) fillTable(inst);
  }

  function fillTable(inst) {
    const D = inst.data, [s, e] = inst.win, rows = [], tn = Math.min(10, e - s + 1);
    for (let k = 0; k < tn; k++) rows.push(s + Math.round(k / Math.max(1, tn - 1) * (e - s)));
    $q(inst.host, '.pc-tbl').innerHTML = `<caption class="mu">${dateText(D.d[s], 1)} to ${dateText(D.d[e], 1)} (sampled)</caption>` +
      '<tr><th scope="col">Date</th><th scope="col">Open</th><th scope="col">High</th><th scope="col">Low</th><th scope="col">Close</th><th scope="col">Volume</th></tr>' +
      rows.map(i => `<tr><th scope="row">${dateText(D.d[i], 1)}</th><td>${fmt(D.o[i])}</td><td>${fmt(D.h[i])}</td><td>${fmt(D.l[i])}</td><td>${fmt(D.c[i])}</td><td>${vol(D.v[i])}</td></tr>`).join('');
  }

  // zoom or pan (mouse, touch, slider, buttons) arrives here; one update per frame
  function winFromEvent(inst, ev) {
    const p = (ev && ev.batch && ev.batch[0]) || ev || {}, n = inst.data.c.length;
    let s, e;
    if (Number.isFinite(p.startValue) && Number.isFinite(p.endValue)) { s = Math.round(p.startValue); e = Math.round(p.endValue); }
    else if (Number.isFinite(p.start) && Number.isFinite(p.end)) { s = Math.round(p.start / 100 * (n - 1)); e = Math.round(p.end / 100 * (n - 1)); }
    else return null;
    s = clamp(s, 0, n - 1); e = clamp(e, 0, n - 1);
    return s <= e ? [s, e] : null;
  }
  function queueZoom(inst, ev) {
    const w = winFromEvent(inst, ev);
    if (!w) return;
    inst.pendingWin = w;
    if (inst.raf) return;
    inst.raf = requestAnimationFrame(() => {
      inst.raf = 0;
      if (inst.dead || !inst.pendingWin) return;
      applyWin(inst, inst.pendingWin); inst.pendingWin = null;
    });
  }
  function applyWin(inst, w) {
    const prevS = inst.win[0];
    inst.win = w;
    const rk = matchRange(w, inst.data.c.length);
    if (rk !== inst.rk) { inst.rk = rk; inst.prefs.range = rk; savePrefs(); }
    if (inst.prefs.on.cmp && inst.nal && prevS !== w[0])      // rebase both lines to 100 at the new left edge
      inst.chart.setOption({ series: [{ id: 'px', data: rebase(inst.data.c, w[0]) }, { id: 'nifty', data: rebase(inst.nal, w[0]) }] });
    updateUi(inst);
  }
  function setWindow(inst, w) {
    inst.chart.dispatchAction({ type: 'dataZoom', startValue: w[0], endValue: w[1] });
    applyWin(inst, w);
  }

  function say(inst, t) { $q(inst.host, '.sr').textContent = t; }

  // ---------- full screen ----------
  const fsEl = () => document.fullscreenElement || document.webkitFullscreenElement || null;
  function enterFs(inst) {
    if (inst.fs) return;
    const h = inst.host;
    inst.fs = true; inst.native = false;
    inst.fsPrev = { el: document.activeElement, x: window.scrollX, y: window.scrollY };
    h.classList.add('pc-full'); document.documentElement.classList.add('pc-fs-lock');
    h.setAttribute('role', 'dialog'); h.setAttribute('aria-modal', 'true'); h.setAttribute('aria-label', inst.sym + ' price chart, full screen');
    const rq = h.requestFullscreen || h.webkitRequestFullscreen;
    if (rq) try {
      Promise.resolve(rq.call(h)).then(() => {
        if (!inst.fs) { exitNative(); return; }
        inst.native = true;
        try { if (matchMedia('(pointer: coarse)').matches && screen.orientation && screen.orientation.lock) screen.orientation.lock('landscape').catch(() => {}); } catch (e) { /* ignore */ }
      }).catch(() => { /* overlay fallback stays */ });
    } catch (e) { /* overlay fallback stays */ }
    updateFsBtn(inst);
    const b = $q(h, '[data-k="fs"]'); if (b) b.focus();
    resizeSoon(inst);
  }
  function exitNative() { try { if (fsEl()) (document.exitFullscreen || document.webkitExitFullscreen).call(document); } catch (e) { /* ignore */ } }
  function leaveFs(inst, silent) {
    if (!inst.fs) return;
    const h = inst.host, prev = inst.fsPrev;
    inst.fs = false;
    h.classList.remove('pc-full'); document.documentElement.classList.remove('pc-fs-lock');
    ['role', 'aria-modal', 'aria-label'].forEach(a => h.removeAttribute(a));
    if (fsEl() === h) exitNative();
    try { if (screen.orientation && screen.orientation.unlock) screen.orientation.unlock(); } catch (e) { /* ignore */ }
    inst.native = false;
    if (silent) return;
    updateFsBtn(inst);
    if (prev) { window.scrollTo(prev.x, prev.y); const b = $q(h, '[data-k="fs"]'); (b || prev.el) && (b || prev.el).focus({ preventScroll: true }); }
    resizeSoon(inst);
  }
  function updateFsBtn(inst) {
    const b = $q(inst.host, '[data-k="fs"]');
    b.textContent = inst.fs ? 'Exit full screen' : 'Full screen'; b.setAttribute('aria-pressed', !!inst.fs);
  }
  function resizeSoon(inst) {
    // layout settles over a couple of frames (and the orientation lock); the ResizeObserver also catches it
    [0, 120, 400].forEach(t => setTimeout(() => { if (!inst.dead) render(inst); }, t));
  }
  function onDocKey(e) {
    INSTS.forEach(inst => {
      if (!inst.fs) return;
      if (e.key == 'Escape') { e.preventDefault(); leaveFs(inst); }
      else if (e.key == 'Tab') {      // keep focus inside the full screen chart
        const f = [...inst.host.querySelectorAll('button:not([disabled]),summary,[tabindex="0"]')].filter(x => x.offsetParent !== null);
        if (!f.length) return;
        const first = f[0], lastEl = f[f.length - 1], a = document.activeElement;
        if (!inst.host.contains(a)) { e.preventDefault(); first.focus(); }
        else if (e.shiftKey && a === first) { e.preventDefault(); lastEl.focus(); }
        else if (!e.shiftKey && a === lastEl) { e.preventDefault(); first.focus(); }
      }
    });
  }
  function onFsChange() {
    INSTS.forEach(inst => { if (inst.fs && inst.native && fsEl() !== inst.host) leaveFs(inst); });   // the browser's own Esc
  }

  // ---------- theme ----------
  let themeBound = false;
  function bindGlobals() {
    if (themeBound || typeof document === 'undefined') return;
    themeBound = true;
    const again = () => requestAnimationFrame(() => INSTS.forEach(render));
    try { new MutationObserver(again).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] }); } catch (e) { /* ignore */ }
    try { const mq = matchMedia('(prefers-color-scheme: dark)'); mq.addEventListener ? mq.addEventListener('change', again) : mq.addListener(again); } catch (e) { /* ignore */ }
    document.addEventListener('keydown', onDocKey, true);
    document.addEventListener('fullscreenchange', onFsChange); document.addEventListener('webkitfullscreenchange', onFsChange);
    addEventListener('orientationchange', () => INSTS.forEach(resizeSoon));
  }

  // ---------- mount ----------
  const seg = (label, btns) => `<div class="pc-seg" role="group" aria-label="${label}">${btns}</div>`;
  function skeleton(inst) {
    const b = (k, t, extra) => `<button type="button" data-k="${k}" aria-pressed="false"${extra || ''}>${t}</button>`;
    return `<div class="pc-head"><span class="pc-px"></span><span class="pc-ch"></span><span class="pc-as mu"></span>` +
      `<button type="button" class="chip pc-fsb" data-k="fs" aria-pressed="false">Full screen</button></div>` +
      `<div class="pc-tools">` +
      `<div class="pc-bar">${seg('Timeframe', RANGES.map(r => b('r:' + r[0], r[0])).join(''))}` +
      `<div class="pc-seg" role="group" aria-label="Zoom"><button type="button" data-k="z:out" aria-label="Zoom out">−</button><button type="button" data-k="z:in" aria-label="Zoom in">+</button><button type="button" data-k="z:reset">Reset</button></div>` +
      seg('Chart type', TYPES.map(t => b('t:' + t[0], t[1])).join('')) + `</div>` +
      `<div class="pc-chips" role="group" aria-label="Chart overlays">${OVERS.map(o => `<button type="button" class="chip" data-k="o:${o[0]}" aria-pressed="false">${o[1]}</button>`).join('')}</div></div>` +
      `<p class="hint pc-note" role="note" hidden></p>` +
      `<div class="pc-plot"><div class="pc-cv" tabindex="0" role="img" aria-label="${esc(inst.sym)} price chart"></div></div>` +
      `<div class="leg"></div><div class="sr" role="status" aria-live="polite"></div>` +
      `<p class="mu pc-disc">Prices are adjusted for splits and dividends. Scroll or pinch to zoom, drag to pan. For research and education. Not investment advice.</p>` +
      `<details class="more pc-table"><summary>Show price data as a table</summary><div class="of"><table class="mini pc-tbl"></table></div></details>`;
  }

  function wire(inst) {
    const host = inst.host, cv = inst.cv, n = inst.data.c.length;
    const onClick = ev => {
      const btn = ev.target.closest && ev.target.closest('button[data-k]');
      if (!btn || !host.contains(btn) || !inst.chart) return;
      const [kind, key] = btn.dataset.k.split(':'), P = inst.prefs;
      if (kind == 'r') { P.range = key; setWindow(inst, rangeWindow(key, n)); }
      else if (kind == 'z') setWindow(inst, key == 'reset' ? rangeWindow(DEF.range, n) : zoomWindow(inst.win, n, key == 'in' ? .5 : 2));
      else if (kind == 't') { P.type = key; savePrefs(); render(inst); }
      else if (kind == 'o') {
        P.on[key] = !P.on[key]; savePrefs();
        if (key == 'cmp' && P.on.cmp && !inst.nal) return loadNifty(inst);
        render(inst);
      } else if (btn.dataset.k == 'fs') inst.fs ? leaveFs(inst) : enterFs(inst);
    };
    host.addEventListener('click', onClick); inst.off = () => host.removeEventListener('click', onClick);
    $q(host, '.pc-table').addEventListener('toggle', () => { if ($q(host, '.pc-table').open) fillTable(inst); });
    inst.onTip = i => { inst.cur = i; clearTimeout(inst.headT); inst.headT = setTimeout(() => setHead(inst), 0); };
    cv.addEventListener('keydown', ev => {
      const [s, e] = inst.win, cur = inst.cur != null ? inst.cur : e, step = ev.shiftKey ? 5 : 1;
      let to = null;
      if (ev.key == 'ArrowRight') to = cur + step; else if (ev.key == 'ArrowLeft') to = cur - step;
      else if (ev.key == 'Home') to = s; else if (ev.key == 'End') to = e;
      else if (ev.key == '+' || ev.key == '=') { ev.preventDefault(); return setWindow(inst, zoomWindow(inst.win, n, .5)); }
      else if (ev.key == '-') { ev.preventDefault(); return setWindow(inst, zoomWindow(inst.win, n, 2)); }
      else if (ev.key == '0') { ev.preventDefault(); return setWindow(inst, rangeWindow(DEF.range, n)); }
      if (to == null) return;
      ev.preventDefault();
      const i = clamp(to, s, e); inst.cur = i;
      inst.chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: i });
      setHead(inst); say(inst, readout(inst, i));
    });
    cv.addEventListener('focus', () => { if (inst.cur == null) say(inst, 'Chart focused. ' + $q(host, '.pc-ch').textContent); });
    cv.addEventListener('blur', () => { inst.cur = null; setHead(inst); });
    if (window.ResizeObserver) {
      let t;
      inst.ro = new ResizeObserver(() => {
        sweep();
        if (inst.dead) return;
        cancelAnimationFrame(t); t = requestAnimationFrame(() => render(inst));
      });
      inst.ro.observe(cv);
    }
  }

  function loadNifty(inst) {
    inst.noteMsg = 'Loading the Nifty 50…'; render(inst);
    getData(NIFTY).then(nf => {
      if (inst.dead) return;
      inst.nal = align(inst.data.d, nf); inst.noteMsg = ''; render(inst);
    }).catch(() => {
      if (inst.dead) return;
      inst.prefs.on.cmp = false; inst.noteMsg = 'The Nifty 50 history could not be loaded, so the comparison is off.'; render(inst);
    });
  }

  // ECharts is about 1 MB, so pages that only show a chart when a row is opened load it the first time one is needed
  let ecLoad = null;
  const withEcharts = () => (typeof window !== 'undefined' && window.echarts) || typeof echarts !== 'undefined' ? Promise.resolve() :
    (ecLoad || (ecLoad = new Promise((ok, no) => {
      const sc = document.createElement('script'); sc.src = '/assets/js/echarts.min.js'; sc.onload = ok;
      sc.onerror = () => { ecLoad = null; sc.remove(); no(new Error('ECharts could not be loaded')); };
      document.head.appendChild(sc);
    })));

  function mount(host) {
    if (!host || host._pc) return;
    sweep(); bindGlobals();
    const sym = host.dataset.sym;
    const inst = host._pc = { host, sym, data: null, nal: null, prefs, win: [0, 0], rk: '', cur: null, noteMsg: '' };
    host.innerHTML = '<div class="load pc-msg"><i></i>Loading price history…</div>';
    const fail = () => {
      host.innerHTML = '<p class="pc-msg">Price history could not be loaded. <button type="button" class="chip" data-k="retry">Try again</button></p>';
      host.querySelector('button').onclick = () => { host._pc = null; mount(host); };
    };
    Promise.all([getData(sym), withEcharts()]).then(([d]) => {
      if (!host.isConnected || host._pc !== inst) return;
      if (!d || !d.c || d.c.length < MIN_BARS || !d.d || d.d.length != d.c.length) {
        host.innerHTML = '<p class="pc-msg">Not enough price history to draw a chart yet.</p>'; host._pc = null; return;
      }
      inst.data = d; inst.ind = indicators(d);
      inst.rk = prefs.range || DEF.range; inst.win = rangeWindow(inst.rk, d.c.length);
      if (matchRange(inst.win, d.c.length) !== inst.rk) inst.rk = matchRange(inst.win, d.c.length);
      host.innerHTML = skeleton(inst);
      inst.cv = $q(host, '.pc-cv');
      INSTS.add(inst);
      wire(inst);
      const go = () => { if (!inst.dead) render(inst); };
      if (prefs.on.cmp) getData(NIFTY).then(nf => { inst.nal = align(d.d, nf); go(); }).catch(() => { prefs.on.cmp = false; go(); });
      else go();
    }).catch(fail);
  }

  const redraw = host => { const i = host && host._pc; if (i && i.data && !i.dead) render(i); };
  const api = { mount, redraw, _t: { sma, bollinger, align, rangeCount, RANGES, rangeWindow, matchRange, zoomWindow, window52, rebase, pctSince,
    fmt, vol, compactVol, signed, axisFmt, buildOption, tipHtml, readout, candles, winFromEvent } };
  (typeof window !== 'undefined' ? window : globalThis).PriceChart = api;
  if (typeof module !== 'undefined') module.exports = api;
})();

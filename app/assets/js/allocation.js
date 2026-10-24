/* Allocation donut: how the portfolio's current value splits across stocks or sectors.
   One hue (the accent) stepped from dark to light by size, a neutral for "Other", 2px gaps between segments, and every segment named
   with its share in the list beside it, so nothing depends on telling the shades apart. */
(function () {
  'use strict';
  function E(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  // rows: [{label, value}] -> the five largest then "Other"; zero and missing values are left out
  function slices(rows, max) {
    max = max || 6;
    var r = rows.filter(function (x) { return x.value > 0; }).sort(function (a, b) { return b.value - a.value; });
    var tot = r.reduce(function (a, x) { return a + x.value; }, 0);
    var top = r.slice(0, max - 1), rest = r.slice(max - 1);
    if (rest.length === 1) top.push(rest[0]); else if (rest.length) top.push({ label: 'Other (' + rest.length + ')', value: rest.reduce(function (a, x) { return a + x.value; }, 0), other: true });
    return { total: tot, items: top.map(function (x) { return { label: x.label, value: x.value, pct: tot ? x.value / tot * 100 : 0, other: !!x.other, none: !!x.none }; }) };
  }

  function donutHtml(rows, opts) {
    opts = opts || {};
    var s = slices(rows, 6);
    if (!s.total) return '<p class="pf-empty">Values appear once prices are available.</p>';
    var R = 52, C = 2 * Math.PI * R, gap = 2, acc = 0, steps = [1, .78, .6, .46, .34, .25];
    var segs = s.items.map(function (it, i) {
      var len = Math.max(0.5, it.pct / 100 * C - gap), off = -acc; acc += it.pct / 100 * C;
      var style = it.other || it.none ? 'stroke:var(--neutral-series-2)' : 'stroke:var(--accent);opacity:' + (steps[i] || .25);
      return '<circle class="dn-seg" data-i="' + i + '" cx="70" cy="70" r="' + R + '" fill="none" stroke-width="18" stroke-dasharray="' + len.toFixed(2) + ' ' + (C - len).toFixed(2) + '" stroke-dashoffset="' + off.toFixed(2) + '" style="' + style + '"><title>' + E(it.label) + ': ' + it.pct.toFixed(1) + '%</title></circle>';
    }).join('');
    var label = 'Allocation by ' + (opts.by || 'stock') + ': ' + s.items.map(function (x) { return x.label + ' ' + x.pct.toFixed(0) + '%'; }).join(', ');
    var list = s.items.map(function (it, i) {
      var sw = it.other || it.none ? 'background:var(--neutral-series-2)' : 'background:var(--accent);opacity:' + (steps[i] || .25);
      return '<li data-i="' + i + '"><i style="' + sw + '"></i><span class="dn-n">' + E(it.label) + '</span><b>' + it.pct.toFixed(1) + '%</b></li>';
    }).join('');
    return '<div class="donut"><svg viewBox="0 0 140 140" role="img" aria-label="' + E(label) + '"><g transform="rotate(-90 70 70)">' + segs + '</g>' +
      '<text x="70" y="66" text-anchor="middle" class="dn-c1">' + (opts.centerTop || '') + '</text><text x="70" y="84" text-anchor="middle" class="dn-c2">' + (opts.centerBottom || '') + '</text></svg><ul class="dn-l">' + list + '</ul></div>';
  }

  // wires hover and focus between the list and the ring
  function bind(el) {
    el.querySelectorAll('.dn-l li').forEach(function (li) {
      var on = function (v) { el.querySelectorAll('.dn-seg').forEach(function (c) { c.classList.toggle('dim', v && c.dataset.i !== li.dataset.i); }); li.classList.toggle('hot', v); };
      li.addEventListener('mouseenter', function () { on(true); }); li.addEventListener('mouseleave', function () { on(false); });
    });
  }

  window.Allocation = { slices: slices, html: donutHtml, bind: bind };
  if (typeof module !== 'undefined' && module.exports) module.exports = { slices: slices };
})();

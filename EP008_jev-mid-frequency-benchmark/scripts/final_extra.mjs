// EP009 终版补充指标（探索性分析）：在正式场全量数据上算
import fs from 'node:fs';
const dir = process.argv[2];
const recs = fs.readFileSync(dir + '/decisions.jsonl', 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l)).sort((a, b) => a.t - b.t);
const T = Float64Array.from(recs, d => d.t), M = Float64Array.from(recs, d => d.mid0);
const idxAt = x => { let lo = 0, hi = T.length; while (lo < hi) { const m = (lo + hi) >> 1; if (T[m] < x) lo = m + 1; else hi = m; } return lo; };
// 从 t0（中间价 mid）起 h 秒后的收益（bps）；目标时刻附近 1 秒内没有记录（中断）就不算
const fwd = (t0, mid, h) => { const x = t0 + h * 1000, i = idxAt(x); if (i >= T.length || T[i] - x > 1000) return null; return (M[i] - mid) / mid * 1e4; };
const pv = (d, a, h = 30) => { const v = d.p?.[a]; return v == null ? null : typeof v === 'number' ? v : v[h]; };
const J = recs.filter(d => d.p?.jev && d.jev?.done != null && d.jev.mid1 != null);
const corr = (x, y) => { const n = x.length; let sx = 0, sy = 0; for (let i = 0; i < n; i++) { sx += x[i]; sy += y[i]; } const mx = sx / n, my = sy / n; let a = 0, b = 0, c = 0; for (let i = 0; i < n; i++) { const dx = x[i] - mx, dy = y[i] - my; a += dx * dy; b += dx * dx; c += dy * dy; } return a / Math.sqrt(b * c); };
const rank = x => { const o = Array.from(x, (v, i) => [v, i]).sort((a, b) => a[0] - b[0]); const r = new Float64Array(x.length); o.forEach(([, i], k) => r[i] = k); return r; };
const pct = (h, n) => +(h / n * 100).toFixed(1);
const out = {n: recs.length, jevAnswered: J.length, hours: +((T[T.length - 1] - T[0]) / 3.6e6).toFixed(2)};

// 1) 信号衰减：Jev 从答完时刻、以答完时的中间价起算；规则从决策时刻起算
out.decay = {};
for (const h of [0.6, 1, 2, 3, 5, 10, 30, 60]) {
  const r = {};
  for (const who of ['jev', 'obi1', 'obi20', 'mock']) {
    const xs = [], ys = []; let n = 0, hit = 0;
    for (const d of J) {
      const t0 = who === 'jev' ? d.jev.done : d.t, mid = who === 'jev' ? d.jev.mid1 : d.mid0;
      const f = fwd(t0, mid, h); if (f == null) continue; const p = who === 'jev' ? d.p.jev[Math.max(3, h <= 3 ? 3 : h <= 10 ? 10 : h <= 30 ? 30 : 60)] : pv(d, who);
      xs.push(p - .5); ys.push(f); if (f !== 0) { n++; if ((p >= .5) === (f > 0)) hit++; }
    }
    r[who] = {hit: pct(hit, n), n, rankIC: +corr(rank(xs), rank(ys)).toFixed(3)};
  }
  out.decay[h + 's'] = r;
}

// 2) 一致率 + 打架时跟谁
const RULES = ['obi1', 'ofi', 'obi20', 'cvd', 'mom5', 'rev20', 'vwap', 'mock', 'coin'];
out.agree = Object.fromEntries(RULES.map(a => { let n = 0, s = 0; for (const d of J) { const q = pv(d, a); if (q == null) continue; n++; if ((q >= .5) === (d.p.jev[30] >= .5)) s++; } return [a, pct(s, n)]; }));
out.conflictFollowTFI = Object.fromEntries(['obi1', 'obi20', 'ofi'].map(b => { let n = 0, f = 0; for (const d of J) { const c = pv(d, 'cvd') >= .5, o = pv(d, b) >= .5; if (c === o) continue; n++; if ((d.p.jev[30] >= .5) === c) f++; } return [b, {n, pct: pct(f, n)}]; }));

// 3) 分歧时听谁的（同一时刻、同一结果，按发问时刻）
for (const h of [3, 30]) {
  let n = 0, jr = 0;
  for (const d of J) { const o = d.out?.[h]; if (!o || o === 'flat') continue; const j = d.p.jev[h] >= .5, q = pv(d, 'obi1') >= .5; if (j === q) continue; n++; if (j === (o === 'up')) jr++; }
  out['disagreeQI_' + h + 's'] = {n, jevRight: pct(jr, n), qiRight: pct(n - jr, n)};
}

// 4) 理论收益与延迟拆解（零手续费，每人持 1 单位，按中间价逐点累计；相邻点隔 >10s 不累计）
function eq(who, sched, delay) {
  let prev = null, lastT = null, e = 0, pos = 0, flips = 0; const q = [];
  const set = s => { if (s !== pos) { if (pos !== 0) flips++; pos = s; } };
  for (const d of recs) {
    if (prev != null && d.t - lastT <= 10000) e += pos * (d.mid0 - prev) / prev * 1e4;
    prev = d.mid0; lastT = d.t;
    while (q.length && q[0].done <= d.t) set(q.shift().s);
    const answered = d.p?.jev && d.jev?.done != null;
    if (sched === 'every' || answered) { const s = pv(d, who) >= .5 ? 1 : -1; if (delay && answered) q.push({done: d.jev.done, s}); else set(s); }
  }
  return {pnlBps: Math.round(e), flips, perFlipBps: +(e / flips).toFixed(3)};
}
out.equity = {};
for (const w of ['obi1', 'obi20', 'mock', 'ofi', 'cvd', 'coin']) out.equity[w] = {every: eq(w, 'every', false), jevTicks: eq(w, 'jevTicks', false), jevTicksDelayed: eq(w, 'jevTicks', true)};
out.equity.jev = {jevTicks: eq('jev', 'jevTicks', false), real: eq('jev', 'jevTicks', true)};

// 5) 概率质量（Jev 30 秒，按答完时刻）
{ let b = 0, ll = 0, n = 0; const ps = [], ys = [];
  for (const d of J) { const o = d.after?.jev?.[30]; if (!o || o === 'flat') continue; const y = o === 'up' ? 1 : 0, p = Math.min(.999, Math.max(.001, d.p.jev[30])); b += (p - y) ** 2; ll += -(y * Math.log(p) + (1 - y) * Math.log(1 - p)); n++; ps.push(p); ys.push(y); }
  const base = ys.reduce((s, y) => s + y, 0) / n; let bb = 0; for (const y of ys) bb += (base - y) ** 2;
  const r = rank(ps); let rs = 0, np = 0; for (let i = 0; i < ys.length; i++) if (ys[i]) { rs += r[i] + 1; np++; } const nn = ys.length - np;
  let hi = 0; for (const p of ps) if (p >= .9 || p < .1) hi++;
  out.probQuality = {n, brier: +(b / n).toFixed(4), brierAlways50: .25, brierClimatology: +(bb / n).toFixed(4), logLoss: +(ll / n).toFixed(3), logLossAlways50: +Math.log(2).toFixed(3), auc: +((rs - np * (np + 1) / 2) / (np * nn)).toFixed(3), shareOver90: pct(hi, n)}; }

// 6) 按行情激烈程度分三档（最近 100 个决策点的已实现波动）
{ const vol = new Float64Array(recs.length).fill(NaN); let s = 0; const r2 = new Float64Array(recs.length);
  for (let i = 1; i < recs.length; i++) r2[i] = ((M[i] - M[i - 1]) / M[i - 1] * 1e4) ** 2;
  for (let i = 1; i < recs.length; i++) { s += r2[i]; if (i > 100) s -= r2[i - 100]; if (i >= 100) vol[i] = Math.sqrt(s); }
  const iOf = new Map(recs.map((d, i) => [d, i]));
  const vs = J.map(d => vol[iOf.get(d)]).filter(v => !Number.isNaN(v)).sort((a, b) => a - b), q1 = vs[Math.floor(vs.length / 3)], q2 = vs[Math.floor(vs.length * 2 / 3)];
  const acc = {};
  for (const d of J) { const v = vol[iOf.get(d)]; if (Number.isNaN(v)) continue; const g = v < q1 ? 'low' : v < q2 ? 'mid' : 'high';
    for (const h of [3, 30]) { const o = d.out?.[h], oj = d.after?.jev?.[h]; const A = (acc[g + h] ||= {jev: [0, 0], qi: [0, 0], coin: [0, 0]});
      if (oj && oj !== 'flat') { A.jev[0]++; if ((d.p.jev[h] >= .5) === (oj === 'up')) A.jev[1]++; }
      if (o && o !== 'flat') { A.qi[0]++; if ((pv(d, 'obi1') >= .5) === (o === 'up')) A.qi[1]++; A.coin[0]++; if ((pv(d, 'coin') >= .5) === (o === 'up')) A.coin[1]++; } } }
  out.volRegime = {cutBps: [+q1.toFixed(2), +q2.toFixed(2)], ...Object.fromEntries(Object.entries(acc).map(([k, v]) => [k, {jev: pct(v.jev[1], v.jev[0]), qi: pct(v.qi[1], v.qi[0]), coin: pct(v.coin[1], v.coin[0]), n: v.jev[0]}]))}; }

// 7) 挂单：成交 / 没成交的判断准确率（保守口径成交，30 秒；Jev 按答完、规则按决策时刻）
out.fillConditional = {};
for (const who of ['jev', 'obi1', 'coin']) {
  const g = {filled: [0, 0], unfilled: [0, 0]};
  for (const d of (who === 'jev' ? J : recs)) { const m = d.mk?.[who], o = who === 'jev' ? d.after?.jev?.[30] : d.out?.[30]; if (!m || !o || o === 'flat') continue; const k = m.tc != null ? 'filled' : 'unfilled'; g[k][0]++; if ((m.side === 'buy') === (o === 'up')) g[k][1]++; }
  out.fillConditional[who] = Object.fromEntries(Object.entries(g).map(([k, [n, h]]) => [k, {n, hit: pct(h, n)}]));
}

// 8) 手续费墙：各时长平均绝对涨跌，及挂单 4bps / 吃单 10bps 回本要多准：p = (1 + fee / 平均涨跌) / 2
out.feeWall = {};
for (const h of [10, 30, 60, 300, 900]) { let s = 0, n = 0; for (let i = 0; i < recs.length; i += 10) { const f = fwd(T[i], M[i], h); if (f == null) continue; s += Math.abs(f); n++; }
  const m = s / n, need = fee => fee >= m ? '不可能' : pct((1 + fee / m) / 2 * 1000, 1000);
  out.feeWall[h + 's'] = {avgAbsBps: +m.toFixed(2), makerNeed: need(4), takerNeed: need(10)}; }

// 9) 修 bug 前后对比用：说涨比例、市场上涨比例
{ let up = 0; for (const d of J) if (d.p.jev[30] >= .5) up++; let mu = 0, mt = 0; for (const d of recs) { const o = d.out?.[30]; if (o && o !== 'flat') { mt++; if (o === 'up') mu++; } }
  out.upBias = {jevUp: pct(up, J.length), marketUp: pct(mu, mt)}; }
console.log(JSON.stringify(out, null, 1));

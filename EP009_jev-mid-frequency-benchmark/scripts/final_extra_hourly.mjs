// EP009 探索性补算（二）：逐小时对打、增量价值（前 12h 拟合 / 后 12h 检验）、理论曲线回撤。用法：node final_extra_hourly.mjs <run 目录>
import fs from 'node:fs';
const recs = fs.readFileSync(process.argv[2] + '/decisions.jsonl', 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l)).sort((a, b) => a.t - b.t);
const pv = (d, a, h = 30) => { const v = d.p?.[a]; return v == null ? null : typeof v === 'number' ? v : v[h]; };
const J = recs.filter(d => d.p?.jev && d.jev?.done != null);
const t0 = recs[0].t, hourOf = t => Math.floor((t - t0) / 3.6e6);
const out = {};

// ① 逐小时：Jev（答完起算）vs QI（决策时刻起算），30 秒和 3 秒
for (const h of [3, 30]) {
  const H = {};
  for (const d of J) { const k = hourOf(d.t), A = (H[k] ||= {j: [0, 0], q: [0, 0]});
    const oj = d.after?.jev?.[h], o = d.out?.[h];
    if (oj && oj !== 'flat') { A.j[0]++; if ((d.p.jev[h] >= .5) === (oj === 'up')) A.j[1]++; }
    if (o && o !== 'flat') { A.q[0]++; if ((pv(d, 'obi1') >= .5) === (o === 'up')) A.q[1]++; } }
  const rows = Object.entries(H).map(([k, A]) => [+k, A.j[1] / A.j[0], A.q[1] / A.q[0]]);
  out['hourly' + h] = {series: rows.map(r => [r[0], +(r[1] * 100).toFixed(2), +(r[2] * 100).toFixed(2)]), hours: rows.length, jevWins: rows.filter(r => r[1] > r[2]).length, jevMin: +(Math.min(...rows.map(r => r[1])) * 100).toFixed(1), jevMax: +(Math.max(...rows.map(r => r[1])) * 100).toFixed(1), qiMin: +(Math.min(...rows.map(r => r[2])) * 100).toFixed(1)};
}

// ② 增量价值：前 12 小时拟合逻辑回归，后 12 小时检验（按发问时刻、同一批点、同一结果）
function fit(X, y, iters = 30) {   // 牛顿法，带截距
  const k = X[0].length + 1; let w = new Array(k).fill(0);
  for (let it = 0; it < iters; it++) {
    const g = new Array(k).fill(0), Hm = Array.from({length: k}, () => new Array(k).fill(0));
    for (let i = 0; i < X.length; i++) { const x = [1, ...X[i]]; let z = 0; for (let a = 0; a < k; a++) z += w[a] * x[a]; const p = 1 / (1 + Math.exp(-z)), r = p * (1 - p);
      for (let a = 0; a < k; a++) { g[a] += (y[i] - p) * x[a]; for (let b = 0; b < k; b++) Hm[a][b] += r * x[a] * x[b]; } }
    // 解 Hm·d = g
    const M = Hm.map((row, i) => [...row, g[i]]);
    for (let c = 0; c < k; c++) { let pvt = c; for (let r = c + 1; r < k; r++) if (Math.abs(M[r][c]) > Math.abs(M[pvt][c])) pvt = r; [M[c], M[pvt]] = [M[pvt], M[c]];
      for (let r = 0; r < k; r++) if (r !== c) { const f = M[r][c] / M[c][c]; for (let cc = c; cc <= k; cc++) M[r][cc] -= f * M[c][cc]; } }
    w = w.map((v, i) => v + M[i][k] / M[i][i]);
  }
  return w;
}
const logit = p => Math.log(Math.min(.999, Math.max(.001, p)) / (1 - Math.min(.999, Math.max(.001, p))));
for (const h of [3, 30]) {
  const rows = [];
  for (const d of J) { const o = d.out?.[h]; if (!o || o === 'flat') continue; rows.push({t: d.t, q: logit(pv(d, 'obi1')), j: logit(d.p.jev[h]), c: logit(pv(d, 'cvd')), m: logit(pv(d, 'mock')), y: o === 'up' ? 1 : 0}); }
  const mid = t0 + 12 * 3.6e6, tr = rows.filter(r => r.t < mid), te = rows.filter(r => r.t >= mid);
  const acc = (feats) => { const w = fit(tr.map(r => feats.map(f => r[f])), tr.map(r => r.y)); let n = 0, hit = 0;
    for (const r of te) { let z = w[0]; feats.forEach((f, i) => z += w[i + 1] * r[f]); n++; if ((z >= 0) === (r.y === 1)) hit++; } return {hit: +(hit / n * 100).toFixed(2), w: w.map(v => +v.toFixed(3))}; };
  out['incremental' + h] = {train: tr.length, test: te.length, QI: acc(['q']), Jev: acc(['j']), QI_Jev: acc(['q', 'j']), QI_TFI_BASE: acc(['q', 'c', 'm']), QI_TFI_BASE_Jev: acc(['q', 'c', 'm', 'j'])};
}

// ③ 理论曲线（零手续费）：逐小时收益为正的小时数、最大回撤（bps）
function curve(who) {
  let prev = null, lastT = null, e = 0, pos = 0, peak = 0, mdd = 0; const q = [], hourly = {};
  for (const d of recs) {
    if (prev != null && d.t - lastT <= 10000) { const r = pos * (d.mid0 - prev) / prev * 1e4; e += r; const k = hourOf(d.t); hourly[k] = (hourly[k] || 0) + r; }
    prev = d.mid0; lastT = d.t; peak = Math.max(peak, e); mdd = Math.max(mdd, peak - e);
    if (who === 'jev') { while (q.length && q[0].done <= d.t) pos = q.shift().s; if (d.p?.jev && d.jev?.done != null) q.push({done: d.jev.done, s: d.p.jev[30] >= .5 ? 1 : -1}); }
    else pos = pv(d, who) >= .5 ? 1 : -1;
  }
  const hv = Object.values(hourly);
  return {pnl: Math.round(e), maxDD: Math.round(mdd), posHours: hv.filter(v => v > 0).length, hours: hv.length, worstHour: Math.round(Math.min(...hv))};
}
out.curves = Object.fromEntries(['jev', 'obi1', 'mock', 'coin'].map(w => [w, curve(w)]));
console.log(JSON.stringify(out, null, 1));

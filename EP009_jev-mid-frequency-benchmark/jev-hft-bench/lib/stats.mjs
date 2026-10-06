// 从决策记录算出看板和分析要的全部数字。实时、回放、事后分析共用这一份，保证三处口径一致。
// 每条记录里的字段都带时间；传入 now 后，只统计「那一刻已经知道」的东西（回放就是靠这个一帧帧放出来的）。

export const H = [3, 10, 30, 60];     // 预测时长（秒），与 models.mjs 的 FAST_H 保持一致
export const MODELS = ['jev', 'ds'];  // 要等它答完的两个模型；其余都是规则，决策那一刻就有答案

// 有哪些对照组，从数据里看，不写死（以后加规则不用改这里）
export function armsOf(records) {
  const s = new Set();
  for (const d of records) for (const k in d.p) s.add(k);
  return [...MODELS.filter(m => s.has(m)), ...[...s].filter(k => !MODELS.includes(k))];
}

export const quantile = (xs, p) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(s.length * p))];
};

// Wilson 区间：看板上给个粗略范围。注意相邻决策点的预测窗口高度重叠，真实区间更宽，严格的看 analyze.mjs 的分块自助法
export function wilson(hit, n, z = 1.96) {
  if (!n) return null;
  const p = hit / n, d = 1 + z * z / n, c = p + z * z / (2 * n), r = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n));
  return [(c - r) / d, (c + r) / d];
}

// 某条记录在 now 时刻对外可见的样子
export function visible(d, now) {
  const jevDone = d.jev?.done != null && d.jev.done <= now, dsDone = d.ds?.done != null && d.ds.done <= now;
  const out = {}, after = {jev: {}, ds: {}};
  for (const h of H) {
    if (d.out?.[h] && d.t + h * 1000 <= now) out[h] = d.out[h];
    if (jevDone && d.after?.jev?.[h] && d.jev.done + h * 1000 <= now) after.jev[h] = d.after.jev[h];
    if (dsDone && d.after?.ds?.[h] && d.ds.done + h * 1000 <= now) after.ds[h] = d.after.ds[h];
  }
  return {
    jevDone, dsDone, out, after,
    pnlJev: jevDone && d.pnl?.jev != null && d.jev.done + 30000 <= now ? d.pnl.jev : null,
    pnlDs: dsDone && d.pnl?.ds != null && d.ds.done + 30000 <= now ? d.pnl.ds : null,
    jevErr: d.jev?.err && (d.jev.errAt ?? d.t) <= now ? d.jev.err : null,
    dsErr: d.ds?.err && (d.ds.errAt ?? d.t) <= now ? d.ds.err : null,
  };
}

const up = (p, dir) => (p >= 0.5) === (dir === 'up');
// 规则类选手的概率跟时长无关，落盘时只存一个数；模型按时长各存一个。这里统一读
export const pOf = (d, arm, h) => { const v = d.p?.[arm]; return v == null ? null : typeof v === 'number' ? v : v[h] ?? null; };

export function computeStats(records, now, {feeBps = 0, arms = null} = {}) {
  const ARMS = arms || armsOf(records);
  const hit = Object.fromEntries(ARMS.map(a => [a, Object.fromEntries(H.map(h => [h, {n: 0, hit: 0, flat: 0}]))]));
  const pnlAll = Object.fromEntries(ARMS.map(a => [a, []]));
  const hitReal = {jev: Object.fromEntries(H.map(h => [h, {n: 0, hit: 0}])), ds: Object.fromEntries(H.map(h => [h, {n: 0, hit: 0}]))};
  const lat = [], dsLat = [], move = [], errs = {}, dsErrs = {};
  const probs = [];
  let points = 0, sent = 0, late = 0, dsSent = 0, dsSkipped = 0;
  for (const d of records) {
    if (d.t > now) break;
    points++;
    const v = visible(d, now);
    if (d.late) late++;
    if (d.jev) sent++;
    if (d.dsSkipped) dsSkipped++;
    if (d.ds) dsSent++;
    if (v.jevErr) errs[v.jevErr] = (errs[v.jevErr] || 0) + 1;
    if (v.dsErr) dsErrs[v.dsErr] = (dsErrs[v.dsErr] || 0) + 1;
    if (v.jevDone && d.p.jev) {
      lat.push(d.jev.done - d.t); probs.push(d.p.jev[30]);
      if (d.jev.mid1 != null) move.push(Math.abs(d.jev.mid1 - d.mid0) / d.mid0 * 1e4);
    }
    if (v.dsDone && d.p.ds) dsLat.push(d.ds.done - d.t);
    for (const h of H) {
      const o = v.out[h];
      if (o) for (const a of ARMS) {
        const p = pOf(d, a, h);
        if (p == null || (a === 'jev' && !v.jevDone) || (a === 'ds' && !v.dsDone)) continue;
        const A = hit[a][h];
        if (o === 'flat') { A.flat++; continue; }
        A.n++; if (up(p, o)) A.hit++;
      }
      for (const a of ['jev', 'ds']) {
        const o2 = v.after[a][h];
        if (!o2 || o2 === 'flat' || pOf(d, a, h) == null) continue;
        hitReal[a][h].n++; if (up(pOf(d, a, h), o2)) hitReal[a][h].hit++;
      }
    }
    if (v.pnlJev != null) pnlAll.jev?.push(v.pnlJev);
    if (v.pnlDs != null) pnlAll.ds?.push(v.pnlDs);
    for (const a of ARMS) {   // 规则类：决策那一刻进场，30 秒后平仓
      if (MODELS.includes(a) || d.pnl?.[a] == null || d.t + 30000 > now) continue;
      pnlAll[a].push(d.pnl[a]);
    }
  }
  const mean = xs => xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null;
  const pnlOf = xs => ({n: xs.length, grossBps: mean(xs), netBps: xs.length ? mean(xs) - 2 * feeBps : null, winRate: xs.length ? xs.filter(x => x > 0).length / xs.length : null});
  const withCi = o => { for (const a in o) for (const h in o[a]) o[a][h].ci = wilson(o[a][h].hit, o[a][h].n); return o; };
  // Jev 给的「30 秒后涨」概率分布：看它是不是动不动就 0.01 / 0.99
  const bins = [[0, .1], [.1, .3], [.3, .5], [.5, .7], [.7, .9], [.9, 1]].map(([lo, hi]) => ({lo, hi, n: 0}));
  for (const p of probs) { const b = bins.find(b => p >= b.lo && p < b.hi) || bins.at(-1); b.n++; }
  return {
    points, sent, late, lateRate: points ? late / points : null,
    errors: errs, errorCount: Object.values(errs).reduce((s, x) => s + x, 0),
    lat: {p50: quantile(lat, .5), p90: quantile(lat, .9), p99: quantile(lat, .99), n: lat.length},
    moveDuringBps: mean(move),
    hit: withCi(hit), hitReal: withCi(hitReal),
    arms: ARMS,
    pnl: {...Object.fromEntries(ARMS.map(a => [a, pnlOf(pnlAll[a])])), feeBps},
    probBins: bins,
    ds: dsSent || dsSkipped ? {sent: dsSent, skipped: dsSkipped, errors: dsErrs, lat: {p50: quantile(dsLat, .5), p90: quantile(dsLat, .9), n: dsLat.length}} : null,
  };
}

// 最近几次 DeepSeek 抽样（它每 15 秒才一次、一答几十秒，得单独拎出来）
export function recentDs(records, now, n = 8) {
  const out = [];
  for (let i = records.length - 1; i >= 0 && out.length < n; i--) {
    const d = records[i]; if (d.t > now || !d.ds) continue;
    const v = visible(d, now);
    out.push({t: d.t, pending: !v.dsDone && !v.dsErr, p: v.dsDone ? d.p.ds?.[30] ?? null : null, lat: v.dsDone ? d.ds.done - d.t : null, err: v.dsErr});
  }
  return out;
}

// 刚揭晓的 Jev 判断：答完 30 秒后的涨跌出来了，对还是错
export function recentSettled(records, now, n = 9) {
  const out = [];
  for (let i = records.length - 1; i >= 0 && out.length < n; i--) {
    const d = records[i]; if (d.t > now - 30000 || !d.p.jev) continue;
    const v = visible(d, now), o = v.after.jev[30]; if (!o) continue;
    const e = d.jev.mid1 ?? d.mid0, p = d.p.jev[30];
    out.push({t: d.t, answeredAt: d.jev.done, p, mid1: e, out: o, ok: o === 'flat' ? null : (p >= 0.5) === (o === 'up'), pnl: v.pnlJev});
  }
  return out;
}

// 最近几十个决策点，给看板的 ACTIVITY LOG
export function recentLog(records, now, n = 40) {
  let i = records.length; while (i > 0 && records[i - 1].t > now) i--;
  return records.slice(Math.max(0, i - n), i).map(d => {
    const v = visible(d, now);
    return {t: d.t, mid0: d.mid0, late: !!d.late, err: v.jevErr, pending: !!d.jev && !v.jevDone && !v.jevErr,
      lat: v.jevDone ? d.jev.done - d.t : null, jev: v.jevDone ? d.p.jev?.[30] ?? null : null,
      mom: pOf(d, 'mock', 30) ?? pOf(d, 'mom', 30),   // 日志里跟 Jev 并排显示的那条规则（jev-trader 自带的）
      out: v.after.jev[30] ?? v.out[30] ?? null,
      ds: d.ds ? {pending: !v.dsDone && !v.dsErr, p: v.dsDone ? d.p.ds?.[30] ?? null : null, lat: v.dsDone ? d.ds.done - d.t : null, err: v.dsErr} : null};
  });
}

// ---------- 挂单模拟 ----------
// 每个选手每个决策点挂一张单（Jev 是每次答完挂一张）。成交后 30 秒按中间价估值：正 = 这笔成交占了便宜，负 = 被逆向选择
// 两个口径：o = 乐观（碰到价就算成交），c = 保守（价格被打穿才算）
export function makerStats(records, now, {feeMakerBps = 2, evalMs = 30000} = {}) {
  const out = {};
  for (const d of records) {
    if (d.t > now || !d.mk) continue;
    for (const [arm, m] of Object.entries(d.mk)) {
      const A = out[arm] ||= {quotes: 0, o: {n: 0, sum: 0, wins: 0}, c: {n: 0, sum: 0, wins: 0}};
      A.quotes++;
      for (const k of ['o', 'c']) {
        const tf = m['t' + k], e = m['e' + k];
        if (tf == null || e == null || tf + evalMs > now) continue;
        A[k].n++; A[k].sum += e; if (e > 0) A[k].wins++;
      }
    }
  }
  for (const A of Object.values(out)) for (const k of ['o', 'c']) {
    const X = A[k]; X.fillRate = A.quotes ? X.n / A.quotes : null; X.edgeBps = X.n ? X.sum / X.n : null;
    X.netVip0Bps = X.n ? X.edgeBps - 2 * feeMakerBps : null; X.winRate = X.n ? X.wins / X.n : null; delete X.sum;
  }
  return out;
}

// ---------- 慢档：每 60 秒，大模型和 Jev 同题（5 / 15 分钟） ----------
export function slowStats(recs, now, horizons = [300, 900]) {
  const players = {}; const lat = {};
  for (const d of recs) {
    if (d.t > now) break;
    // 抛硬币从出题那一刻算
    for (const h of horizons) {
      const o = d.out?.[h]; if (!o || o === 'flat' || d.t + h * 1000 > now) continue;
      const P = (players.coin ||= {asked: 0, answered: 0, errors: {}, skipped: 0, hit: {}});
      const A = P.hit[h] ||= {n: 0, hit: 0}; A.n++; if (up(d.p.coin[h], o)) A.hit++;
    }
    for (const [id, w] of Object.entries(d.m || {})) {
      const P = players[id] ||= {asked: 0, answered: 0, errors: {}, skipped: 0, hit: {}};
      if (w.skipped) { P.skipped++; continue; }
      P.asked++;
      if (w.err && (w.errAt ?? d.t) <= now) { P.errors[w.err] = (P.errors[w.err] || 0) + 1; continue; }
      if (w.done == null || w.done > now) continue;
      P.answered++; (lat[id] ||= []).push(w.done - d.t);
      for (const h of horizons) {   // 模型从答完那一刻算
        const o = d.after?.[id]?.[h]; if (!o || o === 'flat' || w.done + h * 1000 > now || d.p[id]?.[h] == null) continue;
        const A = P.hit[h] ||= {n: 0, hit: 0}; A.n++; if (up(d.p[id][h], o)) A.hit++;
      }
    }
  }
  for (const [id, P] of Object.entries(players)) {
    P.latP50 = quantile(lat[id] || [], .5); P.latP90 = quantile(lat[id] || [], .9);
    for (const A of Object.values(P.hit)) A.ci = wilson(A.hit, A.n);
  }
  return players;
}

export function recentSlow(recs, now, n = 6) {
  const out = [];
  for (let i = recs.length - 1; i >= 0 && out.length < n; i--) {
    const d = recs[i]; if (d.t > now) continue;
    out.push({t: d.t, mid0: d.mid0, m: Object.fromEntries(Object.entries(d.m || {}).map(([id, w]) => [id,
      w.skipped ? {skipped: true} : w.err && (w.errAt ?? d.t) <= now ? {err: w.err} : w.done != null && w.done <= now ? {p: d.p[id]?.[300], lat: w.done - d.t} : {pending: true}]))});
  }
  return out;
}

// ---------- 累计收益曲线 ----------
// 每个选手按自己当前的判断持有 1 个单位：看涨持多、看跌持空，按中间价逐点累计（bps）。
// 规则在决策那一刻换仓；Jev 在答完那一刻换仓（它慢，这段时间还拿着上一次的仓位）。
// flips = 换了几次方向，前端用它算「扣手续费」版本：每次换向 = 平一次 + 开一次。
export function equityCurves(records, now, maxPoints = 360) {
  let n = 0; while (n < records.length && records[n].t <= now) n++;
  if (n < 2) return null;
  const arms = armsOf(records.slice(0, Math.min(n, 2000))).filter(a => a !== 'ds');
  const pos = Object.fromEntries(arms.map(a => [a, 0])), eq = Object.fromEntries(arms.map(a => [a, 0])), flips = Object.fromEntries(arms.map(a => [a, 0]));
  const jevAns = [];                                   // 按答完时间排好的 Jev 回答
  for (let i = 0; i < n; i++) { const d = records[i]; if (d.p?.jev && d.jev?.done != null && d.jev.done <= now) jevAns.push(d); }
  jevAns.sort((a, b) => a.jev.done - b.jev.done);
  const step = Math.max(1, Math.floor(n / maxPoints)), out = {t: [], eq: Object.fromEntries(arms.map(a => [a, []])), flips: Object.fromEntries(arms.map(a => [a, []]))};
  const setPos = (a, p) => { const s = p == null ? pos[a] : p >= .5 ? 1 : -1; if (s !== pos[a]) { if (pos[a] !== 0) flips[a]++; pos[a] = s; } };
  let j = 0;
  for (let i = 0; i < n; i++) {
    const d = records[i];
    if (i > 0) { const r = (d.mid0 - records[i - 1].mid0) / records[i - 1].mid0 * 1e4; for (const a of arms) eq[a] += pos[a] * r; }
    for (const a of arms) if (a !== 'jev') setPos(a, pOf(d, a, 30));
    while (j < jevAns.length && jevAns[j].jev.done <= d.t) setPos('jev', jevAns[j++].p.jev[30]);
    if (i % step === 0 || i === n - 1) {
      out.t.push(d.t);
      for (const a of arms) { out.eq[a].push(+eq[a].toFixed(2)); out.flips[a].push(flips[a]); }
    }
  }
  return out;
}

// ---------- Jev 最近的挂单（给「实时决策与挂单」图和决策流水） ----------
// 每张单：什么时候挂的、挂到什么时候、买还是卖、挂在什么价、Jev 的概率、延迟、有没有成交、成交后 30 秒赚没赚
export function jevQuotes(records, now, spanMs = 90000, maxN = 400) {
  const out = []; let nextStart = null;
  for (let i = records.length - 1; i >= 0 && out.length < maxN; i--) {
    const d = records[i]; if (d.t > now) continue;
    const m = d.mk?.jev, done = d.jev?.done;
    if (!m || done == null || done > now) continue;
    if (done < now - spanMs) break;
    const vis = k => m['t' + k] != null && m['t' + k] <= now ? m['t' + k] : null;
    const val = k => m['t' + k] != null && m['e' + k] != null && m['t' + k] + 30000 <= now ? m['e' + k] : null;
    out.push({t0: done, t1: nextStart ?? now, side: m.side, px: m.px, p: d.p.jev[30], lat: done - d.t,
      fillO: vis('o'), fillC: vis('c'), edgeO: val('o'), edgeC: val('c'), out30: d.after?.jev?.[30] && done + 30000 <= now ? d.after.jev[30] : null});
    nextStart = done;
  }
  return out.reverse();
}

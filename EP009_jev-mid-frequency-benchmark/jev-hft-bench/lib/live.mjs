// 看板用的增量统计。
// 24 小时约 29 万个决策点，每秒全量重算要将近 1 秒，会卡住 300ms 的决策循环、污染延迟数据。
// 做法：已经完全结算的部分（90 秒以前）只汇总一次；每秒只重算最近 90 秒。口径与 stats.mjs 一致。

import {H, MODELS, pOf, visible, wilson} from './stats.mjs';

const FREEZE_MS = 90000;        // 90 秒前的决策点：60 秒结果、挂单成交后 30 秒估值都已经定了
const EQ_LAG_MS = 10000;        // 收益曲线只算到 10 秒前：保证这段时间里 Jev 的回答都已经回来了
const LAT_MAX = 10000;          // 延迟直方图 0–10 秒，1ms 一格

function newAcc() {
  return {points: 0, sent: 0, late: 0, errors: {}, lat: new Uint32Array(LAT_MAX + 1), latN: 0, moveSum: 0, moveN: 0,
    hit: {}, hitJev: Object.fromEntries(H.map(h => [h, {n: 0, hit: 0}])), probBins: [0, 0, 0, 0, 0, 0], maker: {}};
}
function cloneAcc(a) {
  return {...a, errors: {...a.errors}, lat: a.lat.slice(), hit: JSON.parse(JSON.stringify(a.hit)), hitJev: JSON.parse(JSON.stringify(a.hitJev)),
    probBins: a.probBins.slice(), maker: JSON.parse(JSON.stringify(a.maker))};
}
const binOf = p => p < .1 ? 0 : p < .3 ? 1 : p < .5 ? 2 : p < .7 ? 3 : p < .9 ? 4 : 5;

function ingest(acc, d, now) {
  acc.points++;
  const v = visible(d, now);
  if (d.late) acc.late++;
  if (d.jev) acc.sent++;
  if (v.jevErr) acc.errors[v.jevErr] = (acc.errors[v.jevErr] || 0) + 1;
  if (v.jevDone && d.p.jev) {
    acc.lat[Math.min(LAT_MAX, Math.max(0, d.jev.done - d.t))]++; acc.latN++;
    acc.probBins[binOf(d.p.jev[30])]++;
    if (d.jev.mid1 != null) { acc.moveSum += Math.abs(d.jev.mid1 - d.mid0) / d.mid0 * 1e4; acc.moveN++; }
  }
  for (const h of H) {
    const o = v.out[h];
    if (o && o !== 'flat') for (const a in d.p) {
      if (MODELS.includes(a)) continue;
      const A = (acc.hit[a] ||= {})[h] ||= {n: 0, hit: 0};
      A.n++; if ((pOf(d, a, h) >= .5) === (o === 'up')) A.hit++;
    }
    const oj = v.after.jev[h];
    if (oj && oj !== 'flat' && d.p.jev) { const A = acc.hitJev[h]; A.n++; if ((d.p.jev[h] >= .5) === (oj === 'up')) A.hit++; }
  }
  for (const [arm, m] of Object.entries(d.mk || {})) {
    const M = acc.maker[arm] ||= {quotes: 0, o: {n: 0, sum: 0, wins: 0}, c: {n: 0, sum: 0, wins: 0}};
    M.quotes++;
    for (const k of ['o', 'c']) {
      const tf = m['t' + k], e = m['e' + k];
      if (tf == null || e == null || tf + 30000 > now) continue;
      M[k].n++; M[k].sum += e; if (e > 0) M[k].wins++;
    }
  }
}

function q(hist, n, p) {
  if (!n) return null;
  const target = Math.floor(n * p); let c = 0;
  for (let i = 0; i < hist.length; i++) { c += hist[i]; if (c > target) return i; }
  return hist.length - 1;
}

function finalize(acc, feeMakerBps) {
  const withCi = o => { for (const a in o) for (const h in o[a]) o[a][h].ci = wilson(o[a][h].hit, o[a][h].n); return o; };
  const hit = withCi(acc.hit), hitJev = withCi({jev: acc.hitJev}).jev;
  const maker = {};
  for (const [arm, M] of Object.entries(acc.maker)) {
    maker[arm] = {quotes: M.quotes};
    for (const k of ['o', 'c']) {
      const X = M[k], edge = X.n ? X.sum / X.n : null;
      maker[arm][k] = {n: X.n, fillRate: M.quotes ? X.n / M.quotes : null, edgeBps: edge, netVip0Bps: edge == null ? null : edge - 2 * feeMakerBps, winRate: X.n ? X.wins / X.n : null};
    }
  }
  const errorCount = Object.values(acc.errors).reduce((s, x) => s + x, 0);
  return {
    points: acc.points, sent: acc.sent, late: acc.late, lateRate: acc.points ? acc.late / acc.points : null,
    errors: acc.errors, errorCount, successRate: acc.sent ? 1 - errorCount / acc.sent : null,
    lat: {p50: q(acc.lat, acc.latN, .5), p90: q(acc.lat, acc.latN, .9), p99: q(acc.lat, acc.latN, .99), n: acc.latN},
    moveDuringBps: acc.moveN ? acc.moveSum / acc.moveN : null,
    hit, hitJev, maker,
    probBins: [[0, .1], [.1, .3], [.3, .5], [.5, .7], [.7, .9], [.9, 1]].map(([lo, hi], i) => ({lo, hi, n: acc.probBins[i]})),
  };
}

// 按时间找第一个 t > x 的位置（引擎会丢掉很老的记录，所以不能靠下标记进度）
function firstAfter(records, x) { let lo = 0, hi = records.length; while (lo < hi) { const m = (lo + hi) >> 1; if (records[m].t <= x) lo = m + 1; else hi = m; } return lo; }

export class LiveAggregator {
  constructor() { this.reset(); }
  reset() {
    this.acc = newAcc(); this.frozenT = -Infinity; this.lastNow = -Infinity;
    this.eq = null;   // {t, pos, eq, flips, samples: {t: [], eq: {arm: []}, flips: {arm: []}}, jevQueue, lastT}
  }

  snapshot(records, now, {feeMakerBps = 2} = {}) {
    if (now < this.lastNow) this.reset();               // 回放重新开始了
    this.lastNow = now;
    // 1) 把新冻结的部分并进前缀
    const freezeAt = now - FREEZE_MS;
    if (freezeAt > this.frozenT) {
      const i0 = firstAfter(records, this.frozenT), i1 = firstAfter(records, freezeAt);
      for (let i = i0; i < i1; i++) ingest(this.acc, records[i], now);
      this.frozenT = freezeAt;
    }
    // 2) 最近 90 秒临时算
    const tail = cloneAcc(this.acc), j0 = firstAfter(records, this.frozenT), j1 = firstAfter(records, now);
    for (let i = j0; i < j1; i++) ingest(tail, records[i], now);
    const out = finalize(tail, feeMakerBps);
    out.equity = this.advanceEquity(records, now - EQ_LAG_MS);
    return out;
  }

  // ---------- 累计收益：每个选手按当前判断持 1 个单位（看涨多、看跌空），按中间价逐点累计 bps ----------
  advanceEquity(records, upto) {
    let E = this.eq;
    const i0 = E ? firstAfter(records, E.lastT) : 0, i1 = firstAfter(records, upto);
    if (!E) {
      if (i1 < 2) return null;
      E = this.eq = {pos: {}, eq: {}, flips: {}, prevMid: null, jevQueue: [], lastT: -Infinity, k: 0,
        samples: {t: [], eq: {}, flips: {}}};
    }
    const arms = () => Object.keys(E.eq);
    const ensure = a => { if (!(a in E.eq)) { E.eq[a] = 0; E.pos[a] = 0; E.flips[a] = 0; E.samples.eq[a] = E.samples.t.map(() => 0); E.samples.flips[a] = E.samples.t.map(() => 0); } };
    const setPos = (a, p) => { ensure(a); const s = p >= .5 ? 1 : -1; if (s !== E.pos[a]) { if (E.pos[a] !== 0) E.flips[a]++; E.pos[a] = s; } };
    for (let i = i0; i < i1; i++) {
      const d = records[i];
      // 相邻两个决策点隔了 10 秒以上（服务中断、行情断流），这段涨跌不算任何人的收益
      if (E.prevMid != null && d.t - E.lastT <= 10000) { const r = (d.mid0 - E.prevMid) / E.prevMid * 1e4; for (const a of arms()) E.eq[a] += E.pos[a] * r; }
      E.prevMid = d.mid0;
      for (const a in d.p) if (a !== 'jev' && !MODELS.includes(a)) setPos(a, pOf(d, a, 30));
      // Jev 在答完那一刻才换仓；回答按时间先后排队（Jev 一次只挂一个请求，答完顺序就是发问顺序）
      while (E.jevQueue.length && E.jevQueue[0].done <= d.t) setPos('jev', E.jevQueue.shift().p);
      if (d.p.jev && d.jev?.done != null) E.jevQueue.push({done: d.jev.done, p: d.p.jev[30]});
      E.lastT = d.t;
      if (E.k++ % 10 === 0) {   // 每 10 个决策点（3 秒）存一个点
        E.samples.t.push(d.t);
        for (const a of arms()) { E.samples.eq[a].push(+E.eq[a].toFixed(2)); E.samples.flips[a].push(E.flips[a]); }
      }
    }
    // 下采样给前端：最多 400 个点，最后一个点用当前值
    const S = E.samples, n = S.t.length; if (!n) return null;
    const step = Math.max(1, Math.ceil(n / 400)), idx = [];
    for (let i = 0; i < n; i += step) idx.push(i);
    const out = {t: idx.map(i => S.t[i]), eq: {}, flips: {}, lagMs: EQ_LAG_MS};
    for (const a of arms()) { out.eq[a] = idx.map(i => S.eq[a][i]); out.flips[a] = idx.map(i => S.flips[a][i]); }
    out.t.push(E.lastT); for (const a of arms()) { out.eq[a].push(+E.eq[a].toFixed(2)); out.flips[a].push(E.flips[a]); }
    return out;
  }
}

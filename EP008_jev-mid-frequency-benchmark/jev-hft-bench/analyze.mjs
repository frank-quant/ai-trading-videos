// 事后分析：node analyze.mjs data/<某一场>   （网页上点「分析」也是调它）
// 输出 results.md + results.json。
//
// 置信区间用分块自助法：相邻决策点只隔 0.3 秒，「30 秒后涨跌」的窗口几乎完全重叠，不能当独立样本。
// 快档按 60 秒切块、慢档按 15 分钟切块，整块重抽。固定随机种子，结果可复现。

import fs from 'node:fs'; import path from 'node:path';
import {MODELS, armsOf, computeStats, makerStats, slowStats, pOf} from './lib/stats.mjs';
import {SIGNALS, COIN} from './lib/signals.mjs';

const dir = process.argv[2];
if (!dir) { console.error('用法：node analyze.mjs data/<run>'); process.exit(1); }
const readJsonl = f => { try { return fs.readFileSync(f, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l)); } catch (e) { return []; } };
const meta = JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8'));
const recs = readJsonl(path.join(dir, 'decisions.jsonl')).sort((a, b) => a.t - b.t);
const slow = readJsonl(path.join(dir, 'slow.jsonl')).sort((a, b) => a.t - b.t);
const FAST_H = meta.fastHorizons || meta.horizons || [10, 30, 60], SLOW_H = meta.slowHorizons || [300, 900];
const FEE_M = meta.feeMakerBps ?? 2;
const NAMES = {jev: 'Jev', coin: `${COIN.abbr} ${COIN.name}`, mom: 'BASE jev-trader 基准规则', ...Object.fromEntries(Object.entries(SIGNALS).map(([k, v]) => [k, `${v.abbr} ${v.name}`])),
  ...Object.fromEntries((meta.llms || []).map(m => [m.id, m.name]))};
const nameOf = a => NAMES[a] || a;

let seed = 42; const rand = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32;
function blocksOf(xs, ms) { if (!xs.length) return []; const b = []; for (const d of xs) (b[Math.floor((d.t - xs[0].t) / ms)] ||= []).push(d); return b.filter(Boolean); }
// 返回 [点估计, 下界, 上界]；alpha 默认 5%（双侧），做多重比较时传校正后的 alpha
function bootstrap(blocks, fn, B = 2000, alpha = .05) {
  const est = fn(blocks), v = [];
  if (!blocks.length) return [est, null, null];
  for (let b = 0; b < B; b++) { const pick = []; for (let i = 0; i < blocks.length; i++) pick.push(blocks[Math.floor(rand() * blocks.length)]); const x = fn(pick); if (x != null) v.push(x); }
  v.sort((a, b) => a - b);
  const lo = Math.min(v.length - 1, Math.floor(v.length * alpha / 2)), hi = Math.max(0, Math.ceil(v.length * (1 - alpha / 2)) - 1);
  return [est, v[lo] ?? null, v[hi] ?? null];
}
const pct = x => x == null ? '—' : (x * 100).toFixed(1) + '%';
const pp = x => x == null ? '—' : (x > 0 ? '+' : '') + (x * 100).toFixed(1);
const bps = x => x == null ? '—' : (x > 0 ? '+' : '') + x.toFixed(2);
const ci = ([e, lo, hi], f = pct) => `${f(e)}（${f(lo)} ~ ${f(hi)}）`;
const res = {meta, fast: {}, maker: {}, slow: {}, verdict: {}};
let md = `# 结果：${meta.run}\n\n`;

// ---------- 概况 ----------
const actualMin = recs.length ? (recs.at(-1).t - recs[0].t) / 60000 : slow.length ? (slow.at(-1).t - slow[0].t) / 60000 : 0;
md += `- 市场：${meta.market}\n- 计划时长 ${meta.plannedMinutes ?? '—'} 分钟，实际 ${actualMin.toFixed(1)} 分钟`;
md += meta.stoppedEarly ? `，**提前停止**（${meta.stopReason || '原因未记录'}），结论仅代表该时段\n` : '\n';
if (meta.forcedFinish) md += `- 注：以「立即结束」终止，最后一批未结算的判断未计入\n`;
if (meta.convertedFrom) md += `- 注：本场为第一版测试台数据转换而来（${meta.convertedFrom}），不含挂单模拟与完整规则组\n`;
md += `- 快档每 ${meta.tickMs}ms 一个决策点，共 ${recs.length} 个；慢档每 ${meta.slowEverySec ?? '—'} 秒一轮，共 ${slow.length} 轮\n`;
md += `- 置信区间 95%，分块自助法（快档 60 秒一块、慢档 15 分钟一块）\n\n`;

// ---------- 1. 响应延迟 ----------
const ARMS = armsOf(recs), RULES = ARMS.filter(a => !MODELS.includes(a));
const S = computeStats(recs, Infinity, {arms: ARMS});
const has = a => recs.some(d => d.p?.[a] != null);
if (recs.length) {
  md += `## 1. 响应延迟（快档）\n\n| 指标 | 数值 |\n|---|---|\n`;
  md += `| Jev 响应延迟 P50 / P90 / P99 | ${S.lat.p50} / ${S.lat.p90} / ${S.lat.p99} ms（${S.lat.n} 次成功） |\n`;
  md += `| 跳过率（上一请求未返回，决策点跳过） | ${S.late} / ${S.points} = ${pct(S.lateRate)} |\n`;
  md += `| Jev 请求失败 | ${S.errorCount} 次：${Object.entries(S.errors).map(([k, v]) => `${k} × ${v}`).join('，') || '无'} |\n`;
  md += `| Jev 响应期间中间价平均变动 | ${S.moveDuringBps == null ? '—' : S.moveDuringBps.toFixed(2)} bps |\n\n`;
}

// ---------- 2. 方向准确率 ----------
const fb = blocksOf(recs, 60000);
function score(d, arm, h, real) {
  const p = pOf(d, arm, h); if (p == null) return null;
  const o = real && MODELS.includes(arm) ? d.after?.[arm]?.[h] : d.out?.[h];
  if (!o || o === 'flat') return null;
  return (p >= .5) === (o === 'up') ? 1 : 0;
}
const rate = (arm, h, real) => bl => { let n = 0, k = 0; for (const b of bl) for (const d of b) { const s = score(d, arm, h, real); if (s != null) { n++; k += s; } } return n ? k / n : null; };
const paired = (h, other) => bl => { let n = 0, k = 0; for (const b of bl) for (const d of b) { const a = score(d, 'jev', h, true), c = score(d, other, h, false); if (a != null && c != null) { n++; k += a - c; } } return n ? k / n : null; };
if (recs.length) {
  md += `## 2. 方向准确率（快档，价格不变的样本不计）\n\nJev 从响应返回时刻起算（可交易口径）；规则在决策时刻即给出答案。\n\n| 选手 | ${FAST_H.map(h => `${h} 秒`).join(' | ')} |\n|---|${FAST_H.map(() => '---').join('|')}|\n`;
  const rows = [...(has('jev') ? [['**Jev**', 'jev', true], ['Jev（按发问时刻，理想口径）', 'jev', false]] : []), ...RULES.filter(has).map(a => [nameOf(a), a, false])];
  for (const [label, arm, real] of rows) {
    md += `| ${label} | ${FAST_H.map(h => { const r = bootstrap(fb, rate(arm, h, real)); (res.fast[`${arm}${real ? '_real' : ''}`] ||= {})[h] = r; return ci(r); }).join(' | ')} |\n`;
  }
  if (has('jev')) {
    md += `\n**配对差：Jev 减对照**（仅限 Jev 有响应的决策点，单位百分点；区间整体 <0 为显著落后，整体 >0 为显著领先，跨 0 为无显著差异）\n\n| 对照 | ${FAST_H.map(h => `${h} 秒`).join(' | ')} |\n|---|${FAST_H.map(() => '---').join('|')}|\n`;
    res.fast.paired = {};
    for (const o of RULES.filter(has)) md += `| ${nameOf(o)} | ${FAST_H.map(h => { const r = bootstrap(fb, paired(h, o)); (res.fast.paired[o] ||= {})[h] = r; return ci(r, pp); }).join(' | ')} |\n`;
  }
  md += '\n';
}

// ---------- 3. 挂单成交质量 ----------
const hasMaker = recs.some(d => d.mk);
if (hasMaker) {
  const M = makerStats(recs, Infinity, {feeMakerBps: FEE_M});
  const edge = (arm, k) => bl => { let n = 0, s = 0; for (const b of bl) for (const d of b) { const e = d.mk?.[arm]?.['e' + k]; if (e != null) { n++; s += e; } } return n ? s / n : null; };
  md += `## 3. 挂单成交质量（30 秒 markout：成交后 30 秒按中间价估值）\n\n`;
  md += `看涨挂于买一、看跌挂于卖一，持续到下一次决策。**正值表示成交后价格朝有利方向变动；负值表示逆向选择（成交恰发生在判断出错时）。**\n`;
  md += `乐观口径：该价位出现成交即视为成交；保守口径：价格穿越该价位才视为成交。实际情况介于两者之间。\n\n`;
  md += `| 选手 | 挂单次数 | 成交率 乐观 / 保守 | 单笔 markout 乐观（bps） | 单笔 markout 保守（bps） | 保守口径扣 VIP0 挂单费（${FEE_M}bps×2） |\n|---|---|---|---|---|---|\n`;
  for (const arm of Object.keys(M).sort((a, b) => (a === 'jev' ? -1 : b === 'jev' ? 1 : 0))) {
    const A = M[arm], ro = bootstrap(fb, edge(arm, 'o')), rc = bootstrap(fb, edge(arm, 'c'));
    res.maker[arm] = {...A, ciO: ro, ciC: rc};
    md += `| ${arm === 'jev' ? '**Jev**' : nameOf(arm)} | ${A.quotes} | ${pct(A.o.fillRate)} / ${pct(A.c.fillRate)} | ${ci(ro, bps)} | ${ci(rc, bps)} | ${bps(A.c.netVip0Bps)} |\n`;
  }
  md += `\n注：每个决策点独立挂单，未模拟仓位。本表衡量判断对挂单成交质量的影响，不代表可实际运行的策略收益。\n`;
  md += `注：Jev 单次响应需数百毫秒，挂单存续时间长于规则（每 300ms 更新），成交率天然偏高。**应比较单笔收益，而非成交率。**\n\n`;
}

// ---------- 4. 概率校准 ----------
if (has('jev')) {
  const bk = [[0, .1], [.1, .3], [.3, .5], [.5, .7], [.7, .9], [.9, 1.0001]].map(([lo, hi]) => ({lo, hi, n: 0, up: 0}));
  let sayUp = 0, n = 0, realUp = 0;
  for (const d of recs) {
    const p = pOf(d, 'jev', 30), o = d.after?.jev?.[30]; if (p == null || !o || o === 'flat') continue;
    n++; if (p >= .5) sayUp++; if (o === 'up') realUp++;
    const b = bk.find(b => p >= b.lo && p < b.hi); if (b) { b.n++; if (o === 'up') b.up++; }
  }
  res.calibration = {buckets: bk, sayUpRate: sayUp / n, realUpRate: realUp / n, n};
  md += `## 4. 概率校准（Jev，30 秒）\n\n| Jev 给出的上涨概率 | 次数 | 实际上涨比例 | 理想校准值 |\n|---|---|---|---|\n`;
  for (const b of bk) if (b.n) md += `| ${b.lo}–${Math.min(1, b.hi)} | ${b.n} | ${pct(b.up / b.n)} | ${pct((b.lo + Math.min(1, b.hi)) / 2)} |\n`;
  md += `\n- Jev 判断上涨的比例 ${pct(sayUp / n)}，同期实际上涨比例 ${pct(realUp / n)}（共 ${n} 次）\n\n`;
}

// ---------- 5. 分时段稳定性 ----------
// 结论只在某个时段成立是常见陷阱。按 UTC 分三段：亚洲 00–08、欧洲 08–14、美洲 14–24
if (has('jev') && recs.length) {
  const SESS = ['亚洲（UTC 00–08）', '欧洲（UTC 08–14）', '美洲（UTC 14–24）'];
  const sess = t => { const h = new Date(t).getUTCHours(); return SESS[h < 8 ? 0 : h < 14 ? 1 : 2]; };
  const best = RULES.filter(a => a !== 'coin' && has(a)).map(a => [a, res.fast[a]?.[30]?.[0] ?? 0]).sort((x, y) => y[1] - x[1])[0]?.[0];
  const groups = {}; for (const d of recs) (groups[sess(d.t)] ||= []).push(d);
  md += `## 5. 分时段稳定性（30 秒方向准确率）\n\n| 时段 | 决策点 | Jev 延迟 P50 | Jev | ${best ? nameOf(best) + '（全程最佳规则）' : '最佳规则'} | 随机基准 |\n|---|---|---|---|---|---|\n`;
  for (const name of SESS) {
    const g = groups[name];
    if (!g?.length) { md += `| ${name} | 0 | — | — | — | — |\n`; continue; }
    const gb = blocksOf(g, 60000), G = computeStats(g, Infinity, {arms: ARMS});
    const cell = (arm, real) => ci(bootstrap(gb, rate(arm, 30, real), 1000));
    md += `| ${name} | ${g.length} | ${G.lat.p50 ?? '—'} ms | ${cell('jev', true)} | ${best ? cell(best, false) : '—'} | ${cell('coin', false)} |\n`;
  }
  md += '\n';
}

// ---------- 6. 慢档：大模型和 Jev 同题 ----------
if (slow.length) {
  const SS = slowStats(slow, Infinity, SLOW_H), sb = blocksOf(slow, 15 * 60000);
  const sRate = (id, h) => bl => { let n = 0, k = 0; for (const b of bl) for (const d of b) {
    const p = d.p?.[id]?.[h], o = id === 'coin' ? d.out?.[h] : d.after?.[id]?.[h];
    if (p == null || !o || o === 'flat') continue; n++; if ((p >= .5) === (o === 'up')) k++; } return n ? k / n : null; };
  md += `## 6. 大模型对照：慢档同题（${SLOW_H.map(h => h / 60 + ' 分钟').join(' / ')}）\n\n`;
  md += `| 选手 | 请求 / 响应 / 跳过 | 延迟 P50 | ${SLOW_H.map(h => `${h / 60} 分钟命中率`).join(' | ')} | 出错 |\n|---|---|---|${SLOW_H.map(() => '---').join('|')}|---|\n`;
  for (const [id, P] of Object.entries(SS)) {
    const cells = SLOW_H.map(h => { const r = bootstrap(sb, sRate(id, h)); (res.slow[id] ||= {})[h] = r; return ci(r); });
    md += `| ${nameOf(id)} | ${id === 'coin' ? '—' : `${P.asked} / ${P.answered} / ${P.skipped}`} | ${P.latP50 != null ? (P.latP50 / 1000).toFixed(1) + ' 秒' : '—'} | ${cells.join(' | ')} | ${Object.entries(P.errors).map(([k, v]) => `${k}×${v}`).join(' ') || '—'} |\n`;
  }
  md += `\n注：5 分钟时长下，${actualMin.toFixed(0)} 分钟仅约 ${Math.floor(actualMin / 5)} 个互不重叠的窗口，置信区间较宽，只能识别较大差异；本档作为辅助参考。\n\n`;
}

// ---------- 7. 判定：开跑前锁定的四项标准 ----------
if (has('jev')) {
  const j30 = res.fast.jev_real?.[30], pc = res.fast.paired || {};
  const beatsCoin = pc.coin?.[30]?.[1] > 0;
  // 第 2 条要和 m 条规则逐一比较：不校正的话，就算 Jev 和规则一样好，也有约 m×2.5% 的概率被误判「落后」。
  // 用 Bonferroni 校正：每次比较的 alpha = 5% / m
  const rivals = RULES.filter(a => a !== 'coin' && has(a)), alphaAdj = .05 / Math.max(1, rivals.length);
  const adj = Object.fromEntries(rivals.map(o => [o, bootstrap(fb, paired(30, o), 4000, alphaAdj)]));
  res.pairedAdjusted = {alpha: alphaAdj, h: 30, ci: adj};
  const losesTo = rivals.filter(o => adj[o][2] < 0).map(o => nameOf(o));
  const mj = res.maker.jev, makerPos = mj ? mj.ciC?.[1] > 0 : null;
  const okRate = S.sent ? 1 - S.errorCount / S.sent : null;
  const V = [
    ['30 秒方向准确率显著高于随机基准', beatsCoin, `Jev ${ci(j30 || [null, null, null])}；比随机基准 ${pc.coin?.[30] ? ci(pc.coin[30], pp) : '—'} 个百分点`],
    ['30 秒方向准确率不显著落后于任何一条对照策略', losesTo.length === 0, (losesTo.length ? `显著落后于：${losesTo.join('、')}` : '未显著落后于任何一条') + `（Bonferroni 校正，${rivals.length} 次比较，单次 α = ${(alphaAdj * 100).toFixed(2)}%）`],
    ['零手续费下挂单 30 秒 markout 显著为正（保守口径）', makerPos, mj ? `每笔 ${ci(mj.ciC, bps)} bps` : '没有挂单数据'],
    ['请求成功率不低于 99%', okRate != null && okRate >= .99, `${pct(okRate)}（${S.sent} 次请求，出错 ${S.errorCount} 次）`],
  ];
  res.verdict = V.map(([k, ok, why]) => ({k, ok, why}));
  md += `## 7. 判定（开跑前锁定的四项标准，须全部满足）\n\n| 标准 | 结论 | 依据 |\n|---|---|---|\n`;
  for (const [k, ok, why] of V) md += `| ${k} | ${ok == null ? '— 无数据' : ok ? '✅ 满足' : '❌ 不满足'} | ${why} |\n`;
  md += `\n**满足 ${V.filter(v => v[1] === true).length} / ${V.filter(v => v[1] != null).length} 项（仅统计有数据的标准）。**\n`;
}

fs.writeFileSync(path.join(dir, 'results.md'), md);
fs.writeFileSync(path.join(dir, 'results.json'), JSON.stringify(res, null, 1));
console.log(md);

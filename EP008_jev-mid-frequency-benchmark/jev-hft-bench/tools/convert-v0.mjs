// 把第一版测试台（视频里 9/22 那场用的 testbed.mjs）的数据转成现在的格式，好用 bench.mjs --replay 和 analyze.mjs。
// 旧版只存了「决策时刻」的结果；「答完那一刻起算」的结果和 30 秒吃单收益，这里用逐 300ms 的中间价重新算一遍。
// 用法：node tools/convert-v0.mjs <旧数据目录> <新目录>

import fs from 'node:fs'; import path from 'node:path';
const [src, dst] = process.argv.slice(2);
if (!src || !dst) { console.error('用法：node tools/convert-v0.mjs <旧数据目录> <新目录>'); process.exit(1); }
const H = [10, 30, 60];

const mids = fs.readFileSync(path.join(src, 'mids.jsonl'), 'utf8').split('\n').filter(l => /^\d/.test(l))
  .map(l => { const [t, bid, ask] = l.split(',').map(Number); return {t, bid, ask, mid: (bid + ask) / 2}; }).sort((a, b) => a.t - b.t);
const midAt = t => { let lo = 0, hi = mids.length - 1, r = null; while (lo <= hi) { const m = (lo + hi) >> 1; if (mids[m].t <= t) { r = mids[m]; lo = m + 1; } else hi = m - 1; } return r; };
const lastT = mids.at(-1)?.t ?? 0;
const dir = (a, b) => b > a ? 'up' : b < a ? 'down' : 'flat';
const taker = (p, e, x) => p >= 0.5 ? (x.bid - e.ask) / e.ask * 1e4 : (e.bid - x.ask) / e.bid * 1e4;

const old = fs.readFileSync(path.join(src, 'decisions.jsonl'), 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l)).sort((a, b) => a.t - b.t);
const out = [];
for (const o of old) {
  const m0 = midAt(o.t);
  const d = {t: o.t, mid0: o.mid0, bid0: m0?.bid, ask0: m0?.ask, p: {mom: o.p.mom, coin: o.p.coin}, out: o.out || {}, after: {jev: {}, ds: {}}, pnl: {}};
  if (o.late) d.late = true;
  if (o.dsSkipped) d.dsSkipped = true;
  for (const [who, doneK, errK] of [['jev', 'jevDone', 'err'], ['ds', 'dsDone', 'dsErr']]) {
    const sent = who === 'jev' ? !o.late : (o.dsDone != null || o.dsErr != null);
    if (!sent) continue;
    d[who] = {};
    if (o[errK]) { d[who].err = o[errK]; d[who].errAt = o.t; continue; }
    if (o[doneK] == null || !o.p[who]) continue;
    d.p[who] = o.p[who]; d[who].done = o[doneK];
    const e = midAt(o[doneK]); if (who === 'jev') d.jev.mid1 = e?.mid ?? null;
    for (const h of H) { const x = o[doneK] + h * 1000 <= lastT && midAt(o[doneK] + h * 1000); if (e && x) d.after[who][h] = dir(e.mid, x.mid); }
    const x = o[doneK] + 30000 <= lastT && midAt(o[doneK] + 30000);
    if (e && x) d.pnl[who] = +taker(o.p[who][30], e, x).toFixed(4);
  }
  out.push(d);
}

fs.mkdirSync(dst, {recursive: true});
fs.writeFileSync(path.join(dst, 'decisions.jsonl'), out.map(d => JSON.stringify(d)).join('\n') + '\n');
fs.writeFileSync(path.join(dst, 'mids.csv'), 't,bid,ask\n' + mids.map(m => `${m.t},${m.bid},${m.ask}`).join('\n') + '\n');
let sum = {}; try { sum = JSON.parse(fs.readFileSync(path.join(src, 'summary.json'), 'utf8')); } catch (e) {}
const run = path.basename(src);
fs.writeFileSync(path.join(dst, 'meta.json'), JSON.stringify({run, market: 'Binance USDⓈ-M BTCUSDT', tickMs: 300, horizons: H, dry: false,
  ds: out.some(d => d.ds), started: sum.started ?? out[0]?.t, ends: sum.ends ?? lastT, feeBps: 4.5, jevTimeoutMs: 5000, convertedFrom: 'testbed.mjs v0'}, null, 1));
console.log(`转好了：${out.length} 个决策点 → ${dst}`);

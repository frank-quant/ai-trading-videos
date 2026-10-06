// Jev 中高频测试台：node server.mjs，然后浏览器打开 http://localhost:8770
// 所有操作都在网页上：填 key、测连接、开始 / 停止、看实时看板、回放历史、看结果。
//
// 安全：默认只监听 127.0.0.1；所有会改状态的请求都要带 X-Bench 头、且来源必须是本页面，
// 防止你开着别的网页时，它偷偷调你的本地接口、花你的 key。

import fs from 'node:fs'; import path from 'node:path'; import http from 'node:http';
import {fileURLToPath} from 'node:url'; import {spawn} from 'node:child_process';
import {loadConfig, saveConfig, publicConfig, applyUpdate} from './lib/config.mjs';
import {Run} from './lib/engine.mjs';
import {slowStats, recentSlow, jevQuotes} from './lib/stats.mjs';
import {LiveAggregator} from './lib/live.mjs';
import {testJev, testLlm, DEEPSEEK} from './lib/models.mjs';
import {SIGNALS, COIN, strategyMeta} from './lib/signals.mjs';
import {FAST_H, SLOW_H} from './lib/models.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.join(HERE, 'data');
const args = Object.fromEntries(process.argv.slice(2).map((a, i, xs) => a.startsWith('--') ? [a.slice(2), xs[i + 1] && !xs[i + 1].startsWith('--') ? xs[i + 1] : true] : null).filter(Boolean));
const PORT = Number(args.port || process.env.PORT || 8770);
const HOST = args.host || process.env.HOST || '127.0.0.1';
const ARM_NAMES = {jev: 'Jev', coin: `${COIN.abbr} ${COIN.name}`, mom: 'BASE jev-trader 基准规则', ...Object.fromEntries(Object.entries(SIGNALS).map(([k, v]) => [k, `${v.abbr} ${v.name}`]))};

let cfg = loadConfig();
// 正在跑的场次记在 data/active.json：服务意外退出、重启后据此自动续跑
const ACTIVE = path.join(DATA, 'active.json');
const setActive = id => { try { fs.mkdirSync(DATA, {recursive: true}); fs.writeFileSync(ACTIVE, JSON.stringify({id})); } catch (e) {} };
const clearActive = id => { try { if (JSON.parse(fs.readFileSync(ACTIVE, 'utf8')).id === id) fs.unlinkSync(ACTIVE); } catch (e) {} };
let run = null;          // 正在跑的那一场
let replay = null;       // 正在回放的那一场

// ---------- 快照：实时和回放共用一套 ----------
// 最近 90 秒的买一 / 卖一，给「实时决策与挂单」图
function bookSeries(mids, now, span = 90000) {
  let i = mids.length; while (i > 0 && mids[i - 1].t > now) i--;
  const out = []; for (let j = i - 1; j >= 0 && mids[j].t >= now - span; j--) out.push([mids[j].t, mids[j].bid, mids[j].ask]);
  return out.reverse();
}
// 看板统计用增量算（24 小时的数据每秒全量重算会卡住决策循环），每个数据源一个
const aggs = new WeakMap();
const aggFor = records => { let g = aggs.get(records); if (!g) aggs.set(records, g = new LiveAggregator()); return g; };
function buildSnapshot({meta, records, slowRecords, mids, now, extra = {}}) {
  const fee = {feeMakerBps: meta.feeMakerBps ?? 2};
  const book = bookSeries(mids, now), lastBook = book.at(-1);
  return {...meta, ...extra, now, armNames: ARM_NAMES,
    llmNames: Object.fromEntries((meta.llms || []).map(m => [m.id, m.name])),
    mid: lastBook ? (lastBook[1] + lastBook[2]) / 2 : (mids.at(-1)?.mid ?? null),   // 回放时取「当时」的价格，不是整场最后一个
    stats: aggFor(records).snapshot(records, now, fee),
    slow: slowStats(slowRecords, now, meta.slowHorizons),
    book, quotes: jevQuotes(records, now), slowRecent: recentSlow(slowRecords, now)};
}
// 回放的两个附加选项：
//   fromHours  从这一场的第 N 小时开始放（之前的部分直接算进统计）
//   asLive     重现模式：按「当时正在跑」的样子显示（状态、已运行 / 剩余时长、行情连接、运行日志、费用），用来补录屏。
//              数据全部来自这一场的原始记录，只是不显示「回放」字样。
const JEV_USD_PER_CALL = 0.0001145;   // 重现模式下的费用估算：正式场账单口径，每次请求约 2,727 个输入 token × $0.042/百万
function liveSnapshot() {
  if (replay) {
    const now = Math.min(replay.end, replay.t0 + (Date.now() - replay.real0) * replay.speed);
    if (replay.asLive) {
      const runEnd = replay.meta.stoppedAt ?? replay.end, planned = replay.meta.started + (replay.meta.plannedMinutes || 0) * 60000;
      const snap = buildSnapshot({meta: replay.meta, records: replay.records, slowRecords: replay.slowRecords, mids: replay.mids, now,
        extra: {mode: 'live', reenact: true, state: now >= runEnd ? 'done' : 'running', stoppedAt: now >= runEnd ? runEnd : undefined,
          finishedAt: undefined, stopReason: undefined, stoppedEarly: undefined, plannedEnd: planned,
          ws: {depth: true, trade: true}, pending: {fast: 0, fills: 0, slow: 0},
          log: replay.logLines.filter(l => l.t <= now).slice(-30).map(l => l.s)}});
      const calls = id => { let n = 0; for (const r of replay.slowRecords) { if (r.t > now) break; if (r.m?.[id]) n++; } return n; };
      snap.cost = {jevUsd: (snap.stats?.sent || 0) * JEV_USD_PER_CALL,
        llm: Object.fromEntries([['jev', calls('jev')], ...(replay.meta.llms || []).map(m => [m.id, calls(m.id)])].filter(x => x[1]).map(([id, n]) => [id, {calls: n}]))};
      return snap;
    }
    return buildSnapshot({meta: replay.meta, records: replay.records, slowRecords: replay.slowRecords, mids: replay.mids, now,
      extra: {mode: 'replay', speed: replay.speed, state: now >= replay.end ? 'done' : 'replaying'}});
  }
  if (!run) return {mode: 'idle', state: 'idle', armNames: ARM_NAMES};
  return buildSnapshot({meta: run.meta, records: run.records, slowRecords: run.slowRecords, mids: run.mids, now: Date.now(),
    extra: {mode: 'live', state: run.state, ws: run.ws, log: run.logLines.slice(-30), plannedEnd: run.plannedEnd,
      pending: {fast: run.pending.length, fills: run.fillPending.length, slow: run.slowPending.length},
      cost: {jevUsd: run.cost.jevTokens / 1e6 * 0.042, llm: run.cost.llm}}});
}

// ---------- 历史 ----------
function listRuns() {
  if (!fs.existsSync(DATA)) return [];
  return fs.readdirSync(DATA, {withFileTypes: true}).filter(e => e.isDirectory()).map(e => {
    let meta = {}; try { meta = JSON.parse(fs.readFileSync(path.join(DATA, e.name, 'meta.json'), 'utf8')); } catch (x) {}
    const size = ['decisions.jsonl', 'slow.jsonl', 'mids.csv'].reduce((s, f) => { try { return s + fs.statSync(path.join(DATA, e.name, f)).size; } catch (x) { return s; } }, 0);
    return {id: e.name, started: meta.started, plannedMinutes: meta.plannedMinutes, stoppedEarly: !!meta.stoppedEarly, stopReason: meta.stopReason,
      finishedAt: meta.finishedAt, dry: !!meta.dry, legacy: !!meta.convertedFrom, hasResults: fs.existsSync(path.join(DATA, e.name, 'results.md')), sizeMb: +(size / 1e6).toFixed(1),
      running: run?.id === e.name && run.state !== 'done'};
  }).sort((a, b) => (b.started || 0) - (a.started || 0));
}
const safeRun = id => typeof id === 'string' && /^[\w.-]+$/.test(id) && fs.existsSync(path.join(DATA, id, 'meta.json')) ? path.join(DATA, id) : null;
const readJsonl = f => { try { return fs.readFileSync(f, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l)); } catch (e) { return []; } };
function loadReplay(id, speed, fromHours = 0, asLive = false) {
  const dir = safeRun(id); if (!dir) throw new Error('没有这一场');
  const meta = JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8'));
  const records = readJsonl(path.join(dir, 'decisions.jsonl')).sort((a, b) => a.t - b.t);
  const slowRecords = readJsonl(path.join(dir, 'slow.jsonl')).sort((a, b) => a.t - b.t);
  const mids = fs.readFileSync(path.join(dir, 'mids.csv'), 'utf8').split('\n').filter(l => /^\d/.test(l)).map(l => { const [t, b, a] = l.split(',').map(Number); return {t, bid: b, ask: a, mid: (b + a) / 2}; });
  if (!records.length && !slowRecords.length) throw new Error('这一场没有数据');
  const t0 = Math.min(records[0]?.t ?? Infinity, slowRecords[0]?.t ?? Infinity);
  const end = Math.max((records.at(-1)?.t ?? 0) + 61000, (slowRecords.at(-1)?.t ?? 0) + 901000);
  const sp = Math.max(1, Math.min(600, Number(speed) || 20));
  const skipMs = Math.max(0, Math.min(end - t0 - 60000, (Number(fromHours) || 0) * 3600000));
  // 运行日志每行开头是「2026/9/25 10:04:01」，重现模式下按时间一条条放出来
  let logLines = [];
  if (asLive) {
    try {
      logLines = fs.readFileSync(path.join(dir, 'run.log'), 'utf8').split('\n').filter(Boolean).map(s => {
        const m = s.match(/^(\d+)\/(\d+)\/(\d+) (\d+):(\d+):(\d+)/);
        return {t: m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime() : 0, s};
      });
    } catch (e) {}
  }
  return {id, meta, records, slowRecords, mids, t0, end, speed: sp, real0: Date.now() - skipMs / sp, asLive: !!asLive, logLines};
}
function analyze(id) {
  const dir = safeRun(id); if (!dir) return Promise.reject(new Error('没有这一场'));
  return new Promise((res, rej) => {
    const p = spawn(process.execPath, [path.join(HERE, 'analyze.mjs'), dir], {stdio: ['ignore', 'ignore', 'pipe']});
    let err = ''; p.stderr.on('data', d => err += d);
    p.on('close', code => code === 0 ? res() : rej(new Error(err.slice(0, 300) || '分析失败')));
  });
}

// ---------- HTTP ----------
const allowedHosts = new Set([`localhost:${PORT}`, `127.0.0.1:${PORT}`, `[::1]:${PORT}`, ...(args['allow-host'] ? [String(args['allow-host'])] : [])]);
function guard(req) {
  if (!allowedHosts.has(req.headers.host)) return '不认识的 Host（防 DNS 重绑定）';
  if (req.method !== 'GET') {
    if (req.headers['x-bench'] !== '1') return '缺少 X-Bench 头';
    const o = req.headers.origin; if (o && !allowedHosts.has(o.replace(/^https?:\/\//, ''))) return '来源不对';
  }
  return null;
}
const readBody = req => new Promise((res, rej) => { let b = ''; req.on('data', c => { b += c; if (b.length > 1e6) req.destroy(); }); req.on('end', () => { try { res(b ? JSON.parse(b) : {}); } catch (e) { rej(new Error('JSON 格式不对')); } }); });
const send = (res, code, obj, type = 'application/json; charset=utf-8') => { res.writeHead(code, {'Content-Type': type, 'Cache-Control': 'no-store'}); res.end(typeof obj === 'string' || Buffer.isBuffer(obj) ? obj : JSON.stringify(obj)); };

const routes = {
  'GET /': (q, res) => send(res, 200, fs.readFileSync(path.join(HERE, 'web', 'index.html')), 'text/html; charset=utf-8'),
  'GET /api/live': () => liveSnapshot(),
  'GET /api/config': () => publicConfig(cfg),
  'GET /api/strategies': () => ({strategies: strategyMeta(), fastHorizons: FAST_H, slowHorizons: SLOW_H, fees: {makerBps: cfg.run.feeMakerBps, takerBps: cfg.run.feeTakerBps}}),
  'POST /api/config': async q => { cfg = applyUpdate(cfg, await readBody(q)); saveConfig(cfg); return publicConfig(cfg); },
  'POST /api/test': async q => {
    const {target} = await readBody(q);
    if (target === 'jev') { if (!cfg.keys.jev) throw new Error('还没填 Jev key'); return await testJev(cfg.keys.jev); }
    if (target === 'deepseek') { if (!cfg.keys.deepseek) throw new Error('还没填 DeepSeek key'); return await testLlm({...DEEPSEEK, key: cfg.keys.deepseek}); }
    const m = cfg.extraLlms.find(x => x.id === target); if (!m) throw new Error('没有这个模型');
    if (!m.key || !m.baseUrl || !m.model) throw new Error('接口地址、模型名、key 要填全'); return await testLlm(m);
  },
  'POST /api/run/start': async q => {
    const {dry} = await readBody(q);
    if (run && run.state !== 'done') throw new Error('已经有一场在跑了，先停止');
    if (!dry && !cfg.keys.jev) throw new Error('还没填 Jev key。没有 key 可以先用 DRY 模式看看规则组');
    replay = null;
    run = new Run(cfg, DATA, {dry: !!dry});
    run.onFinish = r => { clearActive(r.id); analyze(r.id).catch(e => r.log('自动分析失败：' + e.message)); };
    run.start(); setActive(run.id);
    return {ok: true, id: run.id};
  },
  'POST /api/run/stop': () => { if (!run || run.state !== 'running') throw new Error('没有在跑'); run.stop('网页上点了停止'); return {ok: true}; },
  'POST /api/run/finish': () => { if (!run || run.state === 'done') throw new Error('没有在跑'); run.finish(true); return {ok: true}; },
  'GET /api/runs': () => listRuns(),
  'POST /api/replay': async q => { if (run && run.state !== 'done') throw new Error('正在实跑，先停止再回放'); const {id, speed, fromHours, asLive} = await readBody(q); replay = loadReplay(id, speed, fromHours, asLive); return {ok: true}; },
  'POST /api/replay/stop': () => { replay = null; return {ok: true}; },
  'POST /api/analyze': async q => { const {id} = await readBody(q); await analyze(id); return {ok: true}; },
  'GET /api/results': q => {
    const id = new URL(q.url, 'http://x').searchParams.get('id'), dir = safeRun(id); if (!dir) throw new Error('没有这一场');
    const f = path.join(dir, 'results.md'); if (!fs.existsSync(f)) throw new Error('还没出结果，先点「分析」');
    return {md: fs.readFileSync(f, 'utf8')};
  },
};

http.createServer(async (req, res) => {
  const bad = guard(req); if (bad) return send(res, 403, {error: bad});
  const key = `${req.method} ${new URL(req.url, 'http://x').pathname}`, h = routes[key];
  if (!h) return send(res, 404, {error: 'not found'});
  try { const r = await h(req, res); if (r !== undefined && !res.headersSent) send(res, 200, r); }
  catch (e) { if (!res.headersSent) send(res, 400, {error: e.message, detail: e.detail}); }
}).listen(PORT, HOST, () => {
  console.log(`Jev 中高频测试台：http://localhost:${PORT}`);
  if (HOST !== '127.0.0.1' && HOST !== 'localhost') console.log('⚠️ 你让它监听了非本机地址。页面上能改 key、能花你的钱，别暴露到公网');
});

// ---------- 启动时自动续跑 ----------
(function autoResume() {
  let id; try { id = JSON.parse(fs.readFileSync(ACTIVE, 'utf8')).id; } catch (e) { return; }
  const dir = safeRun(id); if (!dir) return clearActive(id);
  const meta = JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8'));
  if (meta.finishedAt || meta.stoppedAt) return clearActive(id);
  const plannedEnd = meta.started + meta.plannedMinutes * 60000;
  if (Date.now() >= plannedEnd) {
    // 停机期间已经到了计划结束时间：按到点结束处理，停机时段记为中断
    let lastT = meta.started; try { lastT = +fs.readFileSync(path.join(dir, 'mids.csv'), 'utf8').trim().split('\n').at(-1).split(',')[0] || lastT; } catch (e) {}
    Object.assign(meta, {gaps: [...(meta.gaps || []), {from: lastT, to: plannedEnd}], stoppedAt: lastT, finishedAt: Date.now(), stopReason: '服务停机期间到达计划结束时间'});
    fs.writeFileSync(path.join(dir, 'meta.json'), JSON.stringify(meta, null, 1));
    clearActive(id); analyze(id).catch(() => {});
    console.log(`场次 ${id} 在停机期间已到计划结束时间，已收尾并出结果`);
    return;
  }
  if (!meta.dry && !cfg.keys.jev) { console.log(`场次 ${id} 待续跑，但没有 Jev key，先不续跑`); return; }
  run = new Run(cfg, DATA, {resume: id});
  run.onFinish = r => { clearActive(r.id); analyze(r.id).catch(e => r.log('自动分析失败：' + e.message)); };
  run.start();
  console.log(`已自动续跑场次 ${id}`);
})();

process.on('uncaughtException', e => { console.error('未捕获异常（已忽略）：', e.message); run?.log('未捕获异常（已忽略）：' + e.message); });
process.on('unhandledRejection', e => { console.error('未处理的 Promise 拒绝（已忽略）：', e?.message); });
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => { if (run && run.state !== 'done') { run.finish(true); setTimeout(() => process.exit(0), 1500); } else process.exit(0); });

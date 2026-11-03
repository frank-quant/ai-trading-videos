// 一场实测 = 一个 Run。前端点「开始」就 new 一个，点「停止」就停止出新决策、把没结算的结算完。
//
// 两档选手，看同一份币安 BTCUSDT 永续行情：
//   快档（每 300ms）：Jev + 八条经典规则 + 抛硬币，问 10/30/60 秒后涨跌；每个选手都挂一张模拟挂单
//   慢档（每 60 秒）：Jev + 大模型（DeepSeek / 你配的其他模型）+ 抛硬币，问 5/15 分钟后涨跌
// 只读公开行情、只做模拟，不下任何订单。

import fs from 'node:fs'; import path from 'node:path'; import {spawn} from 'node:child_process';
import {runSignals, ofiTick} from './signals.mjs';
import {FAST_H, FAST_QUESTIONS, SLOW_H, SLOW_QUESTIONS, DEEPSEEK, askJev, askLlm} from './models.mjs';

const WS_DEPTH = 'wss://fstream.binance.com/public/stream?streams=btcusdt@depth20@100ms';
const WS_TRADE = 'wss://fstream.binance.com/market/stream?streams=btcusdt@aggTrade';
const KLINES = 'https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m&limit=30';
const TICK_MS = 300, MAKER_EVAL_S = 30;

const pad = n => String(n).padStart(2, '0');
const runId = d => `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}`;
const dir = (a, b) => b > a ? 'up' : b < a ? 'down' : 'flat';

export class Run {
  // resume = 已有场次的 id：服务意外退出后重启时，接着这一场往下跑（数据追加到同一目录，中断时段记进 meta.gaps）
  constructor(cfg, dataDir, {dry = false, resume = null} = {}) {
    this.dry = dry; this.state = 'starting';
    let old = null;
    if (resume) {
      old = JSON.parse(fs.readFileSync(path.join(dataDir, resume, 'meta.json'), 'utf8'));
      dry = this.dry = !!old.dry;
      // 续跑时参数以开跑时锁定的为准，不用当前设置
      cfg = {...cfg, run: {...cfg.run, minutes: old.plannedMinutes, fastTier: old.fastTier, slowTier: old.slowTier, slowEverySec: old.slowEverySec,
        jevTimeoutMs: old.jevTimeoutMs, llmTimeoutMs: old.llmTimeoutMs, feeMakerBps: old.feeMakerBps, feeTakerBps: old.feeTakerBps}};
    }
    this.cfg = cfg;
    this.id = resume || runId(new Date()) + (dry ? '_dry' : '');
    this.out = path.join(dataDir, this.id); fs.mkdirSync(this.out, {recursive: true});
    const R = cfg.run;
    this.llms = dry ? [] : [
      ...(cfg.keys.deepseek ? [{...DEEPSEEK, key: cfg.keys.deepseek}] : []),
      ...cfg.extraLlms.filter(m => m.enabled && m.key && m.baseUrl && m.model).map(m => ({id: m.id, name: m.name || m.model, baseUrl: m.baseUrl, model: m.model, key: m.key})),
    ];
    this.useJev = !dry && !!cfg.keys.jev;
    this.t0 = old ? old.started : Date.now(); this.plannedEnd = this.t0 + R.minutes * 60000;
    this.meta = {run: this.id, market: 'Binance USDⓈ-M BTCUSDT perpetual', tickMs: TICK_MS, dry, started: this.t0, plannedMinutes: R.minutes,
      fastTier: R.fastTier, slowTier: R.slowTier, fastHorizons: FAST_H, slowHorizons: SLOW_H, slowEverySec: R.slowEverySec,
      jev: this.useJev, llms: this.llms.map(m => ({id: m.id, name: m.name, model: m.model})), jevTimeoutMs: R.jevTimeoutMs, llmTimeoutMs: R.llmTimeoutMs,
      feeMakerBps: R.feeMakerBps, feeTakerBps: R.feeTakerBps, makerEvalSec: MAKER_EVAL_S,
      note: '计划时长开跑前定死；提前停止会记 stoppedEarly'};
    const readJsonl = f => { try { return fs.readFileSync(path.join(this.out, f), 'utf8').split('\n').filter(Boolean).map(l => { try { return JSON.parse(l); } catch (e) { return null; } }).filter(Boolean); } catch (e) { return []; } };
    let history = [], slowHistory = [];
    if (old) {
      // 中断时段：从最后一条价格记录到现在
      let lastT = old.started;
      try { const lines = fs.readFileSync(path.join(this.out, 'mids.csv'), 'utf8').trim().split('\n'); lastT = +lines.at(-1).split(',')[0] || lastT; } catch (e) {}
      this.meta = {...old, gaps: [...(old.gaps || []), {from: lastT, to: Date.now()}], resumes: (old.resumes || 0) + 1};
      // 看板要显示整场统计：把已经落盘的记录读回来（引擎之后照常只在内存里留最近 3 小时，更早的由看板增量汇总）
      history = readJsonl('decisions.jsonl').sort((a, b) => a.t - b.t);
      slowHistory = readJsonl('slow.jsonl').sort((a, b) => a.t - b.t);
    }
    this.writeMeta();
    const w = f => fs.createWriteStream(path.join(this.out, f), {flags: 'a'});
    this.f = {dec: w('decisions.jsonl'), mid: w('mids.csv'), feat: w('features.jsonl'), slow: w('slow.jsonl')};
    if (!old) this.f.mid.write('t,bid,ask\n');
    // 运行时数据
    this.book = null; this.trades = []; this.mids = []; this.ws = {depth: false, trade: false}; this.sockets = [];
    this.records = history; this.pending = []; this.slowRecords = slowHistory; this.slowPending = [];
    this.pointCount = history.length;
    this.fillPending = []; this.orders = {}; this.fillCount = 0;      // orders[arm] = {side, px, t, rec, filledOpt, filledCons}
    this.prevTop = null; this.ofiHist = []; this.jevBusy = false; this.slowInflight = {};
    this.cost = {jevTokens: 0, llm: {}}; this.logLines = [];
  }

  log(m) {
    const s = `${new Date().toLocaleString('zh-CN', {hour12: false})} ${m}`;
    this.logLines.push(s); if (this.logLines.length > 200) this.logLines.shift();
    try { fs.appendFileSync(path.join(this.out, 'run.log'), s + '\n'); } catch (e) {}
  }
  writeMeta() { fs.writeFileSync(path.join(this.out, 'meta.json'), JSON.stringify(this.meta, null, 1)); }

  // ---------- 开始 ----------
  start() {
    this.connect(WS_DEPTH, 'depth', d => { this.book = {t: Date.now(), bids: d.b.map(([p, q]) => [+p, +q]), asks: d.a.map(([p, q]) => [+p, +q])}; });
    // 时间一律用本机收到的时刻：挂单、价格采样、结算都是本机时钟，混用交易所时间会因为时钟偏差多算或漏算成交
    this.connect(WS_TRADE, 'trade', d => this.onTrade({t: Date.now(), tx: d.T, p: +d.p, q: +d.q, side: d.m ? 'sell' : 'buy'}));   // m=买方是挂单方 → 主动卖
    this.fastTimer = setInterval(() => this.fastTick(), TICK_MS);   // 价格一直采样（停止后结算还要用），决策只在 running 时出
    if (this.cfg.run.slowTier && (this.useJev || this.llms.length)) this.slowTimer = setInterval(() => this.slowTick(), this.cfg.run.slowEverySec * 1000);
    this.settleTimer = setInterval(() => this.settle(), 1000);
    if (this.cfg.run.keepAwake) this.keepAwake();
    this.state = 'running';
    const g = this.meta.gaps?.at(-1);
    if (this.meta.resumes && g) this.log(`续跑（第 ${this.meta.resumes} 次）：服务在 ${new Date(g.from).toLocaleString('zh-CN', {hour12: false})} 中断，中断 ${((g.to - g.from) / 60000).toFixed(1)} 分钟；已读回 ${this.records.length} 个决策点，计划结束时间不变`);
    else this.log(`开跑：计划 ${this.cfg.run.minutes} 分钟${this.dry ? '（DRY，不调任何模型）' : ''}；Jev ${this.useJev ? '开' : '关'}；大模型 ${this.llms.map(m => m.name).join('、') || '无'}`);
  }

  connect(url, name, onMsg) {
    if (this.state === 'done') return;
    const ws = new WebSocket(url); this.sockets.push(ws);
    let last = Date.now();
    // 连接可能「悄悄没数据」而不触发关闭（实测要等约 150 秒才报断开）：5 秒收不到消息就主动断开重连
    const watchdog = setInterval(() => { if (ws.readyState === 1 && Date.now() - last > 5000) { this.log(`${name} 5 秒没收到数据，主动重连`); try { ws.close(); } catch (e) {} } }, 1000);
    ws.onopen = () => { last = Date.now(); this.ws[name] = true; this.log(`${name} 行情已连上`); };
    ws.onmessage = m => { last = Date.now(); try { onMsg(JSON.parse(m.data).data); } catch (e) {} };
    ws.onclose = () => { clearInterval(watchdog); this.ws[name] = false; if (this.state !== 'done') { this.log(`${name} 断开，3 秒后重连`); setTimeout(() => this.connect(url, name, onMsg), 3000); } };
    ws.onerror = () => {};
  }

  // ---------- 状态：字段照抄 jev-trader 的 TradeState ----------
  buildState() {
    const b = this.book, bb = b.bids[0][0], ba = b.asks[0][0], mid = (bb + ba) / 2, mids = this.mids, n = mids.length;
    const ret = k => n > k ? (mids[n - 1].mid - mids[n - 1 - k].mid) / mids[n - 1 - k].mid * 1e4 : 0;
    // 按档位累计挂单量。注意：jev-trader 原版按「距中间价 10/25/50 bps」统计，那是给价差很宽的链上小币种用的；
    // BTC 最小价位 0.1 美元，20 档只覆盖中间价附近约 0.4 bps，按 bps 统计三组数会完全相同且失真（9/25 发现并修正）
    const lvl = n => ({bid: +b.bids.slice(0, n).reduce((s, [, q]) => s + q, 0).toFixed(3), ask: +b.asks.slice(0, n).reduce((s, [, q]) => s + q, 0).toFixed(3)});
    const bq = b.bids.reduce((s, [, q]) => s + q, 0), aq = b.asks.reduce((s, [, q]) => s + q, 0);
    const tr = this.trades.filter(x => x.t >= Date.now() - 30000);
    const buy = tr.filter(x => x.side === 'buy').reduce((s, x) => s + x.q, 0), sell = tr.filter(x => x.side === 'sell').reduce((s, x) => s + x.q, 0);
    const vw = tr.reduce((s, x) => s + x.p * x.q, 0), vq = buy + sell;
    return {
      market: 'BTCUSDT perpetual (Binance)', tickMs: TICK_MS, mid: +mid.toFixed(2), spreadBps: +((ba - bb) / mid * 1e4).toFixed(3),
      top: {bidPx: bb, askPx: ba, bidQty: b.bids[0][1], askQty: b.asks[0][1]},
      bookImbalance: +((bq - aq) / (bq + aq || 1)).toFixed(3), depthBTC: {top1: lvl(1), top5: lvl(5), top20: lvl(20)},
      book: {bids: b.bids.slice(0, 5).map(([p, q]) => `${p} x ${q}`), asks: b.asks.slice(0, 5).map(([p, q]) => `${p} x ${q}`)},
      returnsBps: {last1: +ret(1).toFixed(2), last5: +ret(5).toFixed(2), last20: +ret(20).toFixed(2), last100: +ret(100).toFixed(2)},
      recentMids: mids.slice(-100).filter((_, i, a) => (a.length - 1 - i) % 5 === 0).map(x => x.mid.toFixed(1)).join(' '),
      trades30s: {count: tr.length, buyBTC: +buy.toFixed(3), sellBTC: +sell.toFixed(3), cvdBTC: +(buy - sell).toFixed(3),
                  vwap: vq ? +(vw / vq).toFixed(2) : null, lastPrice: tr.at(-1)?.p ?? null, lastSide: tr.at(-1)?.side ?? null},
      recentTrades: tr.slice(-8).map(x => `${x.side} ${x.q} @ ${x.p}`),
    };
  }
  midAt(t) { const m = this.mids; let lo = 0, hi = m.length - 1, r = null; while (lo <= hi) { const k = (lo + hi) >> 1; if (m[k].t <= t) { r = m[k]; lo = k + 1; } else hi = k - 1; } return r; }

  // ---------- 快档：每 300ms ----------
  fastTick() {
    if (this.state !== 'running' || !this.book || Date.now() - this.book.t > 2000) return;
    const t = Date.now(), bb = this.book.bids[0][0], ba = this.book.asks[0][0], mid = (bb + ba) / 2;
    this.mids.push({t, mid, bid: bb, ask: ba}); this.f.mid.write(`${t},${bb},${ba}\n`);
    while (this.mids.length && this.mids[0].t < t - 20 * 60000) this.mids.shift();   // 留 20 分钟，够慢档 15 分钟结算
    if (this.mids.length < 110) return;                                          // 先攒 30 秒历史
    const s = this.buildState();
    this.ofiHist.push({t, e: ofiTick(s.top, this.prevTop)}); this.prevTop = s.top;
    while (this.ofiHist.length && this.ofiHist[0].t < t - 3000) this.ofiHist.shift();
    s.ofi3s = +this.ofiHist.reduce((x, y) => x + y.e, 0).toFixed(3);
    const rules = {...runSignals(s), coin: Math.random()};
    this.f.feat.write(JSON.stringify({t, top: s.top, spreadBps: s.spreadBps, bookImbalance: s.bookImbalance, ofi3s: s.ofi3s, returnsBps: s.returnsBps, trades30s: s.trades30s}) + '\n');
    const d = {t, mid0: mid, out: {}, after: {jev: {}},
      p: Object.fromEntries(Object.entries(rules).map(([k, p]) => [k, +p.toFixed(5)]))};   // 规则的概率跟时长无关，存一个数
    this.records.push(d); this.pending.push(d);
    this.pointCount = (this.pointCount || 0) + 1;
    // 内存里只留最近 3 小时：更早的已经落盘，也已经并进看板的增量统计
    if (this.pointCount % 2000 === 0) { const cut = t - 3 * 3600000; let k = 0; while (k < this.records.length && this.records[k].t < cut) k++; if (k) this.records.splice(0, k); }
    // Jev 的单超过 5 秒没更新（一直超时或报错）就撤掉，不让旧判断一直挂着
    if (this.orders.jev && t - this.orders.jev.t > 5000) this.closeOrder('jev');
    for (const [arm, p] of Object.entries(rules)) this.quote(arm, p >= .5 ? 'buy' : 'sell', t, d);   // 规则：每个点撤旧挂新
    if (!this.useJev) return;
    if (this.jevBusy) { d.late = true; return; }
    this.askJevFast(d, s);
  }

  async askJevFast(d, s) {
    this.jevBusy = true; d.jev = {};
    try {
      const r = await askJev(this.cfg.keys.jev, s, FAST_QUESTIONS, this.cfg.run.jevTimeoutMs);
      const t1 = Date.now();
      d.p.jev = r.p; d.jev.done = t1; d.jev.mid1 = this.midAt(t1)?.mid ?? null; d.jev.model = r.model;
      this.cost.jevTokens += r.tokens;
      if (this.state === 'running') this.quote('jev', r.p[MAKER_EVAL_S] >= .5 ? 'buy' : 'sell', t1, d);   // Jev：答完才挂，挂到下一次答完
    } catch (e) { d.jev.err = e.message; d.jev.errAt = Date.now(); }
    finally { this.jevBusy = false; }
  }

  // ---------- 挂单模拟 ----------
  // 看涨就挂在买一，看跌就挂在卖一，挂到这个选手下一次决策为止。
  // 看不到自己排第几，所以给两个边界：乐观 = 有人在这个价成交就算成交；保守 = 价格被打穿才算。
  // 成交结果直接记在挂这张单的那个决策点上：d.mk[arm] = {side, px, to/tc: 乐观/保守成交时刻, eo/ec: 成交后 30 秒的优势 bps}
  quote(arm, side, t, d) {
    const top = this.book; if (!top) return;
    this.closeOrder(arm);
    const px = side === 'buy' ? top.bids[0][0] : top.asks[0][0];
    d.mk ||= {}; d.mk[arm] = {side, px};
    d.open = (d.open || 0) + 1;
    this.orders[arm] = {side, px, t, rec: d, filledOpt: false, filledCons: false};
  }
  closeOrder(arm) { const o = this.orders[arm]; if (o) { o.rec.open--; delete this.orders[arm]; } }
  onTrade(x) {
    this.trades.push(x);
    while (this.trades.length && this.trades[0].t < Date.now() - 120000) this.trades.shift();
    if (this.state !== 'running') return;
    for (const [arm, o] of Object.entries(this.orders)) {
      if (x.t < o.t) continue;
      const hits = o.side === 'buy' ? x.side === 'sell' && x.p <= o.px : x.side === 'buy' && x.p >= o.px;
      if (!hits) continue;
      const through = o.side === 'buy' ? x.p < o.px : x.p > o.px, m = o.rec.mk[arm];
      if (!o.filledOpt) { o.filledOpt = true; m.to = x.t; o.rec.fillsPending = (o.rec.fillsPending || 0) + 1; this.fillPending.push({d: o.rec, arm, k: 'o', t: x.t}); this.fillCount++; }
      if (through && !o.filledCons) { o.filledCons = true; m.tc = x.t; o.rec.fillsPending = (o.rec.fillsPending || 0) + 1; this.fillPending.push({d: o.rec, arm, k: 'c', t: x.t}); }
    }
  }

  // ---------- 慢档：每 60 秒，大模型和 Jev 同题 ----------
  async slowTick() {
    if (this.state !== 'running' || !this.book || this.mids.length < 110) return;
    const t = Date.now(), m0 = this.mids.at(-1);
    const s = this.buildState();
    try {
      const k = await (await fetch(KLINES, {signal: AbortSignal.timeout(5000)})).json();
      s.klines1m = k.map(r => `${new Date(r[0]).toISOString().slice(11, 16)} o${(+r[1]).toFixed(1)} h${(+r[2]).toFixed(1)} l${(+r[3]).toFixed(1)} c${(+r[4]).toFixed(1)} v${(+r[5]).toFixed(1)}`);
    } catch (e) { s.klines1m = null; }
    delete s.top;
    const d = {t, mid0: m0.mid, p: {coin: Object.fromEntries(SLOW_H.map(h => [h, Math.random()]))}, m: {}, out: {}, after: {}};
    this.slowRecords.push(d); this.slowPending.push(d);
    const players = [...(this.useJev ? [{id: 'jev', name: 'Jev'}] : []), ...this.llms];
    for (const pl of players) {
      if ((this.slowInflight[pl.id] || 0) >= this.cfg.run.slowMaxInflight) { d.m[pl.id] = {skipped: true}; continue; }
      this.slowInflight[pl.id] = (this.slowInflight[pl.id] || 0) + 1; d.m[pl.id] = {};
      const ask = pl.id === 'jev' ? askJev(this.cfg.keys.jev, s, SLOW_QUESTIONS, this.cfg.run.jevTimeoutMs * 3) : askLlm(pl, s, SLOW_H, this.cfg.run.llmTimeoutMs);
      ask.then(r => {
        d.p[pl.id] = r.p; d.m[pl.id].done = Date.now(); if (r.retried) d.m[pl.id].retried = true;
        const c = this.cost.llm[pl.id] ||= {calls: 0, tokensIn: 0, tokensOut: 0};
        c.calls++; c.tokensIn += r.tokensIn || r.tokens || 0; c.tokensOut += r.tokensOut || 0;
      }).catch(e => { d.m[pl.id].err = e.message; d.m[pl.id].errAt = Date.now(); })
        .finally(() => { this.slowInflight[pl.id]--; });
    }
  }

  // ---------- 结算：每秒一次 ----------
  settle(force = false) {
    const now = Date.now();
    // 快档
    for (let i = this.pending.length - 1; i >= 0; i--) {
      const d = this.pending[i]; let done = true;
      for (const h of FAST_H) {
        if (d.out[h]) continue;
        const m1 = now >= d.t + h * 1000 + 400 && this.midAt(d.t + h * 1000);
        if (m1) d.out[h] = dir(d.mid0, m1.mid); else done = false;
      }
      if (d.jev) {
        if (d.jev.done == null) { if (!d.jev.err) done = false; }
        else {
          const e = this.midAt(d.jev.done);
          for (const h of FAST_H) {
            if (d.after.jev[h]) continue;
            const x = now >= d.jev.done + h * 1000 + 400 && this.midAt(d.jev.done + h * 1000);
            if (x && e) d.after.jev[h] = dir(e.mid, x.mid); else done = false;
          }
        }
      }
      if (d.open > 0 || d.fillsPending > 0) done = false;   // 这个点挂的单还没撤、或成交还没估值，先不落盘
      if (done || force) { const {open, fillsPending, ...rest} = d; this.f.dec.write(JSON.stringify(rest) + '\n'); this.pending.splice(i, 1); }
    }
    // 挂单成交后 30 秒按中间价估值，写回它所属的决策点
    for (let i = this.fillPending.length - 1; i >= 0; i--) {
      const f = this.fillPending[i];
      const x = now >= f.t + MAKER_EVAL_S * 1000 + 400 && this.midAt(f.t + MAKER_EVAL_S * 1000);
      if (x) { const m = f.d.mk[f.arm]; m['e' + f.k] = +((m.side === 'buy' ? x.mid - m.px : m.px - x.mid) / m.px * 1e4).toFixed(4); }
      if (x || force) { f.d.fillsPending--; this.fillPending.splice(i, 1); }
    }
    // 慢档
    for (let i = this.slowPending.length - 1; i >= 0; i--) {
      const d = this.slowPending[i]; let done = true;
      for (const h of SLOW_H) {
        if (d.out[h]) continue;
        const m1 = now >= d.t + h * 1000 + 400 && this.midAt(d.t + h * 1000);
        if (m1) d.out[h] = dir(d.mid0, m1.mid); else done = false;
      }
      for (const [id, w] of Object.entries(d.m)) {
        if (w.skipped || w.err) continue;
        if (w.done == null) { done = false; continue; }
        const e = this.midAt(w.done); d.after[id] ||= {};
        for (const h of SLOW_H) {
          if (d.after[id][h]) continue;
          const x = now >= w.done + h * 1000 + 400 && this.midAt(w.done + h * 1000);
          if (x && e) d.after[id][h] = dir(e.mid, x.mid); else done = false;
        }
      }
      if (done || force) { this.f.slow.write(JSON.stringify(d) + '\n'); this.slowPending.splice(i, 1); }
    }
    // 到点自动停
    if (this.state === 'running' && now >= this.plannedEnd) this.stop('到了计划时长');
    if (this.state === 'settling' && !this.pending.length && !this.fillPending.length && !this.slowPending.length) this.finish();
  }

  // ---------- 停止 ----------
  // 停止 = 不再出新决策，已经发出去的等它结算完（快档最多 1 分钟，慢档最多 15 分钟）。
  stop(reason = '手动停止') {
    if (this.state !== 'running') return;
    clearInterval(this.slowTimer);
    for (const arm of Object.keys(this.orders)) this.closeOrder(arm);
    this.meta.stoppedAt = Date.now(); this.meta.stopReason = reason;
    this.meta.stoppedEarly = Date.now() < this.plannedEnd - 60000;
    this.writeMeta();
    this.state = 'settling';
    this.log(`停止出新决策（${reason}），等已经发出的判断结算完`);
  }
  // 立即结束 = 没结算的直接落盘（标记未完成），不等了
  finish(force = false) {
    if (this.state === 'done' || this.finishing) return;
    this.finishing = true;
    if (this.state === 'running') this.stop('立即结束');
    if (force) { this.settle(true); this.meta.forcedFinish = true; }
    clearInterval(this.settleTimer); clearInterval(this.fastTimer); clearInterval(this.slowTimer);
    this.state = 'done'; this.meta.finishedAt = Date.now(); this.writeMeta();
    for (const s of this.sockets) { try { s.close(); } catch (e) {} }
    this.stopKeepAwake();
    this.log(`结束。快档决策点 ${this.pointCount || 0}，挂单成交（乐观口径）${this.fillCount} 笔，慢档 ${this.slowRecords.length} 轮`);
    Promise.all(Object.values(this.f).map(s => new Promise(r => s.end(r)))).then(() => this.onFinish?.(this));
  }

  // ---------- 跑的时候不让电脑睡 ----------
  keepAwake() {
    try {
      if (process.platform === 'win32') {
        const ps = `Add-Type -Namespace W -Name P -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'; ` +
          `while ($true) { [W.P]::SetThreadExecutionState([uint32]'0x80000001') | Out-Null; Start-Sleep -Seconds 50 }`;
        this.awake = spawn('powershell.exe', ['-NoProfile', '-Command', ps], {stdio: 'ignore', windowsHide: true});
      } else if (process.platform === 'darwin') {
        this.awake = spawn('caffeinate', ['-i', '-w', String(process.pid)], {stdio: 'ignore'});
      }
      if (this.awake) this.log('已开启防休眠');
    } catch (e) { this.log('防休眠没开成：' + e.message); }
  }
  stopKeepAwake() { try { this.awake?.kill(); } catch (e) {} this.awake = null; }
}

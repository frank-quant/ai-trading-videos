// 调模型：Jev（TypeSafe System One）和任何 OpenAI 兼容的大模型。每个请求都有超时——原版 jev-trader 就是栽在没超时上。

async function post(url, key, body, ms) {
  const ac = new AbortController(), to = setTimeout(() => ac.abort(), ms);
  try {
    const r = await fetch(url, {method: 'POST', signal: ac.signal,
      headers: {'Authorization': `Bearer ${key}`, 'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (!r.ok) {
      let detail = ''; try { detail = (await r.text()).slice(0, 120); } catch (e) {}
      const err = new Error('HTTP ' + r.status); err.detail = detail; throw err;
    }
    return await r.json();
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('timeout');
    throw e;
  } finally { clearTimeout(to); }
}

// ---------- Jev ----------
const JEV_URL = 'https://api.typesafe.ai/v1/systemone';

// 输入说明：完整列出状态里的每个字段、只解释含义，不指定哪个更重要（9/25 修正：之前只点名了成交字段、漏了盘口失衡）
const FIELDS_BOOK = 'Order book — top: best bid/ask price and size; bookImbalance: (bid size − ask size) / (bid size + ask size) over the best 20 levels, from −1 to 1; ' +
  'depthBTC: cumulative BTC size within the best 1, 5 and 20 levels on each side; book: best 5 levels per side as "price x size"';
const FIELDS_TRADES = 'Trades — trades30s: taker buy and taker sell volume over the last 30 seconds, their difference cvdBTC, VWAP, last trade price and side; recentTrades: the last 8 taker trades';
const FIELDS_PATH = 'Price path — returnsBps: mid-price return in bps over the last 1 / 5 / 20 / 100 decision points (300 ms each); recentMids: the mid price every 5th decision point over the last 30 seconds';
export const INPUTS_FAST = `Fields (no field is designated as more important than any other): ${FIELDS_BOOK}; ofi3s: order-flow imbalance at the best bid/ask over the last 3 seconds (positive = net size added on the bid side and/or removed from the ask side). ${FIELDS_TRADES}. ${FIELDS_PATH}.`;
export const INPUTS_SLOW = `Fields (no field is designated as more important than any other): ${FIELDS_BOOK.replace('top: best bid/ask price and size; ', '')}. ${FIELDS_TRADES}. ${FIELDS_PATH}. klines1m: the last 30 one-minute candles (open, high, low, close, volume).`;

// 300ms 档：照 jev-trader 的问法，但如实描述执行方式（原版说自己是吃单，代码却在挂单）
export const FAST_H = [3, 10, 30, 60];   // 3 秒是订单簿类信号最强的尺度；30 秒对应 jev-trader 原版的 100 个区块
export const FAST_QUESTIONS = Object.fromEntries(FAST_H.map(h => [`h${h}`, {type: 'choice',
  instructions: {
    question: `Will the BTC mid price be higher or lower than the current mid (\`mid\`) ${h} seconds from now?`,
    goal: 'Each answer places a post-only limit order: a buy at the best bid if you say up, a sell at the best ask if you say down. ' +
      'It only fills when another trader sells into our bid or buys our ask. Only the direction matters.',
    inputs: INPUTS_FAST},
  criteria: {up: `Mid will be higher in ${h} seconds`, down: `Mid will be lower in ${h} seconds`}}]));

// 60 秒档：跟大模型问同一道题
export const SLOW_H = [300, 900];
export const SLOW_QUESTIONS = Object.fromEntries(SLOW_H.map(h => [`h${h}`, {type: 'choice',
  instructions: {
    question: `Will the BTC mid price be higher or lower than the current mid (\`mid\`) ${h / 60} minutes from now?`,
    inputs: INPUTS_SLOW},
  criteria: {up: `Mid will be higher in ${h / 60} minutes`, down: `Mid will be lower in ${h / 60} minutes`}}]));

export async function askJev(key, state, questions, timeoutMs) {
  const j = await post(JEV_URL, key, {model: 'jev-latest', state, questions}, timeoutMs);
  const p = Object.fromEntries(Object.keys(questions).map(q => {
    const a = j.answers[q]; return [Number(q.slice(1)), a.probabilities?.up ?? (a.choice === 'up' ? 1 : 0)];
  }));
  return {p, model: j.model, tokens: j.usage?.input_tokens || 0};
}

// ---------- OpenAI 兼容的大模型 ----------
export const DEEPSEEK = {id: 'ds', name: 'DeepSeek-V4-Pro', baseUrl: 'https://api.deepseek.com', model: 'deepseek-v4-pro'};

// 大模型一次要想几十秒到两分钟。用流式接收：边想边回传，连接一直有流量，
// 不会被网关或代理当成空闲连接在 60 秒左右掐断（非流式实测会报 terminated）。
async function streamChat(m, body, timeoutMs) {
  const ac = new AbortController(), to = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const r = await fetch(m.baseUrl.replace(/\/+$/, '') + '/chat/completions', {method: 'POST', signal: ac.signal,
      headers: {'Authorization': `Bearer ${m.key}`, 'Content-Type': 'application/json'},
      body: JSON.stringify({...body, stream: true, stream_options: {include_usage: true}})});
    if (!r.ok) { let detail = ''; try { detail = (await r.text()).slice(0, 120); } catch (e) {} const err = new Error('HTTP ' + r.status); err.detail = detail; throw err; }
    const dec = new TextDecoder(); let buf = '', content = '', model = m.model, usage = null;
    for await (const chunk of r.body) {
      buf += dec.decode(chunk, {stream: true});
      let i; while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
        if (!line.startsWith('data:')) continue;
        const data = line.slice(5).trim(); if (data === '[DONE]') continue;
        try { const j = JSON.parse(data); model = j.model || model; if (j.usage) usage = j.usage; content += j.choices?.[0]?.delta?.content || ''; } catch (e) {}
      }
    }
    return {content, model, usage};
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('timeout');
    throw e;
  } finally { clearTimeout(to); }
}

const LLM_SYS = 'You are a crypto market microstructure trader. Answer only with one JSON object.';
export async function askLlm(m, state, horizons, timeoutMs) {
  const keysWanted = horizons.map(h => `"h${h}": p`).join(', ');
  const user = `Current Binance BTCUSDT perpetual market state (JSON):\n${JSON.stringify(state)}\n\n` +
    `For each horizon, give the probability that the BTC mid price will be HIGHER than the current mid (${state.mid}) after that many seconds.\n` +
    `Output exactly: {${keysWanted}} with p between 0 and 1.`;
  const body = {model: m.model, response_format: {type: 'json_object'}, messages: [{role: 'system', content: LLM_SYS}, {role: 'user', content: user}]};
  const t0 = Date.now();
  let r;
  try { r = await streamChat(m, body, timeoutMs); }
  catch (e) {   // 网络层断开（不是超时、不是 HTTP 报错）且时间还够，重试一次；重试过的在结果里会记下来
    if (/^(timeout|HTTP)/.test(e.message) || Date.now() - t0 > timeoutMs / 2) throw e;
    r = await streamChat(m, body, timeoutMs - (Date.now() - t0)); r.retried = true;
  }
  const o = JSON.parse((r.content.match(/\{[\s\S]*\}/) || ['{}'])[0]);
  const p = Object.fromEntries(horizons.map(h => [h, Math.max(0, Math.min(1, Number(o['h' + h])))]));
  if (horizons.some(h => !Number.isFinite(p[h]))) throw new Error('bad answer');
  return {p, model: r.model, retried: !!r.retried, tokensIn: r.usage?.prompt_tokens || 0, tokensOut: r.usage?.completion_tokens || 0};
}

// ---------- 设置页的「测试连接」 ----------
export async function testJev(key) {
  const t0 = Date.now();
  const state = {market: 'BTCUSDT perpetual (Binance)', mid: 100000, note: 'connectivity test'};
  const r = await askJev(key, state, {h30: FAST_QUESTIONS.h30}, 15000);
  return {ok: true, ms: Date.now() - t0, model: r.model};
}
export async function testLlm(m) {
  const t0 = Date.now();
  const url = m.baseUrl.replace(/\/+$/, '') + '/chat/completions';
  const j = await post(url, m.key, {model: m.model, messages: [{role: 'user', content: 'Reply with OK.'}]}, 90000);   // 不限 max_tokens：推理模型会先想一会儿
  return {ok: true, ms: Date.now() - t0, model: j.model || m.model};
}

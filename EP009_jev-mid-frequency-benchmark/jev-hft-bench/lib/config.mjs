// 配置：key 和参数都存在本机用户目录（~/.jev-hft-bench/config.json），不在仓库里，不会被 git 提交。
// 前端拿到的永远是打码后的版本；只有服务端自己能读到完整 key。

import fs from 'node:fs'; import path from 'node:path'; import os from 'node:os';

export const CONFIG_DIR = process.env.JEV_BENCH_HOME || path.join(os.homedir(), '.jev-hft-bench');
const FILE = path.join(CONFIG_DIR, 'config.json');

export const DEFAULTS = {
  keys: {jev: '', deepseek: ''},
  // 额外的大模型：任何 OpenAI 兼容接口都行（GPT、Claude 兼容网关、Kimi、GLM……）
  extraLlms: [],   // [{id, name, baseUrl, model, key, enabled}]
  run: {
    minutes: 1440,          // 计划时长，开跑时写进 meta，中途停了会标记「提前结束」
    fastTier: true,         // 300ms 档：Jev + 八条规则 + 硬币，问 10/30/60 秒
    slowTier: true,         // 60 秒档：大模型 + Jev 同题，问 5/15 分钟
    slowEverySec: 60,
    slowMaxInflight: 3,     // 大模型一次答几十秒到两分钟，最多同时挂几个请求
    jevTimeoutMs: 5000,
    llmTimeoutMs: 240000,
    feeMakerBps: 2,         // 币安 USDⓈ-M VIP0：挂单 0.02%
    feeTakerBps: 5,         //                 吃单 0.05%
    keepAwake: true,        // 跑的时候不让电脑睡（Windows / macOS）
  },
};

const clone = o => JSON.parse(JSON.stringify(o));
function merge(base, over) {
  const out = clone(base);
  for (const k in over || {}) {
    if (over[k] && typeof over[k] === 'object' && !Array.isArray(over[k]) && typeof out[k] === 'object') out[k] = merge(out[k], over[k]);
    else out[k] = over[k];
  }
  return out;
}

export function loadConfig() {
  let saved = {};
  try { saved = JSON.parse(fs.readFileSync(FILE, 'utf8')); } catch (e) {}
  const c = merge(DEFAULTS, saved);
  // 环境变量优先（方便服务器上部署）
  if (process.env.JEV_API_KEY) c.keys.jev = process.env.JEV_API_KEY.trim();
  if (process.env.DEEPSEEK_API_KEY) c.keys.deepseek = process.env.DEEPSEEK_API_KEY.trim();
  return c;
}

export function saveConfig(c) {
  fs.mkdirSync(CONFIG_DIR, {recursive: true});
  fs.writeFileSync(FILE + '.tmp', JSON.stringify(c, null, 1), {mode: 0o600});
  fs.renameSync(FILE + '.tmp', FILE);
}

export const mask = k => !k ? '' : k.length <= 8 ? '****' : `${k.slice(0, 3)}****${k.slice(-4)}`;

// 给前端看的版本：key 全部打码
export function publicConfig(c) {
  return {
    keys: Object.fromEntries(Object.entries(c.keys).map(([k, v]) => [k, {set: !!v, masked: mask(v)}])),
    extraLlms: c.extraLlms.map(m => ({...m, key: undefined, keySet: !!m.key, keyMasked: mask(m.key)})),
    run: c.run,
    configDir: CONFIG_DIR,
  };
}

// 前端提交的修改：key 字段留空 = 不改；填 "-" = 清空
export function applyUpdate(c, u) {
  const n = clone(c);
  for (const [k, v] of Object.entries(u.keys || {})) {
    if (typeof v !== 'string' || v === '') continue;
    n.keys[k] = v === '-' ? '' : v.trim();
  }
  if (Array.isArray(u.extraLlms)) {
    n.extraLlms = u.extraLlms.slice(0, 6).map((m, i) => {
      const old = c.extraLlms.find(x => x.id === m.id) || {};
      const key = typeof m.key === 'string' && m.key !== '' ? (m.key === '-' ? '' : m.key.trim()) : old.key || '';
      return {id: m.id || `llm${Date.now()}${i}`, name: String(m.name || '').slice(0, 40), baseUrl: String(m.baseUrl || '').trim(),
        model: String(m.model || '').trim(), key, enabled: !!m.enabled};
    });
  }
  if (u.run) {
    const r = u.run, num = (x, lo, hi, d) => { const v = Number(x); return Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : d; };
    n.run = {...n.run,
      minutes: num(r.minutes, 1, 10080, n.run.minutes), slowEverySec: num(r.slowEverySec, 15, 3600, n.run.slowEverySec),
      slowMaxInflight: num(r.slowMaxInflight, 1, 10, n.run.slowMaxInflight), jevTimeoutMs: num(r.jevTimeoutMs, 500, 60000, n.run.jevTimeoutMs),
      llmTimeoutMs: num(r.llmTimeoutMs, 5000, 600000, n.run.llmTimeoutMs), feeMakerBps: num(r.feeMakerBps, -5, 20, n.run.feeMakerBps),
      feeTakerBps: num(r.feeTakerBps, 0, 20, n.run.feeTakerBps),
      fastTier: r.fastTier ?? n.run.fastTier, slowTier: r.slowTier ?? n.run.slowTier, keepAwake: r.keepAwake ?? n.run.keepAwake};
  }
  return n;
}

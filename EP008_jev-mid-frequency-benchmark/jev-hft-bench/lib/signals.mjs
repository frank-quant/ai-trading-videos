// 对照组：中高频交易里最常用的八类方向信号，全部无拟合参数（阈值、窗口都是事先定死的，不在数据上调）。
// 每条只回答一件事：下面几秒到几十秒，中间价更可能往上还是往下。
// 输出 0–1 的「上涨概率」。命中率只看是否 ≥ 0.5；缩放系数只影响看板上条形的长短，不影响任何结论。
//
// 没有收入的两类及原因（页面「方法」里也写了）：
//   · Stoikov (2018) 的微价格 micro-price：要从历史数据估计转移矩阵，属于拟合模型，不符合「无参数」的设定。
//     注意：常说的「加权中间价」(按挂单量加权的中间价) 与 QI 符号恒等，不单列。
//   · 跨市场领先滞后、期现基差、做市报价模型：需要多个市场的数据，或者本身不是「判断方向」，不在这次比较的范围内。

const sig = (x, k = 1) => 1 / (1 + Math.exp(-k * x));

export const SIGNALS = {
  obi1: {
    name: '盘口失衡', abbr: 'QI', en: 'Queue Imbalance', group: '订单簿',
    formula: '(买一量 − 卖一量) / (买一量 + 卖一量)',
    why: '买一排队的量比卖一多，说明买方更急，下一跳更可能往上。',
    ref: 'Gould & Bonart (2016), Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book, Market Microstructure and Liquidity',
    f: s => sig((s.top.bidQty - s.top.askQty) / (s.top.bidQty + s.top.askQty || 1), 2),
  },
  ofi: {
    name: '订单流不平衡', abbr: 'OFI', en: 'Order Flow Imbalance', group: '订单簿',
    formula: '最近 3 秒累加（按 300ms 采样的买一 / 卖一变化）：买一端净增量 − 卖一端净增量；价格上移按整档新增、被吃掉按整档消失',
    why: '看的是盘口「变化」而不是「存量」：买一在加单、卖一在撤单或被吃，价格随后倾向上行。',
    ref: 'Cont, Kukanov & Stoikov (2014), The Price Impact of Order Book Events, Journal of Financial Econometrics',
    f: s => sig(s.ofi3s ?? 0, .05),
  },
  obi20: {
    name: '深度失衡', abbr: 'DI', en: 'Depth Imbalance (20 levels)', group: '订单簿',
    formula: '(前 20 档买量合计 − 前 20 档卖量合计) / 两者之和',
    why: 'QI 的多档版本：看得更深、噪声更小，反应也更慢。',
    ref: 'Cartea, Donnelly & Jaimungal (2018), Enhancing Trading Strategies with Order Book Signals, Applied Mathematical Finance（量失衡信号；此处取多档版本）',
    f: s => sig(s.bookImbalance, 1.5),
  },
  cvd: {
    name: '成交失衡', abbr: 'TFI', en: 'Trade Flow Imbalance', group: '成交流',
    formula: '(最近 30 秒主动买入量 − 主动卖出量) / 两者之和',
    why: '真金白银主动吃单的方向。加密货币市场的研究发现它比 OFI 更能解释同期价格变化。jev-trader 的提示词也把它称为最强信号。',
    ref: 'Silantyev (2019), Order Flow Analysis of Cryptocurrency Markets, Digital Finance',
    f: s => { const v = s.trades30s.buyBTC + s.trades30s.sellBTC; return sig(v ? s.trades30s.cvdBTC / v : 0, 2.5); },
  },
  mom5: {
    name: '短期动量', abbr: 'MOM', en: 'Short-term Momentum (1.5 s)', group: '价格',
    formula: 'sign(最近 1.5 秒中间价收益)',
    why: '趋势延续：刚才在涨，押注继续涨。',
    ref: '业界常用的时间序列动量信号，此处取 1.5 秒窗口',
    f: s => sig(s.returnsBps.last5, .4),
  },
  rev20: {
    name: '短期反转', abbr: 'REV', en: 'Short-term Reversal (6 s)', group: '价格',
    formula: '−sign(最近 6 秒中间价收益)',
    why: '与 MOM 相反：短时间冲得太快，押注回吐。两条同时放进来，看这个市场在这个尺度上是趋势还是回归。',
    ref: '短期反转与买卖价差反弹相关，参见 Roll (1984), A Simple Implicit Measure of the Effective Bid-Ask Spread, Journal of Finance',
    f: s => sig(-s.returnsBps.last20, .25),
  },
  vwap: {
    name: 'VWAP 回归', abbr: 'VWAP', en: 'VWAP Reversion (30 s)', group: '价格',
    formula: 'sign(最近 30 秒成交均价 − 当前中间价)',
    why: '价格偏离近期成交均价太远，押注回到均价附近。',
    ref: '执行算法与日内交易中常用的均值回归基准',
    f: s => s.trades30s.vwap ? sig((s.trades30s.vwap - s.mid) / s.mid * 1e4, .5) : .5,
  },
  mock: {
    name: 'jev-trader 基准规则', abbr: 'BASE', en: 'jev-trader MockModel', group: '基准',
    formula: 'σ(最近 20 个决策点收益/8 + 20 档失衡×1.5 + 成交失衡×2)',
    why: 'jev-trader 原版代码里没有 Jev key 时使用的占位规则（MOM + DI + TFI 的加权），去掉了它的随机噪声。',
    ref: 'jarrodwatts/jev-trader，src/model.ts 中的 MockModel',
    f: s => { const v = s.trades30s.buyBTC + s.trades30s.sellBTC, flow = v ? s.trades30s.cvdBTC / v : 0;
      return sig(s.returnsBps.last20 / 8 + s.bookImbalance * 1.5 + flow * 2); },
  },
};

// 抛硬币不在 SIGNALS 里（引擎直接 Math.random()），这里补上说明给页面用
export const COIN = {name: '随机基准', abbr: 'RAND', en: 'Coin Flip', group: '基准',
  formula: '每个决策点独立随机，涨跌各 50%', why: '任何判断都应该先跑赢它。挂单时它衡量的是「不带判断」时被动成交的平均结果（纯逆向选择成本）。', ref: '—'};

export const SIGNAL_KEYS = Object.keys(SIGNALS);

// 一次算完所有规则。
// 信号恰好为 0（比如 1.5 秒内价格没动、两边挂单量相等）时，规则没有信息，随机选一个方向。
// 不这么做的话 0.5 会被当成「看涨」，产生系统性偏差。Jev 被强制二选一，规则也一样，比较才公平。
const TIE = 1e-4;
export const runSignals = state => Object.fromEntries(SIGNAL_KEYS.map(k => {
  let p = SIGNALS[k].f(state);
  if (!Number.isFinite(p)) p = .5;
  if (Math.abs(p - .5) < 1e-9) p = .5 + (Math.random() < .5 ? -TIE : TIE);
  return [k, Math.max(0, Math.min(1, p))];
}));

// OFI 要看相邻两个时刻的买一卖一怎么变：价格往上抬=整份挂单量算新增，价格被打掉=旧挂单量算消失
export function ofiTick(top, prev) {
  if (!prev) return 0;
  const b = top.bidPx > prev.bidPx ? top.bidQty : top.bidPx === prev.bidPx ? top.bidQty - prev.bidQty : -prev.bidQty;
  const a = top.askPx < prev.askPx ? top.askQty : top.askPx === prev.askPx ? top.askQty - prev.askQty : -prev.askQty;
  return b - a;
}

// 给页面「方法」和表头提示用的元数据（不含函数）
export const strategyMeta = () => Object.fromEntries([...Object.entries(SIGNALS), ['coin', COIN]].map(([k, v]) => [k,
  {name: v.name, abbr: v.abbr, en: v.en, group: v.group, formula: v.formula, why: v.why, ref: v.ref}]));

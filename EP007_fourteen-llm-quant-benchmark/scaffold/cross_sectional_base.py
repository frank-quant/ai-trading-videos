# -*- coding: utf-8 -*-
"""
EP004 横截面多因子脚手架（Freqtrade 2026.6）
============================================
把「横截面对齐 + 排名 + 选股 + 多空信号 + 防未来函数」这些苦活封装好。
模型（子类）只需实现一个方法：

    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        # df : 单个币的 OHLCV（date/open/high/low/close/volume），按时间升序
        # 返回：每根 K 线一个「看多分数」，越高越看多。
        #        必须【因果】——只用当根及之前的数据，不许用未来。

脚手架保证（这部分锁死，勿改）：
  - 每个时点把全池币的分数横向对齐 → 横截面百分位排名（每行内 0..1）
  - shift(1)：第 t 根的持仓决策只用 t-1 收盘时可知的横截面（防未来函数）

你（子类）可以自由决定的：
  - `timeframe`：30m / 1h / 4h / 1d 都行（数据都已备好）。**频率直接决定交易成本，
    这是本题的核心权衡之一** —— 频率越高，手续费吃掉的越多。
  - 选股宽度 n_long / n_short
  - **换手控制**：exit_buffer（滞后带）、min_hold（最短持仓）—— 都可 hyperopt
  - 也可以直接重写 populate_entry_trend / populate_exit_trend 实现你自己的交易逻辑，
    只要用脚手架给的 `xs_rank` 列、且不动 _build_panel 的防未来函数逻辑。

已知边界：
  - factor_score 的输入仅 OHLCV（资金费率类因子需自行接数据）。
"""
import numpy as np
import pandas as pd
from freqtrade.exchange import timeframe_to_minutes
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter


class CrossSectionalBase(IStrategy):
    # ↓↓↓ 以下全是【默认值,不是规则】,子类想改就改 ↓↓↓
    timeframe = "30m"           # 30m / 1h / 4h / 1d 都有数据
    can_short = True
    process_only_new_candles = True
    startup_candle_count = 300  # 用更长回看窗的因子请调大
    stoploss = -0.99            # 默认几乎不触发;想加真止损就覆盖它
    minimal_roi = {"0": 100}    # 默认关闭 ROI 退出;想用就覆盖
    # 唯一不可改的是 leverage()(题目规定 ≤1x)和 _build_panel 的 shift(1)(防未来函数)

    # 选股宽度（可 hyperopt）
    # 20 个币 → 上限 10/10 表示用满整个横截面(全多空对冲)
    n_long = IntParameter(1, 10, default=5, space="buy", optimize=True)
    n_short = IntParameter(1, 10, default=5, space="buy", optimize=True)

    # ---- 换手控制（可 hyperopt）：高频下这两个直接决定你会不会被手续费吃光 ----
    # 滞后带：进榜才买，掉出「阈值 + buffer」才卖 —— 避免在阈值附近反复横跳
    exit_buffer = DecimalParameter(0.0, 0.4, default=0.15, decimals=2,
                                   space="buy", optimize=True)
    # 最短持仓根数：开仓后至少持有 N 根 K 线
    min_hold = IntParameter(0, 48, default=4, space="buy", optimize=True)

    _ranks_cache = None
    _ranks_sig = None      # 缓存对应的参数签名(参数一变就重建,防 hyperopt 静默失效)

    # ===================== 子类实现这个 =====================
    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        raise NotImplementedError(
            "子类必须实现 factor_score(df, pair) -> 看多分数(因果, 不看未来)")

    # ===================== 脚手架内部 =====================
    def _build_panel(self):
        """把全池 factor_score 对齐成横截面面板,做唯一一件强制的事:shift(1) 防未来函数。

        返回 {pair: (score_series, rank_series)}:
          - score:  你的 factor_score 原值(已 shift1)—— 保留大小/强弱信息
          - rank:   横截面百分位(0..1,已 shift1)—— 方便直接做排序选股
        **两个都给你,用哪个随你**。排名只是便利,不是规定。
        """
        pairs = self.dp.current_whitelist()
        cols = {}
        for p in pairs:
            d = self.dp.get_pair_dataframe(p, self.timeframe)
            if d is None or len(d) == 0:
                continue
            d = d.copy()
            s = self.factor_score(d, p)
            # 保留时区(Freqtrade 的 date 是 tz-aware UTC)——不能用 .values 剥时区,否则映射全 NaN
            cols[p] = pd.Series(np.asarray(s, dtype="float64"),
                                index=pd.DatetimeIndex(d["date"]))
        if not cols:
            return {}
        panel = pd.DataFrame(cols).sort_index()
        # 唯一强制的一步:shift(1) —— 第 t 根的决策只能用 t-1 收盘时可知的横截面
        scores = panel.shift(1)                              # 原始分数(保留强弱)
        ranks = panel.rank(axis=1, pct=True).shift(1)        # 百分位排名(便利,非强制)
        return {p: (scores[p], ranks[p]) for p in panel.columns}

    def _param_signature(self):
        """当前所有可优化参数的值 —— 面板缓存的 key。

        ⚠️ 关键:hyperopt 只优化 buy space 时**不会重跑 populate_indicators**,
        若把因子算在那里、并按「第一个 pair」触发重建,参数改了也不生效(静默失效)。
        改用参数签名做 key + 在 entry/exit 阶段构建,参数一变必定重算。
        """
        from freqtrade.strategy.parameters import BaseParameter
        sig = []
        for name in dir(type(self)):
            try:
                attr = getattr(type(self), name)
            except Exception:
                continue
            if isinstance(attr, BaseParameter):
                try:
                    sig.append((name, getattr(self, name).value))
                except Exception:
                    pass
        return tuple(sorted(sig, key=lambda x: x[0]))

    def _attach_rank(self, dataframe, metadata):
        """给 dataframe 挂上两列(都已 shift1、防未来函数):
             xs_score —— 你的因子原始分数(横截面对齐后)
             xs_rank  —— 横截面百分位 0..1
           用哪个、怎么用,完全由你的 entry/exit 逻辑决定。
        """
        sig = self._param_signature()
        if self._ranks_cache is None or self._ranks_sig != sig:
            type(self)._ranks_cache = self._build_panel()
            type(self)._ranks_sig = sig
        pair_data = self._ranks_cache.get(metadata["pair"])
        dataframe = dataframe.copy()
        if pair_data is None:
            dataframe["xs_score"] = np.nan
            dataframe["xs_rank"] = np.nan
        else:
            score_s, rank_s = pair_data
            # 与 dataframe["date"] 同为 tz-aware UTC,直接按日期映射
            dataframe["xs_score"] = dataframe["date"].map(score_s)
            dataframe["xs_rank"] = dataframe["date"].map(rank_s)
        return dataframe

    def populate_indicators(self, dataframe, metadata):
        # 故意不在这里算因子:hyperopt(--spaces buy)不会重跑本函数,
        # 在此计算会导致因子参数静默失效。改在 populate_entry_trend 里算。
        return dataframe

    def _thresholds(self):
        n = max(len(self.dp.current_whitelist()), 1)
        long_thr = 1.0 - (self.n_long.value / n)
        short_thr = self.n_short.value / n
        return long_thr, short_thr

    def populate_entry_trend(self, dataframe, metadata):
        dataframe = self._attach_rank(dataframe, metadata)   # 因子/排名在此计算(hyperopt 每轮都会跑)
        long_thr, short_thr = self._thresholds()
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe.loc[dataframe["xs_rank"] >= long_thr, "enter_long"] = 1
        dataframe.loc[dataframe["xs_rank"] <= short_thr, "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        if "xs_rank" not in dataframe.columns:
            dataframe = self._attach_rank(dataframe, metadata)
        long_thr, short_thr = self._thresholds()
        # 滞后带:掉出「阈值 − buffer」才平多;升过「阈值 + buffer」才平空。
        # buffer 越大 → 换手越低 → 手续费越省(但信号也越钝)。
        b = float(self.exit_buffer.value)
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        dataframe.loc[dataframe["xs_rank"] < (long_thr - b), "exit_long"] = 1
        dataframe.loc[dataframe["xs_rank"] > (short_thr + b), "exit_short"] = 1
        return dataframe

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs) -> bool:
        # 最短持仓:开仓后至少持有 min_hold 根 K 线才允许平仓,
        # 防止在阈值附近瞬间进出被手续费磨死。min_hold=0 表示不限制。
        n = int(self.min_hold.value)
        if n <= 0:
            return True
        held_min = (current_time - trade.open_date_utc).total_seconds() / 60.0
        return held_min >= n * timeframe_to_minutes(self.timeframe)

    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, side, **kwargs):
        return 1.0

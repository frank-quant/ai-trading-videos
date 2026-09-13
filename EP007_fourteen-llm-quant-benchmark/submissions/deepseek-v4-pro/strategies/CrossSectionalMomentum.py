# -*- coding: utf-8 -*-
"""
CrossSectionalMomentum — 横截面「跳日」风险调整动量策略（Freqtrade 2026.6）

策略家族：横截面多因子（趋势/动量，市场中性为主、带轻微净多头倾向）。
做多动量最强、做空动量最弱，多空对冲掉大部分市场 beta，只保留横截面相对强弱（alpha）。

因子（每根 K 线一个「看多分数」，严格因果，无未来函数）：
    score_t =  (close_{t-skip} / close_{t-(mom_window+skip)} - 1)
              /  std(1 日收益率, vol_window)
  - mom_window : 动量回看窗（1d 下即天数）
  - skip       : 跳过最近 skip 根 K 线 —— 规避加密货币横截面上很强的「短期反转」
                 (reversal)。动量文献中的标准稳健化手段：把动量区间的前端往后移，
                 避免把昨天刚暴涨/暴跌的「反转候选」误判成动量信号。
  - vol_window : 波动率回看窗。除以已实现波动率做风险归一化，压低对高波动币种的
                 敞口，并让 train/valid 两个区间的表现更稳定（见 design.md）。

用 CrossSectionalBase 脚手架做横截面对齐 + shift(1) 防未来函数（第 t 根决策只用
t-1 收盘可知的横截面），并按百分位排名选股：做多最高 n_long 个、做空最低 n_short 个。
换手由 exit_buffer（滞后带）+ min_hold（最短持仓）控制。

全部超参数在 "buy" space，供 `--spaces buy` hyperopt 使用。default 即最终选定参数。
"""
import pandas as pd
from freqtrade.strategy import IntParameter, DecimalParameter
from cross_sectional_base import CrossSectionalBase


class CrossSectionalMomentum(CrossSectionalBase):
    timeframe = "1d"
    can_short = True
    startup_candle_count = 200

    # ---- 因子参数（default = 最终选定值）----
    mom_window = IntParameter(5, 40, default=12, space="buy", optimize=True)
    skip = IntParameter(0, 6, default=3, space="buy", optimize=True)
    vol_window = IntParameter(5, 60, default=18, space="buy", optimize=True)

    # ---- 选股宽度与换手控制（default = 最终选定值；覆盖脚手架默认）----
    n_long = IntParameter(1, 10, default=7, space="buy", optimize=True)
    n_short = IntParameter(1, 10, default=4, space="buy", optimize=True)
    exit_buffer = DecimalParameter(0.0, 0.4, default=0.17, decimals=2,
                                   space="buy", optimize=True)
    min_hold = IntParameter(0, 20, default=19, space="buy", optimize=True)

    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        # 因果：只用当根及之前数据，无未来函数。
        close = df["close"]
        w = int(self.mom_window.value)
        s = int(self.skip.value)
        v = int(self.vol_window.value)
        # 「跳日」动量：从 t-(w+s) 到 t-s 的收益，跳过最近 s 根（避免短期反转）。
        mom = close.shift(s) / close.shift(w + s) - 1.0
        vol = close.pct_change().rolling(v).std().clip(lower=1e-6)
        return mom / vol

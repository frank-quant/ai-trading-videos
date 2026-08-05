# -*- coding: utf-8 -*-
"""
脚手架自带示例：横截面动量（仅用于冒烟测试脚手架是否跑通，不是参赛策略）。
模型看这个就懂脚手架怎么用：只写 factor_score，其余全由 CrossSectionalBase 接管。
"""
import pandas as pd
from freqtrade.strategy import IntParameter
from cross_sectional_base import CrossSectionalBase


class ExampleXSMomentum(CrossSectionalBase):
    mom_window = IntParameter(6, 96, default=48, space="buy", optimize=True)

    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        # N 根动量：close[t] / close[t-N] - 1，越高越强 → 看多。因果（只用当根及之前）。
        return df["close"].pct_change(self.mom_window.value)

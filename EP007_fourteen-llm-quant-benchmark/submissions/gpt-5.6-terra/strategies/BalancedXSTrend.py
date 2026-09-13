# -*- coding: utf-8 -*-
"""Slow, risk-adjusted cross-sectional trend for the fixed futures universe."""
import numpy as np
import pandas as pd

from freqtrade.strategy import IntParameter, DecimalParameter
from cross_sectional_base import CrossSectionalBase


class BalancedXSTrend(CrossSectionalBase):
    """Rank liquid perpetuals by a blend of medium and long horizon risk-adjusted return.

    The parent attaches the cross-sectional rank with a mandatory one-candle delay.
    """

    timeframe = "4h"
    can_short = True
    process_only_new_candles = True
    startup_candle_count = 300
    stoploss = -0.22
    minimal_roi = {"0": 100}

    # Fixed seed search selection (60 completed EP004ValidLoss trials).
    n_long = IntParameter(1, 10, default=5, space="buy", optimize=True)
    n_short = IntParameter(1, 10, default=3, space="buy", optimize=True)
    exit_buffer = DecimalParameter(0.0, 0.4, default=0.11, decimals=2,
                                   space="buy", optimize=True)
    min_hold = IntParameter(0, 48, default=47, space="buy", optimize=True)

    # Factor horizons are 4-hour candles.  Defaults are deliberately slow enough
    # to avoid paying taker costs for short-lived relative-strength noise.
    fast_window = IntParameter(12, 72, default=18, space="buy", optimize=True)
    slow_window = IntParameter(72, 240, default=89, space="buy", optimize=True)
    vol_window = IntParameter(30, 180, default=171, space="buy", optimize=True)
    fast_weight = DecimalParameter(0.0, 1.0, default=0.15, decimals=2,
                                   space="buy", optimize=True)

    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        close = df["close"].astype(float)
        logret = np.log(close).diff()
        vol = logret.rolling(int(self.vol_window.value), min_periods=20).std()
        # Scale each horizon by trailing realized volatility, rather than giving
        # structurally more volatile altcoins an automatic high rank.
        fast = np.log(close / close.shift(int(self.fast_window.value))) / vol
        slow = np.log(close / close.shift(int(self.slow_window.value))) / vol
        w = float(self.fast_weight.value)
        return w * fast + (1.0 - w) * slow

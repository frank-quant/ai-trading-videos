# -*- coding: utf-8 -*-
"""Causal cross-sectional multi-horizon trend strategy for crypto futures."""

import numpy as np
import pandas as pd
from freqtrade.strategy import DecimalParameter, IntParameter

from cross_sectional_base import CrossSectionalBase


class CausalXSTrend(CrossSectionalBase):
    """Trade persistent relative trends while suppressing noisy short-term moves."""

    timeframe = "4h"
    can_short = True
    startup_candle_count = 300
    stoploss = -0.99
    minimal_roi = {"0": 100.0}

    # All tunable values deliberately live in the required buy space.
    fast_window = IntParameter(18, 60, default=41, space="buy", optimize=True)
    slow_window = IntParameter(72, 240, default=136, space="buy", optimize=True)
    vol_window = IntParameter(24, 120, default=91, space="buy", optimize=True)
    reversal_window = IntParameter(3, 18, default=15, space="buy", optimize=True)
    slow_weight = DecimalParameter(0.30, 0.80, default=0.55, decimals=2,
                                   space="buy", optimize=True)
    reversal_weight = DecimalParameter(0.00, 0.50, default=0.46, decimals=2,
                                       space="buy", optimize=True)

    # Narrower inherited ranges reduce overlap and keep the portfolio diversified.
    n_long = IntParameter(2, 7, default=6, space="buy", optimize=True)
    n_short = IntParameter(2, 7, default=3, space="buy", optimize=True)
    exit_buffer = DecimalParameter(0.05, 0.35, default=0.11, decimals=2,
                                   space="buy", optimize=True)
    min_hold = IntParameter(6, 48, default=46, space="buy", optimize=True)

    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        close = df["close"].astype(float).clip(lower=1e-12)
        log_price = np.log(close)
        log_ret = log_price.diff()

        fast = int(self.fast_window.value)
        slow = int(self.slow_window.value)
        vol_n = int(self.vol_window.value)
        rev_n = int(self.reversal_window.value)
        slow_w = float(self.slow_weight.value)

        # Scale each horizon by the volatility expected over that horizon. This
        # prevents volatile alts from dominating the raw cross-sectional score.
        daily_vol = log_ret.rolling(vol_n, min_periods=vol_n).std().clip(lower=1e-8)
        fast_trend = log_price.diff(fast) / (daily_vol * np.sqrt(fast))
        slow_trend = log_price.diff(slow) / (daily_vol * np.sqrt(slow))
        short_move = log_price.diff(rev_n) / (daily_vol * np.sqrt(rev_n))

        trend = (1.0 - slow_w) * fast_trend + slow_w * slow_trend
        score = trend - float(self.reversal_weight.value) * short_move
        return score.replace([np.inf, -np.inf], np.nan)

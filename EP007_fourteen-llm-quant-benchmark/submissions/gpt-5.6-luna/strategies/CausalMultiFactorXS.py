# -*- coding: utf-8 -*-
"""Causal, cross-sectional multi-factor futures strategy.

The score is intentionally calculated from each pair's own trailing OHLCV only.
Cross-sectional alignment and the mandatory one-candle decision delay are supplied
by CrossSectionalBase.
"""

import numpy as np
import pandas as pd
from freqtrade.strategy import DecimalParameter, IntParameter

from cross_sectional_base import CrossSectionalBase


class CausalMultiFactorXS(CrossSectionalBase):
    """Slow cross-sectional momentum with a short-horizon reversal overlay."""

    timeframe = "4h"
    can_short = True
    startup_candle_count = 300

    # Final selected values are also defaults so the strategy remains reproducible
    # even if the generated Freqtrade parameter sidecar is absent.
    n_long = IntParameter(1, 10, default=6, space="buy", optimize=True)
    n_short = IntParameter(1, 10, default=1, space="buy", optimize=True)
    exit_buffer = DecimalParameter(0.0, 0.4, default=0.11, decimals=2,
                                   space="buy", optimize=True)
    min_hold = IntParameter(0, 48, default=39, space="buy", optimize=True)
    mom_fast = IntParameter(6, 30, default=9, space="buy", optimize=True)
    mom_slow = IntParameter(24, 120, default=100, space="buy", optimize=True)
    reversal_window = IntParameter(2, 12, default=4, space="buy", optimize=True)
    volatility_window = IntParameter(18, 72, default=47, space="buy", optimize=True)
    trend_weight = DecimalParameter(0.0, 1.0, default=0.70, decimals=2,
                                    space="buy", optimize=True)
    reversal_weight = DecimalParameter(0.0, 0.8, default=0.56, decimals=2,
                                       space="buy", optimize=True)

    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        """Return a bullish score using only data through the current candle.

        The base class shifts the resulting panel by one candle before making a
        decision. Rolling standard deviation is used only as a trailing risk
        normalization; no cross-pair or full-sample statistics are used here.
        """
        close = pd.to_numeric(df["close"], errors="coerce")
        log_close = np.log(close.replace(0, np.nan))
        fast = log_close.diff(int(self.mom_fast.value))
        slow = log_close.diff(int(self.mom_slow.value))
        reversal = -log_close.diff(int(self.reversal_window.value))
        bar_ret = log_close.diff()
        trailing_vol = bar_ret.rolling(int(self.volatility_window.value),
                                       min_periods=int(self.volatility_window.value)).std()

        # Volatility-normalized medium/long momentum.  The small floor prevents
        # unstable scores during unusually quiet stretches.
        vol = trailing_vol.clip(lower=0.002)
        trend = (0.45 * fast + 0.55 * slow) / vol
        rev = reversal / vol

        # A bounded trend-strength term rewards persistent direction without
        # letting a single extreme return dominate the cross-sectional ranking.
        trend_strength = np.tanh(slow / vol)
        score = trend + float(self.trend_weight.value) * trend_strength
        score = score + float(self.reversal_weight.value) * rev
        return score.replace([np.inf, -np.inf], np.nan)

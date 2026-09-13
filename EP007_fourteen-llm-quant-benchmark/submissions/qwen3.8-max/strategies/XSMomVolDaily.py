# -*- coding: utf-8 -*-
"""
XSMomVolDaily — cross-sectional long/short momentum on daily bars
=================================================================
Family:  cross-sectional momentum (market-neutral-ish long/short).
Signal:  skip-day momentum divided by realized volatility ("risk-adjusted
         momentum"), ranked across the fixed 20-pair universe.

Factor (computed per pair, causal — only current & past bars):

    mom = close[t-S] / close[t-S-W] - 1          # W-bar momentum, skipping the
                                                 # most recent S bars
    rv  = rolling std of 1-bar returns over max(S+W, 20) bars
    score = mom / rv

Why these choices (full justification in design.md):
- Skip (S >= 1): daily crypto returns show 1-3 day reversal; skipping the most
  recent bars keeps the medium-horizon momentum signal clean.
- Vol scaling: normalising momentum by realized volatility stabilises the
  cross-sectional ranking (a 10% move in a quiet name outranks the same move
  in a wild name) and makes the factor closer to a t-statistic.
- 1d timeframe: momentum at ~1-4 week horizons is the best-documented
  cross-sectional effect in crypto, and daily rebalancing decisions keep
  turnover (and the 0.06%/side fee) under control.
- Turnover control comes from the scaffold: exit_buffer (rank hysteresis) and
  min_hold (minimum holding days), both hyperoptable.

Entry/exit (from CrossSectionalBase):
- long the top n_long by cross-sectional rank, short the bottom n_short;
- exit only when rank falls through (threshold - buffer) / (threshold + buffer);
- decisions at bar t use the cross-section known at t-1 (scaffold shift(1)).
"""
import numpy as np
import pandas as pd
from freqtrade.strategy import IntParameter, DecimalParameter
from cross_sectional_base import CrossSectionalBase


class XSMomVolDaily(CrossSectionalBase):
    timeframe = "1d"                 # daily bars: low turnover, documented momentum horizon
    startup_candle_count = 60        # max lookback is skip+window <= 35 (+20-bar vol floor)

    # ---- factor parameters (all in "buy" space) ----
    # Defaults are the final chosen parameters (hyperopt epoch 231 / 300,
    # EP004ValidLoss, train 2021-01..2024-06, valid 2024-07..2025-06).
    mom_window = IntParameter(5, 30, default=14, space="buy", optimize=True)
    skip = IntParameter(0, 5, default=2, space="buy", optimize=True)

    # ---- portfolio breadth (override scaffold defaults: 2..8) ----
    n_long = IntParameter(2, 8, default=7, space="buy", optimize=True)
    n_short = IntParameter(2, 8, default=6, space="buy", optimize=True)

    # ---- turnover controls (override scaffold ranges for daily bars) ----
    exit_buffer = DecimalParameter(0.05, 0.35, default=0.07, decimals=2,
                                   space="buy", optimize=True)
    min_hold = IntParameter(0, 8, default=8, space="buy", optimize=True)

    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        w = int(self.mom_window.value)
        s = int(self.skip.value)
        close = df["close"]

        # skip-day momentum: return from t-S-W to t-S (causal, ends at current bar minus S)
        mom = close.shift(s) / close.shift(s + w) - 1.0

        # realized volatility of 1-bar returns; floor the window at 20 bars so the
        # vol estimate stays meaningful even for short momentum windows
        rv = close.pct_change().rolling(max(s + w, 20)).std()

        score = mom / rv
        return score.replace([np.inf, -np.inf], np.nan)

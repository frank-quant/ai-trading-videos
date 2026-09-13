# -*- coding: utf-8 -*-
"""
MultiFactorXS — Cross-Sectional Multi-Factor Strategy (EP004)
=============================================================
Strategy family: cross-sectional multi-factor (momentum + reversal)
Timeframe: 1h
Universe: 20 fixed crypto perpetual futures

Factors:
  1. Risk-adjusted momentum — close[t]/close[t-N] - 1, divided by rolling vol.
     Captures trend strength; vol-adjustment prevents high-vol coins from
     dominating the cross-section.
  2. Short-term reversal — negative of short-horizon return. Captures the
     well-documented short-term reversal effect in crypto (overreaction
     correction).

Factor blending: each factor is z-scored over a rolling window before combining,
so no single factor dominates the composite score. Equal weight by default.

Look-ahead protection: fully delegated to CrossSectionalBase.shift(1);
all per-pair computations use only expanding/rolling windows (causal).

Turnover control: inherited from CrossSectionalBase (exit_buffer hysteresis +
min_hold minimum holding candles).
"""
import numpy as np
import pandas as pd
from freqtrade.strategy import IntParameter

from cross_sectional_base import CrossSectionalBase


class MultiFactorXS(CrossSectionalBase):
    """Cross-sectional multi-factor: momentum + reversal, 1h timeframe."""

    timeframe = "1h"
    can_short = True
    startup_candle_count = 400  # sufficient for longest lookback + z-score window

    # ------------------------------------------------------------------
    # Factor lookback parameters (hyperoptable)
    # ------------------------------------------------------------------
    # Momentum: close[t] / close[t - mom_window] - 1, risk-adjusted
    mom_window = IntParameter(
        24, 168, default=72, space="buy",
    )

    # Reversal: negative of close[t] / close[t - rev_window] - 1
    rev_window = IntParameter(
        3, 24, default=8, space="buy",
    )

    # Volatility window for risk-adjustment of momentum
    vol_window = IntParameter(
        24, 96, default=48, space="buy",
    )

    # Rolling z-score window for factor blending (puts factors on same scale)
    zscore_window = IntParameter(
        48, 336, default=168, space="buy",
    )

    # ------------------------------------------------------------------
    # Factor score implementation
    # ------------------------------------------------------------------
    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        """
        Compute a composite bullish score for every candle (causal only).

        Returns a Series aligned with df where higher = more bullish.
        """
        # ---- daily returns for vol estimation ----
        ret = df["close"].pct_change()

        # ---- volatility ----
        vol = ret.rolling(self.vol_window.value, min_periods=10).std()
        # Replace zeros to avoid division by zero; np.nan propagates harmlessly
        vol = vol.replace(0.0, np.nan)

        # ---- Factor 1: risk-adjusted momentum ----
        mom_raw = df["close"].pct_change(self.mom_window.value)
        mom_adj = mom_raw / (vol + 1e-9)

        # ---- Factor 2: short-term reversal ----
        rev_raw = -df["close"].pct_change(self.rev_window.value)

        # ---- z-score normalize each factor for comparable blending ----
        mom_z = self._rolling_zscore(mom_adj, self.zscore_window.value)
        rev_z = self._rolling_zscore(rev_raw, self.zscore_window.value)

        # ---- equal-weight composite ----
        score = mom_z.fillna(0.0) + rev_z.fillna(0.0)

        # Clip extreme outliers (3 standard deviations after combination)
        score = score.clip(lower=-6.0, upper=6.0)

        return score

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    @staticmethod
    def _rolling_zscore(series: pd.Series, window: int) -> pd.Series:
        """Rolling z-score: (x - rolling_mean) / rolling_std.  Fully causal."""
        roll_mean = series.rolling(window, min_periods=max(10, window // 4)).mean()
        roll_std = series.rolling(window, min_periods=max(10, window // 4)).std()
        roll_std = roll_std.replace(0.0, np.nan)
        return (series - roll_mean) / (roll_std + 1e-9)

# -*- coding: utf-8 -*-
"""
LowVolReversalXS - Cross-sectional low-volatility + short-term reversal + funding
contrarian strategy (EP004).

Strategy family : cross-sectional multi-factor (reversal + low-vol + funding)
Timeframe       : 1d
Universe        : 20 fixed crypto perpetual futures (from config.json)

Factors (all computed causally, per pair):
  1. Short-term reversal  - negative of the return over `rev_window` days.
     Recent losers tend to outperform over the next 1-10 days (persistent
     positive cross-sectional IC on both TRAIN and VALIDATION).
  2. Low realized volatility - negative rolling vol over `vol_window` days.
     Low-vol coins outperform on a risk-adjusted basis (persistent negative IC).
  3. Contrarian funding - negative of the daily-mean funding rate. High funding
     marks crowded longs, which tend to underperform afterwards.

Blending: each factor is z-scored over a rolling window (causal) so weights are
comparable; the composite score is a weighted sum. The CrossSectionalBase
scaffold aligns scores across all 20 pairs, ranks them, and shift(1) protects
against look-ahead (a decision on bar t uses only information up to t-1).

Turnover control: rank thresholds with hysteresis (exit_buffer) + minimum hold
(min_hold) from the scaffold. Timeframe 1d keeps rebalancing slow so that the
0.06% per side fee does not eat the alpha.
"""
import os

import numpy as np
import pandas as pd
from freqtrade.strategy import DecimalParameter, IntParameter

from cross_sectional_base import CrossSectionalBase

VALID_END = pd.Timestamp("2025-06-30", tz="UTC")

# Cache funding series per pair (loaded once per process; hyperopt workers are
# separate processes, so there is no cross-trial contamination).
_FUNDING_CACHE = {}


class LowVolReversalXS(CrossSectionalBase):
    """Cross-sectional low-vol + reversal + funding contrarian on 1d bars."""

    timeframe = "1d"
    can_short = True
    startup_candle_count = 220  # covers vol window + z-score warmup

    # ------------------------------------------------------------------
    # Factor parameters (hyperoptable, all in "buy" space)
    # ------------------------------------------------------------------
    rev_window = IntParameter(3, 10, default=5, space="buy", optimize=True)
    vol_window = IntParameter(21, 90, default=63, space="buy", optimize=True)

    w_rev = DecimalParameter(0.5, 2.0, default=1.0, decimals=2,
                             space="buy", optimize=True)
    w_vol = DecimalParameter(0.0, 2.0, default=1.0, decimals=2,
                             space="buy", optimize=True)
    w_fund = DecimalParameter(0.0, 1.5, default=0.5, decimals=2,
                              space="buy", optimize=True)

    # Rolling z-score window for factor blending (fixed, not hyperoptable)
    z_window = 120

    # ------------------------------------------------------------------
    # Selection / turnover control (hyperoptable, "buy" space)
    # ------------------------------------------------------------------
    n_long = IntParameter(2, 6, default=4, space="buy", optimize=True)
    n_short = IntParameter(2, 6, default=4, space="buy", optimize=True)
    exit_buffer = DecimalParameter(0.03, 0.30, default=0.12, decimals=2,
                                   space="buy", optimize=True)
    min_hold = IntParameter(1, 10, default=3, space="buy", optimize=True)

    # ------------------------------------------------------------------
    # Factor implementation
    # ------------------------------------------------------------------
    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        """Composite bullish score per candle (causal only)."""
        close = df["close"]
        ret = close.pct_change()

        # Factor 1: short-term reversal (recent loser -> high score)
        rev = -close.pct_change(self.rev_window.value)

        # Factor 2: low realized volatility (high vol -> low score)
        vol = ret.rolling(self.vol_window.value, min_periods=10).std()
        vol = vol.replace(0.0, np.nan)

        # Factor 3: contrarian funding (high funding -> low score)
        fund = self._funding_daily(pair)
        if fund is not None:
            fund_s = fund.reindex(df["date"]).ffill()
            fund_z = self._rolling_z(fund_s, self.z_window)
        else:
            fund_z = pd.Series(0.0, index=df.index)

        rev_z = self._rolling_z(rev, self.z_window)
        vol_z = self._rolling_z(vol, self.z_window)

        score = (self.w_rev.value * rev_z
                 - self.w_vol.value * vol_z
                 - self.w_fund.value * fund_z)
        return score.fillna(0.0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _rolling_z(series: pd.Series, window: int) -> pd.Series:
        """Causal rolling z-score."""
        minp = max(20, int(window // 4))
        mean = series.rolling(window, min_periods=minp).mean()
        std = series.rolling(window, min_periods=minp).std().replace(0.0, np.nan)
        return (series - mean) / (std + 1e-9)

    def _funding_daily(self, pair: str):
        """Daily mean funding rate for a pair, causal, hard-capped at VALID_END."""
        if pair in _FUNDING_CACHE:
            return _FUNDING_CACHE[pair]
        try:
            userdir = str(self.config.get("user_data_dir", "/freqtrade/user_data"))
            fname = pair.replace("/", "_").replace(":", "_") + "-1h-funding_rate.feather"
            path = os.path.join(userdir, "data", "binance", "futures", fname)
            raw = pd.read_feather(path)
            raw = raw[raw["date"] <= VALID_END]
            daily = raw.set_index("date").resample("1D").mean()["open"]
            daily.index = daily.index.tz_convert("UTC")
            daily = daily.rename("funding")
        except Exception:
            daily = None
        _FUNDING_CACHE[pair] = daily
        return daily

    # ------------------------------------------------------------------
    # Entry / exit (same rank-threshold logic as the scaffold defaults,
    # with hysteresis and minimum-hold inherited from CrossSectionalBase)
    # ------------------------------------------------------------------
    def populate_entry_trend(self, dataframe, metadata):
        dataframe = self._attach_rank(dataframe, metadata)
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
        b = float(self.exit_buffer.value)
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        dataframe.loc[dataframe["xs_rank"] < (long_thr - b), "exit_long"] = 1
        dataframe.loc[dataframe["xs_rank"] > (short_thr + b), "exit_short"] = 1
        return dataframe

    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, side, **kwargs):
        # Exam rule: leverage fixed at 1x.
        return 1.0
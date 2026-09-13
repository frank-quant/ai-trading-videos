# -*- coding: utf-8 -*-
"""
EP007 · HybridXSMomentum
========================
Hybrid cross-sectional strategy on 1d candles:

  factor = (momentum(skip=1, N days) - rev_w * 1d-return) / realized_vol(N_vol days)

i.e. a volatility-scaled blend of medium-term momentum and a 1-day reversal term,
computed strictly causally per pair, then aligned across the 20-pair universe by
CrossSectionalBase (which applies the mandatory shift(1)).

Entry adds an ABSOLUTE trend gate on top of the cross-sectional rank gate:
  long  : xs_rank >= long_thr  AND  close > SMA(trend_win)   (if use_trend)
  short : xs_rank <= short_thr AND  close < SMA(trend_win)   (if use_trend)
The gate keeps the book on the right side of each pair's own trend, which cuts
beta and avoids fighting crashes/rallies; it can be switched off via hyperopt.

Exits: scaffold's rank hysteresis (exit_buffer) + min_hold. All parameters live
in the "buy" space for hyperopt. Leverage stays 1.0 (scaffold default).
"""
import numpy as np
import pandas as pd
from freqtrade.strategy import IntParameter, DecimalParameter, BooleanParameter
from cross_sectional_base import CrossSectionalBase


class HybridXSMomentum(CrossSectionalBase):
    timeframe = "1d"
    can_short = True
    startup_candle_count = 150   # covers mom_win<=90 + skip 1 + vol_win<=40 with margin
    stoploss = -0.99             # rank-based exits only; no hard stop (see design.md)
    minimal_roi = {"0": 100}     # ROI exits off

    # ---- factor params (1d bars) ----
    # defaults = hyperopt argmin epoch 237 (EP004ValidLoss, 300 trials, random-state 42)
    mom_win = IntParameter(10, 90, default=63, space="buy", optimize=True)
    vol_win = IntParameter(5, 40, default=35, space="buy", optimize=True)
    rev_w = DecimalParameter(0.0, 1.5, default=1.11, decimals=2, space="buy", optimize=True)
    SKIP = 1  # momentum skips the most recent day (classic short-term-reversal skip)

    # ---- absolute trend gate ----
    use_trend = BooleanParameter(default=True, space="buy", optimize=True)
    trend_win = IntParameter(10, 120, default=45, space="buy", optimize=True)

    # ---- scaffold selection / turnover params, re-ranged for 1d ----
    n_long = IntParameter(1, 10, default=3, space="buy", optimize=True)
    n_short = IntParameter(1, 10, default=1, space="buy", optimize=True)
    exit_buffer = DecimalParameter(0.0, 0.4, default=0.34, decimals=2,
                                   space="buy", optimize=True)
    min_hold = IntParameter(0, 20, default=17, space="buy", optimize=True)

    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        close = df["close"]
        r1 = close.pct_change(1)
        mom = close.shift(self.SKIP).pct_change(self.mom_win.value)
        vol = r1.rolling(self.vol_win.value).std()
        return (mom - float(self.rev_w.value) * r1) / vol

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe = self._attach_rank(dataframe, metadata)
        long_thr, short_thr = self._thresholds()

        long_ok = dataframe["xs_rank"] >= long_thr
        short_ok = dataframe["xs_rank"] <= short_thr
        if self.use_trend.value:
            sma = dataframe["close"].rolling(self.trend_win.value).mean()
            long_ok = long_ok & (dataframe["close"] > sma)
            short_ok = short_ok & (dataframe["close"] < sma)

        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe.loc[long_ok, "enter_long"] = 1
        dataframe.loc[short_ok, "enter_short"] = 1
        return dataframe

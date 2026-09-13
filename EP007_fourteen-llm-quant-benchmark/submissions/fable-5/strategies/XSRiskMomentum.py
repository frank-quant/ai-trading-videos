# -*- coding: utf-8 -*-
"""
XSRiskMomentum — cross-sectional risk-adjusted momentum, 4h timeframe.
======================================================================
Factor (causal, OHLCV only):

    score[t] = ( close[t-skip] / close[t-skip-W] - 1 ) / realized_vol_W[t]

  - W    = mom_days * 6 bars   (4h bars, 6 per day): medium-term momentum window
  - skip = skip_days * 6 bars  : skip the most recent day(s) to sidestep the
                                 well-documented short-term reversal in crypto
  - realized_vol_W = rolling std of 1-bar log returns over the same W bars —
    dividing by vol turns raw momentum into a t-statistic-like score, so the
    ranking prefers steady trends over one-off pump candles (which mean-revert
    and would otherwise dominate the top/bottom ranks).

Everything is backward-looking (positive shifts, trailing rolling windows).
The CrossSectionalBase scaffold then aligns the score across the 20 pairs,
ranks it cross-sectionally and applies shift(1): the decision for bar t uses
only information known at the close of bar t-1. That protection is inherited
untouched.

Portfolio: long the top n_long ranks, short the bottom n_short ranks.
Turnover control: rank hysteresis (exit_buffer) + minimum holding time
(min_hold bars). Leverage stays at the scaffold's fixed 1.0.

Risk overlay (fixed, not hyperopted — hyperopt runs on the buy space only):
  - stoploss -30%: catastrophic stop per position. A 1x short that gets caught
    in an alt-coin melt-up would otherwise ride toward liquidation (-100%).
  - min_hold never blocks stoploss/liquidation exits (safety exits must not be
    delayed by a turnover control).
"""
import numpy as np
import pandas as pd
from freqtrade.strategy import IntParameter

from cross_sectional_base import CrossSectionalBase

BARS_PER_DAY = 6  # 4h bars


class XSRiskMomentum(CrossSectionalBase):
    timeframe = "4h"
    can_short = True
    startup_candle_count = 320   # max lookback = (42+2)*6 = 264 bars + margin
    stoploss = -0.30             # catastrophic stop only; ranks do the real exits
    minimal_roi = {"0": 100}     # ROI exits disabled

    # ---- factor parameters (buy space, hyperoptable) ----
    mom_days = IntParameter(5, 42, default=21, space="buy", optimize=True)
    skip_days = IntParameter(0, 2, default=1, space="buy", optimize=True)

    # ---- portfolio width (inherited defaults n_long/n_short 1..10) ----
    # ---- turnover controls: narrower min_hold range suited to 4h bars ----
    min_hold = IntParameter(0, 30, default=6, space="buy", optimize=True)

    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        w = int(self.mom_days.value) * BARS_PER_DAY
        skip = int(self.skip_days.value) * BARS_PER_DAY
        mom = df["close"].shift(skip) / df["close"].shift(skip + w) - 1.0
        log_ret = np.log(df["close"] / df["close"].shift(1))
        vol = log_ret.rolling(w, min_periods=w).std()
        return mom / (vol + 1e-9)

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate,
                           time_in_force, exit_reason, current_time, **kwargs) -> bool:
        # Safety exits always pass; min_hold only throttles signal-driven exits.
        if exit_reason in ("stoploss", "liquidation"):
            return True
        return super().confirm_trade_exit(pair, trade, order_type, amount, rate,
                                          time_in_force, exit_reason, current_time,
                                          **kwargs)

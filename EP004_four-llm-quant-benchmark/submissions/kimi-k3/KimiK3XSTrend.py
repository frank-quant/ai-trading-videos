# -*- coding: utf-8 -*-
"""
KimiK3XSTrend — cross-sectional trend/momentum combo, long+short, 20 crypto perps.
====================================================================================
Design (see design.md for full justification):
  - Factor = (1-w) * t-stat momentum (fast window) + w * vol-normalized momentum (slow window).
    Both causal (rolling windows, current & past bars only). Cross-sectional alignment,
    ranking and the mandatory shift(1) anti-look-ahead are handled by CrossSectionalBase.
  - Long the top-N ranks, short the bottom-N ranks; hysteresis (exit_buffer) and min_hold
    control turnover — the central cost constraint of this task (0.12% per round trip).
"""
import numpy as np
import pandas as pd
from freqtrade.strategy import IntParameter, DecimalParameter
from cross_sectional_base import CrossSectionalBase


class KimiK3XSTrend(CrossSectionalBase):
    timeframe = "1d"
    startup_candle_count = 220  # covers max factor window (180 bars) + warmup

    # ---- factor params (hyperopt, buy space) ----
    # fast leg: t-stat of log returns over mom_fast days (default 30)
    mom_fast = IntParameter(10, 60, default=30, space="buy", optimize=True)
    # slow leg: plain momentum over mom_slow days, normalized by vol (default 90)
    mom_slow = IntParameter(60, 180, default=90, space="buy", optimize=True)
    # blend weight of the slow leg
    w_slow = DecimalParameter(0.0, 1.0, default=0.4, decimals=2, space="buy", optimize=True)
    # vol window used to normalize the slow leg (days)
    vol_win = IntParameter(5, 40, default=20, space="buy", optimize=True)

    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        close = df["close"]
        lr = np.log(close / close.shift(1))
        wf = int(self.mom_fast.value)
        ws = int(self.mom_slow.value)
        wv = int(self.vol_win.value)
        # fast leg: t-stat momentum — mean/std * sqrt(w) of log returns (causal rolling)
        mu = lr.rolling(wf).mean()
        sd = lr.rolling(wf).std()
        fast = mu / (sd + 1e-12) * np.sqrt(wf)
        # slow leg: momentum normalized by its own volatility (sharpe-like, causal)
        mom = close.pct_change(ws)
        vol = close.pct_change().rolling(wv).std() * np.sqrt(ws)
        slow = mom / (vol + 1e-12)
        w = float(self.w_slow.value)
        return (1.0 - w) * fast + w * slow

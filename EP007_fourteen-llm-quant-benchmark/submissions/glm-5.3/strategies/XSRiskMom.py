# -*- coding: utf-8 -*-
"""
XSRiskMom — cross-sectional risk-adjusted momentum, long/short, daily bars.

Built on the EP004 scaffold (CrossSectionalBase), which provides:
  - cross-sectional alignment of the per-pair causal factor over the 20-pair
    universe, percentile ranks (0..1) per bar,
  - the mandatory shift(1) look-ahead protection (untouched),
  - hyperoptable n_long / n_short selection and turnover controls
    (exit_buffer hysteresis band, min_hold minimum holding bars).

Factor (causal, OHLCV only, per pair — higher = more bullish):
    mom   = close / close.shift(W) - 1        W-day price momentum
    vol   = rolling std of daily returns over V days
    score = mom / vol                         risk-adjusted momentum
The vol scaling is a monotone-in-vol rescaling of each name's momentum: it
demotes high-volatility "lottery" names whose raw momentum is mostly noise,
a well-documented improvement over raw momentum in crypto cross-sections.
Ranks, not magnitudes, drive trading, so only the *ranking* effect of the
vol scaling matters.

Portfolio: each day (using yesterday's cross-section), the top n_long ranks
are held long and the bottom n_short ranks short. A long is only closed when
the rank drops below (long_thr - exit_buffer), a short only when it rises
above (short_thr + exit_buffer) — the hysteresis band plus min_hold are the
turnover controls that keep the 0.06%-per-side fee from eating the edge.
"""
import numpy as np
import pandas as pd

from cross_sectional_base import CrossSectionalBase
from freqtrade.strategy import IntParameter, DecimalParameter


class XSRiskMom(CrossSectionalBase):
    timeframe = "1d"          # daily cadence: lowest cost per unit of signal
    startup_candle_count = 100  # >= mom_window.max + vol_window.max + slack

    # ---- factor lookbacks (buy space) — defaults are the FINAL chosen params
    # (hyperopt epoch 303 of the 400-epoch run, seed 42) ----
    mom_window = IntParameter(5, 60, default=9, space="buy", optimize=True)
    vol_window = IntParameter(10, 40, default=39, space="buy", optimize=True)

    # ---- scaffold portfolio params, ranges narrowed for a daily cadence ----
    # 2..8 per side: >=2 avoids single-name idiosyncratic books, <=8 keeps
    # selection in the tails of the cross-section where the momentum signal
    # is strongest (and keeps long/short books from overlapping).
    n_long = IntParameter(2, 8, default=8, space="buy", optimize=True)
    n_short = IntParameter(2, 8, default=4, space="buy", optimize=True)
    exit_buffer = DecimalParameter(0.0, 0.4, default=0.24, decimals=2,
                                   space="buy", optimize=True)
    # min holding of 0..20 daily bars (scaffold default range 0..48 is tuned
    # for intrabar timeframes; 20 days is already a very long lock on 1d)
    min_hold = IntParameter(0, 20, default=19, space="buy", optimize=True)

    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        close = df["close"]
        ret = close.pct_change()
        mom = close.pct_change(self.mom_window.value)
        vol = ret.rolling(self.vol_window.value).std()
        score = mom / vol
        # degenerate guard (flat price windows); NaN simply drops out of ranks
        return score.replace([np.inf, -np.inf], np.nan)

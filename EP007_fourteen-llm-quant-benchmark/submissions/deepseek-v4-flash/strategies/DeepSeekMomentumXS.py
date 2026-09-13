# -*- coding: utf-8 -*-
"""
DeepSeekMomentumXS - EP004 cross-sectional momentum strategy (1d).

Strategy family : cross-sectional momentum (rank-based, long + short)
Timeframe       : 1d
Universe        : the 20 fixed USDT-margined perpetuals from config.json

Signal:
    factor_score = close[t] / close[t - mom_window] - 1   (raw momentum)
CrossSectionalBase aligns the factor across all 20 pairs and applies
shift(1), so the decision at bar t uses only information up to t-1. The
scaffold then ranks the factor cross-sectionally (xs_rank): we long the
top n_long coins and short the bottom n_short coins.

Why momentum (see design.md for details):
  * Cross-sectional momentum in crypto is one of the most persistent
    anomalies; the top/bottom-tail continuation is strong at 10-45d
    lookbacks and 1-2 week horizons on BOTH TRAIN and VALIDATION.
  * We deliberately do NOT z-score or vol-adjust the factor per coin:
    per-coin normalisation destroys the cross-sectional tail ranking
    (verified empirically on TRAIN).

Turnover control (inherited from CrossSectionalBase):
  * exit_buffer: exit only once rank falls below threshold - buffer
    (hysteresis band keeps the book sticky and cuts round trips).
  * min_hold: minimum holding period in days before a position may close.
  * 1d timeframe keeps rebalancing slow; fees are 6bps per side.

All hyperopt parameters are declared in the "buy" space.
"""
import pandas as pd
from freqtrade.strategy import DecimalParameter, IntParameter

from cross_sectional_base import CrossSectionalBase


class DeepSeekMomentumXS(CrossSectionalBase):
    """Cross-sectional momentum, 1d bars, long top N / short bottom N."""

    timeframe = "1d"
    can_short = True
    process_only_new_candles = True
    startup_candle_count = 60  # covers max mom_window + margin

    # ------------------------------------------------------------------
    # Factor parameters (hyperoptable, "buy" space)
    # ------------------------------------------------------------------
    # Momentum lookback in days. 10-24d brackets the strongest, most
    # consistent tail continuation found on TRAIN (10-18d sweet spot).
    mom_window = IntParameter(10, 24, default=13, space="buy", optimize=True)

    # ------------------------------------------------------------------
    # Selection & turnover control (hyperoptable, "buy" space)
    # ------------------------------------------------------------------
    n_long = IntParameter(5, 9, default=7, space="buy", optimize=True)
    n_short = IntParameter(5, 9, default=5, space="buy", optimize=True)
    exit_buffer = DecimalParameter(0.15, 0.45, default=0.15, decimals=2,
                                   space="buy", optimize=True)
    min_hold = IntParameter(5, 15, default=10, space="buy", optimize=True)

    # ------------------------------------------------------------------
    # Factor implementation (causal, per-pair)
    # ------------------------------------------------------------------
    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        """N-day simple momentum; higher = more bullish.  Causal only."""
        return df["close"].pct_change(self.mom_window.value)

    # leverage: intentionally NOT overridden; CrossSectionalBase returns 1.0
    # (exam rule: leverage fixed at 1x).

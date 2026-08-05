# -*- coding: utf-8 -*-
"""
XSTrendEnsemble — cross-sectional multi-factor trend, dollar-neutral, long+short.
EP004 submission.

Idea
----
Within a fixed 20-name perp universe, rank every coin each bar on FOUR causal
trend measures that capture the same economic effect (cross-sectional trend
persistence) through different, partly-uncorrelated lenses:

  1. mom      : simple N-day return                          (classic XS momentum)
  2. ma_fast  : (close / SMA_fast - 1) / realised-vol        (vol-normalised trend)
  3. ma_slow  : (close / SMA_slow - 1) / realised-vol        (slower trend, same form)
  4. pos      : position inside the N-day high/low range     (breakout / Donchian)

Each leg is converted to a CROSS-SECTIONAL percentile at that bar (so no leg can
dominate through scale), the four percentiles are averaged, and the composite is
smoothed with a rolling mean over `smooth_days` — the smoothing is the primary
turnover control and is what makes the book survive 6 bps/side.

The composite is handed to CrossSectionalBase.factor_score(); the scaffold then
aligns it across the 20 pairs, ranks it cross-sectionally and applies its
shift(1) look-ahead protection. Nothing in the scaffold is modified or weakened:
ranking an already-ranked composite is a monotone transform, so the ordering the
scaffold sees is exactly the composite ordering, one bar late.

Book construction: long the top `n_side`, short the bottom `n_side` of 20 names,
equal notional, so the book is dollar-neutral by construction — the return is
cross-sectional dispersion, not market beta. Leverage is the inherited 1.0.

Look-ahead: every leg uses only trailing windows of its own pair; the only
cross-pair step is a contemporaneous rank at bar t, which the scaffold then
shifts by one bar before it can be traded.
"""
import numpy as np
import pandas as pd
from freqtrade.exchange import timeframe_to_minutes
from freqtrade.strategy import IntParameter, DecimalParameter, stoploss_from_open

from cross_sectional_base import CrossSectionalBase


class XSTrendEnsemble(CrossSectionalBase):
    # ---- fixed structural choices (see design.md) ----
    timeframe = "4h"
    can_short = True
    process_only_new_candles = True
    startup_candle_count = 650      # covers ma_slow (90d = 540 bars) + smoothing
    stoploss = -0.99                # static fallback; the real stop is custom_stoploss
    minimal_roi = {"0": 100}        # no ROI exit; exits are signal-driven
    use_exit_signal = True
    use_custom_stoploss = True

    # ---- reproducibility ----
    SEED = 20240701

    # ---- book width: forced symmetric so the book is dollar-neutral ----
    # the scaffold's own n_long/n_short are pinned and taken OUT of the search
    # space; `n_side` drives both (see _thresholds).
    n_long = IntParameter(1, 10, default=7, space="buy", optimize=False)
    n_short = IntParameter(1, 10, default=7, space="buy", optimize=False)
    n_side = IntParameter(6, 10, default=7, space="buy", optimize=True)

    # ---- turnover control ----
    smooth_days = IntParameter(4, 14, default=10, space="buy", optimize=True)
    exit_buffer = DecimalParameter(0.0, 0.20, default=0.1, decimals=2,
                                   space="buy", optimize=True)
    # min_hold is kept OUT of the search: signal smoothing plus the hysteresis band
    # already control same-day churn, and every extra search dimension is paid for
    # in the Deflated Sharpe Ratio.
    min_hold = IntParameter(0, 30, default=0, space="buy", optimize=False)

    # ---- risk control ----
    # Freqtrade never re-balances an open position, so without these two a
    # winner compounds into an oversized, one-sided bet and a losing short at
    # 1x isolated margin can run all the way to liquidation (-100%).
    # max_hold recycles every position back to target weight; stop_pct caps the
    # single-name tail.
    max_hold_days = IntParameter(15, 60, default=36, space="buy", optimize=True)
    stop_pct = DecimalParameter(0.25, 0.60, default=0.59, decimals=2,
                                space="buy", optimize=True)

    # ---- factor horizons (days) ----
    mom_days = IntParameter(10, 30, default=14, space="buy", optimize=True)
    ma_fast_days = IntParameter(20, 45, default=25, space="buy", optimize=True)
    ma_slow_days = IntParameter(45, 90, default=45, space="buy", optimize=True)

    # composite cache (keyed by the hyperopt parameter signature)
    _comp_cache = None
    _comp_sig = None

    # ------------------------------------------------------------------
    def _bars_per_day(self) -> int:
        return max(int(round(1440 / timeframe_to_minutes(self.timeframe))), 1)

    def _legs_for_pair(self, d: pd.DataFrame, bpd: int) -> dict:
        """The four causal trend legs for one pair. Trailing windows only."""
        idx = pd.DatetimeIndex(d["date"])
        close = pd.Series(d["close"].to_numpy(dtype="float64"), index=idx)
        high = pd.Series(d["high"].to_numpy(dtype="float64"), index=idx)
        low = pd.Series(d["low"].to_numpy(dtype="float64"), index=idx)
        lr = np.log(close).diff()

        n_mom = int(self.mom_days.value) * bpd
        n_f = int(self.ma_fast_days.value) * bpd
        n_s = int(self.ma_slow_days.value) * bpd
        n_p = n_f                                   # range window tied to the fast trend window

        def trend(n):
            vol = lr.rolling(n).std().replace(0.0, np.nan)
            return (close / close.rolling(n).mean() - 1.0) / vol

        hh = high.rolling(n_p).max()
        ll = low.rolling(n_p).min()
        return {
            "mom": close.pct_change(n_mom),
            "ma_fast": trend(n_f),
            "ma_slow": trend(n_s),
            "pos": (close - ll) / (hh - ll).replace(0.0, np.nan) - 0.5,
        }

    def _composite(self) -> dict:
        """Build the cross-sectionally rank-averaged, time-smoothed composite.

        Computed once per parameter set (hyperopt-safe cache key), then served to
        every factor_score() call. Contemporaneous cross-section only — the
        scaffold applies the shift(1) that makes it tradeable.
        """
        sig = self._param_signature()
        if self._comp_cache is not None and self._comp_sig == sig:
            return self._comp_cache

        bpd = self._bars_per_day()
        legs = {}
        for p in self.dp.current_whitelist():
            d = self.dp.get_pair_dataframe(p, self.timeframe)
            if d is None or len(d) == 0:
                continue
            for name, s in self._legs_for_pair(d, bpd).items():
                legs.setdefault(name, {})[p] = s

        comp = None
        for name, cols in legs.items():
            panel = pd.DataFrame(cols).sort_index()
            # cross-sectional percentile at bar t, centred to [-1, 1]
            rk = (panel.rank(axis=1, pct=True) - 0.5) * 2.0
            comp = rk if comp is None else comp.add(rk, fill_value=np.nan)
        if comp is None:
            out = {}
        else:
            comp = comp / float(len(legs))
            # rolling mean = turnover control (full window, no partial periods)
            comp = comp.rolling(int(self.smooth_days.value) * bpd).mean()
            out = {p: comp[p] for p in comp.columns}

        type(self)._comp_cache = out
        type(self)._comp_sig = sig
        return out

    # ------------------------------------------------------------------
    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        """Bullish score for `pair`: the smoothed cross-sectional composite.

        Returned aligned to df's own index; the scaffold re-aligns and shift(1)s it.
        """
        comp = self._composite()
        s = comp.get(pair)
        if s is None:
            return pd.Series(np.nan, index=df.index)
        return pd.Series(s.reindex(pd.DatetimeIndex(df["date"])).to_numpy(), index=df.index)

    # ------------------------------------------------------------------
    def _thresholds(self):
        """Symmetric book: `n_side` long and `n_side` short => dollar-neutral."""
        n = max(len(self.dp.current_whitelist()), 1)
        k = int(self.n_side.value)
        return 1.0 - (k / n), (k / n)

    # ---------------- risk / recycling ----------------
    def custom_stoploss(self, pair: str, trade, current_time, current_rate: float,
                        current_profit: float, after_fill: bool, **kwargs) -> float:
        """Hard cap on the loss of any single name, measured from the entry price."""
        return stoploss_from_open(-float(self.stop_pct.value), current_profit,
                                  is_short=trade.is_short, leverage=trade.leverage)

    def custom_exit(self, pair: str, trade, current_time, current_rate: float,
                    current_profit: float, **kwargs):
        """Recycle the position after `max_hold_days`.

        This is the substitute for the periodic re-weighting a real
        cross-sectional book does: it stops a runaway winner from turning the
        equal-weight, dollar-neutral book into a concentrated directional bet,
        and it staggers realised P&L across days instead of releasing it in
        rare, huge lumps. If the name is still ranked, the position is simply
        re-opened on the next candle at the correct size.
        """
        held_min = (current_time - trade.open_date_utc).total_seconds() / 60.0
        if held_min >= int(self.max_hold_days.value) * 1440:
            return "max_hold"
        return None

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs) -> bool:
        """min_hold must never block a risk exit."""
        if exit_reason and ("stop" in exit_reason or "max_hold" in exit_reason
                            or "liquidation" in exit_reason):
            return True
        return super().confirm_trade_exit(pair, trade, order_type, amount, rate,
                                          time_in_force, exit_reason, current_time, **kwargs)

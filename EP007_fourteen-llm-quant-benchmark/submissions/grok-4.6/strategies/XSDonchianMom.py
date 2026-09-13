# -*- coding: utf-8 -*-
"""
Cross-sectional Donchian breakout + skip-1 medium momentum.

Causal by construction:
  - each pair's factor uses only that pair's OHLCV through bar t
  - cross-sectional z-scores / ranks use only the 20 values at t
  - Freqtrade fills on the next bar's open (no extra panel shift)
"""
import numpy as np
import pandas as pd
from freqtrade.exchange import timeframe_to_minutes
from freqtrade.strategy import DecimalParameter, IntParameter, IStrategy


class XSDonchianMom(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    can_short = True
    process_only_new_candles = True
    startup_candle_count = 80
    stoploss = -0.99
    minimal_roi = {"0": 100}
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True

    # Width and turnover — the only knobs we search.
    n_long = IntParameter(3, 8, default=7, space="buy", optimize=True)
    n_short = IntParameter(3, 8, default=5, space="buy", optimize=True)
    exit_buffer = DecimalParameter(0.00, 0.20, default=0.01, decimals=2,
                                   space="buy", optimize=True)
    min_hold = IntParameter(1, 10, default=10, space="buy", optimize=True)
    # 1.0 = pure Donchian-21; lower blends in 14d skip-1 momentum after xs-z.
    don_weight = DecimalParameter(0.50, 1.00, default=0.57, decimals=2,
                                  space="buy", optimize=True)

    DON_WINDOW = 21
    MOM_WINDOW = 14
    MOM_SKIP = 1

    _panel_cache = None
    _panel_sig = None

    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, side, **kwargs):
        return 1.0

    def _param_signature(self):
        from freqtrade.strategy.parameters import BaseParameter
        sig = []
        for name in dir(type(self)):
            try:
                attr = getattr(type(self), name)
            except Exception:
                continue
            if isinstance(attr, BaseParameter):
                try:
                    sig.append((name, getattr(self, name).value))
                except Exception:
                    pass
        return tuple(sorted(sig, key=lambda x: x[0]))

    def _pair_factor(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype("float64")
        high = df["high"].astype("float64")
        low = df["low"].astype("float64")
        w = self.DON_WINDOW
        hh = high.rolling(w, min_periods=max(8, w // 2)).max()
        ll = low.rolling(w, min_periods=max(8, w // 2)).min()
        span = (hh - ll).replace(0.0, np.nan)
        don = (close - ll) / span

        sk = self.MOM_SKIP
        mw = self.MOM_WINDOW
        mom = close.shift(sk) / close.shift(sk + mw) - 1.0
        idx = pd.DatetimeIndex(df["date"])
        return pd.DataFrame(
            {
                "don": np.asarray(don, dtype="float64"),
                "mom": np.asarray(mom, dtype="float64"),
            },
            index=idx,
        )

    def _build_panel(self):
        pairs = list(self.dp.current_whitelist())
        dons = {}
        moms = {}
        for p in pairs:
            d = self.dp.get_pair_dataframe(p, self.timeframe)
            if d is None or len(d) == 0:
                continue
            fac = self._pair_factor(d)
            dons[p] = fac["don"]
            moms[p] = fac["mom"]
        if not dons:
            return {}
        don = pd.DataFrame(dons).sort_index()
        mom = pd.DataFrame(moms).sort_index().reindex(don.index)

        def xs_z(panel: pd.DataFrame) -> pd.DataFrame:
            mu = panel.mean(axis=1)
            sd = panel.std(axis=1).replace(0.0, np.nan)
            return panel.sub(mu, axis=0).div(sd, axis=0)

        w = float(self.don_weight.value)
        score = w * xs_z(don) + (1.0 - w) * xs_z(mom)
        ranks = score.rank(axis=1, pct=True)
        return {p: (score[p], ranks[p]) for p in score.columns}

    def _attach(self, dataframe, metadata):
        sig = self._param_signature()
        if type(self)._panel_cache is None or type(self)._panel_sig != sig:
            type(self)._panel_cache = self._build_panel()
            type(self)._panel_sig = sig
        pair_data = type(self)._panel_cache.get(metadata["pair"])
        dataframe = dataframe.copy()
        if pair_data is None:
            dataframe["xs_score"] = np.nan
            dataframe["xs_rank"] = np.nan
        else:
            score_s, rank_s = pair_data
            dataframe["xs_score"] = dataframe["date"].map(score_s)
            dataframe["xs_rank"] = dataframe["date"].map(rank_s)
        return dataframe

    def _thresholds(self):
        n = max(len(self.dp.current_whitelist()), 1)
        long_thr = 1.0 - (self.n_long.value / n)
        short_thr = self.n_short.value / n
        return long_thr, short_thr

    def populate_indicators(self, dataframe, metadata):
        # Factor lives in entry/exit so --spaces buy actually re-evaluates it.
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe = self._attach(dataframe, metadata)
        long_thr, short_thr = self._thresholds()
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        rank = dataframe["xs_rank"]
        dataframe.loc[rank >= long_thr, "enter_long"] = 1
        dataframe.loc[rank <= short_thr, "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        if "xs_rank" not in dataframe.columns:
            dataframe = self._attach(dataframe, metadata)
        long_thr, short_thr = self._thresholds()
        b = float(self.exit_buffer.value)
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        rank = dataframe["xs_rank"]
        dataframe.loc[rank < (long_thr - b), "exit_long"] = 1
        dataframe.loc[rank > (short_thr + b), "exit_short"] = 1
        return dataframe

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate,
                           time_in_force, exit_reason, current_time, **kwargs) -> bool:
        n = int(self.min_hold.value)
        if n <= 0:
            return True
        held_min = (current_time - trade.open_date_utc).total_seconds() / 60.0
        return held_min >= n * timeframe_to_minutes(self.timeframe)

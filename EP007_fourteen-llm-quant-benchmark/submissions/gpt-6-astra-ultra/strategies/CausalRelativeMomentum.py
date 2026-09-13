"""Lagged cross-sectional relative momentum with symmetric breadth and rank hysteresis."""
import numpy as np
import pandas as pd
from freqtrade.strategy import CategoricalParameter, IntParameter, DecimalParameter
from cross_sectional_base import CrossSectionalBase


class CausalRelativeMomentum(CrossSectionalBase):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = True
    startup_candle_count = 90
    stoploss = -0.20
    minimal_roi = {}
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    position_adjustment_enable = False

    # Symmetric breadth is a single decision; disable inherited search knobs.
    n_long = IntParameter(1, 10, default=5, space="buy", optimize=False)
    n_short = IntParameter(1, 10, default=5, space="buy", optimize=False)
    exit_buffer = DecimalParameter(0.0, 0.4, default=0.20, decimals=2, space="buy", optimize=False)
    min_hold = IntParameter(0, 48, default=6, space="buy", optimize=False)
    momentum_bars = CategoricalParameter([6, 12, 24, 42], default=24, space="buy")
    side_width = CategoricalParameter([3, 5, 7], default=5, space="buy")
    rank_buffer = CategoricalParameter([0.10, 0.20, 0.30], default=0.20, space="buy")

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        chosen = config.get("strategy_parameters", {}).get(type(self).__name__, {})
        if chosen:
            self.buy_params = dict(chosen)

    def factor_score(self, df: pd.DataFrame, pair: str) -> pd.Series:
        n = int(self.momentum_bars.value)
        log_price = np.log(df["close"].where(df["close"] > 0))
        vol = log_price.diff().rolling(84, min_periods=84).std()
        score = (log_price - log_price.shift(n)) / (vol.where(vol > 0) * np.sqrt(n))
        # Scaffold applies the mandatory shift(1) to scores and row-wise ranks.
        return score.where(df["volume"] > 0)

    def _param_signature(self):
        # Include data coverage to invalidate the inherited panel cache when
        # candles arrive, or when a causality audit truncates the input prefix.
        # The scaffold's panel construction and mandatory shift stay untouched.
        windows = []
        for pair in self.dp.current_whitelist():
            frame = self.dp.get_pair_dataframe(pair, self.timeframe)
            windows.append((pair, len(frame),
                            str(frame["date"].iloc[0]) if len(frame) else "",
                            str(frame["date"].iloc[-1]) if len(frame) else ""))
        return super()._param_signature() + (("data_windows", tuple(windows)),)

    def _thresholds(self):
        size = max(len(self.dp.current_whitelist()), 1)
        width = int(self.side_width.value) / size
        return 1.0 - width, width

    def populate_entry_trend(self, dataframe, metadata):
        dataframe = self._attach_rank(dataframe, metadata)
        long_threshold, short_threshold = self._thresholds()
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""
        # Strict > selects exactly k top ranks on a complete, untied universe.
        dataframe.loc[dataframe["xs_rank"] > long_threshold, ["enter_long", "enter_tag"]] = (1, "momentum_long")
        dataframe.loc[dataframe["xs_rank"] <= short_threshold, ["enter_short", "enter_tag"]] = (1, "momentum_short")
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        if "xs_rank" not in dataframe.columns:
            dataframe = self._attach_rank(dataframe, metadata)
        long_threshold, short_threshold = self._thresholds()
        buffer = float(self.rank_buffer.value)
        dataframe["exit_long"] = (dataframe["xs_rank"] < long_threshold - buffer).astype(int)
        dataframe["exit_short"] = (dataframe["xs_rank"] > short_threshold + buffer).astype(int)
        return dataframe

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs) -> bool:
        # The one-day minimum applies only to rank exits, never to safety exits.
        if exit_reason != "exit_signal":
            return True
        return (current_time - trade.open_date_utc).total_seconds() >= 6 * 4 * 3600


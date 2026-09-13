"""Symmetric, lagged channel breakouts for the fixed perpetual-futures basket.

Only this strategy is authored here; the supplied scaffold is not imported or changed.
Parameter-dependent columns are all precomputed so ordinary buy-space Hyperopt
can select a different window on every epoch without recalculating indicators.
"""

from pandas import DataFrame
import numpy as np
from freqtrade.strategy import IStrategy, CategoricalParameter


class CausalDonchian(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = True
    process_only_new_candles = True
    startup_candle_count = 340
    minimal_roi = {}
    stoploss = -0.20
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    position_adjustment_enable = False

    entry_days = CategoricalParameter([7, 14, 21, 28], default=14, space="buy")
    exit_days = CategoricalParameter([2, 4, 7, 10], default=4, space="buy")
    trend_days = CategoricalParameter([0, 28, 56], default=56, space="buy")
    atr_buffer = CategoricalParameter([0.0, 0.5, 1.0], default=0.0, space="buy")

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        # The final parameter choice lives in the required config.json. The
        # standard Freqtrade parameter lifecycle loads these as buy_params.
        chosen = config.get("strategy_parameters", {}).get(type(self).__name__, {})
        if chosen:
            self.buy_params = dict(chosen)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        previous_close = dataframe["close"].shift(1)
        true_range = np.maximum(
            dataframe["high"] - dataframe["low"],
            np.maximum(
                (dataframe["high"] - previous_close).abs(),
                (dataframe["low"] - previous_close).abs(),
            ),
        )
        dataframe["known_close"] = previous_close
        dataframe["known_volume"] = dataframe["volume"].shift(1)
        dataframe["known_atr"] = true_range.rolling(42, min_periods=42).mean().shift(1)
        dataframe["known_atr_pct"] = dataframe["known_atr"] / previous_close
        for days in (7, 14, 21, 28):
            window = days * 6
            # At signal row t, compare the t-1 close with extrema ending t-2.
            dataframe[f"entry_high_{days}"] = dataframe["high"].rolling(window).max().shift(2)
            dataframe[f"entry_low_{days}"] = dataframe["low"].rolling(window).min().shift(2)
        for days in (2, 4, 7, 10):
            window = days * 6
            dataframe[f"exit_high_{days}"] = dataframe["high"].rolling(window).max().shift(2)
            dataframe[f"exit_low_{days}"] = dataframe["low"].rolling(window).min().shift(2)
        for days in (28, 56):
            # Finite rolling means avoid hidden initialization dependence.
            dataframe[f"trend_{days}"] = dataframe["close"].rolling(days * 6).mean().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""
        days = self.entry_days.value
        close = dataframe["known_close"]
        buffer = float(self.atr_buffer.value) * dataframe["known_atr"]
        eligible = (
            (dataframe["known_volume"] > 0)
            & dataframe["trend_56"].notna()
            & (dataframe["known_atr_pct"] > 0)
            & (dataframe["known_atr_pct"] < 0.06)
        )
        long_signal = eligible & (close > dataframe[f"entry_high_{days}"] + buffer)
        short_signal = eligible & (close < dataframe[f"entry_low_{days}"] - buffer)
        trend_days = self.trend_days.value
        if trend_days:
            long_signal &= close > dataframe[f"trend_{trend_days}"]
            short_signal &= close < dataframe[f"trend_{trend_days}"]
        dataframe.loc[long_signal, ["enter_long", "enter_tag"]] = (1, "channel_long")
        dataframe.loc[short_signal, ["enter_short", "enter_tag"]] = (1, "channel_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        days = self.exit_days.value
        close = dataframe["known_close"]
        dataframe.loc[close < dataframe[f"exit_low_{days}"], "exit_long"] = 1
        dataframe.loc[close > dataframe[f"exit_high_{days}"], "exit_short"] = 1
        return dataframe

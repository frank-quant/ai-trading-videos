# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
from pandas import DataFrame

from freqtrade.strategy import IStrategy, IntParameter

import talib.abstract as ta
from technical import qtpylib


class MyMeanReversion(IStrategy):
    """
    Mean-reversion strategy based on Bollinger Bands + RSI filter,
    gated by a long-term trend filter.

    Entry: price closes below the lower Bollinger Band (oversold deviation)
           AND RSI is below 30 (confirms oversold condition)
           AND price is above the EMA200 (only buy dips within an uptrend).
    Exit:  price closes back above the middle Bollinger Band (reversion to mean).
    """

    INTERFACE_VERSION = 3

    can_short: bool = False

    # ROI table effectively disabled - exits are driven by the BB mean-reversion signal
    minimal_roi = {"0": 10}

    # Fixed 2% stoploss
    stoploss = -0.02

    trailing_stop = False

    timeframe = "5m"

    process_only_new_candles = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # RSI oversold threshold used as entry filter
    rsi_entry = IntParameter(low=10, high=40, default=30, space="buy", optimize=True, load=True)

    # Long-term trend filter period (only long above this EMA)
    trend_ema_period = 200

    # EMA200 needs ~200 candles of warm-up
    startup_candle_count: int = 200

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    plot_config = {
        "main_plot": {
            "bb_lowerband": {"color": "red"},
            "bb_middleband": {"color": "blue"},
            "bb_upperband": {"color": "red"},
            "trend_ema": {"color": "green"},
        },
        "subplots": {
            "RSI": {
                "rsi": {"color": "orange"},
            },
        },
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Bollinger Bands (20-period, 2 std)
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lowerband"] = bollinger["lower"]
        dataframe["bb_middleband"] = bollinger["mid"]
        dataframe["bb_upperband"] = bollinger["upper"]

        # RSI
        dataframe["rsi"] = ta.RSI(dataframe)

        # Long-term trend filter
        dataframe["trend_ema"] = ta.EMA(dataframe, timeperiod=self.trend_ema_period)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Signal: price deviated below the lower BB (oversold)
                (dataframe["close"] < dataframe["bb_lowerband"])
                # Filter: RSI confirms oversold
                & (dataframe["rsi"] < self.rsi_entry.value)
                # Trend filter: only buy dips while price is above the long-term EMA
                & (dataframe["close"] > dataframe["trend_ema"])
                & (dataframe["volume"] > 0)  # Make sure Volume is not 0
            ),
            "enter_long",
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Signal: price reverted back to (or above) the middle BB
                (dataframe["close"] > dataframe["bb_middleband"])
                & (dataframe["volume"] > 0)  # Make sure Volume is not 0
            ),
            "exit_long",
        ] = 1

        return dataframe

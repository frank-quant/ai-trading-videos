# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
import numpy as np
from pandas import DataFrame

from freqtrade.strategy import IStrategy, CategoricalParameter, DecimalParameter, IntParameter

import talib.abstract as ta
from technical import qtpylib


class KimiK3Strategy(IStrategy):
    """
    Bidirectional (long/short) trend-following strategy for ETH/USDT:USDT 30m futures.

    Direction filter (trend):
      - Uptrend:   EMA20 > EMA50  AND  EMA50 rising (slope over last 8 bars > 0)
      - Downtrend: EMA20 < EMA50  AND  EMA50 falling
      - ADX must exceed a threshold so trades are only taken when a real
        trend exists.

    Chop filter (market regime - the key addition):
      The strategy stays FLAT in directionless markets. A bar is tradeable only if
        - Choppiness Index (14) is below buy_chop_max (high CI = sideways chop), AND
        - |EMA20 - EMA50| / ATR(14) exceeds buy_ema_gap (EMAs intertwined = no trend)
      Optionally (buy_mom_filter) entries also require MACD histogram to agree
      with the trade direction (trend/momentum divergence = likely reversal fake-out).

    Entries (pullback-recovery):
      - Long:  in an uptrend, close crosses back up through EMA20 while RSI
               holds above a floor (buy the dip, skip collapsing momentum).
      - Short: in a downtrend, close crosses back down through EMA20 while RSI
               stays below a ceiling (sell the bounce, skip exploding momentum).

    Exits:
      - Long:  RSI reaches an overbought threshold (momentum exhaustion),
               or the trend flips bearish.
      - Short: RSI reaches an oversold threshold (momentum exhaustion),
               or the trend flips bullish.
      - ROI / stoploss are optimized by hyperopt alongside the signal params.
    """

    INTERFACE_VERSION = 3

    can_short: bool = True

    # ROI / stoploss are defaults; hyperopt (spaces: roi, stoploss) tunes them.
    minimal_roi = {"0": 0.04, "120": 0.02, "240": 0.01}
    stoploss = -0.05
    trailing_stop = False

    timeframe = "30m"

    process_only_new_candles = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # EMA50 warmup + slope lookback
    startup_candle_count: int = 100

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    # --- Hyperopt parameters (entry side, space='buy') ---
    # Long entries require RSI above this level (skip collapsing momentum).
    buy_rsi = IntParameter(30, 50, default=40, space="buy", optimize=True, load=True)
    # Minimum ADX for long entries.
    buy_adx = IntParameter(15, 35, default=20, space="buy", optimize=True, load=True)
    # Short entries require RSI below this level (skip exploding momentum).
    sell_rsi = IntParameter(50, 70, default=60, space="buy", optimize=True, load=True)
    # Minimum ADX for short entries.
    sell_adx = IntParameter(15, 35, default=20, space="buy", optimize=True, load=True)
    # Chop filter: no entries while Choppiness Index is above this level.
    buy_chop_max = IntParameter(45, 65, default=55, space="buy", optimize=True, load=True)
    # Chop filter: no entries while |EMA20-EMA50| is smaller than this many ATRs.
    buy_ema_gap = DecimalParameter(0.0, 1.5, default=0.3, decimals=1, space="buy", optimize=True, load=True)
    # Momentum confirmation: require MACD histogram to agree with trade direction.
    buy_mom_filter = CategoricalParameter(["on", "off"], default="on", space="buy", optimize=True, load=True)

    # --- Hyperopt parameters (exit side, space='sell') ---
    # RSI overbought level that closes a long.
    exit_long_rsi = IntParameter(55, 80, default=70, space="sell", optimize=True, load=True)
    # RSI oversold level that closes a short.
    exit_short_rsi = IntParameter(20, 45, default=30, space="sell", optimize=True, load=True)

    def leverage(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        side: str,
        **kwargs,
    ) -> float:
        # Fixed 1x leverage - shorting capability comes from the futures contract,
        # not from amplified leverage.
        return 1.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Indicator periods are fixed constants here on purpose:
        # hyperopt does not recalculate indicators per epoch, so optimizable
        # parameters are only used in populate_entry_trend / populate_exit_trend.
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        # EMA50 slope over the last 8 bars (4 hours) - trend direction filter.
        dataframe["ema_slow_slope"] = dataframe["ema_slow"] - dataframe["ema_slow"].shift(8)

        # EMA distance in ATR units - intertwined EMAs mean no trend.
        dataframe["ema_gap_atr"] = (dataframe["ema_fast"] - dataframe["ema_slow"]).abs() / dataframe["atr"]

        # Choppiness Index (14): high values = sideways chop, low values = trending.
        tr = ta.TRANGE(dataframe)
        n = 14
        atr_sum = tr.rolling(n).sum()
        high_low = dataframe["high"].rolling(n).max() - dataframe["low"].rolling(n).min()
        dataframe["chop"] = 100 * np.log10(atr_sum / high_low) / np.log10(n)

        # MACD histogram - momentum confirmation.
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd_hist"] = macd["macdhist"]

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        uptrend = (
            (dataframe["ema_fast"] > dataframe["ema_slow"])
            & (dataframe["ema_slow_slope"] > 0)
        )
        downtrend = (
            (dataframe["ema_fast"] < dataframe["ema_slow"])
            & (dataframe["ema_slow_slope"] < 0)
        )

        # Chop filter: stay flat in directionless / intertwined-EMA markets.
        regime_ok = (
            (dataframe["chop"] < self.buy_chop_max.value)
            & (dataframe["ema_gap_atr"] > self.buy_ema_gap.value)
        )

        # Momentum confirmation (can be disabled by hyperopt).
        if self.buy_mom_filter.value == "on":
            mom_long = dataframe["macd_hist"] > 0
            mom_short = dataframe["macd_hist"] < 0
        else:
            mom_long = True
            mom_short = True

        # Long: uptrend + price recovering to the fast EMA after a pullback.
        # RSI must sit above buy_rsi so we skip entries with collapsing momentum.
        dataframe.loc[
            uptrend
            & regime_ok
            & mom_long
            & (dataframe["adx"] > self.buy_adx.value)
            & (dataframe["rsi"] > self.buy_rsi.value)
            & (qtpylib.crossed_above(dataframe["close"], dataframe["ema_fast"])),
            "enter_long",
        ] = 1

        # Short: downtrend + price falling back from the fast EMA after a bounce.
        # RSI must sit below sell_rsi so we skip entries with exploding momentum.
        dataframe.loc[
            downtrend
            & regime_ok
            & mom_short
            & (dataframe["adx"] > self.sell_adx.value)
            & (dataframe["rsi"] < self.sell_rsi.value)
            & (qtpylib.crossed_below(dataframe["close"], dataframe["ema_fast"])),
            "enter_short",
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        trend_flip_bearish = dataframe["ema_fast"] < dataframe["ema_slow"]
        trend_flip_bullish = dataframe["ema_fast"] > dataframe["ema_slow"]

        # Exit long: momentum exhaustion (overbought RSI) or trend flip.
        dataframe.loc[
            (qtpylib.crossed_above(dataframe["rsi"], self.exit_long_rsi.value))
            | trend_flip_bearish,
            "exit_long",
        ] = 1

        # Exit short: momentum exhaustion (oversold RSI) or trend flip.
        dataframe.loc[
            (qtpylib.crossed_below(dataframe["rsi"], self.exit_short_rsi.value))
            | trend_flip_bullish,
            "exit_short",
        ] = 1

        return dataframe

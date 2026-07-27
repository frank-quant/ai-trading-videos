# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
import numpy as np
from pandas import DataFrame

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from freqtrade.optimize.space import SKDecimal

import talib.abstract as ta
from technical import qtpylib


class KimiK3StrategyV2(IStrategy):
    """
    Bidirectional (long/short) trend-following strategy for ETH/USDT:USDT 30m futures.

    Trend filter (core):
      - Uptrend:   EMA20 > EMA50  AND  EMA50 rising (slope over the last 8 bars > 0)
      - Downtrend: EMA20 < EMA50  AND  EMA50 falling
      - ADX must exceed a (optimizable) threshold so positions are only opened
        when a real trend exists.

    Chop filter (regime - stay flat in directionless markets):
      A bar is tradeable only if
        - Choppiness Index (14) is below an optimizable ceiling (high CI = chop), AND
        - |EMA20 - EMA50| / ATR(14) exceeds an optimizable floor
          (intertwined EMAs = no trend)
      Principle: rather miss an opportunity than get slapped from both sides
      in a ranging market.

    Entries (pullback-recovery, direction follows the trend):
      - Long:  in an uptrend, close crosses back up through EMA20 while RSI
               holds above an optimizable floor (buy the dip, skip collapses).
      - Short: in a downtrend, close crosses back down through EMA20 while RSI
               stays below an optimizable ceiling (sell the bounce, skip spikes).

    Exits:
      - Long:  RSI crosses above an optimizable overbought level (momentum
               exhaustion), or the EMA20/EMA50 trend flips bearish.
      - Short: RSI crosses below an optimizable oversold level, or the trend
               flips bullish.
      - ROI ladder (hyperopt 'roi' space) takes profit, wide stoploss
        (searched only inside [-0.30, -0.10]) is the last resort.
      - No trailing stop.
    """

    INTERFACE_VERSION = 3

    can_short: bool = True

    # ROI / stoploss are defaults only; hyperopt (spaces: roi, stoploss) tunes them.
    minimal_roi = {"0": 0.08, "360": 0.04, "1080": 0.02}
    stoploss = -0.18
    trailing_stop = False

    timeframe = "30m"

    process_only_new_candles = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # EMA50 warmup + slope lookback + chop window margin
    startup_candle_count: int = 120

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    # --- Hyperopt parameters (entry side, space='buy') ---
    # NOTE: optimizable parameters live here and are consumed ONLY in
    # populate_entry_trend / populate_exit_trend. Hyperopt does not
    # recalculate populate_indicators per epoch, so no optimizable
    # parameter may be used there.

    # Long entries require RSI above this floor (skip collapsing momentum).
    long_rsi_min = IntParameter(30, 50, default=40, space="buy", optimize=True, load=True)
    # Minimum ADX for long entries (trend strength confirmation).
    long_adx_min = IntParameter(15, 35, default=22, space="buy", optimize=True, load=True)
    # Short entries require RSI below this ceiling (skip exploding momentum).
    short_rsi_max = IntParameter(50, 70, default=60, space="buy", optimize=True, load=True)
    # Minimum ADX for short entries.
    short_adx_min = IntParameter(15, 35, default=22, space="buy", optimize=True, load=True)
    # Chop filter: no entries while Choppiness Index is above this level.
    chop_max = IntParameter(45, 65, default=55, space="buy", optimize=True, load=True)
    # Chop filter: no entries while |EMA20-EMA50| is smaller than this many ATRs.
    ema_gap_min = DecimalParameter(0.0, 1.5, default=0.3, decimals=1, space="buy", optimize=True, load=True)

    # --- Hyperopt parameters (exit side, space='sell') ---
    # RSI overbought level that closes a long.
    exit_long_rsi = IntParameter(60, 85, default=72, space="sell", optimize=True, load=True)
    # RSI oversold level that closes a short.
    exit_short_rsi = IntParameter(15, 40, default=28, space="sell", optimize=True, load=True)

    class HyperOpt:
        # Nested per-strategy hyperopt space overrides (do NOT inherit IHyperOpt).
        # Stoploss is deliberately searched ONLY in the wide band [-0.30, -0.10]:
        # 30m ETH intraday noise would repeatedly sweep a tight stop.
        @staticmethod
        def stoploss_space():
            return [SKDecimal(-0.30, -0.10, decimals=3, name="stoploss")]

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
        # Fixed 1x leverage - shorting capability comes from the futures
        # contract itself, not from amplified leverage.
        return 1.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Indicator periods are fixed constants here on purpose (see note at
        # the parameter declarations): no optimizable parameter is read here.
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
            (dataframe["chop"] < self.chop_max.value)
            & (dataframe["ema_gap_atr"] > self.ema_gap_min.value)
        )

        # Long: uptrend + price recovering to the fast EMA after a pullback.
        # RSI must sit above long_rsi_min so we skip entries with collapsing momentum.
        dataframe.loc[
            uptrend
            & regime_ok
            & (dataframe["adx"] > self.long_adx_min.value)
            & (dataframe["rsi"] > self.long_rsi_min.value)
            & (qtpylib.crossed_above(dataframe["close"], dataframe["ema_fast"])),
            "enter_long",
        ] = 1

        # Short: downtrend + price falling back from the fast EMA after a bounce.
        # RSI must sit below short_rsi_max so we skip entries with exploding momentum.
        dataframe.loc[
            downtrend
            & regime_ok
            & (dataframe["adx"] > self.short_adx_min.value)
            & (dataframe["rsi"] < self.short_rsi_max.value)
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

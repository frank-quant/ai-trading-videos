# -*- coding: utf-8 -*-
"""
CryptoAlphaTrend Strategy (EP004 / EP007)
========================================
Systematic Multi-Factor Trend Following Strategy for Crypto Perpetual Futures.
Combines Donchian Channel Breakout with Trend EMA confirmation,
EMA slope momentum filter, and Contrarian Funding Rate (carry) positioning.

- Timeframe: 4h
- Two-sided: Both Long and Short positions actively traded
- Leverage: Fixed at 1.0 (strict rule)
- Causality: Strictly causal with no look-ahead (all reference levels shifted)
"""
import os
import numpy as np
import pandas as pd
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter


class CryptoAlphaTrend(IStrategy):
    timeframe = "4h"
    can_short = True
    process_only_new_candles = True
    startup_candle_count = 150

    # Risk management
    stoploss = -0.15          # 15% catastrophic stoploss
    minimal_roi = {"0": 100}  # Channel trailing exits

    # Hyperoptable parameters in 'buy' space
    entry_window = IntParameter(16, 48, default=24, space="buy", optimize=True)
    exit_window = IntParameter(4, 16, default=8, space="buy", optimize=True)
    trend_ema = IntParameter(30, 100, default=60, space="buy", optimize=True)
    ema_slope_bars = IntParameter(1, 8, default=4, space="buy", optimize=True)
    max_fr_long = DecimalParameter(0.0001, 0.0008, default=0.0004, decimals=4, space="buy", optimize=True)
    min_fr_short = DecimalParameter(-0.0006, 0.0001, default=-0.0001, decimals=4, space="buy", optimize=True)

    _fr_cache = {}

    @classmethod
    def _load_funding_rate(cls, pair: str, dt_index: pd.DatetimeIndex) -> pd.Series:
        if pair not in cls._fr_cache:
            sym = pair.replace('/', '_').replace(':', '_')
            fpath = f"/freqtrade/user_data/data/binance/futures/{sym}-1h-funding_rate.feather"
            if not os.path.exists(fpath):
                fpath = f"D:\\freqtrade_demo\\EP004_env\\data_shared\\binance\\futures\\{sym}-1h-funding_rate.feather"
            if os.path.exists(fpath):
                fr_df = pd.read_feather(fpath)
                fr_df["date"] = pd.to_datetime(fr_df["date"], utc=True)
                cls._fr_cache[pair] = fr_df.set_index("date")["open"].sort_index()
            else:
                cls._fr_cache[pair] = pd.Series(0.0, index=dt_index)
        s = cls._fr_cache[pair]
        aligned = s.reindex(dt_index, method="ffill").fillna(0.0)
        return aligned

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # 1. Trend EMA and slope
        dataframe["trend_ema"] = dataframe["close"].ewm(span=self.trend_ema.value).mean()
        dataframe["ema_slope"] = dataframe["trend_ema"] - dataframe["trend_ema"].shift(self.ema_slope_bars.value)

        # 2. Donchian Breakout Channels (strictly causal: shift(1) to avoid look-ahead)
        dataframe["entry_high"] = dataframe["high"].shift(1).rolling(self.entry_window.value).max()
        dataframe["entry_low"] = dataframe["low"].shift(1).rolling(self.entry_window.value).min()

        dataframe["exit_high"] = dataframe["high"].shift(1).rolling(self.exit_window.value).max()
        dataframe["exit_low"] = dataframe["low"].shift(1).rolling(self.exit_window.value).min()

        # 3. Funding Rate (aligned and shifted by 1 candle for causality)
        dt_idx = pd.to_datetime(dataframe["date"], utc=True)
        raw_fr = self._load_funding_rate(metadata["pair"], dt_idx)
        dataframe["funding_rate"] = raw_fr.values
        # Rolling 72h (18 4h-candles) funding rate, shifted by 1
        dataframe["fr_rolling"] = dataframe["funding_rate"].rolling(18).mean().shift(1).fillna(0.0)

        # 4. Volatility (ATR)
        tr1 = dataframe["high"] - dataframe["low"]
        tr2 = (dataframe["high"] - dataframe["close"].shift(1)).abs()
        tr3 = (dataframe["low"] - dataframe["close"].shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        dataframe["atr"] = tr.rolling(14).mean()

        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0

        # Long Entry:
        # 1. Price breaks out above N-candle high
        # 2. Price above Trend EMA
        # 3. Funding rate is not exorbitantly crowded on long side
        long_cond = (
            (dataframe["close"] > dataframe["entry_high"]) &
            (dataframe["close"] > dataframe["trend_ema"]) &
            (dataframe["fr_rolling"] <= self.max_fr_long.value) &
            (dataframe["volume"] > 0)
        )

        # Short Entry:
        # 1. Price breaks down below N-candle low
        # 2. Price below Trend EMA
        # 3. EMA slope is downward (actively trending down, avoiding bull counter-trend traps)
        # 4. Funding rate is not deeply negative (avoiding crowded short squeeze traps)
        short_cond = (
            (dataframe["close"] < dataframe["entry_low"]) &
            (dataframe["close"] < dataframe["trend_ema"]) &
            (dataframe["ema_slope"] < 0) &
            (dataframe["fr_rolling"] >= self.min_fr_short.value) &
            (dataframe["volume"] > 0)
        )

        dataframe.loc[long_cond, "enter_long"] = 1
        dataframe.loc[short_cond, "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0

        # Exit Long: close falls below past exit_window low
        exit_long_cond = dataframe["close"] < dataframe["exit_low"]
        # Exit Short: close rises above past exit_window high
        exit_short_cond = dataframe["close"] > dataframe["exit_high"]

        dataframe.loc[exit_long_cond, "exit_long"] = 1
        dataframe.loc[exit_short_cond, "exit_short"] = 1
        return dataframe

    def leverage(self, pair: str, current_time, current_rate: float,
                 proposed_leverage: float, max_leverage: float, side: str,
                 **kwargs) -> float:
        return 1.0

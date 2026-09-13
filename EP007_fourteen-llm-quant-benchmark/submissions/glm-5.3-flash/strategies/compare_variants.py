# -*- coding: utf-8 -*-
"""Temporary comparison variants (deleted before delivery)."""
from freqtrade.strategy import IntParameter, BooleanParameter
from HybridXSMomentum import HybridXSMomentum


class HybridXS4h(HybridXSMomentum):
    """Same logic at 4h: windows scaled to bars (4h bar = 1/6 day)."""
    timeframe = "4h"
    startup_candle_count = 800
    mom_win = IntParameter(48, 720, default=120, space="buy", optimize=True)
    vol_win = IntParameter(12, 240, default=120, space="buy", optimize=True)
    trend_win = IntParameter(24, 720, default=300, space="buy", optimize=True)
    min_hold = IntParameter(0, 120, default=24, space="buy", optimize=True)


class PureXS1d(HybridXSMomentum):
    """1d, no absolute trend gate (pure cross-sectional)."""
    use_trend = BooleanParameter(default=False, optimize=False, space="buy")

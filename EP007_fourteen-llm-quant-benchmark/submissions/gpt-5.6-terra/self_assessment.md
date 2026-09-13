# Self assessment

The chief overfitting risk is selection on one 12-month validation regime. Although
the selected candidate has a favourable train/validation relationship and the search
was capped at 60 trials, its very strong validation result may still reflect the
2024--25 cross-sectional dispersion rather than a permanent momentum premium. The
89-candle horizon, 171-candle volatility window, 47-candle holding constraint, and
the asymmetric 5-long/3-short book are all parameters that could be regime-sensitive.

The main look-ahead risk is cross-sectional alignment: ranking a whole sample, or
using a contemporaneous close to trade that close, would be invalid. This strategy
does neither. Its factor is rolling and causal; `CrossSectionalBase._build_panel`
constructs ranks only across the contemporaneous fixed universe and shifts the full
panel by one candle before entry/exit logic sees it. There are no centered windows,
negative shifts, full-sample normalisers, dynamic universe filters, or external data.

Metrics use realised close-date PnL as prescribed by `EP004ValidLoss`. That makes
the segment boundary intentionally different from two separately restarted
backtests: trades opened before 2024-07-01 and closed after it are allocated to
VALIDATION. This is a faithful reproduction of the stated objective, but it is a
limitation to remember when interpreting the segment returns. The reported turnover
is gross entry notional divided by starting capital; actual fill quality and live
funding can be worse than this historical simulation.

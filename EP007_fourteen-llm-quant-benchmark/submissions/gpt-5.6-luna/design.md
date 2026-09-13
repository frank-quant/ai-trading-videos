# CausalMultiFactorXS design

## Strategy family and market

This is a cross-sectional, long/short multi-factor strategy on exactly the 20 USDT-
margined perpetuals in `config.json`. At each decision time it ranks every pair's
bullish score, buys the top six and shorts the bottom one. Thus both directions are
structurally enabled and were both used in the final run (1,259 long / 471 short trades
in TRAIN and 366 long / 144 short trades in VALIDATION). Leverage is left at the
scaffold's fixed 1.0x implementation.

## Timeframe and signals

The timeframe is 4h. It is slow enough to keep the approximately 0.12% round-trip cost
from overwhelming the signal, while retaining more observations than daily bars.

For each pair, using only its own OHLCV history, the score is:

1. Volatility-normalized momentum: a 45% weight on `mom_fast` log return plus a 55%
   weight on `mom_slow` log return, divided by trailing return volatility.
2. Trend persistence: `tanh(slow_return / trailing_volatility)`, weighted by the
   selected `trend_weight`.
3. Short-horizon reversal: the negative `reversal_window` log return divided by the
   same trailing volatility, weighted by `reversal_weight`.

The volatility floor prevents unstable rankings in exceptionally quiet periods. The
score is deliberately rank-based across the fixed universe, so absolute price scale and
pair-specific volatility do not decide the book.

The inherited `CrossSectionalBase` performs the cross-pair alignment and its mandatory
`shift(1)`: the order decision on candle *t* uses scores calculated through candle
*t-1*. There is no full-sample normalization, centered window, negative shift, or
future resampling.

## Turnover and exits

The final parameters are:

```text
exit_buffer       0.11
min_hold          39 candles (6.5 days)
mom_fast          9 candles
mom_slow          100 candles
n_long            6
n_short           1
reversal_weight   0.56
reversal_window   4 candles
trend_weight      0.70
volatility_window 47 candles
```

The exit hysteresis band prevents a position from being closed merely because a score
briefly crosses a selection boundary. The minimum hold further limits churn. The
strategy uses the scaffold's no-ROI, wide stoploss defaults; turnover control and
cross-sectional diversification are preferred to frequent tactical exits.

## Optimization and objective

I ran 120 epochs with `-j 20`, random state 42, the provided `EP004ValidLoss`, and the
full allowed 2021-01-01 through 2025-06-30 range. I stopped at 120 because the search
already produced a validation Sharpe of 2.0420 with training Sharpe 0.5339 and a clear
low-turnover solution; using the remaining budget would increase trial-count/deflated-
Sharpe exposure without evidence of a more robust candidate. The fixed objective was
used unchanged. The final selected parameters are also recorded in `config.json` and
the hyperopt parameter file generated under `strategies/`.

## Metric convention

For both segments, daily PnL is aggregated by UTC close date, divided by the original
10,000 USDT wallet, and missing dates are filled with zero. Sharpe is the resulting
mean/std multiplied by `sqrt(365)`, exactly as in `EP004ValidLoss`; fees and funding
adjustments are already in the Freqtrade trade PnL. `ann_return` is the geometric annual
rate of the segment's base-capital cumulative PnL, and the remaining metrics are
computed from the same daily series or the corresponding closed trades.

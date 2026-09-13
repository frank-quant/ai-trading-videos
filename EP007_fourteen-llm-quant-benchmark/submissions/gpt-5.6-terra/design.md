# BalancedXSTrend design

## Family and signal

This is a 4-hour cross-sectional relative-strength strategy for the fixed set of 20
USDT perpetuals. It buys the five highest and shorts the three lowest factor ranks.
Both long and short entries occur in both TRAIN (979/790) and VALIDATION (300/239).

The score is a 15/85 blend of log price changes over 18 and 89 four-hour candles,
each divided by trailing 171-candle realised log-return volatility. The medium horizon
captures persistent relative strength; the longer component is dominant to avoid
reacting to crypto microstructure noise. Volatility scaling prevents high-beta coins
from winning a rank merely because their unscaled returns are larger. The parent
scaffold aligns all 20 scores and applies `shift(1)`, so every rank used at a candle
was known at the prior candle close.

## Trading and risk controls

The 4-hour timeframe is deliberately slower than the available 30m/1h data: a
round-trip costs 12 bps under the fixed configuration. A position enters only in the
selected rank tail, exits only after crossing a 0.11-rank hysteresis band, and cannot
exit for 47 candles (188 hours). This is the primary turnover control. The strategy
uses the required 1x leverage and a -22% disaster stop; ROI exits are disabled. No
funding-rate signal was engineered; Freqtrade's futures accounting includes the
available funding fees in the backtest PnL.

## Search and selection

I used the provided `EP004ValidLoss`, `-j 20`, and random state `20260904`. Sixty
completed epochs searched factor horizons, blend, volatility window, long/short
breadth, hysteresis and minimum holding period. I stopped at 60 rather than expanding
to the 2,000-epoch ceiling because the first robust candidate already had validation
Sharpe 1.809 versus train Sharpe 0.826, and further search would add a substantial
deflated-Sharpe/multiple-testing penalty. The selected parameters are recorded in
`config.json` and as strategy defaults.

The reported Sharpe is exactly the objective's daily-PnL, fixed-starting-wallet,
zero-filled, `sqrt(365)` annualisation. I would retain that objective for this problem:
it handles overlapping concurrent trades more fairly than trade-level Sharpe, while
the included train/validation gap penalty discourages a train-only solution.

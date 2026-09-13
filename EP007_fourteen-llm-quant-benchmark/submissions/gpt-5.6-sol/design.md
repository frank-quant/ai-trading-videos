# CausalXSTrend design

## Family and portfolio

CausalXSTrend is a cross-sectional relative-trend strategy on the fixed 20-contract universe. At each decision it ranks every contract by a bullish composite, opens the top six long and bottom three short, and exits only after a position crosses a wider rank threshold. The asymmetric breadth is a hyperopt result rather than symbol selection: every contract is always eligible on both sides. Leverage is fixed at 1x.

This construction is less dependent on absolute crypto-market direction than independent per-pair trend signals. It nevertheless permits moderate net exposure because strict dollar neutrality was not the objective and unequal long/short breadth improved the prescribed validation-gap score.

## Signal

The score blends 41-candle (6.8-day) and 136-candle (22.7-day) log-price changes with weights 45% and 55%. Each horizon is divided by trailing 91-candle realized volatility scaled by the square root of its horizon. Volatility scaling keeps high-volatility altcoins from dominating the relative comparison while the two horizons reduce dependence on one arbitrary trend length.

A 46%-weighted 15-candle (2.5-day) normalized move is subtracted. This reversal penalty avoids chasing short-lived spikes while leaving the slower trend intact. The final value is ranked across the fixed universe.

All rolling values are backward-looking. The unmodified `CrossSectionalBase` panel applies `shift(1)` after cross-sectional alignment and ranking, so a bar-t decision uses only values known at the end of bar t-1. There is no full-sample normalization, centered window, negative shift, or future resampling.

## Timeframe, exits, and turnover

The 4h timeframe balances signal freshness against the fixed 6 bps-per-side cost. A position must be held for at least 46 candles (7.7 days), and a 0.11 percentile hysteresis band delays exits after an asset leaves its entry bucket. ROI exits are disabled and the catastrophic stop remains at the scaffold's non-binding -99%, because the initial smoke test showed a conventional -30% stop crystallized clustered relative dislocations and reduced validation return. Rank migration is the primary exit.

The final backtest remains cost-sensitive: annualized two-way notional turnover is 91.17x in TRAIN and 151.49x in VALIDATION. Reported profits and Sharpes are after Freqtrade's configured 0.06% per-side cost and include historical funding payments.

## Optimization

I ran 300 epochs with `EP004ValidLoss`, `-j 20`, and random seed 5607. The search covered factor horizons/weights, long and short breadth, exit hysteresis, and minimum hold; all parameters were in the buy space. Three hundred trials are enough for the compact ten-parameter domain and substantially below the 2,000-epoch allowance, limiting multiple-testing and Deflated-Sharpe penalties. The selected epoch was 116, with parameters recorded in `config.json` and as defaults in the strategy.

The mandated loss is appropriate for the exam because it explicitly penalizes train-to-validation degradation. In production I would prefer nested walk-forward folds, a turnover penalty, and tail-risk constraints rather than selecting against one validation block, but I did not replace or modify the required objective.

## Metrics convention

Metrics come from the combined final backtest, split by trade close timestamp exactly like `EP004ValidLoss`. Daily realized PnL is divided by the 10,000 USDT starting wallet, missing calendar days are zero, and Sharpe is annualized by sqrt(365). Annual return is the arithmetic mean daily return times 365; Sortino uses zero-target downside deviation; maximum drawdown is computed on the segment's daily realized-PnL curve; Calmar is annual return divided by that drawdown. Turnover is summed entry-plus-exit notional divided by initial capital and annualized.

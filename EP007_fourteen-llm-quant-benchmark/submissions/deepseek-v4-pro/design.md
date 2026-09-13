# Design — CrossSectionalMomentum

## 1. Strategy family: cross-sectional momentum (market-neutral + small net-long tilt)

I chose a **cross-sectional (relative-value) momentum** strategy over a single-asset trend
or mean-reversion strategy. Rationale:

- The universe is a fixed basket of 20 highly-correlated crypto perpetuals. The dominant
  common factor is **market beta**. A per-asset trend strategy would be mostly long beta;
  a cross-sectional strategy that goes long the strongest and short the weakest names
  **cancels most of that beta** and isolates the cross-sectional dispersion, which is the
  only place a small fixed universe offers a repeatable edge.
- Cross-sectional momentum is one of the most robust, best-documented anomalies in
  crypto (and equities). Crypto markets exhibit strong momentum in the cross-section over
  1–4 week horizons.
- It is naturally **two-sided**: `can_short = True`, and the strategy actually uses the
  short leg (n_short = 4).

Market-neutrality is **not forced** — I allow a modest net-long tilt (`n_long=7`,
`n_short=4`). The tilt is a deliberate, documented choice: crypto has a positive long-run
drift, and the data (both train and valid) favored a slight long tilt. But the core of the
P&L is the long/short *spread*, not the tilt: over the full sample the long leg returned
+198% vs. +78% market change, and the short leg returned **+13.9%** even in a strong bull
market — i.e. the short book made money on both sides of the spread, which is genuine
relative-value alpha rather than beta.

## 2. Signal / factor

For each pair, at each daily candle, I compute a single "bullishness" score:

```
score_t = ( close[t - skip] / close[t - (mom_window + skip)] - 1 )
          / std( 1-day returns over vol_window )
```

and then rank the 20 scores cross-sectionally each day; the top `n_long` are longs, the
bottom `n_short` are shorts.

**Why each ingredient:**

- **Momentum (`mom_window`)**: the core anomaly. Final value `mom_window = 12` days (≈ 2
  weeks). The hyperopt surface was flat over 11–14 days, so this is a robust choice, not a
  lucky peak.
- **Skip the last `skip` days (`skip = 3`)**: crypto has a *very* strong short-horizon
  reversal (yesterday's big winner tends to underperform today). Without skipping, the
  momentum signal is partly contaminated by reversal. Moving the momentum window's near
  edge back by a few days is a standard momentum robustification. The improvement is large
  and sits on a plateau (skip = 2, 3, 4 all work), so it is not overfit to a single value.
- **Risk-normalisation by realized volatility (`vol_window = 18`)**: dividing by trailing
  realized vol gives a "momentum-per-unit-risk" score. This (a) reduces the strategy's
  loading on the highest-volatility coins (which also have the largest transaction-cost
  drag and tail risk), and (b) made the train/valid behaviour dramatically more stable —
  raw momentum had train Sharpe 1.07 / valid 0.36 (a 0.7 gap), whereas the
  vol-normalised version had train ≈ valid across the whole window range.

## 3. Timeframe & turnover

**Timeframe = 1d.** This is the central cost/turnover trade-off of the problem:

- 30m/1h are destroyed by fees. The scaffold's own 30m example produced ~10,000 trades
  and lost 36% on validation purely to the 0.06%/side fee.
- 4h still rebalances 6× more often than 1d for little extra signal.
- 1d has enough bars (1,278 train + 363 valid) for stable cross-sectional ranks, and the
  daily rebalance cadence keeps round-trips low enough for the 0.12% round-trip cost to be
  a small fraction of the captured spread.

**Turnover control** (the second half of the cost problem):
- `exit_buffer = 0.17`: a position is only exited when its cross-sectional percentile rank
  falls 0.17 *past* the entry threshold (hysteresis). This kills threshold-chatter.
- `min_hold = 19` days: no position is closed before 19 days regardless of rank. This is a
  hard cap on turnover; the measured average holding period is ~23 days.

Result: ~300 valid-period trades/year, gross notional turnover ≈ 33×/year — but because a
round trip costs only 0.12% and the average captured move is far larger, fees are not the
binding constraint (see self_assessment.md for the exact cost arithmetic).

## 4. Entry / exit / risk

- **Entry**: at candle `t`, using only the cross-section known at `t-1` (the scaffold's
  mandatory `shift(1)`), enter long on the top `n_long` percentiles, short on the bottom
  `n_short`.
- **Exit**: rank-hysteresis as above. No fixed `minimal_roi` and no tight `stoploss`
  (stoploss = -0.99 is effectively "off"): the position-level risk is governed by the
  cross-sectional exit + the market-neutral book, which bounds drawdown far better than a
  per-name stop on a relative-value signal would (a stop-loss on one leg would destroy the
  hedge).
- **Sizing**: config-fixed (`stake_amount = unlimited`, `max_open_trades = 20`,
  `tradable_balance_ratio = 0.99`, **1× leverage**). Each of the ~11 open positions gets
  ≈ 1/11 of capital.

## 5. Optimisation & epochs

I hyperoptimised with the **provided `EP004ValidLoss`** (fits TRAIN, scores VALIDATION,
penalises train>valid gap) over the `buy` space with `-j 20`, `--random-state 42`.

**Epochs used: 400.** Why 400 and not 2000:

- The factor structure (vol-normalised, skip-day momentum) was already fixed by *a-priori*
  reasoning and a small number of exploratory backtests before hyperopt, so the search
  only needed to tune ~7 numeric parameters.
- The hyperopt surface is a **broad plateau** (the top 30 trials span valid Sharpe ≈
  2.2–2.8 with `mom_window` 11–14, `skip` 2–4, `n_short` = 4 consistently), which means
  the optimum is robust and does not require a fine-grained search.
- Over-searching is explicitly penalised by the Deflated Sharpe Ratio; 400 epochs is well
  inside the 2000 budget and leaves margin.

Final chosen parameters (also recorded in `config.json`):

| param | value | role |
|---|---|---|
| mom_window | 12 | momentum lookback (days) |
| skip | 3 | skip recent days (anti-reversal) |
| vol_window | 18 | volatility lookback for risk-normalisation |
| n_long | 7 | number of longs |
| n_short | 4 | number of shorts |
| exit_buffer | 0.17 | rank hysteresis |
| min_hold | 19 | min holding period (days) |

## 6. On the objective

`EP004ValidLoss` is `-(valid_sharpe - 0.5·max(0, train_sharpe - valid_sharpe))`. It only
penalises the classic failure mode (overfitting *train* so that it degrades on
*valid*). I agree with that direction, but note the asymmetry: a strategy that is much
*stronger* on valid than train is not penalised at all, even though that is also a form of
regime dependence (here, the 2024-07..2025-06 window was a strong bull). If I could modify
the objective I would add a symmetric small penalty on `|train - valid|` in *both*
directions, because a large valid≫train gap means the valid-period Sharpe is partly a
bull-market gift rather than a stable edge. I did not silently change the objective — I
optimised exactly `EP004ValidLoss` — but I chose parameters from the flat, well-populated
region of the surface rather than the single highest point, and I flag the regime risk in
self_assessment.md.

## 7. No look-ahead

- The factor uses only `close.shift(...)` (backward) and a `rolling().std()` (backward).
  No forward shift, no centred windows, no full-sample normalisation, no cross-section
  that includes the future.
- The scaffold aligns the 20 factor series and applies `shift(1)` so the decision at bar
  `t` uses only the cross-section observable at `t-1`. I did not touch that protection.
- The cross-sectional *rank* is computed within each bar only (no look-ahead), and the
  volatility used for normalisation is a trailing, per-pair, causal window (not a
  full-sample or cross-sectional statistic).

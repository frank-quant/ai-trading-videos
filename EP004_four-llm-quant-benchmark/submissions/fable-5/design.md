# Design — XSRiskMomentum

## Strategy family: cross-sectional risk-adjusted momentum

I chose a **cross-sectional** design because the objective is risk-adjusted return on a
fixed 20-coin basket with mandatory shorts. Ranking coins against each other and holding
long the strongest / short the weakest nets out part of the common market factor
(crypto pairs are 60–90 % correlated with BTC), which directly lowers portfolio
volatility — the denominator of the score — and gives the short side a structural job
even in bull regimes. Momentum is the best-documented cross-sectional anomaly in crypto
(weekly/monthly-horizon continuation is robust across studies and survives realistic
fees at moderate turnover), so it is the factor I can justify committing to *before*
seeing validation results, rather than something mined from this dataset.

I used the provided `CrossSectionalBase` scaffold unmodified (its shift(1) alignment is
exactly the look-ahead protection I would have written) and implemented only the factor,
plus a fixed risk overlay.

## The factor

```
score[t] = ( close[t-skip] / close[t-skip-W] - 1 ) / std(log-returns over W bars)
W    = mom_days × 6 bars (4h),   skip = skip_days × 6 bars
```

- **Momentum (`mom_days`)**: medium-horizon continuation. Hyperopt chose 11 days —
  inside the 1–4-week horizon the crypto momentum literature points to.
- **Skip window (`skip_days`)**: crypto exhibits short-term (~1-day) *reversal*;
  skipping the most recent day(s) keeps the continuation signal from being contaminated
  by it. Chosen: 2 days.
- **Vol-normalisation**: dividing by same-window realized vol turns the return into a
  t-statistic-like score. Raw pct-change ranks are dominated by the highest-vol coins
  (one pump candle ⇒ top rank ⇒ mean-reverts ⇒ you buy tops). Risk-adjusting prefers
  steady trends, reduces rank churn (turnover), and equalises the chance every coin has
  of reaching the extremes of the ranking. This is the standard "momentum / vol" refinement.

Everything is backward-looking (positive shifts, trailing rolling windows, per-row
cross-sectional ranks); the scaffold then applies shift(1) so the decision at bar *t*
uses only bar *t-1* information. No full-sample statistics anywhere.

## Timeframe: 4h

- 1d gives too few bars for an 11-day window to react and makes turnover control coarse;
  30m/1h multiply signal-noise trading and fees (the 30m example scaffold loses −6 % in
  two months purely to churn).
- 4h (6 bars/day) lets the ranking react within a day while the turnover controls keep
  average holding ~4–7 days, i.e. rebalance cost stays a small fraction of the momentum edge.

## Turnover control (fees are 0.12 % per round trip)

- `exit_buffer = 0.16` (rank hysteresis): a long opened in the top-25 % band is only
  closed when its rank falls ~3 slots below the entry threshold — kills threshold
  ping-pong, the main fee sink.
- `min_hold = 29` bars (~4.8 days): no signal-driven exit before ~5 days. Stoploss and
  liquidation exits are explicitly exempt (safety exits must not be throttled).
- Result: ≈ 1.5 trades/day across 20 pairs, annual one-sided turnover ≈ 35× wallet
  (~70× counting both legs) — at 6 bp/side ≈ 4 %/yr fee drag versus a ~20–55 %/yr gross edge.

## Portfolio: long 5 / short 1

Hyperopt's entire top region wanted an asymmetric book (`n_short = 1`). This is a
directional long tilt, and I am explicit about it: crypto carried a positive drift over
both segments, and a symmetric 5/5 book pays fees on five shorts whose alpha is smaller
than their beta cost. The single rotating short slot keeps the short side genuinely
active (164 short trades in validation, 556 in train) and adds hedge value in
drawdowns, while not fighting the drift. Returns therefore contain market beta — by
design, and acknowledged (see self_assessment.md).

## Risk overlay (fixed, not searched)

- `stoploss = −0.30` per position: catastrophic stop. Its main job is the short side —
  a 1x short caught in an alt-coin melt-up would otherwise ride toward −100 %/liquidation.
- Leverage untouched at 1.0 (exam rule; Sharpe is scale-invariant anyway).

## Hyperopt: 300 of 2000 epochs — why

Search space: `mom_days` (5–42), `skip_days` (0–2), `n_long`/`n_short` (1–10 each),
`exit_buffer` (0–0.40), `min_hold` (0–30) — 6 parameters, all in the buy space, all with
a mechanical role fixed in advance (no factor-form search). With the provided
`EP004ValidLoss` (fit on TRAIN, scored on VALIDATION with gap penalty), seed 42, `-j 20`.
I stopped at 300 because (a) the space is low-dimensional and smooth — the optimizer's
top-20 trials converged to one connected region (mom 11–12 d, skip 1–2, small buffer,
long hold, thin short book) well before epoch 300, so more epochs buy no new information;
and (b) every extra trial is another draw against the Deflated Sharpe Ratio — with the
loss scored directly on VALIDATION, over-searching *is* overfitting the validation set.

## Parameter choice: epoch 276, not the best-loss epoch 273

| epoch | objective | train Sharpe | valid Sharpe | book |
|---|---|---|---|---|
| 273 (best loss) | 2.111 | 0.30 | 2.11 | 2 long / 1 short |
| **276 (chosen)** | 2.056 | **0.79** | 2.06 | **5 long / 1 short** |

273's edge over 276 is 2.6 % of objective, bought with a 3-position book (huge
idiosyncratic risk, likely validation luck — its train Sharpe is only 0.30). 276 holds
6 positions, has 2.6× the train Sharpe (consistency across regimes), larger hysteresis
(cheaper), and essentially the same validation score. Picking the more diversified,
train-consistent neighbour over the argmax is a deliberate anti-overfitting choice.

## Final numbers (exam Sharpe definition, net of fees)

TRAIN: Sharpe 0.81, ann. return 20.4 %, maxDD 50.7 % (2021-05 and 2022 bear).
VALID: Sharpe 1.96, ann. return 54.6 %, maxDD 20.2 %. Train−valid gap ≤ 0 → no penalty.

## On the objective

The fixed objective (validation Sharpe with a one-sided train-gap penalty) is
reasonable, with one caveat worth stating: because hyperopt *scores on* VALIDATION,
the validation period stops being out-of-sample the moment the search starts — the DSR
correction for number of trials is then essential, and keeping the trial count low
(300) is my response. If I could change the objective I would score on rolling
walk-forward folds inside 2021–2025 and reserve VALIDATION for a single untouched
evaluation; the mechanism is otherwise sound.

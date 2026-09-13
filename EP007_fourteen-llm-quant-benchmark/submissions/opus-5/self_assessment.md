# Self-assessment — where XSTrendEnsemble is most at risk

Written to be useful rather than flattering. The three headings are ordered by how much
I think they actually threaten the out-of-sample result.

---

## 1. The single biggest risk: the validation year was kind to this factor

**What happened.** On TRAIN (2021-04 … 2024-06) the strategy scores a Sharpe of about
**0.75**; on VALIDATION (2024-07 … 2025-06) about **1.71**. The gap runs the
*opposite* way to the usual overfitting signature — validation is the better segment.

**Why that is not reassuring.** The objective's gap penalty
`0.5 * max(0, train - valid)` is exactly zero whenever validation beats train, so nothing
in the loss pushed back on a configuration that happens to suit the validation year. And a
one-year annualised Sharpe estimated from ~365 daily observations has a standard error of
roughly `sqrt((1 + S^2/2)/T)` ≈ **1.0**. A validation Sharpe of 1.5 is therefore not
reliably distinguishable from one of 0.5. Whatever the test period turns out to be, I
expect the realised Sharpe to be closer to the TRAIN number than to the VALIDATION number,
and I would treat the train figure as the honest central estimate.

**What I did about it.** Every structural choice — timeframe, the four factor legs, the
book width, smoothing — was made on TRAIN evidence and on four-way TRAIN sub-period
stability, *before* looking at validation. Configurations that only worked on validation
were explicitly rejected: a market-volatility regime filter lifted validation Sharpe from
1.44 to 2.34 while dropping TRAIN from 1.50 to 1.34, and a low-beta or low-vol overlay at
50 % weight pushed validation past 1.8 while collapsing TRAIN to ~0.0-0.6. Both are the
classic shape of fitting a single lucky year, and neither is in the submitted strategy.

## 2. Overfitting risk in the search itself

**Leg selection is the most-searched decision.** The four-leg set was chosen by scoring all
3-, 4- and 5-member subsets of an 8-candidate pool (182 combinations) on TRAIN. That is
real selection pressure, and it is the part of the design I would trust least. Two things
limit the damage: the selection statistic was mean *sub-period* TRAIN Sharpe rather than
full-sample TRAIN Sharpe, and the whole neighbourhood is flat — the top ~20 subsets all sit
between 1.4 and 1.8, and every single leg is individually profitable (solo TRAIN Sharpe
1.0-1.3). The ensemble is not carrying a leg that only works in combination.

**Hyperopt was deliberately kept small.** 300 epochs over 8 parameters, on a loss
whose validation term has SE ≈ 1.0. With that much noise, a longer search mostly buys a
higher order statistic of noise, which is precisely what the Deflated Sharpe Ratio removes.

The trial cloud proves the point rather than just asserting it: across the 300 trials the
correlation between TRAIN and VALIDATION Sharpe is only **r = 0.21**, and validation Sharpe
has sd 0.27 around a mean of 1.26. The best epoch (254, valid 1.946) is **2.5 sd** above
that mean — an order statistic, not a discovery. I did not take it. The submitted parameters
are epoch 233, chosen because its 12-nearest-neighbour region has the highest average
objective of all 300 trials (1.595), so it is a plateau rather than a spike. Its own
validation Sharpe (1.710) is deliberately *lower* than the best epoch's.

**Disclosure: one selection decision was not pre-committed.** My rule had a second step —
within the plateau, take the best neighbourhood TRAIN Sharpe — which selected epoch 28. I
dropped that step after seeing that epoch 28 is dominated by epoch 233 on own TRAIN (0.69 vs
0.75), own validation (0.94 vs 1.71) *and* neighbourhood objective (1.43 vs 1.60). I think
the tiebreaker was simply badly designed (it pulled toward the short-`max_hold` edge of the
plateau), but changing a rule after seeing the answer is exactly the move that invites
overfitting, so it is stated plainly here rather than buried.

**Residual concern.** All parameter ranges were set after I had already seen coarse TRAIN
results, so the bounds themselves encode some prior fitting. The ranges are wide and
centred on economically sensible values, but I cannot claim they were chosen blind. Two
chosen values also sit at or next to a bound (`stop_pct` 0.59 of max 0.60, `ma_slow_days` 45
of min 45), which means the search wanted to leave the box in those directions.

## 3. Look-ahead risk — audited, and I believe it is clean

This is the risk I am most confident about, because it is testable rather than a matter of
judgement.

* **The mechanical test.** `strategies/_lookahead_test.py` recomputes the whole composite on
  data truncated at six different cut dates and compares it to the full-sample composite.
  All **179,560** overlapping values match to `max|diff| = 0.0`, with identical NaN
  patterns. If any leg or any normalisation touched a future bar, this fails.
* **Why it is clean by construction.** Every leg (`pct_change`, `rolling(...).mean/std/max/min`)
  is a trailing pandas window. There is no `shift(-n)`, no `center=True`, no forward
  resample, and — importantly — **no full-sample statistics anywhere**: legs are combined by
  cross-sectional percentile *within a single timestamp*, never by a mean/std computed over
  the whole history. That is the normalisation trap the rules call out, and it is avoided.
* **The one cross-pair step, and why it is safe.** Ranking pair A against pair B at time `t`
  uses B's bar `t`, which is contemporaneous, not future. The scaffold's `_build_panel`
  then applies `shift(1)` before anything can be traded, and Freqtrade fills at the *open of
  the next candle* — an effective two-bar lag. `_build_panel` is inherited unmodified.
* **The empirical corroboration.** Performance degrades smoothly and gently as the lag is
  increased (TRAIN Sharpe 1.53 / 1.50 / 1.43 / 1.39 / 1.30 at lags of 1, 2, 3, 4 and 6
  bars). A strategy leaking future information collapses when you delay it; this one does
  not, which says the edge is genuine multi-day trend persistence rather than a timing
  artefact.

**The remaining subtlety.** The universe itself is survivorship-biased: these 20 coins were
all liquid perpetuals in 2026, which is information from after 2021. That bias is imposed by
the exam (the universe is fixed in advance and I am forbidden to change it), and being
dollar-neutral within the basket removes most but not all of it — a basket that excludes
coins that died is a basket whose *shorts* are systematically survivors.

---

## 4. Other things I would flag to a risk committee

* **No re-weighting of open positions.** Freqtrade holds whatever the entry bought, so a
  winner drifts to an oversized weight and the book stops being exactly equal-weight. The
  `max_hold_days` recycle bounds this, but the live book is only *approximately*
  dollar-neutral between recycles. I measured this: it is the main reason the realised
  backtest Sharpe sits below the continuously-rebalanced research figure.
* **Short squeezes are the fat tail.** At 1x isolated margin a short is liquidated if the
  coin roughly doubles. An early version without a stop took a **-92 % liquidation and two
  -99 % stop-outs** on TRAIN. `stop_pct` exists specifically for this and is the one risk
  control I would not remove, even though tighter stops score worse.
* **Costs are ~14 % of gross P&L.** The edge is real but not enormous; at 0.06 %/side
  a modest increase in the true cost of trading (wider spreads on the smaller alts than the
  fee proxy assumes) would eat a noticeable share of it. The strategy is more cost-sensitive
  than it is signal-sensitive.
* **Regime concentration.** All four legs are trend measures. They are correlated by
  construction, so the diversification across legs is specification diversification, not
  economic diversification. A sustained cross-sectional trend reversal hurts all four at
  once. In the submitted backtest this shows up as an outright **losing** stretch:
  2021-11 … 2022-10 returns **-5.5 %**, Sharpe **-0.29**. Every calendar year is positive
  (2021 0.48, 2022 0.39, 2023 1.56, 2024 1.20, 2025 H1 1.78) but the first two are thin.

# XSTrendEnsemble — design

Cross-sectional, dollar-neutral, long **and** short, 4h bars, 20 fixed USDT perpetuals.
Every number below is from TRAIN unless it explicitly says validation.

**Headline.** Long the top 7 and short the bottom 7 of the 20 names on an equal-weight
average of four cross-sectionally ranked trend measures, smoothed over 10 days to control
turnover. EP004-definition Sharpe **0.752 on TRAIN, 1.710 on VALIDATION**; 32x annual
turnover; 1x leverage; 1271 trades split 637 long / 634 short. 300 hyperopt epochs, final
parameters taken from a plateau in the trial cloud rather than the best epoch (§8). §6
records where I think the prescribed objective is wrong.

---

## 1. Strategy family: cross-sectional multi-factor trend

**Choice.** Rank the 20 coins against each other every bar, go long the strongest `n_side`
and short the weakest `n_side` with equal notional.

**Why this family.** Three reasons, in order of weight:

1. **It is the family the data supports.** I screened 31 distinct factor definitions
   (momentum, reversal, realised vol, low-beta, skew, dollar-volume, Amihud illiquidity,
   breakout position) in ~60 configurations at 1h/4h/1d on TRAIN. Trend/momentum factors
   were the only group with a large, consistent, net-of-cost edge: cross-sectional 20-30 day
   momentum and trend-vs-moving-average produced net TRAIN Sharpes of 1.1-1.4 as *single*
   factors, while
   short-horizon reversal was strongly *negative* (1-day reversal: -4.5), i.e. crypto
   perpetuals continue rather than revert at these horizons. Low-vol, skew and illiquidity
   factors were flat-to-negative on TRAIN.
2. **Dollar-neutrality answers the beta question directly.** Long `n_side` and short
   `n_side` names at equal notional makes the book's net exposure identically zero by
   construction, so the return is cross-sectional dispersion and cannot be market beta.
   That is a structural guarantee, not a regression result. Given the brief explicitly warns
   that "returns which are just market beta will be identified as such", I preferred a
   design where the question cannot arise. It also removes the enormous directional
   volatility of crypto from the P&L, which is what a Sharpe objective rewards.
3. **It is cheap enough to survive 12 bps a round trip.** A cross-sectional book only trades
   when the *ordering* changes, not when the market moves. With signal smoothing the
   submitted book runs at 32x wallet turnover a year on TRAIN — ~1.9 % a year in fees
   against a ~20 % gross annual return.

**What I rejected and why.** A directional trend overlay (scale the book by whether the
equal-weight index is above its 60-day average) was tested and discarded: it raised nothing
reliably and destroyed the 2021-11…2022-10 sub-period (Sharpe 0.64 → **-1.66**). Regime
filters keyed on market volatility looked excellent on validation (1.44 → 2.34) while
*hurting* TRAIN (1.50 → 1.34) — the signature of fitting one lucky year, so they are not in
the strategy.

## 2. Signals — four legs, each justified

Each leg is computed per pair from trailing windows only, converted to a **cross-sectional
percentile at that bar**, and the four percentiles are averaged with equal weight.

| Leg | Definition | Why it is in |
|---|---|---|
| `mom` | `close.pct_change(mom_days)` | Textbook cross-sectional momentum, and the strongest solo leg (TRAIN 1.30). Raw return is not comparable across coins — which is precisely why it enters as a *rank*. |
| `ma_fast` | `(close/SMA(ma_fast_days) - 1) / realised_vol` | Trend against a moving average, divided by realised vol so that a 5 % move in BTC and in DOGE are not read as the same signal. |
| `ma_slow` | same form, longer window | Same economics, slower clock. The single most valuable leg to keep: removing it costs more TRAIN Sharpe than removing any other (-0.46). |
| `pos` | `(close - min(low,N)) / (max(high,N) - min(low,N)) - 0.5` | Donchian/breakout position. Bounded in [-0.5, 0.5] and driven by *extremes* rather than averages, so it reads a different part of the price path. |

Measured contribution of each leg (4h, 8-day smoothing, `n_side` 8, TRAIN). These come from
the offline research harness — a continuously re-weighted book scored **mark-to-market**, so
the levels run well above the realised-at-close backtest numbers in §9 (see §6 for exactly
why). They are used here only to compare legs *against each other*, which the accounting
convention does not distort. "worst sub" is the weakest of four equal TRAIN sub-periods:

| leg set | TRAIN | VALID | worst sub | ΔTRAIN vs full |
|---|---|---|---|---|
| **all four (submitted)** | **1.765** | 1.581 | **1.09** | — |
| drop `ma_slow` | 1.305 | 1.799 | 0.69 | **-0.46** |
| drop `mom` | 1.469 | 1.365 | 0.78 | -0.30 |
| drop `pos` | 1.597 | 1.514 | 1.11 | -0.17 |
| drop `ma_fast` | 1.716 | 1.288 | 1.06 | -0.05 |
| `mom` alone | 1.300 | 1.275 | 0.31 | -0.47 |
| `ma_fast` alone | 1.112 | 1.305 | 0.75 | -0.65 |
| `pos` alone | 1.129 | 1.589 | 0.64 | -0.64 |
| `ma_slow` alone | 1.025 | 0.870 | 0.13 | -0.74 |

**Why an ensemble at all.** No single leg comes near the composite: solo legs run 1.03-1.30
against 1.77 combined. The robustness gain is larger than the level gain — the composite's
*worst* sub-period is 1.09, against 0.13-0.75 for the legs individually (same
mark-to-market basis; the realised backtest's worst sub-period is negative, see §9). That
is what a gap-penalised objective actually pays for.

**Honest note on `ma_fast`.** It is the weakest member: removing it costs only 0.05 of TRAIN
Sharpe, so it is close to redundant with `ma_slow`. It stays because the four-leg set has the
best TRAIN Sharpe and a top-two worst sub-period, and because dropping a leg to chase 0.05
would be fitting noise in the other direction. A reviewer preferring parsimony could run
`mom + ma_slow + pos` (1.716 / 1.06) and lose almost nothing.

**Why average cross-sectional ranks rather than raw values or z-scores.** This was worth a
lot: the identical legs combined by per-pair time-series z-score score TRAIN 1.11; combined
by cross-sectional percentile they score **1.77**. Ranking within each bar also caps every
leg's influence so none can dominate through scale or an outlier, and — importantly for §7 —
it uses no full-sample statistics.

**Leg selection, honestly.** The four-leg set was picked by evaluating all 3/4/5-member
subsets of an 8-candidate pool on TRAIN, ranked by mean sub-period Sharpe. That is genuine
search pressure and is flagged in self_assessment.md. Mitigating it: the top ~20 subsets
all score 1.4-1.8, so the choice sits on a plateau rather than a spike.

**What I left out.** Funding rate was available but not used as a signal — Freqtrade already
charges funding on every position in futures mode (-407.86 USDT over the submitted run), so
it is already in the P&L as a *cost*. Adding it as a *signal* would be a carry factor — a
different strategy family — and I had no TRAIN evidence it survived costs.

## 3. Timeframe: 4h

All four timeframes were run with the *identical* submitted composite — same horizons in
days, same smoothing in days, same `n_side` — so this is apples-to-apples (TRAIN,
mark-to-market):

| timeframe | Sharpe, no smoothing | Sharpe, 8-day smoothing | turnover/yr | fee drag/yr | worst TRAIN sub-period |
|---|---|---|---|---|---|
| 30m | **-1.27** | 1.66 | 774 → 30 | 46 % → 1.8 % | 0.74 |
| 1h | -0.26 | 1.68 | 508 → 30 | 31 % → 1.8 % | 0.82 |
| **4h** | 0.97 | **1.77** | 214 → 29 | 13 % → 1.8 % | **1.09** |
| 1d | 1.21 | 1.51 | 72 → 28 | 4.3 % → 1.7 % | 0.81 |

Two things fall out of this table, and they set the whole design.

**First, the left column is the cost constraint made visible.** Traded raw, 30m and 1h are
*negative* — a 46 % and 31 % annual fee bill against a gross edge worth ~1.8 Sharpe. The
frequency does not fail because the signal is worse at 30m; the gross signal is essentially
identical everywhere. It fails purely on cost.

**Second, once the signal is smoothed, turnover converges to ~30x a year at every
frequency**, because a smoothed composite changes at the speed of the underlying economics,
not at the speed of the bar. So the timeframe stops being a cost decision and becomes purely
an *execution-granularity* decision — and there 4h wins on TRAIN Sharpe (1.77) and, more
convincingly, on worst sub-period (1.09 vs 0.74-0.82). 1d is visibly coarser: it reacts a day
late and gives up ~0.26 of Sharpe. Below 4h there is nothing left to gain — the extra bars
only subdivide a signal that is not moving that fast.

4h also lets the book exit a name at six points a day, which staggers realised P&L across
days; §6 explains why that matters more than it economically should.

## 4. Turnover control — the part that decides whether this works

The table above is the argument: **smoothing is not a refinement, it is what makes the
strategy exist at all.** At 4h it takes turnover from 214x to 29x a year and net TRAIN
Sharpe from 0.97 to 1.77, against a gross Sharpe of ~1.89 — i.e. smoothing recovers almost
all of the gross edge, where the raw signal hands nearly half of it to the exchange. Most
raw rank churn is noise around the selection threshold, not information. Three mechanisms,
in order of importance:

1. **Signal smoothing (`smooth_days`, chosen 10 days)** — a rolling mean of the composite,
   applied before the cross-sectional selection. The primary control, per the table above.
2. **Hysteresis (`exit_buffer`, chosen 0.10)** — enter the top/bottom `n_side`, but do not
   exit until the name has fallen `exit_buffer` past the threshold in cross-sectional
   percentile terms. Stops a name oscillating across the boundary from being traded twice.
3. **`max_hold_days`** — see §5; it caps turnover from the other side by bounding how long
   any position can sit.

`min_hold` (a floor on holding period) is inherited from the scaffold but **pinned to 0 and
excluded from the search**: the two controls above already remove same-day churn, and every
extra search dimension is paid for in the Deflated Sharpe Ratio.

**Book width.** The offline research favoured `n_side = 8` (8 beat 6 on diversification and
10 on turnover, since 10 forces the most ambiguous names near the median into the book).
Hyperopt chose **7** (14 of 20 names), and the parameter marginals over all 300 trials agree
— 7 has the best mean objective (1.36) with 6 next (1.24). 7 and 8 are adjacent points on a
flat ridge; I took the search's answer.

## 5. Risk management — and what forced it

The first working version had **no** stop and no holding-period cap, and TRAIN contained a
**-92 % liquidation and two -99 % stop-outs**: at 1x isolated margin a short is liquidated
when a coin roughly doubles, and unmanaged shorts were being held for 21 days on average.
Three trades cost ~15 % of the wallet. Two controls fix it:

* **`stop_pct`** — a hard per-name stop measured from entry (via `custom_stoploss` +
  `stoploss_from_open`), purely to cap the short-squeeze tail. Tight stops are *bad* for a
  trend book — 15 % stops cut TRAIN Sharpe to 0.24 — so this is deliberately loose. It is
  tail insurance, not a signal.
* **`max_hold_days`** — every position is recycled after N days. Freqtrade never re-weights
  an open position, so without this a winner compounds into an oversized directional bet and
  the book stops being dollar-neutral. Recycling also releases realised P&L steadily rather
  than in rare lumps, which matters for the objective (§6). Too short is expensive: a 4-day
  cap pushes turnover to 157x a year and Sharpe to 0.30.

Leverage is the inherited `1.0` — `leverage()` is not overridden. `minimal_roi` is disabled
(no profit target: truncating winners is the wrong trade for a trend strategy).

I also tested explicit drift-band re-weighting via partial exits (`adjust_trade_position`).
It reduced drawdown slightly (0.168 → 0.153) but enabling position adjustment perturbs
Freqtrade's `unlimited` stake sizing, and it did not pay for the added complexity, so it is
not in the submission.

## 6. Disagreement with the objective (stated, not acted on)

**I optimised the objective I was given.** But I think the Sharpe definition is the wrong
one, and the brief invites me to say so.

The loss groups `profit_abs` by **`close_date`** — a position's entire P&L lands on the day
it is closed, so the "daily return" series is realised-P&L-at-close, not the daily change in
account equity. I measured the difference on an identical book (same signal, same weights,
same costs; only the accounting differs):

| accounting | TRAIN Sharpe | VALID Sharpe | daily σ | daily kurtosis |
|---|---|---|---|---|
| mark-to-market equity | **1.77** | **1.58** | 0.0077 | 4.8 |
| realised-at-close (**the loss**) | 1.17 | 0.91 | 0.0106 | 22.9 |

The convention alone costs **34 % of the measured Sharpe on train and 42 % on validation**,
and multiplies daily kurtosis by five, because a 30-day position dumps 30 days of P&L into a
single day. **What I would optimise
instead: the Sharpe of the daily mark-to-market equity curve.** It measures the same
economics, is invariant to when you happen to close a position, and does not reward
churning positions purely to spread P&L across more days. As specified, the metric quietly
penalises long holding periods for a non-economic reason and rewards a strategy for
realising gains more often — an incentive I would not want in a live book.

Two smaller points. The gap penalty `0.5*max(0, train - valid)` is one-sided, so it does
nothing when validation *beats* train — which is my case, and which is arguably the more
suspicious direction given a one-year validation window. And with ~365 daily observations
the validation Sharpe has a standard error of roughly 1.0, so the objective it maximises is
mostly noise at the margin; that is the main reason I kept the search deliberately short.

## 7. Look-ahead safety

The scaffold's `_build_panel` is inherited **unmodified**, including its `shift(1)`. On top
of that: every leg is a trailing pandas window (`pct_change`, `rolling(...)`), there is no
negative shift / centred window / forward resample, and **no full-sample statistics** — legs
are combined by cross-sectional percentile *within one timestamp*, never by a mean or std
over the history. The only cross-pair step is a contemporaneous rank at bar `t`, which the
scaffold then shifts by one bar; Freqtrade fills at the next candle's open, so the effective
lag is two bars.

Verified mechanically by `strategies/_lookahead_test.py`: the composite computed on the full
sample and on data truncated at six cut dates agrees on all **179,560** overlapping values
with `max|diff| = 0.0` and identical NaN patterns. Corroborated empirically — performance
decays smoothly with added lag (TRAIN Sharpe 1.53/1.50/1.43/1.39/1.30 at lags 1/2/3/4/6)
rather than collapsing, which is what a leak would look like.

## 8. Optimisation — epochs used and why

**300 epochs**, `--spaces buy`, loss `EP004ValidLoss`, `-j 20`, `--random-state 20240701`.

**Why not 2000.** The objective's validation term has a standard error near 1.0. Searching
harder against a noisy target mostly raises the order statistic of the noise, which is
exactly what the Deflated Sharpe Ratio subtracts back off; the marginal epoch buys
overfitting more than it buys signal. The search space is also small and smooth by design —
8 parameters, all with an economic meaning and a plateau rather than a spike (the
`n_side` x `smooth_days` grid varies only between ~1.1 and ~1.8 across its whole range), so
the extra epochs would have little left to find.

**Search space** (all in the `buy` space; `min_hold`, `n_long`, `n_short` are pinned and
excluded from the search):

| parameter | range | chosen |
|---|---|---|
| `n_side` | int 6 … 10 | **7** |
| `smooth_days` | int 4 … 14 | **10** |
| `exit_buffer` | 0.00 … 0.20 | **0.10** |
| `max_hold_days` | int 15 … 60 | **36** |
| `stop_pct` | 0.25 … 0.60 | **0.59** |
| `mom_days` | int 10 … 30 | **14** |
| `ma_fast_days` | int 20 … 45 | **25** |
| `ma_slow_days` | int 45 … 90 | **45** |

**How the final parameters were chosen — and the evidence that this mattered.**

The single most important number produced by the whole search is this: across the 300
trials, the correlation between TRAIN Sharpe and VALIDATION Sharpe is **r = 0.21**. The
validation ranking is almost independent of in-sample quality — i.e. it is mostly noise.
Validation Sharpe has a cross-trial mean of 1.26 and sd of 0.27, and the best epoch (254,
valid 1.946) sits **2.5 sd above that mean**. Taking it would be taking the largest noise
draw of 300, which is exactly what the Deflated Sharpe Ratio exists to strip out.

So I did not take the best epoch. The rule, fixed before looking at the cloud, was:
score every trial by the mean objective of its **12 nearest neighbours** in normalised
parameter space, keep the top 20 % (a plateau survives its neighbours' vote; a spike does
not), and pick within that plateau. The submitted parameters are **epoch 233**, which has
the highest neighbourhood objective of all 300 trials (1.595, against its own 1.710) —
i.e. its whole surrounding region is good, not just the point.

The parameter marginals corroborate the pick independently: averaging the objective over
all trials at each value, the best regions are `n_side` 7, `smooth_days` 7-10,
`exit_buffer` 0.09-0.10, `max_hold_days` 30-36, `stop_pct` 0.48-0.60, `ma_fast_days` 20-22,
`ma_slow_days` 51-54. Epoch 233 sits inside or adjacent to every one of those.

**Disclosure of a deviation.** My pre-committed rule had a second step — within the
plateau, take the best *neighbourhood* TRAIN Sharpe — which selected epoch 28. I dropped
that tiebreaker after seeing that epoch 28 is dominated by epoch 233 on own TRAIN Sharpe
(0.69 vs 0.75), own validation Sharpe (0.94 vs 1.71) *and* neighbourhood objective (1.43 vs
1.60): the tiebreaker was pulling toward the short-`max_hold` edge of the plateau, which
buys a little in-sample Sharpe and gives up much more out of sample. Dropping it was a
change made after seeing results, and it is the one selection decision in this submission
that was not fixed in advance.

**Two boundary notes, stated rather than hidden.** `stop_pct` = 0.59 is one step off its
upper bound, which is the search telling me the stop should be as loose as allowed — it
fires on only 20 of 1271 trades and is genuinely tail insurance, not a signal.
`ma_slow_days` = 45 sits *on* its lower bound, so the true optimum for that leg may be
faster than the range allowed; the marginals are flat there (1.31 vs 1.34 for 51-54), so I
did not widen the range and re-search, which would have added trials for a noise-level gain.

## 9. Results

Final backtest, one run over `20210101-20250630`, split at 2024-07-01 by `close_date` —
exactly as `EP004ValidLoss` splits it. Sharpe is the EP004 definition throughout (daily
realised P&L / 10000 starting wallet, non-trading days zero-filled, annualised by
`sqrt(365)`). Fees 6 bps/side and funding are charged inside these numbers.

| | TRAIN (2021-04 … 2024-06) | VALIDATION (2024-07 … 2025-06) |
|---|---|---|
| **Sharpe** | **0.752** | **1.710** |
| annual return | 17.1 % | 81.1 % |
| Sortino | 1.01 | 3.68 |
| Calmar | 0.91 | 4.04 |
| max drawdown | 18.8 % | 20.1 % |
| win rate | 45.1 % | 49.2 % |
| profit factor | 1.15 | 1.46 |
| turnover / year | 32.1x | 58.1x |
| trades (long / short) | 956 (479 / 477) | 315 (158 / 157) |

Objective value `-(1.710 - 0.5 * max(0, 0.752 - 1.710)) = -1.710`; the gap penalty is
inactive because validation exceeds train.

**Stability, reported honestly.** Sharpe by calendar year: 2021 **0.48**, 2022 **0.39**,
2023 **1.56**, 2024 **1.20**, 2025 (H1) **1.78** — positive every year, but the first two
are weak. Split into four equal TRAIN sub-periods the worst one is **negative**:
2021-11 … 2022-10 returns **-5.5 %** for a Sharpe of **-0.29**. The continuously-rebalanced
research book had no losing sub-period (worst +1.09); the difference is the realised-at-close
accounting of §6 plus the position drift of §5. This is the strategy's real weak spot and I
would rather state it than let the headline validation number stand alone.

**Both sides are genuinely used.** Long and short counts are symmetric by construction
(479/477 on train, 158/157 on validation) and *both* legs are profitable — but unequally:
on TRAIN longs contributed +48.5 % and shorts +11.5 % of wallet. The book is dollar-neutral
at entry, so that asymmetry is the market's upward drift plus the drift of open positions
between recycles, not a directional tilt in the signal.

**Sanity checks.** `leverage` is 1.0 on every one of the 1271 trades. Funding was charged:
-407.86 USDT over the full run. No liquidations.

**Cost load.** On TRAIN, 32.1x annual turnover at 6 bps/side is ~1.9 % a year in fees plus
~1.0 % a year in funding, against a ~20 % gross annual return — costs consume roughly 14 %
of the gross edge.

Seed `20240701`, recorded in `config.json` (`ep004_seed`) and as `XSTrendEnsemble.SEED`.

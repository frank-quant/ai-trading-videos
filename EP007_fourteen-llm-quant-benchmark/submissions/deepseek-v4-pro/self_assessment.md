# Self-assessment — where this strategy is most at risk

## 1. Overfitting to a favourable validation regime (highest risk)

The single biggest risk is **regime overfitting to the validation window**. 2024-07 →
2025-06 was a strong bull market for crypto, and cross-sectional momentum with a modest
net-long tilt is exactly the kind of book that shines in that environment. Evidence:

- `valid_sharpe` (2.80) is far above `train_sharpe` (0.59). This is *not* penalised by
  `EP004ValidLoss` (it only penalises train ≫ valid), but it is a warning: much of the
  valid-period return is a bull-market tailwind plus beta, not a stable edge.
- The long leg returned +198% over the sample vs. +78% for the market. The short leg was
  +13.9% (real alpha — it made money shorting in a bull market), but the long leg still
  dominates the P&L.

I mitigated this by (a) keeping the core book market-neutral in *structure* (long/short
spread is the signal), (b) choosing parameters from the flat plateau of the hyperopt
surface rather than the single highest trial, and (c) using only 400 epochs. But I have to
be honest: **the 2.80 valid Sharpe should be heavily discounted** — under a Deflated
Sharpe Ratio with N=400 trials on a one-year window, a large part of it is expected
selection noise. The train-period Sharpe of ~0.59 is a more honest estimate of the
strategy's steady-state edge.

## 2. The long tilt = some residual beta

`n_long=7 / n_short=4` leaves a net 3-long (15% net-long) exposure. That tilt was chosen
because it helped in both train and valid, and because crypto has a positive drift, but it
means the strategy is **not fully beta-neutral**. A grader decomposing returns into beta +
alpha will attribute part of the valid-period return to beta. I accept this: the task
allows directional strategies, and the *spread* (winners minus losers) is still the engine.
A fully neutral `5/5` variant is a close fallback with valid Sharpe ≈ 2.4 and a cleaner
beta story; I chose `7/4` for the higher risk-adjusted score after documenting the tilt.

## 3. Turnover / cost sensitivity

The fee is 0.06% per side (6 bps; the config note says this already embeds a ~1.5 bps
slippage proxy on top of ~4.5 bps taker, so no extra slippage is charged in the backtest).
Gross notional turnover is ≈ 33×/year in valid. That is high in absolute terms, and the
strategy's edge is materially fee-sensitive: a naive 30m version of the same idea loses
~36%/year to fees. I controlled it with `min_hold=19` + `exit_buffer=0.17`, but a small
increase in costs (or a regime with smaller cross-sectional dispersion) would eat the
edge. The cost arithmetic: ~300 valid trades/year, each round trip ≈ 0.12%, ≈ 36%/year of
gross cost drag against a +162% gross — fees are ~1/4 of gross, which is manageable but
not negligible.

## 4. Look-ahead risks (low, but I checked)

- The factor is built only from `close.shift(k)` (backward) and `rolling().std()`
  (backward). No future bar, no centred window, no forward resample.
- Normalisation uses **trailing per-pair** volatility (causal), never a full-sample or
  cross-sectional statistic — so a value at time `t` is identical whether computed on the
  full data or on data truncated at `t`.
- The scaffold's `shift(1)` adds a second layer of delay (decision at `t` uses the
  cross-section at `t-1`, executed at `t+1` open). This is conservative (costs one extra
  bar of delay) and I did not weaken it.
- The only thing I did *not* independently re-verify is Freqtrade's internal
  funding-fee application in futures backtests; `funding_fees` are recorded per trade and
  I report `funding_included: true`, but I did not recompute their net contribution. Given
  1× leverage and ~23-day holds, funding is a second-order term.

## 5. Survivorship / universe

The universe is fixed (20 names) and I did not add or drop symbols based on performance.
No look-ahead selection. This risk is therefore structural zero.

## 6. Metrics methodology note

`metrics.json` follows the **provided loss's exact convention** (as required): train/valid
Sharpe, Sortino, Calmar and ann_return are computed from the *full-range* backtest
(2021-01..2025-06), splitting trades by `close_date` at 2024-07-01, and dividing each
segment's daily PnL by the **fixed starting wallet (10,000 USDT)**, zero-filling non-trading
days and annualising by √365. This reproduces `EP004ValidLoss` exactly (train 0.5914, valid
2.8035). Because the denominator is the *initial* wallet while valid-period positions are
sized on the (larger) compounded wallet, `ann_return` for valid (1.619) is a
loss-consistent "segment PnL / initial wallet" figure, not a standalone valid-period CAGR —
a fresh valid-only backtest compounds to +96.8% with a Freqtrade daily-wallet Sharpe of
2.48. Sharpe is scale-invariant, so the scored 2.80 is unaffected by this denominator
choice; I flag it only so the two figures are not misread as contradictory.

## 7. What I would do with more time

- Add a **cross-sectional dispersion / regime filter** (trade the spread more aggressively
  when dispersion is high) to de-risk the bull-regime dependence.
- Add a **beta hedge** or fully-neutral `5/5` variant and let a symmetric gap penalty pick.
- Test **funding-rate carry** as a second factor (data exists in `data/` but is not wired
  into the scaffold).

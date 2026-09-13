# design.md — HybridXSMomentum (EP007)

## 1. What the strategy is

A **daily (1d) hybrid cross-sectional strategy** on the fixed 20-pair USDT-perp
universe, built on the provided `CrossSectionalBase` scaffold (its shift(1)
look-ahead protection and `leverage()=1.0` are used untouched). Two signal layers:

1. **Cross-sectional factor (rank-based selection).** For each pair, computed
   causally on its own 1d OHLCV:

   ```
   r1      = close.pct_change(1)                      # 1-day return
   mom     = close.shift(1).pct_change(63)            # ~2-quarter momentum, skips latest day
   vol     = r1.rolling(35).std()                     # ~5-week realized daily vol
   score   = (mom - 1.11 * r1) / vol                  # vol-scaled momentum + reversal blend
   ```

   The scaffold aligns the 20 scores per timestamp, takes the cross-sectional
   percentile rank (0..1), and **shifts the whole panel by one bar** — the decision
   at bar t only uses the cross-section known at t-1. Entry: `xs_rank >= 1-3/20`
   → long (top 3), `xs_rank <= 1/20` → short (bottom 1).

2. **Absolute trend gate (per pair, not cross-sectional).** A long additionally
   requires `close > SMA(45)`; a short requires `close < SMA(45)`. This keeps each
   position on the right side of its own trend, cuts beta, and prevents the
   reversal term from fighting crashes/rallies. (With the gate off — pure XS —
   the baseline collapsed on TRAIN: Sharpe 0.26 vs 0.83; see §3.)

**Exits / turnover control.** Rank hysteresis (`exit_buffer = 0.34`: a long exits
only when its rank drops below `long_thr − 0.34`, i.e. ~7 rank notches of slack;
symmetric for shorts) plus `min_hold = 17` days. Result: average holding ≈ 40
days, turnover ≈ 7.1x/yr (train) and 9.8x/yr (valid) of starting equity in
entry+exit notional → fee drag ≈ 0.4–0.6%/yr at 6 bps/side. No stoploss
(`stoploss = -0.99`), exits are rank-based; no ROI exits.

**Why these signals.** Medium-term momentum is the most robust cross-sectional
anomaly in crypto; dividing by realized vol (Sharpe-momentum) de-noises the
ranking across pairs with very different vol regimes; the 1-day reversal term
 exploits the strong short-horizon reversal of illiquid-alt moves (weight 1.11
was chosen by hyperopt); the SMA gate converts the relative view into tradeable
positions on both sides. Funding is not used as a signal (data exists but I chose
not to add a fourth factor — parsimony for DSR); funding *costs* are charged
automatically by the futures backtester from the provided funding/mark files.

**Position sizing.** Config's `stake_amount = "unlimited"` sizes each position at
≈ available/20 (≈5% initially, growing with equity); leverage 1x (scaffold
default, untouched). Sharpe is scale-invariant, so no leverage is used (and it is
forbidden anyway).

## 2. Timeframe choice

Costs are the central constraint (0.12% per round trip). 30m/1h were rejected up
front: turnover would need to be ~20-50x higher to be useful, and fee drag would
dominate any realistic alpha. I ran the family at 1d and 4h (identical logic,
windows scaled to bars) through full hyperopt searches — see §4:

| search (300 epochs each, seed 42) | best valid Sharpe | valid 95th pct |
|---|---|---|
| **1d (HybridXSMomentum)** | **2.94** | 2.39 |
| 4h (HybridXS4h) | 2.48 | 2.16 |

1d won on best loss, on the whole right tail, and it has the lower fee exposure.
**1d is the delivered strategy**; the 4h comparison variant is kept in
`strategies/compare_variants.py` for reproducibility of the 4h trials only.

## 3. Baselines before tuning (default params, full range 20210101-20250630)

| variant | train Sharpe | valid Sharpe | note |
|---|---|---|---|
| hybrid, 1d | 0.83 | 0.63 | trend gate ON |
| pure XS (gate OFF), 1d | 0.26 | 0.64 | gate is load-bearing on train |
| hybrid, 4h (scaled defaults) | 0.31 | 0.92 | — |

## 4. Hyperopt — what was run and why I stopped

- Loss: **provided `EP004ValidLoss`** (train-fit, valid-scored, 0.5× gap penalty),
  untouched. `--spaces buy`, `-j 20`, `--random-state 42`, timerange
  `20210101-20250630` (hard-capped at the data boundary).
- Search space (all in "buy" space): `mom_win 10–90`, `vol_win 5–40`,
  `rev_w 0–1.5`, `use_trend (bool)`, `trend_win 10–120`, `n_long 1–10`,
  `n_short 1–10`, `exit_buffer 0–0.4`, `min_hold 0–20`. `SKIP=1` was fixed a
  priori (classic momentum skip; interacts with `rev_w`, so both were not freed).
- **Epochs: 600 total** = 300 (1d) + 300 (4h). I stopped deliberately:
  (a) the 1d search showed a *broad plateau*, not a lonely spike — among the 179
  trials with `mom_win ∈ [55,75]`, the median valid Sharpe is 1.83 and the 75th
  pct 2.14; (b) continuing epochs mostly mines the right tail of the trial
  distribution, which is exactly what the Deflated Sharpe Ratio penalises — with
  600 trials the expected max-of-N haircut is already material; (c) the 4h
  comparison had already resolved the timeframe question. Over-searching is
  over-fitting.
- **Final parameters = the argmin of the provided loss** (epoch 237 of the 1d
  search): `mom_win 63, vol_win 35, rev_w 1.11, use_trend True, trend_win 45,
  n_long 3, n_short 1, exit_buffer 0.34, min_hold 17`. They are hard-coded as
  class defaults in `strategies/HybridXSMomentum.py`; `config.json` is the exact
  config used, with `random_seed: 42`.
- The argmin did not suffer the train>valid gap penalty (train 0.52 < valid 2.94),
  so the selection was effectively on valid Sharpe — see §6 for what I think of that.

## 5. Results (self-reported, loss definition: daily PnL/starting wallet, ×√365)

From the segment backtests of §run.md (fresh 10k wallet per segment):

| metric | TRAIN (2021-01..2024-06) | VALID (2024-07..2025-06) |
|---|---|---|
| ann_return | 7.7% | 49.7% |
| **sharpe** | **0.524** | **2.831** |
| sortino | 0.566 | 3.543 |
| calmar | 0.315 | 14.37 |
| max_drawdown | -24.4% | -3.5% |
| win_rate | 45.1% | 62.7% |
| profit_factor | 1.247 | 2.915 |
| turnover_per_year | 7.09 | 9.78 |
| n_trades | 233 | 83 (45 long / 38 short) |
| sharpe_net_of_costs | 0.524 | 2.831 |

For transparency: measured on the full-range run split at 2024-07-01 (exactly how
the loss scores epochs), the same parameters give train 0.516 / valid 2.939 —
consistent with the segment numbers (differences come from wallet-path/compounding
and boundary trades). Fees (6 bps/side) and funding are already inside every number;
`slippage_bps = 0` because the fixed fee already includes a slippage proxy per the
environment's config. Validation trades contain zero liquidations and nine
force-exits only at the 2025-06-30 boundary.

## 6. Disagreements with the fixed objective (reasoned, not silently optimised)

1. **The gap penalty is one-sided.** `loss = -(vs - 0.5·max(0, ts-vs))` punishes
   train>valid but *rewards* valid>train configurations, even when the gap is a
   red flag (as here: 0.52 vs 2.83-2.94). A symmetric `|ts-vs|` penalty (or a
   penalty on valid/train ratio) would push selection toward strategies whose
   train performance explains their validation performance. I used the provided
   loss as required, but I would not trust a 2.8+ valid Sharpe that has no
   train-period support without the additional robustness evidence in §7.
2. **Daily-PnL Sharpe is insensitive to path within a day and to trade
   concentration.** A book with one short slot (n_short=1) can score the same
   daily Sharpe with far fewer independent bets; a DSR-style correction for the
   number of effective bets would punish my final pick more than the raw loss does.
   Given the fixed objective, I report it anyway and flag the risk in
   self_assessment.md.

## 7. Robustness evidence behind the final pick

- **Plateau, not spike:** 8 of the top-12 trials are the same (mom_win≈63,
  n_short=1) family; the mom_win 55–75 neighborhood has median valid Sharpe 1.83.
- **Structure, not noise, in the top-30:** all 30 use the trend gate, all have
  `mom_win > 55`, 22/30 have `rev_w > 0.5` — the search agrees on direction even
  when individual params differ.
- **Validation subperiods are consistent, not one lucky window:** 2024H2 Sharpe
  2.73 / 2025H1 3.34 (loss-split view), with only two losing months (−97, −238
  USDT) in validation.
- **Not market beta:** the 20-pair basket itself rose +36.2% during validation;
  the strategy made +49.7% annualised with 3.5% maxDD and traded both sides
  (45 long / 38 short trades). Over the full range, longs earned +6.5k USDT and
  shorts +3.4k USDT.
- **Mechanically clean:** worst validation trades are −30…−44% (rank exits, no
  liquidations), best +61…+202% (XLM/DOGE/XRP longs through the Q4-2024 alt rally).

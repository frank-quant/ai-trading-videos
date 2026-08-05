# DeepSeekMomentumXS - design notes

## Strategy family

**Cross-sectional momentum** on the fixed 20-coin USDT-margined perpetual
basket, on **1d bars**: each day we rank the 20 coins by their trailing
N-day return, go **long the top `n_long`** and **short the bottom `n_short`**,
and hold with hysteresis (exit only when the rank falls below the entry
threshold minus `exit_buffer`) plus a minimum holding period (`min_hold`).

The implementation subclasses `CrossSectionalBase`, which gives us three
things for free and which we did not weaken:

1. cross-sectional alignment of the per-pair factor across all 20 pairs,
2. `shift(1)` so the decision at bar *t* uses only information known at
   *t-1* (the single mandatory no-look-ahead step),
3. rank thresholds, hysteresis and min-hold plumbing.

## Why momentum

We ran a systematic factor screen on TRAIN+VALIDATION before fixing the
design (scripts/research_sim.py reproduces the research). The screen
measured, per factor, the cross-sectional rank IC *and* the tradable
top-5/bottom-5 tail spread at 1/3/5/10-day forward horizons, on both
segments:

- **Momentum (10-45d) is the only factor whose *tail* spread is strongly
  positive on BOTH TRAIN and VALIDATION** (e.g. 14d momentum top5-bottom5
  spread: +73%/yr h1, +216%/yr h3, +340%/yr h5 on TRAIN; +7%/yr h1,
  +152%/yr h5, +482%/yr h10 on VALIDATION). Crypto cross-sectional momentum
  is a documented anomaly (winner continuation over 1-2 week horizons), and
  it shows up precisely where the strategy trades: the tails of the cross
  section.
- **Short-term reversal** (negative 1-5d return) is inconsistent: positive
  on VALIDATION but negative on TRAIN at most horizons.
- **Low realized volatility** has a positive *rank IC* but a *negative tail
  spread* (the lowest-vol tail underperforms the highest-vol tail); it is
  not tradeable as a long/short tail book.
- Momentum blended with low-vol, reversal, or funding-contrarian terms did
  not robustly beat pure momentum under the provided loss, so we kept the
  factor pure and the search space small.

One methodological finding worth recording: **per-coin (own-history)
z-scoring destroys the cross-sectional signal** (14d-momentum tail spread
drops sharply when each coin is normalized against its own past). The
scaffold's cross-sectional ranking is the right normalization; the strategy
therefore feeds the scaffold the raw momentum value and lets `xs_rank` do
the cross-sectional standardization.

## Timeframe

**1d.** Fees are 6bps per side (~12bps round trip), so frequency is the
central cost decision. 30m/1h/4h produce more signals but churn through the
fee budget; 1d with hysteresis keeps the book sticky (validation turnover
~53x notional per year => ~6.4%/yr cost drag, small relative to the edge)
while still capturing the 1-2 week momentum horizon.

## Signal and rules

```python
factor_score(df, pair) = close[t] / close[t - mom_window] - 1
```

- Entry: `xs_rank >= 1 - n_long/20` -> long; `xs_rank <= n_short/20` -> short.
- Exit: long exits when `xs_rank < 1 - n_long/20 - exit_buffer`;
  short exits when `xs_rank > n_short/20 + exit_buffer`.
- `min_hold` days minimum before a position may close.
- Leverage fixed at 1x (`leverage()` not overridden; base returns 1.0).
- Position sizing: Freqtrade `stake_amount = "unlimited"`, `max_open_trades
  = 20`, `tradable_balance_ratio = 0.99`, isolated margin - untouched.

## Turnover control

1. **Daily rebalancing only** (1d bars).
2. **Hysteresis band** (`exit_buffer`): a coin leaves the book only when its
   rank falls well below (long) / above (short) the entry threshold, so
   positions do not flip when ranks jitter near the boundary.
3. **Minimum hold** (`min_hold` = 10d final): blocks round-tripping in the
   days right after entry.
4. **Bounded book** (n_long=7, n_short=5): only the strongest/weakest tails
   are traded; the middle of the cross-section (where momentum has no edge)
   is not touched.

## Costs

Fee is 0.06% per side from config.json (unchanged), and Freqtrade's futures
backtest also applies **funding fees** from the provided 1h funding-rate
data (the `funding_fees` field in every backtest trade confirms this), so
`funding_included` is true and all reported PnL/Sharpe numbers are net of
fees *and* funding. `slippage_bps` is reported as 0 because the config fee
of 6bps already includes a slippage allowance (per the config comment:
~4.5bps Binance perpetual taker + slippage buffer) and no separate slippage
model is used.

## Hyperopt

- Loss: the **provided `EP004ValidLoss`** (fits on TRAIN, scores on
  VALIDATION, penalises `0.5*max(0, train_sharpe - valid_sharpe)`). We did
  not write our own objective.
- Space: all parameters declared in the **"buy"** space:
  `mom_window` (10..24), `n_long` (5..9), `n_short` (5..9),
  `exit_buffer` (0.15..0.45), `min_hold` (5..15).
- **500 epochs** (`-j 20`, `--random-state 42`). We deliberately used a
  quarter of the 2000-epoch budget: the search landscape is smooth and
  narrow (momentum 10-18d, wide books, sticky holds), and the Deflated
  Sharpe Ratio penalises the number of trials, so additional epochs would
  mostly add over-search risk without material improvement. The top-15
  trials all cluster in one coherent region (mom 11-13, n_short=5,
  hold 10-13), which is exactly what a non-overfit optimum looks like.
- Best trial (epoch 408): `{mom_window: 13, n_long: 7, n_short: 5,
  exit_buffer: 0.15, min_hold: 10}` -> train Sharpe 0.649, valid Sharpe
  2.246, objective -2.24565 (no gap penalty; train < valid). These are the
  final parameters, recorded in config.json.

## Results

Segment backtests (each starting from the 10000 USDT wallet; loss-style
Sharpe = daily close-date PnL / 10000, 0-filled, sqrt(365)):

| metric | TRAIN 2021-01..2024-06 | VALIDATION 2024-07..2025-06 |
|---|---:|---:|
| annualised return | 19.2% | 71.1% |
| Sharpe | 0.69 | 2.15 |
| Sortino | 1.11 | 6.59 |
| Calmar | 0.91 | 6.17 |
| max drawdown | 21.0% | 11.5% |
| win rate | 45.0% | 49.1% |
| profit factor | 1.12 | 1.53 |
| turnover (x/yr) | 49.0 | 53.1 |
| trades | 1399 | 420 |
| long / short trades | 730 / 669 | 217 / 203 |

The validation Sharpe computed inside the hyperopt loss on the *combined*
run is 2.246 (train 0.649), identical to the hyperopt best; the segment-run
number (2.149) is slightly lower only because the validation backtest starts
flat with a 10000 wallet instead of inheriting the compounded book.

## Comments on the objective

The provided objective is reasonable and we optimised exactly it. One
observation: because the gap penalty only bites when TRAIN > VALID, the
loss has no incentive to prefer strategies that are strong on TRAIN when
VALIDATION is even stronger - which is the correct side of the trade-off
for a purely out-of-sample judgement, so we have no serious disagreement.
If we were building for deployment rather than for an exam score, we would
add a small floor/consistency term (e.g. require TRAIN Sharpe >= 0.5 or
penalise `|train - valid|` symmetrically) and prefer the mom-16..18 family,
which is more balanced across regimes (train ~ valid ~ 1.3); we kept the
given loss as the selection criterion for the final parameters.

## Look-ahead protection

- `CrossSectionalBase._build_panel` applies `shift(1)` to both the raw score
  and the cross-sectional rank - untouched.
- All per-pair computations are rolling/expanding and causal; momentum at
  bar *t* uses closes up to and including *t* only.
- No full-sample or centred normalisation anywhere.
- Verified empirically: a backtest truncated at 2025-03-31 produces
  **identical** closed trades up to that date vs the full-validation run
  (307/307 matched, 0 mismatches).

# Design — XSDonchianMom

Cross-sectional long/short on the fixed 20 USDT-margined perpetuals. Leverage left at 1x. Fee left at 0.06% per side.

## Strategy family

**Cross-sectional multi-factor (breakout + medium momentum).** At each daily close, score every name, rank the 20, long the top `n_long`, short the bottom `n_short`. Market-neutrality is not forced (`n_long=7`, `n_short=5` after hyperopt), but both sides are always eligible and both sides actually trade.

Time-series trend following was tested on TRAIN and was weaker and less stable across 2021–2024H1 calendar years. A pure size/illiquidity sort looked strong in 2021–22 and died in 2023–24H1, so it was discarded.

I did **not** subclass `CrossSectionalBase`. The scaffold's extra `shift(1)` plus Freqtrade's next-bar fill is a two-day lag on a daily strategy. The implementation ranks at bar *t* using only information known at *t*'s close; Freqtrade fills at *t+1* open. That is the usual one-bar causal lag. The scaffold file itself was not modified.

## Signals

Fixed on TRAIN diagnostics; not hyperopted.

1. **21-day Donchian position** `(close - 21d low) / (21d high - 21d low)`. Scale-free, comparable across coins. On TRAIN, a 5/5 daily XS sort of this factor had net Sharpe ~1.5 after 6 bp costs and was positive in 2021, 2022, 2023 and 2024H1.
2. **14-day skip-1 momentum** `close[t-1] / close[t-15] - 1`. Skip-1 drops the last bar (short-horizon reversal / microstructure). Raw 1–7 day reversal had a positive IC but **negative** net Sharpe — turnover ate it — so reversal is not in the live score.

Each factor is **cross-sectionally z-scored at date t** (mean/std of the 20 values at t, no full-sample stats) and blended:

`score = don_weight * z(donchian_21) + (1 - don_weight) * z(mom_14_skip1)`

Then percentile-ranked across the 20. `don_weight` is the only factor knob in the search (0.50–1.00); chosen value **0.57**.

Funding rate had a decent TRAIN IC after smoothing but was left out of the signal to keep the specification small. Freqtrade still **applies** funding as a cost (`funding_included: true`).

## Timeframe

**1d.** 30m / 1h / 4h daily-rebalanced sorts of the same families were destroyed by 12 bp round-trips. 1d is where Donchian/momentum still have signal after costs. Higher frequency was not used as a "more data" cheat.

## Entry / exit / turnover

- Enter long if `xs_rank >= 1 - n_long/20`; enter short if `xs_rank <= n_short/20`.
- Exit long only after rank falls through `long_thr - exit_buffer` (symmetric for shorts).
- `confirm_trade_exit` blocks exits until `min_hold` daily bars have elapsed (stoploss/liquidation still fire).
- No ROI, no trailing stop. `stoploss = -0.99` (isolated 1x still liquidated twice on TRAIN+VALID).

Chosen turnover knobs: **`min_hold=10`**, **`exit_buffer=0.01`**, **`n_long=7`**, **`n_short=5`**. Average hold ~14 days. That is the cost control; a 10-day floor is more important here than a wide hysteresis band.

## Sizing

Freqtrade defaults: `stake_amount=unlimited`, `max_open_trades=20`, `tradable_balance_ratio=0.99`. Scoring is Sharpe, which is scale-invariant, so I did not fight the engine on equal-weight notionals.

## Epochs

**80** (`--random-state 42`, `-j 20`, `--spaces buy`, `EP004ValidLoss`).

Why not 2000: the factor windows were already locked on TRAIN; the search is only width, blend weight, and turnover. DSR penalises the number of trials. 80 epochs with 20 workers covered the 5-dimensional buy space without a second mining pass.

I used the **provided loss as required**. Disagreement, not silent substitution: `EP004ValidLoss` penalises `train > valid` but **not** `valid >> train`. The selected trial has TRAIN Sharpe 1.10 vs VALID 2.19. A two-sided gap penalty, or selecting on TRAIN and treating VALID as a true holdout, would have been the better scientific objective. I still shipped the official-loss winner.

## Seed

`42` in `config.json` and `--random-state 42`.

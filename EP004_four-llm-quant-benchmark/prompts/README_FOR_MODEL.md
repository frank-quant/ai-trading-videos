# READ THIS FIRST — how to work in this environment

You are in a **Freqtrade 2026.6 `user_data` directory**. Market: USDT-margined perpetual
futures, 20 fixed pairs, futures / isolated margin. Timeframe is YOUR choice. Your full task is
in the goal prompt you were given; **this file is the ENVIRONMENT MECHANICS** for running it.

## 1. Write your strategy — family is your choice
Put your strategy in `strategies/` (e.g. `strategies/MyStrategy.py`). **Any systematic
strategy family is allowed** — cross-sectional, trend, mean-reversion, breakout, ensemble.
The one structural requirement: it must be able to go **both long and short**
(`can_short = True`, both sides actually used). Long-only is disqualified.

### Option A — write a plain Freqtrade IStrategy from scratch
Fully allowed. You own `populate_indicators` / `populate_entry_trend` /
`populate_exit_trend`, risk management, sizing, everything.

### Option B — use the OPTIONAL cross-sectional scaffold
If you go cross-sectional, `strategies/cross_sectional_base.py` saves you the plumbing:
subclass it and implement `factor_score(self, df, pair) -> pd.Series` (a **causal**
bullish score per candle). It aligns that score across the 20 pairs and applies
**shift(1)** so a decision at bar *t* only uses information known at *t-1*, then hands you:
- `xs_score` — your raw factor value, cross-sectionally aligned (keeps magnitude)
- `xs_rank` — cross-sectional percentile 0..1
plus hyperoptable `n_long` / `n_short` (1–10) and turnover controls `exit_buffer`
(hysteresis) / `min_hold` (min holding candles). Everything else in it (`stoploss`,
`minimal_roi`, `startup_candle_count`, entry/exit, sizing) is a **default you may
override**. Worked example: `strategies/ExampleXSMomentum.py`.
**If you use the scaffold, do not weaken its shift(1) protection** (disqualifying).

### What is YOURS to decide
| Choice | How |
|---|---|
| **Strategy family** | anything systematic, long **and** short capable |
| **Timeframe** | `timeframe = "30m" / "1h" / "4h" / "1d"` — all four downloaded |
| **Entry/exit, risk mgmt, sizing** | entirely yours |
| **Turnover control** | scaffold's `exit_buffer` / `min_hold`, or your own scheme |
| **Epochs** | up to 2000 — use as many as you judge right (fewer is often better; DSR penalises over-search) |

> **Costs are the central constraint**: fee is fixed at 0.06% per side (~0.12% per round
> trip) and must not be changed. High rebalance frequency + high turnover will be eaten
> alive by fees. Choosing frequency and controlling turnover is part of the problem.

### Capital & sizing (fixed for all models — do not change)
`dry_run_wallet = 10000 USDT`, `max_open_trades = 20` (one position per pair, 20 pairs),
`stake_amount = "unlimited"` (Freqtrade sizes each position from available balance),
`tradable_balance_ratio = 0.99`, isolated margin, **max 1x leverage per side**.
Holding fewer names deploys less capital, which scales absolute return up or down —
but scoring is on **risk-adjusted** metrics (Sharpe / Sortino / Calmar), which are
scale-invariant, so this does not advantage or disadvantage any choice of n_long/n_short.

## 2. Data boundary (hard)
- `data/` contains **TRAIN (2021-01 .. 2024-06)** and **VALIDATION (2024-07 .. 2025-06)** ONLY.
- The test set does **not** exist in this environment. Do not look for, or download, any other data.

## 3. How to run (PowerShell, from THIS folder)
⚠️ **Never pass `--timeframe` on the command line** — it overrides the timeframe set in your
strategy class and would silently run your strategy at the wrong frequency.

Backtest — **ALWAYS pass `--cache none`** (Freqtrade's cache will otherwise reuse stale results):
```
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy <YourClass> --config /freqtrade/user_data/config.json --cache none --timerange 20240701-20250630
```
Hyperopt (2000 epochs) — **use the PROVIDED loss `EP004ValidLoss`** (in `hyperopts/`); it fits
on TRAIN and scores on VALIDATION with a train/valid-gap penalty. **Do NOT write your own
objective/loss.** Declare all your hyperopt parameters in the **"buy"** space so `--spaces buy`
optimizes them. **Use `-j 20`** (parallel; per-trial logging is join-key based and parallel-safe).
**`hyperopt` does NOT accept `--cache none`** — don't add it.
```
# 1) clear stale per-trial log first (PowerShell)
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue
# 2) run hyperopt
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy <YourClass> --hyperopt-loss EP004ValidLoss --spaces buy --epochs <N> -j 20 --config /freqtrade/user_data/config.json --timerange 20210101-20250630
# 3) export the required hyperopt_results.json
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model <YOUR_MODEL_NAME>
```

## 4. Deliverables (produce in this `user_data` root)
`config.json` (your final chosen params + fixed seed), `run.md`, `metrics.json`,
`hyperopt_results.json`, `design.md`, `self_assessment.md`. **Exact schemas are in the goal prompt.**
(Your strategy `.py` stays in `strategies/`.)

## 5. Hard rules
- **No look-ahead** anywhere in your signal path: no future bars (no negative shift / centered windows /
  forward resample), no full-sample normalization, no target leakage. It must be verifiable by
  a "full data vs data-truncated-at-t gives the same value" test.
- **Realistic costs** are already set in `config.json` (fee 0.06%). Do not lower them.
- **Fixed 20-pair universe**; no performance-based selection.
- **Set and record a fixed random seed.**

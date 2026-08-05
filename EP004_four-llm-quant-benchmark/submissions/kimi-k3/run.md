# run.md — reproduce kimi_k3 (KimiK3XSTrend)

All commands run from this `user_data` folder (PowerShell, Docker). Data download excluded
(data already present and mounted read-only). **Never pass `--timeframe`** — the strategy class
sets `timeframe = "1d"`. Strategy: `strategies/KimiK3XSTrend.py` (+ its parameter file
`strategies/KimiK3XSTrend.json`). Fixed seed: **42**.

## 1. Hyperopt (400 epochs, provided loss, fixed seed)

```powershell
# clear stale per-trial log first
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue

docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy KimiK3XSTrend --hyperopt-loss EP004ValidLoss --spaces buy --epochs 400 -j 20 --random-state 42 --config /freqtrade/user_data/config.json --timerange 20210101-20250630
```

## 2. Export every trial to hyperopt_results.json

```powershell
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model kimi_k3
```

## 3. Final parameters

Hyperopt dumps its best-loss epoch to `strategies/KimiK3XSTrend.json`; the **final chosen
parameters are epoch 235** (not the raw best-loss epoch — see design.md §5 for the selection
rule), already recorded in `strategies/KimiK3XSTrend.json` and `config.json`:

```
mom_fast=12  mom_slow=127  w_slow=0.81  vol_win=36
n_long=5  n_short=3  exit_buffer=0.22  min_hold=1
```

## 4. Backtests (always `--cache none`)

Combined run (this is the convention the provided loss uses; the TRAIN/VALID numbers in
`metrics.json` are computed from this run's trade list, split at 2024-07-01 — they reproduce
`hyperopt_results.json` epoch 235 exactly: train 0.8215 / valid 1.8650):

```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy KimiK3XSTrend --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20250630 --export trades
```

Standalone segment runs (fresh 10k wallet per segment; net Sharpe 0.96 train / 1.55 valid —
both conventions are reported in design.md §5):

```powershell
# TRAIN 2021-01 .. 2024-06
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy KimiK3XSTrend --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20240630 --export trades

# VALIDATION 2024-07 .. 2025-06
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy KimiK3XSTrend --config /freqtrade/user_data/config.json --cache none --timerange 20240701-20250630 --export trades
```

Metric computation from an exported trade list (daily PnL / starting wallet, 0-filled days,
`sqrt(365)` annualization — the exact loss definition) is in `notebooks/compute_metrics.py`.

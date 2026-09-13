# run.md — exact reproduction commands

All commands run from this folder (`user_data` root). Docker image
`freqtradeorg/freqtrade:stable` (2026.6). The shared data directory is mounted
read-only from `D:\freqtrade_demo\EP004_env\data_shared`. Data download excluded.
No `--timeframe` is ever passed on the CLI (the strategy class sets `timeframe = "1d"`).

Strategy: `strategies/HybridXSMomentum.py` (class `HybridXSMomentum`).
All chosen parameters are the **class defaults** in that file (hyperopt epoch 237);
`config.json` carries the seed (`random_seed: 42`).

The commands below are given in the PowerShell form of README_FOR_MODEL.md.
(They were executed under Git Bash with `MSYS_NO_PATHCONV=1` and explicit
`D:/...` mount paths; the two forms are equivalent.)

## 1. Full-range backtest (TRAIN+VALIDATION, cap = data boundary 2025-06-30)

```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy HybridXSMomentum --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20250630
```

Expected: Total profit 9887.582 USDT (+98.88%), Sharpe (daily wallet balance) 1.11,
183 long / 131 short trades, backtested 2021-05-31 -> 2025-06-30.

## 2. Segment backtests (source of metrics.json)

```powershell
# TRAIN only
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy HybridXSMomentum --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20240630

# VALIDATION only
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy HybridXSMomentum --config /freqtrade/user_data/config.json --cache none --timerange 20240701-20250630
```

Expected: train Sharpe 0.57 (0.5243 on the loss definition), 233 trades;
valid Sharpe 2.69 (2.8312 on the loss definition), 83 trades, 45 long / 38 short.

## 3. Hyperopt (as run; provided loss, buy space, seed 42)

```powershell
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy HybridXSMomentum --hyperopt-loss EP004ValidLoss --spaces buy --epochs 300 -j 20 --random-state 42 --config /freqtrade/user_data/config.json --timerange 20210101-20250630
```

Second search for family selection (4h variant, class `HybridXS4h` in
`strategies/compare_variants.py`; same loss/space/seed):

```powershell
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy HybridXS4h --hyperopt-loss EP004ValidLoss --spaces buy --epochs 300 -j 20 --random-state 42 --config /freqtrade/user_data/config.json --timerange 20210101-20250630
```

Each run was exported with:

```powershell
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model glm_5_3_flash
```

The two per-run exports (`hyperopt_results_1d.json`, `hyperopt_results_4h.json`,
kept under `worklogs/`) were merged with a `strategy`/`timeframe` tag per trial
into the deliverable `hyperopt_results.json` (600 trials).

## 4. Metrics extraction (loss-definition Sharpe etc.)

```powershell
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/tools/analyze_bt.py
```

Reads the newest zip in `backtest_results/` and prints TRAIN/VALID metrics using
the exact `EP004ValidLoss` definition (daily PnL / starting wallet, zero-filled
calendar days, annualised by sqrt(365)).

# Reproduction commands — XSMomVolDaily (qwen3_8_max)

Run from this project root in **PowerShell**. Data download is excluded (data is
pre-downloaded and mounted read-only from `D:\freqtrade_demo\EP004_env\data_shared`).

Never pass `--timeframe` on the command line (the strategy fixes it at `1d`).
Backtests always use `--cache none`; hyperopt does not accept that flag.

## 1. Backtests (final parameters are baked into the strategy class defaults)

TRAIN (2021-01-01 .. 2024-06-30):

```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSMomVolDaily --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20240630
```

VALIDATION (2024-07-01 .. 2025-06-30):

```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSMomVolDaily --config /freqtrade/user_data/config.json --cache none --timerange 20240701-20250630
```

Results land in `backtest_results/` (one `.zip` per run). The self-reported numbers
in `metrics.json` are computed from those zips with the working script
`notebooks/compute_metrics.py` (same daily-PnL Sharpe convention as the provided loss):

```powershell
python notebooks/compute_metrics.py backtest_results/<train-result>.zip train
python notebooks/compute_metrics.py backtest_results/<valid-result>.zip valid
```

## 2. Hyperopt (300 epochs, provided loss EP004ValidLoss, buy space, -j 20)

```powershell
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy XSMomVolDaily --hyperopt-loss EP004ValidLoss --spaces buy --epochs 300 -j 20 --config /freqtrade/user_data/config.json --timerange 20210101-20250630
```

Note: hyperopt is stochastic in its search order; re-running it will not reproduce
identical trials. The trials actually used for selection are recorded in
`hyperopt_results.json`.

## 3. Export every trial to `hyperopt_results.json`

```powershell
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model qwen3_8_max
```

## Selected parameters (hyperopt epoch 231 / 300, lowest EP004ValidLoss)

| param | value |
|---|---|
| mom_window | 14 |
| skip | 2 |
| n_long | 7 |
| n_short | 6 |
| exit_buffer | 0.07 |
| min_hold | 8 |

Seed: 42 (recorded in `config.json` as `_seed`; the strategy/backtest pipeline is
deterministic given the parameters).

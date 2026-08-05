# Reproducing the DeepSeekMomentumXS results

All commands run from this folder (`ft_deepseek`), PowerShell. Data download is
excluded (the mounted `data_shared` volume already contains the TRAIN
2021-01..2024-06 and VALIDATION 2024-07..2025-06 data). The final chosen
parameters are recorded in `config.json` under `params.strategy` (and as
defaults in `strategies/DeepSeekMomentumXS.py`):

```json
{ "exit_buffer": 0.15, "min_hold": 10, "mom_window": 13,
  "n_long": 7, "n_short": 5 }
```

Fixed seed: `42` (used for hyperopt via `--random-state 42`).

## Backtests (always `--cache none`; never pass `--timeframe`)

Train segment:
```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy DeepSeekMomentumXS --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20240630
```

Validation segment:
```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy DeepSeekMomentumXS --config /freqtrade/user_data/config.json --cache none --timerange 20240701-20250630
```

Combined range (used internally by the EP004ValidLoss objective; reproduces
the hyperopt best run, 1815 trades, +187.63%):
```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy DeepSeekMomentumXS --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20250630
```

## Hyperopt (the exact run that produced hyperopt_results.json)

```powershell
# 1) clear stale per-trial log
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue
# 2) run hyperopt (500 epochs, -j 20, fixed seed, provided loss, "buy" space)
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy DeepSeekMomentumXS --hyperopt-loss EP004ValidLoss --spaces buy --epochs 500 -j 20 --config /freqtrade/user_data/config.json --timerange 20210101-20250630 --random-state 42
# 3) export the required hyperopt_results.json
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model deepseek_momentum_xs
```

Best trial: epoch 408, objective -2.24565 (valid Sharpe 2.246, train 0.649,
no train/valid gap penalty).

## Metrics

`metrics.json` numbers are computed from the two segment backtests above
(each starting from the 10000 USDT wallet) with the EP004ValidLoss Sharpe
definition: daily `profit_abs` grouped by close date, divided by the starting
wallet, non-trading days filled with 0, annualised by `sqrt(365)`. Fees
(0.06% per side) and funding fees are already inside `profit_abs` (Freqtrade
futures backtest), so the reported Sharpe is net of costs. The helper script
is `scripts/compute_metrics.py`.

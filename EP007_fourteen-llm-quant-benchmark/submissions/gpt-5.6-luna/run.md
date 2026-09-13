# Reproduction commands

Run these commands from this directory in PowerShell. The data download is intentionally
omitted. The supplied data mount is read-only; the `chown` warnings emitted by Docker are
harmless.

## Hyperopt

```powershell
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy CausalMultiFactorXS --hyperopt-loss EP004ValidLoss --spaces buy --epochs 120 -j 20 --random-state 42 --config /freqtrade/user_data/config.json --timerange 20210101-20250630
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model CausalMultiFactorXS
```

The 120 epochs were deliberate: the search found a validation-strong, low-turnover
candidate early enough to avoid spending the full 2,000-epoch budget and increasing
multiple-testing exposure.

## Backtests

Do not pass `--timeframe`; the strategy class owns the 4h timeframe.

```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy CausalMultiFactorXS --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20240630 --export trades
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy CausalMultiFactorXS --config /freqtrade/user_data/config.json --cache none --timerange 20240701-20250630 --export trades
```

The reported Sharpe values in `metrics.json` use the exact `EP004ValidLoss` daily-PnL
definition on one combined 2021-01-01 through 2025-06-30 run, split at 2024-07-01.

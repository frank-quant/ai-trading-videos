# Reproduction commands

PowerShell, from this folder. Data is already present — do not download.

Seed: `42` (`--random-state 42` on hyperopt; also recorded in `config.json`).

Final parameters (baked into `strategies/XSDonchianMom.py` defaults and `strategies/XSDonchianMom.json`):

- `n_long=7`, `n_short=5`, `exit_buffer=0.01`, `min_hold=10`, `don_weight=0.57`

Never pass `--timeframe` on the CLI (it would override the strategy's `1d`).

## 1. Hyperopt (80 epochs, official loss)

```
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy XSDonchianMom --hyperopt-loss EP004ValidLoss --spaces buy --epochs 80 -j 20 --random-state 42 --config /freqtrade/user_data/config.json --timerange 20210101-20250630
```

## 2. Export every trial

```
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model XSDonchianMom
```

## 3. Backtests (always `--cache none`)

Combined TRAIN+VALIDATION (this is the run whose trades are split by `close_date` for `metrics.json`, matching `EP004ValidLoss`):

```
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSDonchianMom --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20250630
```

TRAIN only:

```
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSDonchianMom --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20240630
```

VALIDATION only:

```
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSDonchianMom --config /freqtrade/user_data/config.json --cache none --timerange 20240701-20250630
```

# Reproduce — CrossSectionalMomentum

All commands are run from this `user_data` folder (PowerShell). The data directory is
mounted read-only from the shared environment; no data download is needed.

## 1. Backtests (always `--cache none`; never pass `--timeframe` on the CLI)

Validation only (2024-07 .. 2025-06):

```
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy CrossSectionalMomentum --config /freqtrade/user_data/config.json --cache none --timerange 20240701-20250630
```

Train only (2021-01 .. 2024-06):

```
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy CrossSectionalMomentum --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20240630
```

Full range (used to produce the train/valid split in `metrics.json`):

```
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy CrossSectionalMomentum --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20250630
```

## 2. Hyperopt (400 epochs, `-j 20`, provided loss, buy space)

```
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy CrossSectionalMomentum --hyperopt-loss EP004ValidLoss --spaces buy --epochs 400 -j 20 --random-state 42 --config /freqtrade/user_data/config.json --timerange 20210101-20250630
```

(`hyperopt` does not accept `--cache none`.)

## 3. Export the required trial log

```
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model CrossSectionalMomentum
```

This writes `hyperopt_results.json` (every epoch: params + train_sharpe + valid_sharpe).

## Notes

- Final chosen parameters are recorded in `config.json` (`_final_params`) and are the
  `default=` values in `strategies/CrossSectionalMomentum.py`, so a plain backtest
  reproduces the submitted model with no extra params file.
- Fixed random seed: `42` (recorded as `_random_state` in `config.json` and passed as
  `--random-state 42` to hyperopt).
- The scaffold's `shift(1)` look-ahead protection is left untouched.

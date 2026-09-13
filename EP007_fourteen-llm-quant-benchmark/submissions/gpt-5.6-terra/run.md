# Reproduction

Run these commands in PowerShell from this directory. The `20260904` random state is
the fixed seed. Do not append `--timeframe`; the strategy owns its 4-hour timeframe.

```powershell
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy BalancedXSTrend --hyperopt-loss EP004ValidLoss --spaces buy --epochs 60 -j 20 --random-state 20260904 --config /freqtrade/user_data/config.json --timerange 20210101-20250630
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model BalancedXSTrend
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy BalancedXSTrend --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20250630 --export trades
```

`metrics.json` uses the same convention as `EP004ValidLoss`: realised trade PnL is
aggregated by UTC close day, divided by the 10,000-USDT starting wallet, zero-filled
across every calendar day, then annualised by `sqrt(365)`. TRAIN and VALIDATION are
split by close time at `2024-07-01 UTC` from the one continuous backtest.

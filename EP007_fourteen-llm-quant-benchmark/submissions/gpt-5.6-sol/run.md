# Reproduction

Run these commands in PowerShell from this directory. The dataset is mounted read-only; no download command is needed.

```powershell
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue

docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy CausalXSTrend --hyperopt-loss EP004ValidLoss --spaces buy --epochs 300 -j 20 --random-state 5607 --config /freqtrade/user_data/config.json --timerange 20210101-20250630

docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model CausalXSTrend

docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy CausalXSTrend --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20240630 --export trades

docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy CausalXSTrend --config /freqtrade/user_data/config.json --cache none --timerange 20240701-20250630 --export trades

docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy CausalXSTrend --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20250630 --export trades
```

`metrics.json` uses the final combined backtest and the exact loss convention: trades are assigned by close timestamp, TRAIN is before 2024-07-01, non-trading days are zero, and daily profit is divided by the 10,000 USDT starting wallet. The segment commands are included as independent sanity checks. Funding is included by Freqtrade's futures backtester. The configured 6 bps per side includes the venue fee plus the scaffold's slippage proxy; `slippage_bps` reports the 1.5 bps proxy component.

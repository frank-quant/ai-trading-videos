# Reproduction commands (PowerShell, from this `user_data` folder)

Strategy: `strategies/XSRiskMomentum.py` (timeframe **4h**, set in the class — never pass
`--timeframe` on the CLI). Final parameters are loaded automatically from
`strategies/XSRiskMomentum.json` and are also recorded in `config.json` under `_ep004_final`.
Seed: **42** (hyperopt `--random-state 42`).

## 1. Backtest — TRAIN (2021-01-01 .. 2024-06-30)

```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSRiskMomentum --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20240630
```

## 2. Backtest — VALIDATION (2024-07-01 .. 2025-06-30)

```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSRiskMomentum --config /freqtrade/user_data/config.json --cache none --timerange 20240701-20250630
```

## 3. Hyperopt (as originally run — 300 epochs, seed 42)

```powershell
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy XSRiskMomentum --hyperopt-loss EP004ValidLoss --spaces buy --epochs 300 -j 20 --random-state 42 --config /freqtrade/user_data/config.json --timerange 20210101-20250630
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model XSRiskMomentum
```

Note: rerunning hyperopt overwrites `strategies/XSRiskMomentum.json` with the single
best-loss epoch (273). The submitted parameters are those of **epoch 276** (chosen for
robustness, see design.md); restore them to `strategies/XSRiskMomentum.json` before
running the backtests above, or verify against `config.json` → `_ep004_final.final_params`.

## 4. metrics.json (from the two backtest result zips of steps 1–2)

```powershell
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/compute_metrics.py --train /freqtrade/user_data/backtest_results/<TRAIN_RESULT>.zip --valid /freqtrade/user_data/backtest_results/<VALID_RESULT>.zip
```

The metrics use the same Sharpe definition as `EP004ValidLoss`: daily PnL summed per
calendar day / starting wallet (10 000 USDT), non-trading days filled with 0, annualised
by sqrt(365). All figures are net of the 0.06 %-per-side fee.

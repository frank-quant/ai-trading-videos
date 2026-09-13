# run.md — exact reproduction commands (XSRiskMom)

All commands are run from THIS folder (the `user_data` root), data download excluded.
`--cache none` is always passed to backtesting; hyperopt does not accept it.
The random seed is 42 (`--random-state 42`); backtests themselves are deterministic.

## 0. Params note (read first)

The final chosen parameters (hyperopt **epoch 303** of the 400-epoch run below) are recorded in
THREE places that always agree:

- `config.json` → `_final_params` block (documentation)
- `strategies/XSRiskMom.py` → class-default values of the `IntParameter`/`DecimalParameter`s
- `strategies/XSRiskMom.json` → Freqtrade's auto-loaded parameter file

⚠️ Re-running hyperopt (step 1) overwrites `strategies/XSRiskMom.json` with the *search's own*
best epoch (243). My final choice is epoch 303 (selected from `hyperopt_results.json` for
robustness — see design.md §7). After a fresh hyperopt, restore the final params by re-writing
`strategies/XSRiskMom.json` from `config.json`'s `_final_params` (or simply rely on the class
defaults — they are identical).

## 1. Hyperopt (400 epochs, provided loss EP004ValidLoss, seed 42, -j 20)

```powershell
# PowerShell, from this folder
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy XSRiskMom --hyperopt-loss EP004ValidLoss --spaces buy --epochs 400 -j 20 --random-state 42 --config /freqtrade/user_data/config.json --timerange 20210101-20250630
```

(Git Bash variant used during development: prepend `MSYS_NO_PATHCONV=1` and use
`-v "$(pwd -W):/freqtrade/user_data"`.)

## 2. Export hyperopt_results.json (provided script)

Note: the per-trial train/valid log (`hyperopt_trials.jsonl`) is written to the user_data root
by the provided loss during hyperopt. The log from the 400-epoch run is preserved at
`hyperopt_results/hyperopt_trials.jsonl`; if you want to re-export without re-running
hyperopt, copy it back to the root first (`Copy-Item hyperopt_results\hyperopt_trials.jsonl .`).

```powershell
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model XSRiskMom
```

## 3. Final backtests (exact scored segments)

```powershell
# TRAIN 2021-01-01 .. 2024-06-30
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSRiskMom --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20240701

# VALIDATION 2024-07-01 .. 2025-06-30
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSRiskMom --config /freqtrade/user_data/config.json --cache none --timerange 20240701-20250630

# (optional) full period, for the continuous equity curve
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSRiskMom --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20250630
```

Each run writes `backtest_results/backtest-result-<timestamp>.zip` (newest zip = latest run).

## 4. metrics.json computation

`strategies/metrics_from_result.py` implements the exact Sharpe definition of the objective
(daily PnL / starting wallet 10 000, non-trading days filled with 0, ×√365; Sortino analogous
with downside deviation; max drawdown from the daily equity curve):

```powershell
# TRAIN zip = the zip produced by the TRAIN run in step 3 (substitute its timestamp)
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/metrics_from_result.py /freqtrade/user_data/backtest_results/backtest-result-<TRAIN>.zip train 2021-01-01 2024-06-30 XSRiskMom

# VALID zip = the zip produced by the VALIDATION run in step 3
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/metrics_from_result.py /freqtrade/user_data/backtest_results/backtest-result-<VALID>.zip valid 2024-07-01 2025-06-30 XSRiskMom
```

The zips used for the reported `metrics.json` were
`backtest-result-2026-09-01_16-24-05.zip` (TRAIN) and `backtest-result-2026-09-01_16-24-15.zip`
(VALID).

## Reference results (reproduction targets)

| segment | trades (L/S) | net profit | Sharpe (objective def.) | max DD |
|---|---|---|---|---|
| TRAIN 2021-01..2024-06 | 975 (519/456) | +195.2% | 1.336 | 17.2% |
| VALID 2024-07..2025-06 | 300 (162/138) | +85.0% | 2.457 | 7.3% |

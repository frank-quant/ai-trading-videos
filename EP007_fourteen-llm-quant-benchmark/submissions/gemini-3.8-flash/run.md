# Reproduction Runbook: CryptoAlphaTrend

This runbook documents the exact, fully reproducible commands to execute backtesting on both Train and Validation periods, run hyperparameter optimization, and export all results.

---

## 1. Environment & Prerequisites

- **Freqtrade Docker Image**: `freqtradeorg/freqtrade:stable`
- **Shared Data Directory**: `D:\freqtrade_demo\EP004_env\data_shared` (mounted read-only to `/freqtrade/user_data/data:ro`)
- **Working Strategy Directory**: Current project folder (mounted to `/freqtrade/user_data`)
- **Hardware Profile**: 24 CPU cores, 20 parallel workers for hyperopt (`-j 20`).

---

## 2. Backtest Commands

### 2.1 Validation Period Backtest (`2024-07-01` to `2025-06-30`)
```powershell
docker run --rm `
  -v "${PWD}:/freqtrade/user_data" `
  -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" `
  freqtradeorg/freqtrade:stable `
  backtesting `
  --strategy CryptoAlphaTrend `
  --config /freqtrade/user_data/config.json `
  --cache none `
  --timerange 20240701-20250630
```

### 2.2 Train Period Backtest (`2021-01-01` to `2024-06-30`)
```powershell
docker run --rm `
  -v "${PWD}:/freqtrade/user_data" `
  -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" `
  freqtradeorg/freqtrade:stable `
  backtesting `
  --strategy CryptoAlphaTrend `
  --config /freqtrade/user_data/config.json `
  --cache none `
  --timerange 20210101-20240630
```

---

## 3. Hyperparameter Optimization & Export

### 3.1 Hyperopt Run (300 epochs, 20 parallel workers)
```powershell
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue
docker run --rm `
  -v "${PWD}:/freqtrade/user_data" `
  -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" `
  freqtradeorg/freqtrade:stable `
  hyperopt `
  --strategy CryptoAlphaTrend `
  --hyperopt-loss EP004ValidLoss `
  --spaces buy `
  --epochs 300 `
  -j 20 `
  --config /freqtrade/user_data/config.json `
  --timerange 20210101-20250630
```

### 3.2 Export Hyperopt Results
```powershell
docker run --rm `
  --entrypoint python `
  -v "${PWD}:/freqtrade/user_data" `
  freqtradeorg/freqtrade:stable `
  /freqtrade/user_data/export_hyperopt.py --model CryptoAlphaTrend
```

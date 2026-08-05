# Reproducing XSTrendEnsemble (EP004)

All commands are run from this `user_data` directory in **PowerShell**.
Data download is out of scope (the shared read-only data mount is assumed to exist at
`<数据目录>`).

Fixed inputs: `config.json` (fee 0.06 %/side, 20-pair static whitelist, futures/isolated,
`dry_run_wallet` 10000, `max_open_trades` 20, `stake_amount` unlimited), strategy
`strategies/XSTrendEnsemble.py`, loss `hyperopts/EP004ValidLoss.py`.

**Random seed: `20240701`** — passed to hyperopt as `--random-state 20240701`, recorded in
`config.json` (`ep004_seed`) and as `XSTrendEnsemble.SEED`. The backtest itself is
deterministic, so the seed only affects the hyperopt search.

The timeframe (`4h`) is set in the strategy class. **Never pass `--timeframe`** — it would
silently override it.

---

## 0. Final parameters

The chosen parameters are stored in **two** places and must agree:

* `config.json` → `ep004_final_params` (the deliverable record), and
* `strategies/XSTrendEnsemble.json` (the file Freqtrade actually reads at runtime).

`strategies/XSTrendEnsemble.json` is what the backtests below consume. If it is missing,
the class defaults in `strategies/XSTrendEnsemble.py` are identical to the chosen values,
so the runs reproduce either way.

---

## 1. Hyperopt (search) — 300 epochs, provided loss, buy space

```powershell
# clear the stale per-trial log first, or export_hyperopt.py will join against old rows
Remove-Item hyperopt_trials.jsonl -ErrorAction SilentlyContinue

docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy XSTrendEnsemble --hyperopt-loss EP004ValidLoss --spaces buy --epochs 300 -j 20 --random-state 20240701 --config /freqtrade/user_data/config.json --timerange 20210101-20250630
```

`EP004ValidLoss` fits on TRAIN (2021-01-01 … 2024-06-30) and scores on VALIDATION
(2024-07-01 … 2025-06-30) with the train/valid-gap penalty:
`loss = -(valid_sharpe - 0.5 * max(0, train_sharpe - valid_sharpe))`.
Note `hyperopt` does **not** accept `--cache none`.

## 2. Export every trial → `hyperopt_results.json`

```powershell
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model XSTrendEnsemble
```

## 3. Final backtest → the numbers in `metrics.json`

One run over the combined range; TRAIN and VALIDATION are then split by `close_date`
at 2024-07-01 — exactly how `EP004ValidLoss` splits them, so the reported Sharpe is
directly comparable to the optimisation objective.

```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSTrendEnsemble --config /freqtrade/user_data/config.json --cache none --export trades --timerange 20210101-20250630
```

Segment metrics (EP004 Sharpe definition: daily realised P&L / 10000 starting wallet,
non-trading days filled with 0, annualised by `sqrt(365)`):

```powershell
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/_ep004_metrics.py
```

### Optional — the two segments run separately

Only for inspection; `metrics.json` uses the split of the combined run above, because a
trade opened in June 2024 and closed in July 2024 must be attributed the same way the
loss attributes it.

```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSTrendEnsemble --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20240701
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy XSTrendEnsemble --config /freqtrade/user_data/config.json --cache none --timerange 20240701-20250630
```

## 4. Look-ahead check

`strategies/_lookahead_test.py` recomputes the composite on the full sample and on the
sample truncated at six cut dates, and asserts the values at `t <= cut` are bit-identical.

```powershell
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" -v "<数据目录>:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/_lookahead_test.py
```

Run these commands in PowerShell from `D:\freqtrade_demo\EP007_env\ft_gpt_6_astra`. Docker must have access to the supplied local image and the read-only shared data directory. No data download is required or authorized. Never pass `--timeframe`. Every backtest below uses `--cache none`; Hyperopt does not accept that option.

The evaluated runtime is Freqtrade 2026.6. The local `freqtradeorg/freqtrade:stable` image resolved to `sha256:87aa5c6d65359b34e9d99a0bb260a38c0efe0315253811e6f48c2afe8f278a6a`; its immutable repository reference is `freqtradeorg/freqtrade@sha256:87aa5c6d65359b34e9d99a0bb260a38c0efe0315253811e6f48c2afe8f278a6a`. The commands show the exact tag used. Use the recorded image for comparable reruns. Seed is 20260906, recorded in config and explicitly passed to Hyperopt.

Reproduce the final combined backtest with the delivered config:

```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy CausalRelativeMomentum --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20250630 --export trades *> logs/final_backtest.log
```

The completed result delivered in this run is `backtest_results/backtest-result-2026-09-06_03-59-50.zip`. Its TRAIN and VALIDATION metrics intentionally split the same continuous backtest, exactly matching the supplied loss. Freqtrade generates timestamped zip names; for a fresh rerun use its newly generated name. Regenerate metrics from the most recent backtest:

```powershell
$taskResult = Get-ChildItem -LiteralPath backtest_results -Filter *.zip | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$taskContainerResult = '/freqtrade/user_data/backtest_results/' + $taskResult.Name
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/work/report_metrics.py --result $taskContainerResult --strategy CausalRelativeMomentum --model CausalRelativeMomentum-GPT-6-astra --seed 20260906 --epochs 160 --family cross-sectional --factors volatility_scaled_48h_log_momentum lagged_cross_sectional_percentile --turnover-control "4h decisions, 0.10 rank hysteresis, 24h minimum for rank exits, immediate safety exits" *> logs/final_metrics.log
```

The helper imports the unchanged `EP004ValidLoss._sharpe_daily`; it does not substitute Freqtrade's summary-table Sharpe. Metric definitions and the split-boundary convention are in design.md and `strategies/work/metrics_audit.json`.

To reproduce the search, first restore its initial configuration. This intentionally replaces the final parameter mapping temporarily; the final selection command below restores the chosen mapping. All original scaffold config values remain identical.

```powershell
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/work/finalize_search.py --prepare-search
Copy-Item -LiteralPath strategies/work/search_config.json -Destination config.json
```

The initial default trend smoke backtest was run once before Hyperopt:

```powershell
docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable backtesting --strategy CausalDonchian --config /freqtrade/user_data/config.json --cache none --timerange 20210101-20250630 --export trades --export-filename /freqtrade/user_data/backtest_results/baseline.json *> logs/baseline.log
```

These are the three Hyperopt runs, in the actual order. Each export must finish while its corresponding root trial log is still present. The loop preserves the exact strategy, loss, spaces, worker count, seed, epoch requests and timerange used. Retired candidate sources are retained in strategies as working reproduction files. No parameter sidecars are used.

```powershell
$taskRuns = @(
    @{ Strategy='CausalDonchian'; Label='trend'; Epochs=96 },
    @{ Strategy='CausalReversal'; Label='reversal'; Epochs=64 },
    @{ Strategy='CausalRelativeMomentum'; Label='momentum'; Epochs=26 }
)
foreach ($taskRun in $taskRuns) {
    Remove-Item -LiteralPath hyperopt_trials.jsonl -ErrorAction SilentlyContinue
    $taskLog = 'logs/' + $taskRun.Label + '_hyperopt.log'
    docker run --rm -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable hyperopt --strategy $taskRun.Strategy --hyperopt-loss EP004ValidLoss --spaces buy --epochs $taskRun.Epochs -j 20 --random-state 20260906 --disable-param-export --config /freqtrade/user_data/config.json --timerange 20210101-20250630 *> $taskLog
    if ($LASTEXITCODE -ne 0) { throw 'Hyperopt failed; inspect the run log before proceeding.' }
    $taskModel = $taskRun.Strategy + '-GPT-6-astra'
    docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/export_hyperopt.py --model $taskModel
    if ($LASTEXITCODE -ne 0) { throw 'The provided export failed.' }
    $taskExport = 'strategies/work/' + $taskRun.Label + '_hyperopt_results.json'
    $taskTrialLog = 'strategies/work/' + $taskRun.Label + '_hyperopt_trials.jsonl'
    Copy-Item -LiteralPath hyperopt_results.json -Destination $taskExport -Force
    Move-Item -LiteralPath hyperopt_trials.jsonl -Destination $taskTrialLog -Force
}
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/work/finalize_search.py
```

The momentum request was set to `160 - 89 - 45 = 26` after observing the number of actually evaluated earlier trials. Freqtrade skipped 7/19/0 duplicate proposals in the three runs, leaving 89/45/26 evaluations and 160 total. There are 137 distinct parameter dictionaries. The provided exporter renumbers within each run; finalize_search.py preserves every exported trial, renumbers globally and selects the minimum full-precision stored loss, taking the first occurrence on ties. It asserts that no more than 160 evaluations were combined. Global epoch 144 is selected. The archived `momentum_epoch_budget.json` records the 26-slot request. Different versions or execution scheduling can change duplicate handling; the immutable raw files and complete exports preserve this actual run.

After reproducing the search, rerun the final backtest and metrics commands above. Causality and delivery audits are reproducible with:

```powershell
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/work/momentum_audit.py
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" -v "D:\freqtrade_demo\EP004_env\data_shared:/freqtrade/user_data/data:ro" freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/work/real_data_audit.py
docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/work/audit_delivery.py
```

`strategy_audit.py` and `reversal_audit.py` contain the discarded-family synthetic checks originally run before final selection. The final audit verifies all original config values, eight scaffold hashes, the exact JSON schemas, the full trial archive and unambiguous score joins, both trading directions, fees/funding reconciliation, and reproduction of the chosen full-precision loss. Logs and working audit files remain under the existing directories; the project root contains only the supplied files and required deliverables.

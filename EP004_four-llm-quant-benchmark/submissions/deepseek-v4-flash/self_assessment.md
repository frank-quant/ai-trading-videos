# Self-assessment: overfitting and look-ahead risks

## Where the strategy could be overfit

1. **Validation-period concentration (the biggest risk).** The final
   parameters were selected by `EP004ValidLoss`, which scores on VALIDATION
   (2024-07..2025-06). The chosen config has TRAIN Sharpe 0.65-0.69 vs
   VALIDATION Sharpe 2.15-2.25. A Sharpe of ~2.2 over a single 365-day
   window, in a period when large-cap alts trended strongly (SOL, XRP,
   TRX, AAVE...), could partly reflect a favourable regime rather than a
   repeatable edge. Cross-sectional momentum is a well-documented anomaly
   and the factor's tail spread is positive on TRAIN too (14d top5-bottom5
   +73%/yr at the 1-day horizon), which mitigates this, but the magnitude
   of the validation number should be expected to compress out-of-sample.

2. **Search-space mining.** We ran 500 hyperopt trials and the research
   process itself examined several factor families before committing to
   momentum. The DSR penalises the reported 500 trials, but informal
   exploration of other families (reversal, low-vol, funding tilts) is
   extra hidden multiplicity that no DSR will see. We tried to offset this
   by choosing a family with strong prior support in the crypto literature
   and by keeping the final factor set minimal (a single momentum window
   plus four selection/turnover parameters).

3. **Parameter fragility.** `mom_window=13`, `n_long=7`, `n_short=5`,
   `exit_buffer=0.15`, `min_hold=10` is the objective-maximising point, but
   neighbours are nearly as good (top-15 trials span mom 11-13, hold 10-13,
   buffers 0.15-0.42, valid Sharpe 2.04-2.25). The optimum is not a narrow
   spike, which is reassuring; still, small changes to the parameter grid
   could move the selected point.

4. **Turnover dependence.** The strategy turns over ~50x notional per year;
   ~6-7%/yr of gross return goes to fees. The fee is fixed at 6bps/side in
   config.json and cannot be lowered, but any real-world slippage beyond
   that allowance would degrade results proportionally.

## Look-ahead risks

1. **The shift(1) is the single point of protection.** `factor_score` is
   computed per pair on the full dataframe, then the scaffold aligns and
   shifts the panel so bar *t*'s decision uses rank at *t-1*, and Freqtrade
   fills at the *next* bar's open. We did not modify `_build_panel`, and the
   strategy never references future bars (no negative shifts, no centred
   windows, no forward resampling). We verified empirically that truncating
   the data at 2025-03-31 reproduces all 307 closed trades of the full
   validation run exactly, which is the stated test for no look-ahead.

2. **Ranking is per timestamp.** The scaffold ranks within each timestamp
   only; no full-sample or expanding cross-sectional moments leak into the
   score.

3. **Funding-rate handling.** Funding fees are applied by Freqtrade's
   futures backtest from the 1h funding-rate files (capped by the timerange),
   and the strategy itself does not use funding as a signal, so there is no
   funding-data look-ahead path.

4. **Start-of-sample artefacts.** With data starting exactly at 2021-01-01,
   the first ~13 days have no momentum values and the first trades appear
   only after the cross-section has warmed up; this affects both TRAIN and
   any re-run identically, and the loss's 0-filled days handle it.

## What we would do differently with more data/time

- Prefer a train/valid-balanced config (e.g. the mom-16..18 family with
  TRAIN ~ VALID ~ 1.3) if the goal were deployment robustness rather than
  the stated objective.
- Walk-forward re-optimisation (re-fit quarterly, never touching the test
  window) and a DSR calculation that accounts for the informal factor
  screening, not just the 500 recorded hyperopt epochs.
- Add a funding-aware tilt only if it survives walk-forward out-of-sample
  testing; in our screens its benefit was inconsistent.

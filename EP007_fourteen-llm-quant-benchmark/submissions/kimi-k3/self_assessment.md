# self_assessment.md — kimi_k3 (KimiK3XSTrend)

Where this strategy is most at risk, stated plainly.

## 1. Overfitting risks

- **Validation-aware model selection (the biggest one).** The provided loss scores on
  VALIDATION, so all 400 hyperopt trials — and my final pick — are chosen with validation in
  the loop. Validation is effectively part of the training set. Mitigants: only 400 trials
  (DSR-aware), a small 8-parameter space, parameters picked from a *plateau* (16 neighboring
  trials all score valid ≥ 1.1) rather than the argmax spike, and all factor *design* decisions
  (family, legs, timeframe, cost model) were made on TRAIN data only, before any hyperopt run.
  Residual risk remains: the true test year can still disappoint relative to the 1.87 valid
  number; the honest expectation is closer to the train-segment 0.8–1.0 net Sharpe.

- **Regime dependence.** Cross-sectional momentum feeds on dispersion and trending names.
  TRAIN sub-period spreads for the core factor were +1.9 / +0.8 / +1.3 (all positive, but the
  middle third was much weaker — 2022 chop). A long, directionless, low-dispersion grind (or a
  violent squeeze where losers rip and winners dump) will hurt. The book is market-neutral-ish
  by construction, so *market* beta is not the risk; *style* beta (momentum crash risk) is.

- **The objective's blind spot.** `loss = -(valid − 0.5·max(0, train−valid))` does not punish
  train≪valid configs. The raw best epoch (370: train −0.38, valid 2.68) is exactly that
  pathology — hyperopt found it in 370 trials, so the search *will* find such points. I rejected
  it and chose epoch 235 (train 0.82 / valid 1.87) instead. If the grader re-scores purely by
  the exam loss on a test window that behaves like validation, epoch 370 would have scored
  higher; I judged that regime-luck and optimized for robustness instead. This is a conscious
  trade-off, documented here and in design.md §5.

- **min_hold=1 sits at the space edge.** The chosen config effectively disables min_hold and
  relies on `exit_buffer=0.22` alone for churn control. Turnover is still low (~11×/yr train),
  and neighbors with min_hold 5–18 score similarly (e.g. epoch 305: 0.86/1.65), so this is not
  fragile — but an edge-value parameter is always a small warning sign.

## 2. Look-ahead risks

- **Scaffold guarantees.** All ranking/alignment goes through `CrossSectionalBase._build_panel`,
  whose `shift(1)` (both score and rank) I did not touch — decisions at bar *t* use the *t−1*
  cross-section. My `factor_score` uses only backward-looking pandas rolling windows
  (`rolling().mean/std`, `pct_change`) — causal by construction; no centering, no negative
  shifts, no full-sample normalization anywhere in my code.
- **Truncation test.** Because every statistic is a finite backward rolling window, recomputing
  the factor on data truncated at any *t* yields identical values up to *t* (verified by
  construction: no global state, no expanding/full-sample statistics).
- **Data snooping at design time.** Research scripts (`notebooks/research*.py`) hard-mask to
  `close.index <= 2024-06-30` for all factor selection; validation was only ever read by the
  provided loss. The 1d files extend past 2025-06, but every backtest/hyperopt command pins
  `--timerange` within 2021-01..2025-06, and Freqtrade loads only that window.

## 3. Execution / modeling caveats

- Freqtrade backtests fill at the next candle open with the config's fixed 0.06% taker fee;
  real fills on the smaller names (FIL, ETC…) would add slippage beyond the fee proxy in fast
  markets. Positions are ~10–25% of wallet each, multi-day holds, so this is second-order.
- Funding cashflows are not modeled by the backtester and not used as a signal (researched,
  rejected — see design.md §1); shorts in crypto typically *pay* funding in bull tapes, so live
  results would likely be modestly worse than backtest on the short leg.
- `n_trades` on validation is 144 — comfortably above the loss's 50-trade floor, but the valid
  Sharpe's standard error is still large (one year of daily data ≈ ±0.3–0.4 on the Sharpe
  estimate). Treat 1.87 as a point estimate with wide error bars, not a promise.

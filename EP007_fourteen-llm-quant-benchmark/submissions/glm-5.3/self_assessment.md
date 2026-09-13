# self_assessment.md — XSRiskMom

Where this strategy is most at risk of overfitting or look-ahead, and why.

## 1. Overfitting risk #1: selection on the validation segment (highest risk)

The loss we were told to use scores on VALIDATION. Every one of the 400 trials — including
the final choice (epoch 303) — was therefore evaluated on the validation year. That makes the
validation set an *implicit training set*, and my reported valid Sharpe 2.46 is an optimistically
biased estimate of out-of-sample performance. Mitigations I applied (they reduce, but do not
eliminate, the bias):

- I did **not** take the loss argmax (epoch 243: train 0.25 / valid 2.63) precisely because it
  looked like single-segment overfitting; the chosen point has real edge on both segments
  (train 1.34 / valid 2.46).
- I checked that the choice sits on a parameter **plateau**: neighbouring parameter sets
  (mom 9→10→12, vol 39→30→20, buffer 0.24→0.34, n_short 4→5) all give valid Sharpe 1.77–2.43,
  so the result does not hinge on one lucky coordinate.
- The factor itself is a 2-parameter, one-family signal, not a many-factor soup — the search
  space is small (6 dims), which limits the degrees of freedom available to overfit.

Residual risk: the cross-sectional momentum effect in crypto is regime-dependent. 2024-07..
2025-06 contained strong trending episodes (XRP +369%, BTC +70%) that favour momentum; a
choppy, mean-reverting test period would hurt this book, and there is nothing in 400 trials
that proves otherwise.

## 2. Overfitting risk #2: parameter-count vs evidence

400 trials × 6 dimensions, judged with a DSR lens, is defensible but not free. The specific
fragile coordinates I can identify:

- **vol_window=39** (essentially the top of the 10–40 range): the vol term is a ranking
  modifier; extreme windows alter the ordering only slightly, so I am not worried about a
  cliff, but 39 is not a "rounded" number — it smells of fine-tuning to noise. Perturbing it
  to 20 or 30 cost ~0.7–0.8 valid Sharpe (2.46 → 1.77–2.13), which is material and honest
  evidence that part of the parameter's value is fit to the sample.
- **min_hold=19 / exit_buffer=0.24** interact: both push turnover down. The plateau's better
  corner (buffer 0.34, min_hold 19) scored train 1.50 / valid 2.43 — so the *direction*
  (strong hysteresis, long holding) is robust even where the exact values are not.

## 3. Look-ahead risk: low, and verified

- The factor uses only `pct_change` (backward) and `rolling().std()` (backward). I ran the
  truncation test — computing the factor at 40 random cut points from data-truncated-at-t
  reproduces the full-sample value with max difference exactly 0.0.
- The scaffold's shift(1) + cross-sectional rank is untouched; ranks at bar t use only the
  t-1 cross-section.
- No full-sample normalisation exists anywhere in the path: the vol denominator is a rolling
  39-day window, and cross-sectional ranks are computed *per bar* across pairs, never across
  time.
- One subtle place worth flagging honestly: `startup_candle_count=100` means the first ~39
  bars of any segment have NaN factors and never trade — no warm-up leakage, but it does mean
  each standalone segment run "wastes" the first month and a bit (this affects both segments
  equally and slightly flatters the flat-wallet standalone VALID run's annualised return,
  since the skipped month was skipped for signal, not performance).

## 4. Structural risks in the execution simulation

- **Funding is charged on every held position** (included; VALID funding −170 USDT vs +8 495
  net profit). Funding is small here because the book is only mildly net long and funding in
  this period was moderate; in a frenzied bull the long side pays materially more funding and
  the 8/4 tilt would be costlier.
- **Fill assumptions**: backtest fills at the candle's open of the next bar with the fixed
  0.06% fee. For these large-cap perps at 1x with daily cadence and ~500 USDT clips this is
  realistic; I did not model separate slippage because the config fee already bundles a
  slippage proxy (per its own comment) on top of the ~0.045% taker fee.
- **Liquidation edge case**: 6 TRAIN trades ended in liquidation (-99 stoploss region).
  At 1x isolated margin these are deep-drawdown single names (LUNA-style collapses) — the
  book survived them, but a denser basket version with more leverage would not.

## 5. Beta exposure — the valid-year number is not purely alpha

The book runs **8 long / 4 short** ≈ +33% net notional. The validation universe was up
+36.2% equal-weight (BTC +70%, 11/20 names up), so part of the +85% VALID return and part of
the 2.46 Sharpe is directional market beta, not cross-sectional skill. Evidence the skill
component is real: the short book alone made +19.5% in VALID (shorting the *worst* four names
while the market rose), and TRAIN's short book made +22.4%. But a grader regressing my daily
returns on BTC will find a positive, significant beta — that is by design (the search chose
the tilt) and disclosed. The risk: if the test period is flat-to-down, the beta tailwind
reverses and I would expect roughly the train-segment profile (Sharpe ~1.3) rather than 2.5.

## 6. Data-boundary compliance

All runs used `--timerange` within 20210101–20250630. The raw data files physically extend to
2026-06-18, but every backtest, the hyperopt, and all analysis scripts filtered to ≤
2025-06-30 (the shared-data mount is read-only; nothing beyond the boundary was read by any
command I ran).

## 7. If I had more time / would do differently

- Add a **regime filter** (e.g. market-level trend/vol state) to gate the momentum book —
  cross-sectional momentum's worst periods are market-wide crashes where all correlation → 1.
- Test **equal-risk weighting** (inverse-vol position sizes) instead of the stake-unlimited
  equal-cash sizing — would have dampened the 2021 TRAIN drawdown (17%).
- Run **walk-forward splits inside TRAIN** (e.g. 3 folds) to select parameters without ever
  touching VALID, then report VALID once. That is the correct protocol; I did not do it
  because the mandated loss scores directly on VALID.

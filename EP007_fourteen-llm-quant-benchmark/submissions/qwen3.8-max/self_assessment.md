# Self-assessment — where XSMomVolDaily is most at risk

## 1. Overfitting risks (in order of severity)

**Selection is scored directly on VALIDATION.** The provided objective maximises
validation Sharpe, so by construction the chosen parameters are the best of 300
candidates *on the segment that is also being reported*. Mitigations, not cures:
the search ended on a wide plateau (top ~15 trials within 0.3 Sharpe of each other,
similar parameters), TRAIN Sharpe is positive, and only 300 of 2000 allowed epochs
were used. None of that makes the validation number unbiased.

**The train/validation gap is large and one-sidedly ignored.** The chosen trial has
train_sharpe 0.30 vs valid_sharpe 2.49. The fixed loss only penalises train > valid,
so this gap was free. The likely explanation is regime: TRAIN contains the 2022 bear
(where the short leg and momentum timing suffered) while VALIDATION (Jul 2024-Jun
2025) was a strong, dispersion-rich uptrend — an ideal environment for long/short
momentum. If the out-of-sample test window is less momentum-friendly, expect results
to look much closer to TRAIN than to VALIDATION. This is the single biggest risk.

**The short leg is regime-fragile.** Shorts lost -41% of stake-equivalent in TRAIN
and gained +9.4% in VALIDATION. `n_short=6` and the whole short-side economics are
therefore calibrated on a period where shorts happened to turn profitable; a
broad-based melt-up would make the short book bleed again (and vice versa).

**Short tail risk.** With 1x isolated margin a short can lose close to 100% of its
stake in a squeeze; TRAIN produced 3 liquidations and 2 near-stop exits averaging
≈ -94% (e.g. BCH short -97.7%). The strategy has no protective exit beyond rank
deterioration, so a violent short squeeze in the test window is a realistic bad
outcome. `min_hold=8` deliberately delays reaction, which makes this worse in a
squeeze and better in normal chop — an explicit trade-off.

**Metric-specific distortions.** The closed-trade daily Sharpe with zero-filled days
favors higher trade frequency (see design.md §6). Reported turnover (~30x entry/year)
is moderate, but part of that level was selected under this metric.

**Factor-window luck.** `mom_window=14` was the strongest window in the search; the
neighbourhood (13-14) is stable, but the exact value is estimated from one 3.5-year
training sample.

## 2. Look-ahead audit

I believe the signal path is free of look-ahead; the concrete checks:

- Factor uses only `shift(s≥0)` and backward `rolling` windows — computable at bar t
  from data ≤ t. The scaffold additionally applies shift(1) to the aligned panel, so
  the decision at bar t uses the cross-section as known at the close of t-1.
- Ranking is computed row-wise (per timestamp) across pairs — never across time, so
  no future cross-sectional information enters any rank.
- No full-sample statistics anywhere: no z-scoring or normalisation over the whole
  sample; the only normalisation is the backward rolling volatility.
- `min_hold` and `exit_buffer` decisions use only trade-open-time vs now and the
  current (already shift(1)-ed) rank.
- Fill timing: signals on candle t-1 produce orders at candle t's open via
  Freqtrade's standard backtest engine (`entry_pricing.price_side = other`).
- Startup warm-up (60 candles) is trimmed by Freqtrade before trading starts; all
  rolling windows (max 35 bars, vol floor 20) are shorter than that.
- **The standard truncation test holds**: recomputing any bar's score with data
  truncated at that bar gives the same value, because every operation is causal.

Residual caveats rather than identified leaks: (a) hyperopt itself selects on the
validation period, which is a form of in-sample reuse of that data — institutional,
unavoidable under the given objective, and disclosed; (b) `data/` physically contains
rows beyond 2025-06-30, but every run was timerange-clipped to TRAIN/VALIDATION and
no value from outside that range was read or optimised.

## 3. What would change my mind about this design

If the test window shows (i) a momentum crash / sharp mean-reversion regime, or
(ii) a low-dispersion, single-direction melt where all 20 names move together, the
cross-sectional spread itself collapses and no parameter choice within this family
would save it. The honest prior is that VALIDATION Sharpe 2.25 overstates what this
strategy will earn out-of-sample; TRAIN Sharpe 0.29 is the more conservative anchor.

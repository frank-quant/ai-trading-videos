# Self-assessment

The main overfitting risk is regime dependence. The selected validation period contains
a favorable directional crypto regime, and the asymmetric six-long/one-short book may
be exploiting that regime rather than a stable long/short edge. The short side is
structurally present and profitable in aggregate, but it contributes less than the long
side. The large validation return relative to TRAIN is therefore not evidence that the
strategy will generalize unchanged.

The factor windows and weights are also searched parameters. Although the search was
limited to 120 epochs and the model is intentionally compact, selecting on a validation
period still creates selection bias; this is why the trial count, seed, and every trial
are recorded. The result is especially sensitive to the 4h execution model, fee
assumption, and the hysteresis/minimum-hold settings.

Look-ahead risk is concentrated at the cross-sectional plumbing boundary. The factor
function uses only trailing `diff` and `rolling` operations on the current pair. The
inherited base then aligns all pair scores and applies the required one-bar `shift(1)`
before either entry or exit can use them. No future bar, full-sample statistic, or
cross-section containing future observations is used. A causal truncation test should
therefore change only values after the truncation point, not the score or rank at the
truncated candle.

Funding is not used as a predictive factor. Freqtrade's futures backtest/export includes
the available funding adjustments in trade PnL; this is reflected by
`funding_included: true` in the metrics file. No funding data outside the allowed date
boundary was read.

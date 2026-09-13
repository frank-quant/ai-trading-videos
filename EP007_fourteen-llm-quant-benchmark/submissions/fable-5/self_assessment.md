# Self-assessment — where XSRiskMomentum is most at risk

Ranked, most worrying first.

## 1. The validation set was optimized on — my biggest overfitting risk

`EP004ValidLoss` scores trials directly on VALIDATION (by design, same for all
candidates). That means my valid Sharpe of 1.96 is *not* an out-of-sample number: 300
trials looked at it, and I then hand-picked one of the top trials. The honest estimate
of true out-of-sample Sharpe is lower — with ~300 effective trials on a smooth
6-parameter space, the Deflated Sharpe correction will bite. Mitigations I applied:
few trials (300 of 2000 allowed), a pre-committed factor form (nothing about the
signal's *structure* was searched, only windows and portfolio plumbing), and choosing a
parameter point supported by a broad top region rather than the argmax. Residual risk:
real.

## 2. Regime dependence of the long tilt (market beta in the result)

The chosen book is 5 long / 1 short. VALIDATION (2024-07 → 2025-06) contains a strong
crypto bull leg; part of the 54.6 % validation return is simply market drift captured by
the tilt, not cross-sectional skill — long side made +59 %, short side −5 % in
validation. In a sustained bear, the tilted book loses its beta cushion and the
strategy leans on pure momentum spread, which the TRAIN segment (containing 2022)
suggests is worth ~0.8 Sharpe, not ~2. Judges regressing returns on a BTC/market factor
will correctly identify a positive beta. I accept this trade-off knowingly (design.md),
but it is the main reason to expect valid ≫ test degradation if the test regime differs.

## 3. Hyperparameter fragility around the momentum window

The top region clusters tightly at `mom_days` 11–12. Neighbouring windows (9, 14, 21)
score materially lower on validation. A tight optimum in lookback-window space is a
classic overfitting signature; the true momentum horizon is unlikely to be exactly 11
days. I partially discount this because 11 d sits in the middle of the horizon the
literature supports (1–4 weeks), but the *sharpness* of the peak is validation-fitted.

## 4. Look-ahead — believed clean, and here is the audit trail

- Factor: `close.shift(skip)/close.shift(skip+W) − 1` over trailing
  `rolling(W).std()` — positive shifts and trailing windows only.
- Cross-sectional rank: computed per timestamp row (no time dimension), then the
  scaffold's `shift(1)` delays it one full bar; scaffold code untouched.
- No full-sample statistics: no z-scores over the whole history, no fitted scalers.
- The rank at bar t does use the *contemporaneous* cross-section of other coins at
  t−1 close — that is information available at decision time, so it is causal.
- Remaining exposure: I rely on the scaffold's guarantee that `dp.get_pair_dataframe`
  in backtesting returns candle-aligned data; the shift(1)-then-map-by-date mechanism
  is the scaffold's, verified by reading its code, not by an independent
  truncate-and-recompute test. If anything is wrong there it affects every scaffold
  user equally.

## 5. Execution-model optimism

Fills are simulated at 4h-candle open prices with a flat 6 bp/side taker fee as the
cost-plus-slippage proxy. For the majors this is realistic; for the thinnest names
(FIL, XLM, ATOM at ~500 USDT clips) real slippage at signal-coincident moments could
be a few extra bp. With turnover ~70×/yr, each extra bp per side costs ~0.7 %/yr —
would shave the edge, not erase it. Funding payments are included by freqtrade's
futures backtesting (funding-rate data present), but funding on the tilted long book
during bull regimes is a real cost that a live run would feel more sharply than the
average suggests.

## 6. Small-N portfolio statistics

Six concurrent positions (5L/1S) from a 20-coin universe: single-name events (delisting
risk aside, e.g. an AAVE exploit) move the book ~17 % of deployed capital. The −30 %
stop caps a single-bar disaster but a gap through the stop fills worse. This is the
price of the concentration the optimizer preferred; I widened it from the 3-position
argmax precisely for this reason, and would not run fewer than ~6 positions live.

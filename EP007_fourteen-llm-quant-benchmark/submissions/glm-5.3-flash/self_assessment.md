# self_assessment.md — where this strategy can break

## 1. Look-ahead audit (what I verified)

- **Scaffold shift(1) untouched.** All cross-sectional scores/ranks flow through
  `CrossSectionalBase._build_panel`, which applies `panel.shift(1)` and
  `rank(axis=1, pct=True).shift(1)`. I did not modify that method.
- **Factor is causal.** `factor_score` uses only `pct_change`, `.shift(+1)`,
  `rolling(...).std()` on the pair's own past bars — no negative shifts, no
  centered/forward windows, no full-sample standardization. A
  "value at t is identical when computed on data truncated at t" test passes by
  construction: every operator is a causal rolling map; nothing sees rows > t.
- **Cross-sectional rank at row t uses only row t** of the (already causal)
  score panel; the scaffold then shifts the result — so a decision at bar t uses
  the cross-section as of t-1 close, and freqtrade fills at t's open or later.
- **Trend gate** is `close > SMA(45)` on the pair's own history — causal.
- **No target leakage:** the loss scores on realized trade PnL; no forward
  returns enter any signal. Funding/mark files are consumed by the backtester for
  costs, not by the signal.
- **Data boundary:** every command uses `--timerange` capped at 20250630. The
  1d feather files physically contain candles beyond the boundary; none were used
  (timerange filtering trims them before any indicator is computed).

## 2. Where it is most at risk of overfitting

1. **valid >> train (2.83 vs 0.52).** The fixed loss cannot punish this direction.
   The validation period (2024-07..2025-06) was unusually kind to trend-gated
   momentum with a reversal kicker: a violent alt-specific crash (H1 2025) after a
   clean Q4-2024 alt rally. In a range-grind regime like 2022 the same parameters
   *lost* money (2022 subperiod Sharpe ≈ −0.5, maxDD ≈ −24% on train). My honest
   expectation for the unseen test period is well below the validation Sharpe.
2. **Concentration: `n_short = 1`.** One short slot means the short book's
   outcome hinges on few bets (38 short trades in validation). The high daily
   Sharpe partly reflects few, mostly-winning concentrated bets — small effective
   sample, high estimator variance. A DSR correction for effective bet count
   would haircut this more than the raw number suggests.
3. **83 validation trades total.** With ~40-day holds, 12 months gives few
   independent observations; the valid Sharpe confidence interval is wide.
4. **Search on the scored data.** 600 trials were evaluated on the same
   train+validation window the loss scores. I stopped at 600 (vs the 2000 allowed)
   and documented the plateau, but the reported valid Sharpe is still an
   order statistic of 600 correlated tries — the Deflated Sharpe Ratio will (and
   should) discount it.
5. **Parameter coincidence at the range edges:** `rev_w = 1.11` and
   `min_hold = 17` sit mid-range (good), but `n_short = 1` is the boundary of its
   grid — boundary optima are a classic overfit signature. I kept it because the
   loss argmin chose it and the top-30 cluster agrees, but a `n_short = 2`
   variant of the same params would be my first robustness check with more data.

## 3. Failure modes that are NOT overfitting but still dangerous

- **Tail risk by design:** `stoploss = -0.99` means a squeezed short (an XRP-style
  +200% pump) rides until the rank exit; worst observed trade −44%. With ~5-7%
  positions and 1x leverage this is survivable but unpleasant; a crash-through
  regime with violent bear-market rallies is the worst case.
- **Funding drag in euphoric regimes:** crowded-long funding (8h) is charged to
  my longs; in a mania phase the long book pays a real carry.
- **Universe regime shift:** the factor assumes cross-sectional dispersion in the
  20 majors persists. If all 20 converge to one beta factor (extreme
  correlation), ranks become noise and the book churns at the hysteresis bands
  (mitigated by `exit_buffer=0.34` + `min_hold=17`).

## 4. If I had one more iteration

Add a symmetric gap penalty to the objective (or select by
`min(valid, train) − λ·|gap|`), forbid boundary optima (n_short ≥ 2), and
vol-target the book instead of uniform stakes. None of these change the delivered
strategy; they are listed as honest caveats, not post-hoc improvements.

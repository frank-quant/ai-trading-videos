# design.md — XSRiskMom

## 1. Strategy family: cross-sectional risk-adjusted momentum, long/short

I chose a **cross-sectional (relative-strength) momentum strategy** on the fixed 20-pair
universe. Rationale:

- With 20 correlated crypto perps, most of each name's return is the market factor; the
  cross-sectional spread between winners and losers is the part of returns a fixed-universe
  book can actually harvest without predicting the market itself.
- Cross-sectional momentum is one of the most replicated effects in crypto (and equities):
  over multi-day to multi-week horizons, recent relative winners keep outperforming recent
  relative losers. It is a slow signal (daily bars, multi-day holding), which matters because
  costs are the central constraint of this exam.
- Long and short come out of the construction naturally: long the top of the cross-section,
  short the bottom. Both sides are genuinely used (TRAIN: 519 long / 456 short trades;
  VALID: 162 / 138; both books profitable in both segments: TRAIN long +172.8% / short +22.4%,
  VALID long +65.5% / short +19.5%).

I built on the provided `CrossSectionalBase` scaffold (its shift(1) look-ahead protection is
used exactly as given, untouched), subclassing it with one `factor_score`.

## 2. The factor

Per pair, per daily bar (all causal, OHLCV only):

    mom(9)  = close / close.shift(9) - 1            # 9-day price momentum
    vol(39) = rolling std of daily returns, 39d     # realized volatility
    score   = mom(9) / vol(39)                      # risk-adjusted momentum

The scaffold then (i) aligns the 20 scores per bar, (ii) converts them to cross-sectional
percentile ranks (0..1), and (iii) applies the mandatory shift(1) so bar-t decisions only use
the t-1 cross-section.

**Why momentum, and why 9 days:** short-horizon (1–3 week) cross-sectional momentum is the
horizon most consistently documented for crypto; medium-horizon (30–90d) crypto momentum is
much noisier because the asset class mean-reverts over months. The hyperopt search
(5–60d) independently converged on the short end (9 of the top 10 trials used mom_window
9–16).

**Why divide by volatility:** this is a monotone-in-vol rescaling of each name's momentum —
it demotes high-volatility "lottery" names whose raw momentum is mostly noise. Since only
ranks (not magnitudes) drive trading, the scaling matters only through the *ordering* it
induces, which makes it robust (no scale calibration to overfit). Vol-adjusted momentum
(essentially a cross-sectional Sharpe ranking) is the standard way momentum is run in
institutional crypto books.

**Causality verification:** `pct_change` and `rolling().std()` are strictly backward-looking;
I verified the "full data vs data-truncated-at-t" test directly — at 40 random cut points the
factor value at t computed on truncated data equals the full-sample value with max absolute
difference exactly 0.0. The first ~39 bars are NaN (warm-up) and simply never trade.

## 3. Timeframe: 1d

Daily bars minimise cost per unit of signal: the factor is slow, positions hold ~23 days on
average, so each round trip pays 0.12% against an expected multi-percent holding-period move.
At 30m/1h the same cross-sectional signal would need to overcome roughly one to two orders of
magnitude more fee drag per unit of alpha. 4h/1d were the viable candidates; 1d wins on cost
and the daily Sharpe objective is computed at exactly this cadence.

## 4. Portfolio construction and sizing

- Each day, rank all 20 pairs by the (shifted) factor. **Long the top n_long=8, short the
  bottom n_short=4.**
- The 8/4 asymmetry was selected by the search, not imposed. It implicitly reflects that the
  universe drifts (crypto's long-side tail is fatter over the full sample) — the book runs
  mildly net long, which is a deliberate, disclosed exposure choice, not an accident (see
  self_assessment.md §5 for the beta decomposition).
- Sizing is the fixed exam setup (stake "unlimited", max 20 trades, 1x): Freqtrade sizes each
  new position at roughly equal weight of available balance, so the book is approximately
  equal-weight 8 long / 4 short.
- No stoploss/ROI exits (`stoploss=-0.99`, `minimal_roi` disabled): exits are purely the
  cross-sectional signal. Stops would add turnover and cut against a slow signal; at 1x
  isolated margin single-name risk is bounded by the stake.

## 5. Turnover control (the cost answer)

Turnover is controlled by two mechanisms, both hyperopted:

- **Rank hysteresis (`exit_buffer=0.24`):** a long is only closed when its rank falls below
  (top-8 threshold − 0.24) — i.e. out of the top ~35% of the cross-section, not merely out of
  the top 8. A short is only closed when its rank rises above (bottom-4 threshold + 0.24) —
  into the top ~44%. This wide band means a name must materially change its relative standing
  before capital moves.
- **Minimum holding (`min_hold=19` daily bars):** no position closes within its first 19
  daily bars.

Measured effect: ~23-day average holding, 300 closed trades in the validation year across a
12-position book (≈25/month), turnover ≈ 20× notional per year on VALID (27× on TRAIN).
Total costs (fees + funding) consumed ~4.6% of gross profit in VALID (239 + 170 USDT vs
8 904 gross) and ~11% in TRAIN (1 147 + 1 223 vs ~21 900 gross). The strategy survives its
costs with a wide margin; funding is included (futures mode, charged on every open position).

## 6. Optimization protocol

- Loss: the **provided** `EP004ValidLoss` (fit TRAIN, score VALIDATION, 0.5× gap penalty) —
  unmodified.
- Space: all 6 parameters in the **"buy"** space (`mom_window`, `vol_window`, `n_long`,
  `n_short`, `exit_buffer`, `min_hold`).
- **400 epochs** (not the full 2000): the search space is 6-dimensional and TPE had visibly
  converged — the best objective improved by <5% over the last 150 epochs, and the top-1% of
  trials all sit in the same parameter region. The exam scores a Deflated Sharpe Ratio that
  penalises the number of trials; running 5× more epochs against a 6-dim space buys noise, not
  signal. 400 was chosen as "converged, not over-searched".
- Seed: `--random-state 42`, `-j 20`, `--timerange 20210101-20250630` (never beyond the data
  boundary).

## 7. Final parameter selection (epoch 303, not the raw argmax)

The hyperopt argmax was epoch 243 (objective 2.626: train Sharpe 0.246, valid 2.626). I
instead chose **epoch 303** (objective 2.559, within 3% of the max): train Sharpe **1.335**,
valid Sharpe **2.559**, and the *same* mom_window=9.

Reason: epoch 243's parameters produce almost no edge on 3.5 years of TRAIN (0.25 Sharpe) —
its entire objective comes from the validation year. That is the mirror image of the
train-good/valid-bad failure the exam penalises: a parameter set whose evidence base is one
segment. Epoch 303 is profitable in both segments (both long AND short books profitable in
both), which is the profile most likely to survive an unseen test period. I verified
robustness around the choice with perturbation backtests — neighbouring parameters
(mom 9→10/12, vol 39→30, buffer 0.24→0.34, n_short 4→5) all produce valid Sharpe 1.77–2.43,
so the choice sits on a plateau, not a spike.

## 8. Reported metrics and the Sharpe definition

All self-reported numbers use the objective's exact definition: daily PnL aggregated over the
segment ÷ starting wallet (10 000 USDT), non-trading days filled with 0, annualised ×√365.
Both segments were scored with standalone runs (flat 10k wallet at segment start). Every
reported figure is **net of costs** — the backtest charges the fixed 0.06%/side fee (which per
the config comment already bundles a slippage proxy on top of the ~0.045% taker fee) and
perp funding on held positions; hence `sharpe == sharpe_net_of_costs` and
`slippage_bps = 0` (nothing additional is modeled beyond the bundled fee).

## 9. On the objective itself

I think the provided objective is well-constructed for this exam: scoring on validation with
a train/valid gap penalty is a reasonable single-number proxy for out-of-sample
risk-adjusted return, and the daily-PnL Sharpe (rather than per-trade Sharpe) is the right
normalisation for overlapping books. One caveat I would note: the gap penalty is asymmetric —
it ignores valid ≫ train, so the loss quietly rewards parameter sets whose TRAIN edge is
small. That is exactly what the argmax epoch exploited (see §7), which is why I manually
selected a both-segments-strong point from the same trial set rather than taking the loss
argmax. If it were my choice I would add a small symmetric penalty on |train − valid| or a
floor on train Sharpe, to keep selection honest.

## 10. Files

- `strategies/XSRiskMom.py` — the strategy (scaffold subclass; factor + parameter ranges).
- `strategies/XSRiskMom.json` — Freqtrade parameter file with the final epoch-303 values.
- `strategies/metrics_from_result.py`, `strategies/eval_run.py` — working tools that compute
  the objective-consistent metrics from backtest zips (used for metrics.json).
- `config.json` — exam config + `_final_params` + `_seed` documentation keys.
- `hyperopt_results.json` — all 400 trials with train/valid Sharpe (via provided
  `export_hyperopt.py`).

# Design — XSMomVolDaily (model: qwen3_8_max)

## 1. Strategy family

**Cross-sectional long/short momentum** on a fixed 20-pair perpetual basket, built on
the provided `CrossSectionalBase` scaffold. Each day the universe is ranked by a
risk-adjusted momentum score; the top `n_long=7` names are held long, the bottom
`n_short=6` short (positions per pair ≈ wallet/20 ≈ 500 USDT at 1x leverage).
The portfolio is close to market-neutral by construction, so returns are driven by
the cross-sectional spread, not by crypto beta. Both sides are genuinely used
(TRAIN: 833 long / 819 short trades; VALIDATION: 254 / 257).

## 2. The factor and why

Per pair, at daily bar `t` (causal — only bars ≤ t):

```
mom   = close[t-skip] / close[t-skip-mom_window] - 1
rv    = rolling std of 1-bar returns over max(skip+mom_window, 20) bars
score = mom / rv
```

The scaffold then aligns scores across the 20 pairs and applies **shift(1)**: the
decision executed at bar t uses only the cross-section known at the close of t-1.

- **Momentum** — the best-documented cross-sectional anomaly in crypto at horizons
  of ~1-4 weeks (e.g. Liu/Tsyvinski/Wu, *Risks and Returns of Cryptocurrency*).
  TRAIN (2021 bull, 2022 bear, 2023-24 recovery) contains several distinct momentum
  regimes, which is what a hyperopt can actually learn from.
- **Skip = 2 days** — daily crypto returns exhibit 1-3 day reversal; skipping the
  newest bars keeps the medium-horizon momentum signal clean instead of blending it
  with the opposing short-term effect. (The search allowed skip 0-5 and picked 2.)
- **Volatility scaling** — dividing by realized volatility makes the score closer to
  a t-statistic on the momentum estimate, stabilises the cross-sectional ranking, and
  stops structurally high-vol names from dominating the ranking by noise. The vol
  window is floored at 20 bars so short momentum windows don't produce garbage vol
  estimates. Rank-based selection then makes only the ordering matter, which makes
  the factor robust to scale differences across pairs.
- **No funding-rate factor** — funding data exists but wiring it in adds pipeline
  risk and another overfitting surface for marginal expected gain; OHLCV-only keeps
  the design minimal. (Funding is still *charged* by the backtester — verified via
  the per-trade `funding_fees` field.)

## 3. Timeframe and turnover choices

- **Timeframe `1d`**. The documented momentum horizon is weekly; daily decisions are
  the lowest-cost frequency that can express it. Every round trip costs ≈ 0.12%, so
  frequency is a first-order cost decision: at the final parameters the average
  holding period is ~12 days and entry turnover is ~29-30x wallet per year, i.e.
  roughly 3.5%/year in fees — small against the ~2.3%/trade gross edge in VALIDATION.
- **Turnover control** (all hyperopted):
  - `exit_buffer = 0.07` — rank hysteresis: a name enters at the rank threshold but
    only exits once its rank falls 0.07 through it, avoiding ping-pong at the boundary.
  - `min_hold = 8` daily bars — no exit before 8 days held, capping churn.
  - The scaffold's shift(1) + once-daily decisions themselves bound turnover.
- **No stoploss / ROI** (`stoploss=-0.99`, `minimal_roi={"0": 100}` = both
  effectively off). Exits are signal-driven (rank deterioration). Tight daily stops
  whipsaw in crypto and would massively increase turnover; at 1x leverage there is no
  liquidation risk for longs and isolated-margin shorts cap their own loss. The
  observed tail is real and reported in self_assessment.md (a few squeezed shorts in
  TRAIN hit ≈ -95%).
- **Breadth 7 long / 6 short** — diversified enough that one coin cannot dominate
  the book, concentrated enough that the factor signal matters. The short side being
  one name smaller is what the optimizer chose and is defensible: both TRAIN and
  VALIDATION windows are net-bullish, which is a structural headwind for the short
  leg of any cross-sectional book.

## 4. Hyperopt: epochs used and why

- **300 epochs out of the 2000 budget**, `--spaces buy`, `-j 20`, provided loss
  `EP004ValidLoss`, timerange 20210101-20250630. Every trial is recorded in
  `hyperopt_results.json`.
- The search space is 6 small-range parameters (mom_window 5-30, skip 0-5,
  n_long/n_short 2-8, exit_buffer 0.05-0.35, min_hold 0-8). 300 TPE samples cover
  that space densely; pushing toward 2000 would mostly mine noise, and the Deflated
  Sharpe Ratio penalty grows with the trial count.
- Stopping at 300 is supported by the shape of the results: the top ~15 trials
  (loss 2.18-2.49) form a **plateau**, all with mom_window 13-14, skip 2-4,
  n_long 7-8, n_short 4-6, min_hold 6-8, buffer 0.05-0.27. The optimum is a wide
  basin, not a needle — further epochs would buy little expected generalisation.
- **Selection rule: minimum loss under the provided objective** → epoch 231
  (train_sharpe 0.298, valid_sharpe 2.489, loss -2.489; 1635 train / 520 valid trades).
  The chosen parameters are baked into the strategy class defaults and recorded in
  `config.json` (`_final_params`) so a plain `backtesting` run reproduces them.

## 5. Results (standalone runs, final parameters, net of 6 bps/side + funding)

| | TRAIN 2021-01..2024-06 | VALIDATION 2024-07..2025-06 |
|---|---|---|
| Ann. return | +7.3% | +62.5% |
| Sharpe (daily-PnL convention) | 0.29 | 2.25 |
| Max drawdown | 23.5% | 10.8% |
| Trades | 1652 | 511 |
| Profit factor | 1.05 | 1.42 |

The loss-function's own evaluation of the same parameters on the combined run was
train_sharpe 0.298 / valid_sharpe 2.489; the small difference vs the standalone
numbers is boundary state (positions carried across 2024-07-01 in the combined run).

## 6. Comments on the fixed objective (as invited by the task)

I used the provided objective unchanged, with two observations:

1. **The gap penalty is one-sided** (`max(0, train - valid)`). Trials where VALIDATION
   massively beats TRAIN are not penalised at all, yet that asymmetry is itself a
   regime-luck warning sign. My chosen trial (train 0.30 vs valid 2.49) is exactly
   such a case — flagged honestly in self_assessment.md. A symmetric penalty would
   have favoured e.g. epoch 125 (train 0.88 / valid 2.26). I kept the specified rule;
   silently switching would have been worse.
2. **Closed-trade-only Sharpe with zero-filled days** understates slow strategies
   (many zero-PnL days inflate the apparent stability denominator/numerator ratio in
   proportion to trade frequency), which quietly rewards higher turnover. I did not
   chase this artefact: the chosen frequency (daily) and turnover (~30x/year entry)
   are justified by the factor horizon and costs, not by the metric.

## 7. Cost realism

Fee fixed at 0.06%/side (unchanged in config.json). `slippage_bps` is reported as 0
because the scaffold's 6 bps/side already bundles taker fee (~4.5 bps) plus a
slippage proxy. `entry_pricing/exit_pricing = other` (order-book top) adds a further
conservative fill assumption. Funding is charged by the futures backtester on the
available funding-rate data (net received in VALIDATION: +95.9 USDT, since shorts
collect positive funding).

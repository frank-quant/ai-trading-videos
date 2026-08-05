# design.md — KimiK3XSTrend

## 1. Strategy family
**Cross-sectional momentum (trend) long/short** on the fixed 20-perp universe, built on the
provided `CrossSectionalBase` scaffold (which enforces the shift(1) anti-look-ahead alignment —
untouched). At every bar the strategy scores all 20 names, goes **long the top-N ranks and short
the bottom-N ranks**, with hysteresis-based exits. The book is roughly market-neutral by
construction: long and short legs are sized symmetrically by the scaffold's rank thresholds, so
the PnL is driven by the *cross-sectional spread*, not by market beta (the task explicitly warns
that market-beta returns will be identified as such).

Why cross-sectional momentum and not the other families — all decisions below were made on
**TRAIN (2021-01 .. 2024-06) data only** (validation was only ever read by the provided loss):

- Cross-sectional **short-term reversal** (1–10d) has genuinely positive rank IC (+0.02…+0.03 at
  3d) but the edge lives in the *middle* of the distribution, not the tails we trade: the
  top/bottom-quartile L/S spread of reversal factors is **negative** at 1–3d horizons, and any
  variant fast enough to capture reversal churns 200–500×/yr — at 0.12% per round trip that is a
  25–60%/yr fee drag. Dead on arrival under realistic costs.
- **Low-volatility** (`-realized vol`) has the strongest IC (+0.067, ICIR≈0.2) but a flat/negative
  traded spread — it is a level effect, not a tail effect, and adds nothing once traded.
- **Funding-rate** factor (long low-funding / short high-funding): its L/S spread is *negative*
  (-12bp/d) — high-funding names keep outperforming on price (funding is a momentum proxy), and
  Freqtrade backtesting does not credit funding cashflows, so the carry leg cannot even show up.
  Dropped; `funding_included=false`.
- **Momentum**: raw cross-sectional momentum has slightly negative rank IC at 1–60d, BUT the
  *traded tails* tell the right story: vol-normalized momentum's top-vs-bottom quartile spread is
  **+15…+21bp/day gross (spread-Sharpe 1.4–2.1), stable across all three TRAIN sub-periods**
  (+1.9/+0.8/+1.3). Momentum in crypto is a tail phenomenon (winners keep winning, losers keep
  losing); rank IC gets cancelled by mid-book noise. We trade tails, so we trade momentum.

## 2. Signals / factor construction (all causal, OHLCV-only)
`factor_score` = `(1-w)·tstat_mom(mom_fast) + w·mom(mom_slow)/vol(vol_win)`

- **Fast leg — t-stat momentum** (default 30d): mean/log-return over the window divided by its
  std, ×√window — a statistical "is this trend real" t-statistic. Vol-normalization makes scores
  comparable across a low-vol BTC and a high-vol DOGE, so cross-sectional ranks reflect signal
  quality, not beta.
- **Slow leg — vol-normalized momentum** (default 90d): plain 90d return divided by its realized
  vol. Captures the slow regime trend that the 30d leg misses; the two legs diversify each other
  (combo beat either leg alone in the cost-aware TRAIN sim: +1.27 vs +0.84 best single).
- Cross-sectional alignment, percentile ranking and the mandatory **shift(1)** are the scaffold's
  job; every rolling window uses current-and-past bars only. No full-sample normalization anywhere.

## 3. Timeframe & turnover control
**Timeframe: 1d.** Justified by an A/B on TRAIN with identical factor: 1d gave Sharpe 0.55 /
PF 1.18 / +42% vs 4h's 0.43 / 1.11 / +32.6% — the signal is slow (weeks), so 4h bars mostly added
noise flips and fee drag (traded volume 1.6× higher). Daily also shortens hyperopt trials 6×.
Fees are the central constraint (0.12%/round trip), and turnover control is the design:

- `exit_buffer` (hysteresis, 0–0.4): exit only when the rank leaves the threshold *by a margin* —
  kills threshold jitter. TRAIN sim: buffer 0.1→0.4 cuts turnover 300×→33×/yr while *raising* net
  Sharpe (0.84→1.27).
- `min_hold` (0–48 bars): minimum holding period, blocks fee-bleed flip-flops.
- `n_long`/`n_short` (1–10): book width — wider books diversify idiosyncratic risk.
- No stoploss/ROI exits: the rank exit *is* the risk control; hard stops fight a slow signal.
  Leverage fixed at 1.0 (rule; also pointless for a Sharpe objective).

## 4. Optimization
- Loss: provided `EP004ValidLoss` (unchanged) — fits on TRAIN+VALID, scores validation Sharpe
  with a 0.5×(train−valid) gap penalty. **No custom objective.**
- Space: 8 params, all in `buy` — `mom_fast(10–60)`, `mom_slow(60–180)`, `w_slow(0–1)`,
  `vol_win(5–40)`, `n_long/n_short(1–10)`, `exit_buffer(0–0.4)`, `min_hold(0–48)`.
- **Epochs: 400** of the allowed 2000, `--random-state 42` (fixed seed, recorded in config.json),
  `-j 20`. Rationale for stopping at 400: the search space is deliberately small (8 params,
  research-narrowed defaults), hyperopt's TPE converges well within a few hundred trials, and the
  deliverable is judged with a Deflated Sharpe Ratio that penalizes trial count — 400 epochs of a
  narrow, economically-motivated space is a conscious bias-variance choice, not a budget accident.
- Final parameters: **not** the raw best-loss epoch — a robustness pick from the top plateau
  (epoch 235; rule and evidence in §5), because the best-loss epoch was a negative-train/
  lucky-valid point (see §5 and self_assessment.md).

## 5. Final parameters & results
**Parameter selection rule.** The raw best-loss epoch (370: train −0.38 / valid 2.68) exploits
the fact that the loss only penalizes *positive* train→valid gaps: it loses money across 3.5
years of TRAIN and looks great on one trendy validation year — a regime-luck signature, the exact
overfitting pattern this task says is a failure. I therefore did **not** take the argmax. From the
400 trials I picked the config maximizing robustness across *both* segments inside a dense,
self-consistent parameter plateau (16 neighboring trials in `mom_slow 100–140, w_slow 0.6–1.0,
n 3–6/2–4, buffer 0.1–0.3` all score valid ≥ 1.1, mean 1.74):

- **epoch 235**: `mom_fast=12, mom_slow=127, w_slow=0.81, vol_win=36, n_long=5, n_short=3,
  exit_buffer=0.22, min_hold=1` — a ~4-month vol-normalized trend core with a 12-day t-stat
  fast leg (0.19 weight), a 5-long/3-short book, and hysteresis-driven exits.

Results (loss-convention: one combined 2021-01..2025-06 backtest, daily PnL / 10k starting
wallet, 0-filled days, √365 — identical to `hyperopt_results.json` epoch 235):

| segment | net Sharpe | gross Sharpe | Sortino | Calmar | maxDD | win% | PF | trades |
|---|---|---|---|---|---|---|---|---|
| TRAIN 2021-01..2024-06 | **0.82** | 0.85 | 0.92 | 1.37 | 11.9% | 46.8% | 1.41 | 357 |
| VALID 2024-07..2025-06 | **1.87** | 1.89 | 2.99 | 4.84 | 17.4% | 55.6% | 1.99 | 144 |

Standalone segment backtests (fresh 10k wallet each — what `run.md`'s per-segment commands
reproduce) give net Sharpe **0.96 train / 1.55 valid**: validation is *stronger* than training
under both conventions, i.e. no train→valid degradation. Both sides are traded throughout
(train: 174 long / 196 short; valid: 59 / 82). Fee drag is modest by design: ~11×/yr one-way
turnover on train ⇒ ≈1.3%/yr of fees against ≈16%/yr gross return.

Full per-trial data: `hyperopt_results.json` (400/400 trials scored). Metrics: `metrics.json`.

## 6. On the fixed objective
The objective (validation Sharpe − 0.5·gap) is a sound exam question: it is the same daily-PnL
Sharpe for everyone, it directly prices overfitting via the gap term, and the 50-trade validation
floor blocks degenerate "one lucky trade" solutions. If I could change one thing I would annualize
with the *actual deployed capital* rather than the full wallet (idle slots dilute the Sharpe of
narrow books vs wide books), but the wallet-based definition is what it is — and it is identical
for all candidates, so I optimized exactly what was asked and nothing else.

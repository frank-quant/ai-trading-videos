You are building a systematic trading strategy in Freqtrade. Work autonomously:
write the code, run backtests, read the results, and iterate until you are done.
FIRST read README_FOR_MODEL.md in your working directory — it describes this environment:
the provided scaffold, how to run backtests/hyperopt here, and where to put deliverables.

TASK
Build the best systematic trading strategy you can on a fixed basket of 20 crypto
perpetual futures, judged on out-of-sample risk-adjusted return.
**The strategy family is entirely your choice** — cross-sectional multi-factor,
trend following, mean reversion, breakout, regime switching, ensemble, whatever you
can justify. The ONE structural requirement is that it must be able to take BOTH
LONG and SHORT positions (this is a two-sided market; a long-only strategy is
disqualified). Market-neutrality is optional — a directional strategy is allowed,
but be aware that returns which are just market beta will be identified as such.

UNIVERSE
Use exactly this fixed list of 20 USDT-margined perpetuals (already in config.json):
BTC, ETH, SOL, BNB, XRP, DOGE, ADA, LINK, LTC, BCH,
AVAX, DOT, UNI, ATOM, NEAR, FIL, ETC, TRX, XLM, AAVE  (all as <SYM>/USDT:USDT).
Do NOT add or drop symbols based on how they perform — the universe is fixed in advance.

SIGNALS (fully your choice)
Whatever your strategy family, you decide the signals/indicators/rules and how they
combine, and you must justify each choice in design.md. For reference only: momentum,
reversal, realized volatility, volume/liquidity, breakout levels, regime filters.
Only OHLCV is wired up out of the box; funding-rate data exists in the data directory
but you would have to load it yourself — optional.

OPTIONAL SCAFFOLD (use it or ignore it)
If you choose a CROSS-SECTIONAL approach, `CrossSectionalBase`
(strategies/cross_sectional_base.py) saves you the plumbing: it aligns a per-pair
`factor_score` across the 20 pairs and applies shift(1) so a decision at bar t only uses
information known at t-1. It exposes `xs_score` / `xs_rank`, plus hyperoptable
`n_long` / `n_short` / `exit_buffer` / `min_hold`. Everything in it is a default you may
override. Worked example: strategies/ExampleXSMomentum.py.
**If you prefer a different strategy family, write a plain Freqtrade IStrategy from
scratch and ignore the scaffold entirely — that is fully allowed.** If you DO use the
scaffold, you must not weaken its shift(1) look-ahead protection.

YOUR DESIGN CHOICES (all free — justify them in design.md)
- STRATEGY FAMILY: cross-sectional, trend, mean-reversion, breakout, ensemble, ...
- TIMEFRAME: 30m, 1h, 4h or 1d — all four are downloaded and ready.
  Higher frequency means more signal but far more cost.
- ENTRY/EXIT, RISK MANAGEMENT, TURNOVER CONTROL, POSITION SIZING: yours.
- Factor / indicator design, search space: yours.

SIZING & LEVERAGE
**Leverage is fixed at 1x. Do NOT override `leverage()` to return anything above 1.0**
(Freqtrade's default already returns 1.0, so simply leave it alone). This is an exam
rule and it is checked — raising leverage is disqualifying. Note it would not help you
anyway: the objective is a Sharpe ratio, which is scale-invariant, so leverage adds
risk of ruin without improving your score.
The strategy must be able to go both long and short.

COSTS ARE THE CENTRAL CONSTRAINT
Fees are fixed at 0.06% per side (already in config.json) and must not be changed.
Every round trip costs ~0.12%. A strategy that rebalances aggressively will be
destroyed by transaction costs. Managing turnover is part of the problem.

OBJECTIVE
Maximize the ANNUALISED SHARPE on the VALIDATION period, while keeping the gap between
TRAIN and VALIDATION small. Sharpe here is defined precisely (and implemented in the
provided loss): daily PnL aggregated over the segment, divided by the starting wallet,
non-trading days filled with 0, annualised by sqrt(365). Use the SAME definition for any
Sharpe you self-report. The loss is  -(valid_sharpe - 0.5 * max(0, train_sharpe - valid_sharpe)).
A strategy that looks great on TRAIN but degrades on VALIDATION is a FAILURE.
Do not optimize toward, or read, any data outside TRAIN/VALIDATION.

OPTIMIZATION
Tune with Freqtrade Hyperopt. Budget: **up to 2000 epochs — you decide how many to
actually use.** Stopping early is a legitimate, and often correct, choice: over-searching
is over-fitting, and your results will be judged with a Deflated Sharpe Ratio that
penalises the number of trials you ran. State in design.md how many epochs you used
and why. Declare your parameters in the "buy" space. You MUST use the PROVIDED loss
`EP004ValidLoss` (it fits on TRAIN and scores on VALIDATION with a train/valid-gap penalty —
do NOT write your own objective). Use `-j 20`. Then run the provided `export_hyperopt.py`
to produce hyperopt_results.json. Record the final chosen parameters in config.json.
Exact commands are in README_FOR_MODEL.md.
The fixed objective is the exam question — it must be identical for all candidates. If you
think it is the wrong objective for this problem, say so in design.md and explain what you
would optimise instead; reasoned disagreement is credited, silently optimising something
else is not.

DATA BOUNDARY (hard)
You may ONLY use TRAIN (2021-01 .. 2024-06) and VALIDATION (2024-07 .. 2025-06).
No other data exists in this environment. Any attempt to reach outside this range
is disqualifying.

HARD REQUIREMENTS — violations are DISQUALIFYING
0. LONG AND SHORT. The strategy must be able to open both long and short positions
   (`can_short = True` and both sides actually used). Long-only is disqualified.
1. NO LOOK-AHEAD. Any value used to trade at time t must be computable using only
   information strictly before t. This includes any normalisation or ranking:
   means / stds / ranks / z-scores must never be computed over the full sample,
   and never over a cross-section that includes the future.
2. REALISTIC COSTS. The fee in config.json (0.06% per side) must not be lowered.
   At any rebalance frequency you choose, costs are material and must not be ignored —
   the higher your turnover, the more they matter.
3. FIXED UNIVERSE. All 20 pairs, fixed in advance. No performance-based selection.
4. DELIVER exactly the files listed under DELIVERABLES below — same names, nothing else.

DELIVERABLES — exact names, exact locations:
- strategies/<YourStrategy>.py : your strategy (must live in strategies/ so Freqtrade finds it)
and in the project root:
- config.json        : the exact Freqtrade config used (your final chosen parameters + seed)
- run.md             : the exact commands to reproduce your backtests (data download excluded)
- metrics.json       : your self-reported metrics, schema below, for TRAIN and VALIDATION ONLY
- hyperopt_results.json : EVERY hyperopt trial — its params + TRAIN score + VALIDATION score
- design.md          : your design — strategy family, signals/rules, timeframe &
                       turnover choices, epochs used, each with a short justification
- self_assessment.md : where your strategy is most at risk of overfitting or look-ahead, and why
Set and record a fixed random seed. Keep the project root clean — no other new top-level
files (working files inside strategies/ , hyperopt_results/ etc. are fine).

metrics.json — fill both "train" and "valid" with these EXACT keys:
{
  "model": "<name>", "seed": <int>, "factors": ["..."],
  "timeframe": "<30m|1h|4h|1d>", "epochs_used": <int>,
  "strategy_family": "<cross-sectional|trend|mean-reversion|...>",
  "turnover_control": "<describe your turnover control, or null>",
  "fee_bps": <num>, "slippage_bps": <num>, "funding_included": true,
  "train": { "ann_return": <num>, "sharpe": <num>, "sortino": <num>, "calmar": <num>,
             "max_drawdown": <num>, "win_rate": <num>, "profit_factor": <num>,
             "turnover_per_year": <num>, "n_trades": <int>, "sharpe_net_of_costs": <num> },
  "valid": { "ann_return": <num>, "sharpe": <num>, "sortino": <num>, "calmar": <num>,
             "max_drawdown": <num>, "win_rate": <num>, "profit_factor": <num>,
             "turnover_per_year": <num>, "n_trades": <int>, "sharpe_net_of_costs": <num> }
}

hyperopt_results.json — schema (one entry per epoch; produced by export_hyperopt.py):
{
  "model": "<name>", "n_epochs": <however many you actually ran>,
  "trials": [
    { "epoch": <int>, "params": { <your search-space params> },
      "train_sharpe": <num>, "valid_sharpe": <num> }
  ]
}

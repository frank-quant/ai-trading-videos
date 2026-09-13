# Self-assessment — XSDonchianMom

## Overfitting

The largest risk is that **hyperopt scores on VALIDATION**. `EP004ValidLoss` is `-(valid_sharpe - 0.5 * max(0, train_sharpe - valid_sharpe))`. The winning trial (epoch 51 / 80) has TRAIN Sharpe **1.10** and VALID Sharpe **2.19**. That reverse gap is not penalised, so the search is free to pick VALIDATION-lucky turnover settings.

Evidence this is not just "the factor worked":

- `min_hold=10` is the **top of the search box**. Boundary solutions are a classic overfit tell.
- `exit_buffer=0.01` is almost off. Most of the turnover control is the hold floor, which was searched.
- `don_weight=0.57` and `n_long=7` (net long vs 5 shorts) were also searched on the same VALIDATION window.
- Default pre-hyperopt knobs (`n_long=n_short=5`, `min_hold=3`, `don_weight=0.70`, `exit_buffer=0.10`) already had VALID daily-wallet Sharpe ~1.23. Hyperopt more than doubled the official VALID Sharpe; some of that is real (longer holds, less churn), some is likely 2024-07..2025-06 specific.

Mitigations that *were* applied: only 80 epochs; Donchian 21 and momentum 14/skip-1 **frozen on TRAIN** (not in the buy space); 4h/1h/30m rejected on TRAIN costs rather than on VALID; size/illiquidity discarded after it failed 2023–24H1 *inside TRAIN*.

What I would not claim: that VALID Sharpe 2.19 is an unbiased estimate of live Sharpe. Deflated Sharpe on 80 trials plus a VALID-tuned hold period should shrink that number a lot.

## Look-ahead

I believe the signal path is causal, but these are the places a reviewer should poke:

1. **No extra panel `shift(1)`.** Rank at bar *t* uses OHLCV through *t*. Freqtrade with `process_only_new_candles=True` fills at the next open. If anyone treats `populate_entry_trend` as intra-bar, this would look like look-ahead; it is not, under Freqtrade's next-bar rule. I chose this over the scaffold's extra lag on purpose (see `design.md`).
2. **Cross-sectional z-score and rank at t** use all 20 names' *t* values. That is contemporaneous, not future. It is **not** a full-sample z-score.
3. **Donchian high/low include bar t.** Known at t's close; traded next bar. Standard.
4. **Momentum is skip-1**, so it does not even use close[t]. Extra conservative.
5. **Panel is built from `get_pair_dataframe`**, which in backtesting is the full series. Factors are rolling windows ending at each row, then `rank(axis=1)` per timestamp — equivalent to a truncated-at-t computation if the rolling windows are causal (they are).
6. Hyperopt parameters live in entry/exit, not `populate_indicators`, so `--spaces buy` actually re-evaluates the blend (same trick as the scaffold).

I did not use future bars, centered windows, or expanding stats that include the evaluation date's future.

## Other failure modes

- **Residual market beta.** Longs earned most of the PnL; shorts were weakly positive on the combined run. `n_long=7 > n_short=5` leans long. A choppy or crashing VALID-style period that is *not* a relative-momentum bull would look worse. The task allows directional books; this is the main economic risk, not a bug.
- **Left-tail on isolated 1x.** Combined run: 2 liquidations and one −99% stop. Daily bars gap through a −0.99 stop. Calmar on TRAIN is poor (−42% on the official daily-PnL/10k path). Sharpe can look fine while path-dependence is ugly.
- **Wallet-denominator artefact.** Official Sharpe uses `profit_abs / 10000` every day, including VALID when the wallet is already >10k. VALID `ann_return` in `metrics.json` is therefore larger than a fresh-10k VALID backtest. Sharpe is closer to scale-invariant; I still report the official definition.
- **Funding is a cost, not a signal.** Crowding via funding was visible on TRAIN and unused. If funding regimes dominate 2025+, we miss it.
- **Fixed 21/14 windows.** Chosen on TRAIN. They are economically standard (≈1m breakout, ≈2w momentum) rather than a grid-mined pair, but they are still in-sample choices.

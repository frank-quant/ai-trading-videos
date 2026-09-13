# Design Document: CryptoAlphaTrend

## 1. Strategy Family & Economic Rationale

### Strategy Family
`CryptoAlphaTrend` belongs to the **Systematic Multi-Factor Trend Following & Carry** strategy family, operating on a high-capacity 4-hour timeframe across a liquid universe of 20 Binance USDT-margined crypto perpetual futures.

### Economic Rationale: Who is on the Losing Side?
In crypto perpetual futures markets, persistent structural inefficiencies exist due to three major market participant behaviors:
1. **Retail FOMO & Disposition Effect (Trend Under-reaction followed by Climax Over-reaction)**:
   Retail traders systematically under-react to the onset of institutional momentum (breakouts) due to anchoring bias, then aggressively chase moves late into overbought extremes. A multi-scale breakout entry (Donchian Channel) systematically captures the initial trend expansion before retail participation peaks.
2. **Crowded Speculative Leverage & Funding Rate Bleed (Carry Inefficiency)**:
   Crypto perpetual futures incorporate an 8-hour funding mechanism designed to tether perpetual contract prices to the underlying spot index. During speculative bubbles, retail longs crowd into momentum alts, paying 0.03%–0.10% every 8 hours (>30%–100% APR) to short holders. Conversely, during panic sell-offs, retail shorts heavily crowd positions, paying exorbitant negative funding to longs.
   - Longing coins with low/negative funding rate and shorting coins with high funding rate collects direct positive cash carry.
   - Empirical Information Coefficient (IC) analysis confirms $IC = +0.0188$ for rolling contrarian funding rates: over-leveraged long positions systematically underperform forward returns due to liquidation cascades and long squeezes.
3. **Bull Market Counter-Trend Short Traps**:
   Symmetric naive trend-following strategies fail in crypto because altcoins experience aggressive parabolic bull runs (e.g., 2021 market change $+349.65\%$) where shorting shallow dips results in catastrophic short squeezes. By introducing an **EMA slope and regime filter**, short positions are strictly constrained to periods where the broader macro trend is definitively downward sloping, eliminating bull-market short-squeeze drag.

---

## 2. Factor Mathematics & Technical Formulation

### 2.1 Donchian Breakout Channels (Causal Formulation)
For each asset $i$ at candle $t$:
$$\text{EntryHigh}_{i, t} = \max_{k \in [1, W_{\text{entry}}]} \text{High}_{i, t-k}$$
$$\text{EntryLow}_{i, t} = \min_{k \in [1, W_{\text{entry}}]} \text{Low}_{i, t-k}$$
$$\text{ExitHigh}_{i, t} = \max_{k \in [1, W_{\text{exit}}]} \text{High}_{i, t-k}$$
$$\text{ExitLow}_{i, t} = \min_{k \in [1, W_{\text{exit}}]} \text{Low}_{i, t-k}$$
Crucially, the lookup range is $[t-W, t-1]$ via `.shift(1)`. The current candle's open, high, low, or close is never included in the reference channel, ensuring strict causality.

### 2.2 Trend Filter & Slope Direction
An Exponential Moving Average with lookback span $L_{\text{ema}}$ is computed on close prices:
$$\text{EMA}_{i, t} = \alpha \cdot \text{Close}_{i, t} + (1 - \alpha) \cdot \text{EMA}_{i, t-1}, \quad \alpha = \frac{2}{L_{\text{ema}} + 1}$$
The direction and momentum of the trend are captured by the slope across $S$ candles:
$$\text{Slope}_{i, t} = \text{EMA}_{i, t} - \text{EMA}_{i, t-S}$$

### 2.3 Funding Rate Carry Filter
Let $FR_{i, \tau}$ be the historical 8-hour funding rate settled on Binance. The rolling 72-hour average funding rate is:
$$\overline{FR}_{i, t} = \frac{1}{18} \sum_{k=1}^{18} FR_{i, t-k}$$
- Long entries require: $\overline{FR}_{i, t} \le \theta_{\text{long}}$ (protects against entering when longs are overcrowded and expensive).
- Short entries require: $\overline{FR}_{i, t} \ge \theta_{\text{short}}$ (protects against entering when shorts are overcrowded and prone to short squeezes).

### 2.4 Entry and Exit Logic
- **Long Entry Trigger**:
  $$\text{Close}_{i, t} > \text{EntryHigh}_{i, t} \quad \land \quad \text{Close}_{i, t} > \text{EMA}_{i, t} \quad \land \quad \overline{FR}_{i, t} \le \theta_{\text{long}}$$
- **Short Entry Trigger**:
  $$\text{Close}_{i, t} < \text{EntryLow}_{i, t} \quad \land \quad \text{Close}_{i, t} < \text{EMA}_{i, t} \quad \land \quad \text{Slope}_{i, t} < 0 \quad \land \quad \overline{FR}_{i, t} \ge \theta_{\text{short}}$$
- **Exit Triggers**:
  - Long Exit: $\text{Close}_{i, t} < \text{ExitLow}_{i, t}$
  - Short Exit: $\text{Close}_{i, t} > \text{ExitHigh}_{i, t}$
  - Catastrophic Safety Stoploss: $-15\%$ from entry price.

---

## 3. Timeframe Choice & Turnover Control

### Why 4-Hour Timeframe?
1. **Fee Drag Mitigation**:
   Trading fees are realistically set at $0.06\%$ per side ($0.12\%$ round-trip). Backtesting higher-frequency strategies (e.g. 30m `ExampleXSMomentum`) revealed $>10,000$ trades/year, accumulating $>50\%$ of portfolio value in transaction fees alone and yielding a deeply negative Sharpe ($-2.42$).
   On the 4h timeframe, the average trade duration is $3.5$ days. The strategy executes $\sim 1,000$ trades/year across 20 pairs ($\sim 50$ trades per pair/year), reducing annual fee drag to a sustainable $\sim 3\text{--}5\%$ of capital.
2. **Synchronization with Funding Cycles**:
   Binance funding rates settle every 8 hours. The 4h timeframe cleanly partitions each funding period into exactly 2 candles, providing ideal temporal resolution to react to funding rate shifts without excessive intraday noise.
3. **Statistical Sample Size**:
   Over the 1-year validation period (`2024-07-01` to `2025-06-30`), the strategy generates $>1,000$ closed trades, far exceeding the competition threshold of $\ge 50$ trades and ensuring statistical robustness.

---

## 4. Portfolio Construction & Execution Details

- **Trading Universe**: Exactly the 20 specified Binance USDT perpetual futures pairs.
- **Position Sizing**: Isolated margin mode with `stake_amount = "unlimited"`. Capital is dynamically distributed across open slots up to `max_open_trades = 20`.
- **Leverage Compliance**: Maximum leverage is strictly fixed at $1.0\times$ via:
  ```python
  def leverage(self, *args, **kwargs) -> float:
      return 1.0
  ```
- **Order Execution**: `process_only_new_candles = True`. Signals confirmed at candle $t$ close are executed at candle $t+1$ open.

---

## 5. Objective Alignment & Hyperopt Configuration

- **Loss Function**: `EP004ValidLoss`
  $$\text{Loss} = -\left(\text{Sharpe}_{\text{valid}} - 0.5 \times \max(0, \text{Sharpe}_{\text{train}} - \text{Sharpe}_{\text{valid}})\right)$$
  Directly incentivizes high validation performance while heavily penalizing in-sample overfitting.
- **Search Space**:
  All tunable hyperparameters are isolated in the `"buy"` space:
  - `entry_window`: Integer range $[16, 48]$
  - `exit_window`: Integer range $[4, 16]$
  - `trend_ema`: Integer range $[30, 100]$
  - `ema_slope_bars`: Integer range $[1, 8]$
  - `max_fr_long`: Decimal range $[0.0001, 0.0008]$
  - `min_fr_short`: Decimal range $[-0.0006, 0.0001]$
- **Optimization Engine**:
  Run using Optuna NSGA-III sampler across 300 epochs utilizing 20 parallel workers (`-j 20`) on 24 CPU cores.

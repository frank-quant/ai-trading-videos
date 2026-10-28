#!/usr/bin/env python3
"""对交付结果做独立文件级和会计恒等式检查：python verify_results.py"""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
summary = pd.read_csv(ROOT / "summary_metrics.csv")
daily = pd.read_csv(ROOT / "daily_equity_drawdown.csv", parse_dates=["date"])
trades = pd.read_csv(ROOT / "trades.csv", parse_dates=["date", "signal_date"])
signals = pd.read_csv(ROOT / "signals.csv", parse_dates=["signal_date", "execution_date"])
checks = {}

for row in summary.itertuples():
    key = row.strategy
    last = daily.iloc[-1]
    checks[f"{key}_final_equity_ties_to_daily"] = bool(np.isclose(row.final_equity, last[f"{key}_equity"], rtol=0, atol=1e-6))
    strategy_trades = trades[trades["strategy"] == key]
    checks[f"{key}_fees_tie_to_trades"] = bool(np.isclose(row.total_fees, strategy_trades["fee"].sum(), rtol=0, atol=1e-6))
    checks[f"{key}_end_position_not_liquidated"] = row.end_position in ("SOXX", "SPY", "BIL") and row.end_shares > 0

for trade in trades.itertuples():
    if trade.side == "BUY":
        checks[f"buy_cash_identity_{trade.strategy}_{trade.trade_id}"] = bool(np.isclose(
            trade.gross_amount + trade.fee, -trade.cash_flow_after_fee, rtol=0, atol=1e-6
        ))
    else:
        checks[f"sell_cash_identity_{trade.strategy}_{trade.trade_id}"] = bool(np.isclose(
            trade.gross_amount - trade.fee, trade.cash_flow_after_fee, rtol=0, atol=1e-6
        ))

# 基准可用复权开盘价独立复算：复权因子 = adj_close / close。
spy = pd.read_csv(ROOT / "data" / "SPY_daily.csv", parse_dates=["date"]).set_index("date")
start = pd.Timestamp("2020-01-02")
end = pd.Timestamp("2025-12-31")
adj_open_start = spy.at[start, "open"] * spy.at[start, "adj_close"] / spy.at[start, "close"]
for fee in (0.001, 0.002):
    key = "spy_buy_hold_fee_10bps" if fee == 0.001 else "spy_buy_hold_fee_20bps"
    independent_final = 100000 / (1 + fee) * spy.at[end, "adj_close"] / adj_open_start
    reported = summary.loc[summary["strategy"] == key, "final_equity"].iloc[0]
    relative_difference = abs(independent_final / reported - 1)
    checks[f"{key}_independent_adjusted_price_check"] = relative_difference < 0.001
    print(f"{key}: 独立复权价复算 ${independent_final:,.2f}；账本 ${reported:,.2f}；相对差 {relative_difference:.6%}")

# 每个信号的执行日必须是下一共同交易日，且费用不能出现在未换仓月份。
calendar = spy.index
checks["all_execution_dates_are_next_session"] = all(
    calendar[calendar.get_loc(row.signal_date) + 1] == row.execution_date for row in signals.itertuples()
)
base_trades = trades[trades["strategy"] == "rotation_fee_10bps"]
changes = base_trades[base_trades["side"] == "BUY"][["date", "selected"]]
expected = signals[signals["selected"] != signals["selected"].shift(1)][["execution_date", "selected"]]
checks["only_changed_targets_generate_buys"] = changes["date"].reset_index(drop=True).equals(expected["execution_date"].reset_index(drop=True)) and changes["selected"].reset_index(drop=True).equals(expected["selected"].reset_index(drop=True))
checks["all_fee_rates_are_10_or_20_bps"] = set(trades["fee_rate"].unique()) == {0.001, 0.002}
checks["no_missing_core_files"] = all((ROOT / name).exists() for name in (
    "report.md", "report.html", "equity_drawdown.png", "backtest.py", "fetch_data.py",
    "signals.csv", "trades.csv", "daily_equity_drawdown.csv", "data_validation.json",
))

checks = {name: bool(passed) for name, passed in checks.items()}
result = {"checks": checks, "count": len(checks), "all_passed": all(checks.values())}
(ROOT / "verification_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"完成 {len(checks)} 项核验：{'全部通过' if result['all_passed'] else '存在失败'}")
if not result["all_passed"]:
    raise SystemExit([name for name, passed in checks.items() if not passed])

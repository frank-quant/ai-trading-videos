# -*- coding: utf-8 -*-
"""Working tool: build the metrics.json blocks from a backtest result file.

Sharpe/Sortino use the EXACT objective definition from EP004ValidLoss:
daily PnL / starting wallet, zero-filled non-trading days, sqrt(365) annualised.
Everything is net of costs (0.06%/side taker fee + funding), because the
backtest that produced these numbers already charged them.

Usage:
  python strategies/metrics_from_result.py <result.zip> <label train|valid> <start> <end>
"""
import json
import sys
import zipfile

import numpy as np
import pandas as pd


def load_result(path, strat=None):
    if path.endswith(".zip"):
        z = zipfile.ZipFile(path)
        name = [n for n in z.namelist()
                if n.endswith(".json") and "meta" not in n and "config" not in n][0]
        data = json.load(z.open(name))
    else:
        data = json.load(open(path))
    strats = data["strategy"]
    name = strat or list(strats.keys())[0]
    return name, strats[name], pd.DataFrame(strats[name]["trades"])


def daily_returns(trades: pd.DataFrame, start, end, capital: float) -> pd.Series:
    pnl = pd.to_numeric(trades["profit_abs"], errors="coerce").fillna(0.0)
    day = pd.to_datetime(trades["close_date"], utc=True).dt.floor("D")
    daily = pnl.groupby(day).sum() / capital
    idx = pd.date_range(start, end, freq="D", tz="UTC")
    return daily.reindex(idx, fill_value=0.0)


def sharpe(daily: pd.Series) -> float:
    sd = float(daily.std())
    if len(daily) < 30 or sd == 0:
        return 0.0
    return float(daily.mean() / sd * np.sqrt(365.0))


def sortino(daily: pd.Series) -> float:
    downside = daily[daily < 0]
    dd = float(np.sqrt((downside ** 2).sum() / len(daily)))
    if len(daily) < 30 or dd == 0:
        return 0.0
    return float(daily.mean() / dd * np.sqrt(365.0))


def main():
    path, label, start, end = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    strat = sys.argv[5] if len(sys.argv) > 5 else None
    name, res, trades = load_result(path, strat)
    start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    capital = 10000.0
    daily = daily_returns(trades, start_ts, end_ts, capital)
    n_days = len(daily)
    total_profit = float(trades["profit_abs"].sum())
    final_bal = capital + total_profit
    ann_return = (final_bal / capital) ** (365.0 / n_days) - 1.0

    # equity curve on daily granularity -> max drawdown (relative)
    equity = capital * (1.0 + daily.cumsum())
    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_dd = float(dd.min())

    wins = int((trades["profit_abs"] > 0).sum())
    n_trades = int(len(trades))
    win_rate = wins / n_trades if n_trades else 0.0
    gross_win = float(trades.loc[trades["profit_abs"] > 0, "profit_abs"].sum())
    gross_loss = float(-trades.loc[trades["profit_abs"] <= 0, "profit_abs"].sum())
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")

    years = n_days / 365.0
    entry_notional = float(trades["stake_amount"].sum())
    turnover_per_year = entry_notional / capital / years

    s = sharpe(daily)
    so = sortino(daily)
    calmar = ann_return / abs(max_dd) if max_dd != 0 else float("inf")

    block = {
        "ann_return": round(ann_return, 4),
        "sharpe": round(s, 4),
        "sortino": round(so, 4),
        "calmar": round(calmar, 4),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "turnover_per_year": round(turnover_per_year, 4),
        "n_trades": n_trades,
        "sharpe_net_of_costs": round(s, 4),
    }
    print(json.dumps({label: block}, indent=2))


if __name__ == "__main__":
    main()

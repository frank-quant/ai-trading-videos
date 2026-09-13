# -*- coding: utf-8 -*-
"""Working tool: evaluate a backtest-result zip with the EXACT objective definition
of EP004ValidLoss (daily PnL / starting wallet, zero-filled days, sqrt(365)).
Usage (inside container):
  python /freqtrade/user_data/strategies/eval_run.py <zip-or-json> [strategy_name]
"""
import glob
import json
import os
import sys
import zipfile

import numpy as np
import pandas as pd

TRAIN_START = pd.Timestamp("2021-01-01", tz="UTC")
VALID_START = pd.Timestamp("2024-07-01", tz="UTC")
VALID_END = pd.Timestamp("2025-06-30", tz="UTC")


def sharpe_daily(seg, start, end, capital):
    if seg is None or len(seg) == 0 or capital <= 0:
        return 0.0
    pnl = pd.to_numeric(seg["profit_abs"], errors="coerce").fillna(0.0)
    day = pd.to_datetime(seg["close_date"], utc=True).dt.floor("D")
    daily = pnl.groupby(day).sum() / capital
    idx = pd.date_range(start, end, freq="D", tz="UTC")
    daily = daily.reindex(idx, fill_value=0.0)
    sd = float(daily.std())
    if len(daily) < 30 or sd == 0:
        return 0.0
    return float(daily.mean() / sd * np.sqrt(365.0))


def load_trades(path, strat=None):
    if path.endswith(".zip"):
        z = zipfile.ZipFile(path)
        name = [n for n in z.namelist() if n.endswith(".json") and "meta" not in n and "config" not in n][0]
        data = json.load(z.open(name))
    else:
        data = json.load(open(path))
    strats = data["strategy"]
    name = strat or list(strats.keys())[0]
    return name, pd.DataFrame(strats[name]["trades"]), strats[name]


def main():
    path = sys.argv[1]
    strat = sys.argv[2] if len(sys.argv) > 2 else None
    name, df, res = load_trades(path, strat)
    cd = pd.to_datetime(df["close_date"], utc=True)
    train = df.loc[cd < VALID_START]
    valid = df.loc[(cd >= VALID_START) & (cd <= VALID_END)]
    cap = 10000.0
    ts = sharpe_daily(train, TRAIN_START, VALID_START, cap)
    vs = sharpe_daily(valid, VALID_START, VALID_END, cap)
    gap = max(0.0, ts - vs)
    # extra diagnostics
    for label, seg in (("train", train), ("valid", valid)):
        daily_ret = pd.to_numeric(seg["profit_abs"]).groupby(
            pd.to_datetime(seg["close_date"], utc=True).dt.floor("D")).sum() / cap
        n_days = len(seg)
        fees = (seg["fee_open"] * seg["stake_amount"] + seg["fee_close"] * seg["stake_amount"]).sum()
        print(f"[{label}] trades={n_days} gross_profit={seg['profit_abs'].sum():.0f} "
              f"fees~={fees:.0f} funding={seg['funding_fees'].sum():.0f}")
    print(f"train_sharpe={ts:.4f} valid_sharpe={vs:.4f} gap={gap:.4f} "
          f"objective={vs - 0.5 * gap:.4f}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Working file (not a deliverable): compute EP004-definition metrics from an
exported Freqtrade backtest, for TRAIN and VALIDATION separately.

Sharpe is EXACTLY the loss's definition: daily realised PnL / starting wallet,
non-trading days filled with 0, annualised by sqrt(365).

  docker run --rm --entrypoint python -v "${PWD}:/freqtrade/user_data" \
      freqtradeorg/freqtrade:stable /freqtrade/user_data/strategies/_ep004_metrics.py
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

TRAIN_S = pd.Timestamp("2021-01-01", tz="UTC")
VALID_S = pd.Timestamp("2024-07-01", tz="UTC")
VALID_E = pd.Timestamp("2025-06-30", tz="UTC")
CAP = 10000.0


def daily(seg, start, end):
    idx = pd.date_range(start, end, freq="D", tz="UTC")
    if len(seg) == 0:
        return pd.Series(0.0, index=idx)
    pnl = pd.to_numeric(seg["profit_abs"], errors="coerce").fillna(0.0)
    day = pd.to_datetime(seg["close_date"], utc=True).dt.floor("D")
    return (pnl.groupby(day).sum() / CAP).reindex(idx, fill_value=0.0)


def stats(seg, start, end, label):
    d = daily(seg, start, end)
    yrs = len(d) / 365.0
    sd = float(d.std())
    sharpe = float(d.mean() / sd * np.sqrt(365.0)) if sd > 0 else 0.0
    dn = d[d < 0]
    sortino = float(d.mean() / dn.std() * np.sqrt(365.0)) if len(dn) and dn.std() > 0 else 0.0
    eq = d.cumsum()
    mdd = float((eq.cummax() - eq).max())
    ann = float(d.sum() / yrs)
    calmar = ann / mdd if mdd > 0 else 0.0
    p = pd.to_numeric(seg["profit_abs"], errors="coerce").fillna(0.0) if len(seg) else pd.Series(dtype=float)
    win = float((p > 0).mean()) if len(p) else 0.0
    gp, gl = float(p[p > 0].sum()), float(-p[p < 0].sum())
    pf = gp / gl if gl > 0 else float("inf")
    vol = float(pd.to_numeric(seg["stake_amount"], errors="coerce").fillna(0.0).sum()) if len(seg) else 0.0
    return dict(label=label, ann_return=round(ann, 4), sharpe=round(sharpe, 4),
                sortino=round(sortino, 4), calmar=round(calmar, 4),
                max_drawdown=round(mdd, 4), win_rate=round(win, 4),
                profit_factor=round(pf, 4),
                turnover_per_year=round(2.0 * vol / CAP / yrs, 2),
                n_trades=int(len(seg)),
                n_long=int((~seg["is_short"]).sum()) if len(seg) else 0,
                n_short=int(seg["is_short"].sum()) if len(seg) else 0)


def load_latest(userdir="/freqtrade/user_data"):
    files = sorted(glob.glob(os.path.join(userdir, "backtest_results", "*.zip"))
                   + [f for f in glob.glob(os.path.join(userdir, "backtest_results", "*.json"))
                      if "last_result" not in f and ".meta." not in f],
                   key=os.path.getmtime)
    if not files:
        sys.exit("no backtest results found")
    from freqtrade.data.btanalysis import load_backtest_data
    return load_backtest_data(files[-1]), files[-1]


if __name__ == "__main__":
    userdir = sys.argv[1] if len(sys.argv) > 1 else "/freqtrade/user_data"
    df, src = load_latest(userdir)
    df["close_date"] = pd.to_datetime(df["close_date"], utc=True)
    cd = df["close_date"]
    out = {"source": os.path.basename(src),
           "train": stats(df.loc[cd < VALID_S], TRAIN_S, VALID_S, "train"),
           "valid": stats(df.loc[(cd >= VALID_S) & (cd <= VALID_E)], VALID_S, VALID_E, "valid")}
    if "exit_reason" in df:
        out["exit_reasons"] = df["exit_reason"].value_counts().to_dict()
    print(json.dumps(out, indent=2, default=str))

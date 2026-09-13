# -*- coding: utf-8 -*-
"""Working file (not a deliverable): EP004-definition Sharpe per calendar year and
per TRAIN sub-period, from the final exported backtest."""
import sys

import numpy as np
import pandas as pd

from _ep004_metrics import CAP, TRAIN_S, VALID_S, VALID_E, load_latest

df, src = load_latest(sys.argv[1] if len(sys.argv) > 1 else "/freqtrade/user_data")
df["close_date"] = pd.to_datetime(df["close_date"], utc=True)


def sharpe(a, b):
    seg = df.loc[(df["close_date"] >= a) & (df["close_date"] < b)]
    idx = pd.date_range(a, b, freq="D", tz="UTC")
    d = (pd.to_numeric(seg["profit_abs"], errors="coerce").fillna(0.0)
         .groupby(seg["close_date"].dt.floor("D")).sum() / CAP).reindex(idx, fill_value=0.0)
    sd = float(d.std())
    return (0.0 if sd == 0 else float(d.mean() / sd * np.sqrt(365.0))), len(seg), float(d.sum())


print(f"source: {src}\n")
print("--- four equal TRAIN sub-periods ---")
e = pd.date_range(TRAIN_S, VALID_S, periods=5).floor("D")
subs = []
for i in range(4):
    s, n, p = sharpe(e[i], e[i + 1])
    subs.append(s)
    print(f"  {e[i].date()} .. {e[i+1].date()}  sharpe={s:6.3f}  trades={n:4d}  pnl={p*100:7.2f}%")
print(f"  worst={min(subs):.3f}  mean={np.mean(subs):.3f}")

print("\n--- calendar years ---")
for y in range(2021, 2026):
    a = max(pd.Timestamp(f"{y}-01-01", tz="UTC"), TRAIN_S)
    b = min(pd.Timestamp(f"{y+1}-01-01", tz="UTC"), VALID_E)
    if a >= b:
        continue
    s, n, p = sharpe(a, b)
    print(f"  {y}: sharpe={s:6.3f}  trades={n:4d}  pnl={p*100:7.2f}%")

print("\n--- long vs short split ---")
for lbl, a, b in (("train", TRAIN_S, VALID_S), ("valid", VALID_S, VALID_E)):
    seg = df.loc[(df["close_date"] >= a) & (df["close_date"] < b)]
    for side, m in (("long", ~seg["is_short"]), ("short", seg["is_short"])):
        p = pd.to_numeric(seg.loc[m, "profit_abs"], errors="coerce").fillna(0.0)
        print(f"  {lbl} {side:5s}: n={int(m.sum()):4d}  pnl={p.sum()/CAP*100:7.2f}%  "
              f"win={float((p>0).mean())*100:5.1f}%")

print("\n--- leverage sanity (must be 1.0) ---")
print(f"  leverage: min={df['leverage'].min()} max={df['leverage'].max()}")
print(f"  funding fees total: {float(df['funding_fees'].sum()):.2f} USDT")

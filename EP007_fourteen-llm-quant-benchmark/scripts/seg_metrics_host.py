# -*- coding: utf-8 -*-
"""分段指标(EP004ValidLoss 口径) —— 主机版,可指定文件。

⚠️ 为什么需要它:模型自报的 sharpe 用的是**考题定义**(每日已实现盈亏按 close_date 归集
   / 初始资金,无交易日补 0,×sqrt(365)),而 Freqtrade 输出的 `Sharpe (daily wallet balance)`
   是**逐日盯市**口径。同一本账两者能差 0.4~0.6 夏普。
   → 要查「自报 vs 复现」有没有虚报,必须用本脚本,不能拿 daily wallet balance 去比。
   (EP004 报告的表现分用的是 daily wallet balance,那是另一件事,两套并行不冲突。)

EP004 原版 `_verify/seg_metrics.py` 只吃目录里最新的 zip,没法指定文件;本版加了 --trades。

用法:
  python seg_metrics_host.py --trades <path\\to\\valid.zip> --start 2024-07-01 --end 2025-06-30 --label valid
"""
import argparse, json, os, zipfile
import numpy as np
import pandas as pd


def load_trades(z):
    with zipfile.ZipFile(z) as f:
        for n in f.namelist():
            if n.endswith(".json") and "_config" not in n:
                o = json.loads(f.read(n))
                for v in o.get("strategy", {}).values():
                    if v.get("trades"):
                        return pd.DataFrame(v["trades"])
    raise SystemExit(f"{z} 里没找到 trades")


def stats(seg, start, end, cap):
    idx = pd.date_range(start, end, freq="D", tz="UTC")
    if len(seg) == 0:
        d = pd.Series(0.0, index=idx)
    else:
        pnl = pd.to_numeric(seg["profit_abs"], errors="coerce").fillna(0.0)
        day = pd.to_datetime(seg["close_date"], utc=True).dt.floor("D")
        d = (pnl.groupby(day).sum() / cap).reindex(idx, fill_value=0.0)

    yrs = len(d) / 365.0
    sd = float(d.std())
    sharpe = float(d.mean() / sd * np.sqrt(365.0)) if sd > 0 else 0.0
    dn = d[d < 0]
    sortino = float(d.mean() / dn.std() * np.sqrt(365.0)) if len(dn) and dn.std() > 0 else 0.0
    eq = d.cumsum()
    mdd = float((eq.cummax() - eq).max())
    ann = float(d.sum() / yrs)

    p = (pd.to_numeric(seg["profit_abs"], errors="coerce").fillna(0.0)
         if len(seg) else pd.Series(dtype=float))
    gp, gl = float(p[p > 0].sum()), float(-p[p < 0].sum())
    vol = (float(pd.to_numeric(seg["stake_amount"], errors="coerce").fillna(0.0).sum())
           if len(seg) else 0.0)
    return dict(
        ann_return=round(ann, 4), sharpe=round(sharpe, 4), sortino=round(sortino, 4),
        calmar=round(ann / mdd, 4) if mdd > 0 else 0.0, max_drawdown=round(mdd, 4),
        win_rate=round(float((p > 0).mean()), 4) if len(p) else 0.0,
        profit_factor=round(gp / gl, 4) if gl > 0 else None,
        turnover_per_year=round(2.0 * vol / cap / yrs, 2),
        n_trades=int(len(seg)),
        n_long=int((~seg["is_short"]).sum()) if len(seg) else 0,
        n_short=int(seg["is_short"].sum()) if len(seg) else 0,
        pnl_long=round(float(p[~seg["is_short"]].sum()), 2) if len(seg) else 0.0,
        pnl_short=round(float(p[seg["is_short"]].sum()), 2) if len(seg) else 0.0,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--label", default="test")
    ap.add_argument("--capital", type=float, default=10000.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    start, end = pd.Timestamp(a.start, tz="UTC"), pd.Timestamp(a.end, tz="UTC")
    df = load_trades(a.trades)
    cd = pd.to_datetime(df["close_date"], utc=True)
    seg = df.loc[(cd >= start) & (cd <= end)]

    out = {"source": os.path.basename(a.trades), "label": a.label,
           "window": f"{a.start}..{a.end}", "capital": a.capital,
           "metrics": stats(seg, start, end, a.capital)}
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    p = a.out or os.path.join(os.path.dirname(os.path.dirname(a.trades)),
                              "verified", f"seg_{a.label}.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(f"[seg] -> {p}")

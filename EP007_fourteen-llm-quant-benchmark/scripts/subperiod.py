# -*- coding: utf-8 -*-
"""分市场状态 / 子区间检验 —— 五层评分体系第 3 层「分市场状态」的实现。

问的是:这笔钱是均匀赚出来的,还是集中在某一两个月?
只在某一段赚 = 脆;各段都不太亏 = 相对可信。

用法:
  python subperiod.py --trades <test.zip> --tag qwen3_8_max
  python subperiod.py --trades <test.zip> --tag qwen3_8_max --freq Q
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


def market_by_period(locked, idx, freq):
    px = {}
    for f in sorted(__import__("glob").glob(os.path.join(locked, "binance/futures/*-1d-futures.feather"))):
        sym = os.path.basename(f).split("_")[0]
        d = pd.read_feather(f)
        px[sym] = pd.Series(d["close"].values,
                            index=pd.DatetimeIndex(pd.to_datetime(d["date"])).normalize())
    P = pd.DataFrame(px).sort_index()
    r = P.pct_change().mean(axis=1)
    r = r.loc[idx[0]:idx[-1]]
    return r.groupby(r.index.to_period(freq)).apply(lambda s: (1 + s).prod() - 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--freq", default="M", help="M=按月 Q=按季")
    ap.add_argument("--start", default="2025-07-01")
    ap.add_argument("--end", default="2026-07-01")  # 必须到 07-01,否则切掉末端强平(那批 close_date=2026-07-01 00:00)
    ap.add_argument("--capital", type=float, default=10000.0)
    ap.add_argument("--locked", default=r"D:\freqtrade_locked\data_LOCKED")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    df = load_trades(a.trades)
    cd = pd.to_datetime(df["close_date"], utc=True)
    lo, hi = pd.Timestamp(a.start, tz="UTC"), pd.Timestamp(a.end, tz="UTC")
    seg = df.loc[(cd >= lo) & (cd <= hi)].copy()
    seg["c"] = pd.to_datetime(seg["close_date"], utc=True)
    seg["pa"] = pd.to_numeric(seg["profit_abs"], errors="coerce").fillna(0.0)
    seg["per"] = seg["c"].dt.to_period(a.freq)

    idx = pd.date_range(a.start, a.end, freq="D", tz="UTC")
    mkt = market_by_period(a.locked, idx, a.freq)

    rows = []
    for per, g in seg.groupby("per"):
        pnl = float(g["pa"].sum())
        rows.append(dict(
            period=str(per), n=int(len(g)),
            pnl=round(pnl, 1), ret_pct=round(pnl / a.capital * 100, 2),
            long_pnl=round(float(g.loc[~g["is_short"], "pa"].sum()), 1),
            short_pnl=round(float(g.loc[g["is_short"], "pa"].sum()), 1),
            win_rate=round(float((g["pa"] > 0).mean()) * 100, 1),
            market_pct=round(float(mkt.get(per, np.nan)) * 100, 2) if per in mkt.index else None,
        ))
    t = pd.DataFrame(rows)
    tot = float(t["pnl"].sum())
    pos = t[t["pnl"] > 0]["pnl"].sum()

    print(t.to_string(index=False))
    print()
    print("区间总盈亏      : %.1f USDT (%.2f%%)" % (tot, tot / a.capital * 100))
    print("盈利期数/总期数 : %d / %d" % (int((t['pnl'] > 0).sum()), len(t)))
    if len(t):
        best = t.loc[t["pnl"].idxmax()]
        print("最赚的一期      : %s  %.1f USDT" % (best["period"], best["pnl"]))
        if tot > 0:
            print("★ 最赚一期占总盈亏 : %.0f%%" % (best["pnl"] / tot * 100))
            print("★ 去掉最赚一期后   : %.1f USDT (%.2f%%)" % (tot - best["pnl"], (tot - best["pnl"]) / a.capital * 100))
        print("正盈亏期合计    : %.1f;负盈亏期合计: %.1f" % (pos, tot - pos))

    out = a.out or os.path.join(os.path.dirname(os.path.dirname(a.trades)), "verified", f"subperiod_{a.freq}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"tag": a.tag, "freq": a.freq, "rows": rows,
               "total_pnl": round(tot, 1), "n_positive": int((t['pnl'] > 0).sum()), "n_periods": len(t)},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n[sub] -> " + out)


if __name__ == "__main__":
    main()


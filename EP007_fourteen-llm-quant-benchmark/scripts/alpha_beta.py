# -*- coding: utf-8 -*-
"""alpha/beta 归因 —— EP004 报告「第 3 层 · 排名核心依据」的可复用实现。

EP004 当时是手算的,结果硬编码在 make_video_charts.py 里(ALPHA/BETA 两个 dict)。
本脚本把它抽出来,口径与 EP004 完全一致,并可在 EP004 四家上回归验证。

口径(与 EP004 一致,不许改):
  大盘        = 20 币 1d 收盘价的日收益**等权均值**,再累乘 → EP004 的 −45.0% 就是这么来的
                (注意:这和 Freqtrade 输出的 `Market change` 不是一回事,后者是首尾价均值)
  策略净值    = 逐日盯市 = 初始资金 + 已实现盈亏(按 close_date 归集,累加) + 当日未平仓浮盈
  beta / alpha= 策略日收益 对 大盘日收益 做 OLS;alpha 为截距,年化 ×365
  beta 拖累   = beta × 大盘区间总收益
  alpha 贡献  = 策略区间总收益 − beta 拖累
  净敞口      = 每日(多头名义 − 空头名义)/当日权益,再取全区间均值

用法:
  python alpha_beta.py --env D:\\freqtrade_demo\\EP007_env\\ft_glm_5_3 --tag glm_5_3
  python alpha_beta.py --env D:\\freqtrade_demo\\EP004_env\\ft_fable_5 --tag fable_5   # 回归验证
"""
import argparse, glob, json, os, zipfile
import numpy as np
import pandas as pd


def load_market(locked, start, end):
    px = {}
    for f in sorted(glob.glob(os.path.join(locked, "binance/futures/*-1d-futures.feather"))):
        sym = os.path.basename(f).split("_")[0]
        d = pd.read_feather(f)
        px[sym] = pd.Series(d["close"].values,
                            index=pd.DatetimeIndex(pd.to_datetime(d["date"])).normalize())
    if not px:
        raise SystemExit(f"没在 {locked} 找到 *-1d-futures.feather")
    P = pd.DataFrame(px).sort_index()
    nxt = (pd.Timestamp(start, tz="UTC") + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    mkt = P.pct_change().mean(axis=1).loc[nxt:end]
    return P, mkt


def load_trades(z):
    with zipfile.ZipFile(z) as f:
        for n in f.namelist():
            if n.endswith(".json") and "_config" not in n:
                o = json.loads(f.read(n))
                for v in o.get("strategy", {}).values():
                    if v.get("trades"):
                        return pd.DataFrame(v["trades"])
    raise SystemExit(f"{z} 里没找到 trades")


def mtm_equity(df, P, days, cap):
    df = df.copy()
    df["o"] = pd.to_datetime(df["open_date"], utc=True).dt.normalize()
    df["c"] = pd.to_datetime(df["close_date"], utc=True).dt.normalize()
    df["sym"] = df["pair"].str.split("/").str[0]
    df["sgn"] = np.where(df["is_short"], -1.0, 1.0)
    df["amt"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["orate"] = pd.to_numeric(df["open_rate"], errors="coerce")
    df["pa"] = pd.to_numeric(df["profit_abs"], errors="coerce").fillna(0.0)

    realized = df.groupby("c")["pa"].sum().reindex(days, fill_value=0.0).cumsum()
    eq, expo = [], []
    for d in days:
        op = df[(df["o"] <= d) & (df["c"] > d)]
        upnl, net = 0.0, 0.0
        for _, r in op.iterrows():
            if r["sym"] not in P:
                continue
            p = P[r["sym"]].asof(d)
            if pd.isna(p):
                continue
            upnl += r["sgn"] * (p - r["orate"]) * r["amt"]
            net  += r["sgn"] * p * r["amt"]
        e = cap + realized[d] + upnl
        eq.append(e)
        expo.append(net / e if e else 0.0)
    return pd.Series(eq, index=days), pd.Series(expo, index=days)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True, help="考场目录")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--trades", default=None, help="默认找 verified/test.zip 或 backtest_results/test.zip")
    ap.add_argument("--locked", default=r"D:\freqtrade_locked\data_LOCKED")
    ap.add_argument("--start", default="2025-07-01")
    ap.add_argument("--end", default="2026-07-01")
    ap.add_argument("--capital", type=float, default=10000.0)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    z = a.trades
    if not z:
        for c in ("verified/test.zip", "backtest_results/test.zip"):
            p = os.path.join(a.env, *c.split("/"))
            if os.path.exists(p):
                z = p
                break
    if not z or not os.path.exists(z):
        raise SystemExit("找不到 test.zip,用 --trades 指定")

    days = pd.date_range(a.start, a.end, freq="D", tz="UTC")
    P, mkt = load_market(a.locked, a.start, a.end)
    mkt_d = mkt.reindex(days).fillna(0.0)
    mkt_total = float((1 + mkt).prod() - 1)

    eq, expo = mtm_equity(load_trades(z), P, days, a.capital)
    r_s = eq.pct_change().fillna(0.0)

    m = mkt_d.to_numpy(float)
    s = r_s.to_numpy(float)
    ok = np.isfinite(m) & np.isfinite(s)
    beta, alpha_d = np.polyfit(m[ok], s[ok], 1)
    pred = beta * m[ok] + alpha_d
    ss_res = float(((s[ok] - pred) ** 2).sum())
    ss_tot = float(((s[ok] - s[ok].mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0

    total = float(eq.iloc[-1] / a.capital - 1)
    drag = beta * mkt_total
    res = {
        "tag": a.tag,
        "trades_file": z,
        "window": f"{a.start}..{a.end}",
        "market_total_return_pct": round(mkt_total * 100, 2),
        "strategy_total_return_pct": round(total * 100, 2),
        "beta": round(float(beta), 3),
        "r2": round(float(r2), 3),
        "alpha_annual_pct": round(float(alpha_d) * 365 * 100, 1),
        "beta_drag_pct": round(drag * 100, 1),
        "alpha_contrib_pct": round((total - drag) * 100, 1),
        "net_exposure_pct": round(float(expo.mean()) * 100, 1),
        "final_equity": round(float(eq.iloc[-1]), 2),
    }
    print(json.dumps(res, ensure_ascii=False, indent=2))
    out = a.out or os.path.join(a.env, "verified", "alpha_beta.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"[ab] -> {out}")


if __name__ == "__main__":
    main()

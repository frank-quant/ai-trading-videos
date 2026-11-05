"""Performance metrics for the SMA5/SMA20 teaching backtest vs benchmarks.

Series compared (identical window 2023-06-01 ~ 2026-10-23):
  1. 赛力斯 SMA5/20 交叉策略 — 零成本 (Ledger_Gross.csv)
  2. 赛力斯 SMA5/20 交叉策略 — 含费 0.075%/单边 (Ledger.csv)
  3. 赛力斯 买入持有 (前复权，首日开盘买入、末日收盘持有)
  4. 沪深300 价格指数 买入持有

Fee decomposition is reported as TWO separate quantities:
  * 费用造成的期末净值差 = 零成本期末净值 − 含费期末净值
  * 实际支付费用合计     = 含费账本累计手续费
They differ because fees shrink the capital that is deployed afterwards, so
later fees are charged on a smaller base (the compounding effect).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INITIAL = 1_000_000.0
ANN = 252


def read(name):
    with (ROOT / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def dd_stats(dates, navs):
    """Max drawdown with peak / trough / recovery dates."""
    peak_i, peak_v = 0, navs[0]
    best = {"dd": 0.0, "peak_i": 0, "trough_i": 0}
    for i, v in enumerate(navs):
        if v > peak_v:
            peak_v, peak_i = v, i
        d = v / peak_v - 1.0
        if d < best["dd"]:
            best = {"dd": d, "peak_i": peak_i, "trough_i": i}
    rec = None
    peak_v2 = navs[best["peak_i"]]
    for i in range(best["trough_i"], len(navs)):
        if navs[i] >= peak_v2:
            rec = i
            break
    return {
        "max_drawdown": best["dd"],
        "dd_peak_date": dates[best["peak_i"]],
        "dd_trough_date": dates[best["trough_i"]],
        "dd_recovery_date": dates[rec] if rec is not None else None,
        "dd_peak_to_trough_days": best["trough_i"] - best["peak_i"],
        "dd_underwater_days": (rec - best["peak_i"]) if rec is not None else len(navs) - best["peak_i"],
    }


def series_from_ledger(rows, label, cost_regime):
    dates = [r["date"] for r in rows]
    navs = [float(r["nav"]) for r in rows]
    holding = sum(1 for r in rows if float(r["shares"]) > 0)
    buys = sum(1 for r in rows if r["action"] == "BUY")
    sells = sum(1 for r in rows if r["action"] == "SELL")
    fees = float(rows[-1]["cum_fee"])
    d = dd_stats(dates, navs)
    return {
        "row_type": "strategy",
        "series": label,
        "cost_regime": cost_regime,
        "window_start": dates[0],
        "window_end": dates[-1],
        "trading_days": len(dates),
        "initial_capital": f"{INITIAL:.2f}",
        "final_nav": f"{navs[-1]:.4f}",
        "cumulative_return": f"{navs[-1] / INITIAL - 1:.6f}",
        # 年化口径：N 个净值观测点 = N-1 个日收益期 → 指数 252/(N-1)
        "annualized_return": f"{(navs[-1] / INITIAL) ** (ANN / (len(dates) - 1)) - 1:.6f}",
        "max_drawdown": f"{d['max_drawdown']:.6f}",
        "dd_peak_date": d["dd_peak_date"],
        "dd_trough_date": d["dd_trough_date"],
        "dd_recovery_date": d["dd_recovery_date"] or "",
        "dd_peak_to_trough_days": d["dd_peak_to_trough_days"],
        "dd_underwater_days": d["dd_underwater_days"],
        "trade_count_round_trips": min(buys, sells),
        "buy_count": buys,
        "sell_count": sells,
        "holding_days": holding,
        "holding_ratio": f"{holding / len(dates):.6f}",
        "total_fees_paid": f"{fees:.4f}",
        "fee_drag_on_initial": f"{fees / INITIAL:.6f}",
        "fee_final_nav_gap": "",
        "value": "",
        "note": "",
        "_navs": [n / INITIAL for n in navs],   # 归一化为净值倍数，便于与基准同量纲作图
        "_dates": dates,
    }


def series_from_buy_hold(rows, label, note):
    dates = [r["date"] for r in rows]
    p0 = float(rows[0]["open"])
    navs = [float(r["close"]) / p0 for r in rows]
    d = dd_stats(dates, navs)
    return {
        "row_type": "benchmark",
        "series": label,
        "cost_regime": "zero_cost",
        "window_start": dates[0],
        "window_end": dates[-1],
        "trading_days": len(dates),
        "initial_capital": f"{INITIAL:.2f}",
        "final_nav": f"{navs[-1] * INITIAL:.4f}",
        "cumulative_return": f"{navs[-1] - 1:.6f}",
        "annualized_return": f"{navs[-1] ** (ANN / (len(dates) - 1)) - 1:.6f}",
        "max_drawdown": f"{d['max_drawdown']:.6f}",
        "dd_peak_date": d["dd_peak_date"],
        "dd_trough_date": d["dd_trough_date"],
        "dd_recovery_date": d["dd_recovery_date"] or "",
        "dd_peak_to_trough_days": d["dd_peak_to_trough_days"],
        "dd_underwater_days": d["dd_underwater_days"],
        "trade_count_round_trips": 0,
        "buy_count": 1,
        "sell_count": 0,
        "holding_days": len(dates),
        "holding_ratio": "1.000000",
        "total_fees_paid": "0.0000",
        "fee_drag_on_initial": "0.000000",
        "fee_final_nav_gap": "",
        "value": "",
        "note": note,
        "_navs": navs,
        "_dates": dates,
    }


def main():
    g = read("Ledger_Gross.csv")
    f = read("Ledger.csv")
    prices = read("prices.csv")
    bench = read("prices_bench.csv")

    s_gross = series_from_ledger(g, "赛力斯 SMA5/20 交叉策略", "zero_cost")
    s_net = series_from_ledger(f, "赛力斯 SMA5/20 交叉策略", "fee_0.075pct_oneway")

    gap = float(s_gross["final_nav"]) - float(s_net["final_nav"])
    fees_paid = float(s_net["total_fees_paid"])
    s_gross["fee_final_nav_gap"] = f"{gap:.4f}"
    s_gross["note"] = "费用分解见下方 fee_breakdown 行"
    s_net["fee_final_nav_gap"] = f"{gap:.4f}"
    s_net["note"] = "费用分解见下方 fee_breakdown 行"

    bh_stock = series_from_buy_hold(
        prices, "赛力斯 买入持有",
        "前复权首日开盘买入、末日收盘持有，样本末不卖出")
    bh_bench = series_from_buy_hold(
        bench, "沪深300 价格指数 买入持有",
        "首日开盘买入、末日收盘持有，样本末不卖出")

    def breakdown(name, value, note):
        r = dict.fromkeys(
            ["row_type", "series", "cost_regime", "window_start", "window_end",
             "trading_days", "initial_capital", "final_nav", "cumulative_return",
             "annualized_return", "max_drawdown", "dd_peak_date", "dd_trough_date",
             "dd_recovery_date", "dd_peak_to_trough_days", "dd_underwater_days",
             "trade_count_round_trips", "buy_count", "sell_count", "holding_days",
             "holding_ratio", "total_fees_paid", "fee_drag_on_initial",
             "fee_final_nav_gap", "value", "note"], "")
        r["row_type"] = "fee_breakdown"
        r["series"] = name
        r["value"] = value
        r["note"] = note
        return r

    rows = [s_gross, s_net, bh_stock, bh_bench,
            breakdown("费用造成的期末净值差（零成本期末净值 − 含费期末净值）",
                      f"{gap:.4f}",
                      "含费账本相对零成本账本少掉的期末净值；与下一行的实际支付费用不是同一口径"),
            breakdown("实际支付费用合计（含费账本累计手续费）",
                      f"{fees_paid:.4f}",
                      f"占初始资金 {fees_paid / INITIAL * 100:.2f}%；大于上一行，因费用使后续可用资金变小、后续费用按更小基数计提")]

    cols = ["row_type", "series", "cost_regime", "window_start", "window_end",
            "trading_days", "initial_capital", "final_nav", "cumulative_return",
            "annualized_return", "max_drawdown", "dd_peak_date", "dd_trough_date",
            "dd_recovery_date", "dd_peak_to_trough_days", "dd_underwater_days",
            "trade_count_round_trips", "buy_count", "sell_count", "holding_days",
            "holding_ratio", "total_fees_paid", "fee_drag_on_initial",
            "fee_final_nav_gap", "value", "note"]

    with (ROOT / "metrics.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    paths = {
        "dates": s_gross["_dates"],
        "series": {
            "策略（零成本）": s_gross["_navs"],
            "策略（含费0.075%）": s_net["_navs"],
            "赛力斯买入持有": bh_stock["_navs"],
            "沪深300买入持有": bh_bench["_navs"],
        },
    }
    (ROOT / "raw" / "nav_paths.json").write_text(
        json.dumps(paths, ensure_ascii=False), encoding="utf-8")

    out = {r["series"] + "|" + r["cost_regime"]: {
        k: r[k] for k in ("final_nav", "cumulative_return", "annualized_return",
                          "max_drawdown", "trade_count_round_trips", "holding_days",
                          "holding_ratio", "total_fees_paid")} for r in rows if r["row_type"] != "fee_breakdown"}
    out["fee_breakdown"] = {"final_nav_gap": gap, "fees_paid": fees_paid}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

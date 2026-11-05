"""Round-trip detail + buy-and-hold benchmark for the teaching backtest."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INITIAL = 1_000_000.0


def read(name):
    with (ROOT / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    g = read("Ledger_Gross.csv")
    f = read("Ledger.csv")
    prices = read("prices.csv")
    bench = read("prices_bench.csv")

    # ---- round trips from the gross ledger (same trades in both) ----
    trips = []
    entry = None
    for i, r in enumerate(g):
        if r["action"] == "BUY":
            entry = {"row": r, "signal_date": g[i - 1]["date"]}
        elif r["action"] == "SELL" and entry is not None:
            e_price = float(entry["row"]["fill_price"])
            x_price = float(r["fill_price"])
            trips.append({
                "signal_date": entry["signal_date"],
                "entry_date": entry["row"]["date"], "entry_price": e_price,
                "exit_date": r["date"], "exit_price": x_price,
                "ret": x_price / e_price - 1.0,
            })
            entry = None

    # ---- buy & hold benchmarks over the full sample ----
    def bh(rows):
        p0 = float(rows[0]["open"])
        p1 = float(rows[-1]["close"])
        return p1 / p0 - 1.0

    def bh_mdd(rows):
        """Buy-and-hold NAV path: shares fixed at the first open, marked to each close."""
        p0 = float(rows[0]["open"])
        navs = [float(r["close"]) / p0 for r in rows]
        peak, mdd = navs[0], 0.0
        for v in navs:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1.0)
        return mdd

    bh_stock = bh(prices)
    bh_bench = bh(bench)
    bh_stock_mdd = bh_mdd(prices)
    bh_bench_mdd = bh_mdd(bench)

    def maxdd(rows):
        nav = [float(r["nav"]) for r in rows]
        peak, mdd = nav[0], 0.0
        for v in nav:
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1.0)
        return mdd

    def ann(rows):
        nav = float(rows[-1]["nav"])
        # 年化口径：N 个净值观测点 = N-1 个日收益期 → 指数 252/(N-1)
        return (nav / INITIAL) ** (252 / (len(rows) - 1)) - 1

    lines = []
    w = lines.append
    w("# 回测逐笔与基准对照（教学用）")
    w("")
    w("## 一、逐笔往返交易（零成本口径）")
    w("")
    w("| # | 信号日 | 买入日 | 买入价 | 卖出日 | 卖出价 | 单笔收益 |")
    w("|---:|---|---|---:|---|---:|---:|")
    for i, t in enumerate(trips, 1):
        w(f"| {i} | {t['signal_date']} | {t['entry_date']} | {t['entry_price']:.2f} | "
          f"{t['exit_date']} | {t['exit_price']:.2f} | {t['ret'] * 100:+.2f}% |")
    rets = [t["ret"] for t in trips]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    w("")
    w(f"- 往返次数 {len(trips)}，胜率 {len(wins) / len(rets) * 100:.1f}%"
      f"（{len(wins)} 胜 / {len(losses)} 负）")
    w(f"- 平均盈利 {sum(wins) / len(wins) * 100:+.2f}%，平均亏损 {sum(losses) / len(losses) * 100:+.2f}%")
    w(f"- 最佳单笔 {max(rets) * 100:+.2f}%，最差单笔 {min(rets) * 100:+.2f}%")
    w("")
    w("## 二、两种成本口径对照")
    w("")
    w("| 口径 | 期末净值 | 累计收益 | 年化 | 最大回撤 | 累计费用 |")
    w("|---|---:|---:|---:|---:|---:|")
    for name, rows in (("零成本 Ledger_Gross", g), ("含费 Ledger (0.075%/单边)", f)):
        w(f"| {name} | {float(rows[-1]['nav']):,.2f} | "
          f"{float(rows[-1]['cum_return']) * 100:+.2f}% | {ann(rows) * 100:+.2f}% | "
          f"{maxdd(rows) * 100:.2f}% | {float(rows[-1]['cum_fee']):,.2f} |")
    w("")
    w(f"- 费用侵蚀：期末净值差 {float(g[-1]['nav']) - float(f[-1]['nav']):,.2f} 元"
      f"（占零成本期末净值 {(float(g[-1]['nav']) - float(f[-1]['nav'])) / float(g[-1]['nav']) * 100:.2f}%）；"
      f"累计手续费 {float(f[-1]['cum_fee']):,.2f} 元 = 初始资金的 "
      f"{float(f[-1]['cum_fee']) / INITIAL * 100:.2f}%")
    w("")
    w("## 三、基准对照（同期买入持有）")
    w("")
    w("| 标的 | 区间 | 收益 | 最大回撤 |")
    w("|---|---|---:|---:|")
    w(f"| 赛力斯 买入持有 | {prices[0]['date']} 开盘 → {prices[-1]['date']} 收盘 | "
      f"{bh_stock * 100:+.2f}% | {bh_stock_mdd * 100:.2f}% |")
    w(f"| 沪深300 买入持有 | {bench[0]['date']} 开盘 → {bench[-1]['date']} 收盘 | "
      f"{bh_bench * 100:+.2f}% | {bh_bench_mdd * 100:.2f}% |")
    w(f"| SMA5/20 交叉策略（零成本） | 同期 | {float(g[-1]['cum_return']) * 100:+.2f}% | "
      f"{maxdd(g) * 100:.2f}% |")
    w(f"| SMA5/20 交叉策略（含费） | 同期 | {float(f[-1]['cum_return']) * 100:+.2f}% | "
      f"{maxdd(f) * 100:.2f}% |")
    w("")
    w("> 教学要点（请注意这几点都属于**样本内**结论）：")
    w(">")
    w(f"> 1. 低胜率（25%）仍取得正收益，靠的是少数大盈利单笔（最佳 {max(rets) * 100:+.1f}%）——"
      "这是趋势跟踪的典型形态，收益分布高度右偏。")
    w(f"> 2. 本策略 {float(f[-1]['cum_return']) * 100:+.2f}% **跑输**同期直接买入持有赛力斯"
      f"（{bh_stock * 100:+.2f}%），因此该结果**不能证明策略有效**；它唯一的相对优势是"
      f"回撤更浅（{maxdd(f) * 100:.2f}% vs {bh_stock_mdd * 100:.2f}%）。")
    w(f"> 3. 同期沪深300 仅 {bh_bench * 100:+.2f}%，个股波动远大于指数，"
      "单一标的的交叉策略结果对**参数与样本区间**极其敏感。")
    w("> 4. 交易成本把累计收益从 "
      f"{float(g[-1]['cum_return']) * 100:+.2f}% 拉低到 {float(f[-1]['cum_return']) * 100:+.2f}%，"
      "在 40 次往返、3 年多、标的大幅波动的样本里，费用是决定性因素之一。")
    w("")
    (ROOT / "raw" / "backtest_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({
        "round_trips": len(trips), "win_rate": len(wins) / len(rets),
        "avg_win": sum(wins) / len(wins), "avg_loss": sum(losses) / len(losses),
        "best": max(rets), "worst": min(rets),
        "bh_stock": bh_stock, "bh_bench": bh_bench,
        "gross_final_nav": float(g[-1]["nav"]), "fee_final_nav": float(f[-1]["nav"]),
        "gross_mdd": maxdd(g), "fee_mdd": maxdd(f),
        "gross_ann": ann(g), "fee_ann": ann(f),
        "total_fees": float(f[-1]["cum_fee"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

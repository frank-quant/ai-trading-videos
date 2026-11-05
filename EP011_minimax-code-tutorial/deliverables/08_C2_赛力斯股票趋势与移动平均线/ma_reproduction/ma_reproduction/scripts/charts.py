"""Three teaching charts: price+MA+signals, NAV vs benchmarks, drawdown."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "charts"
OUT.mkdir(exist_ok=True)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 150
plt.rcParams["savefig.dpi"] = 160
plt.rcParams["axes.grid"] = True
plt.rcParams["grid.alpha"] = 0.25
plt.rcParams["grid.linestyle"] = "--"

C_PRICE = "#2b2b2b"
C_MA5 = "#d97706"
C_MA20 = "#2563eb"
C_MA60 = "#7c3aed"
C_BUY = "#dc2626"
C_SELL = "#0891b2"
C_GROSS = "#1d4ed8"
C_NET = "#ea580c"
C_BH = "#16a34a"
C_BENCH = "#6b7280"


def read(name):
    with (ROOT / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def date_ticks(ax, dates, n=8):
    step = max(1, len(dates) // n)
    idx = list(range(0, len(dates), step))
    last = len(dates) - 1
    if idx[-1] != last:
        # avoid the final label colliding with its neighbour
        if last - idx[-1] < step * 0.45:
            idx[-1] = last
        else:
            idx.append(last)
    ax.set_xticks(idx)
    ax.set_xticklabels([dates[i][:7] for i in idx], rotation=0, fontsize=9)


def pct_axis(ax, axis="y"):
    fmt = FuncFormatter(lambda v, _: f"{v * 100:.0f}%" if abs(v) < 1 else f"{v:,.1f}")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def main():
    prices = read("prices.csv")
    ind = read("indicators.csv")
    gross = read("Ledger_Gross.csv")
    net = read("Ledger.csv")
    metrics = read("metrics.csv")
    navs = json.loads((ROOT / "raw" / "nav_paths.json").read_text(encoding="utf-8"))

    dates = [r["date"] for r in prices]
    close = [float(r["close"]) for r in prices]
    n = len(dates)

    m = {r["series"] + "|" + r["cost_regime"]: r for r in metrics if r["row_type"] != "fee_breakdown"}
    bd = {r["series"]: r for r in metrics if r["row_type"] == "fee_breakdown"}
    s_g = m["赛力斯 SMA5/20 交叉策略|zero_cost"]
    s_n = m["赛力斯 SMA5/20 交叉策略|fee_0.075pct_oneway"]
    bh = m["赛力斯 买入持有|zero_cost"]
    ix = m["沪深300 价格指数 买入持有|zero_cost"]
    gap = float(list(bd.values())[0]["value"]) if False else None

    gap_v = float([r for r in metrics if r["row_type"] == "fee_breakdown"][0]["value"])
    fee_v = float([r for r in metrics if r["row_type"] == "fee_breakdown"][1]["value"])

    # ---------------- chart 1: price + MA + trade points ----------------
    fig, ax = plt.subplots(figsize=(15, 7.2))
    ax.plot(range(n), close, lw=1.15, color=C_PRICE, label="收盘价（前复权）", zorder=3)
    for key, col, lab in (("sma5", C_MA5, "MA5"), ("sma20", C_MA20, "MA20"), ("sma60", C_MA60, "MA60")):
        ys = [float(r[key]) if r[key] else None for r in ind]
        ax.plot(range(n), ys, lw=1.0, color=col, alpha=0.95, label=lab, zorder=2)

    buys = [(i, float(r["fill_price"])) for i, r in enumerate(gross) if r["action"] == "BUY"]
    sells = [(i, float(r["fill_price"])) for i, r in enumerate(gross) if r["action"] == "SELL"]
    ax.scatter([i for i, _ in buys], [p for _, p in buys], s=78, marker="^",
               color=C_BUY, edgecolors="white", linewidths=0.7, zorder=5,
               label=f"买入点（次日开盘成交）{len(buys)} 次")
    ax.scatter([i for i, _ in sells], [p for _, p in sells], s=78, marker="v",
               color=C_SELL, edgecolors="white", linewidths=0.7, zorder=5,
               label=f"卖出点（次日开盘清仓）{len(sells)} 次")

    ax.set_title("赛力斯 601127.SH：价格、均线与 SMA5/SMA20 交叉买卖点（2023-06-01 ~ 2026-10-23，前复权）",
                 fontsize=14, pad=14)
    ax.set_ylabel("价格（元）", fontsize=11)
    date_ticks(ax, dates)
    ax.legend(loc="upper left", fontsize=9.5, framealpha=0.92, ncol=3)
    ax.set_xlim(-2, n + 2)
    ax.text(0.995, 0.02,
            f"买入 {len(buys)} 次 ｜ 卖出 {len(sells)} 次 ｜ 期末空仓（2026-10-21 已按死叉清仓）",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=9.5,
            bbox=dict(boxstyle="round,pad=0.45", fc="#f8fafc", ec="#cbd5e1"))
    fig.tight_layout()
    fig.savefig(OUT / "chart_price_signals.png", bbox_inches="tight")
    plt.close(fig)

    # ---------------- chart 2: NAV vs benchmarks ----------------
    fig, ax = plt.subplots(figsize=(15, 7.6))
    x = range(n)
    series = [
        ("策略（零成本）", "策略（零成本）", C_GROSS, "-", 2.0),
        ("策略（含费0.075%）", "策略（含费 0.075%/单边）", C_NET, "--", 2.0),
        ("赛力斯买入持有", "赛力斯 买入持有", C_BH, "-", 1.8),
        ("沪深300买入持有", "沪深300 买入持有", C_BENCH, "-", 1.8),
    ]
    for key, disp, col, ls, lw in series:
        y = navs["series"][key]
        ax.plot(x, y, ls, lw=lw, color=col, label=disp, zorder=4 if col != C_NET else 3)
    ax.axhline(1.0, color="#94a3b8", lw=0.9, ls=":", zorder=1)

    ax.set_title("策略净值 vs 基准（同一区间 2023-06-01 ~ 2026-10-23，起始净值 1.00）",
                 fontsize=14, pad=14)
    ax.set_ylabel("净值（倍）", fontsize=11)
    date_ticks(ax, dates)
    ax.legend(loc="upper left", fontsize=10, framealpha=0.92)

    lines = [
        "期末净值 / 累计收益",
        f"  策略（零成本）      {float(s_g['final_nav']):,.0f}   {float(s_g['cumulative_return']) * 100:+.2f}%",
        f"  策略（含费）        {float(s_n['final_nav']):,.0f}   {float(s_n['cumulative_return']) * 100:+.2f}%",
        f"  赛力斯 买入持有     {float(bh['final_nav']):,.0f}   {float(bh['cumulative_return']) * 100:+.2f}%",
        f"  沪深300 买入持有    {float(ix['final_nav']):,.0f}   {float(ix['cumulative_return']) * 100:+.2f}%",
        "",
        "费用分解（两个口径分别列示）",
        f"  费用造成的期末净值差   {gap_v:,.2f} 元",
        f"  实际支付费用合计       {fee_v:,.2f} 元",
        "",
        f"结论：策略（含费 {float(s_n['cumulative_return']) * 100:+.2f}%）",
        f"跑输买入持有（{float(bh['cumulative_return']) * 100:+.2f}%），",
        f"仅回撤更浅（{float(s_n['max_drawdown']) * 100:.2f}% vs {float(bh['max_drawdown']) * 100:.2f}%）。",
        "样本内结果，不构成策略有效性证明。",
    ]
    ax.text(0.985, 0.965, "\n".join(lines), transform=ax.transAxes, ha="right", va="top",
            fontsize=9.3, family="Microsoft YaHei",
            bbox=dict(boxstyle="round,pad=0.6", fc="#fffbeb", ec="#f59e0b", alpha=0.95))
    ax.set_ylim(bottom=min(0.85, min(min(v) for v in navs["series"].values()) * 0.99))
    fig.tight_layout()
    fig.savefig(OUT / "chart_nav_comparison.png", bbox_inches="tight")
    plt.close(fig)

    # ---------------- chart 3: drawdown (curves + max-DD bar panel) ----------------
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(15, 9.4),
                                  gridspec_kw={"height_ratios": [3.1, 1], "hspace": 0.28})
    worst = []
    for key, disp, col, ls, lw in series:
        y = navs["series"][key]
        peak, dd, worst_dd, worst_i, worst_pk, pki = y[0], [], 0.0, 0, 0, 0
        for i, v in enumerate(y):
            if v > peak:
                peak, pki = v, i
            d = v / peak - 1.0
            dd.append(d)
            if d < worst_dd:
                worst_dd, worst_i, worst_pk = d, i, pki
        worst.append((disp, col, worst_dd, worst_i, worst_pk))
        ax.plot(x, dd, ls, lw=lw, color=col, zorder=3)
        ax.fill_between(x, dd, 0, color=col, alpha=0.06, zorder=2)
        ax.scatter([worst_i], [worst_dd], s=46, color=col, zorder=6,
                   edgecolors="white", linewidths=0.7)

    ax.set_title("回撤曲线（同一区间，水下图；越接近 0 越接近历史高点）", fontsize=14, pad=12)
    ax.set_ylabel("回撤", fontsize=11)
    date_ticks(ax, dates)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v * 100:.0f}%"))
    handles = [plt.Line2D([], [], color=w[1], lw=2.4) for w in worst]
    labels = [f"{w[0]}  最大回撤 {w[2] * 100:.2f}%" for w in worst]
    ax.legend(handles, labels, loc="lower left", fontsize=9.8, framealpha=0.94)

    labels = [w[0] for w in worst]
    vals = [w[2] * 100 for w in worst]
    cols = [w[1] for w in worst]
    bars = ax2.barh(range(len(vals)), vals, color=cols, height=0.6, zorder=3)
    ax2.set_yticks(range(len(labels)))
    ax2.set_yticklabels(labels, fontsize=10)
    ax2.invert_yaxis()
    ax2.set_xlim(min(vals) * 1.25, 0)
    ax2.set_xlabel("最大回撤（%）", fontsize=11)
    ax2.set_title("最大回撤对比（括号内为峰值日 → 谷底日）", fontsize=11.5, pad=8)
    ax2.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    for b, w_ in zip(bars, worst):
        ax2.text(b.get_width() + 0.8, b.get_y() + b.get_height() / 2,
                 f"{b.get_width():.2f}%   ({dates[w_[4]]} → {dates[w_[3]]})",
                 va="center", ha="left", fontsize=9, color="white", fontweight="bold")
    ax2.grid(axis="y", alpha=0)
    fig.tight_layout()
    fig.savefig(OUT / "chart_drawdown.png", bbox_inches="tight")
    plt.close(fig)

    print(json.dumps({
        "charts": [str(p.relative_to(ROOT)) for p in sorted(OUT.glob("*.png"))],
        "buys": len(buys), "sells": len(sells),
        "final_nav_gap": gap_v, "fees_paid": fee_v,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

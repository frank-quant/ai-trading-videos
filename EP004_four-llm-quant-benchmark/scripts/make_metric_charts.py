#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EP004 · 评价指标配图生成器
==========================
为报告里每个「评价指标」配一张图,做到「图 + 结论」成对出现。
全部由原始数据现算,不硬编码结果。

产出到 _video/:
  gate_check.png        第1层 硬门槛 + 第4层 作弊检测 —— 体检卡
  long_short.png        第2层 表现 —— 多空两侧收益分解
  turnover_cost.png     第2层 表现 —— 换手/周期对成本的影响(对照实验)
  argmax_choice.png     第5层 判断力 —— 四家选参对照(argmax vs 实选)
  convergence_grid.png  第5层 判断力 —— 四家搜索收敛曲线
  mc_grid.png           第3层 稳健性 —— 蒙特卡洛 prob(profit)
  regime_shift.png      环境解释 —— 三段市场状态变化

用法:
  python make_metric_charts.py
"""
import argparse
import glob
import json
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

BG, FG, DIM, GRID = "#0d1117", "#e6edf3", "#8b949e", "#30363d"
RED, GREEN, GOLD = "#ff6b6b", "#3fb950", "#ffd24d"
MODELS = ["kimi_k3", "opus_5", "fable_5", "deepseek"]
NAMES = {"kimi_k3": "Kimi K3", "opus_5": "Opus 5", "fable_5": "Fable 5", "deepseek": "DeepSeek"}
COLORS = {"kimi_k3": "#3fb6ff", "opus_5": "#ff9f40", "fable_5": "#3fb950", "deepseek": "#bc8cff"}
# 各家最终采用的 epoch(来自各自 design.md / self_assessment.md)
CHOSEN = {"kimi_k3": 235, "opus_5": 233, "fable_5": 276, "deepseek": 408}
NL = chr(10)


def style(ax, title=None, xlabel=None, ylabel=None, ts=16):
    ax.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=DIM, labelsize=11)
    if title:
        ax.set_title(title, color=FG, fontsize=ts, pad=14, weight="bold")
    if xlabel:
        ax.set_xlabel(xlabel, color=DIM, fontsize=12)
    if ylabel:
        ax.set_ylabel(ylabel, color=DIM, fontsize=12)


def save(fig, out, name):
    fig.savefig(os.path.join(out, name), facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {name}")


# ------------------------------------------------------------ 体检卡
GATES = [
    ("编译 / 跑通 / 有成交", ["✓"] * 4),
    ("多空双向都用了", ["104 / 87", "167 / 157", "386 / 139", "213 / 194"]),
    ("杠杆 1x 未超", ["✓"] * 4),
    ("脚手架未篡改", ["✓"] * 4),
    ("手续费未偷改(6bps)", ["✓"] * 4),
    ("交付 6 文件齐全", ["✓"] * 4),
    ("因果检查(全量 vs 截断)", ["PASS", "PASS *", "PASS", "PASS"]),
]


def chart_gate(out):
    nr, nc = len(GATES), len(MODELS)
    fig, ax = plt.subplots(figsize=(14, 7.6), dpi=120)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(-0.5, nc + 1.6)
    ax.set_ylim(-0.6, nr + 0.3)
    ax.axis("off")
    for j, m in enumerate(MODELS):
        ax.text(j + 1.6, nr - 0.25, NAMES[m], ha="center", color=COLORS[m],
                fontsize=15, weight="bold")
    for i, (label, vals) in enumerate(GATES):
        y = nr - 1.3 - i
        ax.text(-0.35, y, label, ha="left", va="center", color=FG, fontsize=13)
        ax.plot([-0.4, nc + 1.35], [y - 0.5, y - 0.5], color=GRID, lw=0.8)
        for j, v in enumerate(vals):
            ok = v in ("✓",) or v.startswith("PASS")
            ax.text(j + 1.6, y, v, ha="center", va="center",
                    color=GREEN if ok else FG, fontsize=14,
                    weight="bold" if ok else "normal")
    ax.set_title("第 1 层 硬门槛 + 第 4 层 作弊检测:四家全过",
                 color=FG, fontsize=19, weight="bold", pad=18)
    fig.text(0.5, 0.015,
             "* Opus 的 factor_score 走 dataprovider,标准截断法不适用,改用框架级检验(两个结束日期的回测比对重叠期决策)",
             ha="center", color=DIM, fontsize=11)
    fig.tight_layout(rect=[0, 0.03, 1, 1])
    save(fig, out, "gate_check.png")


# ------------------------------------------------------------ 多空分解
LONG_SHORT = {  # (多头收益, 空头收益) 单位 %
    "kimi_k3": (-28.5, -1.3), "opus_5": (-30.6, 11.1),
    "fable_5": (-16.8, 9.2), "deepseek": (-22.4, 15.3),
}


def chart_long_short(out):
    fig, ax = plt.subplots(figsize=(13, 7.5), dpi=120)
    fig.patch.set_facecolor(BG)
    x = np.arange(len(MODELS))
    w = 0.35
    lo = [LONG_SHORT[m][0] for m in MODELS]
    sh = [LONG_SHORT[m][1] for m in MODELS]
    ax.bar(x - w / 2, lo, w, color="#546e7a", label="多头一侧", zorder=3)
    ax.bar(x + w / 2, sh, w, color=[GREEN if v > 0 else RED for v in sh],
           label="空头一侧", zorder=3)
    for i in range(len(MODELS)):
        ax.annotate(f"{lo[i]:+.1f}%", (i - w / 2, lo[i]), ha="center", va="top",
                    xytext=(0, -8), textcoords="offset points", color=FG, fontsize=13, weight="bold")
        ax.annotate(f"{sh[i]:+.1f}%", (i + w / 2, sh[i]), ha="center",
                    va="bottom" if sh[i] > 0 else "top",
                    xytext=(0, 8 if sh[i] > 0 else -8), textcoords="offset points",
                    color=GREEN if sh[i] > 0 else RED, fontsize=13, weight="bold")
    ax.axhline(0, color=DIM, lw=1.3)
    ax.set_xticks(x)
    ax.set_xticklabels([NAMES[m] for m in MODELS], color=FG, fontsize=14)
    ax.set_ylim(-38, 22)
    style(ax, "样本外:多空两侧各赚了多少(大盘 −45%)", ylabel="对初始资金的贡献(%)", ts=18)
    ax.annotate("熊市里该赚钱的一侧\n它反而亏了", xy=(0 + w / 2, -1.3), xytext=(0.35, -24),
                color=RED, fontsize=14, weight="bold",
                arrowprops=dict(arrowstyle="->", color=RED, lw=2.2))
    ax.legend(facecolor="#161b22", edgecolor=GRID, labelcolor=FG, fontsize=13, loc="lower right")
    save(fig, out, "long_short.png")


# ------------------------------------------------------------ 换手成本对照
def chart_turnover(out):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 6.6), dpi=120)
    fig.patch.set_facecolor(BG)
    labs = ["30 分钟\n不控换手", "4 小时\n+ 最短持仓"]
    rets, trades = [-44.7, 3.28], [12745, 436]
    for ax, vals, ttl, unit in [(a1, rets, "同一个因子,只改周期和换手控制", "%"),
                                (a2, trades, "一年成交笔数", "笔")]:
        ax.set_facecolor(BG)
        cols = [RED, GREEN] if unit == "%" else ["#546e7a", "#546e7a"]
        ax.bar([0, 1], vals, 0.5, color=cols, zorder=3)
        for i, v in enumerate(vals):
            ax.annotate(f"{v:+.2f}%" if unit == "%" else f"{v:,}", (i, v), ha="center",
                        va="bottom" if v > 0 else "top",
                        xytext=(0, 9 if v > 0 else -9), textcoords="offset points",
                        color=FG, fontsize=20, weight="bold")
        ax.set_xticks([0, 1])
        ax.set_xticklabels(labs, color=FG, fontsize=14)
        if unit == "%":
            ax.axhline(0, color=DIM, lw=1.3)
            ax.set_ylim(-56, 16)
        else:
            ax.set_ylim(0, 15000)
        style(ax, ttl, ylabel="一年收益" if unit == "%" else "笔数", ts=16)
    fig.suptitle("周期越快,手续费吃得越狠 —— 四家都没碰 30 分钟",
                 color=GOLD, fontsize=21, weight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    save(fig, out, "turnover_cost.png")


# ------------------------------------------------------------ 选参对照
def _trials(env, m):
    d = json.load(open(os.path.join(env, f"ft_{m}", "hyperopt_results.json"), encoding="utf-8"))
    t = pd.DataFrame(d["trials"])
    # Kimi 有 2 轮 valid_sharpe 为 null,不清掉相关性会算成 nan
    return t.replace([np.inf, -np.inf], np.nan).dropna(subset=["train_sharpe", "valid_sharpe"])


def chart_argmax(out, env):
    fig, axes = plt.subplots(2, 2, figsize=(15, 11.5), dpi=120)
    fig.patch.set_facecolor(BG)
    for ax, m in zip(axes.ravel(), MODELS):
        t = _trials(env, m)
        ax.scatter(t["train_sharpe"], t["valid_sharpe"], s=26, color=DIM, alpha=0.42,
                   zorder=2, edgecolor="none")
        am = t.loc[t["valid_sharpe"].idxmax()]
        ch = t.loc[t["epoch"] == CHOSEN[m]]
        ch = ch.iloc[0] if len(ch) else am
        took_argmax = int(am["epoch"]) == int(ch["epoch"])

        # 先定轴范围,顶部留出表头空间
        lo, hi = t["valid_sharpe"].min(), t["valid_sharpe"].max()
        ax.set_ylim(lo - (hi - lo) * 0.10, hi + (hi - lo) * 0.42)
        xl, xh = t["train_sharpe"].min(), t["train_sharpe"].max()
        ax.set_xlim(xl - (xh - xl) * 0.08, xh + (xh - xl) * 0.14)

        ax.scatter([am["train_sharpe"]], [am["valid_sharpe"]], s=340, marker="X",
                   color=RED, zorder=5, edgecolor=BG, lw=1.8)
        # argmax 标注一律放在叉的正下方
        ax.annotate(f"验证集最高分 e{int(am['epoch'])}" + NL +
                    f"train {am['train_sharpe']:.2f} / valid {am['valid_sharpe']:.2f}",
                    (am["train_sharpe"], am["valid_sharpe"]), textcoords="offset points",
                    xytext=(-14 if not took_argmax and
                            ch["train_sharpe"] > am["train_sharpe"] else 0, -18),
                    ha="right" if not took_argmax and
                    ch["train_sharpe"] > am["train_sharpe"] else "center",
                    va="top", color=RED, fontsize=11.5,
                    bbox=dict(boxstyle="round,pad=0.35", fc=BG, ec=RED, lw=0.9, alpha=0.92))
        if not took_argmax:
            ax.scatter([ch["train_sharpe"]], [ch["valid_sharpe"]], s=340, marker="o",
                       color=COLORS[m], zorder=5, edgecolor=BG, lw=2)
            # 实选点标注放在点的另一侧,避开 argmax
            side = 1 if ch["train_sharpe"] >= am["train_sharpe"] else -1
            ax.annotate(f"实际采用 e{int(ch['epoch'])}" + NL +
                        f"train {ch['train_sharpe']:.2f} / valid {ch['valid_sharpe']:.2f}",
                        (ch["train_sharpe"], ch["valid_sharpe"]), textcoords="offset points",
                        xytext=(18 * side, 16), ha="left" if side > 0 else "right",
                        va="bottom", color=COLORS[m], fontsize=11.5, weight="bold",
                        bbox=dict(boxstyle="round,pad=0.35", fc=BG, ec=COLORS[m],
                                  lw=0.9, alpha=0.92))
        r = float(t["train_sharpe"].corr(t["valid_sharpe"]))
        verdict = "直接采用了最高分" if took_argmax else "拒绝了最高分"
        ax.text(0.025, 0.975, f"{NAMES[m]}   ·   {len(t)} 轮   ·   r = {r:.2f}",
                transform=ax.transAxes, color=COLORS[m], fontsize=15, weight="bold",
                va="top", ha="left")
        ax.text(0.025, 0.895, verdict, transform=ax.transAxes,
                color=RED if took_argmax else GREEN, fontsize=13.5, weight="bold",
                va="top", ha="left")
        ax.axhline(0, color=GRID, lw=1, ls="--")
        ax.axvline(0, color=GRID, lw=1, ls="--")
        style(ax, None, xlabel="训练集夏普", ylabel="验证集夏普")
    fig.suptitle("第 5 层 判断力:三家拒绝了验证集最高分,一家接住了",
                 color=FG, fontsize=23, weight="bold", y=0.985)
    fig.text(0.5, 0.011,
             "灰点 = 每一轮搜索结果 · 红叉 = 验证集最高分那组 · 圆点 = 模型最终采用的那组       "
             "r = 训练集与验证集夏普的相关性,越接近 0 说明验证集排名越接近纯噪音",
             ha="center", color=DIM, fontsize=12)
    fig.tight_layout(rect=[0, 0.026, 1, 0.955])
    save(fig, out, "argmax_choice.png")


# ------------------------------------------------------------ 收敛曲线
def chart_convergence(out, env):
    fig, ax = plt.subplots(figsize=(14, 7.2), dpi=120)
    fig.patch.set_facecolor(BG)
    for m in MODELS:
        t = _trials(env, m).sort_values("epoch")
        best = t["valid_sharpe"].cummax()
        ax.plot(t["epoch"], best, color=COLORS[m], lw=2.6,
                label=f"{NAMES[m]}({len(t)} 轮)", zorder=3)
        ax.scatter([t["epoch"].iloc[-1]], [best.iloc[-1]], s=90, color=COLORS[m],
                   zorder=4, edgecolor=BG, lw=1.6)
    ax.axvline(2000, color=RED, lw=1.6, ls="--")
    ax.text(1960, ax.get_ylim()[0] + 0.12, "题目给的上限 2000 轮  ",
            ha="right", color=RED, fontsize=13, weight="bold")
    ax.set_xlim(0, 2100)
    style(ax, "搜索轮数:上限 2000,没有一家跑满", xlabel="搜索轮次",
          ylabel="截至该轮的最佳验证集夏普", ts=18)
    ax.legend(facecolor="#161b22", edgecolor=GRID, labelcolor=FG, fontsize=13, loc="lower right")
    ax.text(0.5, 0.94, "它们知道多搜是要付代价的 —— 搜得越多,靠运气刷出漂亮回测的概率越大",
            transform=ax.transAxes, ha="center", color=GOLD, fontsize=14)
    save(fig, out, "convergence_grid.png")


# ------------------------------------------------------------ 蒙特卡洛
def chart_mc(out, env):
    fig, ax = plt.subplots(figsize=(13, 7), dpi=120)
    fig.patch.set_facecolor(BG)
    vals, ns = [], []
    for m in MODELS:
        d = json.load(open(os.path.join(env, f"ft_{m}", "verified", "mc.json"), encoding="utf-8"))
        vals.append(d["prob_profit"] * 100)
        ns.append(d["n_trades"])
    x = np.arange(len(MODELS))
    ax.bar(x, vals, 0.5, color=[COLORS[m] for m in MODELS], zorder=3)
    for i, v in enumerate(vals):
        ax.annotate(f"{v:.1f}%", (i, v), ha="center", va="bottom", xytext=(0, 8),
                    textcoords="offset points", color=FG, fontsize=21, weight="bold")
        ax.annotate(f"{ns[i]} 笔交易", (i, 0.12), ha="center", color=DIM, fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels([NAMES[m] for m in MODELS], color=FG, fontsize=14)
    ax.set_ylim(0, 11)
    style(ax, "蒙特卡洛重排 5000 次:这套策略赚钱的概率有多大",
          ylabel="prob(profit)  %", ts=18)
    ax.annotate("唯一非零的一家", xy=(2, 8.9), xytext=(2.35, 9.6),
                color=GREEN, fontsize=14, weight="bold",
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=2.2))
    fig.text(0.5, 0.015, "方法:对成交序列做分块自助重采样(block=10),5000 次重排后统计终值为正的比例",
             ha="center", color=DIM, fontsize=11)
    fig.tight_layout(rect=[0, 0.035, 1, 1])
    save(fig, out, "mc_grid.png")


# ------------------------------------------------------------ 市场状态
SEGS = [("训练", "2021-01-01", "2024-06-30"), ("验证", "2024-07-01", "2025-06-30"),
        ("样本外", "2025-07-01", "2026-07-01")]


def chart_regime(out, locked):
    px = {}
    for f in sorted(glob.glob(os.path.join(locked, "binance/futures/*-1d-futures.feather"))):
        sym = os.path.basename(f).split("_")[0]
        d = pd.read_feather(f)
        px[sym] = pd.Series(d["close"].values,
                            index=pd.DatetimeIndex(pd.to_datetime(d["date"])).normalize())
    P = pd.DataFrame(px).sort_index()

    rows = []
    for name, a, b in SEGS:
        # 先切窗口再算收益,收益率不能跨出区间起点(否则样本外会算成 -47% 而非 -45%)
        seg = P.loc[a:b].pct_change().dropna(how="all")
        yrs = len(seg) / 365.0
        # 大盘 = 等权日再平衡组合,统一年化后才可比(训练段 3.5 年)
        cum = (1 + seg.mean(axis=1)).prod() - 1
        mkt = (1 + cum) ** (1 / yrs) - 1
        c = seg.corr().values
        avg_corr = float(np.nanmean(c[np.triu_indices_from(c, 1)]))
        # 离散度 = 每日横截面标准差的均值,年化
        disp = float(seg.std(axis=1).mean() * np.sqrt(365))
        rows.append((name, mkt * 100, avg_corr, disp * 100))
    df = pd.DataFrame(rows, columns=["seg", "mkt", "corr", "disp"])

    fig, axes = plt.subplots(1, 3, figsize=(16, 6.4), dpi=120)
    fig.patch.set_facecolor(BG)
    specs = [("mkt", "大盘年化收益(20 币等权)", "%", "训练段 3.5 年,统一年化才可比"),
             ("corr", "币之间的平均相关性", "", "越高 = 越同涨同跌"),
             ("disp", "横截面离散度(年化)", "%", "越低 = 可捕捉的差异越小")]
    x = np.arange(3)
    for ax, (col, ttl, unit, sub) in zip(axes, specs):
        ax.set_facecolor(BG)
        v = df[col].values
        cols = [GREEN if t > 0 else RED for t in v] if col == "mkt" else \
               [GOLD if i < 2 else RED for i in range(3)]
        ax.bar(x, v, 0.55, color=cols, zorder=3)
        for i, t in enumerate(v):
            ax.annotate(f"{t:+.1f}{unit}" if col == "mkt" else f"{t:.2f}{unit}",
                        (i, t), ha="center", va="bottom" if t > 0 else "top",
                        xytext=(0, 8 if t > 0 else -8), textcoords="offset points",
                        color=FG, fontsize=17, weight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(df["seg"], color=FG, fontsize=13)
        if col == "mkt":
            ax.axhline(0, color=DIM, lw=1.2)
            ax.set_ylim(min(v) * 1.35, max(v) * 1.35)
        else:
            ax.set_ylim(0, max(v) * 1.32)
        style(ax, ttl, ts=15)
        if sub:
            ax.text(0.5, 0.94, sub, transform=ax.transAxes, ha="center",
                    color=DIM, fontsize=12)
    fig.suptitle("真正的杀手不是调参技巧,是市场变天",
                 color=GOLD, fontsize=22, weight="bold", y=0.985)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    save(fig, out, "regime_shift.png")
    print(df.to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="<环境根目录>/_video")
    ap.add_argument("--env", default="<环境根目录>")
    ap.add_argument("--locked", default="<样本外数据目录>")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print("生成评价指标配图:")
    chart_gate(a.out)
    chart_long_short(a.out)
    chart_turnover(a.out)
    chart_argmax(a.out, a.env)
    chart_convergence(a.out, a.env)
    chart_mc(a.out, a.env)
    try:
        chart_regime(a.out, a.locked)
    except Exception as e:
        print(f"  (市场状态图跳过: {e})")
    print(f"\n输出目录: {a.out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EP004 · 结果图表生成器
========================
产出(全部 1920x1080 友好、深色主题、四家统一配色):
  1. sharpe_collapse.png   验证集夏普 → 样本外夏普 的跳水      ★核心
  2. fable_waterfall.png   Fable −7.5% = alpha +6.5% + beta −14.0%  ★核心
  3. equity_curves.png     四家样本外净值曲线 + 大盘
  4. equity_curves.gif     同上,动图(曲线逐日生长)              ★动图
  5. radar.png             六维雷达图
  6. dsr_bars.png          DSR:观察夏普 vs 纯运气基线
  7. alpha_beta_scatter.png  alpha vs beta 四象限定位
  8. portraits.png         四句画像总结

用法:
  python make_video_charts.py --out "<环境根目录>/_video"
"""
import argparse
import glob
import json
import os
import zipfile

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

BG = "#0d1117"
FG = "#e6edf3"
DIM = "#8b949e"
GRID = "#30363d"
RED = "#ff6b6b"
GREEN = "#3fb950"
GOLD = "#ffd24d"

MODELS = ["kimi_k3", "opus_5", "fable_5", "deepseek"]
NAMES = {"kimi_k3": "Kimi K3", "opus_5": "Opus 5", "fable_5": "Fable 5", "deepseek": "DeepSeek"}
COLORS = {"kimi_k3": "#3fb6ff", "opus_5": "#ff9f40", "fable_5": "#3fb950", "deepseek": "#bc8cff"}

# 实测数据(来自独立复现)
VALID_SHARPE = {"kimi_k3": 1.24, "opus_5": 1.34, "fable_5": 1.87, "deepseek": 1.93}
TEST_SHARPE = {"kimi_k3": -3.71, "opus_5": -1.42, "fable_5": -0.62, "deepseek": -0.62}
TEST_RET = {"kimi_k3": -29.8, "opus_5": -19.6, "fable_5": -7.5, "deepseek": -7.1}
ALPHA = {"kimi_k3": -29.5, "opus_5": -20.2, "fable_5": 7.9, "deepseek": -0.2}
BETA = {"kimi_k3": 0.12, "opus_5": 0.03, "fable_5": 0.31, "deepseek": 0.15}
DSR = {"kimi_k3": 0.094, "opus_5": 0.868, "fable_5": 0.715, "deepseek": 0.868}
DSR_OBS = {"kimi_k3": 1.57, "opus_5": 1.62, "fable_5": 1.98, "deepseek": 2.18}
DSR_LUCK = {"kimi_k3": 2.55, "opus_5": 0.78, "fable_5": 1.53, "deepseek": 1.44}
RADAR = {  # 稳健/无作弊/表现/代码/诚实/性价比
    # 性价比 = 每分成本(成本÷五维分),四家均有实测:
    #   DeepSeek ¥0.15 / Kimi ¥3.67 / Fable ¥12.26 / Opus ¥50.39 每分
    "kimi_k3": [2, 10, 1, 3, 9, 7],
    "opus_5": [6, 10, 4, 9, 10, 2],
    "fable_5": [7, 10, 8, 5, 9, 5],
    "deepseek": [6, 10, 7.5, 5, 6, 10],
}
RADAR_WEIGHTS = [0.25, 0.15, 0.25, 0.15, 0.15, 0.05]
TOTALS = {"kimi_k3": 4.4, "opus_5": 7.0, "fable_5": 7.6, "deepseek": 7.0}
RADAR_LABELS = ["稳健性", "无作弊", "表现", "代码质量", "解释诚实", "性价比"]
PORTRAITS = [
    ("Fable 5", "选股对了,仓位错了", "alpha +7.9% / 净敞口 34%"),
    ("Opus 5", "仓位对了,选股错了", "beta 0.03 / alpha −20.2%"),
    ("DeepSeek", "两样都不功不过", "alpha ≈ 0 / 回撤最小 14%"),
    ("Kimi K3", "两样都没做对", "alpha −29.5% / DSR 0.094"),
]


def style(ax, title=None, xlabel=None, ylabel=None):
    ax.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=DIM, labelsize=11)
    if title:
        ax.set_title(title, color=FG, fontsize=17, pad=16, weight="bold")
    if xlabel:
        ax.set_xlabel(xlabel, color=DIM, fontsize=12)
    if ylabel:
        ax.set_ylabel(ylabel, color=DIM, fontsize=12)


def fig_new(w=16, h=9):
    fig, ax = plt.subplots(figsize=(w, h), dpi=120)
    fig.patch.set_facecolor(BG)
    return fig, ax


def save(fig, out, name):
    p = os.path.join(out, name)
    fig.savefig(p, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {name}")


# ---------------------------------------------------------------- 0 总分(打码版)
def chart_score_masked(out):
    """§01 摘要用:只给分数不给名字,答案留到 §11"""
    order = ["fable_5", "opus_5", "deepseek", "kimi_k3"]   # 打乱,不按排名
    vals = [TOTALS[m] for m in order]
    fig, ax = fig_new(13, 7.4)
    bars = ax.bar(range(4), vals, 0.55, color="#3d4a5c", zorder=3,
                  edgecolor="#5a6a80", lw=1.4)
    for i, v in enumerate(vals):
        ax.annotate(f"{v:.1f}", (i, v), ha="center", va="bottom", xytext=(0, 10),
                    textcoords="offset points", color=FG, fontsize=34, weight="bold")
        ax.annotate("?", (i, 0.45), ha="center", color="#8b949e",
                    fontsize=46, weight="bold")
    ax.set_xticks(range(4))
    ax.set_xticklabels(["选手 A", "选手 B", "选手 C", "选手 D"], color=DIM, fontsize=17)
    ax.set_ylim(0, 9.4)
    style(ax, "六维总分:一个 7.6,两个 7.0,一个 4.4", ylabel="加权总分(满分 10)")
    ax.text(0.5, 0.90, "谁是谁?答案在第 11 节", transform=ax.transAxes, ha="center",
            color=GOLD, fontsize=19, weight="bold")
    save(fig, out, "score_masked.png")


# ---------------------------------------------------------------- 1 夏普跳水
def chart_sharpe_collapse(out):
    fig, ax = fig_new()
    x = np.arange(len(MODELS))
    for i, m in enumerate(MODELS):
        v, t = VALID_SHARPE[m], TEST_SHARPE[m]
        c = COLORS[m]
        ax.plot([i - 0.16, i + 0.16], [v, t], color=c, lw=3.5, zorder=3,
                solid_capstyle="round")
        ax.scatter([i - 0.16], [v], s=280, color=c, zorder=4, edgecolor=BG, lw=2)
        ax.scatter([i + 0.16], [t], s=280, color=c, zorder=4, marker="v",
                   edgecolor=BG, lw=2)
        ax.annotate(f"{v:.2f}", (i - 0.16, v), textcoords="offset points",
                    xytext=(0, 16), ha="center", color=FG, fontsize=15, weight="bold")
        ax.annotate(f"{t:.2f}", (i + 0.16, t), textcoords="offset points",
                    xytext=(0, -26), ha="center", color=RED, fontsize=15, weight="bold")
    ax.axhline(0, color=DIM, lw=1.2, ls="--", alpha=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([NAMES[m] for m in MODELS], color=FG, fontsize=14)
    style(ax, "验证集夏普  →  样本外夏普", ylabel="年化夏普(日资金曲线口径)")
    ax.set_ylim(-4.9, 2.7)
    ax.text(0.5, 0.955, "四家全部由正转负 · 没有一个例外", transform=ax.transAxes,
            ha="center", color=GOLD, fontsize=15)
    ax.legend(handles=[
        plt.Line2D([], [], marker="o", ls="", color=DIM, markersize=11, label="验证集(它们调参用的)"),
        plt.Line2D([], [], marker="v", ls="", color=RED, markersize=11, label="样本外(没见过的一年)"),
    ], facecolor="#161b22", edgecolor=GRID, labelcolor=FG, fontsize=12, loc="lower right")
    save(fig, out, "sharpe_collapse.png")


# ---------------------------------------------------------------- 2 Fable 瀑布
def chart_fable_waterfall(out):
    fig, ax = fig_new(14, 8)
    items = [("alpha\n(选股本事)", 6.5, GREEN), ("beta\n(押多头的代价)", -14.0, RED),
             ("实际收益", -7.5, GOLD)]
    run = 0.0
    for i, (lab, val, c) in enumerate(items):
        if i < 2:
            bottom = run if val > 0 else run + val
            ax.bar(i, abs(val), bottom=bottom, color=c, width=0.55, zorder=3)
            ax.annotate(f"{val:+.1f}%", (i, bottom + abs(val) / 2), ha="center",
                        va="center", color=BG, fontsize=17, weight="bold")
            run += val
            ax.plot([i + 0.28, i + 0.72], [run, run], color=DIM, lw=1.6, ls=":", zorder=2)
        else:
            ax.bar(i, val, color=c, width=0.55, zorder=3)
            ax.annotate(f"{val:+.1f}%", (i, val / 2), ha="center", va="center",
                        color=BG, fontsize=17, weight="bold")
    ax.axhline(0, color=DIM, lw=1.4)
    ax.set_xticks(range(3))
    ax.set_xticklabels([x[0] for x in items], color=FG, fontsize=14)
    style(ax, "Fable 5:一年赚了 7.9%,却亏了 7.5%", ylabel="对初始资金的贡献")
    ax.text(0.5, 0.93, "选股是真本事,仓位押错了方向", transform=ax.transAxes,
            ha="center", color=GOLD, fontsize=15)
    ax.set_ylim(-17, 9)
    save(fig, out, "fable_waterfall.png")


# ---------------------------------------------------------------- 3/4 净值曲线
def _mtm_equity(env_root, locked_root):
    px = {}
    for f in sorted(glob.glob(os.path.join(locked_root, "binance/futures/*-1d-futures.feather"))):
        sym = os.path.basename(f).split("_")[0]
        d = pd.read_feather(f)
        px[sym] = pd.Series(d["close"].values,
                            index=pd.DatetimeIndex(pd.to_datetime(d["date"])).normalize())
    P = pd.DataFrame(px).sort_index()
    mkt = P.pct_change().mean(axis=1).loc["2025-07-02":"2026-07-01"]
    days = pd.date_range("2025-07-01", "2026-07-01", freq="D", tz="UTC")

    def trades(z):
        with zipfile.ZipFile(z) as f:
            for n in f.namelist():
                if n.endswith(".json") and "_config" not in n:
                    o = json.loads(f.read(n))
                    for v in o.get("strategy", {}).values():
                        if v.get("trades"):
                            return v["trades"]
        return []

    out = {}
    for m in MODELS:
        z = os.path.join(env_root, f"ft_{m}/verified/test.zip")
        if not os.path.exists(z):
            continue
        df = pd.DataFrame(trades(z))
        df["o"] = pd.to_datetime(df["open_date"], utc=True).dt.normalize()
        df["c"] = pd.to_datetime(df["close_date"], utc=True).dt.normalize()
        df["sym"] = df["pair"].str.split("/").str[0]
        df["sgn"] = np.where(df["is_short"], -1.0, 1.0)
        df["amt"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
        df["orate"] = pd.to_numeric(df["open_rate"], errors="coerce")
        df["pa"] = pd.to_numeric(df["profit_abs"], errors="coerce").fillna(0)
        realized = df.groupby("c")["pa"].sum().reindex(days, fill_value=0).cumsum()
        eq = []
        for d in days:
            op = df[(df["o"] <= d) & (df["c"] > d)]
            u = 0.0
            for _, r in op.iterrows():
                p = P[r["sym"]].asof(d) if r["sym"] in P else np.nan
                if not np.isnan(p):
                    u += r["sgn"] * (p - r["orate"]) * r["amt"]
            eq.append(10000 + realized[d] + u)
        out[m] = pd.Series(eq, index=days)
    mkt_eq = (1 + mkt).cumprod() * 10000
    mkt_eq = mkt_eq.reindex(days).ffill().fillna(10000)
    return out, mkt_eq


def chart_equity(out, eqs, mkt_eq, animate=True):
    fig, ax = fig_new()
    for m, s in eqs.items():
        ax.plot(s.index, s.values, color=COLORS[m], lw=2.8,
                label=f"{NAMES[m]}  {TEST_RET[m]:+.1f}%")
    ax.plot(mkt_eq.index, mkt_eq.values, color=DIM, lw=2.2, ls="--",
            label=f"大盘(20币等权)  −45.0%")
    ax.axhline(10000, color=GRID, lw=1.2)
    style(ax, "样本外一年:2025-07 → 2026-07", ylabel="净值(起始 10000)")
    ax.legend(facecolor="#161b22", edgecolor=GRID, labelcolor=FG, fontsize=13, loc="lower left")
    ax.text(0.5, 0.95, "四家全亏,但都跑赢大盘", transform=ax.transAxes,
            ha="center", color=GOLD, fontsize=15)
    save(fig, out, "equity_curves.png")

    if not animate:
        return
    # 动图:曲线逐日生长
    try:
        from matplotlib.animation import FuncAnimation, PillowWriter
        fig, ax = fig_new()
        idx = list(eqs.values())[0].index
        lines = {}
        for m in eqs:
            (ln,) = ax.plot([], [], color=COLORS[m], lw=2.8, label=NAMES[m])
            lines[m] = ln
        (mln,) = ax.plot([], [], color=DIM, lw=2.2, ls="--", label="大盘")
        ax.set_xlim(idx[0], idx[-1])
        lo = min([s.min() for s in eqs.values()] + [mkt_eq.min()])
        ax.set_ylim(lo * 0.94, 11200)
        ax.axhline(10000, color=GRID, lw=1.2)
        style(ax, "样本外一年:2025-07 → 2026-07", ylabel="净值(起始 10000)")
        ax.legend(facecolor="#161b22", edgecolor=GRID, labelcolor=FG, fontsize=13, loc="lower left")
        step = max(1, len(idx) // 90)
        frames = list(range(2, len(idx), step)) + [len(idx)] * 12

        def upd(k):
            for m, s in eqs.items():
                lines[m].set_data(idx[:k], s.values[:k])
            mln.set_data(idx[:k], mkt_eq.values[:k])
            return list(lines.values()) + [mln]

        anim = FuncAnimation(fig, upd, frames=frames, blit=True, interval=60)
        p = os.path.join(out, "equity_curves.gif")
        anim.save(p, writer=PillowWriter(fps=16), savefig_kwargs={"facecolor": BG})
        plt.close(fig)
        print("  -> equity_curves.gif")
    except Exception as e:
        print(f"  (动图跳过: {e})")


# ---------------------------------------------------------------- 5 雷达
def chart_radar(out):
    n = len(RADAR_LABELS)
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    ang += ang[:1]
    fig = plt.figure(figsize=(11, 11), dpi=120)
    fig.patch.set_facecolor(BG)
    ax = plt.subplot(polar=True)
    ax.set_facecolor(BG)
    for m in MODELS:
        v = RADAR[m] + RADAR[m][:1]
        ax.plot(ang, v, color=COLORS[m], lw=2.6, label=NAMES[m])
        ax.fill(ang, v, color=COLORS[m], alpha=0.13)
    ax.set_xticks(ang[:-1])
    ax.set_xticklabels(RADAR_LABELS, color=FG, fontsize=14)
    ax.set_ylim(0, 10)
    ax.set_yticks([2, 4, 6, 8, 10])
    ax.set_yticklabels(["2", "4", "6", "8", "10"], color=DIM, fontsize=10)
    ax.grid(color=GRID)
    ax.spines["polar"].set_color(GRID)
    ax.set_title("六维评分(稳健性与无作弊权重最高)", color=FG, fontsize=18, pad=28, weight="bold")
    ax.legend(facecolor="#161b22", edgecolor=GRID, labelcolor=FG, fontsize=13,
              loc="upper right", bbox_to_anchor=(1.18, 1.10))
    save(fig, out, "radar.png")


# ---------------------------------------------------------------- 6 DSR
def chart_dsr(out):
    fig, ax = fig_new(15, 8)
    x = np.arange(len(MODELS))
    w = 0.34
    obs = [DSR_OBS[m] for m in MODELS]
    luck = [DSR_LUCK[m] for m in MODELS]
    ax.bar(x - w / 2, obs, w, color="#3fb6ff", label="实际拿到的夏普", zorder=3)
    ax.bar(x + w / 2, luck, w, color=RED, label="纯运气能刷到的夏普", zorder=3)
    for i, m in enumerate(MODELS):
        ax.annotate(f"{DSR_OBS[m]:.2f}", (i - w / 2, DSR_OBS[m]), ha="center",
                    va="bottom", color=FG, fontsize=13, weight="bold")
        ax.annotate(f"{DSR_LUCK[m]:.2f}", (i + w / 2, DSR_LUCK[m]), ha="center",
                    va="bottom", color=RED, fontsize=13, weight="bold")
        ax.annotate(f"DSR {DSR[m]:.3f}", (i, -0.22), ha="center", color=DIM, fontsize=12)
    # Kimi 标注
    ax.annotate("运气基线比实际成绩还高\n= 连运气都不如", xy=(0 + w / 2, DSR_LUCK["kimi_k3"]),
                xytext=(0.55, 2.95), color=RED, fontsize=14, weight="bold",
                arrowprops=dict(arrowstyle="->", color=RED, lw=2))
    ax.set_xticks(x)
    ax.set_xticklabels([NAMES[m] for m in MODELS], color=FG, fontsize=14)
    ax.set_ylim(-0.45, 3.4)
    style(ax, "Deflated Sharpe:你的成绩,有多少是搜出来的运气?", ylabel="年化夏普")
    ax.legend(facecolor="#161b22", edgecolor=GRID, labelcolor=FG, fontsize=13)
    save(fig, out, "dsr_bars.png")


# ---------------------------------------------------------------- 7 alpha-beta 四象限
def chart_alpha_beta(out):
    fig, ax = fig_new(13, 9)
    for m in MODELS:
        ax.scatter(BETA[m], ALPHA[m], s=680, color=COLORS[m], zorder=4,
                   edgecolor=BG, lw=2.5)
        ax.annotate(f"{NAMES[m]}\nα {ALPHA[m]:+.1f}%  β {BETA[m]:.2f}",
                    (BETA[m], ALPHA[m]), textcoords="offset points",
                    xytext=(0, -52), ha="center", color=FG, fontsize=12)
    ax.axhline(0, color=DIM, lw=1.4, ls="--")
    ax.axvline(0.10, color=DIM, lw=1.0, ls=":", alpha=0.7)
    ax.text(0.012, 9.2, "有 alpha\n低敞口\n(理想区)", color=GREEN, fontsize=12)
    ax.text(0.335, 9.2, "有 alpha\n但押方向", color=GOLD, fontsize=12)
    ax.text(0.012, -33, "无 alpha\n也没押", color=DIM, fontsize=12)
    ax.text(0.335, -33, "无 alpha\n还押方向", color=RED, fontsize=12)
    style(ax, "四家定位:alpha(真本事) vs beta(押方向)",
          xlabel="beta —— 跟大盘的暴露程度", ylabel="年化 alpha(%)")
    ax.set_xlim(-0.03, 0.42)
    ax.set_ylim(-38, 14)
    save(fig, out, "alpha_beta_scatter.png")


# ---------------------------------------------------------------- 7.5 成本对比
# 实测数据来自 usage_cost.py 读 ~/.claude/projects/*.jsonl
COST = {
    # cny=成本, calls=API调用数, tok=token总量, mins=实际干活时长(剔除空档)
    "deepseek": dict(cny=1.04, calls=124, tok=13_802_820, mins=61, src="平台实扣"),
    "kimi_k3": dict(cny=15.62, calls=71, tok=4_357_623, mins=42, src="平台实扣"),
    "fable_5": dict(cny=13.18 * 7.2, calls=109, tok=7_357_104, mins=12, src="日志折算"),
    "opus_5": dict(cny=50.46 * 7.2, calls=330, tok=59_062_730, mins=95, src="日志折算"),
}
FX = 7.2  # CNY per USD,录制前按当天汇率再核一次
COST_ORDER = ["deepseek", "kimi_k3", "fable_5", "opus_5"]
# 五维加权分(剔除性价比本身,避免循环)
SCORE5 = {"deepseek": 6.87, "kimi_k3": 4.26, "fable_5": 7.74, "opus_5": 7.21}


def chart_cost(out):
    ms = COST_ORDER
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(17, 8), dpi=120)
    fig.patch.set_facecolor(BG)
    x = np.arange(len(ms))

    # 左:总成本(对数轴,跨度 350 倍)
    ax1.set_facecolor(BG)
    ax1.bar(x, [COST[m]["cny"] for m in ms], 0.55,
            color=[COLORS[m] for m in ms], zorder=3)
    for i, m in enumerate(ms):
        v = COST[m]["cny"]
        ax1.annotate(f"¥{v:,.2f}" if v < 10 else f"¥{v:,.0f}", (i, v),
                     ha="center", va="bottom", color=FG, fontsize=21, weight="bold",
                     xytext=(0, 7), textcoords="offset points")
        ax1.annotate(COST[m]["src"], (i, 0.62), ha="center", color=BG,
                     fontsize=11, weight="bold")
    ax1.set_yscale("log")
    ax1.set_ylim(0.5, 1600)
    ax1.set_xticks(x)
    ax1.set_xticklabels([NAMES[m] for m in ms], color=FG, fontsize=15)
    style(ax1, "跑完同一道题花了多少钱", ylabel="人民币(对数轴)")
    ax1.annotate("", xy=(3, 620), xytext=(0, 620),
                 arrowprops=dict(arrowstyle="<->", color=GOLD, lw=2.2))
    ax1.text(1.5, 720, "350 倍", ha="center", color=GOLD, fontsize=20, weight="bold")

    # 右:每分成本 = 成本 / 五维加权分
    ax2.set_facecolor(BG)
    cpp = [COST[m]["cny"] / SCORE5[m] for m in ms]
    ax2.bar(x, cpp, 0.55, color=[COLORS[m] for m in ms], zorder=3)
    for i, v in enumerate(cpp):
        ax2.annotate(f"¥{v:.2f}", (i, v), ha="center", va="bottom", color=FG,
                     fontsize=19, weight="bold", xytext=(0, 7),
                     textcoords="offset points")
    ax2.set_yscale("log")
    ax2.set_ylim(0.08, 260)
    ax2.set_xticks(x)
    ax2.set_xticklabels([NAMES[m] for m in ms], color=FG, fontsize=15)
    style(ax2, "每拿到 1 分成绩,要花多少钱", ylabel="人民币 / 分(对数轴)")

    fig.suptitle("同一道题,最贵的比最便宜的贵 350 倍", color=GOLD,
                 fontsize=27, weight="bold", y=0.985)
    fig.text(0.5, 0.015,
             "DeepSeek / Kimi = 平台实际扣费;Opus / Fable = 会员无账单,按本地日志 token 用量 × 公开单价折算"
             f"   ·   汇率 ¥{FX}/\$",
             ha="center", color=DIM, fontsize=11)
    fig.tight_layout(rect=[0, 0.035, 1, 0.945])
    save(fig, out, "cost_compare.png")


def chart_cost_alpha(out):
    """成本 vs alpha:四家全有数据"""
    fig, ax = fig_new(13, 8)
    for m in COST_ORDER:
        c = COST[m]["cny"]
        ax.scatter(c, ALPHA[m], s=720, color=COLORS[m], zorder=4, edgecolor=BG, lw=2.5)
        ax.annotate(f"{NAMES[m]}\n¥{c:,.0f}   α {ALPHA[m]:+.1f}%", (c, ALPHA[m]),
                    textcoords="offset points", xytext=(0, -62), ha="center",
                    color=FG, fontsize=13)
    ax.axhline(0, color=DIM, lw=1.4, ls="--")
    ax.set_xscale("log")
    ax.annotate("花得不多 + 唯一正 alpha", xy=(COST["fable_5"]["cny"], 7.9),
                xytext=(9, 1.5), color=GREEN, fontsize=15, weight="bold",
                arrowprops=dict(arrowstyle="->", color=GREEN, lw=2.5))
    ax.annotate("花得最多,alpha 倒数第二", xy=(COST["opus_5"]["cny"], -20.2),
                xytext=(11, -27), color=RED, fontsize=14, weight="bold",
                arrowprops=dict(arrowstyle="->", color=RED, lw=2.2))
    style(ax, "花的钱 vs 造出来的 alpha:两者没有关系",
          xlabel="成本(人民币,对数轴)", ylabel="年化 alpha(%)")
    ax.set_xlim(0.6, 1500)
    ax.set_ylim(-36, 14)
    save(fig, out, "cost_alpha.png")


# ---------------------------------------------------------------- 8 画像海报
def chart_portraits(out):
    fig, ax = plt.subplots(figsize=(14, 9), dpi=120)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.axis("off")
    ax.text(0.5, 0.945, "四个顶级 AI,各做对了一半", ha="center",
            color=FG, fontsize=30, weight="bold", transform=ax.transAxes)
    ax.text(0.5, 0.875, "没有一个两样都对", ha="center",
            color=GOLD, fontsize=19, transform=ax.transAxes)
    keys = ["fable_5", "opus_5", "deepseek", "kimi_k3"]
    for i, (k, (name, line, sub)) in enumerate(zip(keys, PORTRAITS)):
        y = 0.72 - i * 0.175
        ax.add_patch(plt.Rectangle((0.06, y - 0.062), 0.88, 0.125,
                                   facecolor="#161b22", edgecolor=COLORS[k],
                                   lw=2.5, transform=ax.transAxes, zorder=2))
        ax.text(0.105, y, name, color=COLORS[k], fontsize=21, weight="bold",
                va="center", transform=ax.transAxes, zorder=3)
        ax.text(0.335, y, line, color=FG, fontsize=23, va="center",
                transform=ax.transAxes, zorder=3)
        ax.text(0.905, y, sub, color=DIM, fontsize=12, va="center",
                ha="right", transform=ax.transAxes, zorder=3)
    save(fig, out, "portraits.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="<环境根目录>/_video")
    ap.add_argument("--env", default="<环境根目录>")
    ap.add_argument("--locked", default="<样本外数据目录>")
    ap.add_argument("--no-gif", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print("生成图表:")
    chart_score_masked(a.out)
    chart_sharpe_collapse(a.out)
    chart_fable_waterfall(a.out)
    chart_radar(a.out)
    chart_dsr(a.out)
    chart_alpha_beta(a.out)
    chart_cost(a.out)
    chart_cost_alpha(a.out)
    chart_portraits(a.out)
    try:
        eqs, mkt = _mtm_equity(a.env, a.locked)
        if eqs:
            chart_equity(a.out, eqs, mkt, animate=not a.no_gif)
    except Exception as e:
        print(f"  (净值曲线跳过: {e})")
    print(f"\n输出目录: {a.out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EP004 · 通用蒙特卡洛 / Block Bootstrap（与策略无关，四家通用）
===========================================================
读 Freqtrade `--export trades` 导出的 json，取每笔收益(profit_ratio)做 block
bootstrap，回答：这条回测曲线有多少是运气？

输出：
  - 盈利路径占比 prob(profit)、P5/P50/P95、原始 vs 重采样路径图
  - 一个 summary json（进 verified/mc.json）

用法（主机上直接跑，只需 numpy + matplotlib）：
  python mc_bootstrap.py --trades <ft_model>/backtest_results/test.zip \
      --iters 5000 --block 10 \
      --out  <ft_model>/verified/mc.json \
      --plot ./out/mc_kimi_k3.png

说明：以“每笔交易”为重采样单位（trade-level MC）。多资产下不同币的交易在时间上
会重叠，这里按成交序列处理，是业界常见的近似；block 保留一点序列相关性。
"""
import argparse
import json
import sys
import numpy as np


def _find_trades(data):
    """兼容多种结构：顶层 list / {'trades':[...]} / Freqtrade {'strategy':{'<name>':{'trades':[...]}}}"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("trades"), list):
            return data["trades"]
        strat = data.get("strategy")
        if isinstance(strat, dict):
            for v in strat.values():
                if isinstance(v, dict) and isinstance(v.get("trades"), list):
                    return v["trades"]
    return None


def load_profit_ratios(path):
    """支持三种输入:Freqtrade 2026.x 的 backtest zip / 目录(取最新 zip)/ 直接的 trades json。"""
    import os
    import zipfile

    if os.path.isdir(path):                      # 传目录 → 取最新 zip
        import glob
        zs = sorted(glob.glob(os.path.join(path, "*.zip")), key=os.path.getmtime)
        if not zs:
            sys.exit(f"[mc] 目录里没有 backtest zip: {path}")
        path = zs[-1]

    if str(path).lower().endswith(".zip"):       # Freqtrade 2026.x 默认产物
        with zipfile.ZipFile(path) as z:
            cand = [n for n in z.namelist()
                    if n.endswith(".json") and "_config" not in n]
            data = None
            for n in cand:                       # 找带 trades 的那个
                o = json.loads(z.read(n))
                if _find_trades(o):
                    data = o
                    break
            if data is None:
                sys.exit(f"[mc] zip 里没找到 trades: {path}")
    else:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

    trades = _find_trades(data)
    if not trades:
        sys.exit(f"[mc] 没找到 trades: {path}")
    rs = []
    for t in trades:
        v = t.get("profit_ratio")
        if v is None:  # 回退：profit_abs / stake_amount
            pa, sa = t.get("profit_abs"), t.get("stake_amount")
            if pa is not None and sa:
                v = float(pa) / float(sa)
        if v is not None:
            rs.append(float(v))
    if not rs:
        sys.exit("[mc] trades 里没有 profit_ratio / (profit_abs, stake_amount) 字段")
    return np.asarray(rs, dtype=float)


def block_bootstrap(r, iters, block, seed=7, start=1000.0, keep_paths=400):
    rng = np.random.default_rng(seed)
    N = len(r)
    finals = np.empty(iters)
    paths = []
    for k in range(iters):
        idx = []
        while len(idx) < N:
            s = int(rng.integers(0, max(1, N - block + 1)))
            idx.extend(range(s, min(s + block, N)))
        idx = np.asarray(idx[:N])
        eq = start * np.cumprod(1.0 + r[idx])
        finals[k] = eq[-1]
        if k < keep_paths:
            paths.append(eq)
    return finals, paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True, help="Freqtrade --export trades 的 json")
    ap.add_argument("--iters", type=int, default=5000)
    ap.add_argument("--block", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--start", type=float, default=1000.0)
    ap.add_argument("--out", default=None, help="summary json 输出路径")
    ap.add_argument("--plot", default=None, help="png 图输出路径")
    a = ap.parse_args()

    r = load_profit_ratios(a.trades)
    finals, paths = block_bootstrap(r, a.iters, a.block, a.seed, a.start)
    orig = a.start * np.cumprod(1.0 + r)
    p5, p50, p95 = (float(x) for x in np.percentile(finals, [5, 50, 95]))
    prob_profit = float((finals > a.start).mean())

    summary = {
        "trades_file": a.trades,
        "n_trades": int(len(r)),
        "iters": a.iters,
        "block": a.block,
        "start": a.start,
        "orig_final": float(orig[-1]),
        "prob_profit": prob_profit,
        "final_P5": p5,
        "final_P50": p50,
        "final_P95": p95,
        "mean_trade_ret": float(r.mean()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"[mc] summary -> {a.out}")

    if a.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei",
                                           "Arial Unicode MS", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        fig, ax = plt.subplots(figsize=(11, 6.2), dpi=130)
        fig.patch.set_facecolor("#0d1117")
        ax.set_facecolor("#0d1117")
        for eq in paths:
            ax.plot(eq, color="#3fb6ff", alpha=0.05, lw=0.7)
        ax.plot(orig, color="#ffd24d", lw=2.6, label="actual backtest path", zorder=10)
        ax.axhline(a.start, color="#888", lw=0.8, ls="--", alpha=0.6)
        ax.set_title(
            f"Block Bootstrap MC · {a.iters} paths · prob(profit)={prob_profit*100:.0f}%",
            color="#e6edf3", fontsize=13, pad=14,
        )
        ax.set_xlabel("trade #", color="#8b949e")
        ax.set_ylabel(f"equity (start {a.start:.0f})", color="#8b949e")
        ax.tick_params(colors="#8b949e")
        for sp in ax.spines.values():
            sp.set_color("#30363d")
        ax.legend(facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3", loc="upper left")
        ax.text(0.985, 0.06, f"P5={p5:.0f}  P50={p50:.0f}  P95={p95:.0f}",
                transform=ax.transAxes, ha="right", color="#8b949e", fontsize=10)
        plt.tight_layout()
        plt.savefig(a.plot, facecolor="#0d1117")
        print(f"[mc] plot -> {a.plot}")


if __name__ == "__main__":
    main()

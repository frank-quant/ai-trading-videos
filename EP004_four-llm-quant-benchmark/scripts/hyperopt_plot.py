#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EP004 · hyperopt 收敛 + 过拟合可视化（读模型交付的 hyperopt_results.json）
======================================================================
输入 schema（见 EP004_测试题与Prompt.md）：
  { "model": "...", "n_epochs": <实际轮数>,
    "trials": [ {"epoch": i, "params": {...},
                 "train_sharpe": .., "valid_sharpe": ..}, ... ] }
（兼容 train_score/valid_score 命名。）

出两张图：
  1) 收敛：每轮 valid 散点 + “到目前为止最优(valid)”折线 → 轮数够不够、何时最优
  2) 过拟合：train(x) vs valid(y) 散点 + 对角线 → 点越往对角线右下方偏 = 训练好验证差 = 过拟合
并打印：最优轮、最优 valid、该点的 train−valid 落差（落差越大越过拟合）。

用法（主机上直接跑）：
  python hyperopt_plot.py --input <ft_model>/hyperopt_results.json \
      --outdir ./out --tag kimi_k3
"""
import argparse
import json
import os
import sys
import numpy as np


def load_trials(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    trials = data.get("trials") if isinstance(data, dict) else data
    if not trials:
        sys.exit(f"[hopt] 没找到 trials: {path}")
    tr, va, ep = [], [], []
    for i, t in enumerate(trials, 1):
        tv = t.get("train_sharpe", t.get("train_score"))
        vv = t.get("valid_sharpe", t.get("valid_score"))
        if tv is None or vv is None:
            continue
        tr.append(float(tv))
        va.append(float(vv))
        ep.append(int(t.get("epoch", i)))
    if not va:
        sys.exit("[hopt] trials 里没有 train_sharpe/valid_sharpe（或 *_score）")
    order = np.argsort(ep)
    return (np.asarray(ep)[order], np.asarray(tr)[order], np.asarray(va)[order],
            data.get("model", "model"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="模型交付的 hyperopt_results.json")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--tag", default="model", help="输出文件名前缀，如 kimi_k3")
    a = ap.parse_args()

    ep, tr, va, model = load_trials(a.input)
    os.makedirs(a.outdir, exist_ok=True)

    best_so_far = np.maximum.accumulate(va)   # valid 越高越好
    best_i = int(np.argmax(va))
    best_epoch = int(ep[best_i])
    gap = float(tr[best_i] - va[best_i])       # 最优点的 train−valid 落差

    # 末段是否走平：最后 20% 的最优改善
    tail = best_so_far[int(len(best_so_far) * 0.8):]
    if len(tail) and tail[0] != 0:
        improve = (tail[-1] - tail[0]) / abs(tail[0])
    else:
        improve = 0.0
    verdict = "已基本走平，轮数够用" if abs(improve) < 0.02 else "末段仍在升，可加轮数"

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei",
                                       "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    # ---- 图1：收敛 ----
    fig, ax = plt.subplots(figsize=(11, 6), dpi=130)
    fig.patch.set_facecolor("#0d1117"); ax.set_facecolor("#0d1117")
    ax.scatter(ep, va, s=6, color="#3fb6ff", alpha=0.25, label="每轮 valid sharpe")
    ax.plot(ep, best_so_far, color="#ffd24d", lw=2.4, label="到目前为止最优(valid)")
    ax.axvline(best_epoch, color="#ff6b6b", lw=1.2, ls="--", label=f"最优在第 {best_epoch} 轮")
    ax.set_title(f"{model} · hyperopt 收敛 · 共 {len(ep)} 轮 · valid sharpe 越高越好",
                 color="#e6edf3", fontsize=13, pad=14)
    ax.set_xlabel("epoch", color="#8b949e"); ax.set_ylabel("valid sharpe", color="#8b949e")
    ax.tick_params(colors="#8b949e")
    for s in ax.spines.values(): s.set_color("#30363d")
    ax.legend(facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3")
    ax.text(0.985, 0.06, f"最优 valid={va[best_i]:.3f}  末段改善={improve*100:.1f}%  → {verdict}",
            transform=ax.transAxes, ha="right", color="#8b949e", fontsize=10)
    plt.tight_layout()
    p1 = os.path.join(a.outdir, f"convergence_{a.tag}.png")
    plt.savefig(p1, facecolor="#0d1117"); plt.close(fig)

    # ---- 图2：过拟合散点 train vs valid ----
    fig, ax = plt.subplots(figsize=(7.6, 7), dpi=130)
    fig.patch.set_facecolor("#0d1117"); ax.set_facecolor("#0d1117")
    sc = ax.scatter(tr, va, s=12, c=ep, cmap="viridis", alpha=0.6)
    lo = float(min(tr.min(), va.min())); hi = float(max(tr.max(), va.max()))
    ax.plot([lo, hi], [lo, hi], color="#ff6b6b", lw=1.4, ls="--", label="train = valid（不过拟合线）")
    ax.scatter([tr[best_i]], [va[best_i]], s=90, color="#ffd24d",
               edgecolor="#0d1117", zorder=10, label=f"选中点(落差 {gap:.2f})")
    ax.set_title(f"{model} · 过拟合体检 · 点在对角线右下方=训练好验证差",
                 color="#e6edf3", fontsize=12, pad=14)
    ax.set_xlabel("train sharpe", color="#8b949e"); ax.set_ylabel("valid sharpe", color="#8b949e")
    ax.tick_params(colors="#8b949e")
    for s in ax.spines.values(): s.set_color("#30363d")
    cb = plt.colorbar(sc, ax=ax); cb.set_label("epoch", color="#8b949e")
    cb.ax.yaxis.set_tick_params(color="#8b949e")
    plt.setp(plt.getp(cb.ax.axes, "yticklabels"), color="#8b949e")
    ax.legend(facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3", loc="upper left")
    plt.tight_layout()
    p2 = os.path.join(a.outdir, f"overfit_{a.tag}.png")
    plt.savefig(p2, facecolor="#0d1117"); plt.close(fig)

    print(json.dumps({
        "model": model, "tag": a.tag, "n_epochs": int(len(ep)),
        "best_epoch": best_epoch,
        "best_valid_sharpe": float(va[best_i]),
        "train_at_best": float(tr[best_i]),
        "train_minus_valid_gap": gap,
        "tail_improve_pct": float(improve * 100), "verdict": verdict,
        "plots": [p1, p2],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

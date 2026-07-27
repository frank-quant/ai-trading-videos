"""
EP003 · hyperopt 收敛曲线
====================================
读取 Freqtrade 的 hyperopt 结果，画出「到目前为止的最优 loss vs epoch」，
用来回答一个问题：800 轮到底够不够？

- 曲线早早走平  → 够了，后面纯陪跑（"我没跑满 10000 轮也没关系"的硬证据）
- 到 800 还在降 → 没收敛，但要在片里讲清：降的是"样本内更贴合"，
                   这正是过拟合的方向，所以我故意没追。

用法（在容器里跑）：
  cd <你的 freqtrade 工作目录>
  docker compose run --rm --entrypoint bash freqtrade -c \
    "pip install -q matplotlib; python /freqtrade/user_data/plot_convergence.py"

先把本文件复制到 user_data/ 下（脚本读的是容器内路径）。
"""
import glob, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULT_DIR = "/freqtrade/user_data/hyperopt_results"
OUT = "/freqtrade/user_data/hyperopt_convergence.png"


def load_epochs():
    """优先用 Freqtrade 自带的 loader，失败则回退到 pickle。"""
    files = sorted(glob.glob(os.path.join(RESULT_DIR, "*.fthypt")) +
                   glob.glob(os.path.join(RESULT_DIR, "*.pickle")))
    if not files:
        raise SystemExit(f"没找到 hyperopt 结果，检查 {RESULT_DIR}")
    latest = max(files, key=os.path.getmtime)
    print("读取:", latest)
    try:
        from freqtrade.optimize.hyperopt_tools import HyperoptTools
        epochs = HyperoptTools.load_filtered_results(latest, {})[0]
    except Exception as e:
        print("Freqtrade loader 失败，回退 pickle:", e)
        import pickle
        with open(latest, "rb") as f:
            epochs = pickle.load(f)
    return epochs


def main():
    epochs = load_epochs()
    losses = [ep["loss"] for ep in epochs if ep.get("loss") is not None]
    n = len(losses)
    if n == 0:
        raise SystemExit("结果里没有 loss 字段")
    best_so_far = np.minimum.accumulate(losses)          # 到第 i 轮的最优
    best_epoch = int(np.argmin(losses)) + 1

    fig, ax = plt.subplots(figsize=(11, 6), dpi=130)
    fig.patch.set_facecolor("#0d1117"); ax.set_facecolor("#0d1117")
    x = np.arange(1, n + 1)
    ax.scatter(x, losses, s=6, color="#3fb6ff", alpha=0.25, label="每轮 loss")
    ax.plot(x, best_so_far, color="#ffd24d", lw=2.4, label="到目前为止的最优")
    ax.axvline(best_epoch, color="#ff6b6b", lw=1.2, ls="--",
               label=f"最优出现在第 {best_epoch} 轮")

    ax.set_title(f"hyperopt 收敛曲线 · 共 {n} 轮 · loss 越低越好",
                 color="#e6edf3", fontsize=13, pad=14)
    ax.set_xlabel("epoch", color="#8b949e")
    ax.set_ylabel("loss", color="#8b949e")
    ax.tick_params(colors="#8b949e")
    for s in ax.spines.values(): s.set_color("#30363d")
    ax.legend(facecolor="#161b22", edgecolor="#30363d", labelcolor="#e6edf3")

    # 走平判断：最后 20% 的最优改善幅度
    tail = best_so_far[int(n * 0.8):]
    improve = (tail[0] - tail[-1]) / abs(tail[0]) if tail[0] != 0 else 0
    verdict = "已基本走平，800 轮够用" if abs(improve) < 0.02 else "末段仍在下降，尚未收敛"
    ax.text(0.985, 0.06, f"最优={best_so_far[-1]:.4f}  末段改善={improve*100:.1f}%  → {verdict}",
            transform=ax.transAxes, ha="right", color="#8b949e", fontsize=10)

    plt.tight_layout()
    plt.savefig(OUT, facecolor="#0d1117")
    print(f"SAVED {OUT}")
    print(f"总轮数={n} 最优轮={best_epoch} 最优loss={best_so_far[-1]:.4f} 末段改善={improve*100:.1f}% → {verdict}")


if __name__ == "__main__":
    main()

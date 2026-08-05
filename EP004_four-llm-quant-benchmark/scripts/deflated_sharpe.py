#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EP004 · Deflated Sharpe Ratio（Bailey & López de Prado）
=======================================================
回答一个问题:**这个夏普,有多少是「试了 N 次挑出最好的那次」挑出来的运气?**

搜的轮数越多、各轮成绩越分散 → 光靠运气就能刷出的最高夏普(SR0)越高 →
你的实际夏普必须显著高过 SR0,DSR 才接近 1。DSR < 0.95 通常视为「不显著」。

输入(都是现成产物):
  --hyperopt  模型的 hyperopt_results.json   (取 N 与各轮 valid_sharpe 的方差)
  --trades    该模型的 verified 回测 zip/目录 (取所选策略的日收益:T、偏度、峰度)
  --wallet    初始资金(默认 10000)

用法(主机上跑):
  python deflated_sharpe.py \
    --hyperopt "<你的模型目录>/hyperopt_results.json" \
    --trades   "<你的模型目录>/backtest_results/valid.zip"
"""
import argparse
import glob
import json
import math
import os
import sys
import zipfile

import numpy as np
import pandas as pd


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p):
    # Acklam 近似的简化版：用二分求解 erf 反函数，精度足够
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _norm_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _find_trades(o):
    if isinstance(o, list):
        return o
    if isinstance(o, dict):
        if isinstance(o.get("trades"), list):
            return o["trades"]
        st = o.get("strategy")
        if isinstance(st, dict):
            for v in st.values():
                if isinstance(v, dict) and isinstance(v.get("trades"), list):
                    return v["trades"]
    return None


def load_daily_returns(path, wallet):
    """从 backtest zip / 目录 / trades json 还原日收益率序列(与 EP004ValidLoss 同口径)。"""
    if os.path.isdir(path):
        zs = sorted(glob.glob(os.path.join(path, "*.zip")), key=os.path.getmtime)
        if not zs:
            sys.exit(f"[dsr] 目录无 zip: {path}")
        path = zs[-1]
    if str(path).lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            data = None
            for n in z.namelist():
                if n.endswith(".json") and "_config" not in n:
                    o = json.loads(z.read(n))
                    if _find_trades(o):
                        data = o
                        break
            if data is None:
                sys.exit(f"[dsr] zip 内无 trades: {path}")
    else:
        data = json.load(open(path, encoding="utf-8"))

    tr = _find_trades(data)
    if not tr:
        sys.exit("[dsr] 没找到 trades")
    df = pd.DataFrame(tr)
    if "close_date" not in df or "profit_abs" not in df:
        sys.exit("[dsr] trades 缺 close_date / profit_abs")
    day = pd.to_datetime(df["close_date"], utc=True).dt.floor("D")
    daily = pd.to_numeric(df["profit_abs"], errors="coerce").fillna(0.0).groupby(day).sum() / wallet
    idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D", tz="UTC")
    return daily.reindex(idx, fill_value=0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hyperopt", required=True)
    ap.add_argument("--trades", required=True)
    ap.add_argument("--wallet", type=float, default=10000.0)
    a = ap.parse_args()

    hp = json.load(open(a.hyperopt, encoding="utf-8"))
    sr_trials = [t.get("valid_sharpe") for t in hp.get("trials", [])
                 if t.get("valid_sharpe") is not None]
    N = max(len(sr_trials), 1)
    if N < 2:
        sys.exit("[dsr] 有效 trial 太少,无法估计 SR 方差")
    sr_var = float(np.var(sr_trials, ddof=1))

    r = load_daily_returns(a.trades, a.wallet)
    T = len(r)
    if T < 30 or r.std() == 0:
        sys.exit(f"[dsr] 日收益样本太短或无波动 (T={T})")
    sr_hat = float(r.mean() / r.std() * math.sqrt(365))   # 年化,与目标函数同口径
    sr_daily = float(r.mean() / r.std())                   # 日频(公式里用这个)
    g3 = float(pd.Series(r).skew())
    g4 = float(pd.Series(r).kurt()) + 3.0                  # pandas 给的是超额峰度

    # 期望最大夏普(纯运气基线),Bailey & López de Prado
    e = math.e
    gamma = 0.5772156649
    sr0_daily = math.sqrt(sr_var / 365) * (
        (1 - gamma) * _norm_ppf(1 - 1.0 / N) + gamma * _norm_ppf(1 - 1.0 / (N * e))
    )

    denom = 1.0 - g3 * sr_daily + (g4 - 1.0) / 4.0 * sr_daily ** 2
    if denom <= 0:
        sys.exit("[dsr] 分母非正(收益分布极端),DSR 不可用")
    z = (sr_daily - sr0_daily) * math.sqrt(T - 1) / math.sqrt(denom)
    dsr = _norm_cdf(z)

    out = {
        "n_trials": N,
        "sr_trials_var": round(sr_var, 4),
        "observed_sharpe_annual": round(sr_hat, 3),
        "expected_max_sharpe_annual_by_luck": round(sr0_daily * math.sqrt(365), 3),
        "T_days": T, "skew": round(g3, 3), "kurtosis": round(g4, 3),
        "DSR": round(dsr, 4),
        "verdict": ("显著(DSR≥0.95)" if dsr >= 0.95 else
                    "偏弱(0.9≤DSR<0.95)" if dsr >= 0.90 else
                    "不显著 —— 大概率是搜出来的运气"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

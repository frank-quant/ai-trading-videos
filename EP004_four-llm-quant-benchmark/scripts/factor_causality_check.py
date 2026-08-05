# -*- coding: utf-8 -*-
"""
EP004 · 通用因果检查器（查策略有没有用未来数据）
=================================================
原理:对同一时点 t,分别用「全量数据」和「只到 t 的截断数据」算策略在 t 的决策,
     若结果不同 → 用了未来数据(look-ahead)。比 freqtrade lookahead-analysis 可靠,
     且对横截面不误报。

**两种策略都支持,自动识别**:
  - 用了脚手架(有 factor_score) → 直接测 factor_score
  - 自写策略(趋势/均值回归/任何家族) → 走完整 indicators→entry→exit,测最终信号

在 freqtrade docker 容器里跑(镜像自带 freqtrade + pandas),**必须 --entrypoint python**。
先把本文件复制进该环境的 user_data/,示例(<CLS> = 模型策略类名):
  export MSYS_NO_PATHCONV=1
  docker run --rm --entrypoint python \
    -v "<你的模型目录>:/freqtrade/user_data" \
    -v "<环境根目录>/data_shared:/freqtrade/user_data/data:ro" \
    freqtradeorg/freqtrade:stable \
    /freqtrade/user_data/factor_causality_check.py --strategy <CLS>
"""
import argparse
import glob
import sys

import numpy as np
import pandas as pd


def load_pair_df(datadir, pair, timeframe):
    fn = pair.replace("/", "_").replace(":", "_")   # BTC/USDT:USDT -> BTC_USDT_USDT
    files = glob.glob(f"{datadir}/binance/futures/{fn}-{timeframe}-futures.feather")
    if not files:
        return None
    return pd.read_feather(files[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True, help="模型策略类名(subclass of CrossSectionalBase)")
    ap.add_argument("--config", default="/freqtrade/user_data/config.json")
    ap.add_argument("--datadir", default="/freqtrade/user_data/data")
    ap.add_argument("--points", type=int, default=10, help="每个币抽查几个时点")
    ap.add_argument("--tol", type=float, default=1e-9)
    a = ap.parse_args()

    from freqtrade.configuration import Configuration
    from freqtrade.resolvers import StrategyResolver

    config = Configuration.from_files([a.config])
    config["strategy"] = a.strategy
    strat = StrategyResolver.load_strategy(config)
    tf = strat.timeframe

    use_factor = hasattr(strat, "factor_score")
    print(f"[mode] {'factor_score(脚手架策略)' if use_factor else 'entry/exit 信号(自写策略)'}")

    pairs = config.get("exchange", {}).get("pair_whitelist", [])
    max_diff = 0.0
    n_cmp = 0
    leaked = None   # (pair, t, reason)

    for p in pairs:
        if leaked:
            break
        d = load_pair_df(a.datadir, p, tf)
        if d is None or len(d) < 500:
            continue

        def signal_at(df_slice, pair):
            """返回该切片上每根 K 线的『决策向量』。
            - 脚手架策略:factor_score
            - 自写策略:走完整 indicators→entry→exit,把 4 个信号列拼成一个数
            """
            meta = {"pair": pair}
            if use_factor:
                return pd.Series(np.asarray(strat.factor_score(df_slice, pair), dtype="float64"))
            x = strat.populate_indicators(df_slice.copy(), meta)
            x = strat.populate_entry_trend(x, meta)
            x = strat.populate_exit_trend(x, meta)
            v = np.zeros(len(x), dtype="float64")
            for i, c in enumerate(["enter_long", "enter_short", "exit_long", "exit_short"]):
                if c in x.columns:
                    v += (2 ** i) * pd.to_numeric(x[c], errors="coerce").fillna(0).to_numpy()
            return pd.Series(v)

        try:
            full = signal_at(d.copy(), p)
        except Exception as e:
            sys.exit(f"[FAIL] {p} 上计算信号报错: {e}")
        L = len(d)
        idxs = np.linspace(int(L * 0.35), L - 2, a.points).astype(int)
        for t in idxs:
            vf = full.iloc[t]
            if not np.isfinite(vf):
                continue                       # 全量本身算不出(startup),跳过
            n_cmp += 1
            trunc = signal_at(d.iloc[: t + 1].copy(), p)
            vt = trunc.iloc[t]
            if not np.isfinite(vt):
                leaked = (p, int(t), "截断数据上算不出该点(全量能)→ 需要未来数据")
                break
            diff = abs(float(vf) - float(vt))
            max_diff = max(max_diff, diff)
            if diff > a.tol:
                leaked = (p, int(t), f"全量={vf:.4g} != 截断={vt:.4g}")
                break

    print(f"[{a.strategy}] 有效对比点={n_cmp}  max |full - truncated| = {max_diff:.3e}")
    if leaked:
        print(f"VERDICT: 信号用了未来数据(look-ahead)!{leaked[0]} @idx{leaked[1]}:{leaked[2]}  -> 判负")
    elif n_cmp < 10:
        print("[WARN] 有效对比点太少(因子 NaN 太多?),结论不可靠——手动复核")
    else:
        print("VERDICT: 信号因果,无未来函数  [PASS]")


if __name__ == "__main__":
    main()

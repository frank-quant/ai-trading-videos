# -*- coding: utf-8 -*-
"""
EP004 统一 hyperopt loss（四家照用,--hyperopt-loss EP004ValidLoss)
==================================================================
目标:在 train+valid 合并区间上跑 hyperopt,但**按验证集打分**并**惩罚训练/验证落差**:
    loss = -(valid_sharpe - PENALTY * max(0, train_sharpe - valid_sharpe))
（loss 越小越好。训练好但验证差 → 落差大 → 被罚。)

同时每轮把 train_sharpe / valid_sharpe 追加到 user_data/hyperopt_trials.jsonl,
供 export_hyperopt.py 拼成 hyperopt_results.json(按 loss 值匹配,**并行安全,可用 -j 20**)。

放置:本文件放各环境的 user_data/hyperopts/ 下。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from freqtrade.optimize.hyperopt_loss.hyperopt_loss_interface import IHyperOptLoss

TRAIN_START = pd.Timestamp("2021-01-01", tz="UTC")
VALID_START = pd.Timestamp("2024-07-01", tz="UTC")   # train < 此 <= valid
VALID_END = pd.Timestamp("2025-06-30", tz="UTC")
PENALTY = 0.5
MIN_TRADES = 30       # 全段最少交易
MIN_VALID_TRADES = 50  # 验证段最少交易 —— 防止用超低频把夏普刷成统计噪音


def _sharpe_daily(seg: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
                  capital: float) -> float:
    """按【日资金曲线】算年化夏普 —— 这是唯一合理的口径。

    为什么不用「每笔交易」的夏普:
      同时可持有多达 20 个仓位,交易严重重叠、并不独立。若按 mean/std × sqrt(笔数) 年化,
      并发越多虚高越厉害 —— 等于奖励「多开仓位」而不是奖励策略好,对只持 1~2 个仓位的
      设计不公平。改成把每日盈亏汇总成日收益率(以初始资金为基数)、按 sqrt(365) 年化后,
      不同并发数、不同 timeframe、不同区间长度都可以直接横向比较。
    """
    if seg is None or len(seg) == 0 or capital <= 0:
        return 0.0
    pnl = pd.to_numeric(seg["profit_abs"], errors="coerce").fillna(0.0)
    day = pd.to_datetime(seg["close_date"], utc=True).dt.floor("D")
    daily = pnl.groupby(day).sum() / capital           # 每日收益率
    # 补齐没有交易的日子(收益 0),否则会高估波动、低估天数
    idx = pd.date_range(start, end, freq="D", tz="UTC")
    daily = daily.reindex(idx, fill_value=0.0)
    sd = float(daily.std())
    if len(daily) < 30 or sd == 0:
        return 0.0
    return float(daily.mean() / sd * np.sqrt(365.0))


def _log(config, ts, vs, nt, nv, loss):
    try:
        ud = str(config.get("user_data_dir", "/freqtrade/user_data"))
        with open(Path(ud) / "hyperopt_trials.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"train_sharpe": None if np.isnan(ts) else round(ts, 4),
                                "valid_sharpe": None if np.isnan(vs) else round(vs, 4),
                                "n_train": int(nt), "n_valid": int(nv),
                                "loss": round(float(loss), 6)}) + "\n")
    except Exception:
        pass


class EP004ValidLoss(IHyperOptLoss):
    @staticmethod
    def hyperopt_loss_function(results, trade_count, min_date, max_date, config, **kwargs) -> float:
        ts = vs = float("nan")
        nt = nv = 0
        loss = 1000.0   # 默认(交易太少=差)
        if (results is not None and len(results) >= MIN_TRADES
                and "close_date" in results and "profit_abs" in results):
            cap = float(config.get("dry_run_wallet", 10000) or 10000)
            cd = pd.to_datetime(results["close_date"], utc=True)
            train = results.loc[cd < VALID_START]
            valid = results.loc[cd >= VALID_START]
            nt, nv = len(train), len(valid)
            if nv >= MIN_VALID_TRADES:        # 验证段交易够多 → 正常打分
                ts = _sharpe_daily(train, TRAIN_START, VALID_START, cap)
                vs = _sharpe_daily(valid, VALID_START, VALID_END, cap)
                gap = max(0.0, ts - vs)       # 两段同为「日频年化夏普」,落差才有意义
                loss = -(vs - PENALTY * gap)
            elif nt > 0:
                # 没撑到验证期(常见于爆仓/停止交易):重罚但保留梯度,
                # 否则整片搜索空间都是常数 1000,hyperopt 无从优化。
                ts = _sharpe_daily(train, TRAIN_START, VALID_START, cap)
                loss = 100.0 - ts
        _log(config, ts, vs, nt, nv, loss)     # 每轮记一行,导出时按 loss 值配对
        return loss

# -*- coding: utf-8 -*-
"""
engine/ch14.py —— rules.md 第 14 章必报评估指标：纯函数实现（只报告，不作门槛）

三组指标（对每个进入第 5 层的策略计算，写进台账；不参与任何筛选——
门槛仍然只有第 5 章那八层）：

  14.1 IC / ICIR 与 10 层分层（仅打分型）
       IC：每个调仓日，策略分数与「下一个调仓周期收益」的截面 Spearman 秩相关。
           报告 ic 均值 / ic 标准差 / ICIR = ic_mean ÷ ic_std × √年化期数 / ic>0 比例。
       分层：每调仓日按分数把股票池分 10 层（等分、层 1 = 分数最低），等权持有到
           下一次调仓。报告每层年化、多头(第 10 层)−空头(第 1 层)年化差、
           单调性 = 层序(1..10) 与层年化收益的 Spearman 秩相关。
       分层是不含交易成本的信号层画像（rules 14.1 未要求扣成本；扣成本口径的
       策略表现就是台账既有的 ann_excess / ir）。
  14.2 年化换手率与容量粗估（全部类型）
       换手率：逐年「买入金额(gross+fee) ÷ 当年平均持仓市值」，报告各年比值的均值。
       容量：对每笔买入，约束「单日买入 ≤ 该股当日成交额 1%」给出可放大的初始
           资金倍数 K = 1%×成交额 ÷ gross（回测以初始资金 1.0 计，线性放大）；
           日容量 = 当日全部买入的 min(K)。报告逐日容量的中位数与最差 5% 分位
           （单位：元）。**不含冲击成本模型，仅作参考**（rules 14.2 原文要求注明）。
       成交额单位：Tushare daily.amount 为**千元**，本模块一律换算成元
       （amount × 1000；已对全量数据核验 amount×1000 ≈ vol(手)×100×close，
       中位比值 1.0000）。
  14.3 信号衰减（全部类型）
       同一套信号，分别按持有 1/5/20/60 个交易日计算年化超额：单事件超额 =
       个股窗口收益 − 同窗口基准收益；年化 = (1 + 平均超额)^(250/h) − 1。
       窗口 = 信号日收盘 → 信号日后第 h 个交易日收盘（adj_nav 口径）。
       信号事件口径（由回测侧数据准备给定，backtest._ch14_compute）：打分型 =
       每个调仓日分数最高的 holdings 只（分数降序、并列按代码，与选股同序；
       不含行业分散约束——那是组合构建约束而非信号本身）；规则型 = 成交明细
       里每笔买入的 (code, signal_date)。

实现要求（rules 14.4 / 本步硬性要求）：
  * 本文件只放**纯函数**（numpy/pandas 数组运算，无 I/O、无全局状态、不 import
    任何 engine 模块）。回测管线（backtest.py 的数据准备 + 挂载）与审计探针
    （直接 import 本模块喂合成数据）调用同一实现。
  * 只在搜索期计算：区间闸门（start ≥ 20140101 且 end ≤ 20221231）在
    backtest.py 的挂载层执行；验证期/封存期回测这些列留空（验证期同名指标
    第 6 层跑完后补算，封存期开封后补算，rules 14.4）。
  * 全部正向收益窗口都以回测自身的交易日历为界（最后一个信号日 + h 超出
    回测末日的事件按 h 剔除），绝不读取回测 end 之后的数据。

台账新增列（backtest.LEDGER_COLS 尾部追加，列名单一事实来源）：
  ic_mean, ic_std, icir, ic_pos_ratio, decile_ls_ann, decile_monotonicity,
  turnover_ann, cap_median, cap_p5, decay_1d, decay_5d, decay_20d, decay_60d
（规则型前 6 列留空；规则型与打分型都出后 7 列。）

CLI 自测（假信号 / 固定种子随机分数，审计员可独立复验）：
  python engine/ch14.py selftest
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# rules.md 第 1 节搜索期（与 engine/funnel.py SEARCH_START/SEARCH_END 同值；
# ch14 不 import funnel，避免环形依赖，两处都以 rules.md 为准）
SEARCH_START, SEARCH_END = "20140101", "20221231"

N_LAYERS = 10                       # rules.md 14.1：分 10 层
DECAY_HORIZONS = (1, 5, 20, 60)     # rules.md 14.3：持有 1/5/20/60 个交易日
CAP_PARTICIPATION = 0.01            # rules.md 14.2：单日买入 ≤ 当日成交额 1%
TRADING_DAYS = 250                  # 与 backtest.information_ratio 同口径

# 台账新增列（engine/backtest.py LEDGER_COLS 引用；顺序即台账列序）
CH14_COLS = ["ic_mean", "ic_std", "icir", "ic_pos_ratio",
             "decile_ls_ann", "decile_monotonicity",
             "turnover_ann", "cap_median", "cap_p5",
             "decay_1d", "decay_5d", "decay_20d", "decay_60d"]


# ================================================================ 基础

def rankdata_avg(x) -> np.ndarray:
    """1..n 平均名次（并列取平均；pandas rank method='average'），NaN 保持 NaN。"""
    a = np.asarray(x, dtype="float64")
    out = np.full(len(a), np.nan)
    m = np.isfinite(a)
    if int(m.sum()) >= 1:
        out[m] = pd.Series(a[m]).rank(method="average").to_numpy()
    return out


def spearman_corr(x, y) -> float:
    """Spearman 秩相关（秩 = 平均名次）。只取双方均有限的配对；有效配对 < 2、
    或任一侧秩恒定（零方差）→ NaN（秩相关无定义）。"""
    a = np.asarray(x, dtype="float64")
    b = np.asarray(y, dtype="float64")
    if len(a) != len(b):
        raise ValueError(f"spearman_corr 长度不一致: {len(a)} vs {len(b)}")
    m = np.isfinite(a) & np.isfinite(b)
    if int(m.sum()) < 2:
        return float("nan")
    rx = rankdata_avg(a[m])
    ry = rankdata_avg(b[m])
    sx = float(rx.std(ddof=1))
    sy = float(ry.std(ddof=1))
    if sx == 0.0 or sy == 0.0:
        return float("nan")
    # np.corrcoef：分子分母同自由度，Pearson(x,y) 在 x,y 已是秩时即 Spearman，
    # 且严格落在 [−1,1]（自写 mean/(std·std) 混用总体/样本自由度会差 (n−1)/n）
    return float(np.corrcoef(rx, ry)[0, 1])


def periods_per_year(n_periods: int, total_days: float) -> float:
    """年化期数 = 期数 × 250 ÷ 覆盖交易日数（ICIR 的 √年化期数 用它的平方根）。"""
    if n_periods <= 0 or total_days <= 0:
        return float("nan")
    return float(n_periods) * TRADING_DAYS / float(total_days)


def annualized_from_periods(period_rets, period_days) -> float:
    """逐期收益 → 年化：∏(1+r)^(250/Σ期交易日数) − 1（NaN 期剔除）。"""
    r = np.asarray(period_rets, dtype="float64")
    d = np.asarray(period_days, dtype="float64")
    m = np.isfinite(r)
    if not m.any() or len(d) != len(r):
        return float("nan")
    nav = float(np.prod(1.0 + r[m]))
    total = float(d[m].sum())
    if total <= 0 or nav <= 0:
        return float("nan")
    return nav ** (TRADING_DAYS / total) - 1.0


# ================================================================ 14.1 IC / 分层

def ic_series(score_panel: pd.DataFrame, fwd_ret_panel: pd.DataFrame) -> pd.Series:
    """逐调仓日 IC：分数与下一调仓周期收益的截面 Spearman 秩相关。

    score_panel / fwd_ret_panel：行 = 调仓日、列 = code 的宽表；分数面板取
    打分截面全体（不限持仓）；下一期收益面板按同一 (行,列) 对齐（调用方
    保证，错位直接 KeyError——宁可大声失败）。返回按调仓日索引的 IC 序列。
    """
    sp = score_panel.loc[fwd_ret_panel.index, fwd_ret_panel.columns].to_numpy(dtype="float64")
    fp = fwd_ret_panel.to_numpy(dtype="float64")
    ics = [spearman_corr(sp[i], fp[i]) for i in range(len(fp))]
    return pd.Series(ics, index=fwd_ret_panel.index, name="ic")


def ic_report(ics, ppy: float) -> dict:
    """IC 汇总：均值 / 标准差(ddof=1) / ICIR / ic>0 比例。

    ICIR = ic_mean ÷ ic_std × √年化期数（rules 14.1）；ic_std = 0（IC 恒定，
    如假信号自测）时 ICIR 无定义 → NaN。有效 IC 期数 < 2 → 全 NaN。
    """
    a = np.asarray([x for x in ics if np.isfinite(x)], dtype="float64")
    if len(a) < 2:
        return {"ic_mean": float("nan"), "ic_std": float("nan"),
                "icir": float("nan"), "ic_pos_ratio": float("nan"),
                "n_ic_periods": int(len(a))}
    mean = float(a.mean())
    std = float(a.std(ddof=1))
    icir = float("nan") if (std == 0.0 or not np.isfinite(ppy)) \
        else float(mean / std * np.sqrt(ppy))
    return {"ic_mean": mean, "ic_std": std, "icir": icir,
            "ic_pos_ratio": float((a > 0).mean()), "n_ic_periods": int(len(a))}


def decile_layer_returns(score_panel: pd.DataFrame, fwd_ret_panel: pd.DataFrame,
                         n_layers: int = N_LAYERS) -> pd.DataFrame:
    """每个调仓日按分数等分 n_layers 层（层 1 = 分数最低），等权层收益。

    分层口径：先剔掉分数或下一期收益非有限的成员（无法参与），再按分数的
    平均名次切桶：layer = floor((rank−1)/n × n_layers)（并列平均名次，确定性；
    无并列时每层恰 n/n_layers 只）。层收益 = 成员下一期收益的等权均值。
    有效成员 < n_layers 的调仓日 → 该行全 NaN（由 layer_report 的年化剔除）。
    """
    sp = score_panel.loc[fwd_ret_panel.index, fwd_ret_panel.columns].to_numpy(dtype="float64")
    fp = fwd_ret_panel.to_numpy(dtype="float64")
    out = np.full((len(fp), n_layers), np.nan)
    for i in range(len(fp)):
        m = np.isfinite(sp[i]) & np.isfinite(fp[i])
        n = int(m.sum())
        if n < n_layers:
            continue
        s = sp[i][m]
        r = fp[i][m]
        rank = pd.Series(s).rank(method="average").to_numpy()
        layer = np.clip(np.floor((rank - 1.0) / n * n_layers),
                        0, n_layers - 1).astype(int)
        for k in range(n_layers):
            sel = layer == k
            if sel.any():
                out[i, k] = float(r[sel].mean())
    return pd.DataFrame(out, index=fwd_ret_panel.index,
                        columns=range(1, n_layers + 1))


def layer_report(layer_rets: pd.DataFrame, period_days) -> dict:
    """分层汇总：每层年化、多头(第 n 层)−空头(第 1 层)年化差、单调性。

    period_days 与 layer_rets 行对齐 = 每期的交易日数；年化见
    annualized_from_periods。单调性 = 层序 1..n 与层年化收益的 Spearman
    秩相关（rules 14.1：单调性差但 IR 高 = 收益来自少数极端个股，须单独标注）。
    """
    d = np.asarray(period_days, dtype="float64")
    ann = np.array([annualized_from_periods(layer_rets[c].to_numpy(dtype="float64"), d)
                    for c in layer_rets.columns], dtype="float64")
    n = len(ann)
    mono = spearman_corr(np.arange(1, n + 1, dtype="float64"), ann) if n >= 2 \
        else float("nan")
    return {"layer_ann": [float(x) for x in ann],
            "decile_ls_ann": float(ann[-1] - ann[0]) if n else float("nan"),
            "decile_monotonicity": float(mono),
            "n_layers": int(n)}


# ================================================================ 14.2 换手 / 容量

def position_intervals(trades: pd.DataFrame, dates) -> pd.DataFrame:
    """从成交明细重建持仓区间（纯函数，换手率分母的输入之一）。

    trades 需含 code/side/exec_date/shares；dates = 回测交易日历（升序）。
    区间 = [买入执行日, 卖出执行日)（按 dates 下标，双闭开区间：卖出当日开盘
    离场、当日收盘不再计市值；期末仍持仓 → 到最后一天）。同日先卖后买
    （回测撮合顺序；"sell" 字典序后于 "buy"，side 降序稳定排序即得）。
    引擎的全部卖出都是整仓卖出、持仓期内不加仓；防御分支：卖出时无持仓 →
    忽略，同码二次买入 → 份额累加。返回列：code, shares, i0(含), i1(不含)。
    """
    idx = {str(d): i for i, d in enumerate(dates)}
    tr = pd.DataFrame({"code": trades["code"].astype(str),
                       "side": trades["side"].astype(str),
                       "shares": trades["shares"].astype("float64"),
                       "exec_date": trades["exec_date"].astype(str)})
    tr["day_i"] = tr["exec_date"].map(idx)
    tr = tr[tr["day_i"].notna()]        # 回测日历外的成交不存在；防御剔除
    tr = tr.sort_values(["day_i", "side"], ascending=[True, False], kind="stable")
    rows: list[dict] = []
    open_pos: dict[str, dict] = {}
    for t in tr.itertuples(index=False):
        c = str(t.code)
        if t.side == "sell":
            p = open_pos.pop(c, None)
            if p is not None:
                rows.append({"code": c, "shares": p["shares"],
                             "i0": p["i0"], "i1": int(t.day_i)})
        else:
            if c in open_pos:           # 防御：引擎不产生加仓
                open_pos[c]["shares"] += float(t.shares)
            else:
                open_pos[c] = {"shares": float(t.shares), "i0": int(t.day_i)}
    n = len(dates)
    for c, p in open_pos.items():
        rows.append({"code": c, "shares": p["shares"], "i0": p["i0"], "i1": n})
    return pd.DataFrame(rows, columns=["code", "shares", "i0", "i1"])


def hold_value_from_intervals(intervals: pd.DataFrame, nav_at, n_days: int) -> np.ndarray:
    """逐日收盘持仓市值 = Σ 持仓份额 × nav_at(code, 当日)（当日无行情沿用最后
    已知净值，与回测 _mark_nav 同语义；nav_at(code, date)→float|NaN 由调用方
    提供——纯函数只依赖传入函数的返回值，同一输入同一输出）。"""
    hv = np.zeros(int(n_days), dtype="float64")
    for t in intervals.itertuples(index=False):
        i0, i1 = max(0, int(t.i0)), min(int(t.i1), int(n_days))
        for i in range(i0, i1):
            v = nav_at(str(t.code), i)
            if np.isfinite(v):
                hv[i] += float(t.shares) * v
    return hv


def turnover_report(trades: pd.DataFrame, dates, hold_value) -> dict:
    """年化换手率（rules 14.2）：逐年 买入金额 ÷ 平均持仓市值，报告各年比值均值。

    买入金额 = gross + fee（现金流出，单位 = 初始资金）；平均持仓市值 = 当年
    逐日收盘持仓市值均值（dates 与 hold_value 对齐）。均值 ≤ 0 的年份跳过
    （无持仓年份无换手可言）。"""
    years = np.array([str(d)[:4] for d in dates], dtype=object)
    hv = np.asarray(hold_value, dtype="float64")
    if len(hv) != len(years):
        raise ValueError(f"hold_value({len(hv)}) 与 dates({len(years)}) 不对齐")
    buy = trades[trades["side"].astype(str) == "buy"]
    amt = (buy["gross"].astype("float64") + buy["fee"].astype("float64"))
    byear = buy["exec_date"].astype(str).str[:4]
    yearly: dict[str, float] = {}
    for y in sorted(set(years.tolist())):
        sel = years == y
        avg = float(hv[sel].mean()) if sel.any() else 0.0
        if avg <= 0:
            continue
        a = float(amt[byear == y].sum())
        yearly[y] = a / avg
    ann = float(np.mean(list(yearly.values()))) if yearly else float("nan")
    return {"turnover_ann": ann, "yearly": yearly}


def capacity_report(buy_exec_dates, buy_gross, buy_amount_yuan) -> dict:
    """容量粗估（rules 14.2，**不含冲击成本，仅作参考**）。

    三个等长数组（每笔买入一笔）：执行日、买入金额 gross（初始资金单位）、
    该股当日成交额（元，Tushare amount 千元 × 1000）。单笔可放大倍数
    K_i = 1% × 成交额 ÷ gross（策略初始资金线性放大 K 倍后该笔买入恰触 1%
    参与率）；日容量 = 当日全部买入的 min(K)。返回逐日容量的中位数与
    最差 5% 分位（numpy percentile 线性插值），单位：元初始资金。"""
    day = np.asarray([str(x) for x in buy_exec_dates], dtype=object)
    g = np.asarray(buy_gross, dtype="float64")
    a = np.asarray(buy_amount_yuan, dtype="float64")
    if not (len(day) == len(g) == len(a)):
        raise ValueError("capacity_report 三个输入数组长度不一致")
    ok = (g > 0) & np.isfinite(g) & np.isfinite(a)
    if not ok.any():
        return {"cap_median": float("nan"), "cap_p5": float("nan"),
                "n_cap_days": 0}
    k = CAP_PARTICIPATION * a[ok] / g[ok]
    caps = pd.Series(k).groupby(day[ok]).min().to_numpy(dtype="float64")
    return {"cap_median": float(np.median(caps)),
            "cap_p5": float(np.percentile(caps, 5)),
            "n_cap_days": int(len(caps))}


# ================================================================ 14.3 信号衰减

def decay_horizon(event_stock_rets, event_bench_rets, h: int) -> float:
    """持有 h 个交易日的年化超额（rules 14.3）。

    单事件超额 = 个股窗口收益 − 同窗口基准收益（两个等长数组，一一对应）；
    年化 = (1 + 平均超额)^(250/h) − 1。任一侧非有限的事件剔除；
    有效事件数为 0 → NaN。"""
    s = np.asarray(event_stock_rets, dtype="float64")
    b = np.asarray(event_bench_rets, dtype="float64")
    if len(s) != len(b):
        raise ValueError(f"decay_horizon 长度不一致: {len(s)} vs {len(b)}")
    m = np.isfinite(s) & np.isfinite(b)
    if not m.any() or h <= 0:
        return float("nan")
    e = float(np.mean(s[m] - b[m]))
    return (1.0 + e) ** (TRADING_DAYS / float(h)) - 1.0


def decay_report(rets_by_h: dict[int, tuple]) -> dict:
    """衰减曲线：{h: (个股窗口收益数组, 基准窗口收益数组)} →
    {decay_1d:…, decay_5d:…, decay_20d:…, decay_60d:…}（年化超额）。"""
    out: dict[str, float] = {}
    for h in DECAY_HORIZONS:
        s, b = rets_by_h[h]
        out[f"decay_{h}d"] = decay_horizon(s, b, h)
    return out


# ================================================================ 自测（CLI）

def _selftest() -> int:
    """已知答案自测：假信号（分数=下一期收益）IC≈1、分层严格单调；
    固定种子随机分数 IC≈0、无单调性；换手/容量/衰减/持仓区间用小算例核对。
    全部确定性（固定种子），审计员可独立复验。退出码 0 = 全过。"""
    ok = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
        ok = ok and bool(cond)

    rng = np.random.default_rng(42)
    n_dates, n_codes = 120, 300
    dates_idx = [f"D{i:04d}" for i in range(n_dates)]
    codes = [f"C{j:04d}" for j in range(n_codes)]

    fwd = pd.DataFrame(rng.normal(0.0, 0.05, (n_dates, n_codes)),
                       index=dates_idx, columns=codes)

    # ---- 1) 假信号：分数 = 下一期收益 → IC≈1、分层严格单调、单调性=1 ----
    ics = ic_series(fwd, fwd)
    rep = ic_report(ics.to_numpy(), ppy=periods_per_year(n_dates, n_dates * 5.0))
    check("假信号 IC≈1（逐日 |IC−1|<1e-12）",
          bool(np.allclose(ics.to_numpy(), 1.0, atol=1e-12)),
          f"ic_mean={rep['ic_mean']:.6f}")
    check("假信号 ic>0 比例 = 1", rep["ic_pos_ratio"] == 1.0)
    check("假信号 ICIR 无定义（IC 恒定 std=0 → NaN）", not np.isfinite(rep["icir"]))
    layers = decile_layer_returns(fwd, fwd)
    lrep = layer_report(layers, np.full(n_dates, 5.0))
    la = np.array(lrep["layer_ann"])
    check("假信号分层严格单调（每层年化逐层递增）",
          bool(np.all(np.diff(la) > 0)),
          f"层1={la[0]:.4f} … 层10={la[-1]:.4f}")
    check("假信号单调性 = 1", abs(lrep["decile_monotonicity"] - 1.0) < 1e-12)
    check("假信号多头−空头年化差 > 0", lrep["decile_ls_ann"] > 0)

    # ---- 2) 固定种子随机分数：IC≈0、无单调性 ----
    rnd = pd.DataFrame(rng.normal(0.0, 1.0, (n_dates, n_codes)),
                       index=dates_idx, columns=codes)
    ics2 = ic_series(rnd, fwd)
    rep2 = ic_report(ics2.to_numpy(), ppy=periods_per_year(n_dates, n_dates * 5.0))
    check("随机分数 IC≈0（|ic_mean|<0.05）", abs(rep2["ic_mean"]) < 0.05,
          f"ic_mean={rep2['ic_mean']:.4f}")
    check("随机分数 ic>0 比例接近 0.5（0.35~0.65）",
          0.35 <= rep2["ic_pos_ratio"] <= 0.65, f"{rep2['ic_pos_ratio']:.3f}")
    lrep2 = layer_report(decile_layer_returns(rnd, fwd), np.full(n_dates, 5.0))
    check("随机分数无单调性（|单调性|<0.5）",
          abs(lrep2["decile_monotonicity"]) < 0.5,
          f"mono={lrep2['decile_monotonicity']:.4f}")

    # ---- 3) spearman 基础性质：自身相关=1、逆序=−1、常数列=NaN ----
    x = np.arange(1.0, 11.0)
    check("spearman(x,x)=1", abs(spearman_corr(x, x) - 1.0) < 1e-12)
    check("spearman(x,−x)=−1", abs(spearman_corr(x, -x) + 1.0) < 1e-12)
    check("spearman 常数列 → NaN", not np.isfinite(spearman_corr(np.ones(5), x[:5])))
    check("spearman NaN 配对剔除（混入 NaN 不改相关）",
          abs(spearman_corr(np.r_[x, np.nan], np.r_[x * 2, np.nan]) - 1.0) < 1e-12)

    # ---- 4) 持仓区间重建 ----
    tr = pd.DataFrame([
        {"code": "A", "side": "buy", "exec_date": "20200102", "shares": 10.0, "gross": 1.0, "fee": 0.0},
        {"code": "B", "side": "buy", "exec_date": "20200106", "shares": 5.0, "gross": 1.0, "fee": 0.0},
        {"code": "A", "side": "sell", "exec_date": "20200109", "shares": 10.0, "gross": 1.0, "fee": 0.0},
        {"code": "C", "side": "buy", "exec_date": "20200109", "shares": 2.0, "gross": 1.0, "fee": 0.0},
    ])
    dts = ["20200102", "20200103", "20200106", "20200107", "20200109", "20200110"]
    iv = position_intervals(tr, dts)
    got = {(r.code, r.shares, r.i0, r.i1) for r in iv.itertuples(index=False)}
    check("持仓区间：A=[0,4) 卖出日不计、B/C 持有到末日",
          got == {("A", 10.0, 0, 4), ("B", 5.0, 2, 6), ("C", 2.0, 4, 6)}, f"{sorted(got)}")

    # ---- 5) 换手率小算例 ----
    dts2 = [f"2020{i:04d}" for i in range(1, 6)] + [f"2021{i:04d}" for i in range(1, 6)]
    tr2 = pd.DataFrame([
        {"code": "A", "side": "buy", "exec_date": "20200001", "shares": 1.0, "gross": 0.4, "fee": 0.0001},
        {"code": "A", "side": "buy", "exec_date": "20210001", "shares": 1.0, "gross": 1.0, "fee": 0.0},
        {"code": "A", "side": "sell", "exec_date": "20210004", "shares": 1.0, "gross": 1.0, "fee": 0.0},
    ])
    hv2 = np.r_[np.full(5, 0.4), np.full(5, 0.5)]
    trep = turnover_report(tr2, dts2, hv2)
    exp2020 = 0.4001 / 0.4
    check("换手率：逐年比值与均值（2020=1.00025, 2021=2.0）",
          np.isclose(trep["yearly"].get("2020"), exp2020)
          and np.isclose(trep["yearly"].get("2021"), 2.0)
          and np.isclose(trep["turnover_ann"], (exp2020 + 2.0) / 2.0),
          f"{trep}")
    hv3 = np.r_[np.full(5, 0.4), np.zeros(5)]     # 2021 无持仓 → 跳过
    trep3 = turnover_report(tr2, dts2, hv3)
    check("换手率：零持仓年份跳过", set(trep3["yearly"]) == {"2020"})

    # ---- 6) 容量小算例 ----
    cap = capacity_report(["20200102", "20200102", "20200106"],
                          [0.01, 0.02, 0.05],
                          [1.0e6, 2.0e6, 1.0e6])
    # 日1: min(1%×1e6/0.01, 1%×2e6/0.02)=min(1e6,1e6)=1e6; 日2: 1%×1e6/0.05=2e5
    check("容量：日容量=当日 min、中位数与 5% 分位",
          np.isclose(cap["cap_median"], 6.0e5)
          and np.isclose(cap["cap_p5"], 2.4e5) and cap["n_cap_days"] == 2,
          f"{cap}")

    # ---- 7) 衰减小算例 ----
    d1 = decay_horizon([0.1, -0.1], [0.0, 0.0], h=5)
    check("衰减：零超额 → 年化 0", np.isclose(d1, 0.0))
    d2 = decay_horizon([0.1, -0.1], [0.02, 0.02], h=5)
    exp = (1.0 - 0.02) ** 50.0 - 1.0
    check("衰减：平均超额 −2% → (0.98)^50−1", np.isclose(d2, exp),
          f"{d2:.6f}")
    dr = decay_report({h: (np.array([0.01, 0.02]), np.array([0.0, 0.0]))
                       for h in DECAY_HORIZONS})
    check("衰减：四条曲线键齐全",
          set(dr) == {"decay_1d", "decay_5d", "decay_20d", "decay_60d"}
          and dr["decay_1d"] > dr["decay_5d"] > dr["decay_20d"] > dr["decay_60d"],
          f"{ {k: round(v, 4) for k, v in dr.items()} }")

    # ---- 8) 年化与期数 ----
    check("periods_per_year：周度 120 期×5 日 → 50",
          np.isclose(periods_per_year(120, 600.0), 50.0))
    check("annualized_from_periods：每期 1%、50 期×5 日 → 11.05",
          np.isclose(annualized_from_periods(np.full(50, 0.01), np.full(50, 5.0)),
                     1.01 ** 50 - 1))

    print(f"[ch14-selftest] {'全部通过' if ok else '存在失败项'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["selftest"]:
        return _selftest()
    print(__doc__)
    print("用法：python engine/ch14.py selftest   # 纯函数已知答案自测")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

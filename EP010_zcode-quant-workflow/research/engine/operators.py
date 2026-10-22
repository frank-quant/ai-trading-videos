# -*- coding: utf-8 -*-
"""
engine/operators.py —— 策略零件库

每个零件是纯函数：输入历史切片面板（长表，列同 DataStore.panel，按 code,date
升序），输出**同形状** DataFrame（同一 index、唯一列 "value"），只回看、绝不
引用未来数据。「T 日的值」= 输出的第 T 行。

输入约定（Tushare 版，列同 DataStore.panel）：
    date, code, open, high, low, close, pre_close, pct_chg, vol, amount,
    af（复权因子）, adj_nav（= close × af，跨日收益唯一口径）,
    turnover_rate, pe_ttm, pb, ps_ttm, total_mv, circ_mv,
    up_limit, down_limit, is_st, l1_code, l1_name,
    fin_end_date, roe, or_yoy, netprofit_yoy,
    fc_ann_date, fc_type, fc_type_code, fc_chg_mid, fc_days,
    ex_ann_date, ex_yoy, ex_days, n_listed,
    tl_on_list（龙虎榜当日上榜 0/1，≤T 对齐）, tl_inst_netbuy_pct（最近一次上榜
    机构净买入占比 %，≤T 对齐）, margin_rzye（融资余额 元，<T 对齐）,
    hk_ratio（北向持股占流通股本 %，<T 对齐）
  panel 通常来自 DataStore 面板（或其 date <= T 切片，保证 <= T）。

窗口 N 只能取 3/5/10/20/60/120/250（rules.md 第 7 节档位），非法 N 抛 ValueError。

嵌套 spec（rules.md 7.5「通用：任意零件的时序分位 / 截面分位」）：
    spec := {op: 名, n?: 窗口, of?: spec}
    ts_pct {of, n}   基零件值的过去 n 根K线时序分位（含当日；窗口内出现 NaN → NaN）
    xsec_pct {of}    当日截面分位（面板内全部同行日期股票）
    ind_rank {of}    当日同申万一级行业内分位（无行业 → NaN）
    解析统一走 eval_spec(panel, spec)。

OPERATORS 注册表：名字 -> 函数，供测试枚举与策略配置解析。新零件经
engine/register_operator.py 通过撕报纸测试后持久化进 engine/operator_registry.json，
import 时自动并入 OPERATORS / OPERATOR_META（见文件末尾注册表一节）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402,F401  （供价格口径复用常量；不读数据；
              #  必须先于 numpy/pandas——guard 钉死 BLAS 线程环境变量）

import numpy as np
import pandas as pd

ALLOWED_WINDOWS = (3, 5, 10, 20, 60, 120, 250)   # rules.md 第 7 节：窗口长度档位


def _check_window(n: int) -> int:
    n = int(n)
    if n not in ALLOWED_WINDOWS:
        raise ValueError(
            f"窗口长度 {n} 不在 rules.md 第 7 节档位 {list(ALLOWED_WINDOWS)} 中"
        )
    return n


def _out(panel: pd.DataFrame, values, name: str) -> pd.DataFrame:
    """组装成同形状输出（同 index、单列 value）。Series 直接按 index 对齐。"""
    if isinstance(values, pd.Series):
        return pd.DataFrame({"value": values.astype("float64")}, index=panel.index)
    v = np.asarray(values, dtype="float64")
    if len(v) != len(panel):
        raise ValueError(f"零件 {name} 输出长度 {len(v)} != 面板长度 {len(panel)}")
    return pd.DataFrame({"value": v}, index=panel.index)


def _grouped(panel: pd.DataFrame):
    """groupby transform 包装：返回的 Series 与 panel.index 对齐（transform 保证）。"""
    return panel.groupby("code", sort=False)


# ---- numpy 滑动窗口聚合（确定性）----
# pandas 的 rolling 用在线算法（滑入滑出更新累积量），结果**依赖序列起点**：
# 同一窗口在「全量序列」与「切片序列」上的值有 ULP 级差异，经截面排名可放大到
# 1e-4 量级（实测）。numpy 的 sliding_window_view + 聚合只看窗口内的值，
# 与序列起点无关（实测 bitwise 一致）。所有 rolling 聚合因此改用本组函数。

def _sw_apply(arr: np.ndarray, n: int, fn) -> np.ndarray:
    """按行序对连续 n 行的窗口应用 fn（fn 接收 (k, n) 数组返回 (k,) 数组）。

    输出与输入等长：前 n-1 行为 NaN。仅适用于「连续行」语义的算子
    （调用方保证按 code 分组后行内日期连续）。arr 必须是单一分组的值。
    """
    arr = np.asarray(arr, dtype="float64")
    k = len(arr)
    out = np.full(k, np.nan, dtype="float64")
    if k >= n:
        w = np.lib.stride_tricks.sliding_window_view(arr, n)
        out[n - 1:] = fn(w)
    return out


def _sw_mean(arr, n):
    return _sw_apply(arr, n, lambda w: w.mean(axis=1))


def _sw_std(arr, n):
    def f(w):
        # 常量窗口（含全 0）显式置 0：滑动 std 对全等窗口给精确 0，
        # 这里用 max==min 判定后再算，避免任何子正常残差
        mx = w.max(axis=1)
        mn = w.min(axis=1)
        sd = w.std(axis=1, ddof=1)
        return np.where(mx == mn, 0.0, sd)
    return _sw_apply(arr, n, f)


def _sw_max(arr, n):
    return _sw_apply(arr, n, lambda w: w.max(axis=1))


def _sw_min(arr, n):
    return _sw_apply(arr, n, lambda w: w.min(axis=1))


def _by_code(panel: pd.DataFrame, col, fn) -> np.ndarray:
    """对列按 code 分组（保持行序）应用组内确定性函数，返回与面板等长的数组。

    分组用 pandas groupby（sort=False，保持面板 (code,date) 排序），
    每组的值数组交给 fn（如 _sw_mean(x, n)）。
    """
    codes = panel["code"].to_numpy()
    vals = panel[col].to_numpy(dtype="float64") if isinstance(col, str) else np.asarray(col, dtype="float64")
    out = np.full(len(panel), np.nan, dtype="float64")
    # 分组边界（面板按 code 排序，连续块）
    idx = np.flatnonzero(np.r_[True, codes[1:] != codes[:-1]])
    bounds = np.r_[idx, len(codes)]
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a:
            out[a:b] = fn(vals[a:b])
    return out


# ================================================================ 零件实现

def ret_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """N 日涨跌幅（%）：复权净值口径 adj_nav[T]/adj_nav[T-n] - 1。

    停牌日 pctChg=0、净值走平，因此停牌夹在中间时该值语义为「含停牌的区间收益」。
    """
    n = _check_window(n)
    nav = panel["adj_nav"]
    prev = _grouped(panel)["adj_nav"].shift(n)
    return _out(panel, (nav / prev - 1.0) * 100.0, f"ret_{n}")


def ma_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """N 日均线（复权净值口径）：adj_nav 的 N 日滚动均值。

    用 numpy 滑动窗口（_sw_mean）：与 pandas rolling 数学等价，但结果
    不依赖序列起点（pandas 在线算法有 ULP 级起点依赖，见 _sw_apply 注释）。
    """
    n = _check_window(n)
    m = _by_code(panel, "adj_nav", lambda x: _sw_mean(x, n))
    return _out(panel, m, f"ma_{n}")


def close_over_ma_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """收盘 / N 日均线（复权净值口径，无量纲倍数）。"""
    n = _check_window(n)
    ma = ma_n(panel, n)["value"]
    return _out(panel, panel["adj_nav"] / ma, f"close_over_ma_{n}")


def dist_high_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """收盘距 N 日最高的幅度（%，≤0）：复权口径。

    N 日最高 = max(前 N-1 根 K 线的复权最高价, 当日复权最高价)，
    其中复权最高价 = 不复权 high × 当日因子（跨日可加比的唯一正确口径）。
    """
    n = _check_window(n)
    hq = (panel["high"] * panel["af"]).to_numpy(dtype="float64")
    # 前 N-1 根的窗口最大值（右对齐到 T-1，即 shift 后 rolling）
    prev_max = _by_code(panel, hq,
                        lambda x: _shift1(_sw_max(x, n - 1)))
    cur = hq
    hh = np.fmax(prev_max, cur)          # NaN 传播：前段不足 N-1 根 → NaN
    with np.errstate(divide="ignore", invalid="ignore"):
        res = (panel["adj_nav"].to_numpy() / hh - 1.0) * 100.0
    return _out(panel, res, f"dist_high_{n}")


def dist_low_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """收盘距 N 日最低的幅度（%，≥0）。口径同 dist_high_n。"""
    n = _check_window(n)
    lq = (panel["low"] * panel["af"]).to_numpy(dtype="float64")
    prev_min = _by_code(panel, lq,
                        lambda x: _shift1(_sw_min(x, n - 1)))
    ll = np.fmin(prev_min, lq)
    with np.errstate(divide="ignore", invalid="ignore"):
        res = (panel["adj_nav"].to_numpy() / ll - 1.0) * 100.0
    return _out(panel, res, f"dist_low_{n}")


def _shift1(arr: np.ndarray) -> np.ndarray:
    """右移一位（首位置 NaN）。"""
    out = np.full(len(arr), np.nan, dtype="float64")
    if len(arr) > 1:
        out[1:] = arr[:-1]
    return out


def close_pos_range(panel: pd.DataFrame) -> pd.DataFrame:
    """收盘在当日振幅中的位置（0~1，不复权口径）：

    (close - low) / (high - low)；high==low（一字板/停牌）时若 close>=preclose
    记 1.0（涨停一字），否则 0.0；数据缺失记 NaN。
    """
    hi, lo, cl = panel["high"], panel["low"], panel["close"]
    rng = hi - lo
    pos = (cl - lo) / rng
    flat = (rng.abs() < 1e-12) | rng.isna()
    if flat.any():
        pos = pos.mask(flat & (cl >= panel["pre_close"]), 1.0)
        pos = pos.mask(flat & (cl < panel["pre_close"]), 0.0)
    return _out(panel, pos, "close_pos_range")


def vol_ratio_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """量比 = 当日成交量 / 前 N 日均量（不含当日；停牌日量为 0 → 结果为 0）。"""
    n = _check_window(n)
    # 前 N 日（不含当日）均量：窗口最大值右对齐到 T-1
    prev_mean = _by_code(panel, "vol",
                         lambda x: _shift1(_sw_mean(x, n)))
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = panel["vol"].to_numpy() / prev_mean
    # 前N日全停牌（量0）时均值=0 → 0/0=NaN，按 0 处理（当日无有效量参照）
    ratio = np.where(np.isfinite(ratio), ratio, np.nan)
    return _out(panel, ratio, f"vol_ratio_{n}")


def turn(panel: pd.DataFrame) -> pd.DataFrame:
    """当日换手率（%，baostock turn 字段原值）。"""
    return _out(panel, panel["turnover_rate"], "turn")


def turn_ma_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """N 日平均换手率（%）。numpy 滑动窗口口径（确定性，见 _sw_apply 注释）。"""
    n = _check_window(n)
    m = _by_code(panel, "turnover_rate", lambda x: _sw_mean(x, n))
    return _out(panel, m, f"turn_ma_{n}")


def vol_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """N 日收益波动率（%）：pct_chg 口径的样本标准差（ddof=1）。

    数值确定性：numpy 滑动窗口只看窗口内的值，与序列起点无关；
    常量窗口（典型：长停牌股 pct_chg 全 0）显式置精确 0.0（数学恒等：
    常量窗口的样本 std 为 0；pandas 滑动算法在该场景给 ~1e-7 起点依赖残差）。
    """
    n = _check_window(n)
    v = _by_code(panel, "pct_chg", lambda x: _sw_std(x, n))
    return _out(panel, v, f"vol_{n}")


def atr_close_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """N 日 ATR / 当日收盘（%，无量纲基准的日内波动幅度）。

    TR_t = max(high-low, |high - preclose|, |low - preclose|)，全部不复权口径
    （TR 的三个输入都是**当日**或**前收盘**的价格，与跨日复权无关——
    preclose 已是交易所按除权除息调整过的基准价，口径自洽）。
    """
    n = _check_window(n)
    hi = panel["high"].to_numpy(dtype="float64")
    lo = panel["low"].to_numpy(dtype="float64")
    pc = panel["pre_close"].to_numpy(dtype="float64")
    tr = np.nanmax(np.stack([hi - lo, np.abs(hi - pc), np.abs(lo - pc)]), axis=0)
    atr = _by_code(panel, tr, lambda x: _sw_mean(x, n))
    with np.errstate(divide="ignore", invalid="ignore"):
        res = atr / panel["close"].to_numpy() * 100.0
    return _out(panel, res, f"atr_close_{n}")


def streak_up(panel: pd.DataFrame) -> pd.DataFrame:
    """连续上涨天数：当日 pctChg>0 计 1，连续累积；下跌或平盘清零。"""
    return _streak(panel, panel["pct_chg"] > 0)


def streak_down(panel: pd.DataFrame) -> pd.DataFrame:
    """连续下跌天数：当日 pctChg<0 计 1，连续累积。"""
    down = (panel["pct_chg"] < 0).astype("float64")
    return _streak(panel, down)


def _streak(panel: pd.DataFrame, flag: pd.Series) -> pd.DataFrame:
    """连续 True 计数（按 code 分组、按日期升序）。纯 Python 循环仅用于 streak，
    面板按 code,date 排序，一次线性扫描 O(行数)。"""
    grp = panel["code"].to_numpy()
    f = flag.to_numpy(dtype="float64")
    out = np.zeros(len(panel), dtype="float64")
    run = 0.0
    prev_grp = None
    for i in range(len(panel)):
        if grp[i] != prev_grp:
            run = 0.0
            prev_grp = grp[i]
        if f[i] > 0:
            run += 1.0
        else:
            run = 0.0
        out[i] = run
    return _out(panel, out, "streak")


def break_high_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """是否突破 N 日最高（1/0）：当日复权最高价 > 前 N 根 K 线复权最高价的最大值。

    「前 N 根」不含当日（T 日突破的是之前 N 天的墙）；前 N 根不足 N 根（新股）
    为 NaN（不视为突破）。用最高价对最高价比较（口径说明见设计文档）。
    """
    n = _check_window(n)
    hq = (panel["high"] * panel["af"]).to_numpy(dtype="float64")
    prev_max = _by_code(panel, hq, lambda x: _shift1(_sw_max(x, n)))
    with np.errstate(invalid="ignore"):
        brk = (hq > prev_max).astype("float64")
    brk = np.where(np.isfinite(prev_max), brk, np.nan)
    return _out(panel, brk, f"break_high_{n}")


# ---- ETF 零件：输入 panel 为**单只 ETF 的日线长表**（DataStore.etfs[code]，
# 列 date/close/close_adj/ret 等，Tushare fund_daily × fund_adj）----
# 口径：ETF 跨日收益与均线都用 close_adj（= close × fund_adj.adj_factor，复权口径，
# 与个股 adj_nav 同一规则；rules.md 第 2 节）。

def etf_above_ma_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """ETF 复权收盘是否在 N 日均线上方（1/0）。panel 必须是单只 ETF 的日线长表。

    均线用 numpy 滑动窗口（与股票侧同口径，结果不依赖序列起点）。
    前 n-1 行无均线定义：不可比较 → 0（不在均线上方），不保留 NaN，
    因为该零件只作为策略条件使用，0 = 条件不成立，与「数据不足」同处理。
    """
    n = _check_window(n)
    close = panel["close_adj"].to_numpy(dtype="float64")
    ma = _sw_mean(close, n)
    with np.errstate(invalid="ignore"):
        res = (close > ma).astype("float64")
    res = np.where(np.isfinite(ma), res, 0.0)
    return _out(panel, res, f"etf_above_ma_{n}")


# ================================================================ 新零件（rules.md 7.5 第 3 版）
#
# 规模 / 估值 / 财务 / 预告快报 / 行业 / 通用分位。全部 threshold_kind="none"
# （只作打分因子 / rank / 嵌套 of 的基零件；能否作条件由 config 校验把关）。
# 财务与预告快报列已在 DataStore 里严格按 ann_date 对齐（见 prices.align_by_ann_date）。

def size_ln(panel: pd.DataFrame) -> pd.DataFrame:
    """规模：流通市值（daily_basic.circ_mv）的自然对数（rules.md 7.5 规模零件）。"""
    return _out(panel, np.log(panel["circ_mv"].to_numpy(dtype="float64")), "size_ln")


def _col(panel: pd.DataFrame, col: str, name: str) -> pd.DataFrame:
    """原样取一列作为零件值（数值列）。"""
    return _out(panel, pd.to_numeric(panel[col], errors="coerce").to_numpy(), name)


def pe_ttm(panel: pd.DataFrame) -> pd.DataFrame:
    """估值：市盈率 TTM（daily_basic.pe_ttm 原值；rules.md 7.5 估值零件的基值）。"""
    return _col(panel, "pe_ttm", "pe_ttm")


def pb(panel: pd.DataFrame) -> pd.DataFrame:
    """估值：市净率（daily_basic.pb 原值）。"""
    return _col(panel, "pb", "pb")


def ps_ttm(panel: pd.DataFrame) -> pd.DataFrame:
    """估值：市销率 TTM（daily_basic.ps_ttm 原值）。"""
    return _col(panel, "ps_ttm", "ps_ttm")


def roe(panel: pd.DataFrame) -> pd.DataFrame:
    """财务：ROE（fina_indicator.roe，严格按 ann_date 对齐后的最新一期）。"""
    return _col(panel, "roe", "roe")


def or_yoy(panel: pd.DataFrame) -> pd.DataFrame:
    """财务：营业收入同比增长率 %（ann_date 对齐）。"""
    return _col(panel, "or_yoy", "or_yoy")


def netprofit_yoy(panel: pd.DataFrame) -> pd.DataFrame:
    """财务：归母净利润同比增长率 %（ann_date 对齐）。"""
    return _col(panel, "netprofit_yoy", "netprofit_yoy")


def fc_type_code(panel: pd.DataFrame) -> pd.DataFrame:
    """业绩预告：最近一次预告类型的数值编码（预增=2/略增=1/扭亏=1.5/续盈=0.5/
    预减=-2/略减=-1/首亏=-1.5/续亏=-0.5/不确定=0；无预告 → NaN）。"""
    return _col(panel, "fc_type_code", "fc_type_code")


def fc_chg_mid(panel: pd.DataFrame) -> pd.DataFrame:
    """业绩预告：最近一次预告的变动幅度 %（(p_change_min+p_change_max)/2，
    单边缺则取另一边；无预告 → NaN）。"""
    return _col(panel, "fc_chg_mid", "fc_chg_mid")


def fc_days(panel: pd.DataFrame) -> pd.DataFrame:
    """业绩预告：距最近一次预告公告日的自然日数（T − ann_date；无预告 → NaN）。"""
    return _col(panel, "fc_days", "fc_days")


def ex_yoy(panel: pd.DataFrame) -> pd.DataFrame:
    """业绩快报：最近一次快报的净利同比 %（yoy_net_profit，ann_date 对齐）。"""
    return _col(panel, "ex_yoy", "ex_yoy")


def ex_days(panel: pd.DataFrame) -> pd.DataFrame:
    """业绩快报：距最近一次快报公告日的自然日数（无快报 → NaN）。"""
    return _col(panel, "ex_days", "ex_days")


def ts_pct(panel: pd.DataFrame, n: int, base: pd.Series) -> pd.DataFrame:
    """通用：基零件值的过去 n 根K线时序分位（含当日，0~1）。

    窗口 = 该股最近 n 行（K 线行，非交易日历）；窗口不完整或窗口内任何值
    非有限 → NaN（全窗口语义，确定性）。分位 = 窗口内 ≤ 当日值的比例。
    """
    n = _check_window(n)
    vals = np.asarray(base, dtype="float64")

    def f(w):
        cur = w[:, -1:]
        ok = np.isfinite(w).all(axis=1)
        with np.errstate(invalid="ignore"):
            pct = (w <= cur).mean(axis=1)
        return np.where(ok, pct, np.nan)

    out = _by_code(panel, vals, lambda x: _sw_apply(x, n, f))
    return _out(panel, out, f"ts_pct_{n}")


def _rank_pct(arr: np.ndarray) -> np.ndarray:
    """截面升序百分位（0~1，并列平均名次；全 NaN / 单点 → 0.5 / NaN 保留）。"""
    a = np.asarray(arr, dtype="float64")
    out = np.full(len(a), np.nan)
    mask = np.isfinite(a)
    m = int(mask.sum())
    if m == 1:
        out[mask] = 0.5
    elif m > 1:
        r = pd.Series(a[mask]).rank(method="average").to_numpy()
        out[mask] = (r - 1.0) / (m - 1.0)
    return out


def _group_pct_vec(vals: np.ndarray, gids: np.ndarray) -> np.ndarray:
    """组内升序百分位（0~1，并列平均名次）——_rank_pct 的全量向量化版。

    逐组语义逐位同值：组内有限值 m≥2 → (平均名次-1)/(m-1)；m==1 → 0.5；
    m==0（组内全 NaN）→ 整组 NaN；NaN 值位置 → NaN。并列 = 浮点相等段
    （-0.0==0.0 与 pandas rank 一致）。gids 为小整数组码（≥0）。

    性能优化轮（rules.md 第 12 章）：剖析显示 ind_rank/xsec_pct 的
    逐组循环在全量面板（7.8M 行 × 18 万组）上占单配置首算的 ~79%
    （pd.Series.rank 179,796 次 + 字符串键 argsort 9.3s）——lexsort
    一次排全量、段边界取平均名次后消掉全部逐组 pandas 调用。
    """
    a = np.asarray(vals, dtype="float64")
    g = np.asarray(gids)
    out = np.full(len(a), np.nan)
    m = np.isfinite(a)
    if not m.any():
        return out
    c = g[m]
    v = a[m]
    gcount = np.bincount(c)                       # 每组有限值个数
    order = np.lexsort((v, c))                    # 主键组、次键值
    cs, vs = c[order], v[order]
    n = len(order)
    brk = np.r_[True, (cs[1:] != cs[:-1]) | (vs[1:] != vs[:-1])]
    seg = np.cumsum(brk) - 1
    starts = np.flatnonzero(brk)
    counts = np.diff(np.r_[starts, n])
    avg0_abs = starts[seg] + (counts[seg] - 1) / 2.0   # 段平均绝对位置
    grp_brk = np.r_[True, cs[1:] != cs[:-1]]
    gstart = np.zeros(len(gcount), dtype="float64")
    gstart[cs[grp_brk]] = np.flatnonzero(grp_brk)
    avg0 = avg0_abs - gstart[cs]                  # → 组内 0-based 平均名次
    gn = gcount[cs]
    pct = np.where(gn >= 2, avg0 / np.maximum(gn - 1.0, 1.0), 0.5)
    res = np.empty(n, dtype="float64")
    res[order] = pct
    out[m] = res
    return out


def xsec_pct(panel: pd.DataFrame, base: pd.Series) -> pd.DataFrame:
    """通用：当日截面分位（0~1）——面板内同一 date **值**的全部行参与排名。

    这是纯函数口径（不感知股票池/可交易过滤）；策略层打分流程会在
    股票池截面上再排名（单调变换可复合，见 notes 与 selftest）。

    分组键是「日期值」，与 ind_rank 同构。整日整组参与排名：日期切片以
    整日为单位进出，天然全等。组序不影响组内名次——pd.factorize 整数码
    即作组键（无须重映射到日期序），再走 _group_pct_vec 一次算完全量
    （旧逐组 _rank_pct 循环在语义上逐位同值，见该函数 docstring）。
    """
    vals = np.asarray(base, dtype="float64")
    dates = panel["date"].to_numpy()
    out = np.full(len(panel), np.nan)
    if len(dates) == 0:
        return _out(panel, out, "xsec_pct")
    codes, _uniques = pd.factorize(dates, use_na_sentinel=False)
    out = _group_pct_vec(vals, np.asarray(codes))
    return _out(panel, out, "xsec_pct")


def ind_rank(panel: pd.DataFrame, base: pd.Series) -> pd.DataFrame:
    """行业：当日同申万一级行业内的分位（0~1）；无行业归属 → NaN。

    与 xsec_pct 同一排名实现，分组键为 (date, l1_code)。复合整数组键
    date_code × (n_ind+1) + (ind_code+1)（factorize 整数码，量级 ~12 万
    无溢出），无行业行不参与排名、整行 NaN——与旧逐组循环逐位同值。
    """
    vals = np.asarray(base, dtype="float64")
    dates = panel["date"].to_numpy()
    inds = panel["l1_code"].to_numpy()
    out = np.full(len(panel), np.nan)
    if len(dates) == 0:
        return _out(panel, out, "ind_rank")
    d_codes, _d_uniq = pd.factorize(dates, use_na_sentinel=False)
    i_codes, _i_uniq = pd.factorize(inds, use_na_sentinel=True)
    i_codes = np.asarray(i_codes)
    no_ind = i_codes < 0
    n_ind = len(_i_uniq) + 1
    # 复合整数组键：真实行业码 +1 ≥ 1；无行业行 +1 = 0，后缀 0 只被
    # 无行业行占据（不与任何真实 (date, industry) 组冲突），天然独立成组。
    gids = np.asarray(d_codes, dtype="int64") * n_ind + (i_codes + 1)
    if no_ind.any():
        vals = vals.copy()
        vals[no_ind] = np.nan          # 无行业 → 组内全 NaN → 整组 NaN
    out = _group_pct_vec(vals, gids)
    return _out(panel, out, "ind_rank")


# ================================================================ 资金面零件（rules.md 7.5 第 3.4 版）
#
# 数据事实与对齐口径（第 1 步体检 + 本步核验）：
#   * top_list / top_inst：无 ann_date，T 日盘后披露 → T 日收盘信号可用
#     trade_date ≤ T 的记录（面板列已在 prices.DataStore 里按 ≤ T 对齐）。
#   * margin_detail（rzye 融资余额，单位**元**）/ hk_hold（北向持股，T 日数据
#     次日披露）→ T 日决策只能用 trade_date ≤ T-1（面板列按 < T 对齐）。
#   * hk_hold 只取 exchange=SH/SZ；北向明细 2016-07-04 起才有（2014-11-17 起
#     只有整体资金流），之前的日期一律 NaN（绝不 0 填充）。
#   * daily_basic.circ_mv 单位**万元**（×1e4 → 元）；margin_detail.rzye 单位元。
#   * top_inst.net_buy = 净成交额（买入−卖出，元；已用 top_list 的
#     l_buy/l_sell 合计逐位核验：sum(net_buy)=net_amount、sum(卖出列)=l_buy）。

def top_list_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """龙虎榜：近 N 日是否上过龙虎榜（1/0）。

    窗口 = 该股最近 n 行K线（含当日；当日上榜也算，T 日盘后披露口径）。
    tl_on_list 是 0/1 事件标记（同日对齐），窗口内最大值即「是否上过」；
    窗口不完整（前 n-1 行）→ NaN（与 break_high_n 等窗口零件同口径）。
    """
    n = _check_window(n)
    v = _by_code(panel, "tl_on_list", lambda x: _sw_max(x, n))
    return _out(panel, v, f"top_list_{n}")


def inst_netbuy(panel: pd.DataFrame) -> pd.DataFrame:
    """龙虎榜：最近一次上榜事件的机构席位净买入占比（%）。

    = 该次上榜「机构专用」席位 net_buy 合计（元）/ 该次上榜全部理由行 l_amount
    最大值（元）× 100；上榜无机构席位 → 0（真实零，非缺失填充）；从未上榜 → NaN。
    事件按 trade_date ≤ T 对齐（T 日上榜当日即有值，之后保持到下一次上榜）。
    """
    return _col(panel, "tl_inst_netbuy_pct", "inst_netbuy")


def margin_ratio(panel: pd.DataFrame) -> pd.DataFrame:
    """两融：融资余额占流通市值比（%）。

    = margin_rzye（元，≤ T-1 最新披露）/（circ_mv（万元，T 日）× 1e4 → 元）
    × 100。两融 T+1 披露、市值 T 日盘后可得，两侧任一缺失 → NaN。
    """
    zy = panel["margin_rzye"].to_numpy(dtype="float64")
    cm = panel["circ_mv"].to_numpy(dtype="float64") * 1.0e4
    with np.errstate(divide="ignore", invalid="ignore"):
        r = zy / cm * 100.0
    return _out(panel, r, "margin_ratio")


def margin_chg_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """两融：融资余额近 N 日变化率（%）。

    = 对齐后 rzye[T] / rzye[T-n] − 1（rzye 为 ≤ T-1 披露口径，T-n 行即
    ≤ T-n-1 口径）；窗口不完整 / 前值为 0 / 任一缺失 → NaN。
    """
    n = _check_window(n)
    cur = panel["margin_rzye"].to_numpy(dtype="float64")
    prev = _grouped(panel)["margin_rzye"].shift(n).to_numpy(dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (cur / prev - 1.0) * 100.0
    r = np.where(prev == 0.0, np.nan, r)
    return _out(panel, r, f"margin_chg_{n}")


def hk_ratio(panel: pd.DataFrame) -> pd.DataFrame:
    """北向：北向持股占流通股本比（%）。hk_hold ratio 原值（vol/流通股本×100，
    SH/SZ 记录），≤ T-1 披露对齐；无记录（含 2016-07-04 前）→ NaN。"""
    return _col(panel, "hk_ratio", "hk_ratio")


def hk_chg_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """北向：持股占比近 N 日变化（百分点）= 占比[T] − 占比[T-n]。

    对齐口径同 hk_ratio（≤ T-1）；窗口不完整 / 任一缺失 → NaN。
    """
    n = _check_window(n)
    cur = panel["hk_ratio"].to_numpy(dtype="float64")
    prev = _grouped(panel)["hk_ratio"].shift(n).to_numpy(dtype="float64")
    return _out(panel, cur - prev, f"hk_chg_{n}")


# ================================================================ 嵌套 spec 解析

def canon_spec(spec: dict) -> str:
    """spec 的规范 JSON（缓存键 / 确定性比较用）。"""
    import json
    return json.dumps(spec, sort_keys=True, ensure_ascii=False)


def eval_spec(panel: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """解析并求值 spec := {op, n?, of?}；未知零件/缺参数直接抛 ValueError。"""
    if not isinstance(spec, dict) or "op" not in spec:
        raise ValueError(f"零件 spec 必须是 {{op, n?, of?}} 形式，得到 {spec!r}")
    name = str(spec["op"])
    if name not in OPERATORS:
        raise ValueError(f"未知零件 {name!r}（可用：{sorted(OPERATORS)}）")
    meta = OPERATOR_META[name]
    if meta.get("has_of"):
        if "of" not in spec:
            raise ValueError(f"零件 {name} 需要嵌套 of 参数")
        base = eval_spec(panel, spec["of"])["value"]
        if meta.get("has_window"):
            return OPERATORS[name](panel, int(spec["n"]), base)
        return OPERATORS[name](panel, base)
    if meta.get("has_window"):
        if spec.get("n") is None:
            raise ValueError(f"零件 {name} 需要窗口参数 n")
        return OPERATORS[name](panel, int(spec["n"]))
    return OPERATORS[name](panel)


# ================================================================ 注册表
#
# OPERATOR_META 是零件的**单一事实来源**（rules.md 8.3：新零件登记后配置校验与
# 猴子抽样池自动生效，无需手改多处）：
#   has_window      零件是否带窗口参数 n（决定 config 的 OP_ARG / NO_ARG 形态、
#                   funnel 的猴子抽样池 OPS_WITH_N / OPS_NO_ARG）
#   has_of          零件是否嵌套引用其他零件（spec 需带 of；funnel 猴子生成时
#                   以随机基零件填充）
#   threshold_kind  条件阈值量纲：pct / mult / streak（决定 config._parse_condition
#                   的档位校验、funnel 的量纲分派与猴子阈值抽样）；"none" =
#                   无阈值量纲，只能作打分因子 / rank / 嵌套基值，不能作 buy/sell 条件。
# 顺序即猴子随机池顺序（rng.choice 按元组顺序抽取，同 seed 生成结果保持稳定），
# 内置零件的排列与第 1 轮 OPS_WITH_N + OPS_NO_ARG 的拼接顺序一致。
OPERATOR_META: dict[str, dict] = {
    "ret_n":           {"has_window": True,  "threshold_kind": "pct"},
    "ma_n":            {"has_window": True,  "threshold_kind": "pct"},
    "close_over_ma_n": {"has_window": True,  "threshold_kind": "mult"},
    "dist_high_n":     {"has_window": True,  "threshold_kind": "pct"},
    "dist_low_n":      {"has_window": True,  "threshold_kind": "pct"},
    "vol_ratio_n":     {"has_window": True,  "threshold_kind": "mult"},
    "turn_ma_n":       {"has_window": True,  "threshold_kind": "pct"},
    "vol_n":           {"has_window": True,  "threshold_kind": "pct"},
    "atr_close_n":     {"has_window": True,  "threshold_kind": "pct"},
    "break_high_n":    {"has_window": True,  "threshold_kind": "mult"},
    "etf_above_ma_n":  {"has_window": True,  "threshold_kind": "mult"},
    "close_pos_range": {"has_window": False, "threshold_kind": "mult"},
    "turn":            {"has_window": False, "threshold_kind": "pct"},
    "streak_up":       {"has_window": False, "threshold_kind": "streak"},
    "streak_down":     {"has_window": False, "threshold_kind": "streak"},
    # ---- rules.md 7.5 第 3 版新零件 ----
    "size_ln":         {"has_window": False, "threshold_kind": "none"},   # 规模
    "pe_ttm":          {"has_window": False, "threshold_kind": "none"},   # 估值
    "pb":              {"has_window": False, "threshold_kind": "none"},
    "ps_ttm":          {"has_window": False, "threshold_kind": "none"},
    "roe":             {"has_window": False, "threshold_kind": "none"},   # 财务（ann_date 对齐）
    "or_yoy":          {"has_window": False, "threshold_kind": "none"},
    "netprofit_yoy":   {"has_window": False, "threshold_kind": "none"},
    "fc_type_code":    {"has_window": False, "threshold_kind": "none"},   # 业绩预告
    "fc_chg_mid":      {"has_window": False, "threshold_kind": "none"},
    "fc_days":         {"has_window": False, "threshold_kind": "none"},
    "ex_yoy":          {"has_window": False, "threshold_kind": "none"},   # 业绩快报
    "ex_days":         {"has_window": False, "threshold_kind": "none"},
    "ts_pct":          {"has_window": True,  "has_of": True, "threshold_kind": "none"},  # 通用时序分位
    "xsec_pct":        {"has_window": False, "has_of": True, "threshold_kind": "none"},  # 通用截面分位
    "ind_rank":        {"has_window": False, "has_of": True, "threshold_kind": "none"},  # 行业内排名
    # ---- rules.md 7.5 第 3.4 版资金面零件（龙虎榜 / 两融 / 北向）----
    "top_list_n":      {"has_window": True,  "threshold_kind": "mult"},   # 近 N 日上过榜（0/1）
    "inst_netbuy":     {"has_window": False, "threshold_kind": "pct"},    # 机构席位净买入占比 %
    "margin_ratio":    {"has_window": False, "threshold_kind": "pct"},    # 两融余额/流通市值 %
    "margin_chg_n":    {"has_window": True,  "threshold_kind": "pct"},    # 两融余额 N 日变化率 %
    "hk_ratio":        {"has_window": False, "threshold_kind": "pct"},    # 北向持股占比 %
    "hk_chg_n":        {"has_window": True,  "threshold_kind": "pct"},    # 北向占比 N 日变化（pp）
}

OPERATORS: dict[str, callable] = {
    "ret_n": ret_n,
    "ma_n": ma_n,
    "close_over_ma_n": close_over_ma_n,
    "dist_high_n": dist_high_n,
    "dist_low_n": dist_low_n,
    "close_pos_range": close_pos_range,
    "vol_ratio_n": vol_ratio_n,
    "turn": turn,
    "turn_ma_n": turn_ma_n,
    "vol_n": vol_n,
    "atr_close_n": atr_close_n,
    "streak_up": streak_up,
    "streak_down": streak_down,
    "break_high_n": break_high_n,
    "etf_above_ma_n": etf_above_ma_n,
    # rules.md 7.5 第 3 版新零件
    "size_ln": size_ln,
    "pe_ttm": pe_ttm,
    "pb": pb,
    "ps_ttm": ps_ttm,
    "roe": roe,
    "or_yoy": or_yoy,
    "netprofit_yoy": netprofit_yoy,
    "fc_type_code": fc_type_code,
    "fc_chg_mid": fc_chg_mid,
    "fc_days": fc_days,
    "ex_yoy": ex_yoy,
    "ex_days": ex_days,
    "ts_pct": ts_pct,
    "xsec_pct": xsec_pct,
    "ind_rank": ind_rank,
    # rules.md 7.5 第 3.4 版资金面零件
    "top_list_n": top_list_n,
    "inst_netbuy": inst_netbuy,
    "margin_ratio": margin_ratio,
    "margin_chg_n": margin_chg_n,
    "hk_ratio": hk_ratio,
    "hk_chg_n": hk_chg_n,
}

# ---- 已登记新零件（engine/register_operator.py 写入）的持久化注册表 ----

REGISTRY_ENV = "ENGINE_OPERATOR_REGISTRY"     # 测试时重定向注册表路径


def _registry_path() -> Path:
    """注册表 JSON 路径：默认 engine/operator_registry.json，可用环境变量重定向。"""
    env = os.environ.get(REGISTRY_ENV, "").strip()
    return Path(env) if env else (Path(__file__).resolve().parent / "operator_registry.json")


def _load_registered_operators() -> None:
    """把注册表里已登记的新零件并入 OPERATORS / OPERATOR_META（import 时执行）。

    登记项损坏（文件丢失 / 函数缺失 / 元数据不全）直接抛 RuntimeError——
    注册表是引擎语义的一部分，静默跳过会让「配置校验放行、回测时才炸」，
    审计上不可接受。本仓库当前未登记任何新零件（注册表文件不存在 → 空操作）。
    """
    p = _registry_path()
    if not p.is_file():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RuntimeError(f"零件注册表 {p} 无法读取：{e!r}") from e
    entries = data.get("operators")
    if not isinstance(entries, dict):
        raise RuntimeError(f"零件注册表 {p} 格式错误：缺少 operators 映射")
    for name in sorted(entries):
        m = entries[name]
        try:
            rel = str(m["module"])
            fn_name = str(m["function"])
            has_window = bool(m["has_window"])
            kind = str(m["threshold_kind"])
        except (KeyError, TypeError) as e:
            raise RuntimeError(f"零件注册表 {p} 中 {name!r} 元数据不全：{e!r}") from e
        if kind not in ("pct", "mult", "streak", "none"):
            raise RuntimeError(f"零件注册表 {p} 中 {name!r} 阈值量纲非法：{kind!r}")
        path = Path(rel)
        if not path.is_absolute():
            path = guard.ROOT / rel
        if not path.is_file():
            raise RuntimeError(f"注册零件 {name!r} 的源文件不存在：{path}")
        mod_name = f"_operator_registry_{name}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)          # type: ignore[union-attr]
            fn = getattr(mod, fn_name)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"注册零件 {name!r} 无法从 {path} 加载函数 {fn_name}：{e!r}") from e
        OPERATORS[name] = fn
        OPERATOR_META[name] = {"has_window": has_window, "threshold_kind": kind}


_load_registered_operators()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("注册零件：")
    for k, fn in OPERATORS.items():
        print(f"  {k:18s} {fn.__doc__.splitlines()[0] if fn.__doc__ else ''}")
    try:
        ret_n(pd.DataFrame({"code": [], "adj_nav": []}), 7)
    except ValueError as e:
        print(f"OK 非法窗口拦截：{e}")

# -*- coding: utf-8 -*-
"""B 组新零件模块（parts/b_ops.py）——第 2 轮按审计结论补交的实现。

原样遵守零件契约（与 engine/operators.py 内置零件一致）：
  * 输入：股票长表面板（按 code,date 升序；列含 date/code/l1_code/pb/ps_ttm/
    fc_chg_mid/fc_days/adj_nav 等，见 engine/prices.py DataStore.panel）；
  * 输出：同 index 的单列 "value" DataFrame（float64；缺失一律 NaN，绝不 0 填充）；
  * 只回看（as-of 一致），确定性（同输入两次计算 bitwise 一致）；
  * 窗口零件：n 只取 rules.md 第 7 节档位 3/5/10/20/60/120/250，非法即抛
    ValueError；每码前 n−1 行（窗口不完整）为 NaN。

本文件自包含（只依赖 numpy/pandas，不 import engine/ 任何模块）——注册表在
engine/operators.py import 期加载本文件，避免循环依赖。

登记（B 组已执行）：
  python engine/register_operator.py parts/b_ops.py \
      --threshold-kind fc_demean_ind=pct,ulcer_n=pct
  （ind_median_* 三个为 threshold none=只作因子/rank，缺省即 none）

声明的精确语义（重审按此对拍；与 notes/search_agent_b.md 申请小节一致）：

1) ind_median_pb / ind_median_ps / ind_median_fc_chg_mid：当日（date）申万
   一级行业（l1_code；无行业 NaN 自成一组，组键加后缀 "__无行业__"）内
   基列（pb / ps_ttm / fc_chg_mid）**有限值的中位数**；忽略组内非有限值；
   组内全 NaN → NaN。输出与该行自身基值是否缺失无关（行业级特征，给缺
   基值的股票也提供行业锚）。threshold_kind=none（只能作打分因子 / rank，
   不能作条件）。

2) fc_demean_ind：组 = 当日 (date, l1_code)（无行业 NaN 自成一组）；参与者 =
   组内 fc_chg_mid 有限 且 fc_days 有限 且 fc_days ≤ 60（自然日，60 含当日，
   61 剔除）的行，**含自身**；med = 参与者 fc_chg_mid 中位数（pandas median
   忽略非有限值）；输出 = 该行 fc_chg_mid − med（pct 量纲）。自身 fc_chg_mid
   缺失 → NaN；组内无任何参与者 → NaN。自身有预告但 fc_days > 60（陈旧预告）
   时：自身不参与中位数，输出仍 = fc_chg_mid − med（如实声明此边界）。

3) ulcer_n：溃疡指数（Ulcer Index，防御因子，替代撤回的 resid_vol_n）。
   窗口 = 该股最近 n 行K线（含当日，按面板行序，与其余窗口零件同口径）；
   对窗口内第 j 行：dd_j = adj_nav_j / max(adj_nav[窗口起点..j]) − 1
   （复权净值口径，≤0）；输出 = sqrt( mean_j(dd_j²) ) × 100，单位 %，≥0。
   **日历跨度边界（与其他窗口零件不同，如实声明）**：窗口首行与末行的
   交易日历位置差 > 254（即窗口未完整落在最近 255 个交易日内，长停牌股
   的行窗横跨远超一年）→ NaN。理由：① 长停牌股的行窗回填的是陈旧价格
   路径，与正常股票的溃疡指数不可比；② 官方登记撕报纸（register_operator
   daterange 口径）用「截至 T 的最后 255 个交易日」切片，窗口必须完整
   落在其中才能全量=切片逐位一致（首次登记实测：无此边界时 600074.SH
   在 T=20140709 切片=NaN/全量=5.26，被登记门槛拒绝）。回测打分中该
   NaN 按缺失语义映射中性 0.5。
   前 n−1 行（窗口不完整）→ NaN；adj_nav 引擎保证非缺失，窗口完整且
   日历跨度合格即有值、无退化分支。数值越小 = 离新高越近 / 回撤越浅 =
   越防御；作因子建议负权。threshold_kind=pct。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# rules.md 第 7 节窗口档位（自包含副本，不 import engine/operators）
ALLOWED_WINDOWS = (3, 5, 10, 20, 60, 120, 250)

_NO_IND = "__无行业__"          # 无行业组的后缀键（与审计探针 _naive_* 一致）


def _check_window(n: int) -> int:
    n = int(n)
    if n not in ALLOWED_WINDOWS:
        raise ValueError(f"窗口长度 {n} 不在 rules.md 第 7 节档位 {list(ALLOWED_WINDOWS)} 中")
    return n


def _out(panel: pd.DataFrame, values) -> pd.DataFrame:
    """同 index 单列 value 输出（契约同 engine/operators._out）。"""
    if isinstance(values, pd.Series):
        return pd.DataFrame({"value": values.astype("float64")}, index=panel.index)
    v = np.asarray(values, dtype="float64")
    if len(v) != len(panel):
        raise ValueError(f"输出长度 {len(v)} != 面板长度 {len(panel)}")
    return pd.DataFrame({"value": v}, index=panel.index)


def _date_ind_key(panel: pd.DataFrame) -> pd.Series:
    """组键：date|l1_code（无行业 NaN → '__无行业__' 自成一组）。"""
    return (panel["date"].astype(str) + "|"
            + panel["l1_code"].astype("string").fillna(_NO_IND))


def _ind_median_of(panel: pd.DataFrame, base: np.ndarray) -> pd.DataFrame:
    """当日 (date,l1) 组内基值中位数（忽略非有限值；组内全 NaN → NaN）。"""
    s = pd.Series(np.asarray(base, dtype="float64"), index=panel.index,
                  dtype="float64")
    med = s.groupby(_date_ind_key(panel), sort=False).transform("median")
    return _out(panel, med)


def ind_median_pb(panel: pd.DataFrame) -> pd.DataFrame:
    """当日申万一级行业内 pb 的中位数（行业估值锚；组内全 NaN → NaN）。"""
    return _ind_median_of(panel, pd.to_numeric(panel["pb"], errors="coerce")
                          .to_numpy(dtype="float64"))


def ind_median_ps(panel: pd.DataFrame) -> pd.DataFrame:
    """当日申万一级行业内 ps_ttm 的中位数（行业估值锚；组内全 NaN → NaN）。"""
    return _ind_median_of(panel, pd.to_numeric(panel["ps_ttm"], errors="coerce")
                          .to_numpy(dtype="float64"))


def ind_median_fc_chg_mid(panel: pd.DataFrame) -> pd.DataFrame:
    """当日申万一级行业内 fc_chg_mid 的中位数（行业预告动量锚；全 NaN → NaN）。"""
    return _ind_median_of(panel, pd.to_numeric(panel["fc_chg_mid"], errors="coerce")
                          .to_numpy(dtype="float64"))


def fc_demean_ind(panel: pd.DataFrame) -> pd.DataFrame:
    """预告意外度的行业调整：fc_chg_mid − 同 (date,l1) 内「距公告 ≤60 自然日」
    预告（含自身）的 fc_chg_mid 中位数（pct 量纲；边界语义见模块 docstring）。"""
    fcm = pd.to_numeric(panel["fc_chg_mid"], errors="coerce").to_numpy(dtype="float64")
    fd = pd.to_numeric(panel["fc_days"], errors="coerce").to_numpy(dtype="float64")
    ok = np.isfinite(fcm) & np.isfinite(fd) & (fd <= 60.0)
    masked = pd.Series(np.where(ok, fcm, np.nan), index=panel.index, dtype="float64")
    med = masked.groupby(_date_ind_key(panel), sort=False).transform("median")
    out = (pd.Series(fcm, index=panel.index, dtype="float64") - med)
    return _out(panel, out)


def ulcer_n(panel: pd.DataFrame, n: int) -> pd.DataFrame:
    """溃疡指数：最近 n 行 adj_nav 的窗口内回撤深度平方均值的开方（%）。

    dd_j = adj_nav_j / cummax(adj_nav[窗口起点..j]) − 1（≤0）；
    输出 = sqrt(mean(dd²))×100 ≥ 0；前 n−1 行（每码）→ NaN。
    日历跨度边界：窗口首末行交易日历位置差 > 254（未完整落在最近 255 个
    交易日内，长停牌股）→ NaN（语义与理由见模块 docstring 第 3 条）。
    只依赖该股自身行（as-of 切片撕报纸安全；无横截面依赖）。
    """
    n = _check_window(n)
    nav = pd.to_numeric(panel["adj_nav"], errors="coerce").to_numpy(dtype="float64")
    codes = panel["code"].to_numpy()
    dates = panel["date"].to_numpy()
    out = np.full(len(panel), np.nan, dtype="float64")
    if len(panel) == 0:
        return _out(panel, out)
    # 交易日历位置（面板 unique 日期升序；切片/全量的位置差同构，见 docstring）
    cal = np.unique(dates)
    pos = np.searchsorted(cal, dates).astype("int64")
    # 面板按 (code,date) 升序：按连续 code 块处理
    bounds = np.flatnonzero(np.r_[True, codes[1:] != codes[:-1]])
    bounds = np.r_[bounds, len(codes)]
    for b0, b1 in zip(bounds[:-1], bounds[1:]):
        L = int(b1 - b0)
        if L < n:
            continue                      # 该码窗口永不完整 → 全 NaN
        w = np.lib.stride_tricks.sliding_window_view(nav[b0:b1], n)
        with np.errstate(invalid="ignore", divide="ignore"):
            cm = np.maximum.accumulate(w, axis=1)     # 每窗口从起点到 j 的最高
            dd = w / cm - 1.0                          # ≤0（NaN 传播）
            sq = np.where(np.isfinite(dd), dd * dd, np.nan)
            with np.errstate(invalid="ignore"):
                ui = np.sqrt(np.nanmean(sq, axis=1)) * 100.0
        ui = np.where(np.isfinite(ui), ui, np.nan)     # 窗口内含 NaN adj_nav → NaN
        # 日历跨度边界：窗口首末行的交易日历位置差 ≤ 254 才有效
        p = pos[b0:b1]
        span = p[n - 1:] - p[: L - n + 1]
        ui = np.where(span <= 254, ui, np.nan)
        out[b0 + n - 1: b1] = ui
    return _out(panel, out)

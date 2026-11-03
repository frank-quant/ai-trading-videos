# -*- coding: utf-8 -*-
"""
engine/prices.py —— 统一数据接口（Tushare Pro 版，rules.md 第 2 / 7.5 / 7.6 节）

数据源：data/raw/ 下 tools/fetch_tushare.py 拉取的 15 个 parquet（全部经 guard）。
日期一律 Tushare 口径 YYYYMMDD 字符串（字典序即时间序）。

口径（rules.md 第 3.1 版第 2 节）：
  * 跨日收益一律用 close × adj_factor（adj_nav）；日内比例（开盘/前收、振幅位置）
    用不复权价。复权连续性自检：adj_nav 日涨幅 vs pct_chg，偏差 > 0.5% 落盘
    reports/price_check.md（CLI --check）。
  * 涨跌停价直接用 stk_limit 的 up_limit / down_limit，不自己推算；当日无记录
    → 该日无涨跌停约束（列 NaN）。
  * 停牌：Tushare daily 无停牌日行情行（无行即无法成交，自然顺延）；suspend_d
    的全天停牌记录作为显式标记（is_suspended），供审计与核对。
  * ST：namechange 历史名称按当日判断（start_date ≤ T < end_date 的记录名称含
    "ST" 即 ST；不能用今天的名称回看历史）。无任何变更记录的股票视为从未 ST。
  * 上市满 250 个交易日：stock_basic.list_date 起按交易日历数交易日（≥250）。
  * 股票池：index_members 按当日快照——每只指数取「最近一次样本 ≤ T」的成分并集
    （沪深300 ∪ 中证500）；缺席下一次样本即在该样本日调出。
  * 财务 / 预告 / 快报严格按 ann_date 对齐：T 日只能看到 ann_date ≤ T 的最新一条
    （同 ann_date 取 end_date 更晚者）。对齐逻辑是纯函数（align_by_ann_date），
    审计可用变异输入复算。
  * 行业：申万一级，index_member_all 按 in_date ≤ T < out_date 判定当日归属。
  * 资金面（rules.md 7.5）：龙虎榜 top_list/top_inst 无 ann_date、T 日盘后披露
    → T 日收盘信号可用 trade_date ≤ T 记录；两融 margin_detail 与北向 hk_hold
    T 日数据次日披露 → 只用 trade_date < T（≤ T-1）；北向只用 exchange=SH/SZ。
    对齐一律走 align_latest_by_trade_date（纯函数）；缺失 → NaN，不 0 填充。
  * ETF：fund_daily × fund_adj，跨日收益用 close × adj_factor。

所有对 data/ 的读取都经过 engine/guard.py。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402  必须先于 numpy/pandas（guard 钉死 BLAS 线程环境变量）

import numpy as np
import pandas as pd

ROOT = guard.ROOT
RAW = guard.RAW_DIR
REPORTS_DIR = ROOT / "reports"


def read_table(name: str) -> pd.DataFrame:
    """RAW 表装载；开封（OPEN_SEALED 存在）时拼接 sealed 同名表（rules.md 第 1 节）。

    未开封时与 guard.read_parquet(RAW / name) 逐位等价；开封后 raw 与 sealed
    按 fetch 切分无重叠（raw ≤ 20241231、sealed ≥ 20250101），直接拼接，各
    消费方随后自行排序/去重/合并（st_intervals、industry_intervals、
    align_by_ann_date 内部均重排序），拼接顺序不破坏任何下游契约。
    """
    df = guard.read_parquet(RAW / name)
    sealed_path = guard.SEALED_DIR / name
    if guard.OPEN_SEALED_MARKER.is_file() and sealed_path.exists():
        df = pd.concat([df, guard.read_parquet(sealed_path)], ignore_index=True)
    return df

ETF_BENCHMARK = "510300.SH"      # 沪深300 ETF（基准与底仓）
ETF_GOLD = "518880.SH"           # 黄金 ETF（底仓避险腿）
ETF_CODES = ("510300.SH", "510500.SH", "518880.SH", "511010.SH")

# 业绩预告类型 → 数值编码（供打分/排名用；rules.md 7.5：预告按公告日对齐。
# 编码只表达「方向与强度」的序数语义，非 rules.md 第 7 节参数）
FORECAST_TYPE_CODE = {
    "预增": 2.0, "略增": 1.0, "扭亏": 1.5, "续盈": 0.5,
    "预减": -2.0, "略减": -1.0, "首亏": -1.5, "续亏": -0.5,
    "不确定": 0.0,
}


def _norm_date_col(s: pd.Series) -> pd.Series:
    return s.astype("string").str.replace("-", "", regex=False).str.slice(0, 8)


def _days_between(later: pd.Series, earlier: pd.Series) -> np.ndarray:
    """两个 YYYYMMDD 字符串序列的日历日差（later − earlier），NaT → NaN。"""
    a = pd.to_datetime(later, format="%Y%m%d", errors="coerce")
    b = pd.to_datetime(earlier, format="%Y%m%d", errors="coerce")
    return (a - b).dt.days.to_numpy(dtype="float64")


# ================================================================ 纯函数（审计可复算）

def st_intervals(namechg: pd.DataFrame) -> dict[str, tuple[np.ndarray, ...]]:
    """namechange → {code: (starts, ends, is_st_flags)}，按 start 升序。

    starts/ends 为 YYYYMMDD 字符串数组（end 空缺 → "99999999"）；flags 为 0/1
    （名称含 "ST"）。同日多条按 end 升序稳定排序。
    """
    out: dict[str, tuple[np.ndarray, ...]] = {}
    if len(namechg) == 0:
        return out
    df = namechg.copy()
    df["start_date"] = _norm_date_col(df["start_date"]).fillna("")
    df["end_date"] = _norm_date_col(df["end_date"]).fillna("").replace("", "99999999")
    df["is_st"] = df["name"].astype("string").str.upper().str.contains("ST", na=False)
    df = df.sort_values(["ts_code", "start_date", "end_date"], kind="stable")
    for code, g in df.groupby("ts_code", sort=False):
        out[str(code)] = (g["start_date"].to_numpy(dtype=object),
                          g["end_date"].to_numpy(dtype=object),
                          g["is_st"].to_numpy(dtype="float64"))
    return out


def industry_intervals(ind: pd.DataFrame) -> dict[str, tuple[np.ndarray, ...]]:
    """index_member_all → {code: (ins, outs, l1_codes, l1_names)}，按 in_date 升序。

    只保留一级行业（l1_code 非空）；out 空缺 → "99999999"。
    """
    out: dict[str, tuple[np.ndarray, ...]] = {}
    if len(ind) == 0:
        return out
    df = ind.copy()
    df = df[df["l1_code"].notna() & (df["l1_code"].astype(str).str.len() > 0)]
    df["in_date"] = _norm_date_col(df["in_date"]).fillna("")
    df["out_date"] = _norm_date_col(df["out_date"]).fillna("").replace("", "99999999")
    df = df.drop_duplicates(["ts_code", "l1_code", "in_date", "out_date"], keep="last")
    df = df.sort_values(["ts_code", "in_date", "out_date"], kind="stable")
    for code, g in df.groupby("ts_code", sort=False):
        out[str(code)] = (g["in_date"].to_numpy(dtype=object),
                          g["out_date"].to_numpy(dtype=object),
                          g["l1_code"].astype(str).to_numpy(dtype=object),
                          g["l1_name"].astype(str).to_numpy(dtype=object))
    return out


def align_by_ann_date(recs: pd.DataFrame, codes: np.ndarray, dates: np.ndarray,
                      value_cols: list[str]) -> dict[str, np.ndarray]:
    """按 ann_date 对齐（rules.md 7.5：T 日只能看到 ann_date ≤ T 的最新一期）。

    recs : 财务/预告/快报记录（含 ts_code, ann_date, end_date 及 value_cols）。
    codes/dates : 面板行的 (code, date) 数组（YYYYMMDD）。
    返回 {col: 与面板等长的 float64/str 数组}；同 ann_date 多条取 end_date 更晚者
    （预排序 (ts_code, ann_date, end_date) 后 searchsorted('right') 自然取最后一条）。
    ann_date 整体缺失的记录永不出现。
    """
    out: dict[str, np.ndarray] = {c: np.full(len(codes), np.nan, dtype="float64")
                                  for c in value_cols}
    if len(recs) == 0:
        return out
    df = recs.copy()
    df["ann_date"] = _norm_date_col(df["ann_date"])
    df["end_date"] = _norm_date_col(df["end_date"])
    df = df.dropna(subset=["ann_date", "end_date"])
    if len(df) == 0:
        return out
    df = df.sort_values(["ts_code", "ann_date", "end_date"], kind="stable")
    order = np.argsort(codes, kind="stable")
    codes_s, dates_s = codes[order], dates[order]
    bounds = np.flatnonzero(np.r_[True, codes_s[1:] != codes_s[:-1]])
    bounds = np.r_[bounds, len(codes_s)]
    rec_by_code = {str(k): g for k, g in df.groupby("ts_code", sort=False)}
    for b0, b1 in zip(bounds[:-1], bounds[1:]):
        code = str(codes_s[b0])
        g = rec_by_code.get(code)
        if g is None:
            continue
        anns = np.array([int(str(x)) for x in g["ann_date"].to_numpy()], dtype="int64")
        q = np.array([int(str(x)) for x in dates_s[b0:b1]], dtype="int64")
        pos = np.searchsorted(anns, q, side="right") - 1
        hit = pos >= 0
        if not hit.any():
            continue
        rows = g.iloc[np.clip(pos, 0, len(g) - 1)]
        panel_rows = order[b0:b1]           # 该代码块在面板中的原始行号
        for c in value_cols:
            col = rows[c]
            if c in ("ann_date", "end_date", "type"):     # 字符串列
                vals = col.astype("string").to_numpy(dtype=object)
                if out[c].dtype != object:
                    out[c] = np.full(len(codes), None, dtype=object)
                out[c][panel_rows[hit]] = vals[hit]
            else:
                vals = pd.to_numeric(col, errors="coerce").to_numpy(dtype="float64")
                out[c][panel_rows[hit]] = vals[hit]
    return out


def align_latest_by_trade_date(recs: pd.DataFrame, codes: np.ndarray, dates: np.ndarray,
                               value_cols: list[str],
                               strict_before: bool) -> dict[str, np.ndarray]:
    """按 trade_date 对齐资金面表（rules.md 7.5：按披露日对齐，不得用当日数据
    做当日决策——适用于次日披露的表）。

    recs : 含 ts_code / trade_date / value_cols 的记录表（龙虎榜事件、两融、北向）。
    codes/dates : 面板行的 (code, date) 数组（YYYYMMDD）。
    strict_before=True  → T 日行取该股 trade_date **< T** 的最新一条（两融/北向：
                         T 日数据次日披露，T 日决策只能用 ≤ T-1 的记录）；
    strict_before=False → T 日行取该股 trade_date **≤ T** 的最新一条（龙虎榜：
                         T 日盘后披露、T 日收盘信号可用当日记录）。
    同 (ts_code, trade_date) 多条取最后一条；无记录 → NaN（绝不 0 填充）。
    与 align_by_ann_date 同一实现骨架（searchsorted，纯函数，审计可复算）。
    """
    out = {c: np.full(len(codes), np.nan, dtype="float64") for c in value_cols}
    if len(recs) == 0:
        return out
    df = recs.copy()
    df["trade_date"] = _norm_date_col(df["trade_date"])
    df = df.dropna(subset=["trade_date"])
    if len(df) == 0:
        return out
    df = df.drop_duplicates(["ts_code", "trade_date"], keep="last")
    df = df.sort_values(["ts_code", "trade_date"], kind="stable")
    order = np.argsort(codes, kind="stable")
    codes_s, dates_s = codes[order], dates[order]
    bounds = np.flatnonzero(np.r_[True, codes_s[1:] != codes_s[:-1]])
    bounds = np.r_[bounds, len(codes_s)]
    rec_by_code = {str(k): g for k, g in df.groupby("ts_code", sort=False)}
    side = "left" if strict_before else "right"
    for b0, b1 in zip(bounds[:-1], bounds[1:]):
        g = rec_by_code.get(str(codes_s[b0]))
        if g is None:
            continue
        tds = np.array([int(str(x)) for x in g["trade_date"].to_numpy()], dtype="int64")
        q = np.array([int(str(x)) for x in dates_s[b0:b1]], dtype="int64")
        pos = np.searchsorted(tds, q, side=side) - 1
        hit = pos >= 0
        if not hit.any():
            continue
        rows = g.iloc[np.clip(pos, 0, len(g) - 1)]
        panel_rows = order[b0:b1]
        for c in value_cols:
            vals = pd.to_numeric(rows[c], errors="coerce").to_numpy(dtype="float64")
            out[c][panel_rows[hit]] = vals[hit]
    return out


# ================================================================ 区间判定（逐行）

def _split_blocks(codes: np.ndarray):
    """按 code 连续块切分（面板按 code 升序）；返回 (order, bounds)。"""
    order = np.argsort(codes, kind="stable")
    codes_s = codes[order]
    bounds = np.flatnonzero(np.r_[True, codes_s[1:] != codes_s[:-1]])
    return order, np.r_[bounds, len(codes_s)]


def _interval_flag(codes: np.ndarray, dates: np.ndarray,
                   iv: dict[str, tuple[np.ndarray, ...]]) -> np.ndarray:
    """逐行判断 (code, date) 是否落在某区间内（starts ≤ date < ends）→ 1/0。"""
    out = np.zeros(len(codes), dtype="float64")
    order, bounds = _split_blocks(codes)
    codes_s, dates_s = codes[order], dates[order]
    for b0, b1 in zip(bounds[:-1], bounds[1:]):
        entry = iv.get(str(codes_s[b0]))
        if entry is None:
            continue
        starts, ends, flags = entry
        q = np.array([int(str(x)) for x in dates_s[b0:b1]], dtype="int64")
        s = np.array([int(str(x)) for x in starts], dtype="int64")
        e = np.array([int(str(x)) for x in ends], dtype="int64")
        pos = np.searchsorted(s, q, side="right") - 1
        hit = pos >= 0
        if hit.any():
            idx = np.clip(pos, 0, len(s) - 1)
            inside = hit & (q < e[idx])
            panel_rows = order[b0:b1]
            out[panel_rows[inside]] = np.asarray(flags, dtype="float64")[idx[inside]]
    return out


def _interval_value(codes: np.ndarray, dates: np.ndarray,
                    iv: dict[str, tuple[np.ndarray, ...]],
                    val_idx: int, alt_idx: int) -> tuple[np.ndarray, np.ndarray]:
    """逐行取区间值；不命中 → None（object 数组）。"""
    out = np.full(len(codes), None, dtype=object)
    alt = np.full(len(codes), None, dtype=object)
    order, bounds = _split_blocks(codes)
    codes_s, dates_s = codes[order], dates[order]
    for b0, b1 in zip(bounds[:-1], bounds[1:]):
        entry = iv.get(str(codes_s[b0]))
        if entry is None:
            continue
        starts, ends = entry[0], entry[1]
        vals, alts = entry[val_idx], entry[alt_idx]
        q = np.array([int(str(x)) for x in dates_s[b0:b1]], dtype="int64")
        s = np.array([int(str(x)) for x in starts], dtype="int64")
        e = np.array([int(str(x)) for x in ends], dtype="int64")
        pos = np.searchsorted(s, q, side="right") - 1
        hit = pos >= 0
        if hit.any():
            idx = np.clip(pos, 0, len(s) - 1)
            inside = hit & (q < e[idx])
            panel_rows = order[b0:b1]
            out[panel_rows[inside]] = np.asarray(vals, dtype=object)[idx[inside]]
            alt[panel_rows[inside]] = np.asarray(alts, dtype=object)[idx[inside]]
    return out, alt


# ================================================================ DataStore

class DataStore:
    """一次性加载 data/raw/ 全部数据；提供当日股票池与内存面板。

    构造后所有读取都在内存里完成；raw 数据不含封存期（上界 20241231，
    guard 仍逐文件把关）。审计需要的原始帧全部作为属性暴露：
    members / basic / namechg / ind / fin / fcs / exps / etfs / panel / suspend_set。
    """

    def __init__(self, quiet: bool = False):
        self.quiet = quiet

        # ---- 交易日历（SSE 开市日，YYYYMMDD 升序）----
        cal = read_table("trade_cal.parquet")
        cal["cal_date"] = _norm_date_col(cal["cal_date"])
        cal["is_open"] = pd.to_numeric(cal["is_open"], errors="coerce")
        self.trade_days = np.array(sorted(cal.loc[cal["is_open"] == 1, "cal_date"]),
                                   dtype=object)

        # ---- 股票基础信息（list_date 用于上市天数）----
        basic = read_table("stock_basic.parquet")
        basic = basic.drop_duplicates("ts_code", keep="last")
        basic["list_date"] = _norm_date_col(basic["list_date"])
        self.basic = basic.sort_values("ts_code").reset_index(drop=True)
        self.list_date = {str(k): (None if pd.isna(v) else str(v))
                          for k, v in zip(basic["ts_code"], basic["list_date"])}

        # ---- 股票池（沪深300 ∪ 中证500，按当日快照）----
        mem = read_table("index_members.parquet")
        mem["trade_date"] = _norm_date_col(mem["trade_date"])
        self.members = mem.sort_values(
            ["trade_date", "index_code", "con_code"]).reset_index(drop=True)
        self._univ_by_idx: dict[str, dict[str, frozenset]] = {}
        for idx, g in self.members.groupby("index_code", sort=False):
            self._univ_by_idx[str(idx)] = {
                str(d): frozenset(g.loc[g["trade_date"] == d, "con_code"].astype(str))
                for d in g["trade_date"].unique()
            }
        self._universe_cache: dict[str, list[str]] = {}

        # ---- 个股面板：daily × adj_factor × daily_basic × stk_limit ----
        daily = read_table("daily.parquet")
        daily["trade_date"] = _norm_date_col(daily["trade_date"])
        daily = daily.rename(columns={"trade_date": "date", "ts_code": "code"})
        for c in ("open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"):
            daily[c] = pd.to_numeric(daily[c], errors="coerce")
        daily = daily.dropna(subset=["close"]).sort_values(
            ["code", "date"], kind="stable").reset_index(drop=True)

        af = read_table("adj_factor.parquet")
        af["trade_date"] = _norm_date_col(af["trade_date"])
        af = af.rename(columns={"trade_date": "date", "ts_code": "code"})
        af["adj_factor"] = pd.to_numeric(af["adj_factor"], errors="coerce")
        af = af.dropna(subset=["adj_factor"]).drop_duplicates(["code", "date"], keep="last")
        daily = daily.merge(af[["code", "date", "adj_factor"]], on=["code", "date"], how="left")
        n_missing_af = int(daily["adj_factor"].isna().sum())
        if n_missing_af:
            raise RuntimeError(f"{n_missing_af} 行日线缺 adj_factor，数据不完整")

        db = read_table("daily_basic.parquet")
        db["trade_date"] = _norm_date_col(db["trade_date"])
        db = db.rename(columns={"trade_date": "date", "ts_code": "code"})
        for c in ("turnover_rate", "pe_ttm", "pb", "ps_ttm", "total_mv", "circ_mv"):
            db[c] = pd.to_numeric(db[c], errors="coerce") if c in db.columns else np.nan
        db = db.drop_duplicates(["code", "date"], keep="last")
        daily = daily.merge(db[["code", "date", "turnover_rate", "pe_ttm", "pb",
                                "ps_ttm", "total_mv", "circ_mv"]],
                            on=["code", "date"], how="left")

        lim = read_table("stk_limit.parquet")
        lim["trade_date"] = _norm_date_col(lim["trade_date"])
        lim = lim.rename(columns={"trade_date": "date", "ts_code": "code"})
        for c in ("up_limit", "down_limit"):
            lim[c] = pd.to_numeric(lim[c], errors="coerce")
        lim = lim.drop_duplicates(["code", "date"], keep="last")
        daily = daily.merge(lim[["code", "date", "up_limit", "down_limit"]],
                            on=["code", "date"], how="left")

        # 复权净值：跨日收益唯一口径（rules.md 第 2 节）
        daily["af"] = daily["adj_factor"]
        daily["adj_nav"] = daily["close"] * daily["af"]

        codes = daily["code"].to_numpy(dtype=object)
        dates = daily["date"].to_numpy(dtype=object)

        # ---- ST（namechange 按当日名称）----
        self.namechg = read_table("namechange.parquet")
        daily["is_st"] = _interval_flag(codes, dates, st_intervals(self.namechg))

        # ---- 申万一级行业（in_date ≤ T < out_date）----
        self.ind = read_table("index_member_all.parquet")
        l1c, l1n = _interval_value(codes, dates, industry_intervals(self.ind), 2, 3)
        daily["l1_code"] = l1c
        daily["l1_name"] = l1n

        # ---- 财务 / 预告 / 快报（严格 ann_date 对齐）----
        self.fin = read_table("fina_indicator.parquet")
        aligned = align_by_ann_date(self.fin, codes, dates,
                                    ["end_date", "roe", "or_yoy", "netprofit_yoy"])
        daily["fin_end_date"] = aligned["end_date"]
        for c in ("roe", "or_yoy", "netprofit_yoy"):
            daily[c] = aligned[c]

        self.fcs = read_table("forecast.parquet")
        fcs = self.fcs.copy()
        fcs["fc_type_code"] = fcs["type"].astype("string").map(FORECAST_TYPE_CODE)
        fcal = align_by_ann_date(fcs, codes, dates,
                                 ["ann_date", "type", "fc_type_code",
                                  "p_change_min", "p_change_max"])
        daily["fc_ann_date"] = fcal["ann_date"]
        daily["fc_type"] = fcal["type"]
        daily["fc_type_code"] = fcal["fc_type_code"]
        pmin = pd.Series(fcal["p_change_min"], dtype="float64")
        pmax = pd.Series(fcal["p_change_max"], dtype="float64")
        mid = pd.Series(np.where(pmin.notna() & pmax.notna(), (pmin + pmax) / 2.0, pmin))
        # 变动幅度：优先 (p_change_min+p_change_max)/2，只有单边时取单边
        daily["fc_chg_mid"] = mid.to_numpy(dtype="float64")
        has_fc = pd.notna(daily["fc_ann_date"])
        daily["fc_days"] = np.nan
        daily.loc[has_fc, "fc_days"] = _days_between(
            pd.Series(dates)[has_fc].reset_index(drop=True),
            daily.loc[has_fc, "fc_ann_date"].reset_index(drop=True))

        self.exps = read_table("express.parquet")
        exal = align_by_ann_date(self.exps, codes, dates,
                                 ["ann_date", "yoy_net_profit"])
        daily["ex_ann_date"] = exal["ann_date"]
        daily["ex_yoy"] = exal["yoy_net_profit"]
        daily["ex_days"] = np.nan
        has_ex = pd.notna(daily["ex_ann_date"])
        daily.loc[has_ex, "ex_days"] = _days_between(
            pd.Series(dates)[has_ex].reset_index(drop=True),
            daily.loc[has_ex, "ex_ann_date"].reset_index(drop=True))

        # ---- 资金面（rules.md 7.5 第 3.4 版：龙虎榜 / 两融 / 北向，point-in-time）----
        # 对齐口径（第 1 步体检结论）：
        #   * top_list / top_inst 无 ann_date，T 日盘后披露 → T 日收盘信号可用
        #     trade_date ≤ T 的记录（align strict_before=False）；
        #   * margin_detail / hk_hold 是 T 日数据次日披露 → T 日决策只能用
        #     trade_date < T（= ≤ T-1）的记录（align strict_before=True）；
        #   * hk_hold 只用 exchange=SH/SZ（北向持股 A 股部分；HK 记录是南向，剔除）。
        # 缺失语义：从未上榜 / 无两融 / 无北向记录 → NaN，绝不 0 填充。
        self.top_list = read_table("top_list.parquet")[
            ["ts_code", "trade_date", "l_amount"]].copy()
        self.top_list["trade_date"] = _norm_date_col(self.top_list["trade_date"])
        self.top_list["ts_code"] = self.top_list["ts_code"].astype(str)
        self.top_list["l_amount"] = pd.to_numeric(self.top_list["l_amount"],
                                                  errors="coerce")
        # 龙虎榜事件表：一股一日一行。分母 l_amount 取该股当日全部上榜理由行的
        # 最大值（不同 reason 的龙虎榜成交额口径不同，取最大桶）；分子 = 该股
        # 当日「机构专用」席位 net_buy 合计（元；top_inst.net_buy = 净成交额 =
        # 买入−卖出，已用 top_list l_buy/l_sell 合计逐位核验）。该次上榜无机构
        # 专用席位 → 净买入为真实 0（事件存在，不是缺失）。
        ev = self.top_list.groupby(["ts_code", "trade_date"], sort=False)[
            ["l_amount"]].max().reset_index()
        self.top_inst = read_table("top_inst.parquet")[
            ["ts_code", "trade_date", "exalter", "net_buy"]].copy()
        self.top_inst["trade_date"] = _norm_date_col(self.top_inst["trade_date"])
        self.top_inst["ts_code"] = self.top_inst["ts_code"].astype(str)
        self.top_inst["net_buy"] = pd.to_numeric(self.top_inst["net_buy"],
                                                 errors="coerce").fillna(0.0)
        inst = self.top_inst[self.top_inst["exalter"].astype("string") == "机构专用"]
        nb = inst.groupby(["ts_code", "trade_date"], sort=False)[
            ["net_buy"]].sum().reset_index().rename(columns={"net_buy": "inst_net"})
        ev = ev.merge(nb, on=["ts_code", "trade_date"], how="left")
        ev["inst_net"] = ev["inst_net"].fillna(0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            ev["tl_inst_netbuy_pct"] = np.where(
                ev["l_amount"] > 0, ev["inst_net"] / ev["l_amount"] * 100.0, np.nan)
        ev["tl_flag"] = 1.0
        ev["tl_ev_date"] = ev["trade_date"].astype(str).astype("float64")
        tal = align_latest_by_trade_date(ev, codes, dates,
                                         ["tl_flag", "tl_ev_date", "tl_inst_netbuy_pct"],
                                         strict_before=False)
        # 当日上榜 = 最新一次上榜事件（≤ T）恰好发生在 T（T 日盘后披露，收盘信号可用）
        daily["tl_on_list"] = np.where(tal["tl_ev_date"] == dates.astype("float64"),
                                       1.0, 0.0)
        daily["tl_inst_netbuy_pct"] = tal["tl_inst_netbuy_pct"]

        self.margin = read_table("margin_detail.parquet")[
            ["ts_code", "trade_date", "rzye"]].copy()
        self.margin["trade_date"] = _norm_date_col(self.margin["trade_date"])
        mal = align_latest_by_trade_date(self.margin, codes, dates, ["rzye"],
                                         strict_before=True)
        daily["margin_rzye"] = mal["rzye"]          # 融资余额（元，T-1 对齐）

        self.hk = read_table("hk_hold.parquet")[
            ["ts_code", "trade_date", "ratio", "exchange"]].copy()
        self.hk["trade_date"] = _norm_date_col(self.hk["trade_date"])
        self.hk = self.hk[self.hk["exchange"].isin(["SH", "SZ"])]
        hal = align_latest_by_trade_date(self.hk, codes, dates, ["ratio"],
                                         strict_before=True)
        daily["hk_ratio"] = hal["ratio"]      # 北向持股占流通股本 %（T-1 对齐）

        # ---- 上市交易日数（list_date 起按交易日历；list_date 缺失 → NaN 保守剔除）----
        n = len(daily)
        base = np.full(n, -1, dtype="int64")
        if len(self.list_date):
            ld = pd.Series([self.list_date.get(str(c)) for c in codes], dtype="object")
            known = ld.notna() & (ld.str.len() == 8)
            base[known.to_numpy()] = np.searchsorted(
                self.trade_days, ld[known].astype(str), side="right")
        cur = np.searchsorted(self.trade_days, dates.astype(str), side="right")
        daily["n_listed"] = np.where(base >= 0, cur - base, np.nan)

        self.panel = daily
        self.codes: list[str] = sorted(daily["code"].astype(str).unique().tolist())
        self.calendar: list[str] = [str(d) for d in self.trade_days]

        # ---- 全天停牌集合（suspend_d；供审计与兜底核对）----
        susp = read_table("suspend_d.parquet")
        susp["trade_date"] = _norm_date_col(susp["trade_date"])
        timing = susp.get("suspend_timing")
        full = (timing.isna() | (timing.astype("string").isin(["", "None"]))) \
            if timing is not None else pd.Series(True, index=susp.index)
        self.suspend_set = set(zip(susp.loc[full, "ts_code"].astype(str),
                                   susp.loc[full, "trade_date"].astype(str)))

        # ---- ETF（fund_daily × fund_adj）----
        fd = read_table("fund_daily.parquet")
        fd["trade_date"] = _norm_date_col(fd["trade_date"])
        fd = fd.rename(columns={"trade_date": "date", "ts_code": "code"})
        for c in ("open", "high", "low", "close", "pre_close"):
            fd[c] = pd.to_numeric(fd[c], errors="coerce")
        fa = read_table("fund_adj.parquet")
        fa["trade_date"] = _norm_date_col(fa["trade_date"])
        fa = fa.rename(columns={"trade_date": "date", "ts_code": "code"})
        fa["adj_factor"] = pd.to_numeric(fa["adj_factor"], errors="coerce")
        fd = fd.merge(fa[["code", "date", "adj_factor"]], on=["code", "date"], how="left")
        fd["close_adj"] = fd["close"] * fd["adj_factor"]
        self.etfs: dict[str, pd.DataFrame] = {}
        for code, g in fd.groupby("code", sort=False):
            g = g.sort_values("date").reset_index(drop=True)
            g["ret"] = g["close_adj"].pct_change(fill_method=None)
            self.etfs[str(code)] = g

        if not self.quiet:
            print(f"[prices] 面板加载完成：{len(self.codes)} 只股票 × "
                  f"{len(daily):,} 行，交易日 {len(self.calendar)} 天；ETF {len(self.etfs)} 只")

    # ------------------------------------------------------------ 股票池

    def universe_on(self, t: str) -> list[str]:
        """T 日股票池 = 两指数「最近一次样本 ≤ T」成分的并集（升序）。"""
        t = str(t)
        if t in self._universe_cache:
            return self._universe_cache[t]
        pool: set[str] = set()
        for snaps in self._univ_by_idx.values():
            prev = [d for d in snaps if d <= t]
            if prev:
                pool |= snaps[max(prev)]
        out = sorted(pool)
        self._universe_cache[t] = out
        return out

    # ------------------------------------------------------------ 审计入口

    def is_suspended(self, code: str, date: str) -> bool:
        """该股当日是否全天停牌（suspend_d 显式记录）。"""
        return (str(code), str(date)) in self.suspend_set

    def is_st_on(self, code: str, date: str) -> bool:
        """该股在 date 当日名称是否含 ST（namechange 历史名称口径）。"""
        sub = self.namechg[self.namechg["ts_code"] == code]
        return bool(_interval_flag(np.array([code], dtype=object),
                                   np.array([str(date)], dtype=object),
                                   st_intervals(sub))[0] == 1.0)

    def industry_on(self, code: str, date: str) -> str | None:
        """该股在 date 当日的申万一级行业代码（l1_code；无归属 → None）。"""
        sub = self.ind[self.ind["ts_code"] == code]
        _, names = _interval_value(np.array([code], dtype=object),
                                   np.array([str(date)], dtype=object),
                                   industry_intervals(sub), 3, 2)
        v = names[0]
        return None if v is None else str(v)

    def asof(self, t: str) -> "PanelView":
        return PanelView(self, t)


class PanelView:
    """DataStore 的 as-of-T 只读切片（防未来函数审计用）。"""

    def __init__(self, store: DataStore, t: str):
        self.store = store
        self.t = str(t)
        panel = store.panel
        self._panel = panel[panel["date"] <= self.t]
        self.dates = sorted(self._panel["date"].unique().tolist())

    @property
    def panel(self) -> pd.DataFrame:
        return self._panel

    @property
    def calendar(self) -> list[str]:
        return self.dates

    def universe_on(self, t: str) -> list[str]:
        if str(t) > self.t:
            raise ValueError(f"PanelView 是 as-of-{self.t} 视图，不能查询 {t}")
        return self.store.universe_on(t)


# ================================================================ 价格自检

def run_price_check(store: DataStore | None = None, threshold_pct: float = 0.5,
                    out_path: Path | None = None) -> Path:
    """价格自检：adj_nav（=close×adj_factor）日涨幅 vs pct_chg。"""
    store = store or DataStore()
    out_path = out_path or (REPORTS_DIR / "price_check.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    p = store.panel
    ret_adj = p.groupby("code", sort=False)["adj_nav"].pct_change(fill_method=None) * 100.0
    diff = (ret_adj - p["pct_chg"]).abs()
    bad = p[diff > threshold_pct].copy()
    bad["ret_adj"] = ret_adj[diff > threshold_pct]
    bad["diff_pp"] = diff[diff > threshold_pct]
    bad = bad.sort_values(["code", "date"])
    lines = [
        "# 价格自检：close×adj_factor 日涨幅 vs pct_chg",
        "",
        f"- 生成方式：`engine/prices.py --check`（阈值：偏差 > {threshold_pct}%）",
        f"- 覆盖：{len(store.codes)} 只股票、{len(p):,} 行",
        f"- 结论：**{bad['code'].nunique()}** 只股票存在偏差，合计 {len(bad)} 个交易日超阈值。",
        "",
        "| 股票 | 日期 | 复权日涨幅% | pct_chg% | 偏差pp |",
        "|---|---|---|---|---|",
    ]
    for r in bad.itertuples():
        lines.append(f"| {r.code} | {r.date} | {r.ret_adj:.3f} | {r.pct_chg:.3f} | {r.diff_pp:.3f} |")
    if not len(bad):
        lines.append("| （无） | | | | |")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


# ================================================================ CLI

def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] != "--check":
        print(__doc__)
        print("用法：python engine/prices.py --check   # 触发价格自检，写 reports/price_check.md")
        return 0
    store = DataStore()
    out = run_price_check(store)
    print(f"[prices] 自检完成，报告写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

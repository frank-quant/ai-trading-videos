#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据体检：只统计 data/raw/（2013-01-01 ~ 2024-12-31），不读 data/sealed/。

产出 reports/data_check.md：
1. 股票池总数、每月成分数是否都是 300/500/1000
2. 每只股票相对交易日历的缺口天数（停牌除外）
3. 复权连续性自检：close × adj_factor 的日涨幅 vs pct_chg，偏差 > 0.5% 的列出
4. 财务 / 预告 / 快报 / 龙虎榜公告日相对报告期的滞后分布
5. 两融、北向、行业数据的起止日期与覆盖率
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "reports" / "data_check.md"

START = "20130101"
END = "20241231"
TARGET = {"000300.SH": 300, "000905.SH": 500, "000852.SH": 1000}


def rd(name: str) -> pd.DataFrame:
    return pd.read_parquet(RAW / f"{name}.parquet")


def lag_table(df: pd.DataFrame, label: str) -> str:
    a = pd.to_datetime(df["ann_date"], format="%Y%m%d", errors="coerce")
    e = pd.to_datetime(df["end_date"], format="%Y%m%d", errors="coerce")
    ok = a.notna() & e.notna()
    lag = (a - e).dt.days[ok]
    neg = int((lag < 0).sum())
    qs = lag.quantile([0.01, 0.25, 0.5, 0.75, 0.99])
    return (
        f"| {label} | {int(ok.sum())} | {neg} | {int(qs.loc[0.01])} | {int(qs.loc[0.25])} | "
        f"{int(qs.loc[0.5])} | {int(qs.loc[0.75])} | {int(qs.loc[0.99])} | {int(lag.max())} |\n"
    )


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    manifest = json.loads((ROOT / "data" / "MANIFEST.json").read_text(encoding="utf-8"))

    L: list[str] = []
    L.append("# 数据体检（只统计 data/raw/，即 2013-01-01 ~ 2024-12-31）\n\n")
    L.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    L.append(f"- 切分日：{manifest.get('split_date')}；本报告不读取、不统计 data/sealed/ 下任何文件。\n")
    L.append("- 封存侧文件只在抓取时内存中计算 SHA256 落盘，本报告对封存数据零接触。\n\n")

    # ---------------------------------------------------------------- 1. 股票池与每月成分数
    mem = rd("index_members")
    pool = sorted(mem["con_code"].astype(str).unique())
    L.append("## 1. 股票池与每月成分数\n\n")
    L.append(f"- 股票池（raw 段内出现过的成分股合集，含已调出/退市）：**{len(pool)} 只**\n")
    L.append("- 池内 2025 年后才进入指数的股票不参与本报告（属封存期信息，本报告不统计）。\n\n")
    cnt = mem.groupby(["index_code", "trade_date"])["con_code"].nunique().reset_index(name="n")
    L.append("| 指数 | 月数 | 成分数最小 | 中位 | 最大 | 目标 | 不达标月数 | 不达标区间 |\n")
    L.append("|---|---|---|---|---|---|---|---|\n")
    for idx, tgt in TARGET.items():
        c = cnt[cnt["index_code"] == idx].sort_values("trade_date")
        months = sorted(c["trade_date"].unique())
        bad = c[c["n"] != tgt]
        if len(months):
            gap_desc = f"{months[0]}~{months[-1]}"
            if len(bad):
                bd = bad["trade_date"].tolist()
                gap_desc += f"；不达标示例：{bd[0]}({int(bad.iloc[0]['n'])}) ~ {bd[-1]}({int(bad.iloc[-1]['n'])})，共 {len(bad)} 个月"
        else:
            gap_desc = "（无数据）"
        L.append(f"| {idx} | {len(months)} | {int(c['n'].min()) if len(c) else '-'} | "
                 f"{int(c['n'].median()) if len(c) else '-'} | {int(c['n'].max()) if len(c) else '-'} | "
                 f"{tgt} | {len(bad)} | {gap_desc} |\n")
    all_months = sorted(cnt["trade_date"].unique())
    L.append(f"\n- 成分月覆盖：{all_months[0]} ~ {all_months[-1]}，共 {len(all_months)} 个月末。\n")
    L.append("- 注：000852（中证1000）发布于 2014-10，之前月份接口无数据（计数 0 不计入上表月数）。\n")
    have = {str(d)[:6] for d in all_months}
    expected_months = []
    y, m = 2013, 12
    while (y, m) <= (2024, 12):
        expected_months.append(f"{y}{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    miss = [x for x in expected_months if x not in have]
    L.append(f"- 相对 2013-12 ~ 2024-12 应有 {len(expected_months)} 个月末，缺失 {len(miss)} 个月"
             + (f"：{miss[:20]}" if miss else "") + "\n\n")

    # ---------------------------------------------------------------- 2. 缺口天数
    cal = rd("trade_cal")
    open_days = np.array(sorted(cal[cal["is_open"].astype(str) == "1"]["cal_date"].astype(str)))
    basic = rd("stock_basic")
    bmap = basic.set_index("ts_code")
    daily = rd("daily")
    daily_codes = set(daily["ts_code"].unique())
    sus = rd("suspend_d")
    sus_groups = {k: np.array(sorted(v.astype(str))) for k, v in sus.groupby("ts_code")["trade_date"]}
    day_groups = {k: np.array(sorted(v.astype(str))) for k, v in daily.groupby("ts_code")["trade_date"]}

    rows = []
    for code in pool:
        if code not in bmap.index:
            rows.append((code, None, None, None, None, None, None, "不在 stock_basic"))
            continue
        ld = str(bmap.at[code, "list_date"]) if pd.notna(bmap.at[code, "list_date"]) else None
        dd = str(bmap.at[code, "delist_date"]) if "delist_date" in bmap.columns and pd.notna(bmap.at[code, "delist_date"]) else None
        if ld is None or ld > END:
            continue
        w0 = max(ld, START)
        w1 = min(dd if dd else END, END)
        ow = open_days[(open_days >= w0) & (open_days <= w1)]
        if len(ow) == 0:
            continue
        arr = day_groups.get(code, np.array([], dtype=object))
        arr = arr[(arr >= w0) & (arr <= w1)]
        miss = np.setdiff1d(ow, arr)                      # 日历有、daily 没有的日子
        sarr = sus_groups.get(code, np.array([], dtype=object))
        sarr = np.unique(sarr[(sarr >= w0) & (sarr <= w1)])  # 停牌按唯一日计数
        explained = np.intersect1d(miss, sarr)            # 缺失日中被停牌解释的部分
        rows.append((code, w0, w1, len(ow), len(miss), len(explained), len(miss) - len(explained), ""))
    g = pd.DataFrame(rows, columns=["ts_code", "w0", "w1", "expected", "miss", "susp_expl", "gap", "note"])
    L.append("## 2. 个股相对交易日历的缺口（停牌除外）\n\n")
    L.append("- 口径：缺失日 = 交易日历有、daily 无行情行的日子；其中出现在 suspend_d 停牌日里的视为停牌解释；"
             "剩余即真缺口。窗口 = max(list_date, 2013-01-01) ~ min(delist_date, 2024-12-31)。\n")
    L.append(f"- 统计 {len(g)} 只股票（raw 段股票池）。\n")
    n0 = int((g["gap"] == 0).sum())
    npos = int((g["gap"] > 0).sum())
    tot_miss = int(g["miss"].sum())
    tot_expl = int(g["susp_expl"].sum())
    L.append(f"- 累计缺失 {tot_miss} 个交易日，其中停牌解释 {tot_expl} 个；真缺口合计 {int(g['gap'].sum())} 个。\n")
    L.append(f"- 真缺口为 0：**{n0}** 只；有真缺口：{npos} 只。\n")
    if npos:
        buckets = pd.cut(g.loc[g["gap"] > 0, "gap"], [0, 1, 5, 20, np.inf],
                         labels=["1", "2~5", "6~20", ">20"], right=True)
        L.append("-  真缺口分布：" + "，".join(f"{k} 天：{v} 只" for k, v in buckets.value_counts().sort_index().items()) + "\n")
    L.append("\n真缺口最大的 20 只（多为换股吸收合并退市但 stock_basic 缺 delist_date、或长期停牌后终止上市）\n\n")
    L.append("| 代码 | 窗口 | 期望交易日 | 缺失日 | 停牌解释 | 真缺口 | list_status | delist_date |\n|---|---|---|---|---|---|---|---|\n")
    for _, r in g.sort_values("gap", ascending=False).head(20).iterrows():
        code = r["ts_code"]
        st = str(bmap.at[code, "list_status"]) if code in bmap.index and pd.notna(bmap.at[code, "list_status"]) else "—"
        dd = str(bmap.at[code, "delist_date"]) if code in bmap.index and "delist_date" in bmap.columns and pd.notna(bmap.at[code, "delist_date"]) else "—"
        L.append(f"| {code} | {r['w0']}~{r['w1']} | {r['expected']} | {r['miss']} | {r['susp_expl']} | {int(r['gap'])} | {st} | {dd} |\n")
    nb = int((g["note"] == "不在 stock_basic").sum())
    if nb:
        L.append(f"\n- 不在 stock_basic 的股票 {nb} 只：{g.loc[g['note'] != '', 'ts_code'].tolist()[:15]}\n")
    L.append("\n")

    # ---------------------------------------------------------------- 3. 复权连续性
    adj = rd("adj_factor")
    m = daily.merge(adj, on=["ts_code", "trade_date"], how="inner")
    m = m.sort_values(["ts_code", "trade_date"], kind="stable")
    m["hfq"] = m["close"] * m["adj_factor"]
    prev = m.groupby("ts_code", sort=False)["hfq"].shift(1)
    r1 = m["hfq"] / prev - 1.0
    r2 = pd.to_numeric(m["pct_chg"], errors="coerce") / 100.0
    valid = prev.notna() & r2.notna() & m["close"].notna() & m["adj_factor"].notna()
    dev = (r1 - r2).abs()
    bad = m[valid & (dev > 0.005)].copy()
    bad["r1"] = r1[valid & (dev > 0.005)]
    bad["r2"] = r2[valid & (dev > 0.005)]
    L.append("## 3. 复权连续性自检（close × adj_factor 日涨幅 vs pct_chg）\n\n")
    L.append(f"- 参与比较：{int(valid.sum())} 个（股票, 交易日）对（同股票相邻两日且两侧均有复权因子）。\n")
    L.append(f"- 偏差 |hfq 涨幅 − pct_chg| > 0.5% 的：**{len(bad)}** 个"
             f"（占比 {len(bad) / max(int(valid.sum()), 1) * 100:.4f}%）。\n")
    if len(bad):
        L.append("\n| 代码 | 交易日 | hfq涨幅 | pct_chg | 偏差 |\n|---|---|---|---|---|\n")
        for _, r in bad.sort_values(["ts_code", "trade_date"]).head(50).iterrows():
            L.append(f"| {r['ts_code']} | {r['trade_date']} | {r['r1']*100:.2f}% | {r['r2']*100:.2f}% | "
                     f"{abs(r['r1']-r['r2'])*100:.2f}% |\n")
        if len(bad) > 50:
            L.append(f"\n（仅列前 50，共 {len(bad)} 个；涉及 {bad['ts_code'].nunique()} 只股票）\n")
    L.append("\n")

    # ---------------------------------------------------------------- 4. 公告日滞后
    L.append("## 4. 公告日相对报告期的滞后天数分布\n\n")
    L.append("| 表 | 有效行数 | 滞后<0 行数 | P1 | P25 | 中位 | P75 | P99 | 最大 |\n|---|---|---|---|---|---|---|---|---|\n")
    L.append(lag_table(rd("fina_indicator"), "fina_indicator 财务指标"))
    L.append(lag_table(rd("forecast"), "forecast 业绩预告"))
    L.append(lag_table(rd("express"), "express 业绩快报"))
    L.append("\n- 龙虎榜（top_list / top_inst）：接口本身**不提供 ann_date 字段**，数据为 T 日盘后披露，"
             "按 `trade_date` 对齐即视为当日可知（滞后 0 日）。\n")
    L.append("- forecast 滞后为负属正常：业绩预告常在报告期结束前发布（如半年度预告多在 4~6 月、三季度预告在 10 月中），"
             "ann_date 早于 end_date。\n")
    fc = rd("forecast")
    if "update_flag" in fc.columns:
        L.append(f"- forecast 含修正记录：update_flag 分布 {fc['update_flag'].value_counts(dropna=False).to_dict()}；"
                 "同日多次修正时按公告日对齐天然涵盖。\n")
    L.append("\n")

    # ---------------------------------------------------------------- 5. 资金面与行业覆盖
    L.append("## 5. 两融、北向、行业数据的起止与覆盖率\n\n")
    md = rd("margin_detail")
    md_days = np.array(sorted(md["trade_date"].astype(str).unique()))
    per_day = md.groupby("trade_date")["ts_code"].nunique()
    span0, span1 = str(md_days[0]), str(md_days[-1])
    exp_days = int(np.searchsorted(open_days, span1, "right") - np.searchsorted(open_days, span0, "left"))
    L.append("### margin_detail（两融明细，按披露日=次一交易日对齐使用）\n\n")
    L.append(f"- 覆盖 {span0} ~ {span1}，有数据交易日 {len(md_days)} / 区间交易日 {exp_days}"
             f"（{len(md_days)/max(exp_days,1)*100:.1f}%）；行数 {len(md):,}。\n")
    L.append(f"- 每日标的数：中位 {int(per_day.median())}，最小 {int(per_day.min())}（{per_day.idxmin()}），"
             f"最大 {int(per_day.max())}（{per_day.idxmax()}）。\n\n")
    hk = rd("hk_hold")
    hk_days = np.array(sorted(hk["trade_date"].astype(str).unique()))
    hk_per_day = hk.groupby(hk["trade_date"].astype(str))["ts_code"].nunique()
    ex_split = hk["exchange"].value_counts().to_dict() if "exchange" in hk.columns else {}
    span0, span1 = str(hk_days[0]), str(hk_days[-1])
    exp_days = int(np.searchsorted(open_days, span1, "right") - np.searchsorted(open_days, span0, "left"))
    L.append("### hk_hold（北向持股明细）\n\n")
    L.append(f"- 覆盖 {span0} ~ {span1}，有数据交易日 {len(hk_days)} / 区间交易日 {exp_days}"
             f"（{len(hk_days)/max(exp_days,1)*100:.1f}%）；行数 {len(hk):,}。\n")
    L.append(f"- **明细数据源自 2016-08 起**：2014-11 沪股通开通 ~ 2016-07 只有 moneyflow_hsgt 整体资金流，无个股明细。\n")
    L.append(f"- 每日标的数：中位 {int(hk_per_day.median())}；记录按 exchange 分：{ex_split}（HK 为南向标的记录）。\n")
    miss_hk = int((np.searchsorted(open_days, span1, "right") - np.searchsorted(open_days, span0, "left")) - len(hk_days))
    L.append(f"- 区间内缺 {miss_hk} 个交易日的明细（数据源缺口，如 2021-04-02 / 2021-04-06）。\n\n")
    mf = rd("moneyflow_hsgt")
    L.append("### moneyflow_hsgt（陆股通整体资金流）\n\n")
    L.append(f"- 覆盖 {mf['trade_date'].min()} ~ {mf['trade_date'].max()}，行数 {len(mf)}"
             f"（数据源 2014-11-17 沪股通开通起）。\n\n")
    ima = rd("index_member_all")
    in_pool = ima[ima["ts_code"].isin(set(pool))]
    L.append("### index_member_all（申万行业历史成分）\n\n")
    L.append(f"- 纳入日期范围 {in_pool['in_date'].min()} ~ {in_pool['in_date'].max()}；"
             f"股票池 {len(pool)} 只中 {in_pool['ts_code'].nunique()} 只有行业记录"
             f"（覆盖率 {in_pool['ts_code'].nunique()/len(pool)*100:.1f}%）。\n")
    L.append(f"- 一级行业数：{in_pool['l1_code'].nunique()}（{in_pool['l1_name'].nunique()} 个名称）；"
             f"记录数 {len(ima):,}（含纳入/剔除区间）。\n\n")

    # ---------------------------------------------------------------- 附：raw 文件清单
    L.append("## 附：data/raw/ 文件清单（来自 MANIFEST.json）\n\n")
    L.append("| 文件 | 接口 | 行数 | 日期范围 |\n|---|---|---|---|\n")
    for k in sorted(manifest["files"]):
        if not k.startswith("raw/"):
            continue
        v = manifest["files"][k]
        if "error" in v:
            L.append(f"| {k} | {v['api']} | 未落盘：{v['error']} | - |\n")
        else:
            dr = f"{v.get('date_min','—')} ~ {v.get('date_max','—')}" if v.get("date_min") else "—"
            L.append(f"| {k} | {v['api']} | {v['rows']:,} | {dr} |\n")
    L.append("\n（SHA256 与单元数见 data/MANIFEST.json；本报告不涉及 sealed 侧任何内容。）\n")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(L), encoding="utf-8")
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tushare Pro 全量数据抓取（A股策略研究，rules.md 口径）。

- Token 仅从环境变量 TUSHARE_TOKEN 读取，绝不写盘、绝不打印。
- 单进程；每次接口调用之间 sleep >= 0.45 秒。
- 时间切分：记录主日期 <= 20241231 写 data/raw/，>= 20250101 写 data/sealed/。
- 封存文件：全部在内存中拼装、计算 SHA256 后一次性落盘，写完不读回、不打印其内容统计。
- 进度：data/_fetch_state.json，每 50 个单元保存一次，支持断点续传（崩溃后从 _fetch_staging/ 分片重建）。
- 遇到权限或频次错误、或连续 3 次失败：保存进度后退出，不重试轰炸。
  （例外：fund_adj 属可选接口，权限不足时跳过并在 MANIFEST 里记录，报告里写明。）
"""
from __future__ import annotations

import calendar as _cal
import hashlib
import io
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SEALED_DIR = DATA_DIR / "sealed"
STAGING = ROOT / "_fetch_staging"
STATE_FILE = DATA_DIR / "_fetch_state.json"
MANIFEST_FILE = DATA_DIR / "MANIFEST.json"

SPLIT_NOTE = "2024-12-31"
SEALED_MIN = "20250101"
START_ALL = "20130101"
END_DATE = "20260930"   # 固定研究截止日；续传时不得改变
CAL_END = "20261231"

SLEEP_SECS = 0.45
SAVE_EVERY = 50
MAX_CONSEC_FAIL = 3

INDEXES = ["000300.SH", "000905.SH", "000852.SH"]
MEM_FIRST_YM = (2013, 12)
MEM_LAST_YM = (2026, 9)      # 月末成分只取完整月份
FLOW_START = "20140101"      # 资金面按交易日拉的起点
HK_START = "20160701"        # hk_hold 明细数据源实际起点（2016-08-01 起有数）
PAGE_LIMIT = 4200            # 接口单次返回上限，达到即继续 offset 翻页
FUNDS = ["510300.SH", "510500.SH", "518880.SH", "511010.SH"]

# 权限不足时允许跳过（写入 MANIFEST 说明）的组
OPTIONAL_GROUPS = {"fund_adj"}
PERM_PAT = re.compile(r"权限|没有访问|积分不足|permission|not\s+authorized|无权", re.I)
RATE_PAT = re.compile(r"每分钟|每天最多|每小时|频率|太频繁|太多次|访问过快|rate.?limit|too\s+many|exceed|超过.{0,6}上限", re.I)
DATE_RE = re.compile(r"^\d{8}$")

# 组名 -> (tushare 接口名, 主日期列候选，按顺序取第一个存在的；空列表=无日期的静态表)
GROUPS_META = {
    "trade_cal":        ("trade_cal", ["cal_date"]),
    "stock_basic":      ("stock_basic", []),
    "index_members":    ("index_weight", ["trade_date", "con_date"]),
    "daily":            ("daily", ["trade_date"]),
    "adj_factor":       ("adj_factor", ["trade_date"]),
    "daily_basic":      ("daily_basic", ["trade_date"]),
    "stk_limit":        ("stk_limit", ["trade_date"]),
    "suspend_d":        ("suspend_d", ["suspend_date", "trade_date"]),
    "namechange":       ("namechange", ["ann_date", "start_date"]),
    "fina_indicator":   ("fina_indicator", ["ann_date", "end_date"]),
    "forecast":         ("forecast", ["ann_date", "end_date"]),
    "express":          ("express", ["ann_date", "end_date"]),
    "index_member_all": ("index_member_all", ["in_date"]),
    "top_list":         ("top_list", ["trade_date"]),
    "top_inst":         ("top_inst", ["trade_date"]),
    "margin_detail":    ("margin_detail", ["trade_date"]),
    "hk_hold":          ("hk_hold", ["trade_date"]),
    "moneyflow_hsgt":   ("moneyflow_hsgt", ["trade_date"]),
    "fund_daily":       ("fund_daily", ["trade_date"]),
    "fund_adj":         ("fund_adj", ["trade_date"]),
}
GROUP_ORDER = list(GROUPS_META)
POOL_GROUPS = {"daily", "adj_factor", "daily_basic", "stk_limit", "suspend_d", "namechange",
               "fina_indicator", "forecast", "express", "index_member_all"}
FLOW_GROUPS = {"top_list", "top_inst", "margin_detail", "hk_hold", "moneyflow_hsgt"}
# 区间型表：不能简单按主日期 < 2013 丢弃（早期纳入但 2013 后仍在生效的记录要保留）
INTERVAL_GROUPS = {"namechange", "index_member_all"}

SMOKE = "--smoke" in sys.argv
if SMOKE:
    _smoke_root = ROOT / "_smoke"
    STAGING = _smoke_root / "staging"
    DATA_DIR = _smoke_root / "data"
    RAW_DIR = DATA_DIR / "raw"
    SEALED_DIR = DATA_DIR / "sealed"
    STATE_FILE = _smoke_root / "state.json"
    MANIFEST_FILE = _smoke_root / "MANIFEST.json"

if "--help" in sys.argv or "-h" in sys.argv:
    print("用法: python tools/fetch_tushare.py [--smoke]\n"
          "截止2026-09-30；仅读取环境变量TUSHARE_TOKEN；单进程、可续传。\n"
          "--smoke 使用独立_smoke目录，不能替代正式数据。")
    raise SystemExit(0)

for _d in (RAW_DIR, SEALED_DIR, STAGING):
    _d.mkdir(parents=True, exist_ok=True)


class StopFetch(Exception):
    """权限/频次/连续失败：保存进度后终止。"""

    def __init__(self, reason: str, code: int = 2):
        super().__init__(reason)
        self.code = code


class SkipGroup(Exception):
    """可选接口权限不足：跳过该组。"""


# ---------------------------------------------------------------- 基础工具

def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def atomic_write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def clean_date(v):
    """把 tushare 的日期值规范成 'YYYYMMDD' 字符串，空值/非规范返回 pd.NA。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return pd.NA
    if pd.isna(v):
        return pd.NA
    s = str(v).strip()
    return s if DATE_RE.match(s) else pd.NA


def lt_mask(s: pd.Series, v: str) -> pd.Series:
    """字符串日期 < v 的布尔掩码，NA 视为 False。"""
    return (s < v).fillna(False)


def ge_mask(s: pd.Series, v: str) -> pd.Series:
    """字符串日期 >= v 的布尔掩码，NA 视为 False。"""
    return (s >= v).fillna(False)


def resolve_dates(df: pd.DataFrame, cols) -> pd.Series | None:
    if not cols:
        return None
    cur = None
    for c in cols:
        if c not in df.columns:
            continue
        v = df[c].map(clean_date)
        cur = v if cur is None else cur.fillna(v)
    if cur is None:
        cur = pd.Series(pd.NA, index=df.index, dtype="object")
    return cur


def shard_path(group: str, unit: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", unit)
    return STAGING / group / f"{safe}.parquet"


def month_list(first: tuple[int, int], last: tuple[int, int]) -> list[str]:
    out = []
    y, m = first
    while (y, m) <= last:
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# ---------------------------------------------------------------- 单元定义

def units_for(group: str, state: dict) -> list[str]:
    if SMOKE:
        return smoke_units(group)
    if group == "trade_cal":
        return ["SSE"]
    if group == "stock_basic":
        return ["L", "D", "P"]
    if group == "index_members":
        return [f"{idx}|{ym}" for ym in month_list(MEM_FIRST_YM, MEM_LAST_YM) for idx in INDEXES]
    if group in POOL_GROUPS:
        if not state.get("pool"):
            raise RuntimeError("股票池尚未建立（index_members 未完成）")
        return list(state["pool"])
    if group == "moneyflow_hsgt":
        # 该接口区间查询可一次返回整年（每年约 240 行），按年为单位
        return [f"Y{y}" for y in range(2014, int(END_DATE[:4]) + 1)]
    if group == "hk_hold":
        if not state.get("flow_dates"):
            raise RuntimeError("交易日列表尚未建立（trade_cal 未完成）")
        return [d for d in state["flow_dates"] if d >= HK_START]
    if group in FLOW_GROUPS:
        if not state.get("flow_dates"):
            raise RuntimeError("交易日列表尚未建立（trade_cal 未完成）")
        return list(state["flow_dates"])
    if group in ("fund_daily", "fund_adj"):
        return list(FUNDS)
    raise RuntimeError(f"未知组 {group}")


def unit_call(group: str, unit: str):
    """返回 (api_name, params)。"""
    if group == "trade_cal":
        return "trade_cal", dict(exchange="SSE", start_date=START_ALL, end_date=CAL_END)
    if group == "stock_basic":
        # 不带 fields 时接口只返回 10 列（缺 list_status/delist_date/exchange/is_hs），必须显式指定
        fields = ("ts_code,symbol,name,area,industry,cnspell,market,exchange,"
                  "list_status,list_date,delist_date,is_hs,act_name,act_ent_type")
        return "stock_basic", dict(list_status=unit, fields=fields)
    if group == "index_members":
        idx, ym = unit.split("|")
        y, m = int(ym[:4]), int(ym[4:])
        last_day = _cal.monthrange(y, m)[1]
        return "index_weight", dict(index_code=idx, start_date=f"{ym}01", end_date=f"{ym}{last_day:02d}")
    if group in ("daily", "adj_factor", "daily_basic", "stk_limit"):
        end = "20241231" if SMOKE else END_DATE
        return group, dict(ts_code=unit, start_date=START_ALL, end_date=end)
    if group in ("suspend_d", "namechange", "fina_indicator", "forecast", "express", "index_member_all"):
        return group, dict(ts_code=unit)
    if group == "moneyflow_hsgt":
        y = int(unit[1:])
        end = END_DATE if y == int(END_DATE[:4]) else f"{y}1231"
        return group, dict(start_date=f"{y}0101", end_date=end)
    if group in FLOW_GROUPS:
        return group, dict(trade_date=unit)
    if group in ("fund_daily", "fund_adj"):
        return group, dict(ts_code=unit, start_date=START_ALL, end_date=END_DATE)
    raise RuntimeError(f"未知组 {group}")


def smoke_units(group: str) -> list[str]:
    stock = ["000001.SZ"]
    return {
        "trade_cal": ["SSE"],
        "stock_basic": ["L"],
        "index_members": ["000300.SH|201312", "000905.SH|202006"],
        "daily": stock,           # 冒烟里 daily 用完整区间以验证封存侧写入
        "adj_factor": ["000001.SZ"],
        "daily_basic": ["000001.SZ"],
        "stk_limit": ["000001.SZ"],
        "suspend_d": stock,
        "namechange": stock,
        "fina_indicator": stock,
        "forecast": stock,
        "express": stock,
        "index_member_all": stock,
        "top_list": ["20210406"],
        "top_inst": ["20210406"],
        "margin_detail": ["20210406", "20241231"],
        "hk_hold": ["20241231"],
        "moneyflow_hsgt": ["Y2021"],
        "fund_daily": ["510300.SH"],
        "fund_adj": ["510300.SH"],
    }.get(group, [])


# 单元结果里是否允许打印行数（冒烟时避免泄露封存侧统计：只看 raw 侧日期）
def may_print_rows(df: pd.DataFrame, dcols) -> bool:
    d = resolve_dates(df, dcols) if dcols else None
    if d is None or d.dropna().empty:
        return True
    return bool((d.dropna() <= "20241231").all())


# ---------------------------------------------------------------- 行过滤 / 切分

def filter_rows(group: str, df: pd.DataFrame) -> pd.DataFrame:
    """按主日期剔除 2013-01-01 之前已完全失效的记录；区间表用区间逻辑。"""
    if len(df) == 0 or group == "stock_basic":
        return df
    _, dcols = GROUPS_META[group]
    if not dcols:
        return df
    d = resolve_dates(df, dcols)
    if group == "namechange":
        end = df["end_date"].map(clean_date) if "end_date" in df.columns else pd.Series(pd.NA, index=df.index, dtype="object")
        keep = ~(d.notna() & lt_mask(d, START_ALL) & end.notna() & lt_mask(end, START_ALL))
        return df[keep]
    if group == "index_member_all":
        out = df["out_date"].map(clean_date) if "out_date" in df.columns else pd.Series(pd.NA, index=df.index, dtype="object")
        keep = ~(out.notna() & lt_mask(out, START_ALL))
        return df[keep]
    keep = ~(d.notna() & lt_mask(d, START_ALL))
    return df[keep]


# ---------------------------------------------------------------- 落盘

def finalize_group(group: str, df_all: pd.DataFrame, manifest: dict, unit_count: int) -> dict:
    """切分、排序、内存中算 SHA256、写盘。返回 raw 侧统计（sealed 侧只写文件，不打印）。"""
    api, dcols = GROUPS_META[group]
    fname = f"{group}.parquet"
    dates = resolve_dates(df_all, dcols) if dcols else None
    if dates is not None:
        sealed_mask = dates.notna() & ge_mask(dates, SEALED_MIN)
    else:
        sealed_mask = pd.Series(False, index=df_all.index)

    raw_stat: dict = {}
    for side, mask in (("raw", ~sealed_mask), ("sealed", sealed_mask)):
        d = df_all[mask]
        if len(d) == 0:
            continue
        sort_cols = [c for c in ([dcols[0] if dcols else None, "ts_code", "index_code", "con_code"]) if c and c in d.columns]
        if sort_cols:
            d = d.sort_values(sort_cols)
        table = pa.Table.from_pandas(d, preserve_index=False)
        buf = io.BytesIO()
        pq.write_table(table, buf, compression="zstd")
        data = buf.getvalue()
        sha = hashlib.sha256(data).hexdigest()
        out = (RAW_DIR if side == "raw" else SEALED_DIR) / fname
        if out.exists():
            expected = manifest.get("files", {}).get(f"{side}/{fname}", {}).get("sha256")
            if expected != sha:
                raise StopFetch("已有数据与新内容不同；请使用新的研究目录，禁止覆盖。")
        else:
            with out.open("xb") as output:
                output.write(data)
        entry = {"api": api, "rows": int(len(d)), "sha256": sha, "units": unit_count}
        if dates is not None:
            dd = dates[mask].dropna()
            if len(dd):
                entry["date_min"] = str(dd.min())
                entry["date_max"] = str(dd.max())
        manifest["files"][f"{side}/{fname}"] = entry
        if side == "raw":
            raw_stat = {"rows": entry["rows"], "date_min": entry.get("date_min"), "date_max": entry.get("date_max")}
        del d, table, buf, data
    return raw_stat


# ---------------------------------------------------------------- 状态

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"groups": {}, "pool": None, "flow_dates": None}


def save_state(state: dict) -> None:
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    atomic_write_json(STATE_FILE, state)


def load_manifest() -> dict:
    if MANIFEST_FILE.exists():
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "split_date": SPLIT_NOTE,
        "fetch_window": {"start": START_ALL, "end": END_DATE},
        "notes": [
            "sealed 侧文件全部在内存中拼装并计算 SHA256 后一次性落盘，落盘后未读回、未打印；",
            "其 rows / date_min / date_max / sha256 均为写入前在内存中的计算值。",
            "stock_basic 为静态参考表（无日期列），全部落 data/raw/。",
            "hk_hold 明细数据源自 2016-08-01 起（Tushare 无更早明细，2014-11~2016-07 只有 moneyflow_hsgt 整体资金流）；文件内含 exchange=SH/SZ/HK 三类记录。",
            "moneyflow_hsgt 按年区间抓取；单次返回达 4200 行的接口调用用 offset 翻页补齐（hk_hold、margin_detail 等按日接口）。",
            "top_list / top_inst 接口本身不提供 ann_date 字段，落盘仅有 trade_date（T 日盘后披露）。",
            "fund_adj（ETF 复权因子）数据源自 2016-01-19 起，之前的交易日无复权因子。",
        ],
        "files": {},
    }


# ---------------------------------------------------------------- 主流程

def fetch_unit_df(pro, api_name: str, params: dict) -> pd.DataFrame:
    """拉一个单元；返回行数达到单次上限时用 offset 翻页。每次请求前 sleep >= 0.45s。"""
    frames: list[pd.DataFrame] = []
    offset = 0
    while True:
        p = dict(params)
        if offset:
            p["offset"] = offset
            p["limit"] = PAGE_LIMIT
        time.sleep(SLEEP_SECS)
        df = pro.query(api_name, **p)
        frames.append(df)
        if len(df) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    return frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("错误：环境变量 TUSHARE_TOKEN 未设置", flush=True)
        sys.exit(1)

    import tushare as ts
    pro = ts.pro_api(token, timeout=60)

    state = load_state()
    manifest = load_manifest()
    gstates = state["groups"]

    # 已完成的组清理残留分片（上次会话可能在 finalize 与清分片之间中断）
    for g, gs in gstates.items():
        if gs.get("status") == "done":
            gdir = STAGING / g
            if gdir.exists():
                for f in gdir.glob("*.parquet"):
                    f.unlink(missing_ok=True)
                gdir.rmdir()

    # 汇总待办（依赖未就绪的组此时无法计数，跑完依赖后再计）
    plan = []
    for g in GROUP_ORDER:
        gs = gstates.get(g)
        if gs and gs.get("status") in ("done", "skipped"):
            continue
        plan.append(g)
    counts: dict[str, int | None] = {}
    total_known = 0
    for g in plan:
        try:
            n = len(units_for(g, state))
            counts[g] = n
            total_known += n
        except RuntimeError:
            counts[g] = None
    print(f"{now()} 模式={'smoke' if SMOKE else 'full'} 待抓组 {len(plan)} 个"
          f"（其中 {sum(v is None for v in counts.values())} 个依赖股票池/日历，暂无法计数），"
          f"已计数单元 {total_known} 个", flush=True)

    t_group0 = time.time()
    for group in GROUP_ORDER:
        gs = gstates.get(group)
        if gs and gs.get("status") in ("done", "skipped"):
            continue
        if gs is None:
            gs = gstates.setdefault(group, {"status": "partial", "done": []})
        units = units_for(group, state)
        done = set(gs.get("done", []))
        todo = [u for u in units if u not in done]
        print(f"{now()} [{group}] 单元 {len(units)}，已完成 {len(done)}，待抓 {len(todo)}", flush=True)

        # 从分片重建已完成的行（崩溃恢复用；只读 staging，不读 data/sealed）
        frames: list[pd.DataFrame] = []
        for u in gs.get("done", []):
            p = shard_path(group, u)
            if p.exists():
                frames.append(pd.read_parquet(p))

        api, dcols = GROUPS_META[group]
        consec_fail = 0
        unsaved = 0
        skipped = False
        t_group0 = time.time()
        for i, unit in enumerate(todo, 1):
            while True:
                try:
                    api_name, params = unit_call(group, unit)
                    df = fetch_unit_df(pro, api_name, params)
                    consec_fail = 0
                    break
                except Exception as e:
                    msg = str(e).replace(token, "[REDACTED]")
                    if PERM_PAT.search(msg):
                        if group in OPTIONAL_GROUPS:
                            print(f"{now()} [{group}] 无权限，跳过该组：{msg[:100]}", flush=True)
                            skipped = True
                            break
                        save_state(state)
                        raise StopFetch(f"[{group}] 权限错误：{msg[:150]}", 2)
                    if RATE_PAT.search(msg):
                        save_state(state)
                        raise StopFetch(f"[{group}] 频次/限流错误：{msg[:150]}", 2)
                    consec_fail += 1
                    if consec_fail >= MAX_CONSEC_FAIL:
                        save_state(state)
                        raise StopFetch(f"[{group}] 连续 {consec_fail} 次失败：{msg[:150]}", 3)
                    time.sleep(2.0)
            if skipped:
                break
            if df is None or len(df) == 0:
                gs.setdefault("done", []).append(unit)
            else:
                if SMOKE:
                    ok = may_print_rows(df, dcols)
                    print(f"  [smoke] {group} {unit} cols={list(df.columns)}" + (f" rows={len(df)}" if ok else ""), flush=True)
                df = filter_rows(group, df)
                if len(df):
                    p = shard_path(group, unit)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    df.to_parquet(p, index=False)
                    frames.append(df)
                gs.setdefault("done", []).append(unit)
            unsaved += 1
            if unsaved >= SAVE_EVERY:
                save_state(state)
                unsaved = 0
            if i % 100 == 0 or i == len(todo):
                el = time.time() - t_group0
                eta = el / i * (len(todo) - i)
                print(f"{now()} [{group}] {i}/{len(todo)} 已用时 {el/60:.1f}m 剩余 ~{eta/60:.1f}m", flush=True)

        if skipped:
            gs["status"] = "skipped"
            gs["skip_reason"] = "接口无权限"
            api_name, _ = GROUPS_META[group]
            manifest["files"][f"raw/{group}.parquet"] = {"api": api_name, "error": "接口无权限，未落盘"}
            atomic_write_json(MANIFEST_FILE, manifest)
            save_state(state)
            continue

        if frames:
            df_all = pd.concat(frames, ignore_index=True).drop_duplicates()
        else:
            df_all = pd.DataFrame()
        raw_stat = finalize_group(group, df_all, manifest, unit_count=len(gs.get("done", [])))
        manifest["generated_at"] = datetime.now().isoformat(timespec="seconds")
        atomic_write_json(MANIFEST_FILE, manifest)
        gs["status"] = "done"
        gs["units"] = len(gs.get("done", []))
        gs["done"] = []
        save_state(state)
        # 状态已确认落盘，再清理分片
        gdir = STAGING / group
        if gdir.exists():
            for f in gdir.glob("*.parquet"):
                f.unlink(missing_ok=True)
            gdir.rmdir()
        print(f"{now()} [{group}] 完成 raw={raw_stat} 用时 {(time.time()-t_group0)/60:.1f}m", flush=True)

        # 派生下游依赖
        if group == "trade_cal" and len(df_all):
            op = df_all[df_all["is_open"].astype(str).str.strip() == "1"]["cal_date"].astype(str)
            state["flow_dates"] = sorted(d for d in op if FLOW_START <= d <= END_DATE)
            print(f"{now()} 交易日（{FLOW_START}~{END_DATE}）共 {len(state['flow_dates'])} 天", flush=True)
            save_state(state)
        if group == "index_members" and len(df_all) and "con_code" in df_all.columns:
            state["pool"] = sorted(df_all["con_code"].astype(str).unique())
            print(f"{now()} 股票池（历史成分合集）共 {len(state['pool'])} 只", flush=True)
            save_state(state)
        del df_all, frames

    save_state(state)
    print(f"{now()} 全部组处理完毕", flush=True)
    for g in GROUP_ORDER:
        gs = gstates.get(g, {})
        print(f"  {g}: {gs.get('status', '?')}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except StopFetch as e:
        print(f"{now()} 终止：{e}", flush=True)
        sys.exit(e.code)
    except KeyboardInterrupt:
        print(f"{now()} 手动中断", flush=True)
        sys.exit(130)

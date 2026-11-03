# -*- coding: utf-8 -*-
"""
engine/shortlist.py —— 分级与入围（rules.md 第 5.3 / 5.4 节，第 3 版）

三档分级：
  达标  过全部 8 层（final 名单来自 data/funnel_layers.json 与农场 JSON）
  入围  没过全部 8 层，但按 5.4 排名进入本组前 3
  落选  其余

每组必须产出 3 个入围策略（名单不允许为空，rules.md 5.4 第 4 条兜底）：
  1. 硬性资格 = 过第 1 层 且 搜索期年化超额 > 0 且 验证期年化超额 > 0。
  2. 入围分 = min(搜索期 IR, 验证期 IR)，取较差段。
  3. 并列时超额最大回撤小者优先（取两段中 |超额回撤| 更大者比较，保守口径）。
  4. 兜底：硬性合格不足 3 个 → 缺口按搜索期 IR 最高补满，标注
     「验证期未通过」；连第 1 层都没人过 → 取搜索期年化超额最高的 3 个，
     标注「未过第 1 层，交易样本不足」。补位不得称为「找到的策略」。
  5. 入围名单之间不做第 7 层去重，但相关系数照常报告（compare 层职责）。

分组（rules.md 第 5.3 节）：AI = group ∈ {A, B} 合并为一组；每只猴子 =
自己的 monkey_<种子> 组；example / test 同样适用（验收演示用）。
分组一律以台账 group 列为准，配置名前缀只是命名约定。

核心计算是纯函数 build_shortlist(ledger, group, final_set)，对拍与反例
测试直接构造台账/名单输入，不做任何运行时补丁。

CLI：
  python engine/shortlist.py --group AI  --layers data/funnel_layers.json \
      --out data/shortlist_AI.json --md reports/shortlist_AI.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guard  # noqa: E402  必须先于 numpy/pandas（guard 钉死 BLAS 线程环境变量）

import pandas as pd
from backtest import LEDGER_COLS, LEDGER_PATH  # noqa: E402
from funnel import (SEARCH_START, SEARCH_END, VALID_START, VALID_END,  # noqa: E402
                    is_probe, latest_rows_for, read_ledger)

ROOT = guard.ROOT
DATA_DIR = ROOT / "data"

GRADE_PASS = "达标"
GRADE_SHORT = "入围"
GRADE_OUT = "落选"
TAG_NO_VAL = "验证期未通过"
TAG_NO_L1 = "未过第 1 层，交易样本不足"
SHORTLIST_N = 3
AI_GROUPS = ("A", "B")


# ================================================================ final 名单

def load_final_set(group: str, layers_path: Path | None = None,
                   farm_dir: Path | None = None) -> tuple[set[str], str]:
    """组的「过全部 8 层」名单：layers JSON 各路 final + 农场 JSON 回写的 final。

    AI 组取 A、B 两路并集；猴子组取农场 JSON（l7_l8_evaluated=True）里
    本 seed 的 final（m<seed>_ 前缀）；example/test 取 EXAMPLES 路。
    返回 (名字集合, 来源说明)。
    """
    layers_path = Path(layers_path) if layers_path else (DATA_DIR / "funnel_layers.json")
    farm_dir = Path(farm_dir) if farm_dir else DATA_DIR
    tracks: list[str] = []
    seed = None
    if group == "AI":
        tracks = ["A", "B"]
    elif group.startswith("monkey_"):
        try:
            seed = int(group.split("_", 1)[1])
        except ValueError:
            seed = None
    elif group in ("example", "test"):
        tracks = ["EXAMPLES"]
    out: set[str] = set()
    src: list[str] = []
    if layers_path.is_file():
        j = json.loads(layers_path.read_text(encoding="utf-8"))
        for tr, td in j.get("tracks", {}).items():
            if tr in tracks:
                out |= {str(x) for x in td.get("final", [])}
                src.append(f"layers:{tr}")
    if seed is not None:
        p = farm_dir / f"funnel_monkey_s{seed}.json"
        if p.is_file():
            j = json.loads(p.read_text(encoding="utf-8"))
            if j.get("l7_l8_evaluated"):
                pre = f"m{seed}_"
                out |= {str(x) for x in j.get("final", []) if str(x).startswith(pre)}
                src.append(f"farm:s{seed}")
    if not src:
        src.append("（无 final 记录：本组尚无过全部 8 层的策略）")
    return out, "；".join(src)


# ================================================================ 核心纯函数

def _row_num(row: dict | None, key: str) -> float | None:
    if row is None:
        return None
    v = str(row.get(key, "")).strip()
    if v in ("", "nan", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _rank_key_score(r: dict):
    """入围分排名键：分高优先；并列 |超额回撤| 大者小者优先；再按名字。"""
    return (-(r["score"] if r["score"] is not None else -1e18),
            r["dd_worst"], r["config"])


def build_shortlist(ledger: pd.DataFrame, group: str, final_set: set[str] | None = None
                    ) -> dict:
    """rules.md 5.3/5.4：对一组台账行做分级与入围（确定性，名单必为 3 个，
    台账里没有任何该组配置时 entries=[] 并在 note 说明）。

    邻域探针（名字含 __，rules.md 5.2 第 3.2 版）**不参与入围排名**：
    照常计入所在组 N，但不是策略，从不进入 entries/shortlist。
    """
    if final_set is None:
        final_set = set()
    groups = list(AI_GROUPS) if group == "AI" else [group]
    sub = ledger[ledger["group"].astype(str).isin(groups)] if len(ledger) else ledger

    latest_s = latest_rows_for(sub, SEARCH_START, SEARCH_END)
    latest_v = latest_rows_for(sub, VALID_START, VALID_END)
    names = sorted(n for n in set(latest_s) | set(latest_v) if not is_probe(n))

    rows: list[dict] = []
    for name in names:
        s, v = latest_s.get(name), latest_v.get(name)
        s_ok = s is not None and str(s.get("status", "")) == "ok"
        v_ok = v is not None and str(v.get("status", "")) == "ok"
        passed_l1 = bool(_row_num(s, "funnel_l1") == 1.0)
        s_ex = _row_num(s, "ann_excess") if s_ok else None
        v_ex = _row_num(v, "ann_excess") if v_ok else None
        s_ir = _row_num(s, "ir") if s_ok else None
        v_ir = _row_num(v, "ir") if v_ok else None
        s_dd = abs(_row_num(s, "excess_max_dd") or 1.0)
        v_dd = abs(_row_num(v, "excess_max_dd") or 1.0)
        hard = bool(passed_l1 and s_ex is not None and s_ex > 0
                    and v_ex is not None and v_ex > 0)
        score = min(s_ir if s_ir is not None else 0.0,
                    v_ir if v_ir is not None else 0.0) if hard else None
        rows.append({
            "config": name, "passed_l1": passed_l1, "hard": hard,
            "search_ir": s_ir, "val_ir": v_ir,
            "search_ex": s_ex, "val_ex": v_ex,
            "dd_worst": max(s_dd, v_dd),
            "in_final": name in final_set, "score": score,
            "tags": [],
        })

    slots = max(0, SHORTLIST_N - sum(1 for r in rows if r["in_final"]))
    picked: list[dict] = [r for r in rows if r["in_final"]]
    rest = [r for r in rows if not r["in_final"]]

    if slots > 0 and not any(r["passed_l1"] for r in rows):
        # 兜底 2：连第 1 层都没人过 → 搜索期年化超额最高的补满
        fill = sorted(rest, key=lambda r: (-(r["search_ex"] if r["search_ex"] is not None
                                             else -1e18), r["dd_worst"], r["config"]))[:slots]
        for r in fill:
            r["tags"].append(TAG_NO_L1)
        picked += fill
    elif slots > 0:
        # 硬性合格按入围分占坑；缺口由其余按搜索期 IR 最高补位（5.4.4）
        qual = sorted([r for r in rest if r["hard"]], key=_rank_key_score)
        fill = qual[:slots]
        for r in fill:
            r["_picked"] = True
        rest_slots = slots - len(fill)
        if rest_slots > 0:
            chosen = {r["config"] for r in fill}
            pool = [r for r in rest if not r["hard"] and r["config"] not in chosen]
            others = sorted(pool, key=lambda r: (-(r["search_ir"] if r["search_ir"] is not None
                                                    else -1e18), r["dd_worst"], r["config"]))
            for r in others[:rest_slots]:
                r["tags"].append(TAG_NO_VAL)
            fill = fill + others[:rest_slots]
        picked += fill

    picked_names = {r["config"] for r in picked}
    for r in rows:
        if r["in_final"]:
            r["grade"] = GRADE_PASS
        elif r["config"] in picked_names:
            r["grade"] = GRADE_SHORT
        else:
            r["grade"] = GRADE_OUT

    entries = [{
        "config": r["config"],
        "grade": r["grade"],
        "score": r["score"],
        "tags": r["tags"],
        "passed_l1": r["passed_l1"],
        "hard_qualified": r["hard"],
        "search_ir": r["search_ir"], "val_ir": r["val_ir"],
        "search_ann_excess": r["search_ex"], "val_ann_excess": r["val_ex"],
        "excess_max_dd_worst": r["dd_worst"],
    } for r in sorted(rows, key=lambda r: r["config"])]

    return {
        "group": group,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "shortlist": [e["config"] for e in entries
                      if e["grade"] in (GRADE_PASS, GRADE_SHORT)],
        "n_qualified": sum(1 for r in rows if r["hard"]),
        "entries": entries,
        "note": "入围分 = min(搜索期 IR, 验证期 IR)；并列按两段中 |超额回撤| 较大者小者优先。"
                f"名单必须 {SHORTLIST_N} 个（rules.md 5.4.4 兜底）；"
                "补位策略只能称为「本组最好的候选」。"
                "邻域探针（名字含 __）照常计入所在组 N，但不参与入围排名"
                "（rules.md 5.2 第 3.2 版）。",
    }


# ================================================================ 报告

def render_md(result: dict) -> str:
    g = result["group"]
    lines = [f"# 入围名单（{g} 组，rules.md 5.3/5.4）", ""]
    lines.append(f"- 生成时间：{result['generated_at']}")
    if "final_set_source" in result:
        lines.append(f"- 达标名单来源：{result['final_set_source']}")
    lines.append(f"- 硬性合格（过 L1 且两段年化超额 > 0）：**{result['n_qualified']}** 个")
    lines.append(f"- 入围名单（达标优先占名额，共 {len(result['shortlist'])} 个）：")
    for nm in result["shortlist"]:
        e = next(x for x in result["entries"] if x["config"] == nm)
        tags = ("；".join(e["tags"])) if e["tags"] else ""
        score = f"{e['score']:.4f}" if e["score"] is not None else "—"
        lines.append(f"  - **{nm}**（{e['grade']}，入围分 {score}"
                     + (f"，{tags}" if tags else "") + "）")
    lines.append("")
    lines.append("| 配置 | 等级 | 入围分 | 搜索期IR | 验证期IR | 搜索期年化超额 | 验证期年化超额 | 标注 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---|")
    fmt = lambda x: f"{x:.4f}" if isinstance(x, float) else "—"
    for e in result["entries"]:
        lines.append(
            f"| {e['config']} | {e['grade']} | {fmt(e['score'])} | {fmt(e['search_ir'])} | "
            f"{fmt(e['val_ir'])} | {fmt(e['search_ann_excess'])} | "
            f"{fmt(e['val_ann_excess'])} | {'；'.join(e['tags']) or '—'} |")
    lines.append("")
    lines.append("> 入围不等于有效：入围策略未必过全部 8 层，报告与展示必须同时标注"
                 "它没过哪几层（rules.md 5.3）。补位策略只能称为「本组最好的候选」。")
    lines.append("")
    return "\n".join(lines)


# ================================================================ CLI

def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="engine/shortlist.py",
                                 description="5.3/5.4 分级与入围")
    ap.add_argument("--group", required=True,
                    help="AI（=A+B 合并）/ monkey_<种子> / example / test")
    ap.add_argument("--ledger", default=str(LEDGER_PATH))
    ap.add_argument("--layers", default=str(DATA_DIR / "funnel_layers.json"))
    ap.add_argument("--out", default=None, help="JSON 输出（默认 data/shortlist_<group>.json）")
    ap.add_argument("--md", default=None, help="MD 输出（默认 reports/shortlist_<group>.md）")
    a = ap.parse_args(argv)

    ledger = pd.read_csv(a.ledger, dtype=str, keep_default_na=False) \
        if Path(a.ledger).exists() else pd.DataFrame(columns=LEDGER_COLS)
    final_set, src = load_final_set(a.group, Path(a.layers))
    result = build_shortlist(ledger, a.group, final_set)
    result["final_set_source"] = src

    out = Path(a.out) if a.out else DATA_DIR / f"shortlist_{a.group}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    md = Path(a.md) if a.md else ROOT / "reports" / f"shortlist_{a.group}.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(render_md(result), encoding="utf-8")
    print(f"[shortlist] {a.group}: {len(result['shortlist'])} 个入围 -> {out}")
    print(f"[shortlist] 报告 -> {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

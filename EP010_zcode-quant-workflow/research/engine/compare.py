# -*- coding: utf-8 -*-
"""
engine/compare.py —— AI 与猴子的对比报告（rules.md 第 8.2 节）

按 rules.md 第 8.2 节的顺序输出（不许只挑有利的指标）：
  ① 每一层存活率：A、B、主猴子（种子43，rules.md第8.1节）三列并排；20 只种子猴子给出每层存活率的中位数和最大值。
  ② 最终幸存数：A、B 分别在 20 只种子猴子中的百分位。若 AI 和猴子最终
     幸存数都为 0，不做排名，改为报告第 2～4 层存活率的对比。
  ③ 超额分布：各组全部配置单年化超额的中位数与四分位数。

口径：
  * 分组一律以台账 group 列为准（rules.md 第 6 节），不靠配置名前缀推断。
  * 存活率 = 该层累计幸存配置数 ÷ 该组基础配置单数。基础配置单 = 该组在
    搜索期（2014-01-01~2022-12-31）最新台账行中的去重配置名，剔除 L5 邻居
    变体（名字含 "__"）；种子猴子优先用农场 JSON 的 base 名单。
  * L1~L4 从台账漏斗列读取；L5/L6 与（layers 回写后的）L7/L8/final 从农场
    JSON 读取；A/B/主猴子的 L5~L8 亦参考 layers JSON 的同名路。
  * L7/L8/final 只统计 l7_l8_evaluated=true 的农场 JSON（farm 只判到 L6，
    未评过的种子其 L7/L8 不得按 0 计入排名）；唯一例外是结构事实 final ⊆ L6：
    农场 JSON 自己记录的 l6 名单为空时，final 必然为 0，与是否评过 L7/L8
    无关——此时 final 按 0 计（让第 8.2 节的「双零→不做排名」分支可达）。

优雅降级：任何输入缺失（台账 / 农场 JSON / layers JSON）都在报告「数据可用性」
一节写明缺什么、缺哪段指标，绝不崩溃、绝不编数据；退出码仍为 0。

CLI：
  python engine/compare.py --ledger ledger/ledger.csv --farm-dir data \
      --layers data/funnel_layers.json --out reports/compare.md
  python engine/compare.py --selftest        # 合成数据自测（不读真实数据）

输入全部参数化，可在合成数据上测试（见 --selftest）。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guard  # noqa: E402  必须先于 numpy/pandas（guard 钉死 BLAS 线程环境变量）

import numpy as np
import pandas as pd
from backtest import LEDGER_COLS  # noqa: E402
from funnel import (flags_of, is_probe, layer_lists,  # noqa: E402
                    latest_search_rows)

ROOT = guard.ROOT
SEARCH_START, SEARCH_END = "20140101", "20221231"   # 与 funnel 同口径（YYYYMMDD）
# 主随机对照种子（rules.md第8.1节）
MAIN_MONKEY_SEED = 43
N_SEED_MONKEYS = 20                                      # rules.md 第 8.1 节 20 只
LAYERS = ("l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "final")


# ================================================================ 输入读取

def read_ledger_csv(path: Path) -> pd.DataFrame | None:
    """读台账（只读）。缺文件 → None；空文件 → 空表（带 v2 列）。"""
    path = Path(path)
    if not path.is_file():
        return None
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if len(df) == 0:
        return pd.DataFrame(columns=LEDGER_COLS)
    return df


def read_json(path: Path) -> dict | None:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def seed_of_farm_json(p: Path) -> int | None:
    """funnel_monkey_s<seed>.json → seed；不合名 → None。"""
    name = p.stem
    if not name.startswith("funnel_monkey_s"):
        return None
    tail = name[len("funnel_monkey_s"):]
    return int(tail) if tail.isdigit() else None


# ================================================================ 每组层统计

def base_names_of_group(ledger: pd.DataFrame, group: str) -> list[str]:
    """组内基础配置单：搜索期最新台账行里该组的去重配置名，剔除 L5 邻居探针
    （名字含 __，funnel.is_probe 同一判定，rules.md 5.2 第 3.2 版）。"""
    latest = latest_search_rows(ledger)
    names = sorted(n for n, r in latest.items()
                   if str(r.get("group", "")).strip() == group and not is_probe(n))
    return names


def group_layer_counts(ledger: pd.DataFrame, base: list[str],
                       farm: dict | None, layers_track: dict | None) -> dict:
    """一组的各层累计幸存数。缺哪段数据就给 None（不编数）。"""
    latest = latest_search_rows(ledger)
    out: dict[str, int | None] = {}
    l14 = layer_lists(base, latest)
    for k in ("l1", "l2", "l3", "l4"):
        out[k] = len(l14[k])
    # L5/L6：优先农场 JSON（种子猴子的权威来源），否则 layers JSON 同名路
    for k in ("l5", "l6"):
        if farm is not None and k in farm:
            out[k] = len(farm.get(k) or [])
        elif layers_track is not None and k in layers_track:
            out[k] = len(layers_track.get(k) or [])
        else:
            out[k] = None
    # L7/L8/final：农场 JSON 且 l7_l8_evaluated=true，或 layers JSON 同名路
    for k in ("l7", "l8", "final"):
        if farm is not None and farm.get("l7_l8_evaluated") and k in farm:
            out[k] = len(farm.get(k) or [])
        elif layers_track is not None and k in layers_track:
            out[k] = len(layers_track.get(k) or [])
        else:
            out[k] = None
    # 结构事实（final ⊆ L6）：农场 JSON 自己记录的 l6 名单为空时，无论是否
    # 评过 L7/L8，final 必然为 0。此时把 None 补成 0——否则「所有种子都未评
    # L7/L8」时 final 全为未知，rules.md 第 8.2 节「AI 与猴子 final 双零→
    # 不做排名、改为第 2~4 层存活率对比」的分支不可达。其余口径不动
    # （未评种子的 l7/l8 仍是 None，不按 0 计入排名）。
    if farm is not None and not farm.get("l7_l8_evaluated"):
        l6 = farm.get("l6")
        if isinstance(l6, list) and not l6:
            out["final"] = 0
    return out


def excess_stats(ledger: pd.DataFrame, base: list[str]) -> dict | None:
    """一组基础配置单的年化超额分布（搜索期最新行，只取有值的行）。"""
    latest = latest_search_rows(ledger)
    vals: list[float] = []
    for n in base:
        r = latest.get(n)
        if r is None:
            continue
        s = str(r.get("ann_excess", "")).strip()
        if s == "":
            continue
        try:
            vals.append(float(s))
        except ValueError:
            continue
    if not vals:
        return None
    a = np.asarray(vals, dtype="float64")
    return {"n": len(vals),
            "p25": float(np.percentile(a, 25)),
            "p50": float(np.percentile(a, 50)),
            "p75": float(np.percentile(a, 75))}


# ================================================================ 报告生成

def pct_str(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def build_report(ledger: pd.DataFrame | None, farm_dir: Path | None,
                 layers: dict | None, inputs_desc: dict) -> str:
    """生成 markdown 报告。任何输入缺失都降级为「写明缺什么」。"""
    lines: list[str] = []
    lines.append("# AI 与猴子对比报告（rules.md 第 8.2 节）")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    for k, v in inputs_desc.items():
        lines.append(f"- {k}：{v}")
    lines.append("")

    notes: list[str] = []
    if ledger is None:
        notes.append("台账不存在：无法统计任何组的 L1~L4 存活率与超额分布。")
    farm_jsons: dict[int, dict] = {}
    if farm_dir is None or not Path(farm_dir).is_dir():
        notes.append(f"农场结果目录不可用（{farm_dir}）：无法统计 20 只种子猴子的各层存活率。")
    else:
        for p in sorted(Path(farm_dir).glob("funnel_monkey_s*.json")):
            s = seed_of_farm_json(p)
            j = read_json(p)
            if s is not None and j is not None:
                farm_jsons[s] = j
        if not farm_jsons:
            notes.append(f"农场结果目录 {farm_dir} 里没有 funnel_monkey_s<seed>.json："
                         f"种子猴子各层存活率与最终幸存数排名不可用。")
    evaluated_seeds = sorted(s for s, j in farm_jsons.items() if j.get("l7_l8_evaluated"))
    if farm_jsons and len(evaluated_seeds) < len(farm_jsons):
        miss = sorted(set(farm_jsons) - set(evaluated_seeds))
        notes.append(f"种子 {miss} 的农场 JSON 尚未经过 L7/L8（l7_l8_evaluated=false），"
                     f"其 L7/L8 不计入中位数/最大值与排名（farm 只判到 L6）；"
                     f"其中 l6 名单为空者，final 按结构事实（final ⊆ L6）记 0。")
    if layers is None:
        notes.append("layers JSON 不可用：A/B/主猴子若无农场 JSON，其 L5~L8 记为「—」。")
    if notes:
        lines.append("## ⓪ 数据可用性")
        lines.append("")
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")

    if ledger is None:
        lines.append("（缺台账，无法继续。报告只陈述缺失，不编造数字。）")
        return "\n".join(lines) + "\n"

    tracks = (layers or {}).get("tracks", {})

    def farm_base(s: int) -> list[str] | None:
        j = farm_jsons.get(s)
        if j is not None and isinstance(j.get("base"), list):
            return [str(x) for x in j["base"]]
        return None

    # ---- ① 每层存活率 ----
    lines.append("## ① 每层存活率（该层累计幸存数 ÷ 基础配置单数）")
    lines.append("")
    col_defs: list[tuple[str, list[str], dict | None, dict | None]] = []
    for g, label in (("A", "A"), ("B", "B")):
        base = base_names_of_group(ledger, g)
        col_defs.append((label, base, None, tracks.get(g)))
    main_base = farm_base(MAIN_MONKEY_SEED) or base_names_of_group(ledger, f"monkey_{MAIN_MONKEY_SEED}")
    col_defs.append((f"主猴子(seed{MAIN_MONKEY_SEED})", main_base,
                     farm_jsons.get(MAIN_MONKEY_SEED), tracks.get("MONKEY")))
    seed_cols = []
    for s in sorted(farm_jsons):
        if s == MAIN_MONKEY_SEED:
            continue
        base = farm_base(s) or base_names_of_group(ledger, f"monkey_{s}")
        seed_cols.append((s, base, farm_jsons[s]))

    header = f"| 层 | A | B | 主猴子(seed{MAIN_MONKEY_SEED}) |"
    sep = "|---|---|---|---|"
    if seed_cols:
        header += f" 猴子中位数(n={len(seed_cols)}) | 猴子最大值 |"
        sep += "---|---|"
    lines.append(header)
    lines.append(sep)
    lines.append(f"| 基础配置单数 | {len(col_defs[0][1])} | {len(col_defs[1][1])} "
                 f"| {len(col_defs[2][1])} | | |" if seed_cols else
                 f"| 基础配置单数 | {len(col_defs[0][1])} | {len(col_defs[1][1])} "
                 f"| {len(col_defs[2][1])} |")
    counts = [group_layer_counts(ledger, base, farm, trk)
              for _label, base, farm, trk in col_defs]
    for k in LAYERS:
        label = "final" if k == "final" else f"L{k[1]}"
        cells = [pct_str(None if c[k] is None or not len(b) else c[k] / len(b))
                 for c, (_l, b, _f, _t) in zip(counts, col_defs)]
        row = f"| {label} | " + " | ".join(cells) + " |"
        if seed_cols:
            seed_rates = []
            for s, base, j in seed_cols:
                c = group_layer_counts(ledger, base, j, None)
                v = c[k]
                seed_rates.append(v / len(base) if (v is not None and base) else None)
            have = [r for r in seed_rates if r is not None]
            if have:
                row += f" {pct_str(float(np.median(have)))} | {pct_str(float(np.max(have)))} |"
            else:
                row += " — | — |"
        lines.append(row)
    lines.append("")
    lines.append("注：种子猴子各层只统计有数据的种子（L7/L8 仅计入 "
                 "l7_l8_evaluated=true 者；final 在 l6 名单为空时按结构事实记 0）；"
                 "「—」= 该段数据缺失或分母为 0。")
    lines.append("")

    # ---- ② 最终幸存数 ----
    lines.append("## ② 最终幸存数（过全部 8 层）")
    lines.append("")
    a_final = counts[0]["final"]
    b_final = counts[1]["final"]
    seed_finals = {s: group_layer_counts(ledger, base, j, None)["final"]
                   for s, base, j in seed_cols}
    seed_finals = {s: v for s, v in seed_finals.items() if v is not None}
    ai_zero = (a_final == 0) and (b_final == 0)
    monkey_zero = all(v == 0 for v in seed_finals.values()) if seed_finals else True
    if a_final is None or b_final is None:
        lines.append("A/B 的最终幸存数不可用（缺 layers 或农场 JSON），无法排名。")
    elif not seed_finals:
        lines.append(f"A 路最终幸存数 = {a_final}；B 路 = {b_final}；"
                     f"无可参评的种子猴子（缺农场 JSON 或均未评 L7/L8），无法排名。")
    elif ai_zero and monkey_zero:
        lines.append(f"A 路最终幸存数 = {a_final}，B 路 = {b_final}，"
                     f"{len(seed_finals)} 只已评种子猴子的最终幸存数也全为 0"
                     "——按 rules.md 第 8.2 节**不做排名**，改为第 2～4 层存活率对比：")
        lines.append("")
        lines.append("| 层 | A | B | 猴子中位数 | 猴子最大值 |")
        lines.append("|---|---|---|---|---|")
        for k in ("l2", "l3", "l4"):
            label = f"L{k[1]}"
            cells = []
            for c, (_l, b, _f, _t) in zip(counts, col_defs):
                cells.append(pct_str(None if c[k] is None or not len(b) else c[k] / len(b)))
            rates = []
            for s, base, j in seed_cols:
                c = group_layer_counts(ledger, base, j, None)
                v = c[k]
                rates.append(v / len(base) if (v is not None and base) else None)
            have = [r for r in rates if r is not None]
            med = pct_str(float(np.median(have))) if have else "—"
            mx = pct_str(float(np.max(have))) if have else "—"
            lines.append(f"| {label} | {cells[0]} | {cells[1]} | {med} | {mx} |")
        lines.append("")
    else:
        lines.append(f"- A 路最终幸存数 = {a_final}；在 {len(seed_finals)} 只已评种子猴子中"
                     f"百分位 = "
                     f"{100.0 * sum(1 for v in seed_finals.values() if v < a_final) / len(seed_finals):.1f}%"
                     f"（严格更低 {sum(1 for v in seed_finals.values() if v < a_final)} 只，"
                     f"并列 {sum(1 for v in seed_finals.values() if v == a_final)} 只）。")
        lines.append(f"- B 路最终幸存数 = {b_final}；百分位 = "
                     f"{100.0 * sum(1 for v in seed_finals.values() if v < b_final) / len(seed_finals):.1f}%"
                     f"（严格更低 {sum(1 for v in seed_finals.values() if v < b_final)} 只，"
                     f"并列 {sum(1 for v in seed_finals.values() if v == b_final)} 只）。")
        lines.append(f"- 百分位口径：严格低于该路幸存数的猴子数 ÷ 已评种子猴子数；"
                     f"参评种子 = {sorted(seed_finals)}。")
    lines.append("")

    # ---- ③ 超额分布 ----
    lines.append("## ③ 年化超额分布（各组全部基础配置单，搜索期最新台账行）")
    lines.append("")
    lines.append("| 组 | n | P25 | 中位数 | P75 |")
    lines.append("|---|---|---|---|---|")

    def dist_row(label: str, base: list[str]) -> str:
        st = excess_stats(ledger, base)
        if st is None:
            return f"| {label} | 0 | — | — | — |"
        return (f"| {label} | {st['n']} | {st['p25'] * 100:+.2f}% "
                f"| {st['p50'] * 100:+.2f}% | {st['p75'] * 100:+.2f}% |")

    lines.append(dist_row("A", col_defs[0][1]))
    lines.append(dist_row("B", col_defs[1][1]))
    lines.append(dist_row(f"主猴子(seed{MAIN_MONKEY_SEED})", col_defs[2][1]))
    all_seed_base: list[str] = []
    for s, base, _j in sorted(seed_cols):
        lines.append(dist_row(f"猴子 seed{s}", base))
        all_seed_base += base
    if seed_cols:
        lines.append(dist_row("种子猴子合并", all_seed_base))
    lines.append("")
    lines.append("本报告只陈述事实与口径，不含任何投资建议。")
    return "\n".join(lines) + "\n"


# ================================================================ CLI

def run_compare(ledger_path: Path, farm_dir: Path, layers_path: Path,
                out_path: Path) -> int:
    ledger = read_ledger_csv(ledger_path)
    layers = read_json(layers_path)
    farm_exists = Path(farm_dir).is_dir()
    inputs_desc = {
        "台账": str(ledger_path) + ("" if ledger is not None else "（不存在）"),
        "农场结果目录": f"{farm_dir}" + ("" if farm_exists else "（目录不存在）"),
        "layers JSON": f"{layers_path}" + ("" if layers is not None else "（不存在）"),
        "输出": str(out_path),
    }
    report = build_report(ledger, farm_dir if farm_exists else None, layers, inputs_desc)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"[compare] 写出 {out_path}")
    for line in report.splitlines():
        if line.startswith("## ①") or line.startswith("## ②") or line.startswith("## ③"):
            print(f"[compare] {line}")
    return 0


def selftest() -> int:
    """合成数据自测：构造台账+农场 JSON+layers JSON，验证三节内容与降级行为。"""
    ok = True
    results: list[tuple[str, bool]] = []

    def check(name: str, cond: bool, detail: str = ""):
        results.append((name, bool(cond)))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
              + (f"  {detail}" if detail and not cond else ""))

    with tempfile.TemporaryDirectory(prefix="compare_selftest_") as td:
        tmp = Path(td)
        # ---- 合成台账：A 组 3 个基础配置（1 邻居变体剔除）+B 2 个+主猴子 2 个+seed1/2 ----
        def row(ts, cfg, group, status="ok", ann_excess="0.05",
                l1="1", l2="1", l3="1", l4="1", start=SEARCH_START, end=SEARCH_END):
            return {"ts": ts, "config": cfg, "group": group, "type": "rule",
                    "start": start, "end": end, "status": status,
                    "n_trades": "200", "ann_ret": "", "bench_ann_ret": "",
                    "ann_excess": ann_excess, "sharpe": "", "max_dd": "",
                    "ir": "1.0", "excess_max_dd": "-0.1", "beat_years": "5",
                    "total_years": "7", "funnel_l1": l1, "funnel_l2": l2,
                    "funnel_l3": l3, "funnel_l4": l4, "note": ""}

        rows = [
            row("2026-01-01T00:00:00Z", "a_1", "A", ann_excess="0.10"),
            row("2026-01-01T00:00:00Z", "a_2", "A", ann_excess="0.02", l3="0"),
            row("2026-01-01T00:00:00Z", "a_3", "A", ann_excess="-0.03", l2="0", l3="0", l4="0"),
            row("2026-01-01T00:00:00Z", "a_1__buy0t_u", "A", l3="0"),   # 邻居：不计基础数
            row("2026-01-01T00:00:00Z", "b_1", "B", ann_excess="0.30"),
            row("2026-01-01T00:00:00Z", "b_2", "B", ann_excess="0.05", l2="0", l3="0", l4="0"),
            row("2026-01-01T00:00:00Z", "m43_1", "monkey_43", ann_excess="0.01", l4="0"),
            row("2026-01-01T00:00:00Z", "m43_2", "monkey_43", ann_excess="-0.02",
                l2="0", l3="0", l4="0"),
            row("2026-01-01T00:00:00Z", "ms1_001", "monkey_1", ann_excess="0.20"),
            row("2026-01-01T00:00:00Z", "ms1_002", "monkey_1", ann_excess="0.01", l3="0"),
            row("2026-01-01T00:00:00Z", "ms2_001", "monkey_2", ann_excess="-0.10",
                l2="0", l3="0", l4="0"),
        ]
        led_path = tmp / "ledger.csv"
        pd.DataFrame(rows, columns=LEDGER_COLS).to_csv(led_path, index=False, encoding="utf-8")
        ledger = read_ledger_csv(led_path)

        # ---- 合成农场 JSON（seed1：全链路；seed2：只到 L6；seed43：主猴子，
        #      3.2 版主猴子种子 43，rules.md 第 11 章）----
        farm_dir = tmp / "farm"
        farm_dir.mkdir()
        (farm_dir / "funnel_monkey_s1.json").write_text(json.dumps({
            "seed": 1, "base": ["ms1_001", "ms1_002"],
            "l5": ["ms1_001"], "l6": ["ms1_001"],
            "l7": ["ms1_001"], "l8": ["ms1_001"], "final": ["ms1_001"],
            "l7_l8_evaluated": True}), encoding="utf-8")
        (farm_dir / "funnel_monkey_s2.json").write_text(json.dumps({
            "seed": 2, "base": ["ms2_001"], "l5": [], "l6": [],
            "l7": [], "l8": [], "final": [], "l7_l8_evaluated": False}),
            encoding="utf-8")
        (farm_dir / "funnel_monkey_s43.json").write_text(json.dumps({
            "seed": 43, "base": ["m43_1", "m43_2"], "l5": [], "l6": [],
            "l7": [], "l8": [], "final": [], "l7_l8_evaluated": True}),
            encoding="utf-8")
        (farm_dir / "not_farm.json").write_text("{}", encoding="utf-8")  # 应被忽略

        # ---- 合成 layers JSON（A 路 L5~L8 且 final=1；B 路评过但 final=0）----
        layers_path = tmp / "layers.json"
        layers_path.write_text(json.dumps({"tracks": {
            "A": {"l1": ["a_1"], "l2": ["a_1"], "l3": ["a_1"], "l4": ["a_1"],
                  "l5": ["a_1"], "l6": ["a_1"], "l7": ["a_1"], "l8": ["a_1"],
                  "final": ["a_1"]},
            "B": {"l1": ["b_1"], "l2": ["b_1"], "l3": ["b_1"], "l4": ["b_1"],
                  "l5": [], "l6": [], "l7": [], "l8": [], "final": []}}}),
            encoding="utf-8")
        layers = read_json(layers_path)

        rep = build_report(ledger, farm_dir, layers,
                           {"台账": "synthetic", "农场结果目录": str(farm_dir),
                            "layers JSON": str(layers_path), "输出": "memory"})
        # ① 基础数：A=3（邻居剔除）、B=2、主猴子=2
        check("selftest ①：基础配置单数 A=3/B=2/主猴子=2（邻居剔除）",
              "| 基础配置单数 | 3 | 2 | 2 |" in rep, rep[:2000])
        # ① A 路 L1=3/3=100%，L3=1/3，final=1/3；B 路 L5=0%
        check("selftest ①：A 路 L1 100%、final 33.3%",
              "| L1 | 100.0% |" in rep and "| final | 33.3% |" in rep)
        # ② 排名：A final=1、B final=0；已评种子 = {1: 1}
        #    A 与 seed1 并列 → 严格更低 0 只 → 百分位 0.0%
        check("selftest ②：A/B 各自百分位（并列不算更高）",
              "A 路最终幸存数 = 1" in rep and "B 路最终幸存数 = 0" in rep
              and "百分位 = 0.0%" in rep and "并列 1 只" in rep)
        # ③ 超额分布：A 组 P50 = median(10%, 2%, -3%) = 2%
        check("selftest ③：A 组中位超额 +2.00%", "| A | 3 |" in rep and "+2.00%" in rep)

        # ---- 结构事实（final ⊆ L6）：未评 L7/L8 但 l6 名单为空 → final=0 ----
        farm_s2 = {"seed": 2, "base": ["ms2_001"], "l5": [], "l6": [],
                   "l7": [], "l8": [], "final": [], "l7_l8_evaluated": False}
        c_none = group_layer_counts(ledger, ["ms2_001"], {**farm_s2, "l6": ["ms2_001"]}, None)
        c_zero = group_layer_counts(ledger, ["ms2_001"], farm_s2, None)
        check("selftest 结构事实：未评 L7/L8 且 l6 空 → final=0、L7/L8 仍未知",
              c_zero["final"] == 0 and c_zero["l7"] is None and c_zero["l8"] is None,
              f"{c_zero}")
        check("selftest 结构事实：l6 非空且未评 L7/L8 → final 仍为未知（不编数）",
              c_none["final"] is None, f"{c_none}")

        # ---- 0-0 触发：全部 final 清零 → 不排名，报告 L2~L4 对比 ----
        (farm_dir / "funnel_monkey_s1.json").write_text(json.dumps({
            "seed": 1, "base": ["ms1_001", "ms1_002"], "l5": ["ms1_001"],
            "l6": ["ms1_001"], "l7": [], "l8": [], "final": [],
            "l7_l8_evaluated": True}), encoding="utf-8")
        layers0 = {"tracks": {"A": {**layers["tracks"]["A"], "final": []},
                              "B": layers["tracks"]["B"]}}
        rep0 = build_report(ledger, farm_dir, layers0,
                            {"台账": "synthetic", "农场结果目录": str(farm_dir),
                             "layers JSON": "synthetic", "输出": "memory"})
        check("selftest ②0：AI 与猴子 final 全 0 → 不排名、给 L2~L4 对比",
              "不做排名" in rep0 and "第 2～4 层存活率对比" in rep0 and "| L3 |" in rep0)

        # ---- 降级：农场目录存在但没有结果 JSON、无 layers ----
        empty_farm = tmp / "empty_farm"
        empty_farm.mkdir()
        rep1 = build_report(ledger, empty_farm, None,
                            {"台账": "synthetic", "农场结果目录": str(empty_farm),
                             "layers JSON": "（无）", "输出": "memory"})
        check("selftest 降级：缺农场数据写明缺失、不崩溃",
              "数据可用性" in rep1 and "没有 funnel_monkey_s<seed>.json" in rep1
              and "无法排名" in rep1)
        check("selftest 降级：缺台账只剩说明",
              "（缺台账，无法继续。报告只陈述缺失，不编造数字。）"
              in build_report(None, None, None, {}))

    n_fail = sum(1 for _, v in results if not v)
    print(f"== compare selftest: {len(results) - n_fail}/{len(results)} PASS ==")
    return 1 if n_fail else 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="engine/compare.py",
                                 description="AI 与猴子对比报告（rules.md 第 8.2 节）")
    ap.add_argument("--ledger", default="ledger/ledger.csv", help="台账 CSV 路径")
    ap.add_argument("--farm-dir", default="data",
                    help="农场结果目录（funnel_monkey_s<seed>.json 所在）")
    ap.add_argument("--layers", default="data/funnel_layers.json", help="layers JSON 路径")
    ap.add_argument("--out", default="reports/compare.md", help="输出 markdown 路径")
    ap.add_argument("--selftest", action="store_true", help="合成数据自测，不读真实数据")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()

    def _abs(p: str) -> Path:
        p = Path(p)
        return p if p.is_absolute() else (ROOT / p)

    return run_compare(_abs(a.ledger), _abs(a.farm_dir), _abs(a.layers), _abs(a.out))


if __name__ == "__main__":
    raise SystemExit(main())

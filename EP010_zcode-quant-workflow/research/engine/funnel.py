# -*- coding: utf-8 -*-
"""
engine/funnel.py —— 漏斗第 5～8 层、种子猴子对照实验、幸存策略风格体检、汇总报告

依据（全部只读；本文件不修改 rules.md、profile.md，绝不读取 data/sealed/，
绝不创建 OPEN_SEALED，台账只追加；本文件自身可以随规则版本演进）：
  * rules.md 第 5 节（漏斗 L1～L8，第 3.2 版口径）、第 6 节（试验记账：group 列、
    试验总数 N 按组分开计算）、第 7 节（参数档位序列）、第 8 节（对照与比较）、
    第 10 章（试跑模式）、第 11 章（猴子的独立性）、第 12 章（并行执行）。
  * Bailey & López de Prado (2014), "The Deflated Sharpe Ratio"（DSR 公式）。
  * engine/backtest.py：第 1～4 层由引擎在回测时判定并落台账（funnel_l1..l4 列），
    本模块**不重做** L1～L4 的回测与判定，只从台账读取。

层次语义（rules.md 第 5.2 节，第 3.2 版）：
  L5 参数邻域：每个参数在其所属档位序列里上/下各挪一档（每次只动一个参数），
     全部邻居回测落台账；邻居中连过 L1～4 的比例 >= 70% 才过。
     端点只有单侧邻居；比较方向（dir/order）与零件本身（op）不是参数、不挪；
     打分型持仓数固定 30，无邻域；industry_cap 按 0=不启用 + 整数档位序列参与挪档。
     **邻域变体（名字含 __）是探针不是策略**（rules.md 5.2，3.2 版）：照常回测、
     照常落台账、照常计入所在组 N（n_trials_for 口径不变），台账行照常带 L1~L4
     标记（L5 判邻居要读它们）；但不进任何层的候选集（layer_lists 显式排除）、
     不自判 L5~L8、不生成自己的邻域（杜绝二阶递归）、不参与入围排名（shortlist）。
  L6 验证期：2023-01-01～2024-12-31 回测，扣成本年化超额 > 0（与 L2 同口径）。
  L7 去重：幸存者两两**日超额收益**（策略日收益 − 基准日收益；搜索期+验证期
     合并、按日期对齐）相关 >= 0.7 视为同类，按夏普（参考口径）降序贪心遍历，
     与全部已保留者相关都 < 0.7 才保留。
  L8 DSR：DSR 与 t 值全部用日超额收益序列（SR = 日超额均值/日超额标准差，未
     年化；偏度/峰度取超额序列的；t = mean/(std(ddof=1)/√T) >= 3）；
     N 按组计算（rules.md 第 6 节）：AI = group ∈ {A,B} 的台账总行数，每只猴子
     = 自己组的全部行数，example/test 不计入任何组；试验间方差 V[SR] 用同组
     ok 行 ir/√250 的样本方差（对信息比率做多重检验折扣）。分组一律以台账
     group 列为准，不靠配置名前缀推断。

试跑模式（rules.md 第 10 章，默认开，--formal 关）：试跑时 L5 邻域检验只对每组
  入围分排名前 30 的候选执行——入围分 = min(搜索期 IR, 验证期 IR)（rules 5.4），
  依赖验证期回测，故编排顺序为：先对全部 L1~L4 幸存者跑验证期回测 → 按入围分
  排名 → 只对前 30 生成邻域并判 L5；其余候选在 layers 输出与报告里标注
  「未做邻域检验」，不得进入 final/达标。正式跑恢复对全部幸存者做邻域检验。
  试跑的任何结论都不得当作正式结果对外发布。

猴子独立性（rules.md 第 11 章）：gen_monkey 生成每个配置前，与台账中任何组的
  已有配置做规范化比对（canonical_config：键排序 + 数值统一格式），重复的用
  同一随机流继续重采样；**同 seed + 同台账 → 输出确定**。主猴子种子 43

并行执行（rules.md 第 12 章）：默认 workers = CPU 核数 − 2（参数/命令行可覆盖）；
  并行不得改变任何结果——回测指标逐位一致由自测验证；台账追加走跨进程锁
  （backtest._ledger_locked）。

公式与歧义决策详见 notes/funnel_design.md（审计员先读它）。

CLI 子命令：
  selftest                                   已知答案自测（>=6 项断言），退出码 0=全过
  layers  --out data/funnel_layers.json      对台账既有配置（a_/b_/m<种子>_/示例）跑 L5~L8
          [--formal] [--workers N]           --formal=正式跑（默认试跑：每组入围分前 30 才做 L5）
  shortlist --group ...                      5.3/5.4 入围名单（转 engine/shortlist.py）
  gen-monkey --seed S --count N --out DIR    种子 S 确定性生成 N 个猴子配置单（台账去重）
  farm    --seeds A-B [--workers N] [--count] [--formal]
                                             猴子批量：生成→回测→L1-4→L5→L6
                                             （L5/L6 与 layers 同一条路径，试跑同样只做
                                             每组入围分前 30，--formal 恢复全量）
  style   --all                              幸存策略风格体检（写 data/funnel_style.json）
  report                                     渲染 reports/funnel_summary.md
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import multiprocessing as mp
import os
import random
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import guard  # noqa: E402  必须先于 numpy/pandas（guard 钉死 BLAS 线程环境变量）

import numpy as np
import pandas as pd
import yaml

import panel_store
from backtest import LEDGER_COLS, LEDGER_PATH, RUNS_DIR, funnel_flags, run_backtest  # noqa: E402
from config import (ALLOWED_HOLD, ALLOWED_MULT, ALLOWED_PCT, ALLOWED_STOP,  # noqa: E402
                    NO_ARG_OPERATORS, OP_ARG_OPERATORS, SCORE_HOLDINGS, ConfigError,
                    load_config)
from operators import ALLOWED_WINDOWS, OPERATORS, OPERATOR_META  # noqa: E402
from prices import ETF_BENCHMARK, DataStore  # noqa: E402

ROOT = guard.ROOT
DATA_DIR = ROOT / "data"
STRATEGIES_DIR = ROOT / "strategies"
NEIGHBOR_DIR = STRATEGIES_DIR / "funnel"          # L5 邻居配置单落盘目录
FARM_DIR = STRATEGIES_DIR / "monkey_farm"         # 种子猴子配置单目录
LAYERS_JSON = DATA_DIR / "funnel_layers.json"
STYLE_JSON = DATA_DIR / "funnel_style.json"
REPORT_MD = ROOT / "reports" / "funnel_summary.md"

SEARCH_START, SEARCH_END = "20140101", "20221231"   # rules.md 第 1 节（YYYYMMDD）
VALID_START, VALID_END = "20230101", "20241231"     # 仅第 6 层用

# ---- rules.md 第 7 节档位序列（与 engine/config.py ALLOWED_* 同源）----
TIERS: dict[str, tuple] = {
    "window": tuple(ALLOWED_WINDOWS),            # 3,5,10,20,60,120,250
    "pct": tuple(ALLOWED_PCT),                   # 1,2,3,5,8,10,15（阈值可正可负，序列按幅值）
    "mult": tuple(ALLOWED_MULT),                 # 0.5,0.8,1.0,1.2,1.5,2.0
    "hold": tuple(ALLOWED_HOLD),                 # 3,5,10,20
    "stop": tuple(ALLOWED_STOP),                 # 无(None),5,8,10
    "streak": tuple(ALLOWED_WINDOWS),            # streak_up/down 阈值=整数档位
}

L5_MIN_RATIO = 0.70          # 邻居连过 L1-4 比例门槛（>=）
L7_CORR_THRESHOLD = 0.7      # 相关 >= 0.7 视为同类
L8_DSR_MIN = 0.95            # DSR > 0.95
L8_T_MIN = 3.0               # 超额 t 值 >= 3
EULER_GAMMA = 0.5772156649015329   # Euler–Mascheroni 常数
ANNUALIZATION = 250.0        # 引擎年化口径：mean/std(ddof=1) × √250（ir/sharpe 同式）

# 阈值量纲分派：从 OPERATOR_META（单一事实来源，含登记注册的新零件）派生，
# 与 engine/config.py _parse_condition 的分派同源。
PCT_THRESHOLD_OPS = frozenset(n for n, m in OPERATOR_META.items()
                              if m["threshold_kind"] == "pct")
MULT_THRESHOLD_OPS = frozenset(n for n, m in OPERATOR_META.items()
                               if m["threshold_kind"] == "mult")
STREAK_THRESHOLD_OPS = frozenset(n for n, m in OPERATOR_META.items()
                                 if m["threshold_kind"] == "streak")
NO_THRESHOLD_OPS = frozenset(n for n, m in OPERATOR_META.items()
                             if m["threshold_kind"] == "none")

TRACK_ORDER = ("A", "B", "MONKEY", "EXAMPLES", "MS")

AI_GROUPS = ("A", "B")       # rules.md 第 6 节：AI 的 N = group ∈ {A,B} 的全部行数

# ---- rules.md 第 10 章试跑模式 / 第 11 章猴子独立性 / 第 12 章并行执行 ----
MAIN_MONKEY_SEED = 43        # rules.md第8.1节
TRIAL_MODE_DEFAULT = True    # 试跑默认开；命令行 --formal 关（正式跑）
TRIAL_L5_TOP_K = 30          # 试跑：L5 只对每组入围分排名前 30 的候选执行
TAG_NO_L5_CHECK = "未做邻域检验"   # 试跑中未进前 30 的候选在 layers/报告里的标注
NEIGHBOR_MARK = "__"         # 探针标记：名字含 __ 的配置 = 第 5 层生成的邻域变体


def is_probe(name: str) -> bool:
    """名字含 __ 的配置是邻域探针（rules.md 5.2，3.2 版）：照常回测、照常落台账、
    照常计入所在组 N；但不进任何层的候选集、不自判 L5~L8、不生成自己的邻域、
    不参与入围排名。探针判定只认名字，与组无关。"""
    return NEIGHBOR_MARK in str(name)


def default_workers() -> int:
    """默认并行 worker 数（rules.md 第 12 章）：CPU 核数 − 2，至少 1。"""
    return max(1, (os.cpu_count() or 2) - 2)


def resolve_trial_mode(formal: bool | None) -> bool:
    """formal=None → 模块默认（试跑开）；formal=True → 正式跑；formal=False → 试跑。
    返回值 = 是否处于试跑模式。"""
    return TRIAL_MODE_DEFAULT if formal is None else (not formal)


# ================================================================ 台账读取

def read_ledger() -> pd.DataFrame:
    """读台账（只读，绝不修改/删除）。缺文件返回空表。"""
    if not LEDGER_PATH.exists():
        return pd.DataFrame(columns=LEDGER_COLS)
    return pd.read_csv(LEDGER_PATH, dtype=str, keep_default_na=False)


def trials_n(ledger: pd.DataFrame) -> int:
    """台账总行数（含报错行，实时读）。

    注意：rules.md 第 6 节第 2 版起试验总数 N **按组分开计算**——L8 用
    n_trials_for(ledger, group)，本函数只作「台账规模」展示，不再当 N 用。
    """
    return int(len(ledger))


def group_of_config(ledger: pd.DataFrame, name: str) -> str | None:
    """配置的归属组：台账中该配置（任何区间）最新一行的 group 列。

    分组一律以台账 group 列为准，不靠配置名前缀推断（rules.md 第 6 节）。
    无任何行 / group 为空 → None。
    """
    if len(ledger) == 0 or "group" not in ledger.columns:
        return None
    sub = ledger[ledger["config"] == name]
    if len(sub) == 0:
        return None
    sub = sub.sort_values("ts", kind="stable")
    g = str(sub.iloc[-1]["group"]).strip()
    return g or None


def n_trials_for(ledger: pd.DataFrame, group: str | None) -> int:
    """某组的试验总数 N（rules.md 第 6 节，含报错行，实时读台账 group 列）。

    AI（group 为 A 或 B 任一）→ N = group ∈ {A, B} 的全部行数（含第 5 层邻域）；
    每只猴子（group = monkey_<种子>）→ N = 自己组的全部行数（含自己的邻域）；
    example / test 不计入任何组的 N（返回 0）。
    """
    if group is None or len(ledger) == 0 or "group" not in ledger.columns:
        return 0
    if group in AI_GROUPS:
        return int(ledger["group"].isin(AI_GROUPS).sum())
    if str(group).startswith("monkey_"):
        return int((ledger["group"] == group).sum())
    return 0


def group_to_track(group: str | None) -> str | None:
    """台账 group 值 → 漏斗展示路名（TRACK_ORDER 之一）。

    展示分路与分组、试验数一样，一律以台账 group 列为准（rules.md 第 6 节），
    不认文件名前缀：A→"A"、B→"B"、monkey_43→"MONKEY"（3.2 版主猴子，rules.md
    第8.1节）、其他 monkey_<数字种子>→"MS"、
    example→"EXAMPLES"；test 与未知组 → None（不进任何展示路，落入
    other_group_configs）。
    """
    if group is None:
        return None
    g = str(group).strip()
    if g == "A":
        return "A"
    if g == "B":
        return "B"
    if g == f"monkey_{MAIN_MONKEY_SEED}":
        return "MONKEY"
    if re.fullmatch(r"monkey_\d+", g):
        return "MS"
    if g == "example":
        return "EXAMPLES"
    return None


def config_track(ledger: pd.DataFrame, name: str) -> str | None:
    """配置的展示路：查台账 group 列（唯一权威），再映射展示路名。

    台账查不到 / group 为空 / 组不映射展示路（如 test）→ None。
    配置单命名前缀（a_/b_/m<种子>_）只是命名约定，不参与分路——前缀与
    台账 group 矛盾时以 group 列为准（rules.md 第 6 节）。
    """
    return group_to_track(group_of_config(ledger, name))


def latest_search_rows(ledger: pd.DataFrame) -> dict[str, dict]:
    """每个配置名在搜索期（20140101~20221231）的最新一行（含报错行）。

    同名多行按 ts 升序取最后一行（ts 为 ISO8601 Z，字典序即时间序；
    稳定排序保证同 ts 时保留文件顺序的最后一行）。
    """
    return latest_rows_for(ledger, SEARCH_START, SEARCH_END)


def latest_rows_for(ledger: pd.DataFrame, start: str, end: str) -> dict[str, dict]:
    """每个配置名在指定区间 [start, end] 的最新一行（含报错行）。"""
    if len(ledger) == 0:
        return {}
    sub = ledger[(ledger["start"] == start) & (ledger["end"] == end)]
    sub = sub.sort_values("ts", kind="stable").drop_duplicates("config", keep="last")
    return {r["config"]: r for r in sub.to_dict("records")}


def flags_of(row: dict | None) -> tuple[int | None, int | None, int | None, int | None]:
    """台账行 → (l1, l2, l3, l4)；缺失/报错行 → None（视为未通过）。"""
    if row is None:
        return (None, None, None, None)
    out = []
    for k in ("funnel_l1", "funnel_l2", "funnel_l3", "funnel_l4"):
        v = str(row.get(k, "")).strip()
        out.append(int(float(v)) if v not in ("", "nan", "None") else None)
    return tuple(out)  # type: ignore[return-value]


def layer_lists(names: list[str], latest: dict[str, dict]) -> dict[str, list[str]]:
    """L1~L4 累计幸存名单（过该层及之前全部层）。

    邻域探针（名字含 __，rules.md 5.2 第 3.2 版）**显式排除在候选集之外**：
    它们照常在台账里带 L1~L4 标记（L5 判邻居时由 l5_judge 直接读 latest），
    但不进任何层的幸存名单，因此不会进入 L5~L8 判定与 final。
    """
    out = {"l1": [], "l2": [], "l3": [], "l4": []}
    for n in names:
        if is_probe(n):
            continue
        f = flags_of(latest.get(n))
        if f[0] == 1:
            out["l1"].append(n)
            if f[1] == 1:
                out["l2"].append(n)
                if f[2] == 1:
                    out["l3"].append(n)
                    if f[3] == 1:
                        out["l4"].append(n)
    return out


def known_config_names(ledger: pd.DataFrame) -> set[str]:
    """台账中出现过的全部配置名（任何状态都算已跑，skip-existing 依据）。"""
    return set(ledger["config"].astype(str)) if len(ledger) else set()


def filter_pending(candidates: list[str], known: set[str]) -> list[str]:
    """skip-existing：返回台账里还没有的配置名（保持原顺序）。"""
    return [c for c in candidates if c not in known]


# ================================================================ 参数邻域（L5）

def threshold_kind(op_name: str) -> str | None:
    """条件阈值的档位序列种类（与 config._parse_condition 分派一致）。"""
    if op_name in PCT_THRESHOLD_OPS:
        return "pct"
    if op_name in MULT_THRESHOLD_OPS:
        return "mult"
    if op_name in STREAK_THRESHOLD_OPS:
        return "streak"
    return None


def _stop_value(v) -> float | None:
    """YAML stop_loss 字段 → 档位值（None=无 / 5.0 / 8.0 / 10.0）。"""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if s.lower() in ("", "none", "无"):
            return None
        if s.endswith("%"):
            s = s[:-1]
        return float(s)
    return float(v)


def _stop_yaml(v: float | None) -> str:
    return "无" if v is None else f"{v:g}%"


def enumerate_params(raw: dict) -> list[dict]:
    """列出配置单中全部可移动参数（rules.md 第 5/7 节）。

    参数 = 窗口 n（buy/sell/rank/factors 中带窗口的零件）、条件阈值（buy/sell，
    按零件量纲落在 pct/mult/streak 序列）、max_hold_days、stop_loss。
    比较方向（dir/order）与零件本身（op）不是参数；打分型因子 weight 不是
    rules.md 第 7 节参数（见 notes/engine_design.md §4）；打分型持仓数固定 30。
    返回有序列表（buy 逐条 → sell 逐条 → rank → hold → stop；score 为 factors 逐条）。
    """
    params: list[dict] = []

    def add(key, idx, field, kind, value, tag):
        params.append({"key": key, "idx": idx, "field": field, "kind": kind,
                       "value": value, "tag": tag})

    def cond_list(key):
        for i, spec in enumerate(raw.get(key) or []):
            if not isinstance(spec, dict):
                continue
            opn = str(spec.get("op", ""))
            if opn in OP_ARG_OPERATORS and spec.get("n") is not None:
                add(key, i, "n", "window", int(spec["n"]), f"{key}{i}n")
            if "threshold" not in spec:
                continue
            kind = threshold_kind(opn)
            if kind is None:
                continue
            add(key, i, "threshold", kind, float(spec["threshold"]), f"{key}{i}t")

    if raw.get("type") == "rule":
        cond_list("buy")
        cond_list("sell")
        rank = raw.get("rank")
        if isinstance(rank, dict) and str(rank.get("op", "")) in OP_ARG_OPERATORS \
                and rank.get("n") is not None:
            add("rank", None, "n", "window", int(rank["n"]), "rankn")
        hold = raw.get("max_hold_days")
        if hold is not None:
            add(None, None, "max_hold_days", "hold", int(hold), "hold")
        add(None, None, "stop_loss", "stop", _stop_value(raw.get("stop_loss")), "stop")
    elif raw.get("type") == "score":
        for i, f in enumerate(raw.get("factors") or []):
            if not isinstance(f, dict):
                continue
            if str(f.get("op", "")) in OP_ARG_OPERATORS and f.get("n") is not None:
                add("factors", i, "n", "window", int(f["n"]), f"f{i}n")
    return params


def tier_index(kind: str, value) -> int:
    """档位值在序列中的下标；pct 按幅值（负阈值 = 同幅值档位的负号版）。

    值不在档位序列 → ValueError（配置不合法，funnel 不为其构造邻居）。
    """
    seq = TIERS[kind]
    v = abs(float(value)) if kind == "pct" else value
    for i, t in enumerate(seq):
        if v is None and t is None:
            return i
        if v is None or t is None:
            continue
        if float(t) == float(v):
            return i
    raise ValueError(f"值 {value!r} 不在档位序列 {kind}={list(seq)} 中")


def param_neighbors(p: dict) -> list[tuple[str, object]]:
    """一个参数的相邻档位：上/下各一档；端点单侧。返回 [("u"|"d", 新值)]。"""
    idx = tier_index(p["kind"], p["value"])
    seq = TIERS[p["kind"]]
    out: list[tuple[str, object]] = []

    def mv(j):
        base = seq[j]
        if p["kind"] == "pct" and float(p["value"]) < 0:
            return -float(base)            # 负百分比阈值保持负号，按幅值挪档
        if p["kind"] == "window":
            return int(base)
        if p["kind"] == "hold":
            return int(base)
        if p["kind"] == "stop":
            return _stop_yaml(base)
        return float(base)

    if idx + 1 < len(seq):
        out.append(("u", mv(idx + 1)))
    if idx - 1 >= 0:
        out.append(("d", mv(idx - 1)))
    return out


def build_neighbor_set(raw: dict) -> list[dict]:
    """配置单 → 全部相邻组合（每次只动一个参数）。

    邻居名 = <原名>__<参数tag>_<u|d>，如 a_r1_brk_01__buy0t_u。
    返回 [{name, raw, param, dir}]（参数枚举顺序确定 → 名字与顺序确定）。
    """
    out: list[dict] = []
    for p in enumerate_params(raw):
        for dtag, nv in param_neighbors(p):
            nraw = copy.deepcopy(raw)
            if p["key"] is None:
                nraw[p["field"]] = nv
            elif p["idx"] is None:
                nraw[p["key"]][p["field"]] = nv
            else:
                nraw[p["key"]][p["idx"]][p["field"]] = nv
            name = f"{raw['name']}__{p['tag']}_{dtag}"
            nraw["name"] = name
            out.append({"name": name, "raw": nraw, "param": p["tag"], "dir": dtag})
    return out


def ensure_yaml(raw: dict, directory: Path) -> Path:
    """把配置单写盘（已存在则复用——生成是确定性的，同名即同内容）。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / f"{raw['name']}.yaml"
    if not p.exists():
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
    return p


_CONFIG_IDX: dict[str, Path] | None = None


def find_config_yaml(name: str) -> Path | None:
    """在 strategies/ 下递归找 <name>.yaml（缓存索引）。"""
    global _CONFIG_IDX
    if _CONFIG_IDX is None:
        _CONFIG_IDX = {}
        if STRATEGIES_DIR.exists():
            for p in sorted(STRATEGIES_DIR.rglob("*.y*ml")):
                _CONFIG_IDX.setdefault(p.stem, p)
    return _CONFIG_IDX.get(name)


# ================================================================ 回测执行器
# 所有回测都经 engine（run_backtest → 自动落台账，报错行也是正常数据）。
# 判定一律以台账为唯一事实来源：任务跑完重读台账再判定。

def _run_one(store, task: dict) -> dict:
    # group 是「每次执行」的属性（rules.md 第 6 节），随任务传入：
    # 农场猴子 = monkey_<seed>；L5 邻居与验证期任务继承其基础配置单的组。
    if not task.get("group"):
        raise ValueError(f"任务 {task.get('name')} 缺少 group（每次执行的必填属性）")
    record = bool(task.get("record", True))
    try:
        res = run_backtest(store, task["path"], task["start"], task["end"],
                           group=task["group"], record=record, quiet=True)
        out = {"config": res["config_name"], "status": "ok",
               "period": f"{task['start']}~{task['end']}"}
        if not record:
            # 自测注入（record=False，不落台账）：带回指标供「并行与串行
            # 逐位一致」（rules.md 第 12 章）比对；生产任务恒 record=True，
            # 走原路径只回状态。
            out["metrics"] = {k: res[k] for k in
                              ("n_trades", "ann_ret", "bench_ann_ret", "ann_excess",
                               "sharpe", "max_dd", "ir", "excess_max_dd",
                               "beat_years", "total_years")}
        return out
    except Exception as e:  # noqa: BLE001 —— 报错已由引擎落台账，这里只记录返回值
        return {"config": task["name"], "status": "error", "note": repr(e)[:300]}


def _synthetic_store():
    """确定性合成小面板仓库（自测注入用）：3 只股票 × 60 个交易日，固定种子。

    与 DataStore 同接口（panel / calendar / universe_on / etfs），供
    SeqRunner/PoolRunner 的 store_kind="synthetic" 注入，验证「并行与串行
    结果逐位一致」（rules.md 第 12 章）——不读任何真实数据、不写台账
    （一致性任务恒 record=False）。"""
    import numpy as _np
    rng = _np.random.default_rng(20260923)
    days = [d.strftime("%Y%m%d") for d in pd.bdate_range("2014-01-02", periods=60)]
    codes = ["000001.SZ", "600000.SH", "600519.SH"]
    rows = []
    px = {c: 10.0 + 5.0 * i for i, c in enumerate(codes)}
    for d in days:
        for c in codes:
            pre = px[c]
            open_ = round(pre * (1 + float(rng.normal(0, 0.004))), 2)
            close = round(pre * (1 + float(rng.normal(0, 0.008))), 2)
            px[c] = close
            rows.append({
                "date": d, "code": c, "open": open_,
                "high": max(open_, close) + 0.02, "low": min(open_, close) - 0.02,
                "close": close, "pre_close": pre,
                "pct_chg": (close / pre - 1) * 100,
                "vol": 1e6, "amount": 1e7, "af": 1.0, "adj_nav": close,
                "turnover_rate": 2.0, "pe_ttm": 20.0, "pb": 2.0, "ps_ttm": 3.0,
                "total_mv": 1e6, "circ_mv": 8e5,
                "up_limit": round(pre * 1.1, 2), "down_limit": round(pre * 0.9, 2),
                "is_st": 0.0, "l1_code": "801010", "l1_name": "农林牧渔",
                "fin_end_date": None, "roe": 10.0, "or_yoy": 5.0,
                "netprofit_yoy": 8.0, "fc_ann_date": None, "fc_type": None,
                "fc_type_code": 2.0, "fc_chg_mid": 50.0, "fc_days": 5.0,
                "ex_ann_date": None, "ex_yoy": 6.0, "ex_days": 3.0,
                "n_listed": 1000.0,
                # 资金面列（第 3 步；全部 NaN/0 —— 合成面板只验撮合与并行一致性，
                # 零件数值语义由 selftest §2/§3 与 newspaper 覆盖）
                "tl_on_list": 0.0, "tl_inst_netbuy_pct": _np.nan,
                "margin_rzye": _np.nan, "hk_ratio": _np.nan,
            })
    panel = pd.DataFrame(rows).sort_values(["code", "date"],
                                           kind="stable").reset_index(drop=True)

    class _SyntheticStore:   # noqa: 与 DataStore 同接口的最小替身
        pass

    st = _SyntheticStore()
    st.panel = panel
    st.calendar = sorted(panel["date"].unique().tolist())
    st.universe_on = lambda t: list(codes)
    # 基准 ETF 日线（etf_above_ma_n 零件与 run_benchmark 兜底用；确定性直线）
    st.etfs = {ETF_BENCHMARK: pd.DataFrame({
        "date": [d.strftime("%Y%m%d") for d in pd.bdate_range("2013-06-03", periods=200)],
        "close_adj": list(np.round(np.linspace(2.0, 3.0, 200), 6)),
    })}
    return st


def _store_for(kind: str):
    """worker 的数据面板工厂："real" = 真实面板（优先跨进程共享缓存
    panel_store，禁用/失败退回 DataStore 全量构建；绕过契约见
    QUANT_BT_RESULT_CACHE/QUANT_BT_RUN_DIR_REUSE），"synthetic" = 确定性合成小面板（自测注入，
    rules.md 第 12 章一致性验证用）。"""
    if kind == "real":
        return panel_store.real_store(quiet=True)
    if kind == "synthetic":
        return _synthetic_store()
    raise ValueError(f"未知 store 种类 {kind!r}")


class SeqRunner:
    """顺序执行：进程内共享一次仓库加载。store_kind 见 _store_for。

    提供 close()（空操作）——与 PoolRunner 同一 runner 协议，调用方无须分型。"""

    def __init__(self, store_kind: str = "real"):
        self.store_kind = store_kind
        self._store = None

    def run(self, tasks: list[dict]) -> list[dict]:
        out = []
        for i, t in enumerate(tasks, 1):
            if self._store is None:
                print(f"[funnel] 加载数据面板（顺序模式，一次共享，kind={self.store_kind}）……",
                      flush=True)
                t0 = time.time()
                self._store = _store_for(self.store_kind)
                print(f"[funnel] 面板加载完成，用时 {time.time()-t0:.1f}s", flush=True)
            r = _run_one(self._store, t)
            out.append(r)
            print(f"[funnel] ({i}/{len(tasks)}) {t['name']} -> {r['status']}", flush=True)
        return out

    def close(self) -> None:
        self._store = None      # 面板随对象释放；接口占位，见 PoolRunner.close


_WORKER_STORE = None


def _pool_init(store_kind: str = "real"):
    global _WORKER_STORE
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    # 每个 worker 各自加载一次仓库（可接受）；台账追加的并发安全由
    # backtest._ledger_locked 的跨进程锁保证（rules.md 第 12 章）。
    _WORKER_STORE = _store_for(store_kind)


def _pool_run(task: dict) -> dict:
    return _run_one(_WORKER_STORE, task)


class PoolRunner:
    """多进程池执行（Windows spawn：worker 函数在模块顶层，入口有 __main__ 保护）。
    store_kind 经 initializer 传入子进程（"synthetic" 供自测注入）。

    池为**常驻**（rules.md 第 12 章固定成本摊薄）：首次 run() 惰性创建，跨批次
    复用（layers 逐路、farm 逐 seed 的多批任务不再各自重启 worker + 重载面板）；
    用完由调用方 close() 排空回收，未 close 的池由 multiprocessing 的退出
    钩子兜底终止。close 后再 run() 会重建新池。"""

    def __init__(self, workers: int, store_kind: str = "real"):
        self.workers = max(1, int(workers))
        self.store_kind = store_kind
        self._pool = None

    def _get_pool(self):
        if self._pool is None:
            print(f"[funnel] 启动 {self.workers} 个回测 worker"
                  f"（常驻池，跨批次复用，各自加载一次面板，kind={self.store_kind}）……",
                  flush=True)
            t0 = time.time()
            self._pool = mp.Pool(self.workers, initializer=_pool_init,
                                 initargs=(self.store_kind,))
            print(f"[funnel] worker 池就绪（用时 {time.time()-t0:.0f}s）", flush=True)
        return self._pool

    def run(self, tasks: list[dict]) -> list[dict]:
        if not tasks:
            return []
        out: list[dict] = []
        t0 = time.time()
        pool = self._get_pool()
        for i, r in enumerate(pool.imap_unordered(_pool_run, tasks, chunksize=1), 1):
            out.append(r)
            if i % 20 == 0 or i == len(tasks):
                print(f"[funnel] 进度 {i}/{len(tasks)}（用时 {time.time()-t0:.0f}s）",
                      flush=True)
        return out

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()      # 不再接新任务，worker 排空现有任务后退出
            self._pool = None


def make_runner(workers: int, store_kind: str = "real"):
    return PoolRunner(workers, store_kind) if workers > 1 else SeqRunner(store_kind)


# ================================================================ L5 / L6 判定

def l5_judge(latest: dict[str, dict], base_name: str,
             neighbor_names: list[str]) -> dict:
    """L5：邻居中连过 L1～4 的比例 >= 70% 才过。

    空邻域（配置无任何可移动参数）视为通过（没有邻居能否证稳健性）；
    邻居报错行没有漏斗标记 → 计为未通过（报错行也是正常数据）。
    """
    n_pass = 0
    per: dict[str, bool] = {}
    for n in neighbor_names:
        f = flags_of(latest.get(n))
        ok = all(v == 1 for v in f)
        per[n] = ok
        n_pass += int(ok)
    total = len(neighbor_names)
    if total == 0:
        return {"pass": True, "ratio": None, "n_total": 0, "n_pass": 0,
                "neighbors": {}, "note": "无可移动参数，空邻域按空真通过"}
    ratio = n_pass / total
    return {"pass": bool(ratio >= L5_MIN_RATIO), "ratio": ratio,
            "n_total": total, "n_pass": n_pass, "neighbors": per, "note": ""}


def l6_judge(ledger: pd.DataFrame, name: str) -> dict:
    """L6：验证期（2023-01-01~2024-12-31）扣成本年化超额 > 0（与 L2 同口径）。"""
    sub = ledger[(ledger["config"] == name) & (ledger["start"] == VALID_START)
                 & (ledger["end"] == VALID_END)]
    sub = sub.sort_values("ts", kind="stable")
    row = sub.iloc[-1].to_dict() if len(sub) else None
    if row is None or str(row.get("status", "")) != "ok" or str(row.get("ann_excess", "")) == "":
        return {"pass": False, "ann_excess": None, "note": "验证期无成功回测行"}
    ax = float(row["ann_excess"])
    return {"pass": bool(ax > 0), "ann_excess": ax,
            "run_dir": str((RUNS_DIR / f"{name}__{VALID_START}_{VALID_END}").relative_to(ROOT)),
            "note": ""}


# ================================================================ 日收益加载（L7/L8/style）

def run_dir_of(name: str, start: str, end: str, runs_dir: Path | None = None) -> Path:
    """配置在 [start, end] 区间的回测产物目录（缺省 = 仓库 reports/runs；
    runs_dir 供自测注入临时目录，使验证期产物检查与环境无关）。"""
    root = Path(runs_dir) if runs_dir is not None else RUNS_DIR
    return root / f"{name}__{start}_{end}"


def load_daily_merged(name: str) -> pd.DataFrame | None:
    """合并搜索期+验证期的日收益（date, strategy_ret, benchmark_ret, excess），
    按日升序。excess = 策略日收益 − 基准日收益（L7/L8 用，rules.md 第 5.1 节）。"""
    frames = []
    for s, e in ((SEARCH_START, SEARCH_END), (VALID_START, VALID_END)):
        p = run_dir_of(name, s, e) / "daily_returns.csv"
        if p.exists():
            df = pd.read_csv(p, dtype={"date": str})
            frames.append(df[["date", "strategy_ret", "benchmark_ret"]])
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True).drop_duplicates("date", keep="last")
    df = df.sort_values("date").reset_index(drop=True)
    df["excess"] = df["strategy_ret"] - df["benchmark_ret"]
    return df


# ================================================================ L7 贪心去重

def pearson_corr(a: pd.Series, b: pd.Series) -> float:
    """按日期内连接后的 Pearson 相关；公共点 < 2 或方差为 0 → 0.0（视为不同类）。"""
    j = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
    if len(j) < 2 or float(j["a"].std(ddof=1)) == 0 or float(j["b"].std(ddof=1)) == 0:
        return 0.0
    return float(j["a"].corr(j["b"]))


def l7_dedup(candidates: list[dict], sharpe_of: dict[str, float],
             loader=None) -> dict:
    """L7 贪心去重（rules.md 第 5.2 节）：按夏普（参考口径）降序遍历
    （并列按名字升序），与全部已保留者相关 < 0.7 才保留。

    相关 = 搜索期+验证期合并的**日超额收益**序列（策略日收益 − 基准日收益，
    按日期对齐）的 Pearson 相关，r >= 0.7 视为同类；阈值与贪心规则不变。
    夏普 = 台账搜索期行记录的（年化）夏普——只作遍历顺序，不作门槛。
    loader：日收益加载函数（默认 load_daily_merged）；自测注入合成序列用，
    不对 engine 模块做任何运行时补丁。
    邻域探针（名字含 __）不是策略（rules.md 5.2 第 3.2 版），进入本函数的
    候选先被显式剔除——探针既不出现在 kept 也不出现在 dropped。
    """
    if loader is None:
        loader = load_daily_merged
    candidates = [c for c in candidates if not is_probe(c["name"])]
    order = sorted(candidates, key=lambda c: (-sharpe_of[c["name"]], c["name"]))
    kept: list[dict] = []
    dropped: list[dict] = []
    series: dict[str, pd.Series] = {}

    def excess_series(nm: str) -> pd.Series:
        if nm not in series:
            df = loader(nm)
            series[nm] = (pd.Series(df["excess"].to_numpy(), index=df["date"])
                          if df is not None else pd.Series(dtype="float64"))
        return series[nm]

    for c in order:
        name = c["name"]
        s = excess_series(name)
        keeper = None
        worst = None
        for k in kept:
            r = pearson_corr(s, excess_series(k["name"]))
            if worst is None or r > worst["corr"]:
                worst = {"corr": r, "with": k["name"]}
            if r >= L7_CORR_THRESHOLD:
                keeper = k
                break
        if keeper is None:
            kept.append({**c, "max_corr": worst})
        else:
            dropped.append({"name": name, "corr_with": keeper["name"],
                            "corr": worst["corr"] if worst else None})
    return {"kept": kept, "dropped": dropped}


# ================================================================ L8 DSR（Bailey & López de Prado 2014）

def trials_sr_variance(ledger: pd.DataFrame, group: str | None) -> tuple[float, int]:
    """同组试验间（日频、未年化）SR 的样本方差：V[SR] = Var(ir_i/√250)。

    第 2 版口径（rules.md 第 6 节 N 按组 + 第 5.2 节 L8 对信息比率做多重检验
    折扣）：只取 group 组（AI = A∪B；猴子 = 自己组）status=ok 且有 ir 的台账行，
    每行的 SR = ir / √250（引擎 ir = 日超额 mean/std(ddof=1)×√250，同一年化式）。
    报错行无试验产出，不计入。
    """
    if len(ledger) == 0 or "status" not in ledger.columns:
        return float("nan"), 0
    sub = ledger[ledger["status"] == "ok"]
    if group is not None and "group" in sub.columns:
        if group in AI_GROUPS:
            sub = sub[sub["group"].isin(AI_GROUPS)]
        elif str(group).startswith("monkey_"):
            sub = sub[sub["group"] == group]
        else:
            return float("nan"), 0          # example/test 不计入任何组
    vals: list[float] = []
    for v in sub["ir"] if "ir" in sub.columns else []:
        s = str(v).strip()
        if s == "":
            continue
        try:
            vals.append(float(s) / math.sqrt(ANNUALIZATION))
        except ValueError:
            continue
    if len(vals) < 2:
        return float("nan"), len(vals)
    return float(np.var(np.asarray(vals, dtype="float64"), ddof=1)), len(vals)


def dsr_compute(sr_daily: float, v_sr: float, n_trials: int,
                skew: float, kurt: float, t_len: int) -> dict:
    """Deflated Sharpe Ratio（Bailey & López de Prado 2014）。

      SR0 = sqrt(V[SR]) · [ (1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(N·e)) ]
      DSR = Φ( (SR − SR0) · sqrt( (T−1) / (1 − γ3·SR + (γ4−1)/4·SR²) ) )

    SR、SR0、V[SR] 全部为日频未年化口径（第 2 版：全部基于**日超额收益**序列）；
    γ3=偏度、γ4=峰度（Pearson，正态=3），T = 日超额收益样本数，
    γ = Euler–Mascheroni，e = 自然常数，N = 本组试验总数（rules.md 第 6 节）。
    """
    if n_trials < 2 or t_len < 2 or not (v_sr >= 0) or not math.isfinite(v_sr):
        return {"sr0": None, "dsr": None, "stat": None, "note": "样本不足（N<2 或 T<2 或无试验方差）"}
    from scipy.stats import norm
    z1 = float(norm.ppf(1.0 - 1.0 / n_trials))
    z2 = float(norm.ppf(1.0 - 1.0 / (n_trials * math.e)))
    sr0 = math.sqrt(v_sr) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)
    denom = 1.0 - skew * sr_daily + (kurt - 1.0) / 4.0 * sr_daily ** 2
    if denom <= 0:
        return {"sr0": sr0, "dsr": None, "stat": None,
                "note": "DSR 分母非正（偏度/峰度与 SR 组合退化），判不通过"}
    stat = (sr_daily - sr0) * math.sqrt((t_len - 1) / denom)
    return {"sr0": sr0, "dsr": float(norm.cdf(stat)), "stat": stat, "note": ""}


def l8_judge(ledger: pd.DataFrame, name: str) -> dict:
    """L8（rules.md 第 5.2 节第 2 版）：DSR > 0.95 且日超额 t 值 >= 3。

    全部统计量基于该策略**日超额收益**序列（策略日收益 − 基准日收益，
    搜索期+验证期合并）：SR = 日超额均值 / 日超额标准差（未年化）；
    偏度/峰度 = 超额序列的总体矩（scipy bias=True，峰度 fisher=False 即 Pearson）；
    t = mean / (std(ddof=1)/√T)。
    N 按组计算（rules.md 第 6 节）：被评配置的组以台账 group 列为准——
    AI（A/B 任一）→ group ∈ {A,B} 的全部行数；猴子 → 自己组全部行数；
    example/test 不计入任何组（N=0，DSR 无法定义 → 判不通过）。
    V[SR] = 同组 ok 行 ir/√250 的样本方差。
    """
    from scipy.stats import kurtosis, skew
    group = group_of_config(ledger, name)
    n = n_trials_for(ledger, group)
    df = load_daily_merged(name)
    if df is None or len(df) < 3:
        return {"pass": False, "group": group, "note": "无合并日收益（搜索期+验证期）", "N": n}
    ex = df["excess"].to_numpy(dtype="float64")
    t_len = len(ex)
    sd_ex = float(np.std(ex, ddof=1))
    sr_daily = float(np.mean(ex)) / sd_ex if sd_ex > 0 else 0.0
    g3 = float(skew(ex, bias=True))
    g4 = float(kurtosis(ex, fisher=False, bias=True))
    v_sr, _ = trials_sr_variance(ledger, group)
    d = dsr_compute(sr_daily, v_sr, n, g3, g4, t_len)
    t_stat = float(np.mean(ex)) / (sd_ex / math.sqrt(t_len)) if sd_ex > 0 else 0.0
    passed = (d["dsr"] is not None) and (d["dsr"] > L8_DSR_MIN) and (t_stat >= L8_T_MIN)
    return {"pass": bool(passed), "group": group, "N": n, "T": t_len, "SR_daily": sr_daily,
            "SR0_daily": d["sr0"], "V_SR_trials": None if not math.isfinite(v_sr) else v_sr,
            "skew": g3, "kurt": g4, "dsr": d["dsr"], "t_stat": t_stat,
            "note": d["note"]}


# ================================================================ gen-monkey

# 随机零件池：从 OPERATOR_META（单一事实来源）派生——新零件经
# engine/register_operator.py 登记（通过撕报纸测试）后自动进入猴子抽样范围，
# 无需再手改多处。顺序 = META 定义顺序（内置零件与第 1 轮
# OPS_WITH_N + OPS_NO_ARG 拼接顺序一致，同 seed 随机流保持稳定）。
OPS_WITH_N = tuple(n for n, m in OPERATOR_META.items() if m["has_window"])
OPS_NO_ARG = tuple(n for n, m in OPERATOR_META.items() if not m["has_window"])
# buy/sell 条件只能用有阈值量纲的零件（threshold_kind != none）；
# factor/rank 无此限制（无量纲零件只能作 factor/rank）。
OPS_CONDITION = tuple(n for n, m in OPERATOR_META.items()
                      if m["threshold_kind"] != "none")
PCT_TIER_POOL = TIERS["pct"]
MULT_TIER_POOL = TIERS["mult"]
HOLD_POOL = TIERS["hold"]
STOP_POOL = ("无", "5%", "8%", "10%")
WEIGHT_POOL = (0.2, 0.3, 0.5, 1.0, 1.5, 2.0, 3.0)   # 打分型因子权重（非 rules.md 档位参数）


# 随机零件池一致性：派生自 OPERATOR_META，必须与 OPERATORS 注册表及
# config.py 的参数形态登记一致（import 时断言，登记新零件后自动成立）
assert set(OPS_WITH_N) | set(OPS_NO_ARG) == set(OPERATORS), \
    "猴子零件池与 OPERATORS 注册表不一致"
assert set(OPS_WITH_N) == set(OP_ARG_OPERATORS)
assert set(OPS_NO_ARG) == set(NO_ARG_OPERATORS)
assert set(OPS_CONDITION) == set(OPERATORS) - NO_THRESHOLD_OPS


def _rand_threshold(rng: random.Random, opn: str):
    kind = OPERATOR_META[opn]["threshold_kind"]
    if kind == "pct":
        return rng.choice((1.0, -1.0)) * rng.choice(PCT_TIER_POOL)
    if kind == "mult":
        return rng.choice(MULT_TIER_POOL)
    if kind == "streak":
        return float(rng.choice(TIERS["streak"]))
    raise ValueError(f"未登记量纲的零件 {opn}")


def _rand_op_spec(rng: random.Random, pool: tuple = None) -> dict:
    pool = OPS_WITH_N + OPS_NO_ARG if pool is None else pool
    opn = rng.choice(pool)
    if opn in OPS_WITH_N:
        return {"op": opn, "n": rng.choice(TIERS["window"])}
    return {"op": opn}


# 嵌套 wrapper（has_of 零件）：rules.md 8.3 新零件对猴子开放——打分因子/rank
# 以 25% 概率包一层时序分位 / 截面分位 / 行业内排名；基零件只取一层（不嵌套嵌套）
OF_WRAPPERS = tuple(n for n, m in OPERATOR_META.items() if m.get("has_of"))
OF_WRAP_PROB = 0.25
# 基零件池 = 全部零件去掉 wrapper：wrapper（ts_pct/xsec_pct/ind_rank）只能作
# 外层包 one 层 of=基零件，config.load_config 拒绝「wrapper 当基零件（缺 of）」
# 的 spec——3.2 自测第 15 节暴露的老生成器缺陷（曾生成过不了 load_config 的
# 配置单），在此源头修正；修正改变随机流内容，但「同 seed + 同台账 → 输出
# 确定」不变（rules.md 第 11 章）。
FACTOR_BASE_POOL = tuple(n for n in OPS_WITH_N + OPS_NO_ARG if n not in OF_WRAPPERS)


def _rand_factor_spec(rng: random.Random) -> dict:
    base = _rand_op_spec(rng, FACTOR_BASE_POOL)
    if OF_WRAPPERS and rng.random() < OF_WRAP_PROB:
        w = rng.choice(OF_WRAPPERS)
        spec = {"op": w, "of": base}
        if OPERATOR_META[w]["has_window"]:
            spec["n"] = rng.choice(TIERS["window"])
        return spec
    return base


def _rand_condition(rng: random.Random) -> dict:
    spec = _rand_op_spec(rng, OPS_CONDITION)
    return {**spec, "dir": rng.choice(("above", "below")),
            "threshold": _rand_threshold(rng, spec["op"])}


def make_rule_cfg(name: str, seed: int, rng: random.Random) -> dict:
    cfg = {
        "name": name, "type": "rule",
        "desc": f"种子猴子随机配置（seed={seed}，engine/funnel.py gen-monkey）",
        "buy": [_rand_condition(rng) for _ in range(rng.randint(1, 4))],
        "sell": [_rand_condition(rng) for _ in range(rng.randint(0, 2))],
        "max_hold_days": rng.choice(HOLD_POOL),
        "stop_loss": rng.choice(STOP_POOL),
        "max_positions": 10,
    }
    if rng.random() < 0.5:
        cfg["rank"] = {**_rand_factor_spec(rng), "order": rng.choice(("asc", "desc"))}
    return cfg


def make_score_cfg(name: str, seed: int, rng: random.Random) -> dict:
    return {
        "name": name, "type": "score",
        "desc": f"种子猴子随机配置（seed={seed}，engine/funnel.py gen-monkey）",
        "factors": [{**_rand_factor_spec(rng),
                     "weight": rng.choice((1.0, -1.0)) * rng.choice(WEIGHT_POOL)}
                    for _ in range(rng.randint(1, 4))],
        "holdings": SCORE_HOLDINGS,
        "rebalance": "weekly_first_trade_day",
    }


def monkey_names(seed: int, count: int) -> list[str]:
    return [f"m{seed}_{i:03d}" for i in range(1, count + 1)]


def canonical_config(raw: dict) -> str:
    """配置单的结构归一化（rules.md 第 11 章「规范化」）：可哈希字符串。

    规范化 = 结构归一：字典键递归排序 + 数值统一格式（int/float 统一按
    float 十进制表示，1 与 1.0 归一）；字符串原样（含 None→"null:"、布尔
    显式标注，避免与数值串扰）；**列表保序**——buy/sell/factors 的条件顺序
    是配置结构的一部分，不排序。同构配置（键序、数值写法不同）归一后相同。
    """
    def norm(o):
        if isinstance(o, dict):
            return {f"k:{k}": norm(v) for k, v in
                    sorted(o.items(), key=lambda kv: str(kv[0]))}
        if isinstance(o, (list, tuple)):
            return [norm(v) for v in o]
        if isinstance(o, bool):
            return f"bool:{o}"
        if isinstance(o, (int, float, np.integer, np.floating)):
            return f"num:{float(o):.10g}"
        if o is None:
            return "null:"
        return f"str:{o}"

    return json.dumps(norm(raw), ensure_ascii=False, sort_keys=True)


def existing_canonical_configs(ledger: pd.DataFrame,
                               extra_raw: dict[str, dict] | None = None
                               ) -> tuple[set[str], int, int]:
    """台账中**任何组**已有配置的规范化形态集合（rules.md 第 11 章去重依据）。

    配置单 YAML 经 find_config_yaml 在 strategies/ 下定位后载入再归一；
    台账有行但找不到/读不了 YAML 的配置无法比对，计数返回（不猜测其内容）。
    extra_raw：调用方显式注入的 {配置名: 原始 dict}（自测用 DI，生产恒 None）。
    返回 (规范化集合, 可比配置数, 缺 YAML 数)。
    """
    seen: set[str] = set()
    have = miss = 0
    names: list[str] = []
    if len(ledger) and "config" in ledger.columns:
        names = list(dict.fromkeys(ledger["config"].astype(str)))
    for name in names:
        raw = (extra_raw or {}).get(name)
        if raw is None:
            src = find_config_yaml(name)
            if src is None:
                miss += 1
                continue
            try:
                raw = yaml.safe_load(open(src, encoding="utf-8"))
            except Exception:  # noqa: BLE001 —— 读不了的配置无法比对，计入缺失
                miss += 1
                continue
        if isinstance(raw, dict) and raw.get("name"):
            seen.add(canonical_config(raw))
            have += 1
    return seen, have, miss


GEN_MONKEY_MAX_ATTEMPTS = 10_000   # 单个配置位的重采样上限（超过即报错，绝不静默放行）


def gen_monkey(seed: int, count: int, out_dir: Path,
               ledger: pd.DataFrame | None = None,
               extra_raw: dict[str, dict] | None = None
               ) -> tuple[list[Path], list[str]]:
    """种子确定性生成 count 个配置单（奇数序号规则型 / 偶数序号打分型）。

    **同 seed + 同台账 → 输出确定**（rules.md 第 11 章）：随机流只依赖
    (seed, 序号, 重采样次数)；与台账中任何组的已有配置（canonical_config
    规范化比对，extra_raw 合并去重）相同的，用同一随机流继续重采样，因此
    同一 seed 在同一台账状态下重新生成的全部字节逐位一致。已存在的文件
    不重写。
    ledger=None 时读仓库台账（生产路径）；自测传合成台账，绝不写台账。
    """
    rng = random.Random(seed)
    if ledger is None:
        ledger = read_ledger()
    seen, have, miss = existing_canonical_configs(ledger, extra_raw)
    if have or miss:
        print(f"[gen-monkey] seed={seed}：台账可比配置 {have}（缺 YAML {miss}），"
              f"按 rules.md 第 11 章规范化去重", flush=True)
    out_dir = Path(out_dir)
    names = monkey_names(seed, count)
    paths: list[Path] = []
    for i, name in enumerate(names, 1):
        for _attempt in range(GEN_MONKEY_MAX_ATTEMPTS):
            cfg = (make_rule_cfg(name, seed, rng) if i % 2 == 1
                   else make_score_cfg(name, seed, rng))
            canon = canonical_config(cfg)
            if canon not in seen:
                break
            # 与台账任何组已有配置重复：同一随机流继续重采样（rules.md 第 11 章）
        else:
            raise RuntimeError(
                f"gen-monkey: seed={seed} 第 {i} 个配置重采样 "
                f"{GEN_MONKEY_MAX_ATTEMPTS} 次仍与台账已有配置重复，拒绝放行")
        seen.add(canon)   # 本批内部同样不重复
        path = out_dir / f"{name}.yaml"
        if not path.exists():
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        paths.append(path)
    return paths, names


# ================================================================ 层判定编排（layers / farm 共用）

def _val_needed(ledger: pd.DataFrame, name: str,
                runs_dir: Path | None = None) -> bool:
    """验证期回测是否待跑：台账无该配置任何行，或验证期日收益产物缺失。"""
    return name not in known_config_names(ledger) or \
        not (run_dir_of(name, VALID_START, VALID_END, runs_dir)
             / "daily_returns.csv").exists()


def plan_l5_l6(ledger: pd.DataFrame, survivors: list[str],
               neighbor_dir: Path | None = None,
               runs_dir: Path | None = None) -> dict:
    """为 L1-4 幸存者规划 L5 邻居与 L6 验证期任务（写盘 YAML，返回待跑任务与判定计划）。

    group（rules.md 第 6 节，每次执行的必填属性）：邻居与验证期任务**继承其
    基础配置单的组**，组以台账 group 列为准；台账查不到该配置的组 → 规划失败
    （记入 plan[name]["error"]，绝不猜测）。判定不在此处做：任务跑完由调用方
    重读台账再判（台账为唯一事实来源）。
    邻域探针（名字含 __，rules.md 5.2 第 3.2 版）**不生成邻域**（杜绝二阶
    递归）：记入 plan[name]["skipped_probe"]，零任务。
    neighbor_dir / runs_dir：邻居 YAML 落盘目录与回测产物根目录（缺省 = 模块
    常量；自测注入临时目录用，不对 engine 模块做运行时补丁）。
    """
    ndir = Path(neighbor_dir) if neighbor_dir is not None else NEIGHBOR_DIR
    tasks: list[dict] = []
    plan: dict[str, dict] = {}
    known = known_config_names(ledger)
    for name in survivors:
        if is_probe(name):
            plan[name] = {"skipped_probe": True, "neighbors": [],
                          "note": "邻域探针不自判 L5、不生成自己的邻域（rules.md 5.2）"}
            continue
        src = find_config_yaml(name)
        if src is None:
            plan[name] = {"error": f"找不到原配置单 {name}.yaml"}
            continue
        grp = group_of_config(ledger, name)
        if grp is None:
            plan[name] = {"error": f"台账无 {name} 的 group 记录，无法继承组（rules.md 第 6 节）"}
            continue
        raw = yaml.safe_load(open(src, encoding="utf-8"))
        neigh = build_neighbor_set(raw)
        nb_names = [nb["name"] for nb in neigh]
        for nb in neigh:
            ensure_yaml(nb["raw"], ndir)
        todo = [nb for nb in neigh if nb["name"] not in known]
        tasks += [{"name": nb["name"], "path": str(ndir / f"{nb['name']}.yaml"),
                   "start": SEARCH_START, "end": SEARCH_END, "group": grp} for nb in todo]
        val_needed = _val_needed(ledger, name, runs_dir)
        plan[name] = {"neighbors": nb_names, "validation_needed": val_needed, "group": grp}
        if val_needed:
            tasks.append({"name": f"{name}__val", "path": str(src),
                          "start": VALID_START, "end": VALID_END, "group": grp})
    return {"tasks": tasks, "plan": plan}


def plan_validation(ledger: pd.DataFrame, survivors: list[str],
                    runs_dir: Path | None = None) -> list[dict]:
    """为 L1-4 幸存者规划**验证期回测**任务（试跑模式第 1 步，rules.md 第 10 章：
    先对全部幸存者跑验证期，才有入围分可排名）。组继承基础配置单的台账组；
    探针不参与；已有验证期产物的跳过（skip-existing 口径与 plan_l5_l6 一致）。"""
    tasks: list[dict] = []
    for name in survivors:
        if is_probe(name):
            continue
        grp = group_of_config(ledger, name)
        if grp is None:
            continue
        src = find_config_yaml(name)
        if src is None:
            continue
        if _val_needed(ledger, name, runs_dir):
            tasks.append({"name": f"{name}__val", "path": str(src),
                          "start": VALID_START, "end": VALID_END, "group": grp})
    return tasks


def _row_float(row: dict | None, key: str) -> float | None:
    """台账行数值列 → float（缺失/报错行 → None）。"""
    if row is None:
        return None
    v = str(row.get(key, "")).strip()
    if v in ("", "nan", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _score_from_rows(s: dict | None, v: dict | None, name: str) -> dict:
    """由搜索期/验证期两行台账算入围分要素（rules.md 5.4）。"""
    s_ok = s is not None and str(s.get("status", "")) == "ok"
    v_ok = v is not None and str(v.get("status", "")) == "ok"
    s_ex = _row_float(s, "ann_excess") if s_ok else None
    v_ex = _row_float(v, "ann_excess") if v_ok else None
    s_ir = _row_float(s, "ir") if s_ok else None
    v_ir = _row_float(v, "ir") if v_ok else None
    passed_l1 = _row_float(s, "funnel_l1") == 1.0
    hard = bool(passed_l1 and s_ex is not None and s_ex > 0
                and v_ex is not None and v_ex > 0)
    dd_worst = max(abs(_row_float(s, "excess_max_dd") or 1.0),
                   abs(_row_float(v, "excess_max_dd") or 1.0))
    return {"name": name, "passed_l1": passed_l1, "hard": hard,
            "search_ir": s_ir, "val_ir": v_ir, "search_ex": s_ex, "val_ex": v_ex,
            "dd_worst": dd_worst,
            "score": (min(s_ir, v_ir) if hard and s_ir is not None
                      and v_ir is not None else None)}


def entry_score(ledger: pd.DataFrame, name: str) -> dict:
    """单个候选的入围分要素（rules.md 5.4）：硬性资格 = 过 L1 且搜索期与
    验证期年化超额都 > 0；入围分 = min(搜索期 IR, 验证期 IR)；并列比较用
    两段中 |超额回撤| 较大者。不满足硬性资格 → score=None（不进入排名）。"""
    s = latest_rows_for(ledger, SEARCH_START, SEARCH_END).get(name)
    v = latest_rows_for(ledger, VALID_START, VALID_END).get(name)
    return _score_from_rows(s, v, name)


def trial_select(ledger: pd.DataFrame, survivors: list[str],
                 k: int = TRIAL_L5_TOP_K) -> tuple[list[str], dict[str, str], list[dict]]:
    """试跑模式（rules.md 第 10 章）：从 L1-4 幸存者中选出做 L5 的前 k 名。

    排名 = 硬性合格者按（入围分降序，|超额回撤|较大者升序，名字升序）取前 k；
    其余（含硬性不合格者——无入围分、本就不进排名）全部标注
    「未做邻域检验」（附原因）。返回 (top 名单, {name: 标注}, 全部要素行)。
    纯函数：只读台账，不跑回测、不写盘。
    """
    latest_s = latest_rows_for(ledger, SEARCH_START, SEARCH_END)
    latest_v = latest_rows_for(ledger, VALID_START, VALID_END)
    ranked = [_score_from_rows(latest_s.get(n), latest_v.get(n), n) for n in survivors]
    hq = sorted([r for r in ranked if r["hard"]],
                key=lambda r: (-r["score"], r["dd_worst"], r["name"]))
    top = [r["name"] for r in hq[:k]]
    rank_of = {r["name"]: i for i, r in enumerate(hq, 1)}
    deferred: dict[str, str] = {}
    for r in ranked:
        nm = r["name"]
        if nm in top:
            continue
        if r["hard"]:
            deferred[nm] = (f"{TAG_NO_L5_CHECK}（试跑：入围分排名 "
                            f"{rank_of[nm]}/{len(hq)}，未进前 {k}）")
        elif not r["passed_l1"]:
            deferred[nm] = f"{TAG_NO_L5_CHECK}（试跑：未过第 1 层，无入围分）"
        else:
            deferred[nm] = f"{TAG_NO_L5_CHECK}（试跑：两段年化超额未全 > 0，无入围分）"
    return top, deferred, ranked


# ================================================================ 子命令：layers

def run_layers(out_path: Path, formal: bool | None = None,
               workers: int | None = None) -> int:
    """对台账既有配置执行 L5~L8（rules.md 第 5/10/12 章）。

    formal=None → 模块默认（试跑开，TRIAL_MODE_DEFAULT）；--formal → 正式跑。
    试跑（rules.md 第 10 章）：先对全部 L1~L4 幸存者跑验证期回测 → 按入围分
    排名 → 只对每组前 TRIAL_L5_TOP_K 名生成邻域并判 L5；其余标注
    「未做邻域检验」，不得进入 final/达标。正式跑恢复对全部幸存者做邻域检验。
    workers=None → default_workers()（CPU − 2，rules.md 第 12 章）。
    """
    t0 = time.time()
    trial = resolve_trial_mode(formal)
    workers = default_workers() if workers is None else max(1, int(workers))
    mode_txt = (f"试跑（L5 只对每组入围分前 {TRIAL_L5_TOP_K} 名执行，--formal 恢复全量）"
                if trial else "正式（全量邻域检验）")
    print(f"[layers] 模式：{mode_txt}；workers={workers}", flush=True)
    ledger = read_ledger()
    latest = latest_search_rows(ledger)
    by_track: dict[str, list[str]] = {t: [] for t in TRACK_ORDER}
    other: list[str] = []
    for name, _row in latest.items():
        tr = config_track(ledger, name)
        if tr is None:
            other.append(name)
            continue
        by_track[tr].append(name)
    for tr in by_track:
        by_track[tr].sort()

    tracks_out: dict[str, dict] = {}
    l6_pool: list[dict] = []       # 全局 L7 候选（跨路）
    runner: SeqRunner | PoolRunner | None = None

    for tr in TRACK_ORDER:
        names = by_track.get(tr, [])
        if tr == "MS" and not names:
            continue               # 农场猴子未跑过时不输出该路
        lists = layer_lists(names, latest)   # 探针已在候选集中显式排除
        td = {**lists, "l5": [], "l6": [], "l7": [], "l8": [], "final": [],
              "l5_detail": {}, "l6_detail": {}, "l8_detail": {}, "l5_not_checked": []}
        if lists["l4"]:
            if runner is None:
                runner = make_runner(workers)   # rules.md 第 12 章：并行默认开
            res = execute_l5_l6_with_runner(runner, ledger, lists["l4"], formal=formal)
            td["l5"], td["l6"] = res["l5"], res["l6"]
            td["l5_detail"], td["l6_detail"] = res["l5_detail"], res["l6_detail"]
            td["l5_not_checked"] = res.get("l5_not_checked", [])
            ledger = read_ledger()
            # 探针防御性再过滤：l6_pool → L7 → L8 → final 整条链路不得含探针
            # （rules.md 5.2 第 3.2 版；上游 layer_lists 已排除，此处双保险）
            for name in res["l6"]:
                if is_probe(name):
                    continue
                l6_pool.append({"name": name, "track": tr,
                                "sharpe": _sharpe_of(latest, name)})
        tracks_out[tr] = td
    if runner is not None:
        runner.close()      # 常驻池排空回收（后续 L7/L8 不再回测）

    # ---- L7（全局贪心）与 L8 ----
    global_l7 = l7_dedup(l6_pool, {c["name"]: c["sharpe"] for c in l6_pool}) \
        if l6_pool else {"kept": [], "dropped": []}
    kept_names = [c["name"] for c in global_l7["kept"]]
    ledger = read_ledger()
    for c in global_l7["kept"]:
        tr = c["track"]
        det = l8_judge(ledger, c["name"])
        tracks_out[tr]["l7"].append(c["name"])
        tracks_out[tr]["l8_detail"][c["name"]] = det
        if det["pass"]:
            tracks_out[tr]["l8"].append(c["name"])
            tracks_out[tr]["final"].append(c["name"])
    # 说明：l7 名单 = L7 去重后仍保留者；被淘汰者记录在 global_l7.dropped

    # MS 路的 L7/L8 结果回写各 seed 农场 JSON（farm 只判到 L6，final 由 layers 置真）
    written_back = write_back_farm_jsons(tracks_out)
    if written_back:
        print(f"[layers] 已回写农场 JSON（l7/l8/final/l7_l8_evaluated）：{written_back}")

    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "n_trials_at_generation": _n_trials_snapshot(read_ledger()),
        "search_period": [SEARCH_START, SEARCH_END],
        "validation_period": [VALID_START, VALID_END],
        "trial_mode": trial,
        "workers": workers,
        "rules": {"l5_min_ratio": L5_MIN_RATIO, "l7_corr_threshold": L7_CORR_THRESHOLD,
                  "l8_dsr_min": L8_DSR_MIN, "l8_t_min": L8_T_MIN,
                  "trial_mode": trial, "trial_l5_top_k": TRIAL_L5_TOP_K if trial else None},
        "tracks": tracks_out,
        "global_l7": {"kept": kept_names,
                      "dropped": global_l7["dropped"]},
        "other_group_configs": sorted(other),
        "note": "l1~l4 从台账（搜索期最新行）读取；l5~l8 本命令执行判定；"
                "final = 过全部 8 层。展示分路按台账 group 列"
                "（config_track，rules.md 第 6 节），不认配置名前缀。"
                "L7 相关与 L8 DSR/t 值用日超额收益；"
                "N 按组（rules.md 第 6 节），见 n_trials_at_generation。"
                "邻域探针（名字含 __）照常落台账与计 N，但不进任何层的候选集、"
                "不自判 L5~L8、不生成自己的邻域、不参与入围排名"
                "（rules.md 5.2 第 3.2 版）。"
                + ("试跑模式（rules.md 第 10 章）：L5 只对每组入围分排名前 "
                   f"{TRIAL_L5_TOP_K} 的候选执行，其余标注「未做邻域检验」"
                   "（见各路 l5_not_checked），不得进入 final/达标；"
                   "试跑结论不得当作正式结果对外发布。"
                   if trial else ""),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(_jsonable(out), ensure_ascii=False, indent=1),
                        encoding="utf-8")

    for tr in TRACK_ORDER:
        if tr not in tracks_out:
            continue
        td = tracks_out[tr]
        print(f"TRACK_RESULT track={tr} l1={len(td['l1'])} l2={len(td['l2'])} "
              f"l3={len(td['l3'])} l4={len(td['l4'])} l5={len(td['l5'])} "
              f"l6={len(td['l6'])} l7={len(td['l7'])} l8={len(td['l8'])}")
    print(f"[layers] 写出 {out_path}（用时 {time.time()-t0:.1f}s）；"
          f"幸存（过全部8层）：{sum(len(t['final']) for t in tracks_out.values())}")
    return 0


def write_back_farm_jsons(tracks_out: dict) -> list[str]:
    """layers 执行完 L7/L8 后，把 MS 路结果回写到各 seed 的农场 JSON。

    farm 只判到 L6，其 JSON 的 final/l7/l8 恒空、l7_l8_evaluated=false；
    只有 layers 对该 seed 的配置执行过 L7/L8 后才回写：l7/l8/final 名单
    （按配置名 m<seed>_ 归属 seed）与 l7_l8_evaluated=true。「执行过」=
    该 seed 有配置进入 MS 路的 L6 幸存名单（含被 L7 淘汰者——此时回写空名单
    与 evaluated=true，如实记录「评过、零幸存」）。
    对应 seed 的农场 JSON 不存在时跳过（不创建假记录）。
    返回实际回写的文件路径列表。
    """
    ms = tracks_out.get("MS")
    if not ms:
        return []
    evaluated: set[int] = set()
    by_seed: dict[int, dict[str, list[str]]] = {}
    for key in ("l7", "l8", "final"):
        for name in ms.get(key, []):
            m = re.match(r"^m(\d+)_", str(name))
            if not m:
                continue
            seed = int(m.group(1))
            evaluated.add(seed)
            by_seed.setdefault(seed, {"l7": [], "l8": [], "final": []})[key].append(str(name))
    for name in ms.get("l6", []):
        m = re.match(r"^m(\d+)_", str(name))
        if m:
            evaluated.add(int(m.group(1)))
    written: list[str] = []
    for seed in sorted(evaluated):
        p = DATA_DIR / f"funnel_monkey_s{seed}.json"
        if not p.exists():
            continue
        j = json.loads(p.read_text(encoding="utf-8"))
        upd = by_seed.get(seed, {"l7": [], "l8": [], "final": []})
        j["l7"] = upd["l7"]
        j["l8"] = upd["l8"]
        j["final"] = upd["final"]
        j["l7_l8_evaluated"] = True
        p.write_text(json.dumps(_jsonable(j), ensure_ascii=False, indent=1),
                     encoding="utf-8")
        written.append(str(p))
    return written


def _n_trials_snapshot(ledger: pd.DataFrame) -> dict:
    """layers JSON 里的试验计数快照：total + 按组 N（rules.md 第 6 节）。"""
    groups: list[str] = []
    if len(ledger) and "group" in ledger.columns:
        groups = sorted({g for g in ledger["group"].astype(str) if g.strip()})
    return {"total": trials_n(ledger),
            "by_group": {g: n_trials_for(ledger, g) for g in groups}}


def execute_l5_l6_with_runner(runner, ledger: pd.DataFrame, survivors: list[str],
                              formal: bool | None = None,
                              read_ledger_fn=None,
                              neighbor_dir: Path | None = None,
                              runs_dir: Path | None = None) -> dict:
    """对一批 L1-4 幸存者执行 L5（邻域）与 L6（验证期）回测与判定。

    formal=None → 模块默认（试跑开）。两条路径：
      * 正式跑（--formal）：对全部幸存者规划邻居+验证期任务（原口径），
        跑完重读台账判 L5，再对 L5 过者判 L6。
      * 试跑（rules.md 第 10 章，默认）：① 先对**全部**幸存者跑验证期回测
        （入围分依赖验证期 IR）；② 按入围分 = min(搜索期 IR, 验证期 IR)
        排名（rules.md 5.4，trial_select）；③ 只对前 TRIAL_L5_TOP_K 名生成
        邻域并判 L5；其余在 l5_detail 标注「未做邻域检验」
        （not_checked=True）并进 l5_not_checked 名单——它们没有 L5 结论，
        永远不会进入 L6→L7→L8→final，不得称为达标。
    read_ledger_fn：台账重读函数（缺省 read_ledger）；自测注入合成台账用。
    neighbor_dir / runs_dir：邻居 YAML 与回测产物目录（自测注入）。
    以上皆为参数注入，不对 engine 模块做任何运行时补丁。
    探针在幸存者名单里会被显式剔除（防御性；layer_lists 已排除）。
    """
    if read_ledger_fn is None:
        read_ledger_fn = read_ledger
    if not survivors:
        return {"l5": [], "l6": [], "l5_detail": {}, "l6_detail": {},
                "l5_not_checked": []}
    survivors = [s for s in survivors if not is_probe(s)]
    if not survivors:
        return {"l5": [], "l6": [], "l5_detail": {}, "l6_detail": {},
                "l5_not_checked": []}
    trial = resolve_trial_mode(formal)

    if trial:
        # ① 全部幸存者的验证期回测（入围分 = min(搜索期 IR, 验证期 IR)，rules 5.4）
        val_tasks = plan_validation(ledger, survivors, runs_dir=runs_dir)
        if val_tasks:
            runner.run(val_tasks)
        ledger2 = read_ledger_fn()
        # ② 按入围分排名，取前 k
        top, deferred, _ranked = trial_select(ledger2, survivors, TRIAL_L5_TOP_K)
        # ③ 只对前 k 名生成邻域并判 L5
        planned = plan_l5_l6(ledger2, top, neighbor_dir=neighbor_dir, runs_dir=runs_dir)
        runner.run(planned["tasks"])
        latest3 = latest_search_rows(read_ledger_fn())
        l5_pass: list[str] = []
        l5_detail: dict[str, dict] = {}
        for name in survivors:
            if name in deferred:
                l5_detail[name] = {"pass": False, "not_checked": True,
                                   "note": deferred[name]}
                continue
            p = planned["plan"].get(name)
            if p is None or "error" in p:
                l5_detail[name] = {"pass": False,
                                   "note": p.get("error") if p else "未规划"}
                continue
            det = l5_judge(latest3, name, p["neighbors"])
            l5_detail[name] = det
            if det["pass"]:
                l5_pass.append(name)
        l6_pass: list[str] = []
        l6_detail: dict[str, dict] = {}
        ledger3 = read_ledger_fn()
        for name in l5_pass:
            det = l6_judge(ledger3, name)
            l6_detail[name] = det
            if det["pass"]:
                l6_pass.append(name)
        return {"l5": l5_pass, "l6": l6_pass, "l5_detail": l5_detail,
                "l6_detail": l6_detail,
                "l5_not_checked": sorted(deferred)}

    # ---- 正式跑：对全部幸存者做邻域检验（原口径）----
    planned = plan_l5_l6(ledger, survivors, neighbor_dir=neighbor_dir, runs_dir=runs_dir)
    runner.run(planned["tasks"])
    ledger2 = read_ledger_fn()
    latest2 = latest_search_rows(ledger2)
    l5_pass = []
    l5_detail = {}
    for name in survivors:
        p = planned["plan"].get(name)
        if p is None or "error" in p:
            l5_detail[name] = {"pass": False, "note": p.get("error") if p else "未规划"}
            continue
        det = l5_judge(latest2, name, p["neighbors"])
        l5_detail[name] = det
        if det["pass"]:
            l5_pass.append(name)
    l6_pass = []
    l6_detail = {}
    for name in l5_pass:
        det = l6_judge(ledger2, name)
        l6_detail[name] = det
        if det["pass"]:
            l6_pass.append(name)
    return {"l5": l5_pass, "l6": l6_pass, "l5_detail": l5_detail,
            "l6_detail": l6_detail, "l5_not_checked": []}


def _sharpe_of(latest: dict[str, dict], name: str) -> float:
    row = latest.get(name)
    v = str(row.get("sharpe", "")).strip() if row else ""
    try:
        return float(v)
    except ValueError:
        return float("-inf")


def _jsonable(o):
    """numpy 标量 → Python 原生类型（JSON 序列化）。"""
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not math.isfinite(float(o)) else float(o)
    if isinstance(o, float):
        return None if not math.isfinite(o) else o
    return o


# ================================================================ 子命令：farm

def run_farm(seed_lo: int, seed_hi: int, workers: int | None, count: int,
             formal: bool | None = None) -> int:
    """猴子批量：生成→回测→L1-4→L5→L6（rules.md 第 5/10/12 章）。

    formal=None → 模块默认（试跑开，TRIAL_MODE_DEFAULT）；--formal → 正式跑。
    L5/L6 一律委托 execute_l5_l6_with_runner——与 layers 完全同一条执行路径：
    试跑（rules.md 第 10 章）时先对全部 L1~L4 幸存者跑验证期回测、只对每组
    入围分前 TRIAL_L5_TOP_K 名生成邻域，其余标注「未做邻域检验」；正式跑恢复
    全量邻域检验。委托同时把池的生成次数从「每个幸存者一批」降到每 seed 至多
    两批（固定成本摊薄，rules.md 第 12 章）。
    """
    workers = default_workers() if workers is None else max(1, int(workers))
    trial = resolve_trial_mode(formal)
    mode_txt = (f"试跑（L5 只对每组入围分前 {TRIAL_L5_TOP_K} 名执行，--formal 恢复全量）"
                if trial else "正式（全量邻域检验）")
    print(f"[farm] workers={workers}（rules.md 第 12 章：默认 CPU−2，可 --workers 覆盖）；"
          f"模式：{mode_txt}", flush=True)
    runner = make_runner(workers)
    for s in range(seed_lo, seed_hi + 1):
        t0 = time.time()
        grp = f"monkey_{s}"        # rules.md 第 6 节：农场猴子 group = monkey_<种子>
        paths, names = gen_monkey(s, count, FARM_DIR)
        print(f"[farm] seed={s}：{count} 个配置单于 {FARM_DIR.relative_to(ROOT)}（group={grp}）",
              flush=True)
        ledger = read_ledger()
        pending = filter_pending(names, known_config_names(ledger))
        print(f"[farm] seed={s}：台账已有 {count - len(pending)}，待回测 {len(pending)}",
              flush=True)
        runner.run([{"name": n, "path": str(p), "start": SEARCH_START, "end": SEARCH_END,
                     "group": grp}
                    for n, p in zip(names, paths) if n in set(pending)])

        ledger = read_ledger()
        latest = latest_search_rows(ledger)
        lists = layer_lists(names, latest)
        # ---- L5 + L6：与 layers 同一条路径（试跑 top-30 / 正式全量；组继承台账列）----
        res = execute_l5_l6_with_runner(runner, ledger, lists["l4"], formal=formal)
        l5_pass, l6_pass = res["l5"], res["l6"]
        l5_detail, l6_detail = res["l5_detail"], res["l6_detail"]
        l5_not_checked = res.get("l5_not_checked", [])

        daily_paths = {}
        for n in names:
            entries = [str(run_dir_of(n, st, en).relative_to(ROOT) / "daily_returns.csv")
                       for st, en in ((SEARCH_START, SEARCH_END), (VALID_START, VALID_END))
                       if (run_dir_of(n, st, en) / "daily_returns.csv").exists()]
            if entries:
                daily_paths[n] = entries
        result = {
            "seed": int(s), "count": int(count),
            "dir": str(FARM_DIR.relative_to(ROOT)),
            "base": names, **lists,
            "l5": l5_pass, "l6": l6_pass,
            "l7": [], "l8": [], "final": [],
            "l7_l8_evaluated": False,
            "l5_detail": l5_detail, "l6_detail": l6_detail,
            "trial_mode": trial, "l5_not_checked": l5_not_checked,
            "daily_returns": daily_paths,
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "note": "farm 只判定到 L6；L7/L8 由 layers 对 MS 路统一执行。"
                    "L5/L6 经 execute_l5_l6_with_runner 与 layers 同口径。"
                    + ("试跑模式（rules.md 第 10 章）：L5 只对每组入围分前 "
                       f"{TRIAL_L5_TOP_K} 的候选执行，l5_not_checked 名单中的候选"
                       "标注「未做邻域检验」，不得称为达标。"
                       if trial else ""),
        }
        out = DATA_DIR / f"funnel_monkey_s{s}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(_jsonable(result), ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"SEED_RESULT seed={s} base={count} l1={len(lists['l1'])} "
              f"l2={len(lists['l2'])} l3={len(lists['l3'])} l4={len(lists['l4'])} "
              f"l5={len(l5_pass)} l6={len(l6_pass)} "
              f"l5_not_checked={len(l5_not_checked)}", flush=True)
        print(f"[farm] seed={s} 写出 {out.relative_to(ROOT)}（用时 {time.time()-t0:.0f}s）",
              flush=True)
    runner.close()
    print(f"FARM_DONE seeds={seed_lo}-{seed_hi}", flush=True)
    return 0


# ================================================================ 子命令：style

def fetch_industry_map(store=None) -> dict[str, str] | None:
    """行业映射（code → 申万一级行业名，取 raw 期末的最近归属）。

    来源 data/raw/index_member_all.parquet（rules.md 7.5 申万历史行业）；
    无数据返回 None（记录后继续）。
    """
    try:
        p = guard.RAW_DIR / "index_member_all.parquet"
        if not guard.exists(p):
            return None
        ind = guard.read_parquet(p)
        from prices import _norm_date_col, industry_intervals, _interval_value
        ind = ind[ind["l1_code"].notna() & (ind["l1_code"].astype(str).str.len() > 0)]
        if ind.empty:
            return None
        end_day = str(_norm_date_col(guard.read_parquet(
            guard.RAW_DIR / "trade_cal.parquet")["cal_date"]).max())
        codes = ind["ts_code"].drop_duplicates().to_numpy(dtype=object)
        qdates = np.full(len(codes), end_day, dtype=object)
        _, names = _interval_value(codes, qdates, industry_intervals(ind), 3, 2)
        return {str(c): (str(v) if v is not None else "未知")
                for c, v in zip(codes, names)}
    except Exception:  # noqa: BLE001
        return None


def etf_return_series(symbol: str, store=None) -> pd.Series | None:
    """ETF 日收益（close_adj = close × fund_adj.adj_factor 的日收益，复权口径）。"""
    if store is not None and symbol in store.etfs:
        d = store.etfs[symbol]
        return pd.Series(d["ret"].to_numpy(), index=d["date"].to_numpy(), dtype="float64")
    p = guard.RAW_DIR / "fund_daily.parquet"
    if not guard.exists(p):
        return None
    fd = guard.read_parquet(p)
    fa = guard.read_parquet(guard.RAW_DIR / "fund_adj.parquet")
    from prices import _norm_date_col
    for df in (fd, fa):
        df["trade_date"] = _norm_date_col(df["trade_date"])
    d = fd[fd["ts_code"] == symbol].merge(
        fa[fa["ts_code"] == symbol][["trade_date", "adj_factor"]],
        on="trade_date", how="inner").sort_values("trade_date")
    if d.empty:
        return None
    close_adj = d["close"].astype(float) * d["adj_factor"].astype(float)
    r = close_adj.pct_change()
    return pd.Series(r.to_numpy(), index=d["trade_date"].astype(str), dtype="float64")


def industry_stats(name: str, ind_map: dict[str, str] | None) -> dict:
    """持仓行业集中度：以买入成交日为「调仓日」，权重 = 当日各笔 gross 占比，
    聚合到行业后算 HHI = Σ w² 与最大行业权重，再对调仓日取时间平均。"""
    if ind_map is None:
        return {"available": False, "note": "行业数据不可用"}
    frames = []
    for s, e in ((SEARCH_START, SEARCH_END), (VALID_START, VALID_END)):
        p = run_dir_of(name, s, e) / "trades.parquet"
        if p.exists():
            t = guard.read_parquet(p)
            t = t[t["side"] == "buy"]
            if len(t):
                frames.append(t[["exec_date", "code", "gross"]])
    if not frames:
        return {"available": False, "note": "无交易明细"}
    t = pd.concat(frames, ignore_index=True)
    t["industry"] = t["code"].astype(str).map(ind_map).fillna("未知")
    hhis, maxws = [], []
    for _, g in t.groupby("exec_date"):
        w = g.groupby("industry")["gross"].sum()
        tot = float(w.sum())
        if tot <= 0:
            continue
        w = w / tot
        hhis.append(float((w ** 2).sum()))
        maxws.append(float(w.max()))
    if not hhis:
        return {"available": False, "note": "无有效调仓日"}
    return {"available": True, "n_rebalance_days": len(hhis),
            "hhi_avg": float(np.mean(hhis)), "max_industry_weight_avg": float(np.mean(maxws))}


def final_survivors() -> list[dict]:
    """过全部 8 层的最终幸存者（按配置名去重）：layers JSON 各路 final +
    农场 JSON 中 l7_l8_evaluated=True 的 final（farm 本身只判到 L6，
    l7_l8_evaluated=false 的不计入）。

    去重是必须的：layers 会把 MS 路结果回写进农场 JSON（write_back_farm_jsons），
    回写后两来源携带同一批 m<seed>_* 名字；同名以 layers JSON 的记录为准
    （layers 是判定方，先收集），farm 来源只补充 layers JSON 未覆盖的名字。
    """
    out: list[dict] = []
    seen: set[str] = set()
    if LAYERS_JSON.exists():
        j = json.loads(LAYERS_JSON.read_text(encoding="utf-8"))
        for tr, td in j.get("tracks", {}).items():
            for name in td.get("final", []):
                name = str(name)
                if name not in seen:
                    seen.add(name)
                    out.append({"config": name, "track": tr})
    for p in sorted(DATA_DIR.glob("funnel_monkey_s*.json")):
        j = json.loads(p.read_text(encoding="utf-8"))
        if j.get("l7_l8_evaluated"):
            for name in j.get("final", []):
                name = str(name)
                if name not in seen:
                    seen.add(name)
                    out.append({"config": name,
                                "track": f"monkey_seed{j.get('seed')}"})
    return out


def run_style() -> int:
    finals = final_survivors()
    if not finals:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STYLE_JSON.write_text(json.dumps(_jsonable({
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "survivors": [],
            "note": "当前无过全部 8 层的幸存策略",
        }), ensure_ascii=False, indent=1), encoding="utf-8")
        print("NO_SURVIVORS")
        return 0

    r500 = etf_return_series("510500.SH")
    r300 = etf_return_series("510300.SH")
    if r500 is None or r300 is None:
        raise RuntimeError("缺少 ETF 数据（data/raw/fund_daily|fund_adj.parquet）")
    etf_diff = r500 - r300     # 中证500 日收益 − 沪深300 日收益

    ind_map = fetch_industry_map()
    if ind_map is None:
        print("[style] 行业数据不可用（index_member_all 缺失），行业体检记为不可用",
              flush=True)

    survivors_out = []
    for f in finals:
        name = f["config"]
        df = load_daily_merged(name)
        entry: dict = {"config": name, "track": f["track"]}
        if df is None or len(df) < 3:
            entry["excess_style"] = {"available": False, "note": "无合并日收益"}
        else:
            ex = pd.Series((df["strategy_ret"] - df["benchmark_ret"]).to_numpy(),
                           index=df["date"].to_numpy(), dtype="float64")
            lo, hi = df["date"].min(), df["date"].max()
            diff = etf_diff[(etf_diff.index >= lo) & (etf_diff.index <= hi)]
            entry["excess_style"] = {
                "available": True,
                "region": f"{lo}~{hi}", "n_days": int(len(df)),
                "corr_excess_vs_500_minus_300": pearson_corr(ex, diff),
            }
        entry["industry"] = industry_stats(name, ind_map)
        survivors_out.append(entry)
        print(f"[style] {name}（{f['track']}）：corr="
              f"{entry.get('excess_style', {}).get('corr_excess_vs_500_minus_300')}, "
              f"industry={'OK' if entry['industry'].get('available') else '不可用'}",
              flush=True)

    STYLE_JSON.write_text(json.dumps(_jsonable({
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "industry_data_available": ind_map is not None,
        "survivors": survivors_out,
        "note": "(a) 日超额=策略日收益−基准日收益（各自 daily_returns.csv），"
                "与 sh510500−sh510300 日收益的相关，区间=该策略搜索期+验证期；"
                "(b) 行业集中度以买入成交日为调仓日、gross 占比为权重",
    }), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[style] 写出 {STYLE_JSON.relative_to(ROOT)}（{len(survivors_out)} 个幸存者）")
    return 0


# ================================================================ 子命令：report

def run_report() -> int:
    ledger = read_ledger()
    latest = latest_search_rows(ledger)
    gen_date = datetime.now().strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append("# 漏斗汇总（funnel_summary）")
    lines.append("")
    lines.append(f"- 生成日期：{gen_date}")
    lines.append(f"- 台账：`ledger/ledger.csv`，当前 **{trials_n(ledger)}** 行；"
                 f"试验总数 N 按组计算（rules.md 第 6 节）：AI = group∈{{A,B}} 全部行数，"
                 f"每只猴子 = 自己组全部行数，example/test 不计入任何组")
    lines.append(f"- 搜索期 {SEARCH_START}~{SEARCH_END}（L1~L5、L7/L8 的搜索段）；"
                 f"验证期 {VALID_START}~{VALID_END}（仅 L6）")
    lines.append("")

    # ---- ① 三列并排漏斗表 ----
    layers = None
    if LAYERS_JSON.exists():
        layers = json.loads(LAYERS_JSON.read_text(encoding="utf-8"))
    def ledger_cum(track_prefix: str) -> dict[str, int]:
        names = sorted(n for n in latest if config_track(ledger, n) == track_prefix)
        ll = layer_lists(names, latest)
        return {k: len(v) for k, v in ll.items()}

    lines.append("## ① 三路漏斗（每层剩余数量）")
    lines.append("")
    lines.append(f"| 层 | A | B | 猴子 seed{MAIN_MONKEY_SEED} |")
    lines.append("|---|---|---|---|")
    for li in range(1, 9):
        row = [f"L{li}"]
        for tr in ("A", "B", "MONKEY"):
            if li <= 4:
                row.append(str(ledger_cum(tr).get(f"l{li}", 0)))
            elif layers is not None and tr in layers.get("tracks", {}):
                row.append(str(len(layers["tracks"][tr].get(f"l{li}", []))))
            else:
                row.append("—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("说明：L1~L4 由回测引擎判定并落台账（搜索期最新行，此处从台账统计；"
                 f"归属路按台账 group 列，A=group A、B=group B、"
                 f"猴子 seed{MAIN_MONKEY_SEED}=group monkey_{MAIN_MONKEY_SEED}，"
                 "不认配置名前缀）；L5~L8 由 `engine/funnel.py layers` "
                 "执行（结果取 `data/funnel_layers.json`）。— = layers 尚未运行。")
    lines.append("")
    if layers is not None and layers.get("trial_mode"):
        lines.append(f"**试跑模式**（rules.md 第 10 章）：第 5 层邻域检验只对每组入围分"
                     f"排名前 {layers.get('rules', {}).get('trial_l5_top_k', TRIAL_L5_TOP_K)}"
                     " 的候选执行；下列候选**未做邻域检验**，不得称为达标"
                     "（试跑结论不得当作正式结果对外发布）：")
        for tr, td in layers.get("tracks", {}).items():
            n_nc = len(td.get("l5_not_checked", []) or [])
            if n_nc:
                lines.append(f"- {tr} 路：{n_nc} 个未做邻域检验")
        lines.append("")

    # ---- ② 20 只种子猴子分布表 ----
    lines.append("## ② 种子猴子分布（farm --seeds）")
    lines.append("")
    farm_files = sorted(DATA_DIR.glob("funnel_monkey_s*.json"),
                        key=lambda p: int(p.stem.split("_s")[-1]))
    if farm_files:
        lines.append("| seed | base | L1 | L2 | L3 | L4 | L5 | L6 | 最终幸存 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for p in farm_files:
            j = json.loads(p.read_text(encoding="utf-8"))
            lines.append(
                f"| {j['seed']} | {len(j.get('base', []))} | {len(j.get('l1', []))} | "
                f"{len(j.get('l2', []))} | {len(j.get('l3', []))} | {len(j.get('l4', []))} | "
                f"{len(j.get('l5', []))} | {len(j.get('l6', []))} | "
                f"{len(j.get('final', []))} |")
        n_farm = len(farm_files)
        lines.append("")
        tie_note = ("（当前台账中仅有以上 seed 的农场结果；"
                    if n_farm < 20 else
                    "（20 只种子全部完成；")
        lines.append(tie_note + f"farm JSON 共 {n_farm} 份）")
    else:
        lines.append("尚未运行任何 `farm --seeds`（无 `data/funnel_monkey_s*.json`）。")
    lines.append("")

    # ---- ③ A 的最终幸存数在猴子中的排名 ----
    lines.append("## ③ A 路最终幸存数 vs 种子猴子")
    lines.append("")
    a_final = 0
    if layers is not None:
        a_final = len(layers.get("tracks", {}).get("A", {}).get("final", []))
    monkey_finals = []
    for p in farm_files:
        j = json.loads(p.read_text(encoding="utf-8"))
        monkey_finals.append((int(j["seed"]), len(j.get("final", []))))
    if monkey_finals:
        n_better = sum(1 for _, c in monkey_finals if c > a_final)
        n_tie = sum(1 for _, c in monkey_finals if c == a_final)
        lines.append(
            f"A 路最终幸存数 = {a_final}；在 {len(monkey_finals)} 只已跑种子的最终幸存数中"
            f"排第 **{n_better + 1}**（{n_better} 只严格更高，{n_tie} 只与 A 同值并列）。")
    else:
        lines.append(f"A 路最终幸存数 = {a_final}；尚无种子猴子 farm 结果可比较。")
    lines.append("")

    # ---- ④ 风格体检 ----
    lines.append("## ④ 幸存策略风格体检")
    lines.append("")
    if STYLE_JSON.exists():
        sj = json.loads(STYLE_JSON.read_text(encoding="utf-8"))
        sv = sj.get("survivors", [])
        if not sv:
            lines.append("无过全部 8 层的幸存策略（`data/funnel_style.json`：survivors=[]）。")
        else:
            lines.append("| 策略 | 路 | 超额 vs (500−300) 相关 | 区间 | 行业HHI均值 | 最大行业权重均值 |")
            lines.append("|---|---|---|---|---|---|")
            for s in sv:
                es = s.get("excess_style", {})
                ind = s.get("industry", {})
                lines.append(
                    f"| {s['config']} | {s['track']} | "
                    f"{es.get('corr_excess_vs_500_minus_300') if es.get('available') else '不可用'} | "
                    f"{es.get('region', '') if es.get('available') else ''} | "
                    f"{ind.get('hhi_avg') if ind.get('available') else ind.get('note', '不可用')} | "
                    f"{ind.get('max_industry_weight_avg') if ind.get('available') else ''} |")
    else:
        lines.append("`engine/funnel.py style --all` 尚未运行。")
    lines.append("")

    # ---- ⑤ 口径 ----
    lines.append("## ⑤ 口径")
    lines.append("")
    _n_snap = layers.get("n_trials_at_generation") if layers else None
    if isinstance(_n_snap, dict):
        _n_txt = (f"total={_n_snap.get('total')}，按组 N={_n_snap.get('by_group')}")
    elif _n_snap is not None:
        _n_txt = str(_n_snap)
    else:
        _n_txt = "（layers 未运行）"
    lines.append(f"- **试验总数 N**（rules.md 第 6 节，按组）：本次 report 读取台账 "
                 f"{trials_n(ledger)} 行；layers 运行时记录：{_n_txt}。"
                 f"AI 的 N = group∈{{A,B}} 全部行数；每只猴子 N = 自己组全部行数；"
                 f"example/test 不计入任何组。")
    lines.append("- **L1**：交易 ≥ 100 笔，买入和卖出各算一笔；打分型按调仓频率分档——"
                 "**周度 ≥ 300 期、月度 ≥ 80 期**（rules.md 5.2，3.4 修订版）。")
    lines.append(f"- **L3（第 3 版）**：信息比率 > 0.4 且超额最大回撤 < 30%（严格不等）。")
    lines.append("- **L4（3.4 修订版）**：9 个完整年份里至少 **6 年**年度超额 > 0。"
                 "打分型报告须注明中性化口径（rules.md 7.5）：引擎已把生效口径"
                 "（行业内秩 / 市值档内秩两个独立开关）写入每个 run 目录 summary.json"
                 " 的 neutralization 字段。")
    lines.append("- **L5**：每个参数在其档位序列（rules.md 第 7 节）上/下各挪一档，"
                 "每次只动一个参数；全部邻居回测落台账；邻居连过 L1~4 比例 ≥ 70% 通过；"
                 "端点单侧邻居；dir/order 与零件本身不挪；打分型持仓数固定 30 无邻域。"
                 "邻域变体（名字含 __）是探针不是策略（rules.md 5.2 第 3.2 版）："
                 "照常落台账与计 N，但不自判 L5~L8、不生成自己的邻域、不参与入围排名。")
    lines.append("- **L6**：验证期 2023-01-01~2024-12-31，扣成本年化超额 > 0（与 L2 同口径，"
                 "ann_excess = 策略年化 − 基准年化）。")
    lines.append("- **L7**：幸存者两两合并（搜索期+验证期、按日期对齐）**日超额收益**"
                 "（策略日收益 − 基准日收益）Pearson 相关，r ≥ 0.7 视为同类；"
                 "按台账搜索期夏普（参考口径）降序贪心，与全部已保留者都 < 0.7 才保留。")
    lines.append("- **L8（DSR, Bailey & López de Prado 2014；全部基于日超额收益）**：")
    lines.append("  - SR₀ = √V[SR] · [(1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e))]，"
                 "γ = 0.5772（Euler–Mascheroni），V[SR] = **同组** ok 行 ir/√250 的样本方差"
                 "（对信息比率做多重检验折扣）。")
    lines.append("  - DSR = Φ[(SR−SR₀)·√((T−1)/(1−γ₃·SR+(γ₄−1)/4·SR²))]，"
                 "SR 为日超额均值/日超额标准差（未年化），γ₃/γ₄ 为超额序列的偏度/峰度"
                 "（总体矩，峰度正态=3），T = 合并日超额样本数。")
    lines.append("  - t 值：t = 超额均值/(超额标准差(ddof=1)/√T)。DSR > 0.95 且 t ≥ 3 通过。")
    lines.append("  - N 按组：AI = group∈{A,B} 台账全部行数；每只猴子 = 自己组全部行数；"
                 "分组以台账 group 列为准。")
    lines.append("- **参考指标**：策略自身夏普与绝对最大回撤照常计算并记台账，"
                 "只作参考、不作门槛（rules.md 第 5.2 节）；绝对回撤由组合层管。")
    lines.append("- **基准**：股票池当日可交易非 ST 成分等权、扣成本（引擎口径，"
                 "见 notes/engine_design.md §5.6）。")
    lines.append("- **复现命令**：")
    lines.append("  - `.venv/Scripts/python.exe engine/funnel.py selftest`")
    lines.append("  - `.venv/Scripts/python.exe engine/funnel.py layers --out data/funnel_layers.json`")
    lines.append("  - `.venv/Scripts/python.exe engine/funnel.py gen-monkey --seed 99 --count 200 --out strategies/monkey_farm`")
    lines.append(f"  - `.venv/Scripts/python.exe engine/funnel.py farm --seeds {MAIN_MONKEY_SEED}-{MAIN_MONKEY_SEED + 19} --workers 4 --count 200`")
    lines.append("  - `.venv/Scripts/python.exe engine/funnel.py style --all`")
    lines.append("  - `.venv/Scripts/python.exe engine/funnel.py report`")
    lines.append("")
    lines.append("本报告只陈述事实与口径，不含任何投资建议。")

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] 写出 {REPORT_MD.relative_to(ROOT)}")
    return 0


# ================================================================ 子命令：selftest

def selftest_l5_neighborhood() -> bool:
    """邻域展开：参数个数、每次只动一个参数、端点单侧、负百分比保持符号。"""
    ok = True
    raw = {
        "name": "st_cfg", "type": "rule",
        "buy": [{"op": "ret_n", "n": 20, "dir": "above", "threshold": 3.0},
                {"op": "close_over_ma_n", "n": 60, "dir": "above", "threshold": 1.0},
                {"op": "vol_ratio_n", "n": 5, "dir": "above", "threshold": 1.2}],
        "sell": [{"op": "close_over_ma_n", "n": 20, "dir": "below", "threshold": 1.0}],
        "rank": {"op": "ret_n", "n": 5, "order": "desc"},
        "max_hold_days": 10, "stop_loss": "8%", "max_positions": 10,
    }
    params = enumerate_params(raw)
    ok &= _assert("邻域：参数个数=11（8 条件项+rankn+hold+stop）", len(params) == 11,
                  f"得到 {len(params)}")
    neigh = build_neighbor_set(raw)
    ok &= _assert("邻域：11 个中位参数 × 2 = 22 个邻居", len(neigh) == 22,
                  f"得到 {len(neigh)}")
    base = copy.deepcopy(raw)
    all_diff_one = True
    for nb in neigh:
        diffs = _diff_fields(base, nb["raw"])
        if len(diffs) != 2 or "name" not in diffs:   # name + 恰一个参数
            all_diff_one = False
    ok &= _assert("邻域：每个邻居与原配置恰差一个字段(+name)", all_diff_one)
    # 端点单侧
    def n_neigh(**over):
        r = copy.deepcopy(raw)
        r.update(over)
        return build_neighbor_set(r)

    w3 = [p for p in enumerate_params({**raw, "buy": [{"op": "ret_n", "n": 3,
                                                       "dir": "above", "threshold": 3.0}]})
          if p["tag"] == "buy0n"][0]
    ok &= _assert("邻域：窗口 3 只有上邻（→5）",
                  param_neighbors(w3) == [("u", 5)], f"{param_neighbors(w3)}")
    w250 = [p for p in enumerate_params({**raw, "buy": [{"op": "ret_n", "n": 250,
                                                         "dir": "above", "threshold": 3.0}]})
            if p["tag"] == "buy0n"][0]
    ok &= _assert("邻域：窗口 250 只有下邻（→120）",
                  param_neighbors(w250) == [("d", 120)], f"{param_neighbors(w250)}")
    neg = [p for p in enumerate_params({**raw, "sell": [{"op": "ret_n", "n": 3,
                                                         "dir": "below", "threshold": -5.0}]})
           if p["tag"] == "sell0t"][0]
    ok &= _assert("邻域：负阈值 -5% → 上邻 -8% / 下邻 -3%（符号保持）",
                  param_neighbors(neg) == [("u", -8.0), ("d", -3.0)],
                  f"{param_neighbors(neg)}")
    p15 = [p for p in enumerate_params({**raw, "buy": [{"op": "ret_n", "n": 3,
                                                        "dir": "above", "threshold": 15.0}]})
           if p["tag"] == "buy0t"][0]
    ok &= _assert("邻域：百分比 15% 只有下邻（→10%）",
                  param_neighbors(p15) == [("d", 10.0)], f"{param_neighbors(p15)}")
    stop0 = [p for p in enumerate_params({**raw, "stop_loss": "无"}) if p["tag"] == "stop"][0]
    ok &= _assert("邻域：止损「无」只有上邻（→5%）",
                  param_neighbors(stop0) == [("u", "5%")], f"{param_neighbors(stop0)}")
    stop10 = [p for p in enumerate_params({**raw, "stop_loss": "10%"}) if p["tag"] == "stop"][0]
    ok &= _assert("邻域：止损 10% 只有下邻（→8%）",
                  param_neighbors(stop10) == [("d", "8%")], f"{param_neighbors(stop10)}")
    h3 = [p for p in enumerate_params({**raw, "max_hold_days": 3}) if p["tag"] == "hold"][0]
    ok &= _assert("邻域：持有天数 3 只有上邻（→5）",
                  param_neighbors(h3) == [("u", 5)], f"{param_neighbors(h3)}")
    # 零参数（打分型全无窗口零件）→ 空邻域
    score0 = {"name": "sc0", "type": "score",
              "factors": [{"op": "turn", "weight": 1.0}, {"op": "streak_up", "weight": -0.5}],
              "holdings": 30, "rebalance": "weekly_first_trade_day"}
    ok &= _assert("邻域：无窗口打分型 0 参数 → 空邻域", build_neighbor_set(score0) == [])
    # dir/order/op 不挪：邻居字段差里不含 dir/order/op/weight/holdings
    bad = [nb for nb in neigh
           if any(k in ("dir", "order", "op", "weight", "holdings", "max_positions")
                  for k in _diff_fields(base, nb["raw"]))]
    ok &= _assert("邻域：dir/order/op/weight 不作为参数挪动", not bad)
    return ok


def _diff_fields(a: dict, b: dict, prefix: str = "") -> set[str]:
    out = set()
    for k in set(a) | set(b):
        va, vb = a.get(k), b.get(k)
        if isinstance(va, list) and isinstance(vb, list):
            for i in range(max(len(va), len(vb))):
                sa = va[i] if i < len(va) else {}
                sb = vb[i] if i < len(vb) else {}
                out |= _diff_fields(sa if isinstance(sa, dict) else {"_": sa},
                                    sb if isinstance(sb, dict) else {"_": sb},
                                    f"{prefix}{k}[{i}].")
        elif isinstance(va, dict) and isinstance(vb, dict):
            out |= _diff_fields(va, vb, f"{prefix}{k}.")
        elif va != vb:
            out.add(f"{prefix}{k}")
    return out


def selftest_l7() -> bool:
    """L7 贪心（第 2 版：相关用**日超额收益**）：高相关的两只保留夏普高者；
    低相关的都保留；共同基准分量被扣除后，原始收益高相关者不再同类。"""
    ok = True
    rng = np.random.default_rng(7)
    mkt = rng.normal(0, 0.01, 500)
    dates = [f"20{i:02d}-01-01" for i in range(500)]  # 仅作索引标签
    a = pd.Series(mkt + rng.normal(0, 0.002, 500), index=dates)
    b = pd.Series(mkt + rng.normal(0, 0.002, 500), index=dates)   # 与 a 高相关
    c = pd.Series(rng.normal(0, 0.01, 500), index=dates)          # 与两者近独立
    sharpe = {"low_corr_dup": 0.5, "high_corr_dup": 1.5, "indep": 0.2}

    def fake(name):
        s = {"low_corr_dup": a, "high_corr_dup": b, "indep": c}[name]
        return pd.DataFrame({"date": s.index, "strategy_ret": s.to_numpy(),
                             "benchmark_ret": np.zeros(len(s)),
                             "excess": s.to_numpy()})

    if True:
        res = l7_dedup([{"name": n, "track": "T"} for n in sharpe], sharpe,
                       loader=fake)
        kept = sorted(x["name"] for x in res["kept"])
        ok &= _assert("L7：保留高夏普者与独立者",
                      kept == ["high_corr_dup", "indep"], f"kept={kept}")
        ok &= _assert("L7：低夏普高相关者被淘汰",
                      [d["name"] for d in res["dropped"]] == ["low_corr_dup"],
                      f"dropped={res['dropped']}")
        ok &= _assert("L7：淘汰记录给出相关对象",
                      res["dropped"][0]["corr_with"] == "high_corr_dup"
                      and res["dropped"][0]["corr"] >= 0.7)
        ok &= _assert("L7 已知答案：corr(a,b)>=0.7、corr(a,c)<0.7",
                      pearson_corr(a, b) >= 0.7 and pearson_corr(a, c) < 0.7)

        # ---- 语义：相关用日超额（策略 − 基准）----
        # 两只原始收益完全相同的策略，若基准也完全相同，超额序列一条为 0、
        # 一条有方差 → 方差为 0 的一方按口径记相关 0.0，不再判同类。
        dup = pd.Series(mkt, index=dates)
        bench_same = pd.Series(mkt, index=dates)

        def fake_ex(name):
            s = {"dup1": dup, "dup2": dup}[name]
            bm = {"dup1": bench_same, "dup2": pd.Series(np.zeros(len(dates)), index=dates)}[name]
            return pd.DataFrame({"date": dates, "strategy_ret": s.to_numpy(),
                                 "benchmark_ret": bm.to_numpy(),
                                 "excess": (s - bm).to_numpy()})

        res2 = l7_dedup([{"name": "dup1", "track": "T"}, {"name": "dup2", "track": "T"}],
                        {"dup1": 1.0, "dup2": 0.9}, loader=fake_ex)
        ok &= _assert("L7 v2：相关用日超额——超额序列不同（一方零方差）不再判同类",
                      sorted(x["name"] for x in res2["kept"]) == ["dup1", "dup2"],
                      f"kept={res2['kept']}, dropped={res2['dropped']}")
        # 反证：同一对策略、用原始收益（超额=原收益，基准=0）时必然判同类淘汰一方
        res3 = l7_dedup([{"name": "high_corr_dup", "track": "T"},
                         {"name": "low_corr_dup", "track": "T"}],
                        {"high_corr_dup": 1.5, "low_corr_dup": 1.4}, loader=fake)
        ok &= _assert("L7 对照：超额=原收益（基准 0）时同类仍淘汰低夏普者",
                      sorted(x["name"] for x in res3["kept"]) == ["high_corr_dup"],
                      f"kept={res3['kept']}")
    return ok


def selftest_dsr() -> bool:
    """DSR 三条性质：SR↑⇒DSR↑；N↑⇒DSR↓；SR=0⇒DSR<0.5。"""
    ok = True
    from scipy.stats import kurtosis, skew
    rng = np.random.default_rng(11)
    r = rng.normal(0.0002, 0.01, 1200)

    def dsr_of(rr, n_trials=800):
        sd = float(np.std(rr, ddof=1))
        sr = float(np.mean(rr)) / sd
        v = 0.0004
        return dsr_compute(sr, v, n_trials, float(skew(rr, bias=True)),
                           float(kurtosis(rr, fisher=False, bias=True)), len(rr))["dsr"]

    d1 = dsr_of(r)
    d2 = dsr_of(r + 0.0005)
    ok &= _assert("DSR：SR 越大 DSR 越大", d2 > d1, f"{d1} vs {d2}")
    d3 = dsr_of(r, n_trials=50)
    d4 = dsr_of(r, n_trials=5000)
    ok &= _assert("DSR：N 越大 DSR 越小", d3 > d4, f"{d3} vs {d4}")
    r0 = r - r.mean()
    d5 = dsr_of(r0)
    ok &= _assert("DSR：SR=0 时 DSR<0.5", d5 < 0.5, f"{d5}")
    # t 值已知答案：x=[1,2,3,4] → mean=2.5, sd=√(5/3), t = 2.5/(sd/√4) = √15
    x = np.array([1.0, 2.0, 3.0, 4.0])
    t = float(np.mean(x)) / (float(np.std(x, ddof=1)) / math.sqrt(len(x)))
    ok &= _assert("t 值：已知答案 √15", abs(t - math.sqrt(15)) < 1e-12, f"t={t}")
    return ok


def selftest_l14_and_skip() -> bool:
    """L1-4 判据从合成台账反算一致（3.4 修订版口径：L1 按调仓频率分档、L4 ≥6 年）；
    层累计名单；skip-existing；按组 N。"""
    ok = True

    def row(ts, cfg, status, *, group="A", n_trades="", ann_excess="", sharpe="",
            max_dd="", ir="", excess_max_dd="", beat_years="", total_years="",
            l1="", l2="", l3="", l4="", start=SEARCH_START, end=SEARCH_END,
            typ="rule"):
        return {"ts": ts, "config": cfg, "group": group, "type": typ, "start": start,
                "end": end, "status": status, "n_trades": n_trades,
                "ann_ret": "", "bench_ann_ret": "", "ann_excess": ann_excess,
                "sharpe": sharpe, "max_dd": max_dd, "ir": ir,
                "excess_max_dd": excess_max_dd, "beat_years": beat_years,
                "total_years": total_years,
                "funnel_l1": l1, "funnel_l2": l2, "funnel_l3": l3, "funnel_l4": l4,
                "note": ""}

    rows = [
        # x1: 全过（两行同名，取最新）
        row("2026-01-01T00:00:00Z", "x1", "ok", n_trades="150", ann_excess="0.05",
            sharpe="1.2", max_dd="-0.10", ir="1.2", excess_max_dd="-0.10",
            beat_years="6", total_years="7", l1="1", l2="1", l3="1", l4="1"),
        row("2026-01-02T00:00:00Z", "x1", "ok", n_trades="150", ann_excess="0.05",
            sharpe="1.2", max_dd="-0.10", ir="1.2", excess_max_dd="-0.10",
            beat_years="6", total_years="7", l1="1", l2="1", l3="1", l4="1"),
        # x2: 只过 L1
        row("2026-01-01T00:00:00Z", "x2", "ok", n_trades="150", ann_excess="-0.01",
            sharpe="0.3", max_dd="-0.30", ir="0.1", excess_max_dd="-0.30",
            beat_years="2", total_years="7", l1="1", l2="0", l3="0", l4="0"),
        # x3: 报错行（无漏斗标记）
        row("2026-01-01T00:00:00Z", "x3", "error_runtime"),
        # y1: 验证期行（不进搜索期名单）
        row("2026-01-01T00:00:00Z", "y1", "ok", start=VALID_START, end=VALID_END,
            n_trades="120", ann_excess="0.02", sharpe="1.0", max_dd="-0.05",
            ir="1.0", excess_max_dd="-0.05", beat_years="2", total_years="2",
            l1="1", l2="1", l3="1", l4="1"),
        # x4: 只差 L4
        row("2026-01-01T00:00:00Z", "x4", "ok", n_trades="150", ann_excess="0.05",
            sharpe="1.2", max_dd="-0.10", ir="1.2", excess_max_dd="-0.10",
            beat_years="4", total_years="7", l1="1", l2="1", l3="1", l4="0"),
        # z1: 猴子组行（验证按组 N）
        row("2026-01-03T00:00:00Z", "z1", "ok", group="monkey_7", n_trades="150",
            ann_excess="0.05", ir="1.0", excess_max_dd="-0.10",
            beat_years="5", total_years="7", l1="1", l2="1", l3="1", l4="1"),
        # e1: example 组行（不计入任何组的 N）
        row("2026-01-03T00:00:00Z", "e1", "ok", group="example", n_trades="150",
            ann_excess="0.05", ir="1.0", excess_max_dd="-0.10",
            beat_years="5", total_years="7", l1="1", l2="1", l3="1", l4="1"),
    ]
    ledger = pd.DataFrame(rows, columns=LEDGER_COLS)
    latest = latest_search_rows(ledger)
    ok &= _assert("台账：同名多行取最新且验证期行不混入",
                  set(latest) == {"x1", "x2", "x3", "x4", "z1", "e1"}, f"{set(latest)}")
    ok &= _assert("台账：group 列取到（x1→A，z1→monkey_7，缺组→None）",
                  group_of_config(ledger, "x1") == "A"
                  and group_of_config(ledger, "z1") == "monkey_7"
                  and group_of_config(ledger, "不存在") is None)
    ok &= _assert("L1-4：报错行无标记", all(v is None for v in flags_of(latest["x3"])))
    lists = layer_lists(["x1", "x2", "x3", "x4"], latest)
    ok &= _assert("L1-4 累计：l1=[x1,x2,x4] l4=[x1]（x4=1110 止步 L4）",
                  lists["l1"] == ["x1", "x2", "x4"] and lists["l2"] == ["x1", "x4"]
                  and lists["l3"] == ["x1", "x4"] and lists["l4"] == ["x1"],
                  f"{lists}")
    # 判据反算：由指标列重算 funnel_flags 与台账记录一致（第 2 版 L3 = ir/超额回撤）
    m = {"type": "rule", "n_trades": 150, "ann_excess": 0.05, "ir": 1.2,
         "excess_max_dd": -0.10, "beat_years": 6}
    f = funnel_flags(m)
    ok &= _assert("L1-4 判据反算：全过 (1,1,1,1)",
                  (f["funnel_l1"], f["funnel_l2"], f["funnel_l3"], f["funnel_l4"]) == (1, 1, 1, 1))
    m2 = {"type": "score", "n_rebalances": 299, "ann_excess": 0.05, "ir": 1.2,
          "excess_max_dd": -0.10, "beat_years": 6}
    ok &= _assert("L1-4 判据反算：打分型（缺省周度）299 期 L1=0", funnel_flags(m2)["funnel_l1"] == 0)
    m2w = {"type": "score", "n_rebalances": 300, "ann_excess": 0.05, "ir": 1.2,
           "excess_max_dd": -0.10, "beat_years": 6, "rebalance": "weekly_first_trade_day"}
    ok &= _assert("L1-4 判据反算：打分型周度恰 300 期 L1=1",
                  funnel_flags(m2w)["funnel_l1"] == 1)
    m2m = {"type": "score", "n_rebalances": 80, "ann_excess": 0.05, "ir": 1.2,
           "excess_max_dd": -0.10, "beat_years": 6, "rebalance": "monthly_first_trade_day"}
    ok &= _assert("L1-4 判据反算：打分型月度恰 80 期 L1=1",
                  funnel_flags(m2m)["funnel_l1"] == 1)
    m2mb = {"type": "score", "n_rebalances": 79, "ann_excess": 0.05, "ir": 1.2,
            "excess_max_dd": -0.10, "beat_years": 6, "rebalance": "monthly_first_trade_day"}
    ok &= _assert("L1-4 判据反算：打分型月度 79 期 L1=0",
                  funnel_flags(m2mb)["funnel_l1"] == 0)
    ok &= _assert("L1-4 判据反算：月度 299 期但按月度档 ≥80 → L1=1（分档不回落周度门槛）",
                  funnel_flags({**m2, "rebalance": "monthly_first_trade_day"})["funnel_l1"] == 1)
    m4 = {"type": "rule", "n_trades": 150, "ann_excess": 0.05, "ir": 1.2,
          "excess_max_dd": -0.10, "beat_years": 5}
    ok &= _assert("L1-4 判据反算：beat_years=5 不过 L4（3.4 修订版门槛 ≥6）",
                  funnel_flags(m4)["funnel_l4"] == 0)
    m4b = {"type": "rule", "n_trades": 150, "ann_excess": 0.05, "ir": 1.2,
           "excess_max_dd": -0.10, "beat_years": 6}
    ok &= _assert("L1-4 判据反算：beat_years=6 恰过 L4",
                  funnel_flags(m4b)["funnel_l4"] == 1)
    m2b = {"type": "rule", "n_trades": 99, "ann_excess": 0.05, "ir": 1.2,
           "excess_max_dd": -0.10, "beat_years": 6}
    ok &= _assert("L1-4 判据反算：99 笔（买卖合计）L1=0", funnel_flags(m2b)["funnel_l1"] == 0)
    m2c = {"type": "rule", "n_trades": 100, "ann_excess": 0.05, "ir": 1.2,
           "excess_max_dd": -0.10, "beat_years": 6}
    ok &= _assert("L1-4 判据反算：恰 100 笔 L1=1", funnel_flags(m2c)["funnel_l1"] == 1)
    # L3 边界（第 3 版）：ir=0.4 与 |超额回撤|=30% 都不取等（rules.md 第 5.2 节）
    m3 = {"type": "rule", "n_trades": 150, "ann_excess": 0.05, "ir": 0.4,
          "excess_max_dd": -0.30, "beat_years": 6}
    f3 = funnel_flags(m3)
    ok &= _assert("L1-4 判据反算：ir=0.4/超额回撤=30% 边界不取等",
                  f3["funnel_l3"] == 0, f"{f3}")
    m3b = {"type": "rule", "n_trades": 150, "ann_excess": 0.05,
           "ir": 0.4 + 1e-9, "excess_max_dd": -0.30 + 1e-9, "beat_years": 6}
    ok &= _assert("L1-4 判据反算：ir>0.4 且 |超额回撤|<30% 过 L3",
                  funnel_flags(m3b)["funnel_l3"] == 1)
    m3c = {"type": "rule", "n_trades": 150, "ann_excess": 0.05,
           "ir": 1.2, "excess_max_dd": -0.3000001, "beat_years": 6}
    ok &= _assert("L1-4 判据反算：超额回撤略超 30% 不过 L3",
                  funnel_flags(m3c)["funnel_l3"] == 0)
    m3d = {"type": "rule", "n_trades": 150, "ann_excess": 0.05,
           "ir": 0.3999, "excess_max_dd": -0.10, "beat_years": 6}
    ok &= _assert("L1-4 判据反算：ir 不足 0.4 不过 L3（夏普高也不行）",
                  funnel_flags({**m3d, "sharpe": 9.9, "max_dd": -0.01})["funnel_l3"] == 0)
    # skip-existing
    known = {"x1", "x3"}
    ok &= _assert("skip-existing：任何状态都算已跑",
                  filter_pending(["x1", "x2", "x3", "x4"], known) == ["x2", "x4"])
    # 台账规模 vs 按组 N（rules.md 第 6 节：AI=A∪B；猴子=自己组；example/test 不计入）
    ok &= _assert("台账总行数 = 8（规模展示）", trials_n(ledger) == 8, f"{trials_n(ledger)}")
    ok &= _assert("N 按组：AI（A 或 B 查询）= A 组 6 行", n_trials_for(ledger, "A") == 6
                  and n_trials_for(ledger, "B") == 6, f"{n_trials_for(ledger, 'A')}")
    ok &= _assert("N 按组：猴子 = 自己组 1 行", n_trials_for(ledger, "monkey_7") == 1)
    ok &= _assert("N 按组：example/test 不计入任何组",
                  n_trials_for(ledger, "example") == 0 and n_trials_for(ledger, "test") == 0)
    # V[SR]：只用同组 ok 行的 ir/√250
    v_a, n_a = trials_sr_variance(ledger, "A")
    v_m, n_m = trials_sr_variance(ledger, "monkey_7")
    v_e, n_e = trials_sr_variance(ledger, "example")
    import math as _math
    # A 组 ok 行（任何区间）都有 ir：x1 两行 1.2、x2 0.1、y1(验证期) 1.0、x4 1.2
    exp_a = float(np.var([1.2 / _math.sqrt(250.0), 1.2 / _math.sqrt(250.0),
                          0.1 / _math.sqrt(250.0),
                          1.0 / _math.sqrt(250.0), 1.2 / _math.sqrt(250.0)], ddof=1))
    ok &= _assert("V[SR]：A 组 = 该组 ok 行 ir/√250 的样本方差（报错行不计）",
                  abs(v_a - exp_a) < 1e-15 and n_a == 5, f"v={v_a}, n={n_a}")
    ok &= _assert("V[SR]：猴子组只取自己组的行", n_m == 1)
    ok &= _assert("V[SR]：example 组不计入（返回 NaN, 0）",
                  n_e == 0 and math.isnan(v_e))
    return ok


def selftest_gen_monkey(tmp: Path) -> bool:
    """gen-monkey 确定性 + 档位合法性（生成的配置全部过 load_config）。"""
    ok = True
    d1, d2 = tmp / "g1", tmp / "g2"
    p1, n1 = gen_monkey(99, 4, d1)
    p2, n2 = gen_monkey(99, 4, d2)
    ok &= _assert("gen-monkey：文件名 m99_001..004（小写 m<种子>_ 前缀）",
                  [p.name for p in p1] == ["m99_001.yaml", "m99_002.yaml",
                                           "m99_003.yaml", "m99_004.yaml"])
    same = all((a.read_bytes() == b.read_bytes()) for a, b in zip(p1, p2))
    ok &= _assert("gen-monkey：同 seed 两次生成逐位一致", same)
    types = []
    for p in p1:
        cfg = load_config(p)     # 会做档位/schema 强校验，非法即抛
        types.append(cfg["type"])
    ok &= _assert("gen-monkey：2 规则型 + 2 打分型（奇规则/偶打分）",
                  types == ["rule", "score", "rule", "score"], f"{types}")
    # 更大规模的档位合法性（不落 selftest 目录之外）
    d3 = tmp / "g3"
    p3, _ = gen_monkey(7, 12, d3)
    ok &= _assert("gen-monkey：12 个配置全部通过 load_config 档位校验",
                  all(load_config(p)["name"] == p.stem for p in p3))
    return ok


def selftest_tiers(tmp: Path) -> bool:
    """档位合法性：示例配置的邻居全部落在档位上且过 load_config。"""
    ok = True
    src = STRATEGIES_DIR / "examples" / "rule_breakout_ma20.yaml"
    raw = yaml.safe_load(open(src, encoding="utf-8"))
    neigh = build_neighbor_set(raw)
    ok &= _assert("档位：示例配置邻居数=27（15 个参数，端点/边界扣减后）", len(neigh) == 27,
                  f"{len(neigh)}")
    bad = []
    for nb in neigh:
        try:
            load_config(ensure_yaml(nb["raw"], tmp / "nb"))
        except ConfigError as e:
            bad.append((nb["name"], str(e)))
    ok &= _assert("档位：全部邻居过 load_config（非法即列出）", not bad, f"{bad[:3]}")
    # 空邻域判定（l5_judge 空真）
    j = l5_judge({}, "x", [])
    ok &= _assert("L5：空邻域空真通过", j["pass"] is True and j["ratio"] is None)
    # 邻居全败 → 比例 0 → 不过
    j2 = l5_judge({"a__p_u": {"funnel_l1": "0", "funnel_l2": "0", "funnel_l3": "0",
                              "funnel_l4": "0"}}, "a", ["a__p_u"])
    ok &= _assert("L5：邻居全败比例 0% 不通过", j2["pass"] is False and j2["ratio"] == 0.0)
    j3 = l5_judge({"a__p_u": {"funnel_l1": "1", "funnel_l2": "1", "funnel_l3": "1",
                              "funnel_l4": "1"},
                   "a__p_d": {"funnel_l1": "1", "funnel_l2": "1", "funnel_l3": "1",
                              "funnel_l4": "0"}}, "a", ["a__p_u", "a__p_d"])
    ok &= _assert("L5：2 邻居过 1 → 50% <70% 不通过", j3["pass"] is False
                  and abs(j3["ratio"] - 0.5) < 1e-12)
    return ok


def selftest_guard_boundary(tmp: Path) -> bool:
    """封存边界：L6 验证期合法、触及 2025 的区间被拦（不读任何封存数据）。"""
    ok = True
    try:
        guard.check_date_range(VALID_START, VALID_END)
        ok &= _assert("guard：验证期 2023~2024 放行", True)
    except guard.SealedDataError:
        ok &= _assert("guard：验证期 2023~2024 放行", False)
    try:
        guard.check_date_range(VALID_START, "2025-01-01")
        ok &= _assert("guard：触及 2025 的区间被拦", False)
    except guard.SealedDataError:
        ok &= _assert("guard：触及 2025 的区间被拦", True)
    return ok


def selftest_layers_l5_plan(tmp: Path) -> bool:
    """layers 主链路回归：plan_l5_l6 以 (ledger, survivors) 两参调用可正常规划，
    任务携带基础配置单的 group（继承自台账 group 列）；台账查不到组 → 规划报错，
    绝不猜测。（复核打回的 HIGH：原实现签名多一个未使用的 latest 必填参数，
    任一路出现 L1-4 幸存者时 layers 即抛 TypeError。）

    验证期产物检查经 runs_dir 注入临时目录——与 reports/runs 的真实产物无关
    （否则本用例会随仓库是否跑过该配置的验证期回测而漂移），并覆盖
    「产物缺失→待跑 / 产物已存在→跳过」两个分支。"""
    ok = True
    base_row = {"ts": "2026-01-01T00:00:00Z", "config": "rule_breakout_ma20",
                "group": "A", "type": "rule", "start": SEARCH_START, "end": SEARCH_END,
                "status": "ok", "n_trades": "500", "ann_ret": "", "bench_ann_ret": "",
                "ann_excess": "0.05", "sharpe": "1.0", "max_dd": "-0.1", "ir": "1.0",
                "excess_max_dd": "-0.1", "beat_years": "5", "total_years": "7",
                "funnel_l1": "1", "funnel_l2": "1", "funnel_l3": "1", "funnel_l4": "1",
                "note": ""}
    ledger = pd.DataFrame([base_row], columns=LEDGER_COLS)   # 基础配置已落台账（group=A）
    orig_nb = globals()["NEIGHBOR_DIR"]
    globals()["NEIGHBOR_DIR"] = tmp / "nb_plan"
    runs_dir = tmp / "runs"          # 空 = 无任何验证期产物
    try:
        # 两参位置调用 = run_layers → execute_l5_l6_with_runner 的真实调用形态
        planned = plan_l5_l6(ledger, ["rule_breakout_ma20"], runs_dir=runs_dir)
        p = planned["plan"]["rule_breakout_ma20"]
        ok &= _assert("L5 规划：27 个邻居", len(p["neighbors"]) == 27,
                      f"{len(p['neighbors'])}")
        ok &= _assert("L5 规划：验证期待跑", p["validation_needed"] is True)
        ok &= _assert("L5 规划：group 继承基础配置单（台账 A → 任务 group=A）",
                      p["group"] == "A"
                      and all(t["group"] == "A" for t in planned["tasks"]),
                      f"{set(t.get('group') for t in planned['tasks'])}")
        tasks = planned["tasks"]
        ok &= _assert("L5 规划：任务数 = 27 邻居 + 1 验证期", len(tasks) == 28,
                      f"{len(tasks)}")
        ok &= _assert("L5 规划：27 个搜索期任务 + 1 个验证期任务",
                      sum(1 for t in tasks if t["end"] == SEARCH_END) == 27
                      and sum(1 for t in tasks if t["end"] == VALID_END) == 1)
        ok &= _assert("L5 规划：全部任务日期不触及封存期",
                      all(t["end"] <= "20241231" for t in tasks))
        missing = [t["name"] for t in tasks if not Path(t["path"]).exists()]
        ok &= _assert("L5 规划：全部任务 YAML 已落盘", not missing, f"{missing[:3]}")
        # 台账已有同名配置 → skip-existing 生效（邻居任务清零；验证期仍要跑）
        known_rows = [base_row] + [
            {**base_row, "config": n} for n in p["neighbors"]]
        planned2 = plan_l5_l6(pd.DataFrame(known_rows, columns=LEDGER_COLS),
                              ["rule_breakout_ma20"], runs_dir=runs_dir)
        ok &= _assert("L5 规划：邻居全部已跑时任务只剩验证期",
                      len(planned2["tasks"]) == 1
                      and planned2["tasks"][0]["end"] == VALID_END,
                      f"{planned2['tasks']}")
        # 验证期产物已存在 → 验证期任务也跳过（环境无关的 hermetic 分支）
        art = run_dir_of("rule_breakout_ma20", VALID_START, VALID_END,
                         runs_dir=runs_dir) / "daily_returns.csv"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text("date,strategy_ret,benchmark_ret,excess\n", encoding="utf-8")
        planned3 = plan_l5_l6(pd.DataFrame(known_rows, columns=LEDGER_COLS),
                              ["rule_breakout_ma20"], runs_dir=runs_dir)
        ok &= _assert("L5 规划：邻居与验证期产物齐全时零任务",
                      planned3["tasks"] == []
                      and planned3["plan"]["rule_breakout_ma20"]["validation_needed"] is False,
                      f"{planned3}")
        # 台账查不到基础配置单的 group → 规划报错（不猜测、不落任务）
        no_group = pd.DataFrame([{**base_row, "group": ""}], columns=LEDGER_COLS)
        planned4 = plan_l5_l6(no_group, ["rule_breakout_ma20"], runs_dir=runs_dir)
        ok &= _assert("L5 规划：无 group 记录 → 规划报错、零任务",
                      planned4["tasks"] == []
                      and "error" in planned4["plan"]["rule_breakout_ma20"],
                      f"{planned4['plan']}")
    finally:
        globals()["NEIGHBOR_DIR"] = orig_nb
    return ok


def selftest_write_back(tmp: Path) -> bool:
    """layers 对 MS 路执行 L7/L8 后回写农场 JSON（复核打回的 MEDIUM：
    l7_l8_evaluated 原先恒为 False，final 无人回写）。"""
    ok = True
    orig_dd = globals()["DATA_DIR"]
    globals()["DATA_DIR"] = tmp
    try:
        (tmp / "funnel_monkey_s5.json").write_text(json.dumps(
            {"seed": 5, "base": ["ms5_001", "m5_002"], "l7": [], "l8": [],
             "final": [], "l7_l8_evaluated": False}), encoding="utf-8")
        tracks = {"MS": {"l7": ["m5_002", "m7_001"], "l8": ["m5_002"],
                         "final": ["m5_002"]}}
        written = write_back_farm_jsons(tracks)
        ok &= _assert("回写：只回写存在农场 JSON 的 seed", written ==
                      [str(tmp / "funnel_monkey_s5.json")], f"{written}")
        j = json.loads((tmp / "funnel_monkey_s5.json").read_text(encoding="utf-8"))
        ok &= _assert("回写：l7_l8_evaluated 置真", j["l7_l8_evaluated"] is True)
        ok &= _assert("回写：final/l7/l8 按 seed 归属写入（ms7_001 不串档）",
                      j["final"] == ["m5_002"] and j["l7"] == ["m5_002"]
                      and j["l8"] == ["m5_002"], f"{j}")
        ok &= _assert("回写：缺失 JSON 的 seed 不造假记录",
                      not (tmp / "funnel_monkey_s7.json").exists())
        # L6 幸存者全被 L7 淘汰的 seed：如实回写「评过、零幸存」
        (tmp / "funnel_monkey_s8.json").write_text(json.dumps(
            {"seed": 8, "base": ["m8_001"], "l6": ["m8_001"], "l7": [], "l8": [],
             "final": [], "l7_l8_evaluated": False}), encoding="utf-8")
        tracks2 = {"MS": {"l6": ["m8_001"], "l7": [], "l8": [], "final": []}}
        written2 = write_back_farm_jsons(tracks2)
        j8 = json.loads((tmp / "funnel_monkey_s8.json").read_text(encoding="utf-8"))
        ok &= _assert("回写：L7 全淘汰的 seed 也置 evaluated=true、final 空",
                      written2 == [str(tmp / "funnel_monkey_s8.json")]
                      and j8["l7_l8_evaluated"] is True and j8["final"] == [],
                      f"{written2} {j8}")
        ok &= _assert("回写：MS 为空路时不动任何文件",
                      write_back_farm_jsons({}) == [])
        # final_survivors 两来源去重（复核第 2 轮 MEDIUM：回写后 layers JSON 与
        # 农场 JSON 携带同一批 ms<seed>_*，不去重会把幸存名单算成重集）
        orig_lj = globals()["LAYERS_JSON"]
        globals()["LAYERS_JSON"] = tmp / "funnel_layers.json"
        try:
            (tmp / "funnel_layers.json").write_text(json.dumps(
                {"tracks": {"A": {"final": ["a_x"]}, "MS": {"final": ["m5_002"]}}}),
                encoding="utf-8")
            finals = final_survivors()
            names = [f["config"] for f in finals]
            ok &= _assert("回写：final_survivors 按配置名去重（m5_002 只出现一次）",
                          names == ["a_x", "m5_002"] and len(names) == len(set(names)),
                          f"{finals}")
            ok &= _assert("回写：同名以 layers JSON 记录为准",
                          {"config": "m5_002", "track": "MS"} in finals
                          and {"config": "m5_002", "track": "monkey_seed5"} not in finals,
                          f"{finals}")
        finally:
            globals()["LAYERS_JSON"] = orig_lj
    finally:
        globals()["DATA_DIR"] = orig_dd
    return ok


def run_selftest() -> int:
    results: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="funnel_selftest_") as td:
        tmp = Path(td)
        print("== funnel selftest ==")
        results.append(("L5 邻域展开（含端点单侧/负百分比/不挪项）", selftest_l5_neighborhood()))
        results.append(("L7 贪心去重（保留高夏普者）", selftest_l7()))
        results.append(("DSR 三性质 + t 值已知答案", selftest_dsr()))
        results.append(("L1-4 判据反算 + 台账提取 + skip-existing", selftest_l14_and_skip()))
        results.append(("gen-monkey 确定性与档位合法", selftest_gen_monkey(tmp)))
        results.append(("档位合法性 + L5 判定边界", selftest_tiers(tmp)))
        results.append(("layers L5 规划主链路（两参调用回归）", selftest_layers_l5_plan(tmp)))
        results.append(("农场 JSON 回写（l7_l8_evaluated）", selftest_write_back(tmp)))
        results.append(("封存边界（验证期放行/2025 拦截）", selftest_guard_boundary(tmp)))
    n_pass = sum(1 for _, v in results if v)
    for name, v in results:
        print(f"  [{'PASS' if v else 'FAIL'}] {name}")
    print(f"== funnel selftest: {n_pass}/{len(results)} 组通过 "
          f"（每组含多条断言）==")
    return 0 if n_pass == len(results) else 1


def _assert(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail and not cond else ""))
    return bool(cond)


# ================================================================ CLI

def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="engine/funnel.py", description="漏斗 L5~L8 与配套实验")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("selftest", help="已知答案自测")

    p_layers = sub.add_parser("layers", help="对台账既有配置执行 L5~L8")
    p_layers.add_argument("--out", default="data/funnel_layers.json")
    p_layers.add_argument("--formal", action="store_true",
                          help="正式跑：对全部 L1~L4 幸存者做邻域检验"
                               "（缺省试跑模式：L5 只对每组入围分前 "
                               f"{TRIAL_L5_TOP_K} 名执行，rules.md 第 10 章）")
    p_layers.add_argument("--workers", type=int, default=None,
                          help="并行 worker 数（缺省 = CPU 核数 − 2，rules.md 第 12 章）")

    p_gen = sub.add_parser("gen-monkey", help="种子确定性生成猴子配置单（台账去重）")
    p_gen.add_argument("--seed", type=int, required=True)
    p_gen.add_argument("--count", type=int, required=True)
    p_gen.add_argument("--out", required=True)

    p_farm = sub.add_parser("farm", help="猴子批量：生成→回测→L1-4→L5→L6")
    p_farm.add_argument("--seeds", required=True, help="A-B（含端点）或单个 A")
    p_farm.add_argument("--workers", type=int, default=None,
                        help="并行 worker 数（缺省 = CPU 核数 − 2，rules.md 第 12 章）")
    p_farm.add_argument("--count", type=int, default=200)
    p_farm.add_argument("--formal", action="store_true",
                        help="正式跑：对全部 L1~L4 幸存者做邻域检验"
                             "（缺省试跑模式：L5 只对每组入围分前 "
                             f"{TRIAL_L5_TOP_K} 名执行，rules.md 第 10 章）")

    p_style = sub.add_parser("style", help="幸存策略风格体检")
    p_style.add_argument("--all", action="store_true")

    sub.add_parser("report", help="渲染 reports/funnel_summary.md")

    p_short = sub.add_parser("shortlist", help="5.3/5.4 入围名单（转 engine/shortlist.py）")
    p_short.add_argument("--group", required=True,
                         help="AI（=A+B 合并）/ monkey_<种子> / example / test")
    p_short.add_argument("--ledger", default=str(LEDGER_PATH))
    p_short.add_argument("--layers", default=str(LAYERS_JSON))
    p_short.add_argument("--out", default=None, help="JSON 输出（默认 data/shortlist_<group>.json）")
    p_short.add_argument("--md", default=None, help="MD 输出（默认 reports/shortlist_<group>.md）")

    a = ap.parse_args(argv)

    if a.cmd == "selftest":
        return run_selftest()
    if a.cmd == "layers":
        out = Path(a.out)
        if not out.is_absolute():
            out = ROOT / out
        return run_layers(out, formal=True if a.formal else None, workers=a.workers)
    if a.cmd == "gen-monkey":
        out_dir = Path(a.out)
        if not out_dir.is_absolute():
            out_dir = ROOT / out_dir
        paths, _ = gen_monkey(a.seed, a.count, out_dir)
        print(f"[gen-monkey] seed={a.seed} count={a.count} -> {out_dir} "
              f"（{len(paths)} 个，已存在者跳过重写）")
        return 0
    if a.cmd == "farm":
        part = a.seeds.split("-")
        lo, hi = int(part[0]), int(part[-1])
        if hi < lo:
            print(f"[farm] 非法 seed 区间 {a.seeds}")
            return 2
        return run_farm(lo, hi, a.workers, a.count, formal=True if a.formal else None)
    if a.cmd == "style":
        if not a.all:
            print("[style] 需要 --all")
            return 2
        return run_style()
    if a.cmd == "report":
        return run_report()
    if a.cmd == "shortlist":
        # 局部 import：shortlist.py 顶层 from funnel import ...（避免循环导入）
        import shortlist as _shortlist
        argv_s = ["--group", a.group, "--ledger", a.ledger, "--layers", a.layers]
        if a.out:
            argv_s += ["--out", a.out]
        if a.md:
            argv_s += ["--md", a.md]
        return _shortlist.main(argv_s)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

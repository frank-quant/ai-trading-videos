# -*- coding: utf-8 -*-
"""
tools/gen_perf_corpus.py —— 性能语料生成（第 2 步任务 A）

生成恰好 50 个（规则型 25 + 打分型 25）合法配置单到独立目录 perf_corpus/
（不进 strategies/，避免污染正式搜索；名字用 pc_ 前缀）。

* 固定整数种子（默认 20261017），同种子输出逐字节确定，命令行可重跑；
* 零件/持有期/调仓频率/中性化/嵌套 wrapper 覆盖常用组合（见 COVERAGE）；
* 全部经 engine/config.py load_config 强校验（档位/量纲/schema），一个不过即退出码 1；
* 生成后打印清单（类型/因子数/调仓/中性化/零件数），供挑剖析样本。

只写 perf_corpus/ 与 stdout，不动 data/、strategies/、台账。
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

import guard  # noqa: E402  先于 numpy/pandas（BLAS 线程钉死）

from config import (ALLOWED_HOLD, ALLOWED_PCT, ALLOWED_MULT, ALLOWED_STOP,  # noqa: E402
                    ALLOWED_WINDOWS, INDUSTRY_CAP_TIERS, ConfigError, load_config)
from operators import OPERATOR_META  # noqa: E402

# 与 funnel.gen-monkey 同源的零件池派生（单一事实来源 OPERATOR_META）
OPS_WITH_N = tuple(n for n, m in OPERATOR_META.items() if m["has_window"])
OPS_NO_ARG = tuple(n for n, m in OPERATOR_META.items() if not m["has_window"])
OPS_CONDITION = tuple(n for n, m in OPERATOR_META.items()
                      if m["threshold_kind"] != "none")
OF_WRAPPERS = tuple(n for n, m in OPERATOR_META.items() if m.get("has_of"))
# 嵌套基零件池：排除 wrapper 自身，并排除 etf_above_ma_n——引擎契约
# （backtest._op_values：etf_above_ma_n 只能在 ETF 日线上顶层求值，嵌套 of
# 会在股票面板上找 close_adj 列直接 KeyError）。顶层因子/条件/rank 仍可用。
FACTOR_BASE_POOL = tuple(n for n in OPS_WITH_N + OPS_NO_ARG
                         if n not in OF_WRAPPERS and n != "etf_above_ma_n")
PCT_POOL = ALLOWED_PCT
MULT_POOL = ALLOWED_MULT
HOLD_POOL = ALLOWED_HOLD                # 3/5/10/20/40/60（3.4 版扩档）
STOP_POOL = ("无", "5%", "8%", "10%")
WEIGHT_POOL = (0.2, 0.3, 0.5, 1.0, 1.5, 2.0, 3.0)
REB_POOL = ("weekly_first_trade_day", "monthly_first_trade_day")

COVERAGE = {
    "窗口": "ALLOWED_WINDOWS 全 7 档在 buy/sell/factors/rank 间轮换",
    "阈值": "pct ± 档位 / mult 档位 / streak 整数档位，按零件量纲",
    "持有期": "规则型 max_hold_days 6 档轮换",
    "止损": "无/5/8/10 轮换",
    "调仓频率": "打分型周度 13 + 月度 12",
    "中性化": "neut_industry × neut_size 四象限均衡（9/8/8 与关/关）",
    "嵌套": "打分因子约 1/4 概率包 ts_pct/xsec_pct/ind_rank 一层",
    "零件类别": "量价/规模估值/财务/预告快报/资金面(龙虎榜两融北向)/B组新零件全部进入抽样池",
    "industry_cap": "规则型少量启用（档位 = 窗口档位）",
}


def _rand_threshold(rng: random.Random, opn: str):
    kind = OPERATOR_META[opn]["threshold_kind"]
    if kind == "pct":
        return rng.choice((1.0, -1.0)) * rng.choice(PCT_POOL)
    if kind == "mult":
        return rng.choice(MULT_POOL)
    if kind == "streak":
        return float(rng.choice(ALLOWED_WINDOWS))
    raise ValueError(opn)


def _rand_op_spec(rng: random.Random, pool=None) -> dict:
    pool = OPS_WITH_N + OPS_NO_ARG if pool is None else pool
    opn = rng.choice(pool)
    spec = {"op": opn}
    if OPERATOR_META[opn]["has_window"]:
        spec["n"] = rng.choice(ALLOWED_WINDOWS)
    return spec


def _rand_factor_spec(rng: random.Random) -> dict:
    base = _rand_op_spec(rng, FACTOR_BASE_POOL)
    if OF_WRAPPERS and rng.random() < 0.25:
        w = rng.choice(OF_WRAPPERS)
        spec = {"op": w, "of": base}
        if OPERATOR_META[w]["has_window"]:
            spec["n"] = rng.choice(ALLOWED_WINDOWS)
        return spec
    return base


def _rand_condition(rng: random.Random) -> dict:
    spec = _rand_op_spec(rng, OPS_CONDITION)
    return {**spec, "dir": rng.choice(("above", "below")),
            "threshold": _rand_threshold(rng, spec["op"])}


def make_rule_cfg(name: str, seed: int, rng: random.Random) -> dict:
    cfg = {
        "name": name, "type": "rule",
        "desc": f"perf corpus（seed={seed}，tools/gen_perf_corpus.py；group=test 专用，不入正式搜索）",
        "buy": [_rand_condition(rng) for _ in range(rng.randint(1, 4))],
        "sell": [_rand_condition(rng) for _ in range(rng.randint(0, 2))],
        "max_hold_days": rng.choice(HOLD_POOL),
        "stop_loss": rng.choice(STOP_POOL),
        "max_positions": 10,
    }
    if rng.random() < 0.5:
        cfg["rank"] = {**_rand_factor_spec(rng), "order": rng.choice(("asc", "desc"))}
    if rng.random() < 0.2:
        cfg["industry_cap"] = rng.choice(INDUSTRY_CAP_TIERS)
    return cfg


def make_score_cfg(name: str, seed: int, rng: random.Random,
                   rebalance: str, neut: tuple[bool, bool]) -> dict:
    # 因子数偏多（2~4），便于剖析时覆盖零件取值热路径
    return {
        "name": name, "type": "score",
        "desc": f"perf corpus（seed={seed}，tools/gen_perf_corpus.py；group=test 专用，不入正式搜索）",
        "factors": [{**_rand_factor_spec(rng),
                     "weight": rng.choice((1.0, -1.0)) * rng.choice(WEIGHT_POOL)}
                    for _ in range(rng.randint(2, 4))],
        "holdings": 30,
        "rebalance": rebalance,
        "neut_industry": neut[0],
        "neut_size": neut[1],
    }


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="生成 50 个性能语料配置（25 规则 + 25 打分）")
    ap.add_argument("--out", default="perf_corpus", help="输出目录（相对仓库根，默认 perf_corpus/）")
    ap.add_argument("--seed", type=int, default=20261017, help="随机种子（默认 20261017）")
    a = ap.parse_args(argv)

    out_dir = ROOT / a.out
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)

    # 打分型调仓/中性化覆盖矩阵：周度 13（9 开关组合均衡 + 4 轮换）+ 月度 12
    reb_plan = ["weekly_first_trade_day"] * 13 + ["monthly_first_trade_day"] * 12
    neut_plan = ([(False, False)] * 7 + [(True, False)] * 6 + [(False, True)] * 6
                 + [(True, True)] * 6)   # 25 个：四象限 7/6/6/6

    cfgs: list[dict] = []
    for i in range(1, 26):
        cfgs.append(make_rule_cfg(f"pc_r{i:02d}", a.seed, rng))
    for i in range(25):
        cfgs.append(make_score_cfg(f"pc_s{i + 1:02d}", a.seed, rng,
                                   reb_plan[i], neut_plan[i]))
    assert len(cfgs) == 50, f"语料必须恰好 50 个，得到 {len(cfgs)}"

    rows: list[str] = []
    n_bad = 0
    for cfg in cfgs:
        path = out_dir / f"{cfg['name']}.yaml"
        if not path.exists():          # 确定性生成：已存在即同内容，不重写
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        try:
            parsed = load_config(path)          # engine/config.py 强校验
            n_parts = (len(parsed.get("buy", [])) + len(parsed.get("sell", []))
                       + (1 if parsed.get("rank") else 0) if parsed["type"] == "rule"
                       else len(parsed["factors"]))
            extra = (f"rebalance={parsed.get('rebalance')} "
                     f"neut_ind={parsed.get('neut_industry')} "
                     f"neut_size={parsed.get('neut_size')}" if parsed["type"] == "score"
                     else f"hold={parsed['max_hold_days']} stop={parsed['stop_loss']}")
            rows.append(f"{parsed['name']}  {parsed['type']}  零件数={n_parts}  {extra}  OK")
        except ConfigError as e:
            n_bad += 1
            rows.append(f"{cfg['name']}  FAIL: {e}")

    print(f"[gen_perf_corpus] seed={a.seed}  目录={a.out}/  共 {len(cfgs)} 个"
          f"（规则 25 + 打分 25），load_config 校验失败 {n_bad} 个")
    for r in rows:
        print("  " + r)
    print("[gen_perf_corpus] 覆盖口径：")
    for k, v in COVERAGE.items():
        print(f"  · {k}: {v}")
    if n_bad:
        print("[gen_perf_corpus] 存在校验失败配置，退出码 1")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

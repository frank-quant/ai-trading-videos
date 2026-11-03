# -*- coding: utf-8 -*-
"""
engine/config.py —— 策略配置单（YAML）解析与档位校验

一切数值只能取 rules.md 第 7 节档位：
  窗口 3/5/10/20/60/120/250；百分比 1/2/3/5/8/10/15；倍数 0.5/0.8/1.0/1.2/1.5/2.0；
  持有天数上限 3/5/10/20/40/60；止损 无/5%/8%/10%；打分型持仓数 30；
  打分型调仓频率 周度/月度（各取该周期第一个交易日）；
  打分型中性化 neut_industry（申万一级行业内截面秩）/ neut_size（当日流通市值
  截面 5 档内秩）两个独立布尔开关，默认全关（rules.md 7.5）。

YAML结构示例见 strategies/examples/ 与 tests/fixtures/；字段与档位以本模块校验为准。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from operators import ALLOWED_WINDOWS, OPERATORS, OPERATOR_META  # noqa: E402

# rules.md 第 7 节档位
ALLOWED_PCT = (1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0)        # 百分比
ALLOWED_MULT = (0.5, 0.8, 1.0, 1.2, 1.5, 2.0)              # 倍数
ALLOWED_HOLD = (3, 5, 10, 20, 40, 60)                      # 持有天数上限（3.4 版扩到 60）
ALLOWED_STOP = (None, 5.0, 8.0, 10.0)                      # 止损（None=无）
SCORE_HOLDINGS = 30                                        # 打分型持仓数
RULE_MAX_HOLDINGS = 10                                     # 规则型最多同时持有
# 打分型调仓频率（rules.md 7 / 7.5：周度和月度；L1 按频率分档 ≥300 / ≥80 期）
REBALANCE_MODES = ("weekly_first_trade_day", "monthly_first_trade_day")

# 零件参数形态：从 OPERATOR_META（单一事实来源，含 engine/operator_registry.json
# 里已登记的新零件）派生——新零件登记后配置校验自动生效，无需再手改这里。
OP_ARG_OPERATORS = frozenset(n for n, m in OPERATOR_META.items() if m["has_window"])
NO_ARG_OPERATORS = frozenset(OPERATORS) - OP_ARG_OPERATORS
OF_OPERATORS = frozenset(n for n, m in OPERATOR_META.items() if m.get("has_of"))
# 行业分散约束（rules.md 7.5 行业零件：同一行业最多持有 N 只）的档位：
# 复用整数档位（窗口档位序列）；0/缺省 = 不启用。
INDUSTRY_CAP_TIERS = tuple(ALLOWED_WINDOWS)


class ConfigError(ValueError):
    """配置单不合法（档位越界 / schema 错误 / 零件名不存在）。"""


def _num(x, what: str):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ConfigError(f"{what} 必须是数值，得到 {x!r}")
    return float(x)


def _check_pct(x, what: str) -> float:
    """百分比档位：正档位或其相反数（如 -5 表示「低于 -5%」）。"""
    v = _num(x, what)
    if v not in ALLOWED_PCT and -v not in ALLOWED_PCT:
        raise ConfigError(f"{what}={v} 不在百分比档位 ±{list(ALLOWED_PCT)}")
    return v


def _check_mult(x, what: str) -> float:
    v = _num(x, what)
    if v not in ALLOWED_MULT:
        raise ConfigError(f"{what}={v} 不在倍数档位 {list(ALLOWED_MULT)}")
    return v


def _parse_operator(spec: dict, what: str) -> dict:
    """零件引用：{op: 名字, n: 窗口(可选), of: 嵌套spec(仅 has_of 零件)}。

    返回 {name, n?, of?}；嵌套 spec 递归校验。
    """
    if not isinstance(spec, dict) or "op" not in spec:
        raise ConfigError(f"{what} 必须是 {op: 零件名, n: 窗口} 形式，得到 {spec!r}")
    name = str(spec["op"])
    if name not in OPERATORS:
        raise ConfigError(f"{what}: 未知零件 {name!r}（可用：{sorted(OPERATORS)}）")
    out: dict = {"op": name}
    if name in OF_OPERATORS:
        if "of" not in spec:
            raise ConfigError(f"{what}: 零件 {name} 需要嵌套 of（基零件 spec）")
        out["of"] = _parse_operator(spec["of"], f"{what}.of")
        if name in OP_ARG_OPERATORS:
            if "n" not in spec:
                raise ConfigError(f"{what}: 零件 {name} 需要窗口参数 n")
            n = int(_num(spec["n"], f"{what}.n"))
            if n not in ALLOWED_WINDOWS:
                raise ConfigError(f"{what}.n={n} 不在窗口档位 {list(ALLOWED_WINDOWS)}")
            out["n"] = n
        elif spec.get("n") is not None:
            raise ConfigError(f"{what}: 零件 {name} 不接受窗口参数")
        return out
    if name in OP_ARG_OPERATORS:
        if "n" not in spec:
            raise ConfigError(f"{what}: 零件 {name} 需要窗口参数 n")
        n = int(_num(spec["n"], f"{what}.n"))
        if n not in ALLOWED_WINDOWS:
            raise ConfigError(f"{what}.n={n} 不在窗口档位 {list(ALLOWED_WINDOWS)}")
        out["n"] = n
    elif name in NO_ARG_OPERATORS:
        if "n" in spec and spec["n"] is not None:
            raise ConfigError(f"{what}: 零件 {name} 不接受窗口参数")
    else:  # pragma: no cover
        raise ConfigError(f"{what}: 零件 {name} 未登记参数形态")
    return out


def _parse_condition(spec: dict, what: str) -> dict:
    """条件：{op: ..., n: ..., 方向: above|below, 阈值: 数值}。

    方向 above = 零件值 > 阈值；below = 零件值 < 阈值。
    阈值按零件量纲（OPERATOR_META 的 threshold_kind，单一事实来源）解释：
    pct → 百分比档位；mult → 倍数档位；streak → 整数档位；
    none → 该零件无阈值量纲，不能作条件（可作 factor/rank）。
    """
    base = _parse_operator(spec, what)
    d = str(spec.get("dir", "")).lower()
    if d not in ("above", "below"):
        raise ConfigError(f"{what}.dir 必须是 above/below，得到 {spec.get('dir')!r}")
    if "threshold" not in spec:
        raise ConfigError(f"{what} 缺少 threshold")
    thr = spec["threshold"]
    name = base["op"]
    kind = OPERATOR_META[name]["threshold_kind"]
    if kind == "pct":
        thr = _check_pct(thr, f"{what}.threshold")
    elif kind == "mult":
        thr = _check_mult(thr, f"{what}.threshold")
    elif kind == "streak":
        if thr not in ALLOWED_WINDOWS:
            raise ConfigError(f"{what}.threshold={thr} 不在整数档位 {list(ALLOWED_WINDOWS)}")
        thr = float(thr)
    else:
        raise ConfigError(f"{what}: 零件 {name} 无阈值量纲，不能用作 buy/sell 条件"
                          f"（只能作打分因子 / rank）")
    return {**base, "dir": d, "threshold": thr}


def _parse_rule_cfg(cfg: dict) -> dict:
    buy = cfg.get("buy")
    if not isinstance(buy, list) or not buy:
        raise ConfigError("规则型 buy 必须是非空条件列表")
    buy = [_parse_condition(c, f"buy[{i}]") for i, c in enumerate(buy)]

    sell = cfg.get("sell") or []
    sell = [_parse_condition(c, f"sell[{i}]") for i, c in enumerate(sell)]

    # 排序：{op:..., n:..., order: asc|desc}（信号过多时按该零件值排序取前 N 只）
    rank = cfg.get("rank")
    if rank is not None:
        base = _parse_operator(rank, "rank")
        order = str(rank.get("order", "desc")).lower()
        if order not in ("asc", "desc"):
            raise ConfigError(f"rank.order 必须是 asc/desc，得到 {rank.get('order')!r}")
        rank = {**base, "order": order}

    hold = cfg.get("max_hold_days")
    if hold not in ALLOWED_HOLD:
        raise ConfigError(f"max_hold_days={hold} 不在档位 {list(ALLOWED_HOLD)}")

    stop = cfg.get("stop_loss", None)
    if stop is None or (isinstance(stop, str) and stop.strip().lower() in ("none", "无", "")):
        stop = None
    else:
        if isinstance(stop, str):
            s = stop.strip()
            if s.endswith("%"):
                s = s[:-1]
            try:
                stop = float(s)
            except ValueError:
                raise ConfigError(f"stop_loss={stop!r} 无法解析为数值")  # noqa: B904
        else:
            stop = _num(stop, "stop_loss")
        if stop not in ALLOWED_STOP:
            raise ConfigError(f"stop_loss={stop} 不在档位 {list(ALLOWED_STOP)}")

    mh = cfg.get("max_positions", RULE_MAX_HOLDINGS)
    if mh != RULE_MAX_HOLDINGS:
        raise ConfigError(f"规则型 max_positions 固定为 {RULE_MAX_HOLDINGS}（rules.md 第 4 节）")

    cap = cfg.get("industry_cap", 0)
    cap = 0 if cap is None else int(_num(cap, "industry_cap"))
    if cap != 0 and cap not in INDUSTRY_CAP_TIERS:
        raise ConfigError(f"industry_cap={cap} 不在档位 {list(INDUSTRY_CAP_TIERS)}（0=不启用）")

    return {"type": "rule", "buy": buy, "sell": sell, "rank": rank,
            "max_hold_days": int(hold), "stop_loss": stop,
            "max_positions": RULE_MAX_HOLDINGS, "industry_cap": cap}


def _parse_bool(key: str, v) -> bool:
    """布尔开关（中性化两键等）：只认 true/false（yaml 布尔或这两个词）。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    raise ConfigError(f"{key} 必须是 true/false，得到 {v!r}")


def _parse_score_cfg(cfg: dict) -> dict:
    factors = cfg.get("factors")
    if not isinstance(factors, list) or not factors:
        raise ConfigError("打分型 factors 必须是非空列表")
    parsed = []
    wsum = 0.0
    for i, f in enumerate(factors):
        if not isinstance(f, dict):
            raise ConfigError(f"factors[{i}] 必须是 {op,n,weight} 形式")
        base = _parse_operator(f, f"factors[{i}]")
        w = _num(f.get("weight"), f"factors[{i}].weight")
        if w == 0:
            raise ConfigError(f"factors[{i}].weight 不能为 0")
        wsum += abs(w)
        parsed.append({**base, "weight": w})
    # 权重归一化不改变排序，但让配置可读；权重本身不受档位约束（非 rules.md 参数）
    hold = cfg.get("holdings", SCORE_HOLDINGS)
    if hold != SCORE_HOLDINGS:
        raise ConfigError(f"打分型 holdings 固定为 {SCORE_HOLDINGS}（rules.md 第 4 节）")
    reb = str(cfg.get("rebalance", "weekly_first_trade_day")).lower()
    if reb not in REBALANCE_MODES:
        raise ConfigError(f"rebalance={reb!r} 不在 {list(REBALANCE_MODES)}"
                          "（周度 / 月度各取第一个交易日；rules.md 7.5）")
    # 中性化两开关（rules.md 7.5：打分型必须支持行业内排名 / 市值分档内排名，
    # 两种口径可各自独立开关，默认全关；当前生效口径写进 run 目录 summary.json）
    neut_ind = _parse_bool("neut_industry", cfg.get("neut_industry", False))
    neut_size = _parse_bool("neut_size", cfg.get("neut_size", False))
    cap = cfg.get("industry_cap", 0)
    cap = 0 if cap is None else int(_num(cap, "industry_cap"))
    if cap != 0 and cap not in INDUSTRY_CAP_TIERS:
        raise ConfigError(f"industry_cap={cap} 不在档位 {list(INDUSTRY_CAP_TIERS)}（0=不启用）")
    return {"type": "score", "factors": parsed, "holdings": SCORE_HOLDINGS,
            "rebalance": reb, "neut_industry": neut_ind, "neut_size": neut_size,
            "weight_sum": wsum, "industry_cap": cap}


def load_config(path: str | Path) -> dict:
    """读取并校验单个 YAML 配置单。任何不合法都抛 ConfigError。"""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"配置单不存在：{path}")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ConfigError("配置单顶层必须是映射")
    name = cfg.get("name")
    if not name or not isinstance(name, str):
        raise ConfigError("配置单缺少 name 字段")
    typ = cfg.get("type")
    if typ == "rule":
        parsed = _parse_rule_cfg(cfg)
    elif typ == "score":
        parsed = _parse_score_cfg(cfg)
    else:
        raise ConfigError(f"type 必须是 rule/score，得到 {typ!r}")
    out = {"name": name, "desc": str(cfg.get("desc", "")), **parsed}
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    a = ap.parse_args()
    try:
        c = load_config(a.config)
        print("OK", c["name"], c["type"])
    except ConfigError as e:
        print("FAIL", e)
        raise SystemExit(1)

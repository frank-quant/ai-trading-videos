"""Whitelisted formula DSL: parse, validate constraints, evaluate on wide frames."""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

# op -> (arity, kind)
OPS = {
    "Add": (2, "ew"), "Sub": (2, "ew"), "Mul": (2, "ew"), "Div": (2, "ew"),
    "Log": (1, "ew"), "Abs": (1, "ew"), "Sign": (1, "ew"),
    "Mean": (2, "roll"), "Std": (2, "roll"), "Var": (2, "roll"), "Sum": (2, "roll"),
    "Max": (2, "roll"), "Min": (2, "roll"), "Rank": (2, "roll"),
    "Ref": (2, "lag"), "Delta": (2, "lag"),
    "Corr": (3, "roll2"),
    "If": (3, "ew"), "Gt": (2, "ew"), "Lt": (2, "ew"),
}
ROLL_AGG = {"Mean": "mean", "Std": "std", "Var": "var", "Sum": "sum",
            "Max": "max", "Min": "min", "Rank": "rank"}
FIELDS = {"open", "high", "low", "close", "vwap", "volume", "amount", "change"}
TOKEN = re.compile(r"\s*(\$[a-z]+|[A-Za-z_][A-Za-z_0-9]*|-?\d+(?:\.\d+)?(?:e-?\d+)?|[(),])")


@dataclass
class Node:
    op: str | None          # None for leaf
    args: list
    field: str | None = None
    const: float | None = None


def tokenize(expr: str) -> list[str]:
    toks, i = [], 0
    while i < len(expr):
        m = TOKEN.match(expr, i)
        if not m:
            if expr[i:].strip() == "":
                break
            raise ValueError(f"bad token at: {expr[i:i+20]!r}")
        toks.append(m.group(1))
        i = m.end()
    return toks


def parse(expr: str) -> Node:
    toks = tokenize(expr)
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def take():
        nonlocal pos
        t = toks[pos]
        pos += 1
        return t

    def atom() -> Node:
        t = take()
        if t.startswith("$"):
            name = t[1:]
            if name not in FIELDS:
                raise ValueError(f"unknown field ${name}")
            return Node(None, [], field=name)
        if re.fullmatch(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", t):
            return Node(None, [], const=float(t))
        if t in OPS:
            if take() != "(":
                raise ValueError(f"expected ( after {t}")
            args = [atom()]
            while peek() == ",":
                take()
                args.append(atom())
            if take() != ")":
                raise ValueError(f"expected ) for {t}")
            if len(args) != OPS[t][0]:
                raise ValueError(f"{t} expects {OPS[t][0]} args, got {len(args)}")
            return Node(t, args)
        raise ValueError(f"unknown token {t!r}")

    root = atom()
    if pos != len(toks):
        raise ValueError("trailing tokens")
    return root


def _int_param(node: Node, op: str) -> int:
    if node.const is None or node.op is not None or node.field is not None:
        raise ValueError(f"{op} window/lag must be an integer constant")
    v = node.const
    if v != int(v):
        raise ValueError(f"{op} window/lag must be integer, got {v}")
    return int(v)


def validate(root: Node, cfg: dict) -> dict:
    fc = cfg["formula"]
    nodes, fields_used = 0, set()
    wlo, whi = fc["window_range"]
    llo, lhi = fc["lag_range"]

    def walk(n: Node) -> int:
        nonlocal nodes
        if n.field is not None:
            fields_used.add(n.field)
            return 1
        if n.const is not None:
            return 0
        nodes += 1
        kind = OPS[n.op][1]
        if kind == "roll":
            w = _int_param(n.args[1], n.op)
            if not (wlo <= w <= whi):
                raise ValueError(f"{n.op} window {w} outside [{wlo},{whi}]")
            return walk(n.args[0]) + w - 1
        if kind == "lag":
            k = _int_param(n.args[1], n.op)
            if not (llo <= k <= lhi):
                raise ValueError(f"{n.op} lag {k} outside [{llo},{lhi}]")
            return walk(n.args[0]) + k
        if kind == "roll2":
            w = _int_param(n.args[2], n.op)
            if not (wlo <= w <= whi):
                raise ValueError(f"{n.op} window {w} outside [{wlo},{whi}]")
            return max(walk(n.args[0]), walk(n.args[1])) + w - 1
        return max(walk(a) for a in n.args)

    lookback = walk(root)
    if nodes > fc["max_operator_nodes"]:
        raise ValueError(f"{nodes} operator nodes > {fc['max_operator_nodes']}")
    if lookback > fc["max_total_lookback"]:
        raise ValueError(f"lookback {lookback} > {fc['max_total_lookback']}")
    if len(fields_used) > fc["max_distinct_fields"]:
        raise ValueError(f"{len(fields_used)} distinct fields > {fc['max_distinct_fields']}")
    return {"operator_nodes": nodes, "total_lookback": lookback,
            "fields": sorted(fields_used)}


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    return df.replace([np.inf, -np.inf], np.nan)


def evaluate(root: Node, fields: dict[str, pd.DataFrame]) -> pd.DataFrame:
    def ev(n: Node) -> pd.DataFrame:
        if n.field is not None:
            return fields[n.field]
        if n.const is not None:
            return n.const
        op = n.op
        a = [ev(x) for x in n.args]
        if op == "Add":
            return a[0] + a[1]
        if op == "Sub":
            return a[0] - a[1]
        if op == "Mul":
            return a[0] * a[1]
        if op == "Div":
            den = a[1].where(a[1] != 0)
            return _clean(a[0] / den)
        if op == "Log":
            return _clean(np.log(a[0].where(a[0] > 0)))
        if op == "Abs":
            return a[0].abs()
        if op == "Sign":
            return np.sign(a[0])
        if op in ROLL_AGG:
            w = int(n.args[1].const)
            r = a[0].rolling(w, min_periods=w)
            out = getattr(r, ROLL_AGG[op])() if op != "Rank" else r.rank(pct=True)
            return _clean(out)
        if op == "Ref":
            return a[0].shift(int(n.args[1].const))
        if op == "Delta":
            return a[0] - a[0].shift(int(n.args[1].const))
        if op == "Corr":
            w = int(n.args[2].const)
            return _clean(a[0].rolling(w, min_periods=w).corr(a[1]))
        if op == "If":
            cond = a[0] > 0
            yes = a[1] if isinstance(a[1], pd.DataFrame) else pd.DataFrame(a[1], index=a[0].index, columns=a[0].columns)
            no = a[2] if isinstance(a[2], pd.DataFrame) else pd.DataFrame(a[2], index=a[0].index, columns=a[0].columns)
            return yes.where(cond, no)
        if op in ("Gt", "Lt"):
            mask = a[0].notna() if isinstance(a[0], pd.DataFrame) else True
            if isinstance(a[1], pd.DataFrame):
                mask = mask & a[1].notna()
            cmp = (a[0] > a[1]) if op == "Gt" else (a[0] < a[1])
            return cmp.astype(float).where(mask)
        raise ValueError(f"unhandled op {op}")

    return _clean(ev(root))


def compile_expr(expr: str, cfg: dict) -> tuple[Node, dict]:
    root = parse(expr)
    info = validate(root, cfg)
    return root, info
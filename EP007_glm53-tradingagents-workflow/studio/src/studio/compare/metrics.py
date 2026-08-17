"""硬指标采集：耗时 / token / 成本 / 报告字数 / 决策方向。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from .runner import ModelRun

DECISION_PATTERNS = [
    (r"买入|看多|增持|加仓", "看多"),
    (r"卖出|看空|减持|减仓", "看空"),
    (r"持有|中性|观望|等待", "中性"),
]


def _decision_of(text: str) -> str:
    if not text:
        return "-"
    # 只看报告后半段（最终决策区），避免被分析师的中间讨论带偏
    tail = text[-3000:]
    for pattern, label in DECISION_PATTERNS:
        if re.search(pattern, tail):
            return label
    return "-"


def _result_text(result: dict) -> str:
    parts = []
    for key in ("report", "full_report", "report_content", "summary", "recommendation"):
        v = result.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v)
    return "\n".join(parts)


def _step_durations(steps: list[dict]) -> str:
    """把 steps 里带时间戳的步骤压成 'name:xxs' 摘要。"""
    out = []
    for s in steps[:8]:
        name = s.get("name") or s.get("step_name") or ""
        dur = s.get("duration") or s.get("duration_s")
        if name:
            out.append(f"{name}:{round(dur, 1)}s" if isinstance(dur, (int, float)) else str(name))
    return "; ".join(out)[:120]


def collect_tokens(client, model: str, since: datetime) -> tuple[int, int]:
    """从原项目用量统计里汇总该模型 since 之后的 prompt/completion token。"""
    try:
        records = client.usage_records(
            model_name=model,
            start=since.strftime("%Y-%m-%dT%H:%M:%S"),
            limit=1000,
        )
    except Exception:
        return 0, 0
    prompt = completion = 0
    for rec in records:
        prompt += int(rec.get("prompt_tokens") or rec.get("input_tokens") or 0)
        completion += int(rec.get("completion_tokens") or rec.get("output_tokens") or 0)
    return prompt, completion


def build_rows(cfg, client, runs: list[ModelRun], bench_start: datetime) -> list[dict]:
    aliases: dict = cfg.get("compare.aliases", {}) or {}
    rows = []
    prices: dict = cfg.get("compare.prices", {}) or {}
    for run in runs:
        prompt_tok = completion_tok = 0
        if run.status == "completed":
            prompt_tok, completion_tok = collect_tokens(client, run.model, bench_start)
        text = _result_text(run.result)
        cost = ""
        price = prices.get(run.model) or {}
        if price and prompt_tok:
            cost = (
                prompt_tok / 1000 * float(price.get("input", 0))
                + completion_tok / 1000 * float(price.get("output", 0))
            )
            cost = f"{cost:.2f}"
        decision = (run.result.get("decision") or {}).get("action") or _decision_of(text)
        rows.append({
            "model": aliases.get(run.model, run.model),
            "status": run.status,
            "wall_s": run.wall_s,
            "report_chars": len(text) if text else 0,
            "prompt_tokens": prompt_tok,
            "completion_tokens": completion_tok,
            "cost": cost,
            "decision": decision,
            "steps": _step_durations(run.steps),
            "task_id": run.task_id,
            "error": run.error[:80] if run.error and run.status != "completed" else "",
        })
    return rows

"""统一事件模型：SSE / 状态轮询 / 报告文件 都归一化成 TimelineEvent。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class TimelineEvent:
    ts: str
    phase: str          # 分析师/研究/交易/风控/管理/系统
    agent: str          # 展示名，如 "市场分析师"
    content: str = ""
    kind: str = "message"   # message | step | report
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Timeline:
    task_id: str
    symbol: str = ""
    created_at: str = field(default_factory=now_iso)
    meta: dict[str, Any] = field(default_factory=dict)
    events: list[TimelineEvent] = field(default_factory=list)

    def add(self, ev: TimelineEvent) -> None:
        self.events.append(ev)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "symbol": self.symbol,
            "created_at": self.created_at,
            "meta": self.meta,
            "events": [e.to_dict() for e in self.events],
        }


def sse_to_event(task_id: str, payload: dict) -> Optional[TimelineEvent]:
    """SSE progress 事件 -> TimelineEvent（步骤级）。"""
    etype = payload.get("event", "progress")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if etype in {"error"}:
        return TimelineEvent(now_iso(), "系统", "SSE", str(data), kind="step")
    step = data.get("current_step") or data.get("step") or {}
    if isinstance(step, dict):
        name = step.get("name") or step.get("step_name") or ""
    else:
        name = str(step)
    if not name and "message" not in data:
        return None
    return TimelineEvent(
        ts=now_iso(),
        phase=_phase_of(name or str(data.get("message", ""))),
        agent=name or "进度",
        content=str(data.get("message") or data.get("progress", "")),
        kind="step",
        meta={"progress": data.get("progress")},
    )


def _phase_of(text: str) -> str:
    mapping = {
        "市场": "分析师", "基本面": "分析师", "新闻": "分析师", "情绪": "分析师",
        "研究": "研究", "辩论": "研究", "多空": "研究", "bull": "研究", "bear": "研究",
        "交易": "交易", "投资": "交易", "trader": "交易",
        "风险": "风控", "risk": "风控",
        "经理": "管理", "manager": "管理", "决策": "管理", "报告": "管理",
    }
    low = text.lower()
    for key, phase in mapping.items():
        if key in low or key in text:
            return phase
    return "系统"

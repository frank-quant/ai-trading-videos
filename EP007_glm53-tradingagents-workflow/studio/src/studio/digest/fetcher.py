"""报告原文获取：优先 API 结果，兜底 data/analysis_results 文件卷。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..core.textutil import normalize_md

REPORT_PRIORITY = [
    "final_trade_decision",
    "investment_plan",
    "trader_investment_plan",
    "research_team_decision",
    "risk_management_decision",
]


@dataclass
class ReportDoc:
    text: str
    source: str          # api | file
    symbol: str = ""
    date: str = ""
    task_id: str = ""

    @property
    def chars(self) -> int:
        return len(self.text)


def fetch_report(client, task_id: str, ta_dir: Optional[Path] = None) -> ReportDoc:
    """获取任务报告：文件卷优先（内容最全），API 兜底（可拿到 symbol/decision）。"""
    try:
        data = client.get_result(task_id)
    except Exception:
        data = {}
    symbol = str(data.get("symbol") or data.get("stock_code") or "")

    if ta_dir:
        doc = _from_dir(ta_dir, symbol)
        if doc:
            doc.task_id = task_id
            doc.symbol = doc.symbol or symbol
            return doc

    text = _result_to_text(data)
    if text:
        return ReportDoc(text=text, source="api", symbol=symbol, task_id=task_id)
    raise FileNotFoundError(
        f"任务 {task_id} 的报告在 {ta_dir or '（未配置 data.ta_dir）'} 与 API 均未找到"
    )


def _result_to_text(data: dict) -> str:
    parts: list[str] = []
    for key in ("report", "full_report", "report_content"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v
    if summary := data.get("summary"):
        parts.append(f"## 总结\n{summary}")
    if rec := data.get("recommendation"):
        parts.append(f"## 建议\n{rec}")
    decision = data.get("decision") or {}
    if decision.get("action"):
        parts.append(
            f"## 决策\n动作: {decision.get('action')}；目标价: {decision.get('target_price')}；"
            f"置信度: {decision.get('confidence')}"
        )
    return "\n\n".join(p for p in parts if p.strip())


def _from_dir(ta_dir: Path, symbol: str) -> Optional[ReportDoc]:
    """扫 analysis_results/<symbol>/<date>/reports/*.md，按优先级拼接。"""
    base = Path(ta_dir) / "analysis_results"
    roots = [base / symbol] if symbol else []
    roots.append(base)  # symbol 未知时全扫
    for root in roots:
        if not root.is_dir():
            continue
        day_dirs = sorted([p for p in root.iterdir() if p.is_dir()], reverse=True)
        for day in day_dirs:
            reports = day / "reports"
            if not reports.is_dir():
                continue
            files = {p.stem: p for p in reports.glob("*.md")}
            if not files:
                continue
            ordered = [files[k] for k in REPORT_PRIORITY if k in files]
            ordered += [p for k, p in files.items() if k not in REPORT_PRIORITY]
            text = "\n\n---\n\n".join(
                f"## {p.stem}\n{normalize_md(p.read_text(encoding='utf-8', errors='replace'))}" for p in ordered
            )
            return ReportDoc(
                text=text, source="file",
                symbol=symbol or root.name, date=day.name,
            )
    return None


def latest_task_dir(ta_dir: Path, symbol: str = "") -> Optional[Path]:
    """给 CLI 用：找最近一次分析产物目录。"""
    base = Path(ta_dir) / "analysis_results"
    roots = [base / symbol] if symbol else [base]
    for root in roots:
        if not root.is_dir():
            continue
        for sym_dir in ([root] if symbol else sorted(root.iterdir(), reverse=True)):
            if not sym_dir.is_dir():
                continue
            days = sorted([p for p in sym_dir.iterdir() if p.is_dir()], reverse=True)
            if days:
                return days[0]
    return None

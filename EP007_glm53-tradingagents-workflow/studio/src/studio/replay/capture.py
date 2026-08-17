"""回放采集：把一次分析的过程归一化为 Timeline。

数据源（按可靠度叠加）：
  1. API 任务状态 steps       —— 步骤骨架与时间
  2. analysis_results 文件卷   —— 各 agent 的报告产物（内容主体）
  3. message_tool.log          —— 框架消息日志（有则解析，无则跳过）
  4. --live 模式：SSE 实时事件 —— 运行中任务的进度流
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..core.events import Timeline, TimelineEvent, now_iso, sse_to_event
from ..core.textutil import normalize_md

REPORT_AGENTS = [
    # (文件名 stem, 展示名, 阶段, 顺序)
    ("market_report", "市场分析师", "分析师", 10),
    ("fundamentals_report", "基本面分析师", "分析师", 11),
    ("news_report", "新闻分析师", "分析师", 12),
    ("sentiment_report", "情绪分析师", "分析师", 13),
    ("research_team_decision", "研究团队（多空辩论）", "研究", 20),
    ("trader_investment_plan", "交易员", "交易", 30),
    ("investment_plan", "投资计划", "交易", 31),
    ("risk_management_decision", "风控经理", "风控", 40),
    ("final_trade_decision", "投资组合经理", "管理", 50),
]


def capture(cfg, client, store, task_id: str, live: bool = False) -> Timeline:
    tl = Timeline(task_id=task_id)

    status = {}
    try:
        status = client.get_status(task_id)
    except Exception:
        pass
    tl.symbol = str(status.get("symbol") or status.get("stock_code") or "")
    tl.meta = {
        "status": status.get("status"),
        "depth": status.get("research_depth") or status.get("depth"),
        "models": {
            "quick": status.get("quick_think_llm") or status.get("quick_model"),
            "deep": status.get("deep_think_llm") or status.get("deep_model"),
        },
    }

    if live and status.get("status") not in {"completed", "failed"}:
        for payload in client.iter_sse(task_id):
            if ev := sse_to_event(task_id, payload):
                tl.add(ev)
                store.add_event(task_id, ev.ts, ev.phase, ev.agent, ev.content[:4000], ev.meta)
        status = client.get_status(task_id)
        tl.meta["status"] = status.get("status")

    # 步骤骨架
    for step in status.get("steps") or []:
        name = step.get("name") or step.get("step_name") or ""
        if not name:
            continue
        tl.add(TimelineEvent(
            ts=step.get("timestamp") or step.get("start_time") or now_iso(),
            phase=_phase_of_name(name), agent=name,
            content=str(step.get("description") or step.get("message") or ""),
            kind="step", meta={"status": step.get("status"), "duration": step.get("duration")},
        ))

    # 文件卷：agent 报告内容
    ta_dir = cfg.get("data.ta_dir", "")
    if ta_dir:
        _add_report_files(Path(ta_dir), tl, tl.symbol, task_id)

    # 结果里的报告文本（文件卷缺失时的兜底）
    if not any(e.kind == "report" for e in tl.events):
        try:
            result = client.get_result(task_id)
            text = result.get("report") or result.get("full_report") or result.get("report_content") or ""
            if isinstance(text, str) and text.strip():
                tl.add(TimelineEvent(now_iso(), "管理", "投资组合经理", text, kind="report",
                                     meta={"source": "api"}))
        except Exception:
            pass

    for ev in tl.events:
        store.add_event(task_id, ev.ts, ev.phase, ev.agent, ev.content[:6000], ev.meta)
    return tl


def _phase_of_name(name: str) -> str:
    from ..core.events import _phase_of
    return _phase_of(name)


def find_reports_dir(ta_dir: Path, symbol: str) -> Optional[Path]:
    """定位该股票最近一次分析的 reports 目录（供 debate 等模块复用）。"""
    base = ta_dir / "analysis_results"
    for root in ([base / symbol] if symbol else []) + [base]:
        if not root.is_dir():
            continue
        for sym_dir in ([root] if symbol else sorted(root.iterdir(), reverse=True)):
            if not sym_dir.is_dir():
                continue
            days = sorted([p for p in sym_dir.iterdir() if p.is_dir()], reverse=True)
            for day in days:
                reports = day / "reports"
                if reports.is_dir():
                    return reports
    return None


def _add_report_files(ta_dir: Path, tl: Timeline, symbol: str, task_id: str) -> None:
    base = ta_dir / "analysis_results"
    candidates = [base / symbol] if symbol else []
    candidates.append(base)
    for root in candidates:
        if not root.is_dir():
            continue
        for sym_dir in ([root] if symbol else sorted(root.iterdir(), reverse=True)):
            if not sym_dir.is_dir():
                continue
            day = sorted([p for p in sym_dir.iterdir() if p.is_dir()], reverse=True)
            if not day:
                continue
            reports = day[0] / "reports"
            if not reports.is_dir():
                continue
            if not tl.symbol:
                tl.symbol = sym_dir.name
            tl.meta["report_date"] = day[0].name
            meta_file = day[0] / "analysis_metadata.json"
            if meta_file.is_file():
                try:
                    md_meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    tl.meta.setdefault("depth", md_meta.get("research_depth"))
                    if not tl.meta.get("models", {}).get("quick"):
                        tl.meta["models"] = {"quick": md_meta.get("quick_model", ""),
                                             "deep": md_meta.get("deep_model", "")}
                    tl.meta["analysts"] = md_meta.get("analysts", [])
                except (json.JSONDecodeError, OSError):
                    pass
            found = {p.stem: p for p in reports.glob("*.md")}
            for stem, agent, phase, order in REPORT_AGENTS:
                if stem not in found:
                    continue
                text = normalize_md(found[stem].read_text(encoding="utf-8", errors="replace")).strip()
                if not text:
                    continue
                tl.add(TimelineEvent(
                    ts=now_iso(), phase=phase, agent=agent, content=text, kind="report",
                    meta={"source": str(found[stem]), "order": order, "file": stem},
                ))
            _parse_message_tool(day[0] / "message_tool.log", tl)
            return


def _parse_message_tool(path: Path, tl: Timeline) -> None:
    """尽力解析框架消息日志；空文件/格式不符则静默跳过。"""
    if not path.is_file() or path.stat().st_size == 0:
        return
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    import re
    blocks = re.split(r"\n[*=\-]{8,}\n", raw)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith("{"):
            try:
                obj = json.loads(block)
                agent = obj.get("agent_type") or obj.get("sender") or "agent"
                content = obj.get("content") or obj.get("message") or ""
                tl.add(TimelineEvent(now_iso(), _phase_of_name(agent), agent, str(content),
                                     kind="message", meta={"source": "message_tool"}))
                continue
            except json.JSONDecodeError:
                pass
        m = re.match(r"^([\w\u4e00-\u9fff ()]+):\s*(.+)", block, re.S)
        if m:
            agent, content = m.group(1).strip(), m.group(2)
            tl.add(TimelineEvent(now_iso(), _phase_of_name(agent), agent, content,
                                 kind="message", meta={"source": "message_tool"}))

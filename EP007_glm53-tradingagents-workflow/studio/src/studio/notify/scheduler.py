"""cron 调度器：定时 分析 -> digest -> 推送 管道。容器常驻进程。"""
from __future__ import annotations

import signal
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import croniter
from rich.console import Console

from ..core.client import TradingAgentsClient
from ..core.config import Config
from ..core.store import Store
from ..digest import condense, fetch_report
from .channels.base import registry
from .render import render_digest_message, render_task_event

console = Console()


def build_channels(cfg: Config):
    """构建推送渠道。键支持 "type#别名" 形式，同类型可配多个实例（如两个飞书群）。"""
    channels = []
    for name, options in (cfg.get("notify.channels", {}) or {}).items():
        ctype, _, alias = name.partition("#")
        try:
            channels.append(registry.build(ctype, options or {}, alias=alias))
        except Exception as e:
            console.print(f"[yellow]⚠ 跳过渠道 {name}: {e}[/yellow]")
    return channels


def push_all(channels, title: str, body: str, markdown: str = "",
             buttons: list | None = None) -> list[str]:
    results = []
    for ch in channels:
        try:
            ch.send(title, body, markdown, buttons=buttons)
            results.append(f"✓ {ch.alias or ch.name}")
        except Exception as e:
            results.append(f"✗ {ch.alias or ch.name}: {e}")
    return results


def _report_urls(cfg, task_id: str) -> tuple[str, str, str]:
    """报告详情服务的链接前缀来自配置；未配置则返回空（卡片就不带按钮）。"""
    prefix = str(cfg.get("notify.report_url_prefix", "") or "").rstrip("/")
    if not prefix:
        return "", "", ""
    return (f"{prefix}/report/{task_id}",
            f"{prefix}/debate/{task_id}",
            f"{prefix}/replay/{task_id}")


def run_pipeline(
    cfg: Config,
    store: Store,
    symbol: str,
    depth: str = "标准",
    pipeline: list[str] | None = None,
    quick_model: str | None = None,
    deep_model: str | None = None,
    poll: float = 10.0,
) -> dict[str, Any]:
    """完整管道：提交分析 -> 等完成 -> (digest -> notify)。返回执行摘要。"""
    pipeline = pipeline or ["digest", "notify"]
    client = TradingAgentsClient(cfg)
    summary: dict[str, Any] = {"symbol": symbol, "depth": depth, "pipeline": pipeline}
    try:
        task_id = client.submit_analysis(symbol, depth=depth, quick_model=quick_model, deep_model=deep_model)
        summary["task_id"] = task_id
        console.print(f"[cyan]▶ 分析已提交: {symbol} ({depth}) task={task_id}[/cyan]")
        status = client.wait_for_task(task_id, poll_interval=poll)
        summary["status"] = status.get("status")
        store.upsert_run(
            task_id, symbol=symbol, depth=depth,
            quick_model=quick_model or "", deep_model=deep_model or "",
            status=status.get("status"), error=status.get("error"),
        )

        channels = build_channels(cfg) if "notify" in pipeline else []
        name = ""
        try:
            name = client.stock_name(symbol)
        except Exception:
            pass
        if status.get("status") == "completed":
            if "digest" in pipeline:
                doc = fetch_report(client, task_id, _ta_dir(cfg))
                text, usage = condense(cfg, doc.text, symbol=symbol, depth=depth)
                store.save_digest(task_id, symbol, cfg.get("llm.model"), doc.chars, text)
                summary["digest"] = text
                summary["input_chars"] = doc.chars
                summary["stock_name"] = name
                console.print(f"[green]✓ 简报已生成（{doc.chars} 字 -> {len(text)} 字）[/green]")
                if channels:
                    report_url, debate_url, replay_url = _report_urls(cfg, task_id)
                    title, body, md, buttons = render_digest_message(
                        symbol, text, report_url, name=name,
                        replay_url=replay_url, debate_url=debate_url)
                    summary["notify"] = push_all(channels, title, body, md, buttons=buttons)
            elif channels:
                title, body, md = render_task_event(symbol, "completed", name=name)
                summary["notify"] = push_all(channels, title, body, md)
        else:
            if channels:
                title, body, md = render_task_event(symbol, status.get("status", "failed"),
                                                    status.get("error"), name=name)
                summary["notify"] = push_all(channels, title, body, md)
    finally:
        client.close()
    return summary


def _ta_dir(cfg: Config):
    from pathlib import Path
    raw = cfg.get("data.ta_dir", "")
    return Path(raw) if raw else None


def serve(cfg: Config) -> None:
    """常驻调度循环（studio cron）。"""
    tz_name = cfg.get("cron.timezone", "Asia/Shanghai")
    tz = ZoneInfo(tz_name)
    jobs = cfg.get("cron.jobs", []) or []
    if not jobs:
        console.print("[yellow]studio.yaml 里没有配置 cron.jobs，调度器空转退出[/yellow]")
        return

    iters = []
    for job in jobs:
        schedule = job.get("schedule", "")
        if not croniter.croniter.is_valid(schedule):
            console.print(f"[red]✗ 任务 {job.get('name')} 的 cron 表达式非法: {schedule}[/red]")
            continue
        iters.append((job, croniter.croniter(schedule, datetime.now(tz))))
    if not iters:
        return
    console.print(f"[bold green]studio 调度器启动（{tz_name}）[/bold green]")
    for job, _ in iters:
        console.print(f"  ⏰ {job.get('name')}: {job.get('schedule')} -> {job.get('symbol')}")

    store = Store(cfg.store_path())
    stopping = {"flag": False}

    def _stop(signum, frame):
        stopping["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while not stopping["flag"]:
        now = datetime.now(tz)
        for job, it in iters:
            nxt = it.get_next(datetime)
            if nxt <= now:
                console.print(f"\n[cyan]⏰ 触发任务: {job.get('name')}[/cyan]")
                try:
                    summary = run_pipeline(
                        cfg, store,
                        symbol=str(job.get("symbol", "")),
                        depth=job.get("depth", cfg.get("compare.defaults.depth", "标准")),
                        pipeline=job.get("pipeline", ["digest", "notify"]),
                        poll=float(cfg.get("compare.defaults.poll_interval", 10)),
                    )
                    console.print(f"[green]✓ 任务完成: {summary.get('status')}[/green]")
                except Exception as e:
                    console.print(f"[red]✗ 任务失败: {e}[/red]")
        time.sleep(20)
    console.print("[yellow]调度器已停止[/yellow]")

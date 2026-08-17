"""多模型对比执行器：同一股票、同一深度，N 个模型并跑（限流）。"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console

from ..core.client import TradingAgentsClient

console = Console()


@dataclass
class ModelRun:
    model: str
    task_id: str = ""
    status: str = "pending"
    wall_s: float = 0.0
    error: str = ""
    steps: list[dict] = field(default_factory=list)
    result: dict = field(default_factory=dict)
    started_at: str = ""


def run_one(cfg, model: str, symbol: str, depth: str, analysts: list[str], poll: float,
             analysis_date: str | None = None) -> ModelRun:
    """单模型一次完整分析（每个线程独立客户端，避免共享连接）。"""
    run = ModelRun(model=model)
    client = TradingAgentsClient(cfg)
    try:
        run.task_id = client.submit_analysis(
            symbol, depth=depth, analysts=analysts, quick_model=model, deep_model=model,
            analysis_date=analysis_date,
        )
        run.started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        t0 = time.time()
        status = client.wait_for_task(run.task_id, poll_interval=poll)
        run.wall_s = round(time.time() - t0, 1)
        run.status = status.get("status", "unknown")
        run.steps = status.get("steps") or []
        run.error = status.get("error") or status.get("message") or ""
        if run.status == "completed":
            try:
                run.result = client.get_result(run.task_id)
            except Exception as e:
                run.error = f"取结果失败: {e}"
    except Exception as e:
        run.status = "failed"
        run.error = str(e)
    finally:
        client.close()
    return run


def run_compare(
    cfg,
    symbol: str,
    models: list[str],
    depth: str,
    analysts: list[str],
    concurrency: int = 2,
    poll: float = 10.0,
    analysis_date: str | None = None,
) -> list[ModelRun]:
    console.print(
        f"[bold]compare: {symbol} / {depth} / {len(models)} 个模型（并发 {concurrency}）[/bold]"
    )
    runs: list[ModelRun] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {
            pool.submit(run_one, cfg, m, symbol, depth, analysts, poll, analysis_date): m
            for m in models
        }
        for fut in as_completed(futures):
            run = fut.result()
            runs.append(run)
            mark = "✓" if run.status == "completed" else "✗"
            console.print(
                f"  {mark} {run.model:<24} {run.status:<10} {run.wall_s:>7.1f}s "
                f"{run.error[:60] if run.error and run.status != 'completed' else ''}"
            )
    # 保持输入顺序输出
    order = {m: i for i, m in enumerate(models)}
    runs.sort(key=lambda r: order.get(r.model, 99))
    return runs

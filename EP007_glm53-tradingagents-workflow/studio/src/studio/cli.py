"""studio 统一命令行入口。

  studio doctor / digest / notify / compare / replay / cron
"""
from __future__ import annotations

import json
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .core.client import TradingAgentsClient
from .core.config import Config
from .core.store import Store

app = typer.Typer(no_args_is_help=True, add_completion=False,
                  help="TradingAgents-CN 增强套件：digest 提炼 / notify 推送 / compare 对比 / replay 回放")
console = Console()

digest_app = typer.Typer(help="把长报告提炼成 200 字开盘简报")
notify_app = typer.Typer(help="推送到 IM 渠道（飞书/webhook）")
compare_app = typer.Typer(help="多模型同题对比")
replay_app = typer.Typer(help="把智能体辩论过程渲染成可回放 HTML")
app.add_typer(digest_app, name="digest")
app.add_typer(notify_app, name="notify")
app.add_typer(compare_app, name="compare")
app.add_typer(replay_app, name="replay")

CONFIG_OPTION = typer.Option(None, "--config", "-c", help="studio.yaml 路径（默认 STUDIO_CONFIG 或当前目录）")


def _cfg(config: Optional[str]) -> Config:
    if config:
        return Config.load(Path(config))
    return Config.load_default()


def _client(cfg: Config) -> TradingAgentsClient:
    return TradingAgentsClient(cfg)


def _store(cfg: Config) -> Store:
    return Store(cfg.store_path())


# ---------------- doctor ----------------
@app.command()
def doctor(config: Optional[str] = CONFIG_OPTION):
    """自检：API 连通 / 登录 / 数据卷 / LLM 配置 / 推送渠道。"""
    cfg = _cfg(config)
    table = Table(title=f"studio doctor v{__version__}")
    table.add_column("检查项", justify="left")
    table.add_column("结果", justify="left")

    client = TradingAgentsClient(cfg)
    try:
        health = client.health()
        table.add_row("API /api/health", f"[green]✓[/green] {health.get('service', 'ok')} v{health.get('version', '?')}")
    except Exception as e:
        table.add_row("API /api/health", f"[red]✗ {e}[/red]")
        console.print(table)
        raise typer.Exit(1)
    try:
        client.login()
        table.add_row("登录", f"[green]✓[/green] 用户 {cfg.get('api.username')}")
    except Exception as e:
        table.add_row("登录", f"[red]✗ {e}[/red]")

    ta_dir = cfg.get("data.ta_dir", "")
    if ta_dir:
        p = Path(ta_dir)
        ok = p.is_dir() and (p / "analysis_results").exists()
        table.add_row("数据卷 ta_dir", f"[green]✓[/green] {ta_dir}" if ok else f"[yellow]⚠ 目录存在但缺 analysis_results: {ta_dir}")
    else:
        table.add_row("数据卷 ta_dir", "[dim]未配置（replay/digest 文件兜底不可用）[/dim]")

    llm_key = str(cfg.get("llm.api_key", "") or "")
    table.add_row("digest LLM",
                  f"[green]✓[/green] {cfg.get('llm.model')} @ {cfg.get('llm.base_url')}" if llm_key and not llm_key.startswith("your_")
                  else "[red]✗ llm.api_key 未配置[/red]")

    channels = cfg.get("notify.channels", {}) or {}
    if channels:
        from .notify.scheduler import build_channels
        built = build_channels(cfg)
        names = ", ".join(c.name for c in built)
        if built:
            missing = set(channels) - {c.name for c in built}
            extra = f"（{','.join(sorted(missing))} 配置不全）" if missing else ""
            table.add_row("推送渠道", f"[green]✓[/green] {names} {extra}")
        else:
            table.add_row("推送渠道", "[yellow]⚠ 已配置但均不可用（见上方警告）[/yellow]")
    else:
        table.add_row("推送渠道", "[dim]未配置[/dim]")

    jobs = cfg.get("cron.jobs", []) or []
    table.add_row("cron 任务", f"{len(jobs)} 个" if jobs else "[dim]无[/dim]")
    console.print(table)


# ---------------- digest ----------------
@digest_app.command("run")
def digest_run(
    task_id: Optional[str] = typer.Argument(None, help="分析任务 ID"),
    file: Optional[Path] = typer.Option(None, "--file", help="直接提炼本地 markdown 文件"),
    symbol: Optional[str] = typer.Option(None, "--symbol", help="按股票代码找最近一次分析产物"),
    save: bool = typer.Option(False, "--save", help="存入 studio 数据库"),
    config: Optional[str] = CONFIG_OPTION,
):
    """提炼报告 -> 约 200 字开盘简报。三选一：task_id / --file / --symbol"""
    from .digest import condense, fetch_report
    from .digest.fetcher import latest_task_dir

    cfg = _cfg(config)
    if file:
        text = file.read_text(encoding="utf-8", errors="replace")
        sym = symbol or ""
        source = str(file)
    elif task_id:
        client = _client(cfg)
        try:
            doc = fetch_report(client, task_id, _ta_dir_or_none(cfg))
        finally:
            client.close()
        text, sym, source = doc.text, doc.symbol or (symbol or ""), f"task:{task_id}"
    elif symbol:
        ta_dir = _ta_dir_or_none(cfg)
        if not ta_dir:
            console.print("[red]--symbol 需要 data.ta_dir 配置[/red]")
            raise typer.Exit(1)
        day = latest_task_dir(ta_dir, symbol)
        if not day:
            console.print(f"[red]在 {ta_dir} 下没找到 {symbol} 的分析产物[/red]")
            raise typer.Exit(1)
        reports = day / "reports"
        files = sorted(reports.glob("*.md")) if reports.is_dir() else []
        text = "\n\n---\n\n".join(f"## {p.stem}\n{p.read_text(encoding='utf-8', errors='replace')}" for p in files)
        sym, source = symbol, str(day)
    else:
        console.print("[red]请提供 task_id、--file 或 --symbol 之一[/red]")
        raise typer.Exit(1)

    if not text.strip():
        console.print("[red]报告内容为空[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]来源: {source}（{len(text)} 字）-> 提炼中…[/dim]")
    try:
        brief, usage = condense(cfg, text, symbol=sym)
    except Exception as e:
        console.print(f"[red]提炼失败: {e}[/red]")
        raise typer.Exit(1)

    console.rule("[bold green]开盘前简报[/bold green]")
    console.print(brief)
    console.rule()
    console.print(f"[dim]{len(text)} 字 -> {len(brief)} 字；token: {json.dumps(usage, ensure_ascii=False)}[/dim]")
    if save:
        _store(cfg).save_digest(task_id or "", sym, str(cfg.get("llm.model")), len(text), brief)
        console.print("[green]✓ 已存入 studio.db[/green]")


def _ta_dir_or_none(cfg: Config):
    raw = cfg.get("data.ta_dir", "")
    return Path(raw) if raw else None


# ---------------- notify ----------------
@notify_app.command("test")
def notify_test(config: Optional[str] = CONFIG_OPTION):
    """向所有已配置渠道发一条测试消息。"""
    from .notify.scheduler import build_channels, push_all
    cfg = _cfg(config)
    channels = build_channels(cfg)
    if not channels:
        console.print("[yellow]没有可用渠道，请配置 notify.channels（feishu/webhook）[/yellow]")
        raise typer.Exit(1)
    for line in push_all(channels, "✅ studio 测试消息", "如果你看到这条，说明推送渠道配置正确。",
                         "**studio** 推送渠道配置正确 🎉"):
        console.print(line)


@notify_app.command("send")
def notify_send(
    task_id: str = typer.Argument(..., help="分析任务 ID（优先发 digest 简报，失败发原文摘要）"),
    config: Optional[str] = CONFIG_OPTION,
):
    """把指定任务的报告（或其简报）推送到所有渠道。"""
    from .digest import condense, fetch_report
    from .notify.render import render_digest_message
    from .notify.scheduler import build_channels, push_all, _report_urls
    cfg = _cfg(config)
    channels = build_channels(cfg)
    if not channels:
        console.print("[yellow]没有可用渠道[/yellow]")
        raise typer.Exit(1)
    client = _client(cfg)
    try:
        doc = fetch_report(client, task_id, _ta_dir_or_none(cfg))
        name = client.stock_name(doc.symbol or "")
    finally:
        client.close()
    try:
        brief, _ = condense(cfg, doc.text, symbol=doc.symbol)
        report_url, debate_url, replay_url = _report_urls(cfg, task_id)
        title, body, md, buttons = render_digest_message(
            doc.symbol, brief, report_url, name=name,
            replay_url=replay_url, debate_url=debate_url)
    except Exception:
        title, body, md, buttons = f"📄 {doc.symbol} 分析报告", doc.text[:1500], doc.text[:3000], []
    for line in push_all(channels, title, body, md, buttons=buttons):
        console.print(line)


# ---------------- compare ----------------
@compare_app.command("run")
def compare_run(
    symbol: str = typer.Argument(..., help="6 位股票代码"),
    models: str = typer.Option(..., "--models", "-m", help="逗号分隔的模型列表"),
    depth: Optional[str] = typer.Option(None, "--depth", "-d", help="研究深度（默认取配置）"),
    concurrency: int = typer.Option(0, "--concurrency", "-j", help="并发数（默认取配置）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只打印计划，不真实调用"),
    date: Optional[str] = typer.Option(None, "--date", help="分析日期 YYYY-MM-DD（默认今天；周末建议指定上一交易日）"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir", help="结果输出目录（默认 data/exports）"),
    config: Optional[str] = CONFIG_OPTION,
):
    """同一支股票跑多个模型，产出硬指标对比表。"""
    from .compare import metrics as M
    from .compare import report as R
    from .compare.runner import run_compare
    cfg = _cfg(config)
    aliases: dict = cfg.get("compare.aliases", {}) or {}
    reverse = {v: k for k, v in aliases.items()}
    model_list = [reverse.get(m.strip(), m.strip()) for m in models.split(",") if m.strip()]
    d = cfg.get("compare.defaults", {}) or {}
    depth = depth or d.get("depth", "标准")
    analysts = d.get("analysts") or ["market", "fundamentals", "news"]
    concurrency = concurrency or int(d.get("concurrency", 2) or 2)
    poll = float(d.get("poll_interval", 10) or 10)

    display = [aliases.get(m, m) for m in model_list]
    console.print(f"[bold]compare plan[/bold]: {symbol} | {depth} | models={display} | 并发={concurrency}")
    if dry_run:
        console.print("[yellow]--dry-run：不执行真实分析[/yellow]")
        return

    bench_start = datetime.now(timezone.utc)
    runs = run_compare(cfg, symbol, model_list, depth, analysts, concurrency, poll, analysis_date=date)
    client = _client(cfg)
    try:
        rows = M.build_rows(cfg, client, runs, bench_start)
    finally:
        client.close()

    meta = {"symbol": symbol, "depth": depth, "created_at": bench_start.isoformat(timespec="seconds")}
    R.render_terminal(rows, f"模型对比 {symbol}（{depth}）")
    md = R.render_markdown(rows, meta)
    out = out_dir or (cfg.exports_dir() / "compare")
    stem = f"compare_{symbol}_{bench_start.strftime('%Y%m%d_%H%M%S')}"
    paths = R.write_outputs(md, R.render_csv(rows), out, stem)

    store = _store(cfg)
    store.save_benchmark(symbol, depth, rows, md)
    for run in runs:
        store.upsert_run(run.task_id, symbol=symbol, depth=depth,
                         quick_model=run.model, deep_model=run.model,
                         status=run.status, wall_s=run.wall_s, error=run.error)
    console.print(f"[green]✓ 对比结果:[/green] {paths['markdown']} , {paths['csv']}")


# ---------------- replay ----------------
@replay_app.command("capture")
def replay_capture(
    task_id: str = typer.Argument(...),
    live: bool = typer.Option(False, "--live", help="任务运行中时挂 SSE 实时抓"),
    config: Optional[str] = CONFIG_OPTION,
):
    """抓取一次分析的过程，归档进 studio.db。"""
    from .replay import capture
    cfg = _cfg(config)
    client = _client(cfg)
    store = _store(cfg)
    try:
        tl = capture(cfg, client, store, task_id, live=live)
    finally:
        client.close()
    console.print(f"[green]✓ 已归档 {len(tl.events)} 条事件[/green]（{tl.symbol or '?'} · {tl.meta.get('status')}）")


@replay_app.command("debate")
def replay_debate(
    task_id: str = typer.Argument(...),
    out: Optional[Path] = typer.Option(None, "--out", help="输出 HTML 路径"),
    config: Optional[str] = CONFIG_OPTION,
):
    """多空辩论专用回放：聊天流一来一回 + 话题对垒双视图。"""
    from .replay.debate import build_debate_data
    from .replay.debate_render import write_debate_html
    cfg = _cfg(config)
    client = _client(cfg)
    try:
        data = build_debate_data(cfg, client, task_id)
    finally:
        client.close()
    if not data:
        console.print("[red]未找到辩论数据（需要 data.ta_dir 且该任务产出 research/risk 报告）[/red]")
        raise typer.Exit(1)
    out = out or (cfg.exports_dir() / "debate" / f"debate_{task_id[:8]}.html")
    path = write_debate_html(data, out, replay_url=f"/replay/{task_id}")
    console.print(f"[green]✓ 辩论回放已导出:[/green] {path}")
    console.print(f"[dim]{len(data['turns'])} 次发言 · {len(data.get('matchups') or [])} 个交锋话题[/dim]")


@replay_app.command("export")
def replay_export(
    task_id: str = typer.Argument(...),
    out: Optional[Path] = typer.Option(None, "--out", help="输出 HTML 路径"),
    config: Optional[str] = CONFIG_OPTION,
):
    """导出单文件回放 HTML（可直接发给别人）。"""
    from .replay import capture, write_html
    cfg = _cfg(config)
    client = _client(cfg)
    store = _store(cfg)
    try:
        tl = capture(cfg, client, store, task_id)
    finally:
        client.close()
    if not tl.events:
        console.print("[red]没有抓到任何事件（任务不存在或数据源为空）[/red]")
        raise typer.Exit(1)
    out = out or (cfg.exports_dir() / "replay" / f"replay_{tl.symbol or 'task'}_{task_id[:8]}.html")
    path = write_html(tl, out)
    console.print(f"[green]✓ 回放已导出:[/green] {path}")
    console.print("[dim]双击打开，或直接把这一个文件发给别人[/dim]")


@replay_app.command("serve")
def replay_serve(
    task_id: str = typer.Argument(...),
    port: int = typer.Option(8899, "--port", "-p"),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
    config: Optional[str] = CONFIG_OPTION,
):
    """本地起 HTTP 预览回放页。"""
    import http.server
    import functools
    from .replay import capture, render_html
    cfg = _cfg(config)
    client = _client(cfg)
    store = _store(cfg)
    try:
        tl = capture(cfg, client, store, task_id)
    finally:
        client.close()
    html_bytes = render_html(tl).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.end_headers()
            self.wfile.write(html_bytes)

        def log_message(self, *args):
            pass

    url = f"http://127.0.0.1:{port}/"
    console.print(f"[green]▶ 回放预览:[/green] {url}（Ctrl+C 退出）")
    if open_browser:
        webbrowser.open(url)
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()


# ---------------- report ----------------
report_app = typer.Typer(help="报告详情服务：飞书卡片按钮的跳转目标")
app.add_typer(report_app, name="report")


@report_app.command("serve")
def report_serve(
    port: int = typer.Option(8890, "--port", "-p"),
    host: str = typer.Option("0.0.0.0", "--host"),
    config: Optional[str] = CONFIG_OPTION,
):
    """常驻 HTTP 服务：/report/<task_id> 完整报告，/replay/<task_id> 辩论回放。"""
    from .notify.report_server import serve as _serve
    cfg = _cfg(config)
    console.print(f"[green]▶ 报告服务:[/green] http://localhost:{port}/（Ctrl+C 退出）")
    _serve(cfg, port=port, host=host)


# ---------------- cron ----------------
@app.command("cron")
def cron(config: Optional[str] = CONFIG_OPTION):
    """常驻调度：按 studio.yaml 的 cron.jobs 定时 分析->digest->推送。"""
    from .notify.scheduler import serve
    serve(_cfg(config))


def main():
    app()


if __name__ == "__main__":
    main()

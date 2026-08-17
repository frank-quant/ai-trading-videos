"""报告详情服务：飞书卡片里"查看完整报告"按钮的落点。

- GET /                      -> 索引页（最近任务列表）
- GET /report/{task_id}      -> 完整报告 HTML（左侧子报告导航 + 右侧内容；手机为抽屉）
- GET /replay/{task_id}      -> 辩论回放 HTML（复用 replay 模块）

页面按需生成、落盘缓存到 data/exports/。
"""
from __future__ import annotations

import html
import http.server
import re
import threading
from pathlib import Path
from typing import Optional

from ..digest.fetcher import fetch_report
from ..replay import capture as replay_capture
from ..replay.capture import REPORT_AGENTS
from ..replay.render import render_html as replay_html

_STEM_LABELS = {stem: label for stem, label, _phase, _order in REPORT_AGENTS}
_STEM_ORDER = {stem: order for stem, _label, _phase, order in REPORT_AGENTS}

_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#0f1117; --panel:#171a23; --line:#262b38; --fg:#dbe2f0; --dim:#8b93a7;
          --accent:#4f8cff; --navw:232px; }
  * { box-sizing:border-box; }
  html { -webkit-text-size-adjust:100%; scroll-behavior:smooth; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:16px/1.8 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
         word-break:break-word; overflow-wrap:anywhere; }

  header { position:sticky; top:0; background:var(--panel); border-bottom:1px solid var(--line);
            padding:10px 16px; display:flex; align-items:center; gap:10px; z-index:30; }
  header .menu-btn { background:#20242f; color:var(--fg); border:1px solid var(--line);
            border-radius:8px; padding:7px 12px; font-size:14px; cursor:pointer; flex:none; }
  header .titles { min-width:0; }
  header h1 { font-size:16px; margin:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  header .sub { color:var(--dim); font-size:11.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

  /* ---- 左侧导航 / 右侧内容 ---- */
  nav#toc { position:fixed; top:0; left:0; bottom:0; width:var(--navw);
            background:var(--panel); border-right:1px solid var(--line);
            padding:14px 10px 24px; overflow-y:auto; z-index:40;
            transition:transform .25s ease; }
  nav#toc .toc-head { font-size:12px; color:var(--dim); letter-spacing:2px;
            padding:4px 10px 10px; border-bottom:1px solid var(--line); margin-bottom:8px; }
  nav#toc a { display:block; color:var(--fg); text-decoration:none; font-size:13.5px;
            line-height:1.45; padding:8px 10px; border-radius:8px; margin:2px 0;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  nav#toc a .idx { color:var(--dim); font-size:11px; margin-right:6px; }
  nav#toc a:hover { background:#20242f; }
  nav#toc a.active { background:rgba(79,140,255,.16); color:var(--accent); }
  #backdrop { display:none; position:fixed; inset:0; background:rgba(0,0,0,.5); z-index:35; }

  main { margin-left:var(--navw); padding:22px 26px 80px; max-width:900px; }
  .section { scroll-margin-top:64px; padding-top:6px; }
  .section + .section { border-top:1px solid var(--line); margin-top:30px; padding-top:24px; }
  .section .sec-tag { display:inline-block; font-size:11.5px; color:var(--accent);
            border:1px solid rgba(79,140,255,.4); border-radius:20px; padding:2px 12px;
            margin-bottom:6px; letter-spacing:1px; }

  .md h1,.md h2,.md h3 { color:#fff; border-bottom:1px solid var(--line); padding-bottom:6px; margin-top:1.7em; line-height:1.5; }
  .md h1 { font-size:19px; } .md h2 { font-size:17px; } .md h3 { font-size:15.5px; }
  .md p { margin:0.8em 0; }
  .md strong { color:#fff; }
  .md table { display:block; overflow-x:auto; border-collapse:collapse; width:100%;
              margin:12px 0; font-size:13.5px; -webkit-overflow-scrolling:touch; }
  .md th,.md td { border:1px solid var(--line); padding:7px 11px; text-align:left; white-space:nowrap; }
  .md th { background:#1d2230; color:#fff; }
  .md tr:nth-child(even) td { background:rgba(255,255,255,.02); }
  .md code { background:var(--panel); padding:1px 6px; border-radius:4px; font-size:13px; }
  .md pre { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; overflow-x:auto; }
  .md pre code { background:none; padding:0; }
  .md blockquote { border-left:3px solid var(--accent); margin:12px 0; padding:4px 14px; color:var(--dim); }
  .md ul,.md ol { padding-left:1.4em; }
  .md li { margin:0.35em 0; }
  .md img { max-width:100%; }
  .md hr { border:none; border-top:1px solid var(--line); margin:22px 0; }
  footer { margin-left:var(--navw); text-align:center; color:var(--dim); font-size:11px; padding:18px; }
  a { color:var(--accent); }

  /* ---- 手机：导航收成左侧抽屉 ---- */
  @media (max-width:700px) {
    body { font-size:15.5px; }
    nav#toc { transform:translateX(-100%); box-shadow:8px 0 30px rgba(0,0,0,.45);
              width:min(78vw, 300px); }
    body.nav-open nav#toc { transform:translateX(0); }
    body.nav-open #backdrop { display:block; }
    main { margin-left:0; padding:14px 14px 60px; }
    footer { margin-left:0; }
    header h1 { font-size:15px; }
    .md h1 { font-size:18px; } .md h2 { font-size:16px; }
    .md th,.md td { padding:6px 9px; font-size:13px; }
  }
</style>
</head>
<body>
<header>
  <button class="menu-btn" id="menuBtn" aria-label="报告目录">☰ 目录</button>
  <div class="titles">
    <h1>__TITLE__</h1>
    <div class="sub">__SUB__</div>
  </div>
</header>
<div id="backdrop"></div>
<nav id="toc">
  <div class="toc-head">报告目录</div>
  __NAV__
</nav>
<main>
__BODY__
</main>
<footer>TradingAgents Studio · report server</footer>
<script>
(function () {
  var body = document.body, btn = document.getElementById('menuBtn'),
      backdrop = document.getElementById('backdrop');
  function close() { body.classList.remove('nav-open'); }
  btn.addEventListener('click', function () { body.classList.toggle('nav-open'); });
  backdrop.addEventListener('click', close);
  document.querySelectorAll('#toc a').forEach(function (a) {
    a.addEventListener('click', close);
  });
  // 滚动高亮当前所在子报告
  var links = Array.prototype.slice.call(document.querySelectorAll('#toc a[href^="#sec-"]'));
  var secs = links.map(function (a) { return document.getElementById(a.getAttribute('href').slice(1)); });
  if ('IntersectionObserver' in window && secs.length) {
    var current = 0;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          var i = secs.indexOf(e.target);
          if (i >= 0) {
            current = i;
            links.forEach(function (a, j) { a.classList.toggle('active', j === i); });
          }
        }
      });
    }, { rootMargin: '-15% 0px -70% 0px' });
    secs.forEach(function (s) { if (s) io.observe(s); });
    links[current] && links[current].classList.add('active');
  }
})();
</script>
</body>
</html>
"""


def _md_to_html(text: str) -> str:
    """轻量 markdown -> HTML（标题/表格/粗斜体/代码/引用/列表够用，无需重依赖）。"""
    try:
        import markdown
        return markdown.markdown(text, extensions=["tables", "fenced_code"])
    except ImportError:
        out = []
        in_table = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("|") and stripped.endswith("|"):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                if set("".join(cells)) <= set("-: "):
                    continue
                tag = "th" if not in_table else "td"
                if not in_table:
                    out.append("<table>")
                    in_table = True
                out.append("<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells) + "</tr>")
                continue
            if in_table:
                out.append("</table>")
                in_table = False
            if stripped.startswith("#"):
                m = re.match(r"^(#{1,6})\s+(.*)", stripped)
                if m:
                    level = min(len(m.group(1)) + 1, 6)
                    out.append(f"<h{level}>{html.escape(m.group(2))}</h{level}>")
                    continue
            if stripped.startswith(">"):
                out.append(f"<blockquote>{html.escape(stripped.lstrip('> '))}</blockquote>")
                continue
            out.append(f"<p>{html.escape(line) if stripped else '&nbsp;'}</p>")
        if in_table:
            out.append("</table>")
        return "\n".join(out)


def split_sections(md_text: str) -> list[tuple[str, str]]:
    """把 fetcher 拼接的 '## <stem>\\n...' 全文切成 (label, markdown) 列表。"""
    parts = re.split(r"(?m)^## ([A-Za-z0-9_]+)\s*$", md_text)
    found: list[tuple[int, str, str]] = []
    for i in range(1, len(parts) - 1, 2):
        stem = parts[i]
        body = (parts[i + 1] if i + 1 < len(parts) else "").replace("\n---\n", "\n").strip()
        if body:
            found.append((_STEM_ORDER.get(stem, 99), _STEM_LABELS.get(stem, stem), body))
    # 叙事顺序：分析师 -> 多空辩论 -> 交易 -> 风控 -> 最终决策（与回放页一致）
    found.sort(key=lambda t: t[0])
    sections = [(label, body) for _order, label, body in found]
    if not sections:  # 单一正文（如 API 摘要兜底）
        sections = [("报告正文", md_text)]
    return sections


def build_report_page(title: str, sub: str, sections: list[tuple[str, str]]) -> str:
    nav_items, body_parts = [], []
    for i, (label, md_text) in enumerate(sections, 1):
        anchor = f"sec-{i}"
        nav_items.append(
            f'<a href="#{anchor}"><span class="idx">{i:02d}</span>{html.escape(label)}</a>'
        )
        body_parts.append(
            f'<section class="section" id="{anchor}">'
            f'<span class="sec-tag">{i:02d} · {html.escape(label)}</span>'
            f'<div class="md">{_md_to_html(md_text)}</div></section>'
        )
    return (_PAGE
            .replace("__TITLE__", html.escape(title))
            .replace("__SUB__", html.escape(sub))
            .replace("__NAV__", "\n".join(nav_items))
            .replace("__BODY__", "\n".join(body_parts)))


def export_report_page(cfg, client, task_id: str, out_dir: Optional[Path] = None) -> Path:
    """生成完整报告 HTML 落盘，返回路径（供飞书按钮 URL 指向）。"""
    out_dir = out_dir or (cfg.exports_dir() / "report")
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fetch_report(client, task_id, _ta_dir(cfg))
    name = _lookup_name(cfg, client, doc.symbol)
    title = f"{name or doc.symbol}（{doc.symbol}）分析报告"
    sub = f"task {task_id} · {doc.chars} 字 · {len(split_sections(doc.text))} 份子报告"
    path = out_dir / f"{task_id}.html"
    path.write_text(build_report_page(title, sub, split_sections(doc.text)), encoding="utf-8")
    return path


def _ta_dir(cfg):
    raw = cfg.get("data.ta_dir", "")
    return Path(raw) if raw else None


def _lookup_name(cfg, client, symbol: str) -> str:
    if not symbol:
        return ""
    try:
        return str(client.stock_name(symbol) or "")
    except Exception:
        return ""


def make_handler(cfg, client_factory):
    """构建 http handler；按需生成页面并缓存。"""
    from ..core.client import TradingAgentsClient
    from ..core.store import Store

    lock = threading.Lock()
    store = Store(cfg.store_path())
    cache: dict[str, Path] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                path = self.path.split("?")[0].rstrip("/")
                if path in ("", "/index"):
                    body = self._index()
                    self._send(200, body)
                elif path.startswith("/report/"):
                    task_id = path[len("/report/"):]
                    page = self._cached(f"report:{task_id}", lambda: self._report(task_id))
                    self._send(200, page.read_text(encoding="utf-8"))
                elif path.startswith("/replay/"):
                    task_id = path[len("/replay/"):]
                    page = self._cached(f"replay:{task_id}", lambda: self._replay(task_id))
                    self._send(200, page.read_text(encoding="utf-8"))
                elif path.startswith("/debate/"):
                    task_id = path[len("/debate/"):]
                    page = self._cached(f"debate:{task_id}", lambda: self._debate(task_id))
                    self._send(200, page.read_text(encoding="utf-8"))
                else:
                    self._send(404, "not found")
            except FileNotFoundError:
                self._send(404, "报告不存在或任务未完成")
            except Exception as e:
                self._send(500, f"生成失败: {html.escape(str(e))}")

        def _cached(self, key: str, build) -> Path:
            with lock:
                if key not in cache:
                    p = build()
                    cache[key] = p if isinstance(p, Path) else p
                return cache[key]

        def _report(self, task_id: str) -> Path:
            client = client_factory(cfg)
            try:
                return export_report_page(cfg, client, task_id)
            finally:
                client.close()

        def _debate(self, task_id: str) -> Path:
            from ..replay.debate import build_debate_data
            from ..replay.debate_render import render_debate_html
            client = client_factory(cfg)
            try:
                data = build_debate_data(cfg, client, task_id)
            finally:
                client.close()
            if not data:
                raise FileNotFoundError("未找到该任务的辩论数据")
            out = cfg.exports_dir() / "debate" / f"{task_id}.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render_debate_html(data, replay_url=f"/replay/{task_id}"),
                           encoding="utf-8")
            return out

        def _replay(self, task_id: str) -> Path:
            client = client_factory(cfg)
            try:
                tl = replay_capture(cfg, client, store, task_id)
            finally:
                client.close()
            out = cfg.exports_dir() / "replay" / f"replay_{tl.symbol or 'task'}_{task_id[:8]}.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(replay_html(tl), encoding="utf-8")
            return out

        def _index(self) -> str:
            rows = []
            for run in store.latest_runs(20):
                sym = run.get("symbol") or "?"
                rows.append(f'<li><a href="/report/{run["task_id"]}">{sym}</a> '
                            f'· {run.get("status")} · {run.get("created_at","")}</li>')
            listing = "\n".join(rows) or "<li>暂无记录</li>"
            return build_report_page("报告索引", "最近的分析任务",
                                     [("最近的分析任务", f"<ul>{listing}</ul>")])

        def _send(self, code: int, text: str):
            data = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    return Handler


def serve(cfg, port: int = 8890, host: str = "0.0.0.0") -> None:
    from ..core.client import TradingAgentsClient
    http.server.ThreadingHTTPServer((host, port), make_handler(cfg, TradingAgentsClient)).serve_forever()

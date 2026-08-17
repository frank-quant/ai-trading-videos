"""多空辩论专用回放页：聊天流（一来一回）+ 正反打（话题配对对垒）。

自包含单文件 HTML：Python 侧预渲染 markdown，JS 只做视图切换与折叠。
"""
from __future__ import annotations

import html
import json

from ..core.textutil import _unescape


def _md(text: str) -> str:
    try:
        import markdown
        return markdown.markdown(text, extensions=["tables", "fenced_code"])
    except ImportError:
        return "<p>" + html.escape(text) + "</p>"


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>多空辩论 · __WHO__</title>
<style>
  :root { --bg:#0f1117; --panel:#171a23; --line:#262b38; --fg:#dbe2f0; --dim:#8b93a7;
          --bull:#ef6c6c; --bear:#3ecf8e; --accent:#4f8cff; }
  * { box-sizing:border-box; }
  html { -webkit-text-size-adjust:100%; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:15px/1.75 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
         word-break:break-word; overflow-wrap:anywhere; }
  header { position:sticky; top:0; z-index:20; background:var(--panel);
           border-bottom:1px solid var(--line); padding:10px 14px; }
  header h1 { margin:0; font-size:16px; }
  header .meta { color:var(--dim); font-size:11.5px; margin-top:2px; }
  .tabs { display:flex; gap:8px; margin-top:10px; }
  .tabs button { flex:1; background:#20242f; color:var(--fg); border:1px solid var(--line);
           border-radius:9px; padding:9px 6px; font-size:14px; cursor:pointer; }
  .tabs button.on { background:rgba(79,140,255,.18); color:var(--accent);
           border-color:var(--accent); font-weight:600; }
  main { max-width:880px; margin:0 auto; padding:16px 14px 80px; }
  .view { display:none; } .view.on { display:block; }

  /* ---- 聊天流 ---- */
  .round-sep { text-align:center; color:var(--dim); font-size:12px; margin:22px 0 12px;
           letter-spacing:2px; }
  .round-sep::before, .round-sep::after { content:"—"; margin:0 8px; opacity:.5; }
  .turn { display:flex; gap:10px; margin:14px 0; }
  .turn.right { flex-direction:row-reverse; }
  .avatar { width:38px; height:38px; border-radius:10px; flex:none; display:flex;
           align-items:center; justify-content:center; font-size:15px; font-weight:700;
           color:#0f1117; }
  .turn.bull .avatar { background:var(--bull); }
  .turn.bear .avatar { background:var(--bear); }
  .bubble { background:var(--panel); border:1px solid var(--line); border-radius:12px;
           padding:10px 14px; flex:1; min-width:0; }
  .turn.bull .bubble { border-color:rgba(239,108,108,.35); }
  .turn.bear .bubble { border-color:rgba(62,207,142,.35); }
  .bubble .who { font-size:12.5px; font-weight:700; margin-bottom:4px; }
  .turn.bull .who { color:var(--bull); }
  .turn.bear .who { color:var(--bear); }
  .bubble .title { font-size:13.5px; color:#fff; background:rgba(255,255,255,.05);
           border-radius:7px; padding:5px 10px; margin-bottom:8px; }
  .bubble .body { font-size:14.5px; }
  .bubble .body :is(h1,h2,h3) { font-size:14.5px; color:#fff; margin:.9em 0 .4em;
           border-bottom:1px dashed var(--line); padding-bottom:3px; }
  .bubble .body table { display:block; overflow-x:auto; border-collapse:collapse;
           margin:8px 0; font-size:12.5px; }
  .bubble .body th, .bubble .body td { border:1px solid var(--line); padding:5px 9px;
           white-space:nowrap; }
  .bubble .body th { background:#1d2230; color:#fff; }
  .bubble .body.collapsed { max-height:300px; overflow:hidden;
           mask-image:linear-gradient(#000 78%,transparent); -webkit-mask-image:linear-gradient(#000 78%,transparent); }
  .expand { color:var(--accent); font-size:12px; cursor:pointer; margin-top:4px;
           user-select:none; }
  .verdict { margin-top:26px; background:linear-gradient(135deg,#1a1f2e,#171a23);
           border:1px solid rgba(79,140,255,.4); border-radius:14px; padding:16px 18px; }
  .verdict h2 { margin:0 0 8px; font-size:15px; color:var(--accent); }
  .verdict .body { font-size:14.5px; }
  .verdict .body :is(h1,h2,h3) { font-size:14.5px; color:#fff; margin:.8em 0 .4em; }

  /* ---- 正反打 ---- */
  .vs-card { background:var(--panel); border:1px solid var(--line); border-radius:14px;
           margin:14px 0; overflow:hidden; }
  .vs-topic { padding:11px 16px; font-size:14.5px; font-weight:700; color:#fff;
           background:#1d2230; border-bottom:1px solid var(--line);
           display:flex; align-items:center; gap:8px; }
  .vs-topic .n { color:var(--accent); font-size:12px; font-weight:400; }
  .vs-cols { display:grid; grid-template-columns:1fr 1fr; }
  .vs-side { padding:12px 14px; font-size:13.8px; line-height:1.7; }
  .vs-side .side-tag { display:inline-block; font-size:11px; font-weight:700; border-radius:12px;
           padding:1px 10px; margin-bottom:7px; }
  .vs-bull { border-right:1px solid var(--line); }
  .vs-bull .side-tag { background:rgba(239,108,108,.15); color:var(--bull);
           border:1px solid rgba(239,108,108,.4); }
  .vs-bear .side-tag { background:rgba(62,207,142,.15); color:var(--bear);
           border:1px solid rgba(62,207,142,.4); }
  .vs-empty { color:var(--dim); text-align:center; margin:40px 0; font-size:13px; }
  footer { text-align:center; color:var(--dim); font-size:11px; padding:18px; }
  footer a { color:var(--accent); text-decoration:none; }

  @media (max-width:700px) {
    main { padding:12px 10px 70px; }
    .avatar { width:32px; height:32px; font-size:13px; }
    .bubble { padding:9px 12px; }
    .bubble .body { font-size:14px; }
    .vs-side { padding:10px 11px; font-size:13px; }
  }
</style>
</head>
<body>
<header>
  <h1>⚔️ 多空辩论 · __WHO__</h1>
  <div class="meta">__META__</div>
  <div class="tabs">
    <button id="tabChat" class="on">💬 辩论实况（__NTURNS__ 回合）</button>
    <button id="tabVs">⚔️ 多空对垒（__NVS__ 个分歧点）</button>
  </div>
</header>

<main>
  <section id="viewChat" class="view on">
__CHAT__
    <div class="verdict">
      <h2>⚖️ 研究经理裁决</h2>
      <div class="body">__VERDICT__</div>
    </div>
  </section>

  <section id="viewVs" class="view">
__VS__
  </section>
</main>

<footer>TradingAgents Studio · <a href="__REPLAY_URL__">查看完整分析回放</a></footer>

<script>
function switchTab(tab) {
  [ ['tabChat','viewChat'], ['tabVs','viewVs'] ].forEach(function (pair) {
    document.getElementById(pair[0]).classList.toggle('on', pair[0] === tab);
    document.getElementById(pair[1]).classList.toggle('on', 'tab' + pair[1].slice(4) === tab);
  });
}
document.getElementById('tabChat').addEventListener('click', function(){ switchTab('tabChat'); });
document.getElementById('tabVs').addEventListener('click', function(){ switchTab('tabVs'); });
document.querySelectorAll('.expand').forEach(function (el) {
  el.addEventListener('click', function () {
    var body = el.previousElementSibling;
    body.classList.toggle('collapsed');
    el.textContent = body.classList.contains('collapsed') ? '展开全文 ▾' : '收起 ▴';
  });
});
</script>
</body>
</html>
"""


def render_debate_html(data: dict, replay_url: str = "#") -> str:
    """data: {who, meta, turns:[{side,label,round,title,content_md}], verdict_md, matchups:[...]}"""
    # ---- 聊天流 ----
    chat: list[str] = []
    seen_rounds: set[int] = set()
    for t in data["turns"]:
        if t.get("round") not in seen_rounds:
            seen_rounds.add(t.get("round"))
            chat.append(f'<div class="round-sep">第 {t.get("round")} 轮</div>')
        body_html = _md(t.get("content", ""))
        long = len(t.get("content", "")) > 700
        title_html = (f'<div class="title">{html.escape(t["title"])}</div>'
                      if t.get("title") else "")
        chat.append(
            f'<div class="turn {t["side"]} {"right" if t["side"] == "bull" else ""}">'
            f'<div class="avatar">{"多" if t["side"] == "bull" else "空"}</div>'
            f'<div class="bubble"><div class="who">{html.escape(t["label"])}研究员</div>'
            f'{title_html}'
            f'<div class="body{" collapsed" if long else ""}">{body_html}</div>'
            + ('<div class="expand">展开全文 ▾</div>' if long else "")
            + "</div></div>"
        )
    chat_html = "\n".join(chat)

    # ---- 正反打 ----
    matchups = data.get("matchups") or []
    if matchups:
        vs: list[str] = []
        for i, m in enumerate(matchups, 1):
            vs.append(
                f'<div class="vs-card"><div class="vs-topic"><span class="n">{i:02d}</span>'
                f'{html.escape(m["topic"])}</div>'
                f'<div class="vs-cols">'
                f'<div class="vs-side vs-bull"><span class="side-tag">多头这么说</span><br>'
                f'{html.escape(m.get("bull", ""))}</div>'
                f'<div class="vs-side vs-bear"><span class="side-tag">空头这么说</span><br>'
                f'{html.escape(m.get("bear", ""))}</div>'
                f"</div></div>"
            )
        vs_html = "\n".join(vs)
    else:
        vs_html = ('<div class="vs-empty">分歧点配对生成失败（LLM 未返回有效结果），'
                   '请稍后重试或检查 llm 配置</div>')

    return (_TEMPLATE
            .replace("__WHO__", html.escape(data.get("who", "")))
            .replace("__META__", html.escape(data.get("meta", "")))
            .replace("__NTURNS__", str(len(data.get("turns", []))))
            .replace("__NVS__", str(len(matchups)))
            .replace("__CHAT__", chat_html)
            .replace("__VERDICT__", _md(data.get("verdict_md", "")))
            .replace("__VS__", vs_html)
            .replace("__REPLAY_URL__", html.escape(replay_url)))


def write_debate_html(data: dict, path, replay_url: str = "#"):
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_debate_html(data, replay_url), encoding="utf-8")
    return path

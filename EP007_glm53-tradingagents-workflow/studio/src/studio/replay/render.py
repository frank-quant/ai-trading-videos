"""回放渲染：单文件自包含 HTML（内嵌数据 + 原生 JS），可直接发给别人。"""
from __future__ import annotations

import html
import json
from pathlib import Path

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Studio Replay — __SYMBOL__ (__TASK__)</title>
<style>
  :root {
    --bg: #0f1117; --panel: #171a23; --line: #262b38; --fg: #dbe2f0; --dim: #8b93a7;
    --accent: #4f8cff;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg);
         font: 14px/1.6 "Segoe UI", "Microsoft YaHei", sans-serif; }
  header { position: sticky; top: 0; z-index: 10; background: var(--panel);
           border-bottom: 1px solid var(--line); padding: 10px 18px;
           display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  header h1 { font-size: 15px; margin: 0 18px 0 0; font-weight: 600; }
  header .meta { color: var(--dim); font-size: 12px; }
  html { -webkit-text-size-adjust: 100%; }
  .controls { display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }
  button, input[type=search], select {
    background: #20242f; color: var(--fg); border: 1px solid var(--line);
    border-radius: 6px; padding: 6px 11px; font-size: 13px; cursor: pointer; }
  input[type=search] { width: 150px; }
  button:hover { border-color: var(--accent); }
  input[type=search] { width: 160px; cursor: text; }
  main { max-width: 980px; margin: 0 auto; padding: 18px 14px 80px; }
  .phase { margin: 26px 0 10px; display: flex; align-items: center; gap: 10px; }
  .phase h2 { font-size: 13px; color: var(--dim); font-weight: 600;
              letter-spacing: 2px; margin: 0; white-space: nowrap; }
  .phase::after { content: ""; flex: 1; height: 1px; background: var(--line); }
  .msg { display: flex; gap: 10px; margin: 12px 0; align-items: flex-start; }
  .avatar { width: 34px; height: 34px; border-radius: 8px; flex: none;
            display: flex; align-items: center; justify-content: center;
            font-size: 15px; background: #262b38; }
  .bubble { background: var(--panel); border: 1px solid var(--line);
            border-radius: 10px; padding: 10px 14px; min-width: 0; flex: 1; }
  .bubble .who { font-size: 12px; font-weight: 600; margin-bottom: 4px; }
  .bubble .who .kind { color: var(--dim); font-weight: 400; margin-left: 8px; font-size: 11px; }
  .bubble .body { white-space: pre-wrap; word-break: break-word; color: var(--fg); }
  .bubble.step { background: transparent; border-style: dashed; color: var(--dim); }
  .bubble .body.collapsed { max-height: 260px; overflow: hidden;
            mask-image: linear-gradient(#000 78%, transparent); }
  .expand { color: var(--accent); font-size: 12px; cursor: pointer; user-select: none; }
  .hidden { display: none !important; }
  .legend { font-size: 11px; color: var(--dim); margin-left: 8px; }
  footer { text-align: center; color: var(--dim); font-size: 11px; padding: 20px; }

  @media (max-width: 700px) {
    header { padding: 8px 12px; gap: 6px; }
    header h1 { font-size: 14px; width: 100%; }
    header .meta { font-size: 11px; width: 100%; order: 2; }
    .controls { margin-left: 0; width: 100%; order: 3; }
    input[type=search] { flex: 1; width: auto; min-width: 90px; }
    button, input[type=search], select { padding: 7px 10px; }
    main { padding: 12px 10px 70px; }
    .msg { gap: 8px; margin: 10px 0; }
    .avatar { width: 30px; height: 30px; font-size: 14px; border-radius: 7px; }
    .bubble { padding: 9px 12px; border-radius: 9px; }
    .bubble .body { font-size: 14.5px; }
    .bubble .body.collapsed { max-height: 220px; }
    .phase { margin: 20px 0 8px; }
    .phase h2 { font-size: 12px; }
  }
</style>
</head>
<body>
<header>
  <h1>🎬 Studio Replay</h1>
  <span class="meta" id="meta"></span>
  <div class="controls">
    <input type="search" id="q" placeholder="搜索内容…">
    <select id="phase"></select>
    <button id="play">▶ 自动播放</button>
    <button id="expandAll">展开全部</button>
  </div>
</header>
<main id="list"></main>
<footer>由 TradingAgents Studio 生成 · 单文件可直接分享</footer>
<script>
const DATA = __DATA__;
const COLORS = {"分析师":"#4f8cff","研究":"#e59a3c","交易":"#3ecf8e","风控":"#ef6c6c","管理":"#b07cf0","系统":"#8b93a7"};
const ICONS  = {"分析师":"📈","研究":"⚔️","交易":"🎯","风控":"🛡️","管理":"🧠","系统":"⚙️"};

const metaEl = document.getElementById('meta');
metaEl.textContent = `${DATA.symbol || '?'} · ${DATA.meta?.depth || ''} · ` +
  `${DATA.meta?.models?.quick || ''}/${DATA.meta?.models?.deep || ''} · ` +
  `${DATA.meta?.status || ''} · ${DATA.events.length} 条记录`;

const phaseSel = document.getElementById('phase');
const phases = [...new Set(DATA.events.map(e => e.phase || '系统'))];
phaseSel.innerHTML = '<option value="">全部阶段</option>' +
  phases.map(p => `<option value="${p}">${ICONS[p]||''} ${p}</option>`).join('');

function render() {
  const q = document.getElementById('q').value.trim().toLowerCase();
  const ph = phaseSel.value;
  const list = document.getElementById('list');
  list.innerHTML = '';
  let lastPhase = null;
  for (const ev of DATA.events) {
    const phase = ev.phase || '系统';
    if (ph && phase !== ph) continue;
    if (q && !(ev.agent + ' ' + ev.content).toLowerCase().includes(q)) continue;
    if (phase !== lastPhase) {
      const h = document.createElement('div');
      h.className = 'phase';
      h.innerHTML = `<h2>${ICONS[phase]||''} ${phase}</h2>`;
      list.appendChild(h);
      lastPhase = phase;
    }
    const color = COLORS[phase] || '#8b93a7';
    const kindLabel = ev.kind === 'report' ? '报告产出' : (ev.kind === 'step' ? '过程步骤' : '发言');
    const wrap = document.createElement('div');
    wrap.className = 'msg'; wrap.dataset.phase = phase;
    const body = ev.content || '（无内容）';
    wrap.innerHTML =
      `<div class="avatar" style="color:${color}">${ICONS[phase]||'⚙️'}</div>` +
      `<div class="bubble ${ev.kind === 'step' ? 'step' : ''}">` +
      `<div class="who" style="color:${color}">${esc(ev.agent)}` +
      `<span class="kind">${kindLabel} · ${ev.ts || ''}</span></div>` +
      `<div class="body">${esc(body)}</div>` +
      (body.length > 600 ? `<div class="expand">展开全文 ▾</div>` : '') +
      `</div>`;
    list.appendChild(wrap);
  }
  if (!list.children.length) list.innerHTML = '<p style="color:var(--dim);text-align:center;margin-top:60px">没有匹配的记录</p>';
  document.querySelectorAll('.expand').forEach(el => el.addEventListener('click', () => {
    const body = el.previousElementSibling;
    body.classList.toggle('collapsed');
    el.textContent = body.classList.contains('collapsed') ? '展开全文 ▾' : '收起 ▴';
  }));
}
function esc(s) { const d = document.createElement('div'); d.textContent = s ?? ''; return d.innerHTML; }

document.getElementById('q').addEventListener('input', render);
phaseSel.addEventListener('change', render);
document.getElementById('expandAll').addEventListener('click', () => {
  document.querySelectorAll('.body').forEach(b => b.classList.remove('collapsed'));
});
let timer = null;
document.getElementById('play').addEventListener('click', function () {
  if (timer) { clearInterval(timer); timer = null; this.textContent = '▶ 自动播放'; return; }
  this.textContent = '⏸ 暂停播放';
  const msgs = [...document.querySelectorAll('.msg')];
  let i = 0;
  document.querySelectorAll('.msg').forEach(m => m.classList.add('hidden'));
  timer = setInterval(() => {
    if (i >= msgs.length) {
      clearInterval(timer); timer = null; this.textContent = '▶ 自动播放';
      document.querySelectorAll('.msg').forEach(m => m.classList.remove('hidden'));
      return;
    }
    msgs[i].classList.remove('hidden');
    msgs[i].scrollIntoView({ block: 'center', behavior: 'smooth' });
    i++;
  }, 700);
});
render();
</script>
</body>
</html>
"""


def render_html(timeline) -> str:
    payload = json.dumps(timeline.to_dict(), ensure_ascii=False)
    out = (_TEMPLATE
           .replace("__DATA__", payload)
           .replace("__SYMBOL__", html.escape(timeline.symbol or "?"))
           .replace("__TASK__", html.escape(timeline.task_id)))
    return out


def write_html(timeline, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(timeline), encoding="utf-8")
    return path

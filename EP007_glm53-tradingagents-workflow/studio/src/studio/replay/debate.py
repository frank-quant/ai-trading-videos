"""多空辩论解析：从研究团队/风控的 dict 报告里抽出轮次发言与话题对垒。

数据形态（ast.literal_eval 后）：
  research_team_decision: {judge_decision, history, bull_history, bear_history, ...}
  risk_management_decision: {judge_decision, history, risky/safe/neutral_history, ...}
history 形如 "\\nBull Analyst: ...\\nBear Analyst: ..."，按说话人前缀切轮次。
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..core.textutil import _unescape

SPEAKER_RE = re.compile(r"(?m)^(Bull|Bear|Risky|Safe|Neutral)\s+Analyst:\s*")

SIDE_LABELS = {
    "Bull": ("多头", "bull"),
    "Bear": ("空头", "bear"),
    "Risky": ("激进", "risky"),
    "Safe": ("保守", "safe"),
    "Neutral": ("中性", "neutral"),
}


@dataclass
class Turn:
    speaker: str            # Bull / Bear / ...
    label: str              # 多头 / 空头 / ...
    side: str               # bull / bear / ...
    content: str
    title: str = ""         # 内容里的一级标题，做气泡标题
    round_no: int = 0


@dataclass
class Debate:
    kind: str = "research"                  # research | risk
    turns: list[Turn] = field(default_factory=list)
    verdict: str = ""                       # judge_decision
    source_file: str = ""
    matchup_error: str = ""


def parse_history(history: str) -> list[Turn]:
    """把 'Bull Analyst: xxx\\nBear Analyst: yyy' 切成轮次。"""
    text = _unescape(history)
    matches = list(SPEAKER_RE.finditer(text))
    if not matches:
        return []
    turns: list[Turn] = []
    counters: dict[str, int] = {}
    for i, m in enumerate(matches):
        speaker = m.group(1)
        body = text[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        body = body.strip().strip("-").strip()
        title = ""
        title_m = re.match(r"^#{1,3}\s+(.+)", body)
        if title_m:
            title = title_m.group(1).strip()
        counters[speaker] = counters.get(speaker, 0) + 1
        label, side = SIDE_LABELS.get(speaker, (speaker, speaker.lower()))
        turns.append(Turn(
            speaker=speaker, label=label, side=side, content=body, title=title,
            round_no=counters[speaker],
        ))
    return turns


def load_debate_from_file(path: Path, kind: str = "research") -> Optional[Debate]:
    """读取并解析一份辩论报告文件；不是 dict 结构或无轮次则返回 None。"""
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not (raw.startswith("{") and raw.endswith("}")):
        return None
    try:
        obj = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(obj, dict):
        return None
    debate = Debate(kind=kind, source_file=str(path))
    debate.verdict = _unescape(str(obj.get("judge_decision") or "")).strip()
    history = obj.get("history") or ""
    if isinstance(history, str):
        debate.turns = parse_history(history)
    # history 缺失时用双方各自的历史拼（顺序丢失但内容保真）
    if not debate.turns:
        for key in ("bull_history", "bear_history", "risky_history", "safe_history", "neutral_history"):
            part = obj.get(key) or ""
            if isinstance(part, str) and part.strip():
                debate.turns += parse_history(part)
    return debate if (debate.turns or debate.verdict) else None


# ---------------- 话题对垒（LLM 配对，带缓存） ----------------

_MATCHUP_PROMPT = """\
你是辩论复盘助手。下面是一场股票多空辩论中双方的全部发言。

请提取双方真正交锋的话题（4-6 个，按重要性排序），输出严格的 JSON 数组：
[{"topic": "话题名（≤12字）", "bull": "多头在该话题上的核心论点（≤80字，保留关键数字）", "bear": "空头的反驳（≤80字，保留关键数字）"}]

要求：
- 每个话题必须双方都实际发表过观点，不许编造
- 保留双方使用的关键数字/价位，那是交锋的焦点
- 只输出 JSON 数组本身，不要任何其他文字

【多头发言】
__BULL__

【空头发言】
__BEAR__
"""


def extract_matchups(cfg, turns: list[Turn]) -> list[dict]:
    """用配置的 LLM 把多空论点按话题配对。失败返回空列表。"""
    bull_speakers = {"bull"}
    bear_speakers = {"bear"}
    bull = "\n\n".join(t.content for t in turns if t.side in bull_speakers)
    bear = "\n\n".join(t.content for t in turns if t.side in bear_speakers)
    if not bull or not bear:
        return []
    prompt = _MATCHUP_PROMPT.replace("__BULL__", bull[:22000]).replace("__BEAR__", bear[:22000])
    text, _err = _chat(cfg, prompt)
    if not text:
        return []
    return _parse_json_array(text)


def matchup_cache_path(cfg, task_id: str) -> Path:
    d = cfg.exports_dir() / "debate"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{task_id}_matchup.json"


def load_or_extract_matchups(cfg, task_id: str, turns: list[Turn]) -> tuple[list[dict], bool]:
    """缓存优先；未命中则调用 LLM。返回 (matchups, from_cache)。"""
    cache = matchup_cache_path(cfg, task_id)
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8")), True
        except json.JSONDecodeError:
            pass
    matchups = extract_matchups(cfg, turns)
    if matchups:
        cache.write_text(json.dumps(matchups, ensure_ascii=False, indent=1), encoding="utf-8")
    return matchups, False


def _chat(cfg, prompt: str) -> tuple[str, str]:
    """极简 OpenAI 兼容对话调用（复用 digest 的 llm 配置）。"""
    import httpx
    base = str(cfg.get("llm.base_url", "")).rstrip("/")
    key = str(cfg.get("llm.api_key", "") or "")
    model = str(cfg.get("llm.model", "") or "")
    if not (base and key and model):
        return "", "llm 未配置"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 3000,
        "temperature": 0.2,
        "stream": False,
    }
    if extra := cfg.get("llm.extra_body"):
        payload.update(extra)
    try:
        r = httpx.post(f"{base}/chat/completions", json=payload, timeout=300,
                       headers={"Authorization": f"Bearer {key}",
                                "Content-Type": "application/json"})
        r.raise_for_status()
        body = r.json()
        text = (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return text.strip(), ""
    except Exception as e:
        return "", str(e)


def _parse_json_array(text: str) -> list[dict]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    out = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("topic"):
                out.append({
                    "topic": str(item.get("topic", ""))[:30],
                    "bull": str(item.get("bull", "")),
                    "bear": str(item.get("bear", "")),
                })
    return out

def build_debate_data(cfg, client, task_id: str) -> Optional[dict]:
    """组装辩论页渲染数据：定位文件 -> 解析轮次 -> 话题配对（缓存优先）。"""
    from pathlib import Path
    from .capture import find_reports_dir

    symbol = ""
    try:
        status = client.get_status(task_id)
        symbol = str(status.get("symbol") or status.get("stock_code") or "")
    except Exception:
        pass
    ta_dir = cfg.get("data.ta_dir", "")
    if not ta_dir:
        return None
    reports = find_reports_dir(Path(ta_dir), symbol)
    if not reports:
        return None

    debate = load_debate_from_file(reports / "research_team_decision.md", "research")
    if not debate:
        debate = load_debate_from_file(reports / "risk_management_decision.md", "risk")
    if not debate:
        return None

    matchups, _cached = load_or_extract_matchups(cfg, task_id, debate.turns)

    name = ""
    try:
        name = client.stock_name(symbol)
    except Exception:
        pass
    who = f"{name}({symbol})" if name else (symbol or task_id[:8])
    meta_parts = [f"task {task_id[:8]}", f"{len(debate.turns)} 次发言"]
    if matchups:
        meta_parts.append(f"{len(matchups)} 个交锋话题")

    return {
        "who": who,
        "meta": " · ".join(meta_parts),
        "turns": [
            {"side": t.side, "label": t.label, "round": t.round_no,
             "title": t.title, "content": t.content}
            for t in debate.turns
        ],
        "verdict_md": debate.verdict,
        "matchups": matchups,
    }

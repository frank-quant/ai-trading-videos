"""LLM 提炼器：长报告 -> 约 200 字开盘简报。OpenAI 兼容接口。"""
from __future__ import annotations

import httpx

from .templates import SYSTEM_PROMPT, build_user

MAX_INPUT_CHARS = 24000  # 防御：过长的报告截中间保头尾
HARD_LIMIT = 400         # 超过这个字数视为失控，收紧重试一次


class CondenseError(RuntimeError):
    pass


def _clip(text: str) -> str:
    if len(text) <= MAX_INPUT_CHARS:
        return text
    head, tail = MAX_INPUT_CHARS * 2 // 3, MAX_INPUT_CHARS // 3
    return text[:head] + "\n\n……（中间部分省略）……\n\n" + text[-tail:]


def condense(cfg, report_text: str, symbol: str = "", depth: str = "") -> tuple[str, dict]:
    """返回 (简报文本, usage 信息)。"""
    base_url = str(cfg.get("llm.base_url", "")).rstrip("/")
    api_key = cfg.get("llm.api_key", "")
    model = cfg.get("llm.model", "")
    if not api_key or not model:
        raise CondenseError("llm.api_key / llm.model 未配置（studio.yaml 的 llm 段）")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user(symbol, depth, _clip(report_text))},
        ],
        "max_tokens": int(cfg.get("llm.max_tokens", 2000)),
        "temperature": float(cfg.get("llm.temperature", 0.3)),
        "stream": False,
    }
    # 供应商特有参数直通，如智谱关思考: llm.extra_body: {thinking: {type: disabled}}
    if extra := cfg.get("llm.extra_body"):
        payload.update(extra)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    last_err: Exception | None = None
    for attempt in range(3):
        if attempt == 1:  # 输出超长：收紧重试
            payload["max_tokens"] = min(payload["max_tokens"], 800)
        if attempt == 2:  # 空内容（常见于推理模型思考吃满 token）：加倍重试
            payload["max_tokens"] = max(payload["max_tokens"], 8192)
        try:
            r = httpx.post(
                f"{base_url}/chat/completions", json=payload, headers=headers, timeout=180
            )
            r.raise_for_status()
            body = r.json()
            choice = (body.get("choices") or [{}])[0]
            message = choice.get("message", {}) or {}
            text = (message.get("content") or "").strip()
            finish = choice.get("finish_reason", "")
            usage = body.get("usage", {})
            if not text and attempt < 2:
                continue  # 空内容：下一轮处理（加倍/关思考）
            if not text:
                raise CondenseError(
                    f"模型返回空内容（finish_reason={finish}；"
                    f"推理模型可调大 llm.max_tokens 或降低 reasoning_effort）"
                )
            if len(text) > HARD_LIMIT and attempt == 0:
                continue  # 超长，收紧重试
            return text, usage
        except httpx.HTTPError as e:
            last_err = e
            if attempt == 2:
                break
    raise CondenseError(f"提炼失败：{last_err or '输出长度失控'}")

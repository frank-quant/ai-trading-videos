"""企业微信群机器人：webhook key，markdown 消息（上限 4096 字节）。

文档: https://developer.work.weixin.qq.com/document/path/91770
"""
from __future__ import annotations

import httpx

from .base import Channel, registry


@registry.register
class WeComChannel(Channel):
    name = "wecom"

    def __init__(self, options: dict):
        self.webhook: str = options.get("webhook", "")
        if not self.webhook:
            raise ValueError("wecom 渠道缺少 webhook 配置")

    def send(self, title: str, body: str, markdown: str = "",
             buttons: list[tuple[str, str]] | None = None) -> None:
        text = f"**{title}**\n{markdown or body}"
        if buttons:
            text += "\n\n" + " | ".join(f"[{label}]({u})" for label, u in buttons)
        # 企微 markdown 上限 4096 字节，按 UTF-8 安全截断
        raw = text.encode("utf-8")
        if len(raw) > 4000:
            text = raw[:4000].decode("utf-8", errors="ignore")
        payload = {"msgtype": "markdown", "markdown": {"content": text}}
        r = httpx.post(self.webhook, json=payload, timeout=15)
        r.raise_for_status()
        result = r.json()
        if result.get("errcode") not in (0, None):
            raise RuntimeError(f"企业微信返回错误: {result}")

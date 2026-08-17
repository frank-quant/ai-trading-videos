"""通用 JSON webhook：POST {title, body, markdown}。可对接任意中转服务。"""
from __future__ import annotations

import httpx

from .base import Channel, registry


@registry.register
class WebhookChannel(Channel):
    name = "webhook"

    def __init__(self, options: dict):
        self.url: str = options.get("url", "")
        if not self.url:
            raise ValueError("webhook 渠道缺少 url 配置")

    def send(self, title: str, body: str, markdown: str = "",
             buttons: list[tuple[str, str]] | None = None) -> None:
        payload = {"title": title, "body": body, "markdown": markdown}
        if buttons:
            payload["buttons"] = [{"text": t, "url": u} for t, u in buttons]
        r = httpx.post(self.url, json=payload, timeout=15)
        r.raise_for_status()

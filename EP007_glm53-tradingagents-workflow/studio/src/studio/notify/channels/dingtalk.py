"""钉钉自定义机器人：webhook + 加签（HMAC-SHA256）。

文档: https://open.dingtalk.com/document/robots/custom-robot-access
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse

import httpx

from .base import Channel, registry


def _sign(secret: str, timestamp: int) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), f"{timestamp}\n{secret}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))


@registry.register
class DingTalkChannel(Channel):
    name = "dingtalk"

    def __init__(self, options: dict):
        self.webhook: str = options.get("webhook", "")
        self.secret: str = options.get("secret", "") or ""
        if not self.webhook:
            raise ValueError("dingtalk 渠道缺少 webhook 配置")

    def send(self, title: str, body: str, markdown: str = "",
             buttons: list[tuple[str, str]] | None = None) -> None:
        url = self.webhook
        if self.secret:
            ts = int(time.time() * 1000)
            url += f"&timestamp={ts}&sign={_sign(self.secret, ts)}"
        # 钉钉 markdown 标题必填；正文过长截断；按钮以链接形式附在文末
        text = (markdown or body)[:18000]
        if buttons:
            text += "\n\n" + " | ".join(f"[{label}]({u})" for label, u in buttons)
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title[:40] or "studio", "text": text},
        }
        r = httpx.post(url, json=payload, timeout=15)
        r.raise_for_status()
        result = r.json()
        if result.get("errcode") not in (0, None):
            raise RuntimeError(f"钉钉返回错误: {result}")

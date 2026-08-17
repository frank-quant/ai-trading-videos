"""飞书自定义机器人：webhook + 可选签名（https://open.feishu.cn/document/... 自定义机器人）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

import httpx

from .base import Channel, registry


def _sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


@registry.register
class FeishuChannel(Channel):
    name = "feishu"

    def __init__(self, options: dict):
        self.webhook: str = options.get("webhook", "")
        self.secret: str = options.get("secret", "") or ""
        if not self.webhook:
            raise ValueError("feishu 渠道缺少 webhook 配置")

    def send(self, title: str, body: str, markdown: str = "",
             buttons: list[tuple[str, str]] | None = None) -> None:
        elements: list[dict] = [
            {
                "tag": "markdown",
                "content": (markdown or body)[:4000],  # 飞书卡片单元素上限约 50KB，这里保守限制
            }
        ]
        if buttons:
            elements.append({
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": label[:20]},
                        "type": "primary" if i == 0 else "default",
                        "url": url,
                    }
                    for i, (label, url) in enumerate(buttons[:3])
                ],
            })
        payload: dict = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title[:60]},
                    "template": "blue",
                },
                "elements": elements,
            },
        }
        if self.secret:
            ts = int(time.time())
            payload["timestamp"] = str(ts)
            payload["sign"] = _sign(self.secret, ts)

        r = httpx.post(self.webhook, json=payload, timeout=15)
        r.raise_for_status()
        result = r.json()
        # 飞书永远返回 200，错误藏在 code 字段里
        if result.get("code") not in (0, None) or result.get("StatusCode") not in (0, None):
            raise RuntimeError(f"飞书返回错误: {result}")

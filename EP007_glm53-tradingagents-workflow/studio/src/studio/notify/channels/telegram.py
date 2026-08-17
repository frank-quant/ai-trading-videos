"""Telegram Bot：sendMessage（纯文本）。国内网络通常需要代理。

文档: https://core.telegram.org/bots/api#sendmessage
配置示例:
  telegram:
    token: "123456:ABC-xxx"        # @BotFather 创建
    chat_id: "-1001234567890"      # 群组 ID（拉 bot 入群后用 getUpdates 查）
    proxy: "http://127.0.0.1:7897" # 可选
"""
from __future__ import annotations

import httpx

from .base import Channel, registry


@registry.register
class TelegramChannel(Channel):
    name = "telegram"

    def __init__(self, options: dict):
        self.token: str = options.get("token", "")
        self.chat_id: str = str(options.get("chat_id", "") or "")
        self.proxy: str = options.get("proxy", "") or ""
        if not (self.token and self.chat_id):
            raise ValueError("telegram 渠道缺少 token / chat_id 配置")

    def send(self, title: str, body: str, markdown: str = "",
             buttons: list[tuple[str, str]] | None = None) -> None:
        text = f"*{title}*\n{body}"
        if buttons:
            text += "\n" + "\n".join(f"• {label}: {u}" for label, u in buttons)
        payload = {
            "chat_id": self.chat_id,
            "text": text[:4000],
            "disable_web_page_preview": True,
        }
        client_kwargs = {"timeout": 15}
        if self.proxy:
            client_kwargs["proxy"] = self.proxy
        with httpx.Client(**client_kwargs) as client:
            r = client.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                            json=payload)
            r.raise_for_status()
            result = r.json()
            if not result.get("ok"):
                raise RuntimeError(f"Telegram 返回错误: {result}")

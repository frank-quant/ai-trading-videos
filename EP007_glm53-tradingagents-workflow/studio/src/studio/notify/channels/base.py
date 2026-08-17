"""推送渠道抽象。"""
from __future__ import annotations

import abc


class Channel(abc.ABC):
    name: str = "base"
    alias: str = ""   # 多实例时的展示名（如 feishu#盯盘群 -> 盯盘群）

    @abc.abstractmethod
    def send(self, title: str, body: str, markdown: str = "",
             buttons: list[tuple[str, str]] | None = None) -> None:
        """发送消息。失败抛异常，由调用方决定如何处理。

        title:   一行标题（纯文本）
        body:    纯文本正文（不支持富文本的渠道用）
        markdown: markdown 正文（支持的渠道优先用）
        buttons: 可选的 (按钮文字, 跳转URL) 列表
        """
        raise NotImplementedError


class ChannelRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, type[Channel]] = {}

    def register(self, cls: type[Channel]) -> type[Channel]:
        self._factories[cls.name] = cls
        return cls

    def build(self, name: str, options: dict, alias: str = "") -> Channel:
        if name not in self._factories:
            raise KeyError(f"未知推送渠道: {name}（可用: {list(self._factories)}）")
        ch = self._factories[name](options)
        ch.alias = alias or name
        return ch


registry = ChannelRegistry()

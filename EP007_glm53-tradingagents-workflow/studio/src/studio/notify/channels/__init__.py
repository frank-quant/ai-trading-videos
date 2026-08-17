"""导入即注册：确保 build_channels 时 feishu/webhook 已进注册表。"""
from .base import Channel, registry
from . import feishu  # noqa: F401
from . import webhook  # noqa: F401
from . import dingtalk  # noqa: F401
from . import wecom  # noqa: F401
from . import telegram  # noqa: F401

__all__ = ["Channel", "registry"]

"""集中配置：studio.yaml 加载 + ${ENV} 展开 + STUDIO__ 覆盖。

覆盖规则（点号路径映射到双下划线）：
  STUDIO__API__PASSWORD -> api.password
  STUDIO__LLM__API_KEY  -> llm.api_key
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

DEFAULTS: dict[str, Any] = {
    "api": {
        "base_url": "http://localhost",
        "username": "admin",
        "password": "",
        "timeout": 30,
    },
    "llm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "",
        "model": "",
        "max_tokens": 2000,
        "temperature": 0.3,
    },
    "data": {"ta_dir": ""},
    "notify": {"channels": {}},
    "compare": {
        "defaults": {
            "depth": "标准",
            "analysts": ["market", "fundamentals", "news"],
            "concurrency": 2,
            "poll_interval": 10,
        },
        "prices": {},
    },
    "replay": {"theme": "dark", "exports_dir": "data/exports"},
    "cron": {"timezone": "Asia/Shanghai", "jobs": []},
}


def _expand(value: Any) -> Any:
    """递归展开字符串里的 ${VAR}；未定义的环境变量展开为空串。"""
    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """点号路径读取的配置封装。"""

    def __init__(self, data: dict[str, Any], path: Path | None):
        self._data = data
        self.path = path

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data = _merge(DEFAULTS, _expand(raw))
        data = cls._apply_env_overrides(data)
        return cls(data, path)

    @classmethod
    def load_default(cls) -> "Config":
        """按顺序找配置：STUDIO_CONFIG -> ./studio.yaml -> 包目录向上两级。"""
        candidates = []
        if env := os.environ.get("STUDIO_CONFIG"):
            candidates.append(Path(env))
        candidates.append(Path.cwd() / "studio.yaml")
        root = Path(__file__).resolve().parents[2]  # src/studio/core -> 仓库根
        candidates += [root / "studio.yaml", root.parent / "studio.yaml"]
        for c in candidates:
            if c.is_file():
                return cls.load(c)
        listed = "\n".join(f"  - {c}" for c in candidates)
        raise FileNotFoundError(
            f"找不到 studio.yaml，尝试过：\n{listed}\n"
            f"请复制 studio.yaml.example 为 studio.yaml，或设置 STUDIO_CONFIG 指向配置文件。"
        )

    @staticmethod
    def _apply_env_overrides(data: dict) -> dict:
        for key, value in os.environ.items():
            if not key.startswith("STUDIO__"):
                continue
            path = key[len("STUDIO__"):].lower().split("__")
            node = data
            for seg in path[:-1]:
                node = node.setdefault(seg, {})
                if not isinstance(node, dict):
                    break
            else:
                node[path[-1]] = value
        return data

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for seg in dotted.split("."):
            if not isinstance(node, dict) or seg not in node:
                return default
            node = node[seg]
        return node

    @property
    def root(self) -> Path:
        """studio 仓库根目录（解析相对路径用）。"""
        return self.path.parent if self.path else Path.cwd()

    def exports_dir(self) -> Path:
        p = Path(self.get("replay.exports_dir", "data/exports"))
        return p if p.is_absolute() else self.root / p

    def store_path(self) -> Path:
        p = self.root / "data" / "studio.db"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

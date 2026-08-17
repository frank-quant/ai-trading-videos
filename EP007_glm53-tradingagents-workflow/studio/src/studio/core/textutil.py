"""文本清洗：处理原项目报告里的转义残留与 dict 转储。"""
from __future__ import annotations

import ast
import re


def normalize_md(text: str) -> str:
    """把模型输出还原成可渲染的 markdown。

    原项目的部分 agent（研究团队/风控）把结果存成 Python dict 的 str()：
      {'judge_decision': '...', 'history': '...', 'bull_history': ...}
    换行还有双重转义（\\\\n）。策略：
      1. dict/list 字面量 -> ast.literal_eval，取 judge_decision 为正文
      2. 普通文本 -> 迭代还原 \\n \\t 等转义
    """
    t = text.strip()
    if t.startswith("{") and t.endswith("}"):
        try:
            obj = ast.literal_eval(t)
            if isinstance(obj, dict):
                return _dict_to_md(obj)
        except (ValueError, SyntaxError):
            pass
    return _unescape(t)


def _dict_to_md(obj: dict) -> str:
    """agent 结果 dict -> markdown。裁决是正文，过程性字段丢弃（辩论有专门视图）。"""
    primary = obj.get("judge_decision") or obj.get("current_response") or obj.get("decision")
    if isinstance(primary, str) and primary.strip():
        return _unescape(primary).strip()
    # 没有裁决字段：把字符串值拼成小节
    parts = []
    for k, v in obj.items():
        if isinstance(v, str) and v.strip() and len(v) > 20:
            parts.append(f"## {k}\n\n{_unescape(v).strip()}")
    return "\n\n".join(parts) if parts else _unescape(str(obj))


def _unescape(t: str) -> str:
    """迭代还原字面量转义（处理 \\n 与双重转义 \\\\n）。"""
    for _ in range(3):
        if "\\n" not in t and "\\t" not in t:
            break
        t = t.replace("\\n", "\n").replace("\\t", "\t")
    t = t.replace("\\'", "'").replace('\\"', '"')
    return re.sub(r"\n{4,}", "\n\n\n", t)

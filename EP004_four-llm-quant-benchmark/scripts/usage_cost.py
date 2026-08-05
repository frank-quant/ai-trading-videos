# -*- coding: utf-8 -*-
"""
EP004 · Claude Code 用量 → 等效成本
===================================
Claude Code 按【项目目录】分开记日志(~/.claude/projects/<编码路径>/*.jsonl),
所以 ft_opus_5 与 ft_fable_5 天然分开统计。本脚本读某个环境目录对应的日志,
汇总 token 并按公开 API 单价换算「等效成本」(你实际走会员,不额外付费)。

用法:
  python usage_cost.py --env ft_opus_5 --model opus5
  python usage_cost.py --env ft_fable_5 --model fable5 --since 2026-07-28T18:00:00

⚠️ 缓存倍率(cache write 1.25x / cache read 0.1x)是常见约定,**录制前请按官方定价核实**。
"""
import argparse
import glob
import json
import os
from datetime import datetime, timezone

# 每百万 token 的输入/输出单价(已核实的公开价)
PRICES = {
    "opus5":  (5.0, 25.0),
    "fable5": (10.0, 50.0),
    "kimik3": (3.0, 15.0),
    "gpt56":  (None, None),   # 待核实
}
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10


def encode_path(env_dir: str) -> str:
    """把工作目录路径转成 Claude Code 日志目录名的形式(近似匹配)。

    例:<盘符>:\\some\\dir\\ft_opus_5  ->  <盘符>--some-dir-ft-opus-5
    """
    return env_dir.replace(":", "-").replace("\\", "-").replace("/", "-").replace("_", "-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True, help="环境目录名或完整路径,如 ft_opus_5")
    ap.add_argument("--model", required=True, choices=list(PRICES))
    ap.add_argument("--since", default=None, help="ISO 时间,只统计此后的记录(如 2026-07-28T18:00:00)")
    ap.add_argument("--projects", default=os.path.expanduser("~/.claude/projects"))
    a = ap.parse_args()

    key = a.env.replace("_", "-").lower()
    cands = [d for d in glob.glob(os.path.join(a.projects, "*")) if key in os.path.basename(d).lower()]
    if not cands:
        raise SystemExit(f"[usage] 没找到匹配 '{a.env}' 的项目日志目录。先跑一次 CLI 再统计。\n"
                         f"        现有: {[os.path.basename(x) for x in glob.glob(os.path.join(a.projects,'*'))]}")

    since = None
    if a.since:
        since = datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc)

    tot = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    n_msg = 0
    for d in cands:
        for fp in glob.glob(os.path.join(d, "*.jsonl")):
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    if since:
                        ts = o.get("timestamp")
                        if ts:
                            try:
                                if datetime.fromisoformat(ts.replace("Z", "+00:00")) < since:
                                    continue
                            except Exception:
                                pass
                    u = (o.get("message") or {}).get("usage") or {}
                    if not u:
                        continue
                    n_msg += 1
                    tot["input"] += u.get("input_tokens", 0)
                    tot["output"] += u.get("output_tokens", 0)
                    tot["cache_read"] += u.get("cache_read_input_tokens", 0)
                    tot["cache_creation"] += u.get("cache_creation_input_tokens", 0)

    pin, pout = PRICES[a.model]
    print(f"[{a.model}] 日志目录: {[os.path.basename(x) for x in cands]}")
    print(f"  API 调用数: {n_msg}")
    for k, v in tot.items():
        print(f"  {k:<14}: {v:>12,}")
    if pin is None:
        print("  单价未核实,无法换算等效成本(录前用 WebSearch 补 GPT-5.6 定价)")
        return
    cost = (tot["input"] * pin
            + tot["cache_creation"] * pin * CACHE_WRITE_MULT
            + tot["cache_read"] * pin * CACHE_READ_MULT
            + tot["output"] * pout) / 1_000_000
    print(f"  >>> 等效成本 ≈ ${cost:.2f}  (单价 ${pin}/${pout} 每百万; cache write x{CACHE_WRITE_MULT}, read x{CACHE_READ_MULT})")
    print("  注: 你走会员实际不额外付费,此数字用于四家横向可比的性价比维度。")


if __name__ == "__main__":
    main()

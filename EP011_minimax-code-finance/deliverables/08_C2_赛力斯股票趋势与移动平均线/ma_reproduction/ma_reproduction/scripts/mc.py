"""Thin wrapper around `mcode-tools connector call`.

Handles two quirks of the CLI on Windows:
  1. stdout is UTF-16LE when redirected by PowerShell -> we run it directly and decode UTF-8.
  2. the CLI sometimes wraps the payload in MCP content blocks
     ([{"type":"text","text":"{...}"}]) -> unwrap and parse the inner JSON.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
ARGS_DIR = RAW / "_args"


def _unwrap(text: str):
    text = text.strip()
    if not text:
        raise ValueError("empty CLI output")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise
    if isinstance(payload, list) and payload and all(
        isinstance(p, dict) and p.get("type") == "text" and "text" in p for p in payload
    ):
        inner = "\n".join(p["text"] for p in payload)
        return json.loads(inner)
    if isinstance(payload, dict) and set(payload.keys()) == {"content"}:
        blocks = payload["content"]
        if all(isinstance(p, dict) and p.get("type") == "text" for p in blocks):
            return json.loads("\n".join(p["text"] for p in blocks))
    return payload


def call(tool: str, args: dict, *, save_as: str | None = None, quiet: bool = False):
    ARGS_DIR.mkdir(parents=True, exist_ok=True)
    arg_file = ARGS_DIR / f"{save_as or tool.split('__')[-1]}.json"
    arg_file.write_text(json.dumps(args, ensure_ascii=False, indent=2), encoding="utf-8")

    exe = "mcode-tools"
    if sys.platform == "win32":
        exe = r"C:\Users\10718\.minimax\bin\mcode-tools.cmd"
    proc = subprocess.run(
        [exe, "connector", "call", tool, "--args-file", str(arg_file)],
        capture_output=True,
        shell=(sys.platform == "win32"),
    )
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(
            f"{tool} exited {proc.returncode}\nSTDOUT:\n{stdout[:4000]}\nSTDERR:\n{stderr[:4000]}"
        )
    try:
        data = _unwrap(stdout)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"{tool}: could not parse output ({exc})\nRAW:\n{stdout[:4000]}") from exc

    if save_as:
        RAW.mkdir(parents=True, exist_ok=True)
        (RAW / save_as).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if not quiet:
        brief = {k: data.get(k) for k in
                 ("status", "cacheStatus", "coverageComplete", "symbol", "adjustment",
                  "matchStatus", "matchStatus", "asOf", "fetchedAt", "revision",
                  "basisVersion", "effectiveRange", "reason", "errors")
                 if isinstance(data, dict) and k in data}
        if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
            brief["items_len"] = len(data["items"])
        print(f"[{tool}] {json.dumps(brief, ensure_ascii=False)}", file=sys.stderr)
    return data


if __name__ == "__main__":
    tool = sys.argv[1]
    args = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    out = call(tool, args, save_as=sys.argv[3] if len(sys.argv) > 3 else None)
    print(json.dumps(out, ensure_ascii=False)[:2000])

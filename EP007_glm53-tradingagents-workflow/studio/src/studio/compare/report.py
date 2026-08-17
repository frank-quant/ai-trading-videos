"""对比表输出：终端 rich 表 + markdown + CSV。"""
from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

from rich.console import Console
from rich.table import Table

COLUMNS = [
    ("model", "模型", "left"),
    ("status", "状态", "left"),
    ("wall_s", "耗时(s)", "right"),
    ("report_chars", "报告字数", "right"),
    ("prompt_tokens", "输入tok", "right"),
    ("completion_tokens", "输出tok", "right"),
    ("cost", "成本", "right"),
    ("decision", "决策", "left"),
]


def render_terminal(rows: list[dict], title: str) -> None:
    table = Table(title=title, show_lines=False)
    for _, header, justify in COLUMNS:
        table.add_column(header, justify=justify)  # type: ignore[arg-type]
    for row in rows:
        cells = []
        for key, _, _ in COLUMNS:
            v = row.get(key, "")
            cells.append(str(v) if v != "" else "-")
        table.add_row(*cells)
    Console().print(table)


def render_markdown(rows: list[dict], meta: dict) -> str:
    lines = [
        f"# 模型对比：{meta.get('symbol')}（{meta.get('depth')}）",
        "",
        f"- 时间：{meta.get('created_at')}",
        f"- 模型数：{len(rows)}",
        "",
        "| " + " | ".join(h for _, h, _ in COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
    ]
    for row in rows:
        cells = [str(row.get(k, "") or "-") for k, _, _ in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    if any(r.get("steps") for r in rows):
        lines += ["", "## 分步耗时", ""]
        for row in rows:
            if row.get("steps"):
                lines.append(f"- **{row['model']}**: {row['steps']}")
    if any(r.get("error") for r in rows):
        lines += ["", "## 错误", ""]
        for row in rows:
            if row.get("error"):
                lines.append(f"- **{row['model']}**: {row['error']}")
    lines.append("")
    return "\n".join(lines)


def render_csv(rows: list[dict]) -> str:
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([k for k, _, _ in COLUMNS])
    for row in rows:
        writer.writerow([row.get(k, "") for k, _, _ in COLUMNS])
    return buf.getvalue()


def write_outputs(md_text: str, csv_text: str, out_dir: Path, stem: str) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{stem}.md"
    csv_path = out_dir / f"{stem}.csv"
    md_path.write_text(md_text, encoding="utf-8")
    csv_path.write_text(csv_text, encoding="utf-8-sig")  # Excel 直接打开不乱码
    return {"markdown": md_path, "csv": csv_path}

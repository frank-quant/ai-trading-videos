from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parent
text = (root / "PLAN.md").read_text(encoding="utf-8")
rows = re.findall(r"^\| (\d{2}) \| (L\d\w*) \| (.+?) \|", text, flags=re.M)
assert len(rows) == 25, f"expected 25 pages, got {len(rows)}"
geom = r"D:/KimiData/daimon-share/daimon/runtime/kimi-code/home/plugins/managed/institutional-finance-kit/skills/institutional-slides/scripts/text-geom.mjs"
failed = []
for page, layout, title in rows:
    if layout not in {"L04"}:
        continue
    result = subprocess.run(
        ["D:/KimiData/daimon-share/daimon/command-process-owner/bin/node.cmd", geom, "--text", title, "--width", "1312", "--size", "28", "--font", "Georgia", "--bold"],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    output = (result.stdout + result.stderr).strip()
    print(f"page-{page}: {output}")
    if result.returncode != 0:
        failed.append((page, output))
print(f"content_titles={sum(1 for _, l, _ in rows if l == 'L04')}, failures={len(failed)}")
if failed:
    raise SystemExit(1)

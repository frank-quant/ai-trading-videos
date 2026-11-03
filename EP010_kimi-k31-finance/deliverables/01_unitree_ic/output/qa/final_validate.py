from pathlib import Path
import json
import re
import yaml

root = Path(__file__).resolve().parents[1]
deck = root / "deck"
presentation = yaml.safe_load((deck / "presentation.pptd").read_text(encoding="utf-8"))
assert len(presentation["pages"]) == 25
for rel in presentation["pages"]:
    page = deck / rel
    assert page.exists(), rel
    data = yaml.safe_load(page.read_text(encoding="utf-8"))
    ids = [e.get("elementId", "") for e in data["elements"]]
    assert len(ids) == len(set(ids)), f"duplicate element id in {rel}"
    for element in data["elements"]:
        src = element.get("src")
        if src and not str(src).startswith(("http://", "https://")):
            assert (deck / src).exists(), f"missing media {src} in {rel}"
    text = page.read_text(encoding="utf-8")
    assert "{{" not in text and "TBD" not in text and "TODO" not in text

plan = (deck / "PLAN.md").read_text(encoding="utf-8")
rows = re.findall(r"^\| \d{2} \| L\d\w* \|", plan, flags=re.M)
assert len(rows) == 25
registry = json.loads((deck / "data-registry.json").read_text(encoding="utf-8"))
assert registry["meta"]["schema_version"] == "dr-1.0"
assert len(registry["data_points"]) == 71
required_reports = {
    "20260809_东吴证券_人形机器人产业化奇点已至.pdf": 32,
    "20260812_华金证券_新股覆盖研究.pdf": 12,
    "20260919_华鑫证券_茁壮成长的中国树.pdf": 8,
    "20261022_太平洋证券_宇树科技深度报告.pdf": 32,
    "20261030_东吴证券_2026年三季报点评.pdf": 3,
}
for name, pages in required_reports.items():
    path = root / "research" / name
    assert path.exists() and path.stat().st_size > 100000, name
    txt = path.with_suffix(".txt").read_text(encoding="utf-8")
    assert f"/ {pages} " in txt or f"/ {pages}\n" in txt, name
print(json.dumps({
    "deck_pages": 25,
    "plan_rows": 25,
    "registry_points": 71,
    "full_research_reports": 5,
    "institutions": ["东吴证券", "太平洋证券", "华鑫证券", "华金证券"],
    "presentation": str(deck / "presentation.pptd"),
    "media_integrity": "pass",
    "placeholders": 0,
    "status": "PASS"
}, ensure_ascii=False, indent=2))

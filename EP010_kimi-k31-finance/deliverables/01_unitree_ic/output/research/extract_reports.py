from pathlib import Path
import json
from pypdf import PdfReader

root = Path(__file__).resolve().parent
manifest = []
for pdf_path in sorted(root.glob("*.pdf")):
    reader = PdfReader(str(pdf_path))
    chunks = []
    page_chars = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        page_chars.append(len(text))
        chunks.append(f"\n\n===== PDF PAGE {idx} / {len(reader.pages)} =====\n\n{text}")
    txt_path = pdf_path.with_suffix(".txt")
    txt_path.write_text("".join(chunks), encoding="utf-8")
    manifest.append({
        "file": pdf_path.name,
        "text_file": txt_path.name,
        "pages": len(reader.pages),
        "bytes": pdf_path.stat().st_size,
        "text_chars": sum(page_chars),
        "min_page_chars": min(page_chars) if page_chars else 0,
        "page_chars": page_chars,
    })
(root / "extraction_manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(manifest, ensure_ascii=False, indent=2))

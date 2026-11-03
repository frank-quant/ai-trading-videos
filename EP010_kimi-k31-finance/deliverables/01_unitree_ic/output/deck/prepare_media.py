from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parent / "media"
for src in root.glob("*-original.jpg"):
    out = src.with_name(src.name.replace("-original", ""))
    with Image.open(src) as im:
        im = im.convert("RGB").resize((1440, 810), Image.Resampling.LANCZOS)
        im.save(out, "JPEG", quality=82, optimize=True, progressive=True)
    print(out.name, out.stat().st_size)

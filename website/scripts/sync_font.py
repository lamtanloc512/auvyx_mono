#!/usr/bin/env python3
"""Đồng bộ font Auvyx Mono từ repo font sang trang web.

- Copy webfont variable (woff2) vào public/fonts/
- Tạo public/download/AuvyxMono.zip (ttf, otf, variable, OFL)
- Tạo src/data/glyphs.json (danh sách ký tự để hiển thị bảng glyph)
- Tạo public/og.png (ảnh chia sẻ mạng xã hội, render bằng chính font)

Dùng:  python3 scripts/sync_font.py [đường dẫn tới repo auvyx_mono]
Cần:   pip install fonttools brotli pillow freetype-py uharfbuzz
"""

from __future__ import annotations

import json
import shutil
import sys
import unicodedata
import zipfile
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONT_REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "auvyx_mono"
SRC = FONT_REPO / "fonts" / "AuvyxMono"

GROUPS = [
    ("Latin", [(0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F), (0x1E00, 0x1EFF)]),
    ("Numbers", [(0x0030, 0x0039), (0x00B2, 0x00B3), (0x00B9, 0x00B9), (0x00BC, 0x00BE), (0x2070, 0x209F), (0x2150, 0x218F)]),
    ("Punctuation", [(0x0021, 0x002F), (0x003A, 0x0040), (0x005B, 0x0060), (0x007B, 0x007E), (0x00A1, 0x00BF), (0x2010, 0x205F)]),
    ("Symbols", [(0x20A0, 0x20CF), (0x2100, 0x214F), (0x2200, 0x22FF), (0x2300, 0x23FF), (0x25A0, 0x25FF), (0x2600, 0x27BF), (0x2B00, 0x2BFF)]),
    ("Arrows", [(0x2190, 0x21FF), (0x27F0, 0x27FF), (0x2900, 0x297F)]),
    ("Box & blocks", [(0x2500, 0x259F), (0x1FB00, 0x1FBFF)]),
    ("Greek", [(0x0370, 0x03FF), (0x1F00, 0x1FFF)]),
    ("Cyrillic", [(0x0400, 0x052F)]),
    ("Powerline", [(0xE0A0, 0xE0FF)]),
]


def group_of(cp: int) -> str | None:
    for name, ranges in GROUPS:
        if any(a <= cp <= b for a, b in ranges):
            return name
    return None


def main() -> None:
    if not SRC.is_dir():
        sys.exit(f"Không tìm thấy {SRC}. Chạy `make auvyx` trong repo font trước.")

    fonts_out = ROOT / "public" / "fonts"
    fonts_out.mkdir(parents=True, exist_ok=True)
    for name in ("AuvyxMono[wght].woff2", "AuvyxMono-Italic[wght].woff2"):
        shutil.copy2(SRC / "webfonts" / name, fonts_out / name.replace("[wght]", "-Variable"))

    dl = ROOT / "public" / "download"
    dl.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dl / "AuvyxMono.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for sub in ("ttf", "otf", "variable", "webfonts"):
            for f in sorted((SRC / sub).glob("*")):
                z.write(f, f"AuvyxMono/{sub}/{f.name}")
        z.write(FONT_REPO / "OFL.txt", "AuvyxMono/OFL.txt")

    font = TTFont(SRC / "variable" / "AuvyxMono[wght].ttf")
    cmap = font.getBestCmap()
    glyphs: dict[str, list] = {g: [] for g, _ in GROUPS}
    for cp in sorted(cmap):
        g = group_of(cp)
        if g is None or unicodedata.category(chr(cp)) in ("Cc", "Cf", "Zs", "Zl", "Zp", "Mn"):
            continue
        glyphs[g].append([cp, unicodedata.name(chr(cp), f"U+{cp:04X}").title()])
    meta = {
        "version": font["name"].getDebugName(5),
        "glyphCount": len(font.getGlyphOrder()),
        "charCount": len(cmap),
        "groups": [{"name": g, "chars": glyphs[g]} for g, _ in GROUPS if glyphs[g]],
    }
    (ROOT / "src" / "data" / "glyphs.json").write_text(json.dumps(meta, ensure_ascii=False))

    make_og(SRC / "ttf")
    print(f"OK: {meta['charCount']} ký tự, {meta['glyphCount']} glyph, {meta['version']}")


def make_og(ttf_dir: Path) -> None:
    import uharfbuzz as hb
    from fontTools.pens.freetypePen import FreeTypePen
    from fontTools.pens.transformPen import TransformPen
    from PIL import Image

    def text(path: Path, s: str, size: int):
        f = TTFont(path)
        gs, order = f.getGlyphSet(), f.getGlyphOrder()
        hbf = hb.Font(hb.Face(hb.Blob.from_file_path(str(path))))
        buf = hb.Buffer()
        buf.add_str(s)
        buf.guess_segment_properties()
        hb.shape(hbf, buf, {})
        pen, x = FreeTypePen(gs), 0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            gs[order[info.codepoint]].draw(TransformPen(pen, (1, 0, 0, 1, x + pos.x_offset, pos.y_offset)))
            x += pos.x_advance
        sc = size / 1000
        return pen.image(width=max(x, 1) * sc, height=1250 * sc, transform=(sc, 0, 0, sc, 0, 280 * sc), contain=False)

    W, H = 1200, 630
    img = Image.new("RGB", (W, H), "#101116")

    def put(im, xy, color):
        img.paste(Image.new("RGB", im.size, color), xy, im.split()[-1])

    put(text(ttf_dir / "AuvyxMono-Bold.ttf", "Auvyx Mono", 150), (70, 150), "#f2efe9")
    put(text(ttf_dir / "AuvyxMono-Italic.ttf", "a monospaced typeface for code", 44), (78, 360), "#ff7a59")
    put(text(ttf_dir / "AuvyxMono-Regular.ttf", "=> != === |> ... Tiếng Việt · Thin → Bold", 32), (80, 470), "#9a98a3")
    out = ROOT / "public" / "og.png"
    img.save(out, optimize=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Tạo Auvyx Mono từ các file font Lilex đã build.

- Đổi tên họ font (name table, CFF, tên file)
- Gắn cứng các biến thể (cvXX / zero) được chọn làm mặc định bằng cách
  trỏ cmap sang glyph thay thế; feature tương ứng được đảo ngược để
  bật lên sẽ trả về glyph gốc.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import copy
import math

import yaml
from fontTools import ttLib
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib.tables import ttProgram
from fontTools.varLib.iup import iup_delta

FONT_EXTENSIONS = {".ttf", ".otf", ".woff", ".woff2"}
PS_NAME_IDS = {3, 6, 20, 25}


def _single_subst_tables(lookup):
    """Trả về các subtable SingleSubst (bỏ qua lớp Extension)."""
    for st in lookup.SubTable:
        if lookup.LookupType == 7:
            if st.ExtensionLookupType != 1:
                continue
            st = st.ExtSubTable
        elif lookup.LookupType != 1:
            continue
        yield st


def _feature_lookups(font: ttLib.TTFont, tag: str) -> list:
    gsub = font["GSUB"].table
    indices = set()
    for rec in gsub.FeatureList.FeatureRecord:
        if rec.FeatureTag == tag:
            indices.update(rec.Feature.LookupListIndex)
    if not indices:
        raise SystemExit(f"Feature '{tag}' không có trong font")
    return [gsub.LookupList.Lookup[i] for i in sorted(indices)]


def make_default(font: ttLib.TTFont, tag: str) -> int:
    """Gắn cứng một feature thay thế đơn (single substitution)."""
    mapping: dict[str, str] = {}
    for lookup in _feature_lookups(font, tag):
        if lookup.LookupType not in (1, 7):
            raise SystemExit(
                f"'{tag}' không phải feature thay thế đơn, không gắn cứng được "
                "(chỉ hỗ trợ cvXX/zero dạng single substitution)"
            )
        for st in _single_subst_tables(lookup):
            mapping.update(st.mapping)

    changed = 0
    for table in font["cmap"].tables:
        for cp, glyph in list(table.cmap.items()):
            if glyph in mapping:
                table.cmap[cp] = mapping[glyph]
                changed += 1

    # Đảo ngược feature: bật lên sẽ trả về glyph gốc
    reverse = {v: k for k, v in mapping.items()}
    if len(reverse) == len(mapping):
        for lookup in _feature_lookups(font, tag):
            for st in _single_subst_tables(lookup):
                st.mapping = {st.mapping[k]: k for k in st.mapping}
    return changed


def is_italic(font: ttLib.TTFont) -> bool:
    return bool(font["OS/2"].fsSelection & 1) or font["post"].italicAngle != 0


def upright_partner(path: Path) -> Path | None:
    """Lilex-BoldItalic.ttf → Lilex-Bold.ttf, Lilex-Italic.ttf → Lilex-Regular.ttf."""
    stem = path.stem
    if "-Italic[" in stem:
        stem = stem.replace("-Italic", "")
    elif stem.endswith("-Italic"):
        stem = stem[: -len("Italic")] + "Regular"
    elif stem.endswith("Italic"):
        stem = stem[: -len("Italic")]
    else:
        return None
    partner = path.with_name(stem + path.suffix)
    return partner if partner.exists() else None


def _center(font: ttLib.TTFont, name: str) -> float:
    pen = BoundsPen(font.getGlyphSet())
    font.getGlyphSet()[name].draw(pen)
    x0, _, x1, _ = pen.bounds
    return (x0 + x1) / 2


def slant_from_upright(italic: ttLib.TTFont, upright: ttLib.TTFont, name: str) -> None:
    """Thay glyph nghiêng bằng glyph đứng được xiên theo italicAngle."""
    t = math.tan(math.radians(-italic["post"].italicAngle))
    target_center = _center(italic, name)

    if "glyf" in italic:
        src = copy.deepcopy(upright["glyf"][name])
        if src.isComposite():
            raise SystemExit(f"'{name}' là glyph ghép, chưa hỗ trợ")
        coords = src.coordinates
        for i, (x, y) in enumerate(coords):
            coords[i] = (x + t * y, y)
        src.recalcBounds(upright["glyf"])
        dx = round(target_center - (src.xMin + src.xMax) / 2)
        for i, (x, y) in enumerate(coords):
            coords[i] = (round(x + dx), y)
        src.program = ttProgram.Program()
        src.program.fromBytecode(b"")
        italic["glyf"][name] = src
        src.recalcBounds(italic["glyf"])
        italic["hmtx"][name] = (upright["hmtx"][name][0], src.xMin)

        if "gvar" in italic and "gvar" in upright:
            base = upright["glyf"][name]
            ucoords = list(base.coordinates)
            ends = list(base.endPtsOfContours)
            new_vars = []
            for var in upright["gvar"].variations.get(name, []):
                v = copy.deepcopy(var)
                pts = v.coordinates[: len(ucoords)]
                phantom = v.coordinates[len(ucoords):]
                if any(p is None for p in pts):
                    pts = iup_delta(pts, ucoords, ends)
                sheared = [(round(ddx + t * ddy), ddy) for ddx, ddy in pts]
                phantom = [p if p is not None else (0, 0) for p in phantom]
                v.coordinates = sheared + phantom
                new_vars.append(v)
            italic["gvar"].variations[name] = new_vars
    elif "CFF " in italic:
        top = italic["CFF "].cff.topDictIndex[0]
        width = upright["hmtx"][name][0]
        pen = T2CharStringPen(width, None)
        bpen = BoundsPen(None)
        upright.getGlyphSet()[name].draw(TransformPen(bpen, (1, 0, t, 1, 0, 0)))
        x0, _, x1, _ = bpen.bounds
        dx = round(target_center - (x0 + x1) / 2)
        upright.getGlyphSet()[name].draw(TransformPen(pen, (1, 0, t, 1, dx, 0)))
        top.CharStrings[name] = pen.getCharString(private=top.Private, globalSubrs=italic["CFF "].cff.GlobalSubrs)
        italic["hmtx"][name] = (width, round(x0 + dx))
    else:
        raise SystemExit("Định dạng outline không hỗ trợ")


def rename(font: ttLib.TTFont, cfg: dict) -> None:
    src, fam, ps = cfg["source_family"], cfg["family"], cfg["postscript"]
    name = font["name"]
    ps_ids = set(PS_NAME_IDS)
    if "fvar" in font:
        ps_ids.update(
            i.postscriptNameID for i in font["fvar"].instances if i.postscriptNameID != 0xFFFF
        )
    for rec in list(name.names):
        value = rec.toUnicode()
        new = value
        if rec.nameID == 0:
            if cfg.get("copyright") and cfg["copyright"] not in value:
                new = f"{cfg['copyright']}. Based on Lilex: {value}"
        elif rec.nameID == 9:
            if cfg.get("designer") and cfg["designer"] not in value:
                new = f"{value}, {cfg['designer']}"
        elif rec.nameID == 8 and cfg.get("designer"):
            new = cfg["designer"]
        elif rec.nameID == 11 and not cfg.get("vendor_url"):
            name.removeNames(nameID=11)
            continue
        elif src in value:
            new = value.replace(src, ps if rec.nameID in ps_ids else fam)
        if new != value:
            name.setName(new, rec.nameID, rec.platformID, rec.platEncID, rec.langID)

    if "CFF " in font:
        cff = font["CFF "].cff
        cff.fontNames = [n.replace(src, ps) for n in cff.fontNames]
        top = cff.topDictIndex[0]
        for attr in ("FamilyName", "FullName"):
            if hasattr(top, attr):
                setattr(top, attr, getattr(top, attr).replace(src, fam))
        if hasattr(top, "Notice") and cfg.get("copyright"):
            top.Notice = f"{cfg['copyright']}. {top.Notice}"


def process(source_dir: Path, target_dir: Path, cfg: dict) -> None:
    src, ps = cfg["source_family"], cfg["postscript"]
    if target_dir.exists():
        shutil.rmtree(target_dir)
    for item in sorted(source_dir.rglob("*")):
        rel = item.relative_to(source_dir)
        dest = target_dir / Path(*[p.replace(src, ps) for p in rel.parts])
        if item.is_dir():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if item.suffix not in FONT_EXTENSIONS:
            shutil.copy2(item, dest)
            continue
        font = ttLib.TTFont(str(item))
        italic = is_italic(font)
        notes = []
        feats = cfg.get("default_features", {})
        if isinstance(feats, list):
            feats = {"upright": feats, "italic": feats}
        for t in feats.get("italic" if italic else "upright", []) or []:
            notes.append(f"{t}:{make_default(font, t)}")
        if italic and cfg.get("italic_from_upright"):
            partner = upright_partner(item)
            if partner is None:
                sys.exit(f"Không tìm thấy bản đứng tương ứng cho {item.name}")
            upright = ttLib.TTFont(str(partner))
            for g in cfg["italic_from_upright"]:
                slant_from_upright(font, upright, g)
                notes.append(f"{g}←{partner.name}")
        rename(font, cfg)
        font.save(str(dest))
        print(f"  {rel} → {dest.relative_to(target_dir)}  [{' '.join(notes)}]")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source_dir", type=Path, help="Thư mục font Lilex (vd: fonts/Lilex)")
    p.add_argument("--config", type=Path, default=Path("sources/auvyx.yaml"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if not a.source_dir.is_dir():
        sys.exit(f"Không tìm thấy {a.source_dir}")
    cfg = yaml.safe_load(a.config.read_text(encoding="utf-8"))
    print(f"{cfg['source_family']} → {cfg['family']}  (mặc định: {cfg.get('default_features')})")
    process(a.source_dir.resolve(), a.output.resolve(), cfg)
    print(f"Xong: {a.output}")


if __name__ == "__main__":
    main()

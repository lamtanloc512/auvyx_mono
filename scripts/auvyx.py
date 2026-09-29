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
from fontTools.pens.pointPen import DecomposingPointPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib.tables import ttProgram
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.varLib import instancer
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
                full = _full_deltas(upright, name, var)
                pts, phantom = full[: len(ucoords)], full[len(ucoords):]
                sheared = [(round(ddx + t * ddy), ddy) for ddx, ddy in pts]
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


def _full_deltas(font: ttLib.TTFont, name: str, var) -> list:
    """Deltas đầy đủ cho mọi điểm (kể cả 4 phantom point), nội suy IUP nếu thiếu."""
    if all(p is not None for p in var.coordinates):
        return list(var.coordinates)
    coords, ctrl = font["glyf"]._getCoordinatesAndControls(
        name, font["hmtx"].metrics, font["vmtx"].metrics if "vmtx" in font else None
    )
    return list(iup_delta(var.coordinates, coords, ctrl.endPts))


def _unfoot_points(pts: list, ends: list, name: str) -> list:
    """Bỏ chân serif ở baseline: kẹp các điểm thấp vào hai cạnh thân chữ."""
    low = [y for _, y in pts if 0 < y <= 150]
    if not low:
        raise SystemExit(f"'{name}': không tìm thấy chân serif")
    top = min(low)
    starts = [0] + [e + 1 for e in ends[:-1]]
    edges = set()
    for st, en in zip(starts, ends):
        n = en - st + 1
        for k in range(n):
            x, y = pts[st + k]
            if y != top:
                continue
            for nb in (pts[st + (k - 1) % n], pts[st + (k + 1) % n]):
                if nb[0] == x and nb[1] > top:
                    edges.add(x)
    if len(edges) != 2:
        raise SystemExit(f"'{name}': không xác định được thân chữ (cạnh: {sorted(edges)})")
    lo, hi = sorted(edges)
    return [(min(max(x, lo), hi), y) if y <= top else (x, y) for x, y in pts]


def remove_foot(font: ttLib.TTFont, name: str) -> None:
    if "glyf" in font:
        glyf = font["glyf"]
        g = glyf[name]
        base = list(g.coordinates)
        ends = list(g.endPtsOfContours)
        new_base = _unfoot_points(base, ends, name)
        if "gvar" in font:
            new_vars = []
            for var in font["gvar"].variations.get(name, []):
                v = copy.deepcopy(var)
                full = _full_deltas(font, name, var)
                d, phantom = full[: len(base)], full[len(base):]
                master = [(x + dx, y + dy) for (x, y), (dx, dy) in zip(base, d)]
                new_master = _unfoot_points(master, ends, name)
                v.coordinates = [
                    (round(mx - bx), round(my - by))
                    for (mx, my), (bx, by) in zip(new_master, new_base)
                ] + phantom
                new_vars.append(v)
            font["gvar"].variations[name] = new_vars
        for i, pt in enumerate(new_base):
            g.coordinates[i] = pt
        g.program = ttProgram.Program()
        g.program.fromBytecode(b"")
        g.recalcBounds(glyf)
        font["hmtx"][name] = (font["hmtx"][name][0], g.xMin)
    elif "CFF " in font:
        top = font["CFF "].cff.topDictIndex[0]
        rec = RecordingPen()
        font.getGlyphSet()[name].draw(rec)
        pts, ends = [], []
        for op, args in rec.value:
            pts.extend(args)
            if op in ("closePath", "endPath") and pts:
                ends.append(len(pts) - 1)
        # điểm đầu (moveTo) trùng điểm cuối contour trong CFF → vẫn đúng với heuristic
        new = _unfoot_points(pts, ends, name)
        it = iter(new)
        width = font["hmtx"][name][0]
        pen = T2CharStringPen(width, None)
        for op, args in rec.value:
            getattr(pen, op)(*[next(it) for _ in args])
        top.CharStrings[name] = pen.getCharString(private=top.Private, globalSubrs=font["CFF "].cff.GlobalSubrs)
        bp = BoundsPen(None)
        font.getGlyphSet()[name].draw(bp)
        font["hmtx"][name] = (width, round(bp.bounds[0]))


# ---------------------------------------------------------------------------
# Ghép glyph từ font OFL khác (vd: Recursive)
# ---------------------------------------------------------------------------

_IMPORT_CACHE: dict = {}


def _source_glyph_names(path: str, font: ttLib.TTFont, chars: str) -> dict:
    """Tên glyph thực tế sau khi áp rvrn/feature variations (shape bằng HarfBuzz)."""
    import tempfile

    import uharfbuzz as hb

    with tempfile.NamedTemporaryFile(suffix=".ttf") as tmp:
        font.save(tmp.name)
        hbf = hb.Font(hb.Face(hb.Blob.from_file_path(tmp.name)))
        order = font.getGlyphOrder()
        names = {}
        for ch in chars:
            buf = hb.Buffer()
            buf.add_str(ch)
            buf.guess_segment_properties()
            hb.shape(hbf, buf, {})
            gid = buf.glyph_infos[0].codepoint
            if gid == 0:
                raise SystemExit(f"Font nguồn không có ký tự '{ch}'")
            names[ch] = order[gid]
        return names


def _instance(src: str, loc: dict) -> ttLib.TTFont:
    key = (src, tuple(sorted(loc.items())))
    if key not in _IMPORT_CACHE:
        _IMPORT_CACHE[key] = instancer.instantiateVariableFont(
            ttLib.TTFont(src), loc, updateFontNames=False
        )
    return _IMPORT_CACHE[key]


class _Collect(DecomposingPointPen):
    """Gom điểm outline (đã tách glyph ghép) theo đúng thứ tự, để các vị trí trục tương thích nhau."""

    skipMissingComponents = True

    def __init__(self, glyphSet):
        super().__init__(glyphSet)
        self.coords, self.ends, self.flags = [], [], []

    def beginPath(self, identifier=None, **kw):
        pass

    def addPoint(self, pt, segmentType=None, smooth=False, name=None, identifier=None, **kw):
        self.coords.append((float(pt[0]), float(pt[1])))
        self.flags.append(1 if segmentType else 0)

    def endPath(self):
        if self.coords and (not self.ends or self.ends[-1] != len(self.coords) - 1):
            self.ends.append(len(self.coords) - 1)


def _outline_at(vf: ttLib.TTFont, name: str, loc: dict):
    gs = vf.getGlyphSet(location=loc, normalized=False)
    pen = _Collect(gs)
    gs[name].drawPoints(pen)
    return pen.coords, pen.ends, pen.flags


def _stroke(coords, ends, flags) -> float:
    """Độ dày nét trung bình ≈ 2·diện tích / chu vi (đo trên ảnh raster, xử lý được contour chồng nhau)."""
    import numpy as np
    from fontTools.pens.freetypePen import FreeTypePen

    g = _make_glyph(coords, ends, flags)
    pen = FreeTypePen(None)
    g.draw(pen, None)
    sc = 0.5
    a = np.asarray(pen.array(width=int(1700 * sc), height=int(1900 * sc), transform=(sc, 0, 0, sc, 550 * sc, 550 * sc), contain=False)) > 0.5
    area = a.sum()
    if not area:
        return 0.0
    inner = a[1:-1, 1:-1] & a[:-2, 1:-1] & a[2:, 1:-1] & a[1:-1, :-2] & a[1:-1, 2:]
    return 2 * area / (area - inner.sum()) / sc


def _import_masters(spec: dict, root: Path) -> dict:
    """Trả về {char: {lilex_wght: (coords, ends, flags)}} đã khớp zone (và khớp độ dày nét nếu bật)."""
    key = ("masters", id(spec))
    if key in _IMPORT_CACHE:
        return _IMPORT_CACHE[key]
    src = str(root / spec["source"])
    vf = ttLib.TTFont(src)
    axes = {a.axisTag: a for a in vf["fvar"].axes}
    wmin, wmax = axes["wght"].minValue, axes["wght"].maxValue
    loc = dict(spec.get("location", {}))
    chars = spec["chars"].replace(" ", "")
    t = math.tan(math.radians(-loc.get("slnt", 0)))
    zs, zt = spec["zones"]["source"], spec["zones"]["target"]
    step = spec.get("extrapolate_step", 50)

    def zone(y: float) -> float:
        for i in range(len(zs) - 1):
            if y <= zs[i + 1] or i == len(zs) - 2:
                a, b, c, d = zs[i], zs[i + 1], zt[i], zt[i + 1]
                return c + (y - a) * (d - c) / (b - a)
        return y

    def raw(name: str, w: float):
        if w >= wmin:
            return _outline_at(vf, name, {**loc, "wght": min(w, wmax)})
        # ngoại suy dưới độ đậm nhỏ nhất của font nguồn
        c0, e, fl = _outline_at(vf, name, {**loc, "wght": wmin})
        c1, _, _ = _outline_at(vf, name, {**loc, "wght": wmin + step})
        k = (wmin - w) / step
        return [(x0 + (x0 - x1) * k, y0 + (y0 - y1) * k) for (x0, y0), (x1, y1) in zip(c0, c1)], e, fl

    def fitted(name: str, w: float):
        coords, ends, flags = raw(name, w)
        out = []
        for x, y in coords:
            xu = x - t * y
            y2 = zone(y)
            out.append((xu + t * y2, y2))
        return out, ends, flags

    base = _instance(src, {**loc, "wght": max(wmin, 400)})
    ch_names = _source_glyph_names(src, base, chars)
    ch_names.update(spec.get("source_names", {}) or {})  # ép dùng glyph khác trong font nguồn

    # Tham chiếu: glyph Lilex gốc của chính ký tự đó, để chữ mới đậm/nhạt đúng như chữ nó thay thế
    ref = None
    if spec.get("match_stroke") and spec.get("reference"):
        ref = ttLib.TTFont(str(root / spec["reference"]))
        ref_cmap = ref.getBestCmap()

    result: dict = {ch: {} for ch in chars}
    report = []
    for ch, name in ch_names.items():
        picks = {}
        for lw, sw in spec["masters"].items():
            lw = int(lw)
            if ref is not None and ord(ch) in ref_cmap:
                target = _stroke(*_outline_at(ref, ref_cmap[ord(ch)], {"wght": lw}))
                lo, hi = wmin - 3 * step, wmax
                for _ in range(14):  # chia đôi: độ dày nét tăng đơn điệu theo wght
                    mid = (lo + hi) / 2
                    if _stroke(*fitted(name, mid)) < target:
                        lo = mid
                    else:
                        hi = mid
                sw = round((lo + hi) / 2, 1)
            picks[lw] = sw
            result[ch][lw] = fitted(name, sw)
        report.append(f"{ch}:" + "/".join(f"{v:g}" for v in picks.values()))
    if ref is not None:
        print(f"    [{spec['name']}] wght nguồn theo nét: " + " ".join(report))
    for ch, ms in result.items():
        shapes = {(len(c), tuple(e)) for c, e, _ in ms.values()}
        if len(shapes) != 1:
            raise SystemExit(f"'{ch}': outline không tương thích giữa các master")
    _IMPORT_CACHE[key] = (result, ch_names)
    return result, ch_names


def _lerp_master(ms: dict, w: float):
    ws = sorted(ms)
    w = min(max(w, ws[0]), ws[-1])
    for a, b in zip(ws, ws[1:]):
        if a <= w <= b:
            r = (w - a) / (b - a)
            ca, e, fl = ms[a]
            cb = ms[b][0]
            return [(xa + (xb - xa) * r, ya + (yb - ya) * r) for (xa, ya), (xb, yb) in zip(ca, cb)], e, fl
    return ms[ws[0]]


def _make_glyph(coords, ends, flags) -> Glyph:
    g = Glyph()
    g.numberOfContours = len(ends)
    g.coordinates = GlyphCoordinates([(round(x), round(y)) for x, y in coords])
    g.endPtsOfContours = ends
    fl = bytearray(flags)
    if fl:
        fl[0] |= 0x40  # OVERLAP_SIMPLE
    g.flags = fl
    g.program = ttProgram.Program()
    g.program.fromBytecode(b"")
    return g


def import_glyphs(font: ttLib.TTFont, spec: dict, root: Path) -> list:
    masters, _ = _import_masters(spec, root)
    cmap = font.getBestCmap()
    width = font["hmtx"]["n"][0] if "n" in font["hmtx"].metrics else 600
    done = []
    for ch, ms in masters.items():
        name = cmap.get(ord(ch))
        if not name:
            continue
        if "fvar" in font:
            default = ms[400]
            g = _make_glyph(*default)
            font["glyf"][name] = g
            g.recalcBounds(font["glyf"])
            font["hmtx"][name] = (width, g.xMin)
            dc = [(round(x), round(y)) for x, y in default[0]]
            variations = []
            for w, region in ((100, (-1.0, -1.0, 0.0)), (700, (0.0, 1.0, 1.0))):
                mc = [(round(x), round(y)) for x, y in ms[w][0]]
                deltas = [(mx - dx, my - dy) for (mx, my), (dx, dy) in zip(mc, dc)] + [(0, 0)] * 4
                variations.append(TupleVariation({"wght": region}, deltas))
            font["gvar"].variations[name] = variations
        else:
            w = font["OS/2"].usWeightClass
            coords, ends, flags = _lerp_master(ms, w)
            g = _make_glyph(coords, ends, flags)
            if "glyf" in font:
                font["glyf"][name] = g
                g.recalcBounds(font["glyf"])
                font["hmtx"][name] = (width, g.xMin)
            else:
                top = font["CFF "].cff.topDictIndex[0]
                pen = T2CharStringPen(width, None)
                g.draw(pen, None)
                top.CharStrings[name] = pen.getCharString(private=top.Private, globalSubrs=font["CFF "].cff.GlobalSubrs)
                bp = BoundsPen(None)
                g.draw(bp, None)
                font["hmtx"][name] = (width, round(bp.bounds[0]))
        done.append(name)
    return done


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
                for extra in cfg.get("extra_copyright", []) or []:
                    new += f" {extra}"
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


# ---------------------------------------------------------------------------
# Khoảng cách ký tự (độ rộng ô monospace)
# ---------------------------------------------------------------------------

_BOX_RANGES = ((0x2500, 0x259F), (0xE0A0, 0xE0FF), (0x1FB00, 0x1FBFF))


def _scale_type(font: ttLib.TTFont, name: str, rev: dict) -> bool:
    """Glyph trải qua nhiều ô / nối mép ô (ligature, box drawing): co theo tỷ lệ."""
    if any(t in name for t in (".liga", ".seq", ".spacer")):
        return True
    cp = rev.get(name)
    return cp is not None and any(a <= cp <= b for a, b in _BOX_RANGES)


def set_cell_width(font: ttLib.TTFont, new: int) -> int:
    hmtx = font["hmtx"]
    old = max(w for w, _ in hmtx.metrics.values())
    if new == old:
        return 0
    k = new / old
    shift = (old - new) / 2
    rev: dict = {}
    for cp, n in font.getBestCmap().items():
        rev.setdefault(n, cp)
    names = [n for n in font.getGlyphOrder() if hmtx[n][0] == old]
    scaled = {n for n in names if _scale_type(font, n, rev)}

    def fx(n: str, x: float) -> float:
        return x * k if n in scaled else x - shift

    if "glyf" in font:
        glyf = font["glyf"]
        gvar = font["gvar"].variations if "gvar" in font else {}
        for n in names:
            g = glyf[n]
            if g.isComposite():
                if n in scaled:
                    for c in g.components:
                        c.x = round(c.x * k)
                    for v in gvar.get(n, []):
                        v.coordinates = [
                            (round(p[0] * k), p[1]) if p is not None and i < len(g.components) else p
                            for i, p in enumerate(v.coordinates)
                        ]
            elif g.numberOfContours > 0:
                for i, (x, y) in enumerate(g.coordinates):
                    g.coordinates[i] = (round(fx(n, x)), y)
                if n in scaled:
                    npts = len(g.coordinates)
                    for v in gvar.get(n, []):
                        v.coordinates = [
                            (round(p[0] * k), p[1]) if p is not None and i < npts else p
                            for i, p in enumerate(v.coordinates)
                        ]
        for n in font.getGlyphOrder():
            g = glyf[n]
            w = hmtx[n][0]
            if g.numberOfContours != 0:
                g.recalcBounds(glyf)
            hmtx[n] = (new if w == old else w, g.xMin if g.numberOfContours != 0 else 0)
    else:
        cff = font["CFF "].cff
        top = cff.topDictIndex[0]
        gs = font.getGlyphSet()
        drawn = {}
        for n in names:
            rec = RecordingPen()
            gs[n].draw(rec)
            drawn[n] = rec
        for n, rec in drawn.items():
            m = (k, 0, 0, 1, 0, 0) if n in scaled else (1, 0, 0, 1, -shift, 0)
            pen = T2CharStringPen(new, None)
            rec.replay(TransformPen(pen, m))
            top.CharStrings[n] = pen.getCharString(private=top.Private, globalSubrs=cff.GlobalSubrs)
            bp = BoundsPen(None)
            rec.replay(TransformPen(bp, m))
            hmtx[n] = (new, round(bp.bounds[0]) if bp.bounds else 0)

    # GPOS: điểm neo dấu của glyph gốc dịch theo glyph
    if "GPOS" in font:
        for lk in font["GPOS"].table.LookupList.Lookup:
            for st in lk.SubTable:
                if lk.LookupType == 9:
                    st = st.ExtSubTable
                if getattr(st, "LookupType", lk.LookupType) != 4 or not hasattr(st, "BaseArray"):
                    continue
                for gname, rec in zip(st.BaseCoverage.glyphs, st.BaseArray.BaseRecord):
                    if hmtx[gname][0] != new:
                        continue
                    for a in rec.BaseAnchor:
                        if a is not None:
                            a.XCoordinate = round(fx(gname, a.XCoordinate))
    # glyph rỗng có độ rộng lệch (vd: U+2028/2029 của Lilex) → đưa về đúng ô
    order = font.getGlyphOrder()
    for n, (w, _) in list(hmtx.metrics.items()):
        empty_glyf = "glyf" in font and font["glyf"][n].numberOfContours == 0
        if w in (0, new) and not (empty_glyf and "gvar" in font and n in font["gvar"].variations):
            continue
        if "glyf" in font:
            if font["glyf"][n].numberOfContours != 0:
                continue
        else:
            bp = BoundsPen(None)
            font.getGlyphSet()[n].draw(bp)
            if bp.bounds is not None:
                continue
            top = font["CFF "].cff.topDictIndex[0]
            top.CharStrings[n] = T2CharStringPen(new, None).getCharString(
                private=top.Private, globalSubrs=font["CFF "].cff.GlobalSubrs
            )
        if w != 0:
            hmtx[n] = (new, 0)
        if "gvar" in font:
            font["gvar"].variations.pop(n, None)
        if "HVAR" in font:
            hv = font["HVAR"].table
            if hv.AdvWidthMap is None:
                outer, inner = 0, order.index(n)
            else:
                idx = hv.AdvWidthMap.mapping[n]
                outer, inner = idx >> 16, idx & 0xFFFF
            vd = hv.VarStore.VarData[outer]
            if inner < len(vd.Item):
                vd.Item[inner] = [0] * len(vd.Item[inner])
    font["OS/2"].xAvgCharWidth = new
    return len(names)


def transform(font: ttLib.TTFont, item: Path, cfg: dict) -> tuple[set, list]:
    """Áp mọi chỉnh sửa glyph lên font. Trả về (tên glyph đã đổi, ghi chú)."""
    italic = is_italic(font)
    notes: list = []
    changed: set = set()
    feats = cfg.get("default_features", {})
    if isinstance(feats, list):
        feats = {"upright": feats, "italic": feats}
    for t in feats.get("italic" if italic else "upright", []) or []:
        notes.append(f"{t}:{make_default(font, t)}")
    unfoot = cfg.get("remove_foot", {}) or {}
    if italic and cfg.get("italic_from_upright"):
        partner = upright_partner(item)
        if partner is None:
            sys.exit(f"Không tìm thấy bản đứng tương ứng cho {item.name}")
        upright = ttLib.TTFont(str(partner))
        for g in unfoot.get("upright", []) or []:
            if g in cfg["italic_from_upright"]:
                remove_foot(upright, g)
        for g in cfg["italic_from_upright"]:
            slant_from_upright(font, upright, g)
            changed.add(g)
            notes.append(f"{g}←{partner.name}")
    root = Path(__file__).resolve().parent.parent
    for spec in cfg.get("import_glyphs", []) or []:
        if ("italic" if italic else "upright") in spec.get("styles", ["upright", "italic"]):
            names = import_glyphs(font, spec, root)
            changed.update(names)
            notes.append(f"{spec['name']}:{len(names)}")
    # bỏ chân serif sau cùng (áp cả cho glyph vừa ghép từ font khác)
    if not italic:
        for g in unfoot.get("upright", []) or []:
            remove_foot(font, g)
            changed.add(g)
            notes.append(f"{g}:no-foot")
    return changed, notes


def finalize(font: ttLib.TTFont, cfg: dict, notes: list) -> None:
    if cfg.get("cell_width"):
        notes.append(f"width→{cfg['cell_width']}:{set_cell_width(font, int(cfg['cell_width']))}")


def _dependents(glyf, changed: set) -> set:
    """Glyph ghép (composite) có dùng — trực tiếp hoặc gián tiếp — glyph đã đổi."""
    memo: dict = {}

    def uses(name: str) -> bool:
        if name in memo:
            return memo[name]
        memo[name] = False
        g = glyf[name]
        r = g.isComposite() and any(c.glyphName in changed or uses(c.glyphName) for c in g.components)
        memo[name] = r
        return r

    return {n for n in glyf.keys() if n not in changed and uses(n)}


def sync_cff_from_ttf(otf: ttLib.TTFont, ttf: ttLib.TTFont, changed: set) -> int:
    """CFF không có glyph ghép: vẽ lại các glyph có dấu từ bản TTF đã chỉnh."""
    top = otf["CFF "].cff.topDictIndex[0]
    gs = ttf.getGlyphSet()
    deps = _dependents(ttf["glyf"], changed)
    for name in deps:
        if name not in top.CharStrings:
            continue
        width = otf["hmtx"][name][0]
        pen = T2CharStringPen(width, gs)
        gs[name].draw(pen)
        top.CharStrings[name] = pen.getCharString(private=top.Private, globalSubrs=otf["CFF "].cff.GlobalSubrs)
        bp = BoundsPen(gs)
        gs[name].draw(bp)
        otf["hmtx"][name] = (width, round(bp.bounds[0]) if bp.bounds else 0)
    return len(deps)


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
        changed, notes = transform(font, item, cfg)
        if "CFF " in font and changed:
            sibling = item.parent.parent / "ttf" / (item.stem + ".ttf")
            if not sibling.exists():
                sys.exit(f"Cần {sibling} để cập nhật glyph có dấu cho {item.name}")
            ttf = ttLib.TTFont(str(sibling))
            transform(ttf, sibling, cfg)
            notes.append(f"cff-accents:{sync_cff_from_ttf(font, ttf, changed)}")
        finalize(font, cfg, notes)
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

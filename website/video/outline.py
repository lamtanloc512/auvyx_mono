"""Vẽ 'giải phẫu' glyph: đường viền Bézier, điểm neo, tay nắm — hiện dần theo tỉ lệ."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from fontTools.pens.freetypePen import FreeTypePen
from fontTools.pens.recordingPen import RecordingPointPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

from engine import H, W


@lru_cache(maxsize=4)
def _font(path):
    return TTFont(path)


def glyph_name(path: str, ch: str) -> str:
    return _font(path).getBestCmap()[ord(ch)]


def contours(path: str, name: str, wght: float):
    gs = _font(path).getGlyphSet(location={"wght": wght})
    rec = RecordingPointPen()
    gs[name].drawPoints(rec)
    out, cur = [], None
    for op, args, kw in rec.value:
        if op == "beginPath":
            cur = []
        elif op == "addPoint":
            cur.append((args[0], args[1]))
        elif op == "endPath":
            out.append(cur)
    return out, gs[name].width


def _flatten(contour, steps=18):
    """Chuỗi điểm của một contour TrueType (bậc 2), khép kín."""
    pts = contour
    n = len(pts)
    start = next((i for i, (_, s) in enumerate(pts) if s is not None), 0)
    seq = pts[start:] + pts[:start] + [pts[start]]
    poly = [seq[0][0]]
    i = 1
    while i < len(seq):
        p, s = seq[i]
        if s is not None:
            poly.append(p)
            i += 1
            continue
        offs = []
        while i < len(seq) and seq[i][1] is None:
            offs.append(seq[i][0])
            i += 1
        end = seq[i][0] if i < len(seq) else seq[0][0]
        ctrl = [poly[-1]]
        for a, b in zip(offs, offs[1:]):
            ctrl += [a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)]
        ctrl += [offs[-1], end]
        for k in range(0, len(ctrl) - 2, 2):
            p0, p1, p2 = ctrl[k], ctrl[k + 1], ctrl[k + 2]
            for t in np.linspace(0, 1, steps)[1:]:
                poly.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]))
        i += 1
        poly.append(end) if poly[-1] != end else None
    return np.array(poly, dtype=np.float64)


def glyph_fill(path, name, wght, scale, ox, oy) -> Image.Image:
    """Mask (L) toàn khung của glyph: toạ độ px = (ox + x*scale, oy - y*scale)."""
    gs = _font(path).getGlyphSet(location={"wght": wght})
    pen = FreeTypePen(gs)
    gs[name].draw(pen)
    img = pen.image(width=W, height=H, transform=(scale, 0, 0, scale, ox, H - oy), contain=False)
    return img.split()[-1]


def draw_anatomy(path, name, wght, scale, ox, oy, frac: float, alpha: float = 1.0, ss: int = 2) -> Image.Image:
    """Ảnh RGBA toàn khung: đường viền vẽ tới `frac` (0..1) tổng chiều dài, cùng điểm neo & tay nắm đã tới."""
    cs, _ = contours(path, name, wght)
    polys = [_flatten(c) for c in cs]
    lens = [np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))] for p in polys]
    total = sum(l[-1] for l in lens)
    budget = frac * total
    img = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def px(p):
        return ((ox + p[0] * scale) * ss, (oy - p[1] * scale) * ss)

    a255 = int(255 * alpha)
    for c, p, L in zip(cs, polys, lens):
        if budget <= 0:
            break
        upto = min(budget, L[-1])
        budget -= L[-1]
        k = np.searchsorted(L, upto)
        seg = [px(q) for q in p[: max(2, k + 1)]]
        d.line(seg, fill=(255, 255, 255, a255), width=3 * ss, joint="curve")
        # điểm neo & tay nắm tới đoạn đã vẽ
        n = len(c)
        reached = upto / max(L[-1], 1e-9)
        for i, (q, s) in enumerate(c):
            if i / n > reached + 1e-6:
                break
            x, y = px(q)
            if s is None:
                for j in (i - 1, (i + 1) % n):
                    if c[j][1] is not None:
                        x2, y2 = px(c[j][0])
                        d.line([(x, y), (x2, y2)], fill=(140, 140, 150, int(a255 * 0.8)), width=1 * ss)
                r = 5 * ss
                d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 138, 76, a255), width=2 * ss)
            else:
                r = 6 * ss
                d.rectangle([x - r, y - r, x + r, y + r], fill=(245, 245, 247, a255))
    return img.resize((W, H), Image.LANCZOS)


def point_at(path, name, wght, scale, ox, oy, frac: float):
    """Toạ độ px của đầu bút khi đã vẽ `frac` tổng chiều dài (dùng cho camera bám theo)."""
    cs, _ = contours(path, name, wght)
    polys = [_flatten(c) for c in cs]
    lens = [np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))] for p in polys]
    budget = clamp01(frac) * sum(l[-1] for l in lens)
    for p, L in zip(polys, lens):
        if budget <= L[-1]:
            k = int(np.clip(np.searchsorted(L, budget), 1, len(L) - 1))
            u = (budget - L[k - 1]) / max(L[k] - L[k - 1], 1e-9)
            q = p[k - 1] + (p[k] - p[k - 1]) * u
            return ox + q[0] * scale, oy - q[1] * scale
        budget -= L[-1]
    q = polys[-1][-1]
    return ox + q[0] * scale, oy - q[1] * scale


def clamp01(v):
    return max(0.0, min(1.0, v))

"""Công cụ dựng khung hình: shape bằng HarfBuzz (có trục wght), vẽ outline bằng FreeType."""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import uharfbuzz as hb
from fontTools.pens.freetypePen import FreeTypePen
from fontTools.pens.transformPen import TransformPen
from PIL import Image, ImageFilter

W, H, FPS = 1920, 1080, 30


class Face:
    def __init__(self, path: str):
        self.path = path
        self.blob = hb.Blob.from_file_path(path)
        self.face = hb.Face(self.blob)
        self.upem = self.face.upem

    def font(self, wght: float) -> hb.Font:
        f = hb.Font(self.face)
        f.set_variations({"wght": float(wght)})
        return f


def _shape(face: Face, text: str, wght: float, feats: dict | None):
    font = face.font(wght)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, feats or {})
    return font, buf


@lru_cache(maxsize=4096)
def text_mask(face: Face, text: str, size: float, wght: float = 400, feats: tuple = (), tracking: float = 0):
    """Trả về (mask L, baseline_px_từ_trên, advance_px)."""
    font, buf = _shape(face, text, wght, dict(feats))
    s = size / face.upem
    pen = FreeTypePen(None)
    x = 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        font.draw_glyph_with_pen(info.codepoint, TransformPen(pen, (1, 0, 0, 1, x + pos.x_offset, pos.y_offset)))
        x += pos.x_advance + tracking
    asc, desc = 1150, 360
    pad = int(size * 0.3)
    w = max(1, int(math.ceil(x * s)) + pad * 2)
    h = int(math.ceil((asc + desc) * s))
    if not buf.glyph_infos:
        return Image.new("L", (w, h), 0), asc * s, x * s, pad
    img = pen.image(width=w, height=h, transform=(s, 0, 0, s, pad, desc * s), contain=False)
    return img.split()[-1], asc * s, x * s, pad


class Canvas:
    def __init__(self, bg=(0, 0, 0)):
        self.a = np.empty((H, W, 3), np.float32)
        self.a[:] = np.array(bg, np.float32) / 255

    def blit(self, mask: Image.Image, x: int, y: int, color, alpha: float = 1.0, grad=None):
        if alpha <= 0.002:
            return
        m = np.asarray(mask, np.float32) / 255 * alpha
        h, w = m.shape
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(W, x + w), min(H, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        m = m[y0 - y : y1 - y, x0 - x : x1 - x][..., None]
        if grad is not None:
            c0, c1 = (np.array(grad[0], np.float32) / 255, np.array(grad[1], np.float32) / 255)
            t = np.linspace(0, 1, w, dtype=np.float32)[x0 - x : x1 - x][None, :, None]
            col = c0 + (c1 - c0) * t
        else:
            col = np.array(color, np.float32) / 255
        region = self.a[y0:y1, x0:x1]
        region += (col - region) * m

    def rect(self, x, y, w, h, color, alpha=1.0, radius=0):
        mask = Image.new("L", (int(w), int(h)), 0)
        from PIL import ImageDraw
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, int(w) - 1, int(h) - 1], radius=radius, fill=255)
        self.blit(mask, int(x), int(y), color, alpha)

    def rgb(self) -> bytes:
        return (np.clip(self.a, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes()


def draw_text(cv: Canvas, face: Face, text: str, size: float, cx: float, baseline: float, *, wght=400, color=(245, 245, 247),
              alpha=1.0, blur=0.0, grad=None, align="center", feats=(), tracking=0):
    if not text.strip():
        return 0
    mask, asc, adv, pad = text_mask(face, text, round(size, 1), round(wght, 1), feats, tracking)
    if blur > 0.3:
        mask = mask.filter(ImageFilter.GaussianBlur(blur))
    if align == "center":
        x = cx - adv / 2 - pad
    elif align == "left":
        x = cx - pad
    else:
        x = cx - adv - pad
    cv.blit(mask, int(round(x)), int(round(baseline - asc)), color, alpha, grad)
    return adv


def advance(face: Face, text: str, size: float, wght=400, feats=()):
    return text_mask(face, text, round(size, 1), round(wght, 1), feats, 0)[2]


# --- easing ---
def clamp(v, a=0.0, b=1.0):
    return max(a, min(b, v))


def prog(t, start, dur):
    return clamp((t - start) / dur)


def ease_out(p):  # expo-ish
    return 1 - (1 - p) ** 4


def ease_in_out(p):
    return 0.5 - 0.5 * math.cos(math.pi * p)


def fade(t, t_in, t_out, d_in=0.6, d_out=0.5):
    """Độ mờ: hiện dần từ t_in, tắt dần tới t_out."""
    return ease_out(prog(t, t_in, d_in)) * (1 - ease_in_out(prog(t, t_out - d_out, d_out)))

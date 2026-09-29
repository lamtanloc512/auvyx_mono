"""Hậu kỳ cho từng khung hình: camera (zoom), bloom (chữ sáng toả nhẹ), grain phim, vignette."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

from engine import H, W

_yy, _xx = np.mgrid[0:H, 0:W].astype(np.float32)
_r = np.sqrt(((_xx - W / 2) / (W / 2)) ** 2 + ((_yy - H / 2) / (H / 2)) ** 2)
VIGNETTE = (1 - 0.22 * np.clip(_r - 0.35, 0, 1) ** 1.6)[..., None].astype(np.float32)
del _yy, _xx, _r


def camera(img: Image.Image, zoom: float, cx: float, cy: float) -> Image.Image:
    """Phóng to quanh điểm (cx, cy) của khung hình."""
    if abs(zoom - 1) < 1e-3 and abs(cx - W / 2) < 0.5 and abs(cy - H / 2) < 0.5:
        return img
    a = 1 / zoom
    return img.transform((W, H), Image.AFFINE, (a, 0, cx - W / 2 * a, 0, a, cy - H / 2 * a), resample=Image.BICUBIC)


def post(arr: np.ndarray, frame_idx: int, cam=None, bloom=0.28, grain=0.006) -> bytes:
    img = Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8))
    if cam is not None:
        img = camera(img, *cam)
    a = np.asarray(img, np.float32) / 255
    if bloom > 0:
        small = img.resize((W // 4, H // 4), Image.BILINEAR)
        hi = np.clip(np.asarray(small, np.float32) / 255 - 0.5, 0, 1) * 2
        glow = Image.fromarray((hi * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(7)).resize((W, H), Image.BILINEAR)
        a = a + (np.asarray(glow, np.float32) / 255) * bloom * (1 - a)
    a *= VIGNETTE
    if grain > 0:
        rng = np.random.default_rng(frame_idx // 2)          # hạt đổi mỗi 2 khung: vẫn "sống" nhưng nén tốt hơn
        a += rng.standard_normal((H // 2, W // 2, 1), dtype=np.float32).repeat(2, 0).repeat(2, 1) * grain
    return (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes()

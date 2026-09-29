#!/usr/bin/env python3
"""Video giới thiệu Auvyx Mono.

Dùng:
    python3 video/intro.py --fonts ../fonts/AuvyxMono/variable --out video/auvyx-mono-intro.mp4
    python3 video/intro.py ... --preview 3 20.5 48.6    # chỉ xuất vài khung hình PNG
    # máy chậm / giới hạn thời gian: render từng phần rồi ghép
    python3 video/intro.py ... --work build/ --part 0/3   (1/3, 2/3)  rồi  --work build/ --assemble

Nhạc được dựng trước (music.py) rồi tìm vị trí từng nốt (onset). Mọi thay đổi trên hình
(điểm neo hiện ra, độ đậm tăng, từng từ, mỗi lần cắt cảnh, chữ cái màn kết) rơi đúng một nốt có thật.

Kịch bản:
  1  Giải phẫu      chữ "a" được dựng từ đường cong Bézier, từng đoạn theo từng nốt piano
  2  Tên            "Auvyx Mono" gõ từng chữ, đậm dần
  3  Tagline        "Designed for code. Built for people." từng từ
  4  Độ đậm         "Aa" nhảy nấc Thin → Bold, rồi camera lao vào nét chữ → trắng xoá đúng lúc beat vào
  5  Montage 1      cắt theo nốt, nhanh dần; nhiều bố cục (chữ khổng lồ, cắt cận, lưới, bậc độ đậm, ligature)
  6  Code           từng dòng theo từng nốt, camera đẩy chậm
  7  Tiếng Việt     tiêu đề + từng từ
  8  Montage 2      dồn dập
  9  Bão glyph      cả màn hình đầy ký tự, mỗi nốt đổi một lần, dày dần
  10 Fermata        nốt dừng ngân trong tiếng vang: bão glyph nổ tung như quay chậm, tan vào bóng tối
  11 Hạ màn         piano chậm dần; "Auvyx Mono" hiện từng chữ theo từng nốt
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import fx  # noqa: E402
import outline  # noqa: E402
from engine import FPS, H, W, Canvas, Face, advance, clamp, draw_text, ease_in_out, ease_out, fade, prog, text_mask  # noqa: E402
from music import BAR, BEAT, GRID0  # noqa: E402

WHITE = (245, 245, 247)
GRAY = (134, 134, 139)
DIM = (58, 58, 62)
ORANGE = (255, 138, 76)
GRAD = ((255, 138, 76), (214, 92, 255))
MUSIC = Path(__file__).parent / "music" / "ethereal88-in-the-remains-of-the-day.mp3"
MUSIC_CREDIT = "Music: In the Remains of the Day by Ethereal 88 · CC BY 4.0"

UP: Face
IT: Face
UP_PATH = IT_PATH = ""
GLYPHS: list[str] = []
DURATION = 60.0


def bar(b: float) -> float:
    """Thời điểm (giây, trên video) của ô nhịp thứ b (trước chỗ nối nhạc)."""
    return GRID0 + b * BAR


def init(font_dir: str, glyph_json: str | None, info: dict | None = None):
    global UP, IT, UP_PATH, IT_PATH, GLYPHS
    UP_PATH = str(Path(font_dir) / "AuvyxMono[wght].ttf")
    IT_PATH = str(Path(font_dir) / "AuvyxMono-Italic[wght].ttf")
    UP, IT = Face(UP_PATH), Face(IT_PATH)
    if glyph_json and Path(glyph_json).exists():
        data = json.loads(Path(glyph_json).read_text())
        GLYPHS = [chr(cp) for g in data["groups"] for cp, _ in g["chars"]
                  if g["name"] not in ("Box & blocks", "Powerline", "Punctuation")]
    else:
        GLYPHS = [chr(c) for c in range(0x21, 0x7F)]
    if info is not None:
        setup(info)


# ---------------------------------------------------------------- nốt nhạc
ONS_T = np.zeros(0)
ONS_S = np.zeros(0)


def snap(t: float, win: float = 0.12, min_s: float = 0.6) -> float:
    m = (np.abs(ONS_T - t) <= win) & (ONS_S >= min_s)
    if not m.any():
        return t
    c, s = ONS_T[m], ONS_S[m]
    return float(c[np.argmax(s * np.exp(-((c - t) / win) ** 2))])


def pick_onsets(t0: float, t1: float, gap: float, min_s: float = 1.0) -> list[float]:
    out, last = [], -1e9
    for t, s in zip(ONS_T, ONS_S):
        if t0 - 0.03 <= t < t1 and s >= min_s and t - last >= gap:
            out.append(float(t))
            last = t
    return out


def plan_cuts(t0: float, t1: float, ramp) -> list[tuple[float, float]]:
    """Cắt đúng nốt. ramp = [(số ô nhịp, số phách mỗi cảnh)] — nhịp cắt mong muốn theo thời gian."""
    phases, p = [], t0
    for bars_, per in ramp:
        phases.append((p, p + bars_ * BAR, per * BEAT))
        p += bars_ * BAR

    def interval(t):
        for a, b, i in phases:
            if a <= t < b:
                return i
        return phases[-1][2]

    cuts = [snap(t0)]
    while True:
        t = cuts[-1]
        I = interval(t)
        target = t + I
        if target > t1 - 0.6 * I:
            break
        lo, hi = t + 0.7 * I, min(t + 1.35 * I, t1 - 0.05)
        m = (ONS_T >= lo) & (ONS_T <= hi) & (ONS_S >= (0.9 if I > 0.3 else 0.7))
        if m.any():
            c, s = ONS_T[m], ONS_S[m]
            nxt = float(c[np.argmax(s * np.exp(-((c - target) / (0.35 * I)) ** 2))])
        else:
            m = (ONS_T > hi) & (ONS_T < min(t + 3 * I, t1 - 0.05)) & (ONS_S >= 0.9)
            if not m.any():
                break
            nxt = float(ONS_T[m][0])
        cuts.append(nxt)
    ends = cuts[1:] + [t1]
    return [(a, b - a) for a, b in zip(cuts, ends)]


def stepper(t: float, notes: list[float], v0: float, v1: float, ease=0.16) -> float:
    """Giá trị nhảy từng nấc trên mỗi nốt (v0 → v1)."""
    if not notes or t < notes[0]:
        return v0
    n = len(notes)
    for k in range(n - 1, -1, -1):
        if t >= notes[k]:
            a = v0 + (v1 - v0) * k / n
            b = v0 + (v1 - v0) * (k + 1) / n
            return a + (b - a) * ease_out(clamp((t - notes[k]) / ease))
    return v0


def reveal_words(t: float, words: list[str], times: list[float]) -> str:
    full = " ".join(words)
    shown = " ".join(w for w, tt in zip(words, times) if t >= tt)
    return shown + " " * (len(full) - len(shown)) if shown else ""


def fit(xs, n, start, gap):
    xs = list(xs)
    while len(xs) < n:
        xs.append((xs[-1] if xs else start) + gap)
    return xs[:n]


# ---------------------------------------------------------------- cảnh
EV: dict = {}
CAM: dict = {}          # camera của khung hình đang vẽ: (zoom, cx, cy)


def s_anatomy(cv, t, D):
    """1 — chữ "a" dựng từ đường cong: mỗi nốt piano vẽ thêm một đoạn, camera lùi dần."""
    name = outline.glyph_name(UP_PATH, "a")
    scale, oy = 1.25, 880
    ox = W / 2 - 590 * scale / 2
    frac = stepper(t, EV["ana_steps"], 0.0, 1.0, ease=0.35)
    t_fill = EV["ana_fill"]
    fill = ease_out(prog(t, t_fill, 0.9))
    out = 1 - ease_in_out(prog(t, D - 0.5, 0.45))
    if fill > 0:
        m = outline.glyph_fill(UP_PATH, name, 400, scale, ox, oy)
        cv.blit(m, 0, 0, WHITE, fill * out)
    if fill < 1:
        lines = outline.draw_anatomy(UP_PATH, name, 400, scale, ox, oy, frac, alpha=(1 - fill) * out)
        a = np.asarray(lines, np.float32) / 255
        cv.a += (a[..., :3] - cv.a) * a[..., 3:4]
    draw_text(cv, UP, "Introducing", 40, W / 2, 1000, color=GRAY, alpha=ease_out(prog(t, EV["ana_intro"], 0.8)) * out)
    # camera cận cảnh bám theo đầu bút, rồi lùi dần ra toàn cảnh khi chữ sắp hoàn thành
    tip = outline.point_at(UP_PATH, name, 400, scale, ox, oy, stepper(t - 0.12, EV["ana_steps"], 0.0, 1.0, ease=0.5))
    back = ease_in_out(prog(t, EV["ana_steps"][-1] - 0.3 if EV["ana_steps"] else 3, 1.4))
    z = 2.2 - 1.2 * back
    CAM["v"] = (z, tip[0] + (W / 2 - tip[0]) * back, tip[1] + (H / 2 - tip[1]) * back)


def s_title(cv, t, D):
    """2 — "Auvyx Mono" gõ từng chữ theo nốt, đậm dần."""
    title = "Auvyx Mono"
    size, base = 210, 610
    w = stepper(t, EV["title_w"], 100, 700, ease=0.2)
    x_left = W / 2 - advance(UP, title, size, 400) / 2
    cell = advance(UP, "AA", size, 400) - advance(UP, "A", size, 400)
    letters = EV["title_letters"]
    k = 0
    out = 1 - ease_in_out(prog(t, D - 0.35, 0.3))
    last_x = x_left
    for i, ch in enumerate(title):
        if ch == " ":
            continue
        if t < letters[k]:
            break
        p = ease_out(prog(t, letters[k], 0.25))
        draw_text(cv, UP, ch, size, x_left + i * cell, base + 16 * (1 - p), wght=w, alpha=p * out, align="left")
        last_x = x_left + (i + 1) * cell
        k += 1
    if k < 9 or int(t * 2.4) % 2 == 0:                                   # con trỏ
        cv.rect(last_x + 10, base - size * 0.72, 12, size * 0.82, ORANGE, out, 2)
    CAM["v"] = (1.0 + 0.03 * ease_out(prog(t, 0, D)), W / 2, H / 2)


def s_tagline(cv, t, D):
    """3 — mỗi từ vào một nốt."""
    a = 1 - ease_in_out(prog(t, D - 0.4, 0.35))
    l1 = reveal_words(t, ["Designed", "for", "code."], EV["tag1"])
    l2 = reveal_words(t, ["Built", "for", "people."], EV["tag2"])
    if l1:
        draw_text(cv, UP, l1, 116, W / 2, 500, wght=700, alpha=a)
    if l2:
        draw_text(cv, UP, l2, 116, W / 2, 650, wght=700, grad=GRAD, alpha=a)
    CAM["v"] = (1.0 + 0.04 * ease_out(prog(t, 0, D)), W / 2, H / 2)


WEIGHT_NAMES = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold"}


def s_weights(cv, t, D):
    """4 — "Aa" nhảy nấc theo nốt; ô nhịp cuối camera lao vào nét chữ → trắng xoá đúng lúc beat vào."""
    w = stepper(t, EV["w_steps"], 100, 700, ease=0.12)
    size = 560
    base = H / 2 + size * 0.36
    draw_text(cv, UP, "Aa", size, W / 2, base, wght=w)
    name = WEIGHT_NAMES[min(WEIGHT_NAMES, key=lambda k: abs(k - w))]
    rush = prog(t, D - BAR, BAR)                                        # ô nhịp cuối
    lab = 1 - ease_out(clamp(rush * 3))
    draw_text(cv, UP, "Seven weights. One variable font.", 40, W / 2, 170, color=GRAY, alpha=lab)
    draw_text(cv, UP, f"{int(round(w))}", 44, W / 2 - 30, 980, color=WHITE, alpha=lab, align="right")
    draw_text(cv, UP, name, 44, W / 2 + 30, 980, color=ORANGE, alpha=lab, align="left")
    z = 1 + 60 * rush ** 3.2
    cx, cy = EV["rush_point"]
    CAM["v"] = (z, W / 2 + (cx - W / 2) * min(1, rush * 4), H / 2 + (cy - H / 2) * min(1, rush * 4))


# ---- montage
MONTAGE_1 = [(2, 2.0), (2, 1.0), (2, 0.5)]
MONTAGE_2 = [(2, 1.0), (2, 0.5)]

# (kiểu, nội dung, cỡ chữ, wght, nghiêng?, màu) — màu: "w" trắng, "g" gradient, "i" đảo nền trắng
CARDS = [
    ("t", "a", 560, 700, False, "w"), ("t", "g", 560, 300, True, "g"), ("t", "=>", 420, 500, False, "w"),
    ("t", "const", 260, 700, False, "i"),
    ("t", "&", 560, 200, False, "w"), ("t", "ơ", 560, 600, False, "g"), ("t", "!==", 400, 500, False, "w"),
    ("t", "async", 260, 400, True, "w"), ("t", "@", 560, 700, False, "i"), ("t", "Ж", 560, 300, False, "w"),
    ("t", "fn()", 300, 600, False, "g"), ("t", "ß", 560, 100, False, "w"),
    ("t", "R", 600, 700, False, "w"), ("t", "|>", 420, 500, False, "g"), ("t", "kljr", 300, 500, True, "w"),
    ("t", "0x1F", 300, 700, False, "i"), ("t", "Ω", 560, 200, False, "w"), ("t", "ữ", 560, 700, False, "g"),
    ("t", "::", 420, 400, False, "w"), ("t", "{ }", 400, 300, False, "w"), ("t", "λ", 560, 600, True, "i"),
    ("t", "#", 560, 700, False, "w"), ("t", "đ", 560, 400, False, "g"), ("t", "->", 420, 600, False, "w"),
    ("t", "W", 600, 100, False, "w"), ("t", "&&", 420, 700, False, "i"), ("t", "ặ", 560, 300, False, "w"),
    ("t", "∞", 520, 500, False, "g"), ("t", "Aa", 480, 700, True, "w"), ("t", "</>", 360, 400, False, "w"),
    ("t", "ç", 560, 700, False, "i"), ("t", "%", 560, 200, False, "w"),
    ("t", "return", 240, 600, False, "w"), ("t", "Thin", 300, 100, False, "g"), ("t", "Bold", 300, 700, False, "w"),
    ("t", "Italic", 300, 400, True, "i"),
    ("t", "1,073 characters.", 120, 700, False, "w"), ("t", "Latin · Greek · Cyrillic", 70, 400, False, "g"),
    ("t", "=== != |> ::", 150, 500, False, "w"), ("t", "Ligatures.", 180, 700, False, "g"),
]


LAYOUTS = ["big", "crop", "big", "ladder", "big", "grid", "big", "lig", "crop", "big", "ticker", "big"]
LIGS = ["=>", "!==", "|>", "->", "::", "&&", "<=", "=/=", "...", "</>"]
TICKER = "const  let  fn  =>  async  await  return  match  impl  !=  ===  |>  ::  null  "


def _card(i):
    kind, txt, size, wght, italic, col = CARDS[i % len(CARDS)]
    rnd = i // len(CARDS)
    if rnd:
        wght = min(700, 100 + (wght - 100 + 300 * rnd) % 700)
        if len(txt) <= 2:
            italic = not italic
        if col == "i":
            col = "w"
    return kind, txt, size, wght, italic, col


def draw_card(cv, i, lt, dur):
    kind, txt, size, wght, italic, col = _card(i)
    layout = LAYOUTS[i % len(LAYOUTS)] if dur >= 0.3 else ("big" if i % 3 else "crop")
    if i == 0:
        col, layout = "i", "big"                           # nối tiếp khung trắng xoá của cảnh độ đậm
    if dur < 0.2 and col == "i":
        col = "w"
    if col == "i":
        cv.a[:] = np.array(WHITE, np.float32) / 255
    fg = (12, 12, 14) if col == "i" else WHITE
    kw = dict(grad=GRAD) if col == "g" else dict(color=fg)
    face = IT if italic else UP
    g = 1 + 0.04 * lt
    if layout == "big":
        draw_text(cv, face, txt, size * g, W / 2, H / 2 + size * 0.36, wght=wght, feats=(("calt", True),), **kw)
    elif layout == "crop":
        ch = txt.strip()[0]
        big = 1500 * (1 + 0.06 * lt)
        draw_text(cv, face, ch, big, W / 2 + 180, H / 2 + big * 0.36 - 40, wght=wght, **kw)
    elif layout == "ladder":
        word = txt if len(txt) > 2 else "Auvyx"
        off = (222, 222, 226) if col == "i" else (44, 44, 48)
        for k, ww in enumerate(range(100, 800, 100)):
            y = 150 + k * 126
            on = k <= int(lt * 9)
            draw_text(cv, face, word, 112, W / 2, y + 44, wght=ww, color=fg if on else off)
    elif layout == "grid":
        cols, rows = 6, 3
        pool = [c for c in GLYPHS if c.strip()]
        for r in range(rows):
            for c in range(cols):
                n = (i * 7 + r * cols + c) * 13 % len(pool)
                hot = (r * cols + c) == (i * 5) % (cols * rows)
                x = W / 2 + (c - (cols - 1) / 2) * 290
                y = H / 2 + (r - (rows - 1) / 2) * 300 + 80
                draw_text(cv, face, pool[n], 190, x, y, wght=wght,
                          **(dict(grad=GRAD) if hot else dict(color=fg if col == "i" else (200, 200, 206))))
    elif layout == "lig":
        lg = LIGS[i % len(LIGS)]
        draw_text(cv, UP, lg, 420 * g, W / 2, H / 2 + 120, wght=500, feats=(("calt", True),), **kw)
        draw_text(cv, UP, lg, 60, W / 2, H - 150, color=GRAY, feats=(("calt", False),))
    elif layout == "ticker":
        cellw = advance(UP, "AA", 150, wght) - advance(UP, "A", 150, wght)
        off = -lt * 900 - (i % 7) * cellw * 5
        k0 = int(-off // cellw)
        text = (TICKER * 4)[k0: k0 + int(W / cellw) + 3]                  # chỉ vẽ phần đang hiện trên màn hình
        draw_text(cv, UP, text, 150, off + k0 * cellw, H / 2 + 54, wght=wght, align="left", **kw)
    if dur >= 2 * BEAT - 0.05 and layout in ("big", "crop"):
        tag = f"{'Italic' if italic else 'Upright'} · wght {wght}"
        draw_text(cv, UP, tag, 28, W / 2, H - 90, color=(90, 90, 96) if col != "i" else (120, 120, 126))


def montage(key, offset_key):
    def scene(cv, t, D):
        t_abs = EV[key + "_start"] + t
        for i, (c0, dur) in enumerate(EV[key]):
            if c0 <= t_abs < c0 + dur:
                draw_card(cv, EV[offset_key] + i, (t_abs - c0) / dur, dur)
                return
    return scene


s_montage1 = montage("m1", "m1_off")
s_montage2 = montage("m2", "m2_off")


CODE = """// Auvyx Mono — calm, clear, made for code
async function load(user: User) {
  const res = await fetch(`/api/users/${user.id}`);
  if (res.status !== 200) return null;

  const data = await res.json();
  return data ?? { name: "Guest" };
}"""
KW = {"async", "function", "const", "await", "if", "return", "null"}
COL = {"kw": (252, 95, 163), "str": (252, 106, 93), "num": (208, 191, 105), "com": (108, 121, 134),
       "type": (93, 216, 255), "fn": (103, 183, 164), "txt": (235, 235, 240)}


def tokenize(line: str) -> list[str]:
    """Trả về màu cho từng ký tự của dòng."""
    kinds = ["txt"] * len(line)
    for m in re.finditer(r"//.*$|`[^`]*`|\"[^\"]*\"|\b\d+\b|[A-Za-z_]\w*", line):
        tok, i = m.group(0), m.start()
        if tok.startswith("//"):
            k = "com"
        elif tok[0] in "`\"":
            k = "str"
        elif tok[0].isdigit():
            k = "num"
        elif tok in KW:
            k = "kw"
        elif tok[0].isupper():
            k = "type"
        elif line[m.end():m.end() + 1] == "(":
            k = "fn"
        else:
            continue
        for j in range(i, m.end()):
            kinds[j] = k
    return kinds


def s_code(cv, t, D):
    """6 — mỗi dòng code vào đúng một nốt; camera đẩy chậm."""
    draw_text(cv, UP, "Made for long sessions.", 44, W / 2, 170, color=GRAY)
    cx, cy, cw, ch = 260, 240, 1400, 640
    cv.rect(cx, cy, cw, ch, (26, 26, 30), 1, 28)
    for i, c in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        cv.rect(cx + 32 + i * 34, cy + 30, 18, 18, c, 1, 9)
    size, lh = 32, 58
    x0, y0 = cx + 70, cy + 130
    for li, full in enumerate(CODE.split("\n")):
        tl = EV["code_lines"][li]
        if t < tl:
            break
        n = int(len(full) * clamp((t - tl) / (BEAT * 0.7)))
        line = full[:n]
        kinds = tokenize(full)[: len(line)]
        for k in set(kinds):
            layer = "".join(chh if kk == k else " " for chh, kk in zip(line, kinds))
            draw_text(cv, IT if k == "com" else UP, layer.rstrip(), size, x0, y0 + li * lh, color=COL[k], align="left")
    CAM["v"] = (1.0 + 0.10 * ease_in_out(prog(t, 0, D)), W / 2, H / 2 + 40)


def s_viet(cv, t, D):
    """7 — tiêu đề vào nốt mạnh, mỗi từ của câu vào một nốt."""
    p = ease_out(prog(t, 0.0, 0.3))
    draw_text(cv, UP, "Tiếng Việt.", 200 * (1 + 0.06 * (1 - p)), W / 2, 520, wght=700, grad=GRAD,
              alpha=min(1, p * 1.5), blur=8 * (1 - p))
    words = "Chữ đẹp là nết người.".split(" ")
    part = reveal_words(t, words, EV["viet_words"])
    if part:
        draw_text(cv, IT, part, 80, W / 2, 690, wght=400)
    draw_text(cv, UP, "Every diacritic, in its place.", 40, W / 2, 830, color=GRAY,
              alpha=ease_out(prog(t, EV["viet_words"][-1], 0.3)))
    CAM["v"] = (1.0 + 0.05 * ease_out(prog(t, 0, D)), W / 2, H / 2)


# ---- bão glyph & fermata
STORM_COLS, STORM_ROWS, STORM_SIZE = 20, 9, 70


def _storm_cells(seed: int, density: float):
    rng = np.random.default_rng(seed)
    pool = [c for c in GLYPHS if c.strip()]
    cells = []
    for r in range(STORM_ROWS):
        for c in range(STORM_COLS):
            if rng.random() > density:
                continue
            cells.append((c, r, pool[rng.integers(len(pool))], int(rng.choice([100, 300, 500, 700])),
                          rng.random() < 0.12, rng.random() < 0.25))
    return cells


def _cell_xy(c, r):
    return (W / 2 + (c - (STORM_COLS - 1) / 2) * 92, H / 2 + (r - (STORM_ROWS - 1) / 2) * 112 + 26)


def draw_storm(cv, cells, spread=0.0, alpha=1.0, blur=0.0):
    for c, r, ch, w, hot, it in cells:
        x, y = _cell_xy(c, r)
        dx, dy = x - W / 2, y - H / 2
        x, y = x + dx * spread, y + dy * spread
        kw = dict(grad=GRAD) if hot else dict(color=WHITE)
        draw_text(cv, IT if it else UP, ch, STORM_SIZE * (1 + spread * 0.8), x, y, wght=w, alpha=alpha, blur=blur, **kw)


def s_storm(cv, t, D):
    """9 — cả màn hình đầy ký tự; mỗi nốt đổi toàn bộ; dày dần tới nốt dừng."""
    t_abs = EV["storm_start"] + t
    notes = EV["storm_notes"]
    k = max(0, np.searchsorted(notes, t_abs, side="right") - 1)
    density = 0.25 + 0.75 * clamp(t / D) ** 1.3
    draw_storm(cv, _storm_cells(1000 + k, density))
    CAM["v"] = (1.0 + 0.06 * clamp(t / D) ** 2, W / 2, H / 2)


def s_fermata(cv, t, D):
    """10 — nốt dừng: bão glyph nổ tung như quay chậm (nhanh lúc đầu, rồi gần như dừng), tan theo tiếng vang;
    chữ "a" ở giữa sáng lên đúng nốt dừng rồi mờ dần theo tiếng ngân."""
    notes = EV["storm_notes"]
    cells = _storm_cells(1000 + len(notes), 1.0)
    k = 1 - (1 - clamp(t / D)) ** 5                    # giảm tốc mạnh = cảm giác slow-motion
    ring = 10 ** (-(t / 2.0) * 30 / 20)                 # khớp độ tắt của tiếng vang (~30 dB trong 2s)
    draw_storm(cv, cells, spread=2.2 * k, alpha=clamp(ring ** 1.8 * (1 - 0.6 * k)), blur=7 * k)
    # quầng tối để chữ ở giữa nổi lên
    halo = Image.new("L", (W, H), 0)
    from PIL import ImageDraw, ImageFilter
    ImageDraw.Draw(halo).ellipse([W / 2 - 330, H / 2 - 330, W / 2 + 330, H / 2 + 330], fill=255)
    cv.blit(halo.filter(ImageFilter.GaussianBlur(90)), 0, 0, (0, 0, 0), 0.85)
    p = ease_out(prog(t, 0, 0.1))
    draw_text(cv, UP, "a", 520 * (1 + 0.06 * k), W / 2, H / 2 + 185, wght=700, color=WHITE,
              alpha=p * clamp(ring ** 0.55), blur=2.5 * k)
    CAM["v"] = (1.06 - 0.06 * k, W / 2, H / 2)


def s_end(cv, t, D):
    """11 — piano chậm dần; mỗi chữ cái vào một nốt."""
    t_abs = EV["end_start"] + t
    out = 1 - ease_in_out(prog(t_abs, DURATION - 1.6, 1.5))
    title = "Auvyx Mono"
    size, base = 170, 560
    x_left = W / 2 - advance(UP, title, size, 700) / 2
    cell = advance(UP, "AA", size, 700) - advance(UP, "A", size, 700)
    k = 0
    for i, ch in enumerate(title):
        if ch == " ":
            continue
        tn = EV["end_letters"][k]
        k += 1
        if t_abs < tn:
            continue
        p = ease_out(prog(t_abs, tn, 0.9))
        draw_text(cv, UP, ch, size, x_left + i * cell, base + 22 * (1 - p), wght=700, alpha=p * out,
                  blur=8 * (1 - p), align="left")
    words = ["Free", "&", "open", "source."]
    full = " ".join(words)
    for j, w in enumerate(words):
        tn = EV["end_words"][j]
        if t_abs < tn:
            break
        p = ease_out(prog(t_abs, tn, 0.7))
        before = " ".join(words[:j])
        x = W / 2 - advance(UP, full, 54) / 2 + (advance(UP, before + " ", 54) if j else 0)
        draw_text(cv, UP, w, 54, x, 680 + 12 * (1 - p), grad=GRAD, alpha=p * out, align="left")
    t3 = EV["end_license"]
    draw_text(cv, UP, "SIL Open Font License 1.1", 30, W / 2, 760, color=GRAY, alpha=ease_out(prog(t_abs, t3, 1.0)) * out)
    draw_text(cv, UP, MUSIC_CREDIT, 22, W / 2, 1030, color=(90, 90, 96), alpha=ease_out(prog(t_abs, t3, 1.0)) * out)
    CAM["v"] = (1.0 + 0.035 * ease_out(prog(t, 0, D)), W / 2, H / 2)


# ---------------------------------------------------------------- timeline (tính từ vị trí các nốt)
SCENES: list = []


def setup(info: dict):
    global ONS_T, ONS_S, SCENES, DURATION
    ONS_T, ONS_S = np.array(info["onsets"]), np.array(info["strengths"])
    DURATION = float(info["duration"])
    t_stop, c_start = info["t_stop"], info["c_start"]
    b4, b6, b8, b12, b18, b20, b22, b26 = (snap(bar(b)) for b in (4, 6, 8, 12, 18, 20, 22, 26))

    EV["ana_steps"] = pick_onsets(0.25, bar(3) - 0.2, 0.3, 0.9)
    EV["ana_fill"] = snap(bar(3))
    EV["ana_intro"] = snap(bar(3) + 2 * BEAT)
    EV["title_letters"] = [x - b4 for x in fit(pick_onsets(b4, b6 - 0.1, 0.2, 0.9), 9, b4, 0.3)]
    EV["title_w"] = EV["title_letters"]
    EV["tag1"] = [x - b6 for x in fit(pick_onsets(b6, b6 + 1.5, 0.28, 0.9), 3, b6, 0.4)]
    EV["tag2"] = [x - b6 for x in fit(pick_onsets(snap(bar(7)), snap(bar(7)) + 1.5, 0.28, 0.9), 3, bar(7), 0.4)]
    EV["w_steps"] = [x - b8 for x in pick_onsets(b8 + 0.05, bar(11) - 0.05, 0.3, 1.0)]
    # điểm camera lao vào: một điểm nằm trên nét chữ "a" của "Aa" ở độ đậm Bold
    m = np.asarray(text_mask(UP, "Aa", 560.0, 700.0)[0])
    mask, asc, adv, pad = text_mask(UP, "Aa", 560.0, 700.0)
    ys, xs = np.nonzero(np.asarray(mask) > 250)
    x0 = W / 2 - adv / 2 - pad
    y0 = H / 2 + 560 * 0.36 - asc
    tx, ty = W / 2 + 150, H / 2 + 40
    j = np.argmin((xs + x0 - tx) ** 2 + (ys + y0 - ty) ** 2)
    EV["rush_point"] = (float(xs[j] + x0), float(ys[j] + y0))

    EV["m1_start"], EV["m1"] = b12, plan_cuts(b12, b18, MONTAGE_1)
    EV["m2_start"], EV["m2"] = b22, plan_cuts(b22, b26, MONTAGE_2)
    EV["m1_off"], EV["m2_off"] = 0, len(EV["m1"])
    EV["code_lines"] = [snap(b18 + i * BEAT, 0.1) - b18 for i in range(len(CODE.split("\n")))]
    EV["viet_words"] = [snap(b20 + (3 + i) * BEAT, 0.1) - b20 for i in range(5)]
    EV["storm_start"] = b26
    EV["storm_notes"] = [b26] + pick_onsets(b26 + 0.1, t_stop - 0.05, 0.19, 0.8)

    EV["end_start"] = c_start
    letters = fit(pick_onsets(c_start, DURATION - 4, 0.42, 0.8), 9, c_start, 0.5)
    words = fit(pick_onsets(letters[-1] + 0.5, DURATION - 2.5, 0.28, 0.6), 4, letters[-1] + 0.5, 0.32)
    lic = fit(pick_onsets(words[-1] + 0.5, DURATION - 1.8, 0.3, 0.4), 1, words[-1] + 0.6, 0.3)
    EV["end_letters"], EV["end_words"], EV["end_license"] = letters, words, lic[0]
    SCENES = [(0, b4, s_anatomy), (b4, b6, s_title), (b6, b8, s_tagline), (b8, b12, s_weights),
              (b12, b18, s_montage1), (b18, b20, s_code), (b20, b22, s_viet), (b22, b26, s_montage2),
              (b26, t_stop, s_storm), (t_stop, c_start, s_fermata), (c_start, DURATION + 1, s_end)]


def frame(t: float, idx: int = 0) -> bytes:
    cv = Canvas()
    CAM["v"] = None
    for a, b, fn in SCENES:
        if a <= t < b:
            fn(cv, t - a, b - a)
            break
    return fx.post(cv.a, idx, cam=CAM["v"])


# ---------------------------------------------------------------- render
def _worker(args):
    idx, f0, f1, tmpdir, font_dir, glyph_json, info = args
    init(font_dir, glyph_json, info)
    out = os.path.join(tmpdir, f"part{idx:02d}.mp4")
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-tune", "film", "-pix_fmt", "yuv420p", out],
        stdin=subprocess.PIPE,
    )
    for f in range(f0, f1):
        ff.stdin.write(frame(f / FPS, f))
    ff.stdin.close()
    ff.wait()
    return out


def main():
    import music

    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", required=True)
    ap.add_argument("--glyphs", default=str(Path(__file__).parent.parent / "src/data/glyphs.json"))
    ap.add_argument("--out", default="auvyx-mono-intro.mp4")
    ap.add_argument("--preview", type=float, nargs="*")
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--work", help="thư mục làm việc để render theo từng phần (--part) rồi ghép (--assemble)")
    ap.add_argument("--part", help="i/N: chỉ render phần thứ i trong N phần")
    ap.add_argument("--assemble", action="store_true")
    a = ap.parse_args()

    tmp_ctx = tempfile.TemporaryDirectory() if not a.work else None
    tmp = a.work or tmp_ctx.name
    os.makedirs(tmp, exist_ok=True)
    wav = os.path.join(tmp, "music.wav")
    info_path = os.path.join(tmp, "music.json")
    if os.path.exists(info_path) and os.path.exists(wav) and a.work:
        info = json.loads(Path(info_path).read_text())
    else:
        info = music.build(str(MUSIC), bar, wav)
        Path(info_path).write_text(json.dumps(info, default=float))
    if a.preview is not None:
        init(a.fonts, a.glyphs, info)
        for t in a.preview:
            Image.frombytes("RGB", (W, H), frame(t, int(t * FPS))).save(f"{Path(a.out).with_suffix('')}-{t:05.2f}.png")
        return
    dur = float(info["duration"])
    total = int(dur * FPS)
    n = a.jobs
    parts_n, part_i = (1, 0)
    if a.part:
        part_i, parts_n = (int(v) for v in a.part.split("/"))
    if not a.assemble:
        lo, hi = total * part_i // parts_n, total * (part_i + 1) // parts_n
        chunks = [(part_i * 100 + i, lo + (hi - lo) * i // n, lo + (hi - lo) * (i + 1) // n, tmp, a.fonts, a.glyphs, info)
                  for i in range(n)]
        with Pool(n) as pool:
            pool.map(_worker, chunks)
        if a.part:
            print("part", a.part, "done")
            return
    parts = sorted(str(p) for p in Path(tmp).glob("part*.mp4"))
    lst = os.path.join(tmp, "list.txt")
    Path(lst).write_text("".join(f"file '{p}'\n" for p in parts))
    silent = os.path.join(tmp, "silent.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", silent],
                   check=True)
    if a.no_music:
        shutil.copy(silent, a.out)
    else:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", wav, "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-t", f"{dur}",
                        "-movflags", "+faststart", a.out], check=True)
    if tmp_ctx:
        tmp_ctx.cleanup()
    print("OK", a.out, f"{dur:.2f}s")


if __name__ == "__main__":
    main()

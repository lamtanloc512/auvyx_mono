#!/usr/bin/env python3
"""Video giới thiệu Auvyx Mono — phong cách keynote: nền đen, chữ lớn, chuyển cảnh chậm.

Dùng:
  python3 video/intro.py --fonts ../auvyx_mono/fonts/AuvyxMono/variable --out video/auvyx-mono-intro.mp4
  python3 video/intro.py ... --preview 12.5   # chỉ xuất 1 khung hình PNG tại giây 12.5
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import re
import subprocess
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
from engine import FPS, H, W, Canvas, Face, advance, clamp, draw_text, ease_in_out, ease_out, fade, prog, text_mask  # noqa: E402

WHITE = (245, 245, 247)
GRAY = (134, 134, 139)
DIM = (58, 58, 62)
GRAD = ((255, 138, 76), (214, 92, 255))

UP: Face
IT: Face
GLYPHS: list[str] = []


def init(font_dir: str, glyph_json: str | None, info: dict | None = None):
    global UP, IT, GLYPHS
    UP = Face(str(Path(font_dir) / "AuvyxMono[wght].ttf"))
    IT = Face(str(Path(font_dir) / "AuvyxMono-Italic[wght].ttf"))
    if glyph_json and Path(glyph_json).exists():
        data = json.loads(Path(glyph_json).read_text())
        GLYPHS = [chr(cp) for g in data["groups"] for cp, _ in g["chars"] if g["name"] not in ("Box & blocks", "Powerline")]
    else:
        GLYPHS = [chr(c) for c in range(0x21, 0x7F)]
    if info is not None:
        setup(info)


# ---------------------------------------------------------------- nhịp nhạc
from music import BAR, BEAT, GRID0  # noqa: E402

DURATION = 60.0
SUSTAIN = 2.6                      # thời gian nốt dừng ngân tới khi lặng
MUSIC = Path(__file__).parent / "music" / "ethereal88-in-the-remains-of-the-day.mp3"
MUSIC_CREDIT = "Music: In the Remains of the Day by Ethereal 88 · CC BY 4.0"


def bar(b: float) -> float:
    """Thời điểm (giây, trên video) của ô nhịp thứ b (trước chỗ nối nhạc)."""
    return GRID0 + b * BAR


ONS_T = np.zeros(0)
ONS_S = np.zeros(0)


def snap(t: float, win: float = 0.12, min_s: float = 0.6) -> float:
    """Nốt mạnh nhất gần t (trong ±win); không có thì giữ t."""
    m = (np.abs(ONS_T - t) <= win) & (ONS_S >= min_s)
    if not m.any():
        return t
    cand, st = ONS_T[m], ONS_S[m]
    return float(cand[np.argmax(st * np.exp(-((cand - t) / win) ** 2))])


def pick_onsets(t0: float, t1: float, gap: float, min_s: float = 1.0) -> list[float]:
    """Chuỗi nốt từ t0 tới t1, mỗi nốt cách nốt trước ít nhất `gap`."""
    out, last = [], -1e9
    for t, s in zip(ONS_T, ONS_S):
        if t0 - 0.03 <= t < t1 and s >= min_s and t - last >= gap:
            out.append(float(t))
            last = t
    return out


def plan_cuts(t0: float, t1: float, ramp) -> list[tuple[float, float]]:
    """Cắt cảnh đúng nốt nhạc. `ramp` = [(số ô nhịp, số phách mỗi cảnh)]: nhịp cắt mong muốn theo thời gian;
    mỗi lần cắt chọn nốt mạnh nhất quanh vị trí mong muốn."""
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
                break                                      # không còn nốt: cảnh hiện tại kéo dài tới hết đoạn
            nxt = float(ONS_T[m][0])
        cuts.append(nxt)
    ends = cuts[1:] + [t1]
    return [(a, b - a) for a, b in zip(cuts, ends)]


# ---------------------------------------------------------------- scenes
# Mỗi cảnh nhận thời gian cục bộ t (giây, tính từ đầu cảnh) và độ dài D. EV = các mốc (giây, trên video).
EV: dict = {}


def s_intro(cv, t, D):  # piano mở đầu
    a = fade(t, 0.3, D - 0.1, 0.8, 0.5)
    draw_text(cv, UP, "Introducing", 44, W / 2, 400, wght=400, color=GRAY, alpha=a)
    t1 = EV["title"]
    p = prog(t, t1, 1.3)
    w = 100 + 600 * ease_in_out(prog(t, t1, 2 * BAR))
    draw_text(cv, UP, "Auvyx Mono", 210, W / 2, 640 + 30 * (1 - ease_out(p)), wght=w,
              alpha=ease_out(p) * (1 - ease_in_out(prog(t, D - 0.45, 0.4))), blur=18 * (1 - ease_out(p)))


def s_tagline(cv, t, D):
    a1 = fade(t, 0.0, D - 0.1, 0.6, 0.45)
    t2 = EV["tag2"]
    a2 = fade(t, t2, D - 0.1, 0.6, 0.45)
    p1, p2 = ease_out(prog(t, 0.0, 0.7)), ease_out(prog(t, t2, 0.7))
    draw_text(cv, UP, "Designed for code.", 110, W / 2, 500 + 24 * (1 - p1), wght=700, alpha=a1, blur=10 * (1 - p1))
    draw_text(cv, UP, "Built for people.", 110, W / 2, 640 + 24 * (1 - p2), wght=700, grad=GRAD, alpha=a2, blur=10 * (1 - p2))


def s_weights(cv, t, D):  # dồn lên Bold đúng lúc beat vào
    a = fade(t, 0.1, D + 1, 0.6, 0.5)
    draw_text(cv, UP, "Seven weights. One variable font.", 44, W / 2, 250, color=GRAY, alpha=a)
    phase = ease_in_out(prog(t, 0.3, D - 0.3)) ** 1.3
    w = 100 + 600 * phase
    draw_text(cv, UP, "Auvyx", 320 * (1 + 0.06 * phase), W / 2, 640, wght=w, alpha=a)
    names = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold"}
    name = names[min(names, key=lambda k: abs(k - w))]
    draw_text(cv, UP, f"wght {int(round(w)):>3}", 36, W / 2 - 40, 840, color=WHITE, alpha=a * 0.9, align="right")
    draw_text(cv, UP, name, 36, W / 2 + 40, 840, color=GRAY, alpha=a, align="left")
    x0, x1, y = 560, 1360, 900
    cv.rect(x0, y, x1 - x0, 4, DIM, a, 2)
    cv.rect(x0, y, (x1 - x0) * phase + 1, 4, (255, 138, 76), a, 2)
    cv.rect(x0 + (x1 - x0) * phase - 10, y - 8, 20, 20, WHITE, a, 10)


# ---- MONTAGE: nhịp cắt mong muốn (số ô nhịp, số phách mỗi cảnh) — thực tế mỗi lần cắt rơi đúng một nốt nhạc
MONTAGE_1 = [(2, 2.0), (2, 1.0), (2, 0.5)]            # 2 phách → 1 phách → nửa phách
MONTAGE_2 = [(2, 1.0), (2, 0.5), (1, 0.5), (1, 0.25)]  # dồn dập tới nốt dừng

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


FINAL_CARD = ("t", "Aa", 520, 700, False, "w")          # hiện đúng nốt dừng, rồi ngân theo nốt đó


def _card(i):
    """Cảnh thứ i; lặp lại danh sách với độ đậm/kiểu khác để không trùng."""
    kind, txt, size, wght, italic, col = CARDS[i % len(CARDS)]
    rnd = i // len(CARDS)
    if rnd:
        wght = min(700, 100 + (wght - 100 + 300 * rnd) % 700)
        if len(txt) <= 2:
            italic = not italic
        if col == "i":
            col = "w"
    return kind, txt, size, wght, italic, col


def draw_card(cv, card, lt, dur, grow=0.035):
    kind, txt, size, wght, italic, col = card
    if dur < 0.2 and col == "i":        # cảnh cực nhanh: không đảo nền trắng (tránh nháy sáng)
        col = "w"
    if col == "i":
        cv.a[:] = np.array(WHITE, np.float32) / 255
    face = IT if italic else UP
    g = 1 + grow * lt
    kw = dict(wght=wght, feats=(("calt", True),))
    if col == "g":
        kw["grad"] = GRAD
    else:
        kw["color"] = (12, 12, 14) if col == "i" else WHITE
    draw_text(cv, face, txt, size * g, W / 2, H / 2 + size * 0.36, **kw)
    if dur >= 2 * BEAT - 0.05:
        tag = f"{'Italic' if italic else 'Upright'} · wght {wght}"
        draw_text(cv, UP, tag, 30, W / 2, H - 120, color=(90, 90, 96) if col != "i" else (120, 120, 126))


def montage(key, offset_key):
    def scene(cv, t, D):
        t_abs = EV[key + "_start"] + t
        for i, (c0, dur) in enumerate(EV[key]):
            if c0 <= t_abs < c0 + dur:
                draw_card(cv, _card(EV[offset_key] + i), (t_abs - c0) / dur, dur)
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


def s_code(cv, t, D):  # mỗi dòng code hiện đúng một nốt
    a = fade(t, 0.0, D - 0.05, 0.25, 0.2)
    draw_text(cv, UP, "Made for long sessions.", 44, W / 2, 170, color=GRAY, alpha=a)
    cx, cy, cw, ch = 260, 240, 1400, 640
    lift = 24 * (1 - ease_out(prog(t, 0.0, 0.3)))
    cv.rect(cx, cy + lift, cw, ch, (28, 28, 32), a, 28)
    for i, c in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        cv.rect(cx + 32 + i * 34, cy + lift + 30, 18, 18, c, a, 9)
    size, lh = 32, 58
    all_lines = CODE.split("\n")
    x0, y0 = cx + 70, cy + lift + 130
    for li, full in enumerate(all_lines):
        t_line = EV["code_lines"][li]
        if t < t_line:
            break
        n = int(len(full) * clamp((t - t_line) / (BEAT * 0.7)))
        line = full[:n]
        kinds = tokenize(full)[: len(line)]
        for k in set(kinds):
            layer = "".join(chh if kk == k else " " for chh, kk in zip(line, kinds))
            face = IT if k == "com" else UP
            draw_text(cv, face, layer.rstrip(), size, x0, y0 + li * lh, color=COL[k], alpha=a, align="left")


def s_viet(cv, t, D):  # tiêu đề vào nốt mạnh, mỗi từ của câu vào một nốt
    a = fade(t, 0.0, D - 0.05, 0.2, 0.2)
    p = ease_out(prog(t, 0.0, 0.3))
    draw_text(cv, UP, "Tiếng Việt.", 190 * (1 + 0.06 * (1 - p)), W / 2, 520, wght=700, grad=GRAD,
              alpha=a * min(1, p * 1.5), blur=8 * (1 - p))
    words = "Chữ đẹp là nết người.".split(" ")
    shown = [w for k, w in enumerate(words) if t >= EV["viet_words"][k]]
    if shown:
        full = " ".join(words)
        part = " ".join(shown) + " " * (len(full) - len(" ".join(shown)))
        draw_text(cv, IT, part, 76, W / 2, 680, wght=400, alpha=a)
    draw_text(cv, UP, "Every diacritic, in its place.", 40, W / 2, 820, color=GRAY,
              alpha=a * ease_out(prog(t, EV["viet_words"][-1], 0.3)))


def drone_env(t):
    import music
    return float(music.drone_env(t, SUSTAIN))


def s_afterglow(cv, t, D):  # nốt dừng: "Aa" hiện đúng nốt, rồi ngân — chậm lại, nhoè, tắt dần cùng tiếng ngân
    kind, txt, size, wght, italic, col = FINAL_CARD
    k = ease_out(prog(t, 0.0, D))
    env = drone_env(t)
    alpha = clamp((20 * math.log10(max(env, 1e-4)) + 55) / 55) ** 1.4    # mờ theo độ lớn (dB) của tiếng ngân
    gray = tuple(int(c + (g - c) * k) for c, g in zip(WHITE, GRAY))
    g = 1.0 + 0.14 * k
    draw_text(cv, IT if italic else UP, txt, size * g, W / 2, H / 2 + size * 0.36 * g, wght=wght, color=gray,
              alpha=alpha, blur=12 * k)


def s_end(cv, t, D):  # đoạn hạ màn: mỗi chữ cái vào một nốt piano (cách nhau ≥ 0,45s)
    t_abs = EV["end_start"] + t
    out = 1 - ease_in_out(prog(t, D - 1.3, 1.25))
    title = "Auvyx Mono"
    size, base = 170, 560
    x_left = W / 2 - advance(UP, title, size, 700) / 2
    step = advance(UP, "AA", size, 700) - advance(UP, "A", size, 700)
    letters = EV["end_letters"]
    k = 0
    for i, ch in enumerate(title):
        if ch == " ":
            continue
        tn = letters[k]
        k += 1
        if t_abs < tn:
            continue
        p = ease_out(prog(t_abs, tn, 0.75))
        draw_text(cv, UP, ch, size, x_left + i * step, base + 22 * (1 - p), wght=700, alpha=p * out,
                  blur=8 * (1 - p), align="left")
    words = ["Free", "&", "open", "source."]
    full = " ".join(words)
    for j, w in enumerate(words):
        tn = EV["end_words"][j]
        if t_abs < tn:
            break
        p = ease_out(prog(t_abs, tn, 0.6))
        before = " ".join(words[:j])
        x = W / 2 - advance(UP, full, 54) / 2 + (advance(UP, before + " ", 54) if j else 0)
        draw_text(cv, UP, w, 54, x, 680 + 12 * (1 - p), grad=GRAD, alpha=p * out, align="left")
    t3 = EV["end_license"]
    draw_text(cv, UP, "SIL Open Font License 1.1", 30, W / 2, 760, color=GRAY, alpha=ease_out(prog(t_abs, t3, 1.0)) * out)
    draw_text(cv, UP, MUSIC_CREDIT, 22, W / 2, 1030, color=(90, 90, 96), alpha=ease_out(prog(t_abs, t3, 1.0)) * out)


# ---------------------------------------------------------------- timeline (tính từ vị trí các nốt)
SCENES: list = []


def setup(info: dict):
    global ONS_T, ONS_S, SCENES
    ONS_T = np.array(info["onsets"])
    ONS_S = np.array(info["strengths"])
    t_stop, c_start = info["t_stop"], info["c_start"]
    b4, b8, b12, b18, b20, b22 = (snap(bar(b)) for b in (4, 8, 12, 18, 20, 22))
    EV.update(title=snap(bar(1)) , tag2=snap(bar(6)) - b4)
    EV["m1_start"], EV["m1"] = b12, plan_cuts(b12, b18, MONTAGE_1)
    EV["m2_start"], EV["m2"] = b22, plan_cuts(b22, t_stop, MONTAGE_2)
    EV["m1_off"], EV["m2_off"] = 0, len(EV["m1"])
    EV["code_lines"] = [snap(b18 + i * BEAT, 0.1) - b18 for i in range(len(CODE.split("\n")))]
    EV["viet_words"] = [snap(b20 + (3 + i) * BEAT, 0.1) - b20 for i in range(5)]
    EV["end_start"] = c_start
    def fill(ns, n, start, gap):                             # dự phòng nếu thiếu nốt
        ns = list(ns)
        while len(ns) < n:
            ns.append((ns[-1] if ns else start) + gap)
        return ns[:n]
    letters = fill(pick_onsets(c_start, DURATION - 3, 0.45, 0.9), 9, c_start, 0.55)   # chữ cái: cách ~1 nốt
    words = fill(pick_onsets(letters[-1] + 0.5, DURATION - 2, 0.25, 0.8), 4, letters[-1] + 0.5, 0.28)  # mỗi nốt một từ
    lic = fill(pick_onsets(words[-1] + 0.5, DURATION - 1.5, 0.3, 0.5), 1, words[-1] + 0.5, 0.3)
    EV["end_letters"], EV["end_words"], EV["end_license"] = letters, words, lic[0]
    SCENES = [(0, b4, s_intro), (b4, b8, s_tagline), (b8, b12, s_weights), (b12, b18, s_montage1),
              (b18, b20, s_code), (b20, b22, s_viet), (b22, t_stop, s_montage2), (t_stop, c_start, s_afterglow),
              (c_start, DURATION, s_end)]


def frame(t: float) -> Canvas:
    cv = Canvas()
    for a, b, fn in SCENES:
        if a <= t < b:
            fn(cv, t - a, b - a)
    return cv


# ---------------------------------------------------------------- render
def _worker(args):
    idx, f0, f1, tmpdir, font_dir, glyph_json, info = args
    init(font_dir, glyph_json, info)
    out = os.path.join(tmpdir, f"part{idx:02d}.mp4")
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", out],
        stdin=subprocess.PIPE,
    )
    for f in range(f0, f1):
        ff.stdin.write(frame(f / FPS).rgb())
    ff.stdin.close()
    ff.wait()
    return out


def main():
    import music

    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", required=True, help="thư mục chứa AuvyxMono[wght].ttf")
    ap.add_argument("--glyphs", default=str(Path(__file__).parent.parent / "src/data/glyphs.json"))
    ap.add_argument("--out", default="auvyx-mono-intro.mp4")
    ap.add_argument("--preview", type=float, nargs="*")
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    a = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "music.wav")
        info = music.build(str(MUSIC), bar, DURATION, wav, sustain=SUSTAIN)
        if a.preview is not None:
            init(a.fonts, a.glyphs, info)
            from PIL import Image
            for t in a.preview:
                Image.frombytes("RGB", (W, H), frame(t).rgb()).save(f"{Path(a.out).with_suffix('')}-{t:05.2f}.png")
            return
        total = int(DURATION * FPS)
        n = a.jobs
        chunks = [(i, total * i // n, total * (i + 1) // n, tmp, a.fonts, a.glyphs, info) for i in range(n)]
        with Pool(n) as pool:
            parts = pool.map(_worker, chunks)
        lst = os.path.join(tmp, "list.txt")
        Path(lst).write_text("".join(f"file '{p}'\n" for p in parts))
        silent = os.path.join(tmp, "silent.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", silent],
                       check=True)
        if a.no_music:
            shutil.copy(silent, a.out)
        else:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", wav, "-map", "0:v", "-map", "1:a",
                            "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-t", f"{DURATION}",
                            "-movflags", "+faststart", a.out], check=True)
    print("OK", a.out)


if __name__ == "__main__":
    main()

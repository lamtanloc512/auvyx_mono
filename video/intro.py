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


def init(font_dir: str, glyph_json: str | None):
    global UP, IT, GLYPHS
    UP = Face(str(Path(font_dir) / "AuvyxMono[wght].ttf"))
    IT = Face(str(Path(font_dir) / "AuvyxMono-Italic[wght].ttf"))
    if glyph_json and Path(glyph_json).exists():
        data = json.loads(Path(glyph_json).read_text())
        GLYPHS = [chr(cp) for g in data["groups"] for cp, _ in g["chars"] if g["name"] not in ("Box & blocks", "Powerline")]
    else:
        GLYPHS = [chr(c) for c in range(0x21, 0x7F)]


# ---------------------------------------------------------------- nhịp nhạc
# Nhạc: "In the Remains of the Day" by Ethereal 88 (CC BY 4.0), 140 BPM.
# Mọi mốc thời gian của video được đặt theo ô nhịp của bài (1 ô = 4 phách = 1,714s).
BPM = 140.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT
GRID0 = 0.421                      # phách đầu tiên của bài (giây)


def bar(b: float) -> float:
    """Thời điểm (giây, trên video) của ô nhịp thứ b."""
    return GRID0 + b * BAR


# ---------------------------------------------------------------- scenes
# Mỗi cảnh nhận thời gian cục bộ t (giây, tính từ đầu cảnh) và độ dài D của cảnh.

def s_intro(cv, t, D):  # ô 0–4: piano mở đầu
    a = fade(t, 0.3, D - 0.1, 0.8, 0.5)
    draw_text(cv, UP, "Introducing", 44, W / 2, 400, wght=400, color=GRAY, alpha=a)
    p = prog(t, BAR, 1.3)
    w = 100 + 600 * ease_in_out(prog(t, BAR, 2 * BAR))
    draw_text(cv, UP, "Auvyx Mono", 210, W / 2, 640 + 30 * (1 - ease_out(p)), wght=w,
              alpha=ease_out(p) * (1 - ease_in_out(prog(t, D - 0.45, 0.4))), blur=18 * (1 - ease_out(p)))


def s_tagline(cv, t, D):  # ô 4–8
    a1 = fade(t, 0.0, D - 0.1, 0.6, 0.45)
    a2 = fade(t, 2 * BAR, D - 0.1, 0.6, 0.45)
    p1, p2 = ease_out(prog(t, 0.0, 0.7)), ease_out(prog(t, 2 * BAR, 0.7))
    draw_text(cv, UP, "Designed for code.", 110, W / 2, 500 + 24 * (1 - p1), wght=700, alpha=a1, blur=10 * (1 - p1))
    draw_text(cv, UP, "Built for people.", 110, W / 2, 640 + 24 * (1 - p2), wght=700, grad=GRAD, alpha=a2, blur=10 * (1 - p2))


def s_weights(cv, t, D):  # ô 8–12: dồn lên Bold đúng lúc beat vào
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


# ---- MONTAGE: cắt cảnh theo nhịp. Mỗi đoạn montage = [(số ô nhịp, số phách mỗi cảnh), ...]
MONTAGE_1 = [(2, 2.0), (2, 1.0), (2, 0.5)]            # ô 12–18: 2 phách → 1 phách → nửa phách
MONTAGE_2 = [(2, 1.0), (2, 0.5), (1, 0.5), (1, 0.25)]  # ô 22–28: dồn dập tới sát đoạn hạ màn

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


def _cuts(ramp):
    cuts, beat = [], 0.0
    for bars, per in ramp:
        for _ in range(int(round(bars * 4 / per))):
            cuts.append((beat * BEAT, per * BEAT))
            beat += per
    return cuts


def _card(i):
    """Cảnh thứ i; lặp lại danh sách với độ đậm/kiểu khác để không trùng."""
    kind, txt, size, wght, italic, col = CARDS[i % len(CARDS)]
    rnd = i // len(CARDS)
    if rnd:
        wght = 100 + (wght - 100 + 300 * rnd) % 700
        wght = min(700, wght)
        if len(txt) <= 2:
            italic = not italic
        if col == "i":
            col = "w"
    return kind, txt, size, wght, italic, col


def montage(ramp, offset):
    cuts = _cuts(ramp)

    def scene(cv, t, D):
        for i, (c0, dur) in enumerate(cuts):
            if c0 <= t < c0 + dur:
                kind, txt, size, wght, italic, col = _card(offset + i)
                if dur < 0.2 and col == "i":        # cảnh cực nhanh: không đảo nền trắng (tránh nháy sáng)
                    col = "w"
                lt = (t - c0) / dur
                if col == "i":
                    cv.a[:] = np.array(WHITE, np.float32) / 255
                face = IT if italic else UP
                grow = 1 + 0.035 * lt
                base = H / 2 + size * 0.36
                kw = dict(wght=wght, feats=(("calt", True),))
                if col == "g":
                    kw["grad"] = GRAD
                else:
                    kw["color"] = (12, 12, 14) if col == "i" else WHITE
                pin = 1.0 if dur < 0.5 else ease_out(clamp(lt * dur / 0.08))
                draw_text(cv, face, txt, size * grow, W / 2, base, alpha=pin, **kw)
                if dur >= 2 * BEAT - 1e-6:
                    tag = f"{'Italic' if italic else 'Upright'} · wght {wght}"
                    draw_text(cv, UP, tag, 30, W / 2, H - 120, color=(90, 90, 96) if col != "i" else (120, 120, 126), alpha=pin)
                return

    scene.count = len(cuts)
    return scene


s_montage1 = montage(MONTAGE_1, 0)
s_montage2 = montage(MONTAGE_2, s_montage1.count)


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


def s_code(cv, t, D):  # ô 18–20: mỗi phách hiện 1 dòng code
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
        t_line = li * BEAT                                  # dòng li xuất hiện ở phách li
        if t < t_line:
            break
        n = int(len(full) * clamp((t - t_line) / (BEAT * 0.7)))   # gõ xong trong 70% phách
        line = full[:n]
        kinds = tokenize(full)[: len(line)]
        for k in set(kinds):
            layer = "".join(chh if kk == k else " " for chh, kk in zip(line, kinds))
            face = IT if k == "com" else UP
            draw_text(cv, face, layer.rstrip(), size, x0, y0 + li * lh, color=COL[k], alpha=a, align="left")


def s_viet(cv, t, D):  # ô 20–22: tiêu đề vào phách mạnh, mỗi phách một từ
    a = fade(t, 0.0, D - 0.05, 0.2, 0.2)
    p = ease_out(prog(t, 0.0, 0.3))
    draw_text(cv, UP, "Tiếng Việt.", 190 * (1 + 0.06 * (1 - p)), W / 2, 520, wght=700, grad=GRAD,
              alpha=a * min(1, p * 1.5), blur=8 * (1 - p))
    words = "Chữ đẹp là nết người.".split(" ")
    shown = [w for k, w in enumerate(words) if t >= (3 + k) * BEAT]
    if shown:
        full = " ".join(words)
        # giữ vị trí cố định: vẽ cả câu nhưng chỉ phần đã hiện (các từ sau thay bằng khoảng trắng)
        part = " ".join(shown) + " " * (len(full) - len(" ".join(shown)))
        draw_text(cv, IT, part, 76, W / 2, 680, wght=400, alpha=a)
    draw_text(cv, UP, "Every diacritic, in its place.", 40, W / 2, 820, color=GRAY, alpha=a * ease_out(prog(t, 5 * BEAT, 0.3)))


def s_end(cv, t, D):  # ô 28 → hết: đoạn hạ màn, piano rải nốt mỗi nửa phách
    NOTE = BEAT / 2
    out = 1 - ease_in_out(prog(t, D - 1.4, 1.3))
    title = "Auvyx Mono"
    size, base = 170, 560
    x_left = W / 2 - advance(UP, title, size, 700) / 2
    step = advance(UP, "AA", size, 700) - advance(UP, "A", size, 700)   # độ rộng 1 ô monospace
    k = 0
    for i, ch in enumerate(title):
        if ch == " ":
            continue
        tn = k * NOTE                                     # mỗi chữ cái vào đúng một nốt piano
        k += 1
        if t < tn:
            continue
        p = ease_out(prog(t, tn, 0.35))
        draw_text(cv, UP, ch, size, x_left + i * step, base + 18 * (1 - p), wght=700, alpha=p * out,
                  blur=6 * (1 - p), align="left")
    t2 = 12 * NOTE                                        # sau 9 chữ cái + 3 nốt nghỉ
    for j, w in enumerate(["Free", "&", "open", "source."]):
        tn = t2 + j * NOTE
        if t < tn:
            break
        p = ease_out(prog(t, tn, 0.3))
        full = "Free & open source."
        before = " ".join(["Free", "&", "open", "source."][:j])
        x = W / 2 - advance(UP, full, 54) / 2 + (advance(UP, before + " ", 54) if j else 0)
        draw_text(cv, UP, w, 54, x, 680 + 10 * (1 - p), grad=GRAD, alpha=p * out, align="left")
    t3 = t2 + 8 * NOTE
    draw_text(cv, UP, "SIL Open Font License 1.1", 30, W / 2, 760, color=GRAY, alpha=ease_out(prog(t, t3, 0.6)) * out)
    draw_text(cv, UP, MUSIC_CREDIT, 22, W / 2, 1030, color=(90, 90, 96), alpha=ease_out(prog(t, t3, 0.6)) * out)


# ---------------------------------------------------------------- timeline & nhạc
SCENES = [(0, bar(4), s_intro), (bar(4), bar(8), s_tagline), (bar(8), bar(12), s_weights),
          (bar(12), bar(18), s_montage1), (bar(18), bar(20), s_code), (bar(20), bar(22), s_viet),
          (bar(22), bar(28), s_montage2), (bar(28), None, s_end)]

MUSIC = Path(__file__).parent / "music" / "ethereal88-in-the-remains-of-the-day.mp3"
MUSIC_CREDIT = "Music: In the Remains of the Day by Ethereal 88 · CC BY 4.0"
# Ghép 2 đoạn, chỗ nối nằm đúng vạch ô nhịp:
#   A  bài 0 → ô 24: piano mở đầu, beat vào ở ô 12 (giây 21.0) = lúc montage bắt đầu
#   B  bài từ ô 97 tới hết: 4 ô cuối còn sôi động, rồi đoạn hạ màn (piano rải nốt) bắt đầu ở ô 101
#      của bài = ô 28 của video = lúc chữ của màn kết bắt đầu hiện theo từng nốt
SPLICE_VIDEO_BAR, SPLICE_SONG_BAR = 24, 97
XF = BEAT                                           # độ dài hoà trộn ở chỗ nối
SONG_END = 180.8
DURATION = round(bar(SPLICE_VIDEO_BAR) + (SONG_END - (GRID0 + SPLICE_SONG_BAR * BAR)), 2)


def frame(t: float) -> Canvas:
    cv = Canvas()
    for a, b, fn in SCENES:
        b = DURATION if b is None else b
        if a <= t < b:
            fn(cv, t - a, b - a)
    return cv


# ---------------------------------------------------------------- render
def _worker(args):
    idx, f0, f1, tmpdir, font_dir, glyph_json = args
    init(font_dir, glyph_json)
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", required=True, help="thư mục chứa AuvyxMono[wght].ttf")
    ap.add_argument("--glyphs", default=str(Path(__file__).parent.parent / "src/data/glyphs.json"))
    ap.add_argument("--out", default="auvyx-mono-intro.mp4")
    ap.add_argument("--preview", type=float, nargs="*")
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    a = ap.parse_args()

    if a.preview is not None:
        init(a.fonts, a.glyphs)
        from PIL import Image
        for t in a.preview:
            cv = frame(t)
            Image.frombytes("RGB", (W, H), cv.rgb()).save(f"{Path(a.out).with_suffix('')}-{t:05.2f}.png")
        return

    total = int(DURATION * FPS)
    n = a.jobs
    with tempfile.TemporaryDirectory() as tmp:
        chunks = [(i, total * i // n, total * (i + 1) // n, tmp, a.fonts, a.glyphs) for i in range(n)]
        with Pool(n) as pool:
            parts = pool.map(_worker, chunks)
        lst = os.path.join(tmp, "list.txt")
        Path(lst).write_text("".join(f"file '{p}'\n" for p in parts))
        silent = os.path.join(tmp, "silent.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                        "-c", "copy", silent], check=True)
        if MUSIC.exists() and not a.no_music:
            j = bar(SPLICE_VIDEO_BAR)
            b_song = GRID0 + SPLICE_SONG_BAR * BAR - XF / 2
            graph = (f"[1:a]atrim=0:{j + XF / 2},asetpts=PTS-STARTPTS[a];"
                     f"[1:a]atrim={b_song}:{SONG_END},asetpts=PTS-STARTPTS[b];"
                     f"[a][b]acrossfade=d={XF}:c1=qsin:c2=qsin,"
                     f"afade=t=out:st={DURATION - 0.8}:d=0.8")
            meas = subprocess.run(["ffmpeg", "-hide_banner", "-f", "lavfi", "-i", "anullsrc", "-i", str(MUSIC),
                                   "-filter_complex", graph + ",loudnorm=I=-15:TP=-1.5:LRA=20:print_format=json[o]",
                                   "-map", "[o]", "-f", "null", "-"], capture_output=True, text=True).stderr
            m = json.loads(meas[meas.rindex("{"):meas.rindex("}") + 1])
            graph += (f",loudnorm=I=-15:TP=-1.5:LRA=20:linear=true:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                      f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}[o]")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", str(MUSIC),
                            "-filter_complex", graph, "-map", "0:v", "-map", "[o]", "-c:v", "copy",
                            "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-t", f"{DURATION}",
                            "-movflags", "+faststart", a.out], check=True)
        else:
            shutil.copy(silent, a.out)
    print("OK", a.out)


if __name__ == "__main__":
    main()

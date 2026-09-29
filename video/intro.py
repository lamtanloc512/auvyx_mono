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
from engine import FPS, H, W, Canvas, Face, advance, clamp, draw_text, ease_in_out, ease_out, fade, prog, text_mask  # noqa: E402

WHITE = (245, 245, 247)
GRAY = (134, 134, 139)
DIM = (58, 58, 62)
GRAD = ((255, 138, 76), (214, 92, 255))
DURATION = 56.0

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


# ---------------------------------------------------------------- scenes
# Mỗi cảnh nhận thời gian cục bộ t (giây, tính từ đầu cảnh) và độ dài D của cảnh.
# Các cảnh đặt trên lưới 2 giây.

def s_intro(cv, t, D):
    a = fade(t, 0.4, D - 0.2, 0.8, 0.6)
    draw_text(cv, UP, "Introducing", 44, W / 2, 400, wght=400, color=GRAY, alpha=a)
    p = prog(t, 1.4, 1.4)
    w = 100 + 600 * ease_in_out(prog(t, 1.6, 3.0))
    draw_text(cv, UP, "Auvyx Mono", 210, W / 2, 640 + 30 * (1 - ease_out(p)), wght=w,
              alpha=ease_out(p) * (1 - ease_in_out(prog(t, D - 0.5, 0.45))), blur=18 * (1 - ease_out(p)))


def s_tagline(cv, t, D):
    a1 = fade(t, 0.0, D - 0.1, 0.7, 0.5)
    a2 = fade(t, 1.0, D - 0.1, 0.7, 0.5)
    y1 = 500 + 24 * (1 - ease_out(prog(t, 0.0, 0.7)))
    y2 = 640 + 24 * (1 - ease_out(prog(t, 1.0, 0.7)))
    draw_text(cv, UP, "Designed for code.", 110, W / 2, y1, wght=700, alpha=a1, blur=10 * (1 - ease_out(prog(t, 0.0, 0.7))))
    draw_text(cv, UP, "Built for people.", 110, W / 2, y2, wght=700, grad=GRAD, alpha=a2,
              blur=10 * (1 - ease_out(prog(t, 1.0, 0.7))))


def s_weights(cv, t, D):
    a = fade(t, 0.1, D - 0.1, 0.7, 0.5)
    draw_text(cv, UP, "Seven weights. One variable font.", 44, W / 2, 250, color=GRAY, alpha=a)
    phase = ease_in_out(prog(t, 1.0, 3.0)) - ease_in_out(prog(t, 4.0, 3.0))
    w = 100 + 600 * phase
    draw_text(cv, UP, "Auvyx", 320, W / 2, 640, wght=w, alpha=a)
    names = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold"}
    name = names[min(names, key=lambda k: abs(k - w))]
    draw_text(cv, UP, f"wght {int(round(w)):>3}", 36, W / 2 - 40, 820, color=WHITE, alpha=a * 0.9, align="right")
    draw_text(cv, UP, name, 36, W / 2 + 40, 820, color=GRAY, alpha=a, align="left")
    x0, x1, y = 560, 1360, 880
    cv.rect(x0, y, x1 - x0, 4, DIM, a, 2)
    cv.rect(x0, y, (x1 - x0) * phase + 1, 4, (255, 138, 76), a, 2)
    cv.rect(x0 + (x1 - x0) * phase - 10, y - 8, 20, 20, WHITE, a, 10)


def s_italic(cv, t, D):
    a = fade(t, 0.1, D - 0.1, 0.7, 0.5)
    draw_text(cv, UP, "A true italic.", 44, W / 2, 300, color=GRAY, alpha=a)
    k_out = ease_in_out(prog(t, 1.75, 0.35))  # chữ đứng tắt ngay trước phách
    k_in = ease_out(prog(t, 2.0, 0.6))        # chữ nghiêng hiện đúng phách mạnh
    word = "Hamburgefonstiv"
    draw_text(cv, UP, word, 150, W / 2 - 20 * k_out, 600, wght=500, alpha=a * (1 - k_out), blur=8 * k_out)
    draw_text(cv, IT, word, 150, W / 2 + 20 * (1 - k_in), 600, wght=500, alpha=a * k_in, blur=8 * (1 - k_in))
    draw_text(cv, IT, "kljrvwtf  KLJRVWTF", 64, W / 2, 790, wght=400, grad=GRAD, alpha=a * ease_out(prog(t, 3.0, 0.8)))


LIGS = ["->", "!=", "===", "|>", "=>", "::"]


def s_ligatures(cv, t, D):
    a = fade(t, 0.1, D - 0.1, 0.7, 0.5)
    draw_text(cv, UP, "Ligatures that read naturally.", 44, W / 2, 260, color=GRAY, alpha=a)
    for i, lig in enumerate(LIGS):
        t0 = 0.5 + i * 1.0                     # hiện ở nửa phách, gộp đúng phách
        last = i == len(LIGS) - 1
        ai = fade(t, t0, D - 0.1 if last else t0 + 1.15, 0.25, 0.3)
        if ai <= 0:
            continue
        k = ease_in_out(prog(t, t0 + 0.4, 0.2))
        draw_text(cv, UP, lig, 300, W / 2, 680, wght=500, alpha=ai * (1 - k), feats=(("calt", False),))
        draw_text(cv, UP, lig, 300, W / 2, 680, wght=500, alpha=ai * k, grad=GRAD)
    draw_text(cv, UP, "if (a != b && x >= 0) data |> render;", 40, W / 2, 900, color=WHITE,
              alpha=a * ease_out(prog(t, 1.0, 1.0)) * 0.85)


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
    a = fade(t, 0.1, D - 0.1, 0.7, 0.5)
    draw_text(cv, UP, "Made for long sessions.", 44, W / 2, 170, color=GRAY, alpha=a)
    cx, cy, cw, ch = 260, 240, 1400, 640
    lift = 30 * (1 - ease_out(prog(t, 0.1, 0.9)))
    cv.rect(cx, cy + lift, cw, ch, (28, 28, 32), a, 28)
    for i, c in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        cv.rect(cx + 32 + i * 34, cy + lift + 30, 18, 18, c, a, 9)
    size, lh = 32, 58
    n = int(max(0, t - 0.9) * 42)  # ký tự đã gõ
    shown = CODE[:n]
    lines = shown.split("\n")
    x0, y0 = cx + 70, cy + lift + 130
    for li, line in enumerate(lines):
        kinds = tokenize(CODE.split("\n")[li])[: len(line)]
        for k in set(kinds):
            layer = "".join(chh if kk == k else " " for chh, kk in zip(line, kinds))
            face = IT if k == "com" else UP
            draw_text(cv, face, layer.rstrip(), size, x0, y0 + li * lh, color=COL[k], alpha=a, align="left")
    if n < len(CODE) or int(t * 2) % 2 == 0:
        last = lines[-1] if lines else ""
        cxp = x0 + advance(UP, last + "x", size) - advance(UP, "x", size) if last else x0
        cv.rect(cxp + 2, y0 + (len(lines) - 1) * lh - size * 0.8, 3, size * 1.05, (255, 138, 76), a, 1)


def s_viet(cv, t, D):
    a = fade(t, 0.1, D - 0.1, 0.7, 0.5)
    # cảnh này trùng cú đánh cao trào của nhạc: chữ bật vào nhanh, thu nhỏ nhẹ về kích thước chuẩn
    p = ease_out(prog(t, 0.0, 0.45))
    draw_text(cv, UP, "Tiếng Việt.", 190 * (1 + 0.07 * (1 - p)), W / 2, 520, wght=700, grad=GRAD,
              alpha=a * min(1, p * 1.6), blur=10 * (1 - p))
    p2 = ease_out(prog(t, 1.0, 0.9))
    draw_text(cv, IT, "Chữ đẹp là nết người.", 76, W / 2, 680, wght=400, alpha=a * p2)
    draw_text(cv, UP, "Every diacritic, in its place.", 40, W / 2, 820, color=GRAY, alpha=a * ease_out(prog(t, 2.0, 0.9)))


_ROWS = None


def glyph_rows():
    global _ROWS
    if _ROWS is None:
        rows = []
        per = 70
        for r in range(11):
            chars = "  ".join(GLYPHS[(r * per + i * 7) % len(GLYPHS)] for i in range(per))
            m, asc, adv, pad = text_mask(UP, chars, 58, 300)
            rows.append((m, asc))
        _ROWS = rows
    return _ROWS


def s_glyphs(cv, t, D):
    a = fade(t, 0.0, D - 0.1, 0.5, 0.5)
    for r, (m, asc) in enumerate(glyph_rows()):
        speed = 60 + 24 * (r % 4)
        x = -((t * speed + r * 137) % max(1, m.width - W - 10))
        cv.blit(m, int(x), int(60 + r * 92 - asc + 58), DIM, a)
    cv.rect(360, 390, 1200, 300, (0, 0, 0), a * 0.82, 40)
    p = ease_out(prog(t, 0.0, 0.8))
    draw_text(cv, UP, "1,073 characters.", 110, W / 2, 560, wght=700, alpha=a * p, blur=8 * (1 - p))
    draw_text(cv, UP, "Latin · Greek · Cyrillic · Vietnamese", 38, W / 2, 650, color=GRAY, alpha=a * ease_out(prog(t, 1.0, 0.8)))


def s_end(cv, t, D):
    out = 1 - ease_in_out(prog(t, D - 1.2, 1.1))
    p = ease_out(prog(t, 0.0, 1.2))
    draw_text(cv, UP, "Auvyx Mono", 170, W / 2, 560, wght=100 + 600 * ease_in_out(prog(t, 0.0, 2.0)),
              alpha=p * out, blur=14 * (1 - p))
    draw_text(cv, UP, "Free & open source.", 54, W / 2, 680, grad=GRAD, alpha=ease_out(prog(t, 2.0, 0.9)) * out)
    draw_text(cv, UP, "SIL Open Font License 1.1", 30, W / 2, 760, color=GRAY, alpha=ease_out(prog(t, 3.0, 0.9)) * out)
    draw_text(cv, UP, MUSIC_CREDIT, 22, W / 2, 1030, color=(90, 90, 96),
              alpha=ease_out(prog(t, 3.0, 0.9)) * out)


# (bắt đầu, kết thúc) của từng cảnh, tính bằng giây
SCENES = [(0, 6, s_intro), (6, 10, s_tagline), (10, 18, s_weights), (18, 24, s_italic), (24, 32, s_ligatures),
          (32, 40, s_code), (40, 46, s_viet), (46, 50, s_glyphs), (50, 56, s_end)]

# Nhạc: "Wildflowers" by Scott Buckley (CC BY 4.0), nhạc điện ảnh dàn dây + piano. Ghép 3 đoạn của bài:
#   A  mở đầu piano (0–40s của bài) chạy nguyên văn video 0–40s, tự dâng dần; lặng đi 0,7s trước cao trào
#   B  CAO TRÀO: cú đánh mạnh nhất của bài (giây 219.12) rơi đúng giây 40.0 của video — lúc hiện "Tiếng Việt."
#   C  HẠ MÀN: câu nhạc kết của bài (giây 305–313), câu cuối vào đúng lúc hiện màn kết (video 50s)
MUSIC = Path(__file__).parent / "music" / "scott-buckley-wildflowers.mp3"
CLIMAX_SONG, CLIMAX_VIDEO = 219.12, 40.0
HIT_XFADE = 0.25
OUTRO_SONG, OUTRO_VIDEO, OUTRO_XFADE = 305.0, 48.0, 2.0
MUSIC_CREDIT = "Music: Wildflowers by Scott Buckley · CC BY 4.0"


def frame(t: float) -> Canvas:
    cv = Canvas()
    for a, b, fn in SCENES:
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
            b_start = CLIMAX_SONG - HIT_XFADE                       # B vào lúc video CLIMAX_VIDEO - HIT_XFADE
            b_len = OUTRO_VIDEO + OUTRO_XFADE - (CLIMAX_VIDEO - HIT_XFADE)
            c_len = DURATION - OUTRO_VIDEO
            graph = (f"[1:a]atrim=0:{CLIMAX_VIDEO},asetpts=PTS-STARTPTS,"
                     f"volume=-4dB,afade=t=out:st={CLIMAX_VIDEO - 0.7}:d=0.7[a];"  # nhỏ hơn cao trào 4dB, lặng một nhịp thở trước cú đánh
                     f"[1:a]atrim={b_start}:{b_start + b_len},asetpts=PTS-STARTPTS[b];"
                     f"[1:a]atrim={OUTRO_SONG}:{OUTRO_SONG + c_len},asetpts=PTS-STARTPTS[c];"
                     f"[a][b]acrossfade=d={HIT_XFADE}:c1=tri:c2=tri[ab];"
                     f"[ab][c]acrossfade=d={OUTRO_XFADE}:c1=qsin:c2=qsin,"
                     f"afade=t=in:st=0:d=1.0,afade=t=out:st={DURATION - 3.0}:d=3.0")
            # đo độ lớn trước, rồi chuẩn hoá tuyến tính (giữ nguyên độ tương phản nhẹ → cao trào)
            meas = subprocess.run(["ffmpeg", "-hide_banner", "-f", "lavfi", "-i", "anullsrc", "-i", str(MUSIC),
                                   "-filter_complex", graph + ",loudnorm=I=-16:TP=-1.5:LRA=20:print_format=json[o]",
                                   "-map", "[o]", "-f", "null", "-"], capture_output=True, text=True).stderr
            m = json.loads(meas[meas.rindex("{"):meas.rindex("}") + 1])
            graph += (f",loudnorm=I=-16:TP=-1.5:LRA=20:linear=true:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
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

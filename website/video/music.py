"""Dựng nhạc nền cho video bằng numpy và tìm các nốt (onset) để hình cắt đúng nhịp.

Bài: "In the Remains of the Day" by Ethereal 88 (CC BY 4.0), 140 BPM.
  A  bài 0 → ô 24: piano mở đầu, beat vào ở ô 12
  B  4 ô sôi động cuối bài (ô 97 → nốt mạnh ở phách đầu ô 101)
  ✦  FERMATA: nốt mạnh ở phách đầu ô 101 (chỗ chính bài chuyển sang đoạn hạ màn) được giữ lại và ngân
     trong tiếng vang (reverb) tự nhiên ~2s — như khoảnh khắc mọi thứ lặng đi sau cao trào
  C  đoạn hạ màn piano tiếp tục, chậm dần (ritardando) cho tới nốt cuối, tan trong tiếng vang
"""
from __future__ import annotations

import subprocess
import wave

import numpy as np

SR = 44100
BPM = 140.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT
GRID0 = 0.421


def song_bar(b: float) -> float:
    return GRID0 + b * BAR


def decode(path: str, start: float | None = None, end: float | None = None, tempo: float | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start}"]
    if end is not None:
        cmd += ["-to", f"{end}"]
    cmd += ["-i", path]
    if tempo:
        cmd += ["-af", f"atempo={tempo}"]
    cmd += ["-f", "f32le", "-ac", "2", "-ar", str(SR), "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def onset_env(mono: np.ndarray, n=1024, hop=128):
    win = np.hanning(n).astype(np.float32)
    frames = (len(mono) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
    mag = np.log1p(np.abs(np.fft.rfft(mono[idx] * win, axis=1)))
    flux = np.maximum(0, np.diff(mag, axis=0)).sum(axis=1)
    times = (np.arange(1, frames) * hop + n / 2) / SR
    return times, flux


def detect_onsets(mono: np.ndarray, min_gap=0.06):
    """Onset = đỉnh của spectral flux vượt ngưỡng thích nghi. Độ mạnh chuẩn hoá theo vùng lân cận (±1,5s)."""
    t, f = onset_env(mono)
    fps = 1 / (t[1] - t[0])
    k = int(0.25 * fps)
    pad = np.pad(f, k, mode="edge")
    local_mean = np.convolve(pad, np.ones(2 * k + 1) / (2 * k + 1), "same")[k:-k]
    K = int(1.5 * fps)
    padK = np.pad(f, K, mode="edge")
    from numpy.lib.stride_tricks import sliding_window_view
    local_hi = np.percentile(sliding_window_view(padK, 2 * K + 1)[:: max(1, K // 8)], 95, axis=1)
    local_hi = np.interp(np.arange(len(f)), np.arange(len(local_hi)) * max(1, K // 8), local_hi) + 1e-6
    peaks, last = [], -1e9
    for i in range(1, len(f) - 1):
        if f[i] >= f[i - 1] and f[i] >= f[i + 1] and f[i] > local_mean[i] * 1.5 + 0.02 * local_hi[i]:
            if t[i] - last >= min_gap:
                peaks.append(i)
                last = t[i]
            elif f[i] > f[peaks[-1]]:
                peaks[-1] = i
                last = t[i]
    times = t[peaks]
    strength = np.clip(f[peaks] / local_hi[peaks], 0, 2)
    silent = np.array([np.sqrt(np.mean(mono[max(0, int(s * SR)): int(s * SR) + 2048] ** 2)) for s in times]) < 1e-3
    return times[~silent], strength[~silent]


def freeze(x: np.ndarray, at: float, length: float, n=4096, hop=1024, seed=7, ref: float | None = None) -> np.ndarray:
    """'Ngân' một nốt: giữ phổ biên độ của khung tại `at`, pha ngẫu nhiên mỗi khung → tiếng ngân liền mạch.
    Âm cao tắt nhanh hơn âm trầm (lọc dần) cho giống tiếng đàn tự nhiên tắt."""
    rng = np.random.default_rng(seed)
    i = int(at * SR)
    win = np.hanning(n).astype(np.float32)
    mag = np.abs(np.fft.rfft(x[i:i + n] * win[:, None], axis=0))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    frames = int(length * SR / hop) + 4
    out = np.zeros((frames * hop + n, 2), np.float32)
    for fr in range(frames):
        tt = fr * hop / SR
        cutoff = 9000 * (1400 / 9000) ** min(1, tt / length)          # 9 kHz → 1,4 kHz
        tilt = 1 / np.sqrt(1 + (freqs / cutoff) ** 4)
        spec = (mag * tilt[:, None]) * np.exp(1j * rng.uniform(0, 2 * np.pi, mag.shape))
        out[fr * hop: fr * hop + n] += np.fft.irfft(spec, n=n, axis=0).astype(np.float32) * win[:, None]
    if ref is None:
        ref = np.sqrt(np.mean(x[i:i + int(0.12 * SR)] ** 2))
    out *= ref / (np.sqrt(np.mean(out[n: n + int(0.3 * SR)] ** 2)) + 1e-9)
    return out[: int(length * SR)]


DRONE_HOLD = 0.7       # giây giữ nguyên độ lớn sau nốt dừng
DRONE_GAIN = 0.9       # so với độ lớn thân nốt dừng
PIANO_FREEZE_AT = 176.50   # giây trong bài: tiếng piano đệm (không trống/bass) cùng hợp âm với nốt dừng (tương đồng 0,98)


def drone_env(t, sustain):
    """Độ lớn tiếng ngân theo thời gian t (giây, tính từ nốt dừng): giữ, rồi tắt dần chậm → nhanh, -55 dB ở cuối."""
    u = np.clip((np.asarray(t, dtype=float) - DRONE_HOLD) / (sustain - DRONE_HOLD), 0, 1)
    return 10 ** (-55 * u ** 1.7 / 20)


def place(dst: np.ndarray, src: np.ndarray, at: float, fade_in=0.0, fade_out=0.0, gain=1.0):
    s = int(round(at * SR))
    src = src.copy() * gain
    if fade_in > 0:
        k = min(len(src), int(fade_in * SR))
        src[:k] *= np.sin(np.linspace(0, np.pi / 2, k))[:, None] ** 2
    if fade_out > 0:
        k = min(len(src), int(fade_out * SR))
        src[-k:] *= np.cos(np.linspace(0, np.pi / 2, k))[:, None] ** 2
    e = min(len(dst), s + len(src))
    dst[s:e] += src[: e - s]


def reverb_ir(rt60=2.8, length=3.2, seed=3, lp=5000.0) -> np.ndarray:
    """Tiếng vang tổng hợp: nhiễu giảm dần theo hàm mũ, hai kênh lệch nhau, cắt bớt âm cao."""
    rng = np.random.default_rng(seed)
    n = int(length * SR)
    t = np.arange(n) / SR
    env = 10 ** (-3 * t / rt60)
    ir = rng.standard_normal((n, 2)).astype(np.float32) * env[:, None]
    spec = np.fft.rfft(ir, axis=0)
    f = np.fft.rfftfreq(n, 1 / SR)
    spec *= (1 / np.sqrt(1 + (f / lp) ** 2))[:, None]
    ir = np.fft.irfft(spec, n=n, axis=0).astype(np.float32)
    ir[: int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))[:, None]   # pre-delay mềm
    return ir / np.sqrt((ir ** 2).sum(axis=0, keepdims=True))


def convolve(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    n = len(x) + len(ir) - 1
    N = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, N, axis=0) * np.fft.rfft(ir, N, axis=0), N, axis=0)[:n].astype(np.float32)


def fades(x, fin=0.0, fout=0.0):
    x = x.copy()
    if fin > 0:
        k = min(len(x), int(fin * SR))
        x[:k] *= np.linspace(0, 1, k)[:, None]
    if fout > 0:
        k = min(len(x), int(fout * SR))
        x[-k:] *= np.linspace(1, 0, k)[:, None]
    return x


def build(path: str, video_bar, out_wav: str, fermata=2.0, rit=(0.92, 0.6), max_dur=62.0):
    """Dựng nhạc; trả về dict (onsets, strengths, t_stop, c_start, duration)."""
    song = decode(path)
    s_t, s_f = detect_onsets(song.mean(axis=1))

    def nearest(t, win=0.08):
        m = np.abs(s_t - t) <= win
        return float(s_t[m][np.argmax(s_f[m])]) if m.any() else t

    XF = BEAT
    j = video_bar(24)
    b_song0 = song_bar(97)
    stop_song = nearest(song_bar(101))
    outro_notes = s_t[(s_t > stop_song + 0.1) & (s_t < 180.0)]
    next_song = float(outro_notes[0])
    off_b = j - b_song0
    t_stop = stop_song + off_b
    c_start = t_stop + fermata

    total = int(max_dur * SR) + SR
    mix = np.zeros((total, 2), np.float32)
    ir = reverb_ir()

    def put(x, at, gain=1.0):
        s0 = int(round(at * SR))
        e = min(total, s0 + len(x))
        mix[s0:e] += x[: e - s0] * gain

    # A + B (chỗ nối đúng vạch ô nhịp, hoà trộn 1 phách)
    A = song[: int((j + XF / 2) * SR)]
    k = int(XF * SR)
    A = A.copy()
    A[-k:] *= np.cos(np.linspace(0, np.pi / 2, k))[:, None] ** 2
    put(A, 0.0)
    B = song[int((b_song0 - XF / 2) * SR): int((next_song - 0.012) * SR)].copy()
    B[:k] *= np.sin(np.linspace(0, np.pi / 2, k))[:, None] ** 2
    B = fades(B, 0, 0.03)
    put(B, j - XF / 2)

    # FERMATA: tiếng vang của nốt dừng ngân tiếp trong khoảng lặng
    hit = fades(song[int((stop_song - 0.005) * SR): int((next_song - 0.012) * SR)], 0.003, 0.03)
    wet = convolve(hit, reverb_ir(rt60=4.2, length=4.5, seed=11, lp=4200))
    put(wet, t_stop - 0.005, gain=0.85)

    # C: đoạn hạ màn, chậm dần — chia theo các nốt, mỗi đoạn một tốc độ (giữ cao độ)
    cuts = [next_song] + [float(t) for t in outro_notes[8::8]] + [180.8]
    pieces, tempos = [], np.linspace(rit[0], rit[1], len(cuts) - 1)
    for (a, b), tp in zip(zip(cuts[:-1], cuts[1:]), tempos):
        pieces.append(decode(path, start=a - 0.004, end=b - 0.004, tempo=float(tp)))
    xf = int(0.012 * SR)
    C = pieces[0]
    for pc in pieces[1:]:
        C[-xf:] *= np.linspace(1, 0, xf)[:, None]
        pc = pc.copy()
        pc[:xf] *= np.linspace(0, 1, xf)[:, None]
        C = np.concatenate([C[:-xf], C[-xf:] + pc[:xf], pc[xf:]])
    C = fades(C, 0.004, 0.0)
    put(C, c_start)
    put(convolve(C, ir), c_start, gain=0.22)          # không gian cho piano, nốt cuối tan dần

    mono = np.abs(mix.mean(axis=1))
    lvl = np.convolve(mono, np.ones(2205) / 2205, "same")
    alive = np.nonzero(lvl > 10 ** (-66 / 20))[0]
    duration = min(max_dur, round((alive[-1] / SR) + 0.8, 2))
    mix = mix[: int(duration * SR)]
    fast = mix[int(21 * SR): int((t_stop - 1) * SR)]
    g = 10 ** (-16 / 20) / (np.sqrt(np.mean(fast ** 2)) + 1e-9)
    g = min(g, 10 ** (-1 / 20) / (np.abs(mix).max() + 1e-9))
    mix *= g
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    on_t, on_f = detect_onsets(mix.mean(axis=1))
    return {"onsets": on_t.tolist(), "strengths": on_f.tolist(), "t_stop": t_stop, "c_start": c_start,
            "duration": duration}

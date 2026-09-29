"""Dựng nhạc nền cho video bằng numpy và tìm các nốt (onset) để hình cắt đúng nhịp.

Bài: "In the Remains of the Day" by Ethereal 88 (CC BY 4.0), 140 BPM.
  A  bài 0 → ô 24: piano mở đầu, beat vào ở ô 12
  B  4 ô sôi động cuối bài (ô 97 → nốt mạnh ở phách đầu ô 101)
  ✦  NỐT DỪNG: nốt mạnh ở phách đầu ô 101 (~48,4s của video). Thân nốt được thay bằng tiếng piano đệm
     cùng hợp âm (lấy từ đoạn hạ màn, không có trống/bass), "ngân" bằng spectral freeze rồi tắt hẳn về im lặng
  C  đoạn hạ màn piano (các nốt sau đó tới hết bài), kéo chậm lại (giữ cao độ)
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


def build(path: str, video_bar, duration: float, out_wav: str, sustain=2.6, outro_start_gap=0.0):
    """Trả về dict: onsets (s), strengths, t_stop, c_start, tempo_c."""
    song = decode(path)
    mono = song.mean(axis=1)
    s_t, s_f = detect_onsets(mono)

    def nearest(t, win=0.08):
        m = np.abs(s_t - t) <= win
        return float(s_t[m][np.argmax(s_f[m])]) if m.any() else t

    XF = BEAT
    j = video_bar(24)
    b_song0 = song_bar(97)
    stop_song = nearest(song_bar(101))                    # nốt dừng (phách đầu ô 101 của bài)
    next_song = float(s_t[s_t > stop_song + 0.1][0])      # nốt piano kế tiếp = bắt đầu đoạn hạ màn
    off_b = j - b_song0                                    # video = bài + off_b trong đoạn B
    t_stop = stop_song + off_b
    c_start = t_stop + sustain + outro_start_gap
    song_end = 180.8
    tempo_c = (song_end - next_song) / (duration - c_start)

    mix = np.zeros((int(duration * SR) + SR, 2), np.float32)
    A = song[: int((j + XF / 2) * SR)]
    place(mix, A, 0.0, fade_out=XF)
    B = song[int((b_song0 - XF / 2) * SR): int((stop_song + 0.17) * SR)]
    place(mix, B, j - XF / 2, fade_in=XF, fade_out=0.05)
    # nốt ngân: vào từ 0,12s sau nốt dừng, giữ ~0,35s rồi tắt dần theo hàm mũ về -60 dB
    body = np.sqrt(np.mean(song[int((stop_song + 0.04) * SR): int((stop_song + 0.17) * SR)] ** 2))
    drone = freeze(song, PIANO_FREEZE_AT, sustain + 0.3, n=8192, hop=2048, ref=body)
    tt = np.arange(len(drone)) / SR + 0.12                 # thời gian tính từ nốt dừng
    drone *= drone_env(tt, sustain)[:, None].astype(np.float32)
    place(mix, drone, t_stop + 0.12, fade_in=0.08, gain=DRONE_GAIN)
    C = decode(path, start=next_song - 0.01, end=song_end, tempo=tempo_c)
    place(mix, C, c_start, fade_in=0.01)
    mix = mix[: int(duration * SR)]

    # chuẩn hoá: đoạn nhanh ~ -16 dBFS RMS, đỉnh không quá -1 dBFS
    fast = mix[int(21 * SR): int(47 * SR)]
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
            "tempo_c": tempo_c, "sustain": sustain}

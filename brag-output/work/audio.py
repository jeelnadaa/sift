"""Original score + effects + narration, mixed on one 120 BPM grid (A minor, Am-F-C-G).
Writes mix.wav (48 kHz stereo); loudness is normalised with ffmpeg afterwards."""
import json
import wave

import numpy as np

SR, DUR = 48000, 32.0
N = int(SR * DUR)
BEAT = 0.5
rng = np.random.default_rng(3)
t_all = np.arange(N) / SR


def hz(m):  # midi -> Hz
    return 440.0 * 2 ** ((m - 69) / 12)


def lp(x, cut):  # one-pole low-pass (cut may be an array)
    a = np.exp(-2 * np.pi * np.broadcast_to(cut, x.shape) / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a[i]) * x[i] + a[i] * acc
        y[i] = acc
    return y


def lp_fast(x, cut):
    from scipy.signal import lfilter
    if np.ndim(cut) == 0:
        a = np.exp(-2 * np.pi * cut / SR)
        return lfilter([1 - a], [1, -a], x)
    cut = np.broadcast_to(cut, x.shape)
    y, zi = np.empty_like(x), np.zeros(1)
    for i in range(0, len(x), 256):  # time-varying cutoff, block by block
        a = np.exp(-2 * np.pi * cut[i] / SR)
        y[i:i + 256], zi = lfilter([1 - a], [1, -a], x[i:i + 256], zi=zi * 1.0)
    return y


try:
    import scipy.signal  # noqa: F401
    LP = lp_fast
except ImportError:
    LP = lambda x, c: lp(x, c)  # noqa: E731


def hp(x, cut):
    return x - LP(x, cut)


def add(buf, sig, at, gain=1.0, pan=0.0):
    i = int(round(at * SR))
    if i >= N:
        return
    j = min(N, i + len(sig))
    if i < 0:
        sig, i = sig[-i:], 0
    l, r = np.sqrt(0.5 * (1 - pan)), np.sqrt(0.5 * (1 + pan))
    buf[0, i:j] += sig[: j - i] * gain * l * 1.414
    buf[1, i:j] += sig[: j - i] * gain * r * 1.414


def env(n, a, d):  # attack seconds, exponential decay time constant
    tt = np.arange(n) / SR
    return np.minimum(tt / max(a, 1e-4), 1) * np.exp(-tt / d)


# chords per bar (2 s): Am F C G, voiced around A3
CH = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]
ROOT = [45, 41, 48, 43]

music = np.zeros((2, N))
sfx = np.zeros((2, N))

# ---- pad: detuned saws, filtered, swells over the film
pad = np.zeros((2, N))
for bar in range(16):
    ch = CH[bar % 4]
    n = int(2.4 * SR)
    tt = np.arange(n) / SR
    s = np.zeros(n)
    for m in ch + [ch[0] + 12]:
        for det, ph in ((-0.08, 0.0), (0.08, 1.3)):
            f = hz(m + det)
            s += ((tt * f + ph) % 1.0 * 2 - 1) * 0.12
    e = np.minimum(tt / 0.35, 1) * np.clip((2.4 - tt) / 0.4, 0, 1)
    s = LP(s * e, 1400)
    add(pad, s, bar * 2.0, 0.55, pan=-0.25 if bar % 2 else 0.25)
padlev = np.interp(t_all, [0, 4, 8, 25.5, 28.5, 31, 32], [0.55, 0.7, 0.5, 0.55, 0.9, 0.8, 0])
music += pad * padlev

# ---- pluck arpeggio on 8ths (0.25 s)
pat = [0, 1, 2, 3, 2, 1, 2, 3]
for k in range(int(30.0 / 0.25)):
    at = k * 0.25
    bar = int(at // 2)
    if 25.5 <= at < 28.5 and k % 2:
        continue  # thinner before the lockup
    ch = CH[bar % 4]
    notes = ch + [ch[0] + 12]
    m = notes[pat[k % 8]] + 12
    n = int(0.6 * SR)
    tt = np.arange(n) / SR
    f = hz(m)
    s = (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(4 * np.pi * f * tt) + 0.15 * np.sin(6 * np.pi * f * tt)) * env(n, 0.003, 0.16)
    cut = 1800 if at < 4 else 3200 if at < 8 else 4200
    s = LP(s, cut)
    g = 0.16 if at < 8 else 0.2
    add(music, s, at, g, pan=0.35 if k % 2 else -0.35)

# ---- kick, every beat from the reveal to the outro, and the lockup hit
kick = np.zeros((2, N))
def kick_at(at, g=1.0):
    n = int(0.45 * SR)
    tt = np.arange(n) / SR
    f = 45 + 85 * np.exp(-tt / 0.03)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) * np.exp(-tt / 0.13) + 0.25 * rng.standard_normal(n) * np.exp(-tt / 0.004)
    add(kick, s, at, 0.85 * g)
beats = [b * BEAT for b in range(int(4.0 / BEAT), int(25.5 / BEAT))]
for at in beats:
    kick_at(at)
kick_at(28.5, 1.25)
music += kick

# sidechain pump: everything but the kick ducks after each kick
pump = np.ones(N)
for at in beats + [28.5]:
    i = int(at * SR); n = int(0.4 * SR)
    j = min(N, i + n)
    pump[i:j] = np.minimum(pump[i:j], 1 - 0.45 * np.exp(-np.arange(j - i) / SR / 0.09))

# ---- sub bass on 8ths (root), from the reveal
bass = np.zeros((2, N))
for k in range(int(4.0 / 0.25), int(25.5 / 0.25)):
    at = k * 0.25
    bar = int(at // 2)
    m = ROOT[bar % 4] - 12 + (12 if k % 4 == 3 else 0)
    n = int(0.24 * SR)
    tt = np.arange(n) / SR
    f = hz(m)
    s = np.tanh(1.6 * np.sin(2 * np.pi * f * tt)) * np.minimum(tt / 0.005, 1) * np.clip((0.24 - tt) / 0.03, 0, 1)
    add(bass, LP(s, 600), at, 0.32 if at >= 8 else 0.22)
# sustained root under the lockup
n = int(3.5 * SR); tt = np.arange(n) / SR
add(bass, LP(np.sin(2 * np.pi * hz(33) * tt) * env(n, 0.01, 1.4), 400), 28.5, 0.5)
music += bass

# ---- hats (offbeat 8ths) and soft claps on 2 and 4, in the busy middle
for k in range(int(8.0 / 0.25), int(25.5 / 0.25)):
    at = k * 0.25
    if k % 2 == 1:
        n = int(0.06 * SR)
        s = hp(rng.standard_normal(n), 7000) * env(n, 0.001, 0.018)
        add(music, s, at, 0.07, pan=0.3)
for b in range(int(8.0 / BEAT), int(25.5 / BEAT)):
    if b % 2 == 1:
        n = int(0.25 * SR)
        s = LP(hp(rng.standard_normal(n), 900), 4000) * env(n, 0.002, 0.06)
        add(music, s, b * BEAT, 0.12, pan=-0.1)

# ---- riser into the outro
n = int(2.0 * SR); tt = np.arange(n) / SR
rs = rng.standard_normal(n)
rs = LP(hp(rs, 300), 300 + 5000 * (tt / 2.0) ** 2) * (tt / 2.0) ** 2
add(music, rs, 23.5, 0.35)

music *= pump  # pump the bed (kick included: tiny, keeps its punch)

# ---- effects, all on the grid
def whoosh(at, g=0.35):  # swells into the cut at `at`
    n = int(0.7 * SR); tt = np.arange(n) / SR
    s = rng.standard_normal(n)
    cut = 400 + 3800 * np.sin(np.pi * np.clip(tt / 0.7, 0, 1))
    s = LP(hp(s, 200), cut.mean()) * np.sin(np.pi * tt / 0.7) ** 2
    add(sfx, s, at - 0.5, g)
for c in (4.0, 8.0, 14.0, 17.5, 20.5, 25.5):
    whoosh(c)

def tick(at, g=0.12, m=81):
    n = int(0.08 * SR); tt = np.arange(n) / SR
    add(sfx, np.sin(2 * np.pi * hz(m) * tt) * env(n, 0.001, 0.02), at, g, pan=rng.uniform(-0.3, 0.3))
for i in range(6):
    tick(8.5 + i * 0.125, 0.09, [81, 84, 88, 84, 81, 76][i])
for i in range(3):
    tick(9.875 + i * 0.125, 0.07, 69)
tick(15.75, 0.12, 93); tick(24.25, 0.12, 93)   # clicks
tick(21.0, 0.1, 88); tick(23.375, 0.1, 88)      # taps
for i in range(4):
    tick(14.5 + i * 0.375 if i < 3 else 16.0, 0.08, [76, 81, 84, 88][i])

def shimmer(at, g=0.12):
    for j, m in enumerate([81, 84, 88, 93, 96]):
        n = int(1.6 * SR); tt = np.arange(n) / SR
        s = (np.sin(2 * np.pi * hz(m) * tt) + 0.2 * np.sin(2 * np.pi * hz(m) * 2.01 * tt)) * env(n, 0.002, 0.5)
        add(sfx, s, at + j * 0.0625, g, pan=-0.5 + j * 0.25)
shimmer(4.0); shimmer(28.5, 0.14)

# phone buzz (two short pulses on the grid)
for at in (6.5, 6.75):
    n = int(0.18 * SR); tt = np.arange(n) / SR
    s = np.sign(np.sin(2 * np.pi * 160 * tt)) * np.sin(np.pi * tt / 0.18)
    add(sfx, LP(s, 900), at, 0.12)

# sync zip: a quick rising glide, phone -> web
n = int(0.5 * SR); tt = np.arange(n) / SR
f = hz(81) * 2 ** (tt / 0.5)
s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * tt / 0.5) ** 2
add(sfx, s, 21.375, 0.08)

# ---- narration: placed at its scene offsets, lightly compressed
VO = {"hook": 0.2, "reveal": 4.2, "rules": 8.2, "timeline": 14.2, "live": 20.6, "outro": 25.8}
vo = np.zeros(N)
for key, at in VO.items():
    with wave.open(f"vo_{key}.wav") as w:
        assert w.getframerate() == SR
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768
    x = x / (np.abs(x).max() + 1e-9) * 0.9
    i = int(at * SR)
    vo[i:i + len(x)] += x[: N - i]
# soft compressor (RMS follower), then a touch of warmth
lvl = np.sqrt(LP(vo ** 2, 12) + 1e-9)
gain = np.where(lvl > 0.12, (0.12 / lvl) ** 0.5, 1.0)
vo = vo * gain
vo = vo + 0.15 * LP(vo, 250)

# duck the bed under the voice
venv = LP(np.abs(vo), 6)
duck = 1 - 0.55 * np.clip(venv / (venv.max() * 0.35), 0, 1)
bed = (music + sfx * 0.9) * duck
bedg = np.interp(t_all, [0, 3.9, 4.3, 25.4, 25.8, 30.7, 31], [0.6, 0.6, 0.33, 0.33, 0.4, 0.4, 0.62])
bed = bed * bedg
mix = bed + np.stack([vo, vo]) * 1.0

# gentle fade at the very end
fade = np.clip((DUR - t_all) / 1.2, 0, 1)
mix *= fade
mix /= np.abs(mix).max() / 0.89
with wave.open("mix.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix.T * 32767).astype(np.int16).tobytes())
print("wrote mix.wav")

if __name__ == "__main__":
    sc = 0.89 / np.abs(bed + np.stack([vo, vo])).max()
    for name, sig in (("bed", bed * sc), ("vo", vo * sc)):
        for a, b in [(0.2, 3.8), (8.2, 13.6), (20.6, 25), (25.8, 30.6)]:
            s = sig[..., int(a * SR):int(b * SR)]
            print(name, a, round(20 * np.log10(np.sqrt((s ** 2).mean()) + 1e-9), 1))

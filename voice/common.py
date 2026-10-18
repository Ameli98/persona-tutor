"""Shared pieces of the voice pipeline: where a voice's files live, the clip table, audio helpers.

A voice lives in data/voices/<name>/:
  clips/*.wav        mono 32 kHz clips, silence-trimmed (ingest)
  clips.csv          one row per clip: text, checks, emotion, ...   (every step adds columns)
  review.json        your reference-clip decisions from the review page
  refs/<emotion>/    approved reference clips + refs.list           (what the tutor reads)
  train.list         GPT-SoVITS training list
  sovits.pth, gpt.ckpt   trained weights (train)
"""
import csv
import re
import subprocess
import wave
from pathlib import Path

import numpy as np

from tutor.backend import settings as settings_mod

SR = 32000
MIN_S, MAX_S = 3.0, 10.0          # clip length GPT-SoVITS trains well on
EMOTIONS = ["neutral", "happy", "angry", "sad", "shy", "surprised"]
# trim leading/trailing silence below -45 dB, keep ~80 ms of padding
TRIM = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse,"
        "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse")
PUNCT = re.compile(r"[\s、。，．・…‥！？!?「」『』（）()―─～〜“”\"'.,;:\-]")
MUFFLED_DB = -30.0  # energy above 4 kHz vs full band; normal speech ≈ -17 dB, through-a-door ≈ -35 dB


def voice_dir(name: str) -> Path:
    s = settings_mod.load()
    d = s.data / "voices" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_clips(d: Path) -> list[dict]:
    f = d / "clips.csv"
    return list(csv.DictReader(open(f, encoding="utf-8"))) if f.exists() else []


def write_clips(d: Path, rows: list[dict]):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    tmp = d / "clips.csv.tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(d / "clips.csv")


def ffmpeg_clip(src: Path, dst: Path, start: float | None = None, end: float | None = None) -> float:
    """Cut [start, end] (whole file if None), trim silence, convert to mono 32 kHz 16-bit. Returns duration."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}", "-to", f"{end:.3f}"]
    cmd += ["-i", str(src), "-af", TRIM, "-ac", "1", "-ar", str(SR), "-sample_fmt", "s16", str(dst)]
    subprocess.run(cmd, check=True)
    return duration(dst)


def duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def peak_and_clipping(path: Path) -> tuple[float, int]:
    with wave.open(str(path)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.int32)
    peak = int(np.abs(a).max()) if len(a) else 0
    return 20 * np.log10(max(peak, 1) / 32768), int((np.abs(a) >= 32700).sum())


def hf_db(path: Path) -> float:
    """Energy above 4 kHz relative to the full band; very low = muffled (through a door, a phone, ...)."""
    def rms(af):
        out = subprocess.run(["ffmpeg", "-nostdin", "-i", str(path), "-af", af + "astats=metadata=0:measure_perchannel=none",
                              "-f", "null", "-"], capture_output=True, text=True).stderr
        return float(re.findall(r"RMS level dB: (-?[\d.]+|-inf)", out)[-1].replace("-inf", "-120"))
    return rms("highpass=f=4000:poles=2,highpass=f=4000:poles=2,") - rms("")


def core_len(text: str) -> int:
    """Length of the text without punctuation/spaces (characters; words count as their letters)."""
    return len(PUNCT.sub("", text))


def normalize_text(text: str) -> str:
    """Text as GPT-SoVITS should read it: no brackets, collapsed ellipses."""
    t = re.sub(r"[『』「」（）()\[\]]", "", text)
    t = re.sub(r"…+|‥+|\.{3,}", "…", t)
    return t.strip()


class Progress:
    """One self-updating line: "transcribing  150/343  44%  ~2 min left". When the output isn't a terminal
    (a log file), it prints a line every 10% instead."""

    def __init__(self, label: str, total: int):
        import sys
        import time
        self.label, self.total, self.done = label, max(total, 1), 0
        self.t0, self.time, self.out = time.time(), time.time, sys.stdout
        self.tty = sys.stdout.isatty()
        self._last_decile = -1
        self._show()

    def step(self, n: int = 1):
        self.done = min(self.total, self.done + n)
        self._show()
        if self.done == self.total and self.tty:
            self.out.write("\n")

    def _show(self):
        pct = 100 * self.done // self.total
        elapsed = self.time() - self.t0
        left = elapsed / self.done * (self.total - self.done) if self.done else None
        eta = "" if left is None or self.done == self.total else \
            (f"  ~{left / 60:.0f} min left" if left >= 90 else f"  ~{left:.0f} s left")
        line = f"{self.label}  {self.done}/{self.total}  {pct}%{eta}"
        if self.tty:
            self.out.write("\r" + line.ljust(60))
            self.out.flush()
        elif pct // 10 != self._last_decile:
            self._last_decile = pct // 10
            print(line, flush=True)


def quietly(fn, *args, **kwargs):
    """Run fn with its console output captured — model libraries print hundreds of lines of harmless
    messages (FunASR's "miss key in ckpt", GPT-SoVITS's per-sentence text dumps). Shown only if fn fails."""
    import contextlib
    import io
    import logging
    buf = io.StringIO()
    level = logging.root.level
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            logging.root.setLevel(logging.ERROR)
            return fn(*args, **kwargs)
    except Exception:
        print(buf.getvalue()[-4000:])
        raise
    finally:
        logging.root.setLevel(level)

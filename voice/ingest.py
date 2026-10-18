"""Step 1: turn a folder of recordings into clean 3–10 s clips.

  python -m voice.ingest <voice name> <folder> [--transcripts lines.csv]

- Any format ffmpeg reads (wav, mp3, m4a, flac, ogg, …; video files give their audio track).
- Short files (≤ 13 s) become one clip each.
- Longer recordings (a podcast, a reading session, ...) are cut at pauses found by voice activity
  detection, joining speech separated by short pauses up to 10 s.
- Transcripts (optional, for short files whose exact text you know) are picked up automatically:
  transcripts.csv / metadata.csv / *.list in the folder, or a <name>.txt next to each audio file;
  --transcripts FILE to point at one elsewhere. Without them the text comes from Whisper.
Writes data/voices/<name>/clips/*.wav and clips.csv (re-running replaces them; review.json is kept).
"""
import argparse
import csv
import re
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .common import MAX_S, MIN_S, ffmpeg_clip, probe_duration, voice_dir, write_clips

# anything ffmpeg reads; video files contribute their audio track
AUDIO_EXT = {".wav", ".mp3", ".ogg", ".oga", ".flac", ".m4a", ".aac", ".opus", ".webm", ".wma", ".aif", ".aiff",
             ".amr", ".3gp", ".caf", ".mp4", ".mov", ".mkv", ".avi"}
SHORT_S = MAX_S + 3     # a file this short is one utterance; trimming will bring it under MAX_S
PHRASE_GAP = 0.35       # a silence at least this long separates two speech regions (s)
JOIN_GAP = 0.6          # regions are joined into one clip only across pauses up to this (s)
SHORT_JOIN_GAP = 1.0    # ...or up to this when one side is too short to keep on its own (s)
PAD = 0.15              # keep a little audio around each cut (s)


def safe_id(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    return re.sub(r"[^\w\-]+", "_", str(rel)).strip("_")


TRANSCRIPT_FILES = ("transcripts.csv", "transcripts.tsv", "metadata.csv", "transcripts.txt")


def _key(name: str) -> str:
    """Match transcript entries by file name without extension, so `clip01`, `clip01.wav` and `sub/clip01.ogg` agree."""
    return Path(name.strip()).with_suffix("").name if Path(name.strip()).suffix.lower() in AUDIO_EXT \
        else Path(name.strip()).name


def load_transcripts(path: Path) -> dict:
    """{file key: text} from common transcript layouts:
      - CSV/TSV with a header naming the columns (file/path/audio/wav/name/id and text/transcript/sentence)
      - two or more columns without a header: first = file, last = text (comma, tab or | separated;
        LJSpeech metadata.csv `id|text|normalized` takes the middle column)
      - GPT-SoVITS .list: path|speaker|language|text
    """
    raw = path.read_text(encoding="utf-8-sig")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return {}
    if path.suffix.lower() == ".list":
        return {_key(ln.split("|")[0]): ln.split("|", 3)[3] for ln in lines if ln.count("|") >= 3}
    delim = max(("|", "\t", ","), key=lambda d: lines[0].count(d))
    rows = list(csv.reader(lines, delimiter=delim))
    head = [c.strip().lower() for c in rows[0]]
    file_cols = [i for i, c in enumerate(head) if c in ("file", "filename", "path", "audio", "wav", "name", "id")]
    text_cols = [i for i, c in enumerate(head) if c in ("text", "transcript", "transcription", "sentence", "line")]
    if file_cols and text_cols:
        fi, ti, rows = file_cols[0], text_cols[0], rows[1:]
    else:  # no header: first column is the file; LJSpeech-style 3 columns use the raw text (middle)
        fi, ti = 0, (1 if len(rows[0]) == 3 and delim == "|" else -1)
    return {_key(r[fi]): r[ti].strip() for r in rows if len(r) >= 2 and r[ti].strip()}


def find_transcripts(root: Path, explicit: str | None) -> tuple[dict, str]:
    """An explicit --transcripts file, else a known transcript file or a .list in the folder, plus
    sidecar <name>.txt files next to the audio. Returns ({key: text}, description)."""
    found, used = {}, []
    candidates = [Path(explicit)] if explicit else \
        [root / n for n in TRANSCRIPT_FILES if (root / n).exists()] + sorted(root.glob("*.list"))
    for f in candidates[:1]:
        found.update(load_transcripts(f))
        used.append(f.name)
    sidecars = {p for p in root.rglob("*.txt") if p.name not in TRANSCRIPT_FILES}
    n_side = 0
    for t in sidecars:
        if any(t.with_suffix(ext).exists() for ext in AUDIO_EXT) and t.stem not in found:
            found[t.stem] = t.read_text(encoding="utf-8-sig").strip()
            n_side += 1
    if n_side:
        used.append(f"{n_side} .txt files next to the audio")
    return found, " + ".join(used)


def segment(path: Path) -> list[tuple[float, float]]:
    """Cut a long recording into clips at real pauses, found by voice activity detection (Silero VAD,
    bundled with faster-whisper) on the audio itself — Whisper's own timestamps stretch into silences.
    Speech regions separated by pauses ≤ JOIN_GAP are joined while the clip stays ≤ MAX_S.
    The text comes later, from transcribing each clip (voice.check)."""
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    audio = decode_audio(str(path), sampling_rate=16000)
    opts = VadOptions(min_silence_duration_ms=int(PHRASE_GAP * 1000), speech_pad_ms=0, max_speech_duration_s=MAX_S)
    regions = [(r["start"] / 16000, r["end"] / 16000) for r in get_speech_timestamps(audio, opts)]
    return merge_regions(regions)


def merge_regions(regions: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Speech regions (seconds) → clip spans: join across short pauses, rescue too-short pieces, keep 3–10 s."""
    chunks, cur = [], None
    for a, b in regions:
        if cur and a - cur[1] <= JOIN_GAP and b - cur[0] <= MAX_S - 2 * PAD:
            cur = (cur[0], b)
        else:
            if cur:
                chunks.append(cur)
            cur = (a, b)
    if cur:
        chunks.append(cur)
    # a piece too short to train on may join its nearer neighbour across a longer pause
    # (a line with a dramatic pause in the middle), as long as the result still fits
    i = 0
    while i < len(chunks):
        a, b = chunks[i]
        if b - a + 2 * PAD < MIN_S:
            gaps = [(a - chunks[i - 1][1], i - 1) if i > 0 else (99, -1),
                    (chunks[i + 1][0] - b, i + 1) if i + 1 < len(chunks) else (99, -1)]
            gap, j = min(gaps)
            lo, hi = min(i, j), max(i, j)
            if j >= 0 and gap <= SHORT_JOIN_GAP and chunks[hi][1] - chunks[lo][0] <= MAX_S - 2 * PAD:
                chunks[lo:hi + 1] = [(chunks[lo][0], chunks[hi][1])]
                i = lo
                continue
        i += 1
    return [(a, b) for a, b in chunks if MIN_S <= b - a + 2 * PAD <= MAX_S]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="voice name, e.g. tutor")
    ap.add_argument("folder", help="folder with your recordings (searched recursively)")
    ap.add_argument("--transcripts", help="transcript file (CSV/TSV/.list); default: found in the folder")
    args = ap.parse_args()
    root = Path(args.folder).resolve()
    d = voice_dir(args.name)
    if (d / "clips.csv").exists():  # re-running replaces the clips; the later steps are simply run again
        keep = " Your reference decisions (review.json) are kept." if (d / "review.json").exists() else ""
        print(f"replacing the existing clips of '{args.name}' — run check, emotion and select again afterwards.{keep}")
    shutil.rmtree(d / "clips", ignore_errors=True)
    (d / "clips").mkdir()
    texts, source = find_transcripts(root, args.transcripts)

    everything = [p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")]
    files = sorted(p for p in everything if p.suffix.lower() in AUDIO_EXT)
    skipped = Counter(p.suffix.lower() or "(no extension)" for p in everything
                      if p.suffix.lower() not in AUDIO_EXT and p.suffix.lower() not in (".csv", ".tsv", ".txt", ".list"))
    if skipped:
        print("skipped (not audio): " + ", ".join(f"{n} {ext}" for ext, n in skipped.most_common()))
    if not files:
        raise SystemExit(f"no audio files under {root} (formats: {' '.join(sorted(AUDIO_EXT))})")
    durs = dict(zip(files, ThreadPoolExecutor(8).map(probe_duration, files)))
    short = [f for f in files if durs[f] <= SHORT_S]
    long = [f for f in files if durs[f] > SHORT_S]
    print(f"{len(files)} files, {sum(durs.values()) / 60:.1f} min: {len(short)} short, {len(long)} long recordings")
    if texts:
        matched = sum(1 for f in short if f.stem in texts)
        print(f"transcripts: {source} — {matched} of {len(short)} short files matched"
              + ("" if matched == len(short) else "; the rest are transcribed by Whisper"))
    else:
        print("transcripts: none found — Whisper will transcribe every clip")

    rows = []

    def one(f):
        cid = safe_id(f, root)
        out = d / "clips" / f"{cid}.wav"
        dur = ffmpeg_clip(f, out)
        text = texts.get(f.stem, "")
        return {"id": cid, "file": f"clips/{cid}.wav", "source": str(f.relative_to(root)), "start": "", "end": "",
                "dur": f"{dur:.3f}", "text": text, "text_src": "given" if text else ""}

    rows += list(ThreadPoolExecutor(8).map(one, short))
    for f in long:
        base = safe_id(f, root)
        chunks = segment(f)
        for k, (a, b) in enumerate(chunks):
            cid = f"{base}_{k:04d}"
            dur = ffmpeg_clip(f, d / "clips" / f"{cid}.wav", max(0.0, a - PAD), b + PAD)
            rows.append({"id": cid, "file": f"clips/{cid}.wav", "source": str(f.relative_to(root)),
                         "start": f"{a:.2f}", "end": f"{b:.2f}", "dur": f"{dur:.3f}", "text": "", "text_src": ""})
        print(f"  {f.name}: {len(chunks)} clips")
    write_clips(d, rows)
    usable = [r for r in rows if MIN_S <= float(r["dur"]) <= MAX_S]
    print(f"wrote {len(rows)} clips ({sum(float(r['dur']) for r in usable) / 60:.1f} min within {MIN_S:.0f}–{MAX_S:.0f} s) "
          f"to {d}\nnext: python -m voice.check {args.name}")


if __name__ == "__main__":
    main()

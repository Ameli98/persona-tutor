"""Step 2: check every clip — does the audio say its text? is it usable for training?

  python -m voice.check <voice name>

Transcribes each clip with Whisper. Clips with a given transcript are compared by pronunciation (so
spelling choices don't count); a large mismatch means the transcript belongs to another file. Clips
without one take Whisper's text. Then flags anything that would hurt training: wrong length, too
little text, very slow speech (breaths, long pauses), muffled audio, clipping.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor

from tutor.backend import settings as settings_mod

from .common import (MAX_S, MIN_S, MUFFLED_DB, Progress, core_len, hf_db, peak_and_clipping, read_clips,
                     voice_dir, write_clips)

MISMATCH_CER = 0.30   # reading error rate above which a given transcript is treated as wrong
SLOW_RATE = 2.5       # readings per second (morae for Japanese) below which a clip is mostly pauses


def flags_for(r: dict, lang) -> list[str]:
    f = []
    dur, text = float(r["dur"]), r["text"]
    if r.get("text_src") == "given" and float(r.get("cer") or 0) > MISMATCH_CER:
        f.append("mismatch")
    if dur < MIN_S:
        f.append("too_short")
    if dur > MAX_S:
        f.append("too_long")
    n = core_len(text)
    if n == 0:
        f.append("no_text")
    elif n < 5:
        f.append("text_short")
    units = len(lang.reading(text)) or n
    if n and units / max(dur, 0.1) < SLOW_RATE:
        f.append("slow_or_nonspeech")
    if float(r["hf_db"]) < MUFFLED_DB:
        f.append("muffled")
    if int(r["clipped"]) > 50:
        f.append("clipping")
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    args = ap.parse_args()
    s = settings_mod.load()
    d = voice_dir(args.name)
    rows = read_clips(d)
    if not rows:
        raise SystemExit(f"no clips in {d}; run python -m voice.ingest first")

    def audio_stats(r):
        p = d / r["file"]
        peak, clipped = peak_and_clipping(p)
        r.update(peak_db=f"{peak:.1f}", clipped=str(clipped), hf_db=f"{hf_db(p):.1f}")

    bar = Progress("measuring audio", len(rows))
    for _ in ThreadPoolExecutor(8).map(audio_stats, rows):
        bar.step()

    from faster_whisper import WhisperModel
    model = WhisperModel(s.cfg["stt"]["model"], device="cuda", compute_type=s.cfg["stt"]["compute_type"])
    bar = Progress("transcribing", len(rows))
    for r in rows:
        segs, _ = model.transcribe(str(d / r["file"]), language=s.lang.CODE, beam_size=5,
                                   without_timestamps=True, condition_on_previous_text=False)
        r["asr"] = "".join(x.text for x in segs).strip()
        if r.get("text_src") == "given":
            r["cer"] = f"{s.lang.compare(r['text'], r['asr'])['cer']:.3f}"
        else:
            r["text"], r["text_src"], r["cer"] = r["asr"], "asr", ""
        r["flags"] = ";".join(flags_for(r, s.lang))
        bar.step()
    write_clips(d, rows)

    from collections import Counter
    ok = [r for r in rows if not r["flags"]]
    print(f"usable: {len(ok)}/{len(rows)} clips, {sum(float(r['dur']) for r in ok) / 60:.1f} min")
    print("flags:", dict(Counter(f for r in rows for f in r["flags"].split(";") if f)))
    print(f"next: python -m voice.emotion {args.name}")


if __name__ == "__main__":
    main()

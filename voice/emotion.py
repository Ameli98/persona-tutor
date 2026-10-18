"""Step 3: label each usable clip with an emotion (neutral / happy / angry / sad / shy / surprised).

  python -m voice.emotion <voice name> [--no-llm]

Measured on a hand-checked set of acted Japanese lines, a speech-emotion model alone agreed with a
human listener only ~28% of the time (it hears expressive acting as "surprised"), the transcript alone
~67%, and both together ~77%. So each clip's transcript goes to the feedback LLM together with how its
voice differs from this speaker's usual voice:
  - emotion2vec+ scores (https://github.com/ddlBoJack/emotion2vec, FunASR model licence), relative to the speaker
  - pitch, pitch range, loudness and speaking rate, relative to the speaker
The LLM also says whether the line carries its emotion without any story context — the property a good
reference clip needs. You confirm the reference clips by ear afterwards (python -m voice.review).
--no-llm (or no API key): every clip starts as "neutral" and you label references on the review page.
"""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from tutor.backend import settings as settings_mod
from tutor.backend.llm import LLMError, make_llm

from .common import EMOTIONS, Progress, quietly, read_clips, voice_dir, write_clips

SER_MODEL = "emotion2vec/emotion2vec_plus_large"
SER_LABELS = ["angry", "disgusted", "fearful", "happy", "neutral", "other", "sad", "surprised", "unknown"]
SER_USED = [0, 2, 3, 4, 6, 7]   # skip disgusted / other / unknown when describing the voice
BATCH = 60

SCHEMA = {"type": "object", "properties": {"labels": {"type": "array", "items": {"type": "object", "properties": {
    "i": {"type": "integer"}, "emotion": {"type": "string", "enum": EMOTIONS},
    "standalone": {"type": "boolean"}}, "required": ["i", "emotion", "standalone"], "additionalProperties": False}}},
    "required": ["labels"], "additionalProperties": False}

SYSTEM = """Each numbered item is one recorded line from a single speaker, with no surrounding context: the transcript, then measurements of the voice compared with this speaker's usual voice (the acoustic model is unreliable on its own).
For each, choose the emotion the voice most likely carries: neutral, happy, angry, sad, shy (embarrassed/flustered), surprised. Weigh the wording and the voice together; calm statements are neutral.
standalone: true if a listener with no context would clearly hear that emotion from this line alone (the wording supports it), false if it depends on the story around it.
Output JSON only."""


def prosody(path: str) -> list[float]:
    import warnings
    warnings.filterwarnings("ignore")  # librosa warns about short clips; the numbers are still fine
    import librosa
    y, sr = librosa.load(path, sr=16000)
    f0, _, _ = librosa.pyin(y, fmin=70, fmax=800, sr=sr, frame_length=1024)
    f0 = f0[~np.isnan(f0)]
    rms = librosa.feature.rms(y=y)[0]
    if not len(f0):
        return [np.nan, np.nan, 20 * np.log10(np.mean(rms) + 1e-9)]
    return [float(np.median(f0)), float(np.percentile(f0, 90) - np.percentile(f0, 10)), 20 * np.log10(np.mean(rms) + 1e-9)]


def relative(x: np.ndarray) -> np.ndarray:
    """Robust z-score against this speaker's own clips."""
    med = np.nanmedian(x, 0)
    iqr = np.nanpercentile(x, 75, 0) - np.nanpercentile(x, 25, 0)
    return (x - med) / np.where(iqr > 0, iqr, 1)


def word(z: float) -> str:
    if np.isnan(z):
        return "unknown"
    return ("much lower" if z < -1 else "lower" if z < -0.35 else "much higher" if z > 1
            else "higher" if z > 0.35 else "typical")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--no-llm", action="store_true", help="skip the LLM; label references by hand on the review page")
    args = ap.parse_args()
    s = settings_mod.load()
    d = voice_dir(args.name)
    rows = read_clips(d)
    todo = [r for r in rows if not r.get("flags")]
    if not todo:
        raise SystemExit("no usable clips; run python -m voice.check first")

    llm = None
    if not args.no_llm:
        try:
            llm = make_llm(s.cfg["llm"]["feedback"])
        except LLMError as e:
            print(f"no LLM ({e}); every clip starts as neutral — label the references on the review page")
    if llm is None:
        for r in todo:
            r.update(emotion="neutral", emotion_src="none", standalone="")
        write_clips(d, rows)
        return

    bar, pro, scores = Progress("voice features", 2 * len(todo)), [], []
    # pitch/loudness in worker processes, before the model touches CUDA (forking after that can crash them).
    # One clip first in this process: librosa's numba code compiles and writes its disk cache once here;
    # eight workers compiling at the same time can write a corrupt cache that segfaults every later run.
    prosody(str(d / todo[0]["file"]))
    with ProcessPoolExecutor(8) as ex:
        for x in ex.map(prosody, [str(d / r["file"]) for r in todo]):
            pro.append(x)
            bar.step()
    pro = np.array(pro)
    print("\nloading the emotion model (the first run downloads ~1 GB)…", flush=True)
    from funasr import AutoModel  # noqa: E402 (slow import; only when needed)
    ser = quietly(AutoModel, model=SER_MODEL, hub="hf", disable_update=True, log_level="ERROR")
    import logging
    logging.getLogger("httpx").setLevel(logging.WARNING)  # funasr turns on INFO logging: one line per LLM request
    for r in todo:
        scores.append(quietly(ser.generate, str(d / r["file"]), granularity="utterance", disable_pbar=True)[0]["scores"])
        bar.step()
    P = np.array(scores)
    rate = np.array([(len(s.lang.reading(r["text"])) or len(r["text"])) / float(r["dur"]) for r in todo])
    Z = relative(np.c_[pro, rate])
    Pz = relative(P)

    def describe(i):
        top = sorted(((Pz[i, k], SER_LABELS[k]) for k in SER_USED), reverse=True)[:2]
        return (f"pitch {word(Z[i, 0])}, pitch range {word(Z[i, 1])}, loudness {word(Z[i, 2])}, "
                f"speaking rate {word(Z[i, 3])}; acoustic model leans (relative to this speaker): {top[0][1]}, then {top[1][1]}")

    cost = 0.0
    bar = Progress("labelling (LLM)", len(todo))
    for start in range(0, len(todo), BATCH):
        idx = range(start, min(start + BATCH, len(todo)))
        msg = "\n".join(f"{j}. 「{todo[i]['text']}」 — {describe(i)}" for j, i in enumerate(idx))
        out, c = llm.json_with_cost(SYSTEM, [{"role": "user", "content": msg}], SCHEMA, 8000)
        cost += c
        got = {x["i"]: x for x in out["labels"]}
        for j, i in enumerate(idx):
            x = got.get(j, {"emotion": "neutral", "standalone": False})
            todo[i].update(emotion=x["emotion"], emotion_src="auto", standalone=str(bool(x["standalone"])).lower())
        bar.step(len(idx))
    for i, r in enumerate(todo):
        r["ser"] = json.dumps({SER_LABELS[k]: round(float(P[i, k]), 3) for k in SER_USED})
    write_clips(d, rows)

    from collections import Counter
    print("emotions:", dict(Counter(r["emotion"] for r in todo)), f"cost ${cost:.3f}")
    print(f"next: python -m voice.select {args.name}")


if __name__ == "__main__":
    main()

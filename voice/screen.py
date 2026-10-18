"""Step 7 (after training): test every reference clip with the trained voice.

  python -m voice.screen <voice name>

A bad reference makes the model mumble or re-read the reference's own text ("prompt leakage"). For each
clip in refs.list this synthesizes two test sentences with it and transcribes them; clips whose output is
misread get a warning on the review page (reject them there and write the references again).
Stop the tutor first (GPU memory).
"""
import argparse
import tempfile
from pathlib import Path

from tutor.backend import settings as settings_mod
from tutor.backend.stt import STT

from .common import Progress, quietly, read_clips, voice_dir
from .select import load_review, save_review

BAD_CER = 0.15


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    args = ap.parse_args()
    s = settings_mod.load()
    d = voice_dir(args.name)
    if not (d / "sovits.pth").exists():
        raise SystemExit("no trained weights; run python -m voice.train first")
    tests = [w["text"] for w in s.warmup_pool()[:2]]
    if not tests:
        raise SystemExit(f"no test sentences: add tutor/lang/{s.lang.CODE}_warmup.yaml")
    refs = [ln.rstrip("\n").split("|") for ln in open(d / "refs" / "refs.list", encoding="utf-8")]
    print(f"loading the trained voice '{args.name}'…", flush=True)
    stt = quietly(STT, s.cfg["stt"]["model"], s.cfg["stt"]["compute_type"], s.lang.CODE, s.native_whisper)
    from tutor.backend.tts import TTS, Ref
    tts = quietly(TTS, settings_mod.path(s.cfg["paths"]["gsv_root"]), d / "sovits.pth", d / "gpt.ckpt",
                  d / "refs" / "refs.list", s.cfg["tts"]["version"], s.lang)
    review = load_review(d)
    review["screen"] = {}
    tmp = Path(tempfile.mkdtemp())
    ids = {r["id"] for r in read_clips(d)}
    bar, bad = Progress("testing references", len(refs)), []
    for path, _, _, text in refs:
        cid = Path(path).stem
        cers = []
        for k, sentence in enumerate(tests):
            out = quietly(tts._synth_once, sentence, Ref(path, text), 42 + k, tmp / f"{k}.wav")
            cers.append(s.lang.compare(sentence, quietly(stt.transcribe, out))["cer"])
        ref_cer = s.lang.compare(text, quietly(stt.transcribe, Path(path)))["cer"]
        is_bad = max(cers) > BAD_CER
        if cid in ids:
            review["screen"][cid] = {"test_cer": round(max(cers), 3), "ref_cer": round(ref_cer, 3), "bad": is_bad}
        if is_bad:
            bad.append(f"  ⚠ {Path(path).parent.name:9} {cid}  reading errors {max(cers):.0%}  「{text[:30]}」")
        bar.step()
    save_review(d, review)
    if bad:
        print("\n".join(bad))
        print(f"{len(bad)} of {len(refs)} references made the voice misread — reject them on the review page "
              f"(they're marked there), then press \"Write references\":\nnext: python -m voice.review {args.name}")
    else:
        print(f"all {len(refs)} references passed.\nnext: ./run.sh  → http://localhost:{s.cfg['server']['port']}")


if __name__ == "__main__":
    main()

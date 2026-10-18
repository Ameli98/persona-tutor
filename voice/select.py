"""Step 4: choose the training set and the reference-clip candidates.

  python -m voice.select <voice name> [--minutes 25] [--speaker NAME]

Training set: up to --minutes of usable clips, balanced across emotions (neutral-heavy keeps the
timbre stable) and spread across source recordings. Reference candidates: per emotion, clips that
carry their emotion without context ("standalone"), 4–8 s long, at a normal speaking rate.
Your decisions from the review page (review.json) are kept: kept clips stay, rejected clips never return.
Writes train.list, review.json (candidates) and refs/ (a first set you can refine by ear).
"""
import argparse
import json
import shutil
from collections import defaultdict

from tutor.backend import settings as settings_mod

from .common import EMOTIONS, core_len, normalize_text, read_clips, voice_dir

# share of the training minutes per emotion
QUOTA = {"neutral": 0.36, "happy": 0.20, "shy": 0.16, "sad": 0.12, "surprised": 0.10, "angry": 0.06}
REFS_PER_EMOTION = 8
CANDIDATES_PER_EMOTION = 12


def rate(r: dict, lang) -> float:
    return (len(lang.reading(r["text"])) or core_len(r["text"])) / float(r["dur"])


def spread(rows: list[dict], key) -> list[dict]:
    """Sort by key, then round-robin across source recordings for variety."""
    by_src = defaultdict(list)
    for r in sorted(rows, key=key):
        by_src[r["source"]].append(r)
    out, queues = [], list(by_src.values())
    while queues:
        queues = [q for q in queues if q]
        for q in queues:
            out.append(q.pop(0))
    return out


def load_review(d) -> dict:
    f = d / "review.json"
    r = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    r.setdefault("decisions", {})   # clip id -> {"status": "keep"|"reject", "emotion": override or None}
    r.setdefault("candidates", {})  # emotion -> [clip ids]
    return r


def save_review(d, review: dict):
    (d / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")


def emotion_of(r: dict, review: dict) -> str:
    dec = review["decisions"].get(r["id"], {})
    return dec.get("emotion") or r.get("emotion") or "neutral"


def apply_refs(d, rows: list[dict], review: dict, speaker: str, lang_code: str) -> dict:
    """refs/<emotion>/*.wav + refs.list: kept clips first, then undecided candidates, up to REFS_PER_EMOTION."""
    by_id = {r["id"]: r for r in rows}
    dec = review["decisions"]
    picked = {}
    for emo in EMOTIONS:
        kept = [i for i, x in dec.items() if x.get("status") == "keep" and i in by_id and emotion_of(by_id[i], review) == emo]
        rest = [i for i in review["candidates"].get(emo, []) if i not in dec and emotion_of(by_id[i], review) == emo]
        picked[emo] = (kept + rest)[:REFS_PER_EMOTION]
    root = d / "refs"
    shutil.rmtree(root, ignore_errors=True)
    lines = []
    for emo, ids in picked.items():
        (root / emo).mkdir(parents=True, exist_ok=True)
        for i in ids:
            dst = root / emo / f"{i}.wav"
            shutil.copy2(d / by_id[i]["file"], dst)
            lines.append(f"{dst}|{speaker}|{lang_code}|{normalize_text(by_id[i]['text'])}\n")
    (root / "refs.list").write_text("".join(lines), encoding="utf-8")
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--minutes", type=float, default=25)
    ap.add_argument("--speaker", help="speaker name written in the lists (default: the voice name)")
    args = ap.parse_args()
    s = settings_mod.load()
    d = voice_dir(args.name)
    speaker = args.speaker or args.name
    rows = read_clips(d)
    usable = [r for r in rows if not r.get("flags") and r.get("text")]
    if not usable:
        raise SystemExit("no usable clips; run voice.check (and voice.emotion) first")
    review = load_review(d)
    rejected = {i for i, x in review["decisions"].items() if x.get("status") == "reject"}

    # --- training set: emotion quotas; an emotion that runs short hands its minutes to neutral
    target = min(args.minutes * 60, sum(float(r["dur"]) for r in usable))
    by_emo = defaultdict(list)
    for r in usable:
        by_emo[emotion_of(r, review)].append(r)
    chosen, spare = [], 0.0
    for emo, share in sorted(QUOTA.items(), key=lambda kv: kv[0] == "neutral"):  # neutral last, takes the spare
        budget, got = target * share + (spare if emo == "neutral" else 0), 0.0
        for r in spread(by_emo.get(emo, []), key=lambda r: -rate(r, s.lang)):
            if got >= budget:
                break
            chosen.append(r)
            got += float(r["dur"])
        spare += max(0.0, budget - got) if emo != "neutral" else 0
    have = {r["id"] for r in chosen}
    for r in usable:  # top up (e.g. little neutral material) until the target is reached
        if sum(float(x["dur"]) for x in chosen) >= target:
            break
        if r["id"] not in have:
            chosen.append(r)
    with open(d / "train.list", "w", encoding="utf-8") as fp:
        for r in sorted(chosen, key=lambda r: r["id"]):
            fp.write(f"{d / r['file']}|{speaker}|{s.lang.CODE}|{normalize_text(r['text'])}\n")

    # --- reference candidates
    for emo in EMOTIONS:
        c = [r for r in by_emo.get(emo, []) if r["id"] not in rejected and 4.0 <= float(r["dur"]) <= 8.0
             and 4.0 <= rate(r, s.lang) <= 11.0]
        ranked = spread(c, key=lambda r: (r.get("standalone") != "true", abs(float(r["dur"]) - 6.0)))
        review["candidates"][emo] = [r["id"] for r in ranked[:CANDIDATES_PER_EMOTION]]
    save_review(d, review)
    picked = apply_refs(d, rows, review, speaker, s.lang.CODE)

    total = sum(float(r["dur"]) for r in chosen)
    print(f"train.list: {len(chosen)} clips, {total / 60:.1f} min")
    for emo in EMOTIONS:
        n = sum(1 for r in chosen if emotion_of(r, review) == emo)
        print(f"  {emo:9} train {n:4d}   refs {len(picked[emo])}   candidates {len(review['candidates'][emo])}")
    print(f"next: listen to the references — python -m voice.review {args.name}")


if __name__ == "__main__":
    main()

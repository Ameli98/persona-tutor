"""After a session: corrected + upgraded versions of every user line, 3–5 key expressions, and which of the
lesson's phrases the learner used."""
import json
import re
import time
from pathlib import Path

from . import lesson as lesson_mod
from .settings import Settings

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "turns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "corrected": {"type": "string"},
                    "corrected_reason": {"type": "string"},
                    "upgraded": {"type": "string"},
                    "upgrade_note": {"type": "string"},
                    "translation": {"type": "string"},
                    "emotion": {"type": "string", "enum": ["neutral", "happy", "angry", "sad", "shy", "surprised"]},
                },
                "required": ["index", "corrected", "corrected_reason", "upgraded", "upgrade_note", "translation", "emotion"],
                "additionalProperties": False,
            },
        },
        "expressions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "said": {"type": "string"},
                    "better": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["said", "better", "reason"],
                "additionalProperties": False,
            },
        },
        "lesson_use": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "used": {"type": "boolean"},
                    "correct": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["item", "used", "correct", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["turns", "expressions", "lesson_use"],
    "additionalProperties": False,
}


def review_system(s: Settings, lesson: dict | None = None) -> str:
    t, n = s.target, s.native
    items = lesson_mod.items(lesson) if lesson else []
    lesson_rule = ("lesson_use: before this conversation the learner studied these, one entry each, in this order:\n" +
                   "\n".join(f"  - {x}" for x in items) +
                   f"\n  used = they said it (or a natural form of it) on their own; correct = used it correctly; note = one short"
                   f" line in {n} (how they used it, or a moment where it would have fit). Unused items: correct=false.\n"
                   ) if items else "lesson_use: an empty array (there was no lesson).\n"
    return f"""You are a {t} speaking coach doing an after-practice review with the learner (native language {n}; {t} level: {s.level}).
Below is the transcript of their conversation with their tutor, {s.persona['name']}. Each learner line is numbered [U<n>].
The learner's lines come from speech recognition (ASR): usually no punctuation, occasionally misrecognised words. Do not comment on punctuation or sentence breaks, and do not count likely recognition errors (homophones, wrong characters) as the learner's mistakes. Add natural punctuation to the corrected and model versions.
For every learner line produce:

- corrected: the corrected version. Keep the learner's own words and content as much as possible; fix only unnatural wording, particles/function words, register mixing, written style in speech, literal translations from {n}, redundancy.
  If the line is already natural, copy it and leave corrected_reason empty; otherwise corrected_reason = one sentence in {n}.
  If the line is in {n} (they asked a question in their own language), corrected = how to ask it naturally in {t}, and corrected_reason says so.
- upgraded: a model answer. Keep their meaning and stance, but say it the way a native speaker would in this situation: fuller (reasons, concrete examples, responding to what the other person said), natural spoken {s.lang.REGISTER}, 1–3 sentences, not too long.
  upgrade_note: one sentence in {n} on what the model answer adds and why it is better.
- translation: the upgraded version translated into {n}.
- emotion: the natural tone of this line in the conversation (neutral/happy/angry/sad/shy/surprised); it decides the voice and expression in the review video.
  Plain answers and explanations are neutral (the default; a polite tone alone is not happy); happy only for real enjoyment or excitement in the line; being praised or talking about oneself with embarrassment is shy; trouble, failure or apologising is sad; complaining or protesting is angry; surprised only when actually surprised.
- index: the matching U number. Exactly one entry per learner line, in order.

expressions: pick 3–5 expressions most worth remembering from the whole conversation. Prefer places where the learner actually said something wrong or unnatural that they will need again
(said = what they said, better = the natural version, reason = one sentence in {n}); if there are fewer than 3 real problems, add useful phrases from the model answers (said = their simpler original wording).
{lesson_rule}corrected_reason, upgrade_note, translation, reason and note are always written in {n} ({t} words may be quoted inside the explanation).
Output JSON only."""


def _explanations_in_native(s: Settings, out: dict) -> bool:
    """False if the explanation fields drifted into the target language (it happens)."""
    texts = [t["corrected_reason"] for t in out["turns"]] + [t["upgrade_note"] for t in out["turns"]] + \
            [e["reason"] for e in out["expressions"]] + [u["note"] for u in out.get("lesson_use", [])]
    return all(s.lang.script_ratio(x) < 0.3 for x in texts if x)  # per field: one drifted note is enough


def _bare(text: str) -> str:
    return re.sub(r"[\s、。，,.！？!?「」…]", "", text)


def transcript_for_review(session: dict, tutor_name: str) -> tuple[str, list[int]]:
    lines, user_idx = [], []
    for i, t in enumerate(session["turns"]):
        if t["role"] == "tutor":
            lines.append(f"{tutor_name}: {t['text']}")
        else:
            n = len(user_idx)
            user_idx.append(i)
            note = ""
            if t.get("feedback") and not t["feedback"].get("natural", True):
                note = f" (live feedback suggested: {t['feedback']['natural_rewrite']})"
            lines.append(f"[U{n}] Learner: {t['text']}{note}")
    return "\n".join(lines), user_idx


def build_review(llm, s: Settings, session_dir: Path) -> tuple[dict, float]:
    session = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    text, user_idx = transcript_for_review(session, s.persona["name"])
    if not user_idx:
        raise ValueError("no user turns to review")
    system = review_system(s, session.get("lesson"))
    out, cost = llm.json_with_cost(system, [{"role": "user", "content": text}], REVIEW_SCHEMA, 16000)
    if not _explanations_in_native(s, out):
        retry = text + f"\n\n(The explanation fields must be written in {s.native}.)"
        out, cost2 = llm.json_with_cost(system, [{"role": "user", "content": retry}], REVIEW_SCHEMA, 16000)
        cost += cost2
    # attach to the user turns by position
    by_n = {r["index"]: r for r in out["turns"]}
    for n, ti in enumerate(user_idx):
        r = by_n.get(n)
        if r and _bare(r["corrected"]) == _bare(session["turns"][ti]["text"]):
            r["corrected_reason"] = ""  # unchanged (only punctuation added): no note, even if the model wrote one
    for n, ti in enumerate(user_idx):
        r = by_n.get(n)
        if r:
            session["turns"][ti]["review"] = {k: r[k] for k in
                                              ("corrected", "corrected_reason", "upgraded", "upgrade_note", "translation", "emotion")}
    review = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "cost_usd": round(cost, 4),
              "expressions": out["expressions"], "lesson_use": out["lesson_use"] if session.get("lesson") else [],
              "session": session}
    (session_dir / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
    return review, cost


def append_log(progress_root: Path, session_dir: Path, review: dict):
    """<data_dir>/log.json: key expressions across sessions (reviewed at the start of the next one)."""
    path = progress_root / "log.json"
    log = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"sessions": []}
    s = review["session"]
    log["sessions"] = [e for e in log["sessions"] if e["dir"] != session_dir.name]
    log["sessions"].append({"dir": session_dir.name, "date": s["started"], "scenario": s["scenario"]["title"],
                            "expressions": review["expressions"]})
    path.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def _read_log(progress_root: Path) -> dict:
    path = progress_root / "log.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"sessions": []}


def latest_recap(progress_root: Path) -> dict | None:
    """The most recent session's key expressions, reviewed at the start of the next practice."""
    sessions = [e for e in _read_log(progress_root)["sessions"] if e.get("expressions")]
    return sessions[-1] if sessions else None


def mark_recap(progress_root: Path, session_dir: str, index: int, score: int | None):
    """Record one recall attempt on an expression (kept for later, e.g. Anki scheduling)."""
    log = _read_log(progress_root)
    for e in log["sessions"]:
        if e["dir"] == session_dir and 0 <= index < len(e["expressions"]):
            e["expressions"][index].setdefault("reviews", []).append(
                {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "score": score})
            (progress_root / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
            return True
    return False

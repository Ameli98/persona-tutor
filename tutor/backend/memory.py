"""What the tutor remembers about the learner across sessions: <data_dir>/learner.json.

Updated by the review LLM after every reviewed session, editable on the page, and put into the tutor's and the
lesson's prompts. A profile summary rather than retrieval over old transcripts: a learner produces a few hundred
sessions a year at most, and what personalisation needs (level, recurring mistakes, what was covered, personal
things to follow up on) is a summary, not a search hit.
"""
import json
import time
from pathlib import Path

from .settings import Settings

# field → (max items, what it holds); "level" is free text, the others are lists of short lines
FIELDS = {
    "level": (None, "an assessment of the learner's current level: what they handle well, what they still avoid or get wrong"),
    "errors": (10, "recurring mistakes, most important first, each with a short example and how often it has come up"),
    "mastered": (30, "phrases and patterns the learner now uses correctly (practise these less)"),
    "topics": (15, "topics covered, newest first: date, topic and one line on what the learner talked about"),
    "about": (20, "things the learner told about themselves worth remembering: work, interests, plans, recent events"),
}

MEMORY_SCHEMA = {
    "type": "object",
    "properties": {"level": {"type": "string"},
                   **{k: {"type": "array", "items": {"type": "string"}} for k in FIELDS if k != "level"}},
    "required": list(FIELDS),
    "additionalProperties": False,
}


def path(data: Path) -> Path:
    return data / "learner.json"


def load(data: Path) -> dict:
    mem = json.loads(path(data).read_text(encoding="utf-8")) if path(data).exists() else {}
    return {"level": mem.get("level", ""), **{k: list(mem.get(k, [])) for k in FIELDS if k != "level"},
            "updated": mem.get("updated")}


def save(data: Path, mem: dict) -> dict:
    """Keeps only the known fields, trims blank lines and caps list lengths."""
    out = {"level": str(mem.get("level", "")).strip()}
    for k, (cap, _) in FIELDS.items():
        if k != "level":
            out[k] = [str(x).strip() for x in mem.get(k, []) if str(x).strip()][:cap]
    out["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = path(data).with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path(data))
    return out


def is_empty(mem: dict) -> bool:
    return not mem.get("level") and not any(mem.get(k) for k in FIELDS if k != "level")


def brief(mem: dict) -> str:
    """The memory as prompt text ("" when there is nothing yet)."""
    if is_empty(mem):
        return ""
    parts = [f"Level: {mem['level']}"] if mem.get("level") else []
    names = {"errors": "Recurring mistakes", "mastered": "Already comfortable with", "topics": "Topics covered before",
             "about": "About them"}
    for k, name in names.items():
        if mem.get(k):
            parts.append(f"{name}:\n" + "\n".join(f"  - {x}" for x in mem[k]))
    return "\n".join(parts)


def update_system(s: Settings) -> str:
    t, n = s.target, s.native
    fields = "\n".join(f"- {k}: {desc}" + (f" (at most {cap})" if cap else "") for k, (cap, desc) in FIELDS.items())
    return f"""You keep the learning record of a {t} learner (native language {n}; self-described level: {s.level}).
You get the current record and the review of the session they just finished (their lines with corrections, and,
when there was a lesson, whether they used its phrases). Return the updated record:
{fields}
Rules:
- The current record may contain the learner's own edits: keep its content unless this session clearly shows
  otherwise. Merge rather than rewrite; update counts on mistakes that came up again.
- Move a mistake to mastered only after the learner got it right without help; drop mastered items they got wrong.
- Base everything on what the learner actually said; don't guess. Likely speech-recognition errors are not mistakes.
- Write in {n}; quote {t} words and phrases as they are. One short line per item.
Output JSON only."""


def update(llm, s: Settings, data: Path, review: dict) -> tuple[dict, float]:
    """Fold a reviewed session into learner.json. Returns (new memory, cost)."""
    mem = load(data)
    sess = review["session"]
    lines = []
    for t in sess["turns"]:
        if t["role"] == "tutor":
            lines.append(f"Tutor: {t['text']}")
            continue
        rv = t.get("review") or {}
        fb = t.get("feedback") or {}
        if fb.get("dismissed") or fb.get("verdict") == "misheard":
            fix = " (not a mistake: the learner said so, or speech recognition misheard it)"
        else:
            fix = f" → corrected: {rv['corrected']} ({rv['corrected_reason']})" if rv.get("corrected_reason") else " (natural)"
        lines.append(f"Learner: {t['text']}{fix}")
    use = review.get("lesson_use") or []
    lesson = "\n".join(f"- {u['item']}: {'used' if u['used'] else 'not used'}"
                       f"{(', correct' if u['correct'] else ', incorrect') if u['used'] else ''}"
                       f"{' — ' + u['note'] if u.get('note') else ''}" for u in use)
    record = {k: mem[k] for k in FIELDS}
    msg = (f"Current record:\n{json.dumps(record, ensure_ascii=False, indent=1)}\n\n"
           f"Session {sess['started'][:10]}, topic: {sess['scenario']['title']}\n" + "\n".join(lines) +
           (f"\n\nLesson phrases:\n{lesson}" if lesson else ""))
    out, cost = llm.json_with_cost(update_system(s), [{"role": "user", "content": msg}], MEMORY_SCHEMA, 4000)
    return save(data, out), cost

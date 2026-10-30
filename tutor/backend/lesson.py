"""A 2–3 minute lesson before the conversation: the phrases, one grammar point, a model dialogue and (when it
matters) a cultural note for today's topic, pitched at the learner's level from their memory. The conversation
then steers towards these phrases and the review checks which ones the learner actually used."""
import json
import time
from pathlib import Path

from . import memory
from .settings import Settings

LESSON_SCHEMA = {
    "type": "object",
    "properties": {
        "phrases": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "translation": {"type": "string"}, "note": {"type": "string"}},
            "required": ["text", "translation", "note"], "additionalProperties": False}},
        "grammar": {"type": "object", "properties": {
            "point": {"type": "string"}, "explanation": {"type": "string"},
            "examples": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "translation": {"type": "string"}},
                "required": ["text", "translation"], "additionalProperties": False}}},
            "required": ["point", "explanation", "examples"], "additionalProperties": False},
        "dialogue": {"type": "array", "items": {"type": "object", "properties": {
            "speaker": {"type": "string", "enum": ["tutor", "learner"]},
            "text": {"type": "string"}, "translation": {"type": "string"}},
            "required": ["speaker", "text", "translation"], "additionalProperties": False}},
        "culture": {"type": "string"},
    },
    "required": ["phrases", "grammar", "dialogue", "culture"],
    "additionalProperties": False,
}


def passage_rules(s: Settings, passage: str) -> str:
    n = s.native
    return f"""
Today's lesson comes from a text the learner chose themselves. The scene:
---
{passage}
---
Teach from this scene:
- phrases: only 3–5, taken from the scene (lightly adapted is fine), the ones most useful at this learner's level. Leave out the rest, however interesting: they aren't expected to learn every hard word.
- Fiction often has speech nobody uses in real life: a character's special way of talking (〜ですわ, 〜じゃ and the like), old-fashioned or very rude wording. If you teach one, its note must say so in {n} and give the everyday way to say it. Don't present it as normal speech.
- dialogue: the tutor and the learner talking about this scene, each as themselves; they are not acting it out.
- culture: anything in the scene a learner would miss, or "".
"""


def lesson_system(s: Settings, scenario: dict, mem: dict, passage: str = "") -> str:
    t, n = s.target, s.native
    remembered = memory.brief(mem)
    minutes = s.cfg.get("session", {}).get("minutes", 5)
    guide = memory.band_guide(s, mem)
    guide = f"\nWhat suits this level: {guide}. Don't spend the lesson on what is well below it, even if the topic is simple: teach a more advanced way to talk about it.\n" if guide else ""
    return f"""You are a {t} teacher preparing a short lesson (2–3 minutes to read) right before a {minutes:g}-minute speaking practice.
The learner's native language is {n}; their {t} level: {s.level}. {s.learner}
{f"What you know from earlier sessions:{chr(10)}{remembered}{chr(10)}" if remembered else ""}
Today's topic: {scenario['title']}
Setting: {scenario['setting']}
Practice goal: {scenario['goal']}
{passage_rules(s, passage) if passage else ""}
Teach what the learner needs to *say* in this conversation, at their level:{guide}
- phrases: 5–8 phrases or chunks they will actually use when talking about this topic, in
  {s.speech}. Prefer things they don't know yet over things listed as already comfortable. note = one short
  line in {n} on usage or nuance ("" if nothing to add).
- grammar: one standard pattern that helps here; if one of their recurring mistakes fits the topic, teach that.
  explanation = 2–3 sentences in {n}; 2 example sentences.
- dialogue: 4–6 lines between the tutor ({s.persona['name']}) and the learner showing the phrases in use; the
  learner's lines are what they could say in the practice. Short, natural, spoken.
- culture: one or two sentences in {n} when there is a cultural or situational point a learner would miss
  (how direct to be, what is polite here); otherwise "".
translations are in {n}. Output JSON only."""


def make(llm, s: Settings, scenario: dict, data, passage: str = "") -> tuple[dict, float]:
    mem = memory.load(data)
    out, cost = llm.json_with_cost(lesson_system(s, scenario, mem, passage),
                                   [{"role": "user", "content": "(Prepare today's lesson.)"}], LESSON_SCHEMA, 4000)
    if passage:
        out["passage"] = passage
    return out, cost


def save(data: Path, lid: str, scenario: dict, lesson: dict):
    """<data_dir>/lessons/<YYYYmmdd-HHMMSS>_<id>.json, for the page's past-lessons list."""
    d = data / "lessons"
    d.mkdir(parents=True, exist_ok=True)
    rec = {"id": lid, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
           "scenario": {k: scenario.get(k) for k in ("id", "title", "titles")}, "lesson": lesson}
    (d / f"{time.strftime('%Y%m%d-%H%M%S')}_{lid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1),
                                                                     encoding="utf-8")


def saved(data: Path) -> list[dict]:
    """Past lessons, newest first."""
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted((data / "lessons").glob("*.json"), reverse=True)]


def items(lesson: dict) -> list[str]:
    """What the conversation should practise and the review checks: the phrases and the grammar point."""
    return [p["text"] for p in lesson.get("phrases", [])] + \
        ([lesson["grammar"]["point"]] if lesson.get("grammar", {}).get("point") else [])


def spoken(lesson: dict) -> list[str]:
    """Every line the lesson page has a play button for."""
    return [x["text"] for x in lesson.get("phrases", []) + lesson.get("grammar", {}).get("examples", []) + lesson.get("dialogue", [])]


def brief(lesson: dict) -> str:
    """The lesson as prompt text for the tutor."""
    phrases = "\n".join(f"  - {p['text']}" for p in lesson.get("phrases", []))
    g = lesson.get("grammar", {})
    scene = f"\nThe scene it comes from:\n{lesson['passage']}" if lesson.get("passage") else ""
    return f"Phrases:\n{phrases}\nGrammar point: {g.get('point', '')}{scene}"

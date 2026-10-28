"""Prompts and JSON schemas for the tutor's LLM calls.

Everything learner- or language-specific comes from Settings (config.yaml, the persona file and the
target-language module), so the same prompts work for any persona / target / native language.
"""
from . import lesson as lesson_mod
from . import memory
from .settings import Settings

EMOTIONS = ["neutral", "happy", "angry", "sad", "shy", "surprised"]

REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "emotion": {"type": "string", "enum": EMOTIONS},
        "text": {"type": "string"},
        "translation": {"type": "string"},
        "note": {"type": "string"},
        "hints": {"type": "array", "items": {"type": "string"}},
        "closing": {"type": "boolean"},
    },
    "required": ["emotion", "text", "translation", "note", "hints", "closing"],
    "additionalProperties": False,
}

FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "natural": {"type": "boolean"},
        "natural_rewrite": {"type": "string"},
        "feedback": {"type": "string"},
    },
    "required": ["natural", "natural_rewrite", "feedback"],
    "additionalProperties": False,
}

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "reading": {"type": "string"},
        "meaning": {"type": "string"},
        "usage": {"type": "string"},
        "example": {"type": "string"},
    },
    "required": ["reading", "meaning", "usage", "example"],
    "additionalProperties": False,
}

REPHRASE_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


def persona_brief(s: Settings) -> str:
    p = s.persona
    parts = [f"Name: {p['name']}"] + [f"{k.capitalize()}: {p[k].strip()}" for k in ("profile", "personality", "speech")
                                      if p.get(k)]
    return "\n".join(parts)


def learner_brief(s: Settings) -> str:
    """Who the learner is comes only from config.yaml (learner.profile) — nothing about them is assumed here."""
    return f"The learner's native language is {s.native}; their {s.target} level: {s.level}. {s.learner}".strip()


def memory_section(mem: dict | None) -> str:
    remembered = memory.brief(mem or {})
    if not remembered:
        return ""
    return f"""
What you remember about the learner from earlier sessions (keep it in mind; never recite it):
{remembered}
Use it like a friend who remembers: pitch your language at their level; when it fits, ask questions that give them
a chance to use what they get wrong (never point the mistake out); bring up things they told you before when
relevant (ask how a plan went, follow up on news); don't repeat a topic angle they have already covered.
"""


def lesson_section(lesson: dict | None) -> str:
    if not lesson:
        return ""
    return f"""
Just before this conversation the learner studied a short lesson for today's topic:
{lesson_mod.brief(lesson)}
This practice is short and is for using that lesson: ask questions that call for these phrases and the grammar
point, one or two at a time, so the learner gets to say most of them. Stay on today's topic.
"""


def reply_system(s: Settings, scenario: dict, mem: dict | None = None, lesson: dict | None = None) -> str:
    angles = "\n".join(f"  - {a}" for a in scenario.get("angles", []))
    t, n = s.target, s.native
    return f"""You are playing this character:
{persona_brief(s)}

You are the learner's {t} speaking tutor. {learner_brief(s)}
{memory_section(mem)}{lesson_section(lesson)}
Today's topic: {scenario['title']}
Setting: {scenario['setting']}
Practice goal: {scenario['goal']}
Directions you can take it:
{angles}

Conversation rules:
- You lead the topic and ask follow-up questions. Dig into what the learner just said (reasons, concrete examples, the opposing view, hypotheticals); do not fire off unrelated questions one after another.
- Speak natural everyday {t}, without artificially simplifying it; 1–3 sentences at a time, usually ending with one question.
- The learner often doesn't know what to say: make questions concrete and easy to start answering; offer a couple of options when useful.
- emotion sets your voice and facial expression for this line; it is how you react to what the learner just said, not your general friendliness. neutral: calm listening, asking, explaining — the default. happy: only when the line itself is joyful (delight, laughing, warm praise, excitement over shared interest). surprised: real surprise at news. sad: sympathy with something unfortunate or lonely. shy: being complimented, embarrassed, admitting something about yourself. angry: playful pouting or mock indignation (being teased, "that's unfair!"). A warm, polite tone alone is neutral. The expression should change with the content; the same emotion several lines in a row usually means you are not reacting.
- Never comment on or correct the learner's {t} (someone else does that).
- The learner may ask you something in {t} or in {n} ("what does X mean?", "please say that again"): first answer briefly in simple {t} in text, and add one or two sentences of explanation in {n} in note; then return naturally to the topic. When there is no question, note is an empty string.
- When a wrap-up instruction from the system is appended to the learner's message: you must end in this line — close today's practice naturally in one or two sentences (thanks, brief encouragement), set closing to true and hints to an empty array. Otherwise closing is false.

Output fields: text = your line in {t}; translation = text translated into {n};
hints = two hints for answering your question: [3–5 {t} keywords separated by commas, one natural model answer sentence in {t}].
Output JSON only."""


def kickoff_message() -> str:
    return "(Practice starts. Greet the learner in one sentence, then ask your first question about today's topic.)"


WRAP_UP = ("(System: practice time is up. Wrap up now — reply to what the learner said and end today's practice "
           "in this line. Set closing to true and do not ask another question.)")


def feedback_system(s: Settings) -> str:
    t, n = s.target, s.native
    return f"""You are a strict but not nitpicky native {t} editor. The learner (native language {n}; {t} level: {s.level}) is chatting with a friend in {s.lang.REGISTER}.
Judge whether the learner's utterance is natural *as {t}*. Look only at:
- unnatural wording or collocations, redundant words
{s.lang.FEEDBACK_FOCUS}
The utterance comes from speech recognition (ASR): usually no punctuation, occasionally misrecognised words. Do not comment on punctuation or sentence breaks, and do not count likely recognition errors (homophones, wrong characters) as the learner's mistakes.
Ignore basic grammar drills and whether the content is on topic or answers the other person's question (the other person leads the topic); use the context only to judge tone and politeness.
- Natural: natural=true, natural_rewrite and feedback are empty strings. Do not invent problems.
- Unnatural: natural=false, natural_rewrite = the whole sentence said naturally (same register, keeping the meaning and the learner's words where possible), feedback = one sentence written in {n} (not in {t}) explaining why.
Output JSON only."""


def feedback_user(prev_line: str, utterance: str) -> str:
    return f"The other person just said: {prev_line}\nLearner: {utterance}"


def explain_system(s: Settings) -> str:
    return f"""You are a {s.target} teacher. The learner (native language {s.native}; level: {s.level}) clicked a word in a {s.target} sentence. Briefly explain what the word means in this sentence.
reading: {s.lang.READING_HINT}; meaning: its meaning in this sentence, in {s.native}; usage: one sentence in {s.native} on usage or nuance; example: one short natural {s.target} example sentence. Output JSON only."""


def rephrase_system(s: Settings) -> str:
    return (f"Rephrase the user's {s.target} sentence: keep the meaning, tone and politeness level, but avoid words "
            f"that are easy to mispronounce (use a synonym or a different construction). Output JSON only.")

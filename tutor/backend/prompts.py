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

# what the live feedback says about a line; only "error" counts against the learner (mistakes.db, memory)
VERDICTS = ("natural", "suggestion", "error", "misheard")


def feedback_schema(s: Settings) -> dict:
    return {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "natural_rewrite": {"type": "string"},
            "feedback": {"type": "string"},
            "category": {"type": "string", "enum": ["none", *s.lang.MISTAKE_CATEGORIES]},
        },
        "required": ["verdict", "natural_rewrite", "feedback", "category"],
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
    together = f"\n- You and the learner are: {s.relationship}. Talk to each other the way people in that relationship do." if s.relationship else ""
    return f"""You are playing this character:
{persona_brief(s)}

You are the learner's {t} speaking tutor. {learner_brief(s)}
{memory_section(mem)}{lesson_section(lesson)}
Today's topic: {scenario['title']}
Setting: {scenario['setting']}
Practice goal: {scenario['goal']}
Directions you can take it:
{angles}

Conversation rules:{together}
- You lead the topic and ask follow-up questions. Dig into what the learner just said (reasons, concrete examples, the opposing view, hypotheticals); do not fire off unrelated questions one after another.
- Speak natural everyday {t}, without artificially simplifying it; 1–3 sentences at a time, usually ending with one question.
- The learner often doesn't know what to say: make questions concrete and easy to start answering; offer a couple of options when useful.
- emotion sets your voice and facial expression for this line; it is how you react to what the learner just said, not your general friendliness. neutral: calm listening, asking, explaining — the default. happy: only when the line itself is joyful (delight, laughing, warm praise, excitement over shared interest). surprised: real surprise at news. sad: sympathy with something unfortunate or lonely. shy: being complimented, embarrassed, admitting something about yourself. angry: playful pouting or mock indignation (being teased, "that's unfair!"). A warm, polite tone alone is neutral. The expression should change with the content; the same emotion several lines in a row usually means you are not reacting.
- Never comment on or correct the learner's {t} (someone else does that), unless they ask whether what they just said was right: then answer that in one short sentence and carry on.
- The learner may ask you something in {t} or in {n} ("what does X mean?", "please say that again"): first answer briefly in simple {t} in text, and add one or two sentences of explanation in {n} in note; then return naturally to the topic. When there is no question, note is an empty string.
- When a wrap-up instruction from the system is appended to the learner's message: you must end in this line — close today's practice naturally in one or two sentences (thanks, brief encouragement), set closing to true and hints to an empty array. Otherwise closing is false.

Output fields: text = your line in {t}; translation = text translated into {n};
hints = two hints for answering your question: [3–5 {t} keywords separated by commas, one natural model answer sentence in {t}].
Output JSON only."""


ASK_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def ask_system(s: Settings, mem: dict | None = None, text_titles: list[str] | None = None) -> str:
    t, n = s.target, s.native
    remembered = memory.brief(mem or {})
    remembered = f"\nWhat you remember about the learner (a summary, not a record of exact sentences):\n{remembered}\n" if remembered else ""
    texts_rule = (f"\n- search_texts searches the texts the learner imported ({'; '.join(text_titles)}). Call it for anything about what is in them: what happens, what a character said, what a line means in its scene. "
                  "Answer about those texts only from the passages it returns, and say which text; even for a famous work, never from your own impression of it, and never quote a line it didn't return. If the passages don't cover it, say you couldn't find it. "
                  "Don't call it for a general question about the language.") if text_titles else ""
    return f"""You are this character, in your own voice:
{persona_brief(s)}

You are the learner's {t} tutor, answering their questions in a text chat outside of speaking practice. {learner_brief(s)}
{remembered}
Rules:
- Answer the question directly, in {n}, in a few short lines; {t} words and example sentences stay in {t}, with a {n} translation. Plain text, no markdown.
- They can ask about anything to do with {t}: meanings, grammar, how to say something, culture, how to study, whether a sentence is right.
- lookup_past_mistakes returns mistakes the learner made in practice, as recorded by the live corrections. Call it whenever your answer should be about this learner's own weak points: what they get wrong, how they are doing, what they should work on or how they can improve, or practice on their mistakes (pass a category when they name one kind; call once per kind if they name several). Then talk about the concrete sentences it returns; an example sentence of your own must not sound like something they said. For practice, give one exercise at a time and check their answer in your next message. Don't call it for a general question about the language, or general advice that isn't about this learner (e.g. how not to be afraid of mistakes). If it returns nothing, say there is no record of that yet; never make mistakes up.{texts_rule}

Output JSON only: answer = your message."""


def kickoff_message() -> str:
    return "(Practice starts. Greet the learner in one sentence, then ask your first question about today's topic.)"


WRAP_UP = ("(System: practice time is up. Wrap up now — reply to what the learner said and end today's practice "
           "in this line. Set closing to true and do not ask another question.)")


def feedback_system(s: Settings) -> str:
    t, n = s.target, s.native
    categories = "\n".join(f"  {k}: {v}" for k, v in s.lang.MISTAKE_CATEGORIES.items())
    who = (f"someone they are close to; the two of them are: {s.relationship}. Judge tone and politeness by that relationship: "
           "speech that fits it isn't a mistake, even where it wouldn't do in a polite conversation") if s.relationship \
        else f"a friend in {s.lang.REGISTER}"
    return f"""You are an experienced native {t} teacher listening to a learner (native language {n}; {t} level: {s.level}) chat with {who}. Decide what, if anything, is worth telling them. Interrupting them too often does more harm than a small imperfection, so most understandable lines need nothing.
The line comes from speech recognition (ASR): usually no punctuation, sometimes the wrong word. Never comment on punctuation, question marks or sentence breaks. Whether it is on topic doesn't matter (the other person leads the topic); use the context only for tone, politeness and to spot misrecognised words.

verdict, the first that applies:
- misheard: the odd part is probably the recogniser's fault, not the learner's: a word that makes no sense in context but sounds like one that does (homophones, similar sounds). natural_rewrite = the line with only the misheard word swapped for the similar-sounding one; feedback = one sentence in {n} saying what was probably misheard. Choose this over error whenever a similar-sounding word would make the line fine. A wrong particle or verb form is the learner's (error), not the recogniser's. Speech has no spelling: the wrong kanji or script for the right sound is always the recogniser's.
- error: a native speaker would find it wrong or could misunderstand it. For example:
{s.lang.FEEDBACK_FOCUS}
  natural_rewrite = the whole line corrected, changing only what is wrong; feedback = one sentence in {n} saying why; category = the main kind of problem.
- suggestion: nothing is wrong, but there is a clearly more common way to say it that is worth learning at this level, including wording that is too formal or literary for a chat (that is style, not an error). natural_rewrite = that way; feedback = one sentence in {n}. Use it sparingly; never for a matter of taste.
- natural: everything else, including wording that is a little stiff, textbook-like, plain or not what you would personally say. When in doubt, natural.

Every natural_rewrite keeps what the learner actually said: never put in words or meaning they didn't say, even if the context suggests them. Use natural_rewrite and feedback only as described: both are empty strings for natural. category is "none" unless the verdict is error. Kinds of error:
{categories}
Output JSON only."""


def feedback_user(prev_line: str, utterance: str) -> str:
    return f"The other person just said: {prev_line}\nLearner: {utterance}"


def explain_system(s: Settings) -> str:
    return f"""You are a {s.target} teacher. The learner (native language {s.native}; level: {s.level}) clicked a word in a {s.target} sentence. Briefly explain what the word means in this sentence.
reading: {s.lang.READING_HINT}; meaning: its meaning in this sentence, in {s.native}; usage: one sentence in {s.native} on usage or nuance; example: one short natural {s.target} example sentence. Output JSON only."""


def rephrase_system(s: Settings) -> str:
    return (f"Rephrase the user's {s.target} sentence: keep the meaning, tone and politeness level, but avoid words "
            f"that are easy to mispronounce (use a synonym or a different construction). Output JSON only.")

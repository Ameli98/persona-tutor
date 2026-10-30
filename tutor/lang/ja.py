"""Japanese: kana readings (pyopenjtalk), sentence splitting, clickable word units, reading comparison.

Implements the language interface described in lang/__init__.py.
"""
import re

import pyopenjtalk

from .common import compare_units

CODE = "ja"            # Whisper / GPT-SoVITS language code
NAME = "Japanese"
SENTENCE_END = "。！？!?"
# What the feedback editor should look at besides general naturalness (prompt text, English)
FEEDBACK_FOCUS = """- particle choice
- mixing polite (desu/masu) and plain forms, or keigo used wrongly for the situation
- written-style expressions used in casual speech
- literal translations from the learner's native language that a Japanese speaker would not say"""
REGISTER = "polite spoken Japanese (desu/masu), natural and not overly formal"
READING_HINT = "the reading in hiragana"
# Kinds of mistake the feedback editor labels and the tutor can look up (name → what it covers, prompt text)
MISTAKE_CATEGORIES = {
    "particle": "wrong or missing particle (は/が, に/で, を, の ...)",
    "conjugation": "verb or adjective form: tense, te-form, passive/causative, potential, negative",
    "register": "politeness: mixing desu/masu and plain forms, keigo, pronouns like 君 or あなた",
    "word_choice": "a word that doesn't fit the meaning or situation",
    "collocation": "words that don't go together, unnatural set phrases",
    "written_style": "written or stiff expressions used in casual speech",
    "literal_translation": "a calque from the learner's native language",
    "word_order": "word or clause order",
    "other": "anything else",
}

PUNCT = re.compile(r"[\s、。，．・…‥！？!?「」『』（）()―─～〜♪“”\"'.,]")
# split after sentence-final punctuation, but keep runs like ！？ or 。」 together
SENT_END = re.compile(r"(?<=[。！？!?])(?![。！？!?」』）)])")


def kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def reading(text: str) -> str:
    """Hiragana *pronunciation* (e.g. けんきゅー) of the whole text, punctuation dropped.
    Used for comparing against ASR output."""
    t = PUNCT.sub("", text)
    return kata_to_hira(pyopenjtalk.g2p(t, kana=True)) if t else ""


def reading_display(text: str) -> str:
    """Hiragana in standard spelling (けんきゅう, こんにちは) for showing to the learner."""
    out = []
    for n in pyopenjtalk.run_frontend(text):
        if n["pos"] == "記号":
            continue
        r = n["read"] if n["read"] and n["read"] != "*" else n["string"]
        out.append(kata_to_hira(r))
    return "".join(out)


def split_sentences(text: str, max_len: int = 60) -> list[str]:
    """Split on sentence-final punctuation; very long sentences also split on 、."""
    out = []
    for s in (p.strip() for p in SENT_END.split(text)):
        if not s:
            continue
        if not re.search(r"\w", s):  # punctuation only (e.g. a stray ？): attach to the previous sentence
            if out:
                out[-1] += s
            continue
        if len(s) <= max_len:
            out.append(s)
            continue
        buf = ""
        for part in re.split(r"(?<=、)", s):
            if buf and len(buf) + len(part) > max_len:
                out.append(buf)
                buf = ""
            buf += part
        if buf:
            out.append(buf)
    return out


def compare(target: str, said: str) -> dict:
    """Compare by kana *pronunciation*, so kanji/kana spelling differences in ASR output don't count."""
    return compare_units(reading(target), reading(said))


def script_ratio(text: str) -> float:
    """Share of kana characters outside 「quotes」: how 'Japanese' an explanation looks (used to catch the
    model writing explanations in the target language instead of the learner's; quoted examples don't count)."""
    letters = [c for c in re.sub(r"「[^」]*」", "", text) if not c.isspace()]
    return sum(1 for c in letters if "\u3040" <= c <= "\u30ff") / (len(letters) or 1)


# parts of speech that attach to the previous word when building clickable units
_ATTACH = {("動詞", "接尾"), ("動詞", "非自立"), ("形容詞", "非自立"), ("形容詞", "接尾"), ("名詞", "接尾")}


def tokens(text: str) -> list[dict]:
    """Split Japanese into clickable units: a content word plus its trailing auxiliaries.

    Each unit: {"surface": "言われている", "base": "言う", "click": True}. Punctuation and
    particles are separate, non-clickable units.
    """
    out = []
    for n in pyopenjtalk.run_frontend(text):
        surf, pos, g1 = n["string"], n["pos"], n["pos_group1"]
        attach = (pos, g1) in _ATTACH or pos == "助動詞" or (pos == "助詞" and g1 == "接続助詞" and out
                                                           and out[-1]["pos"] == "動詞")
        if attach and out and out[-1]["click"]:
            out[-1]["surface"] += surf
            continue
        click = pos not in ("記号", "助詞")
        out.append({"surface": surf, "base": n["orig"] if click else surf, "click": click, "pos": pos})
    for t in out:
        t.pop("pos")
    return out

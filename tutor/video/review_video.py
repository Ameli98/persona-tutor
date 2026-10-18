"""Turn a reviewed session (review.json) into review videos: corrected / model version (× shadowing).

Used by tools/render_review.py (CLI) and the backend's "make review video" button. Split in two steps so
the caller can hold the GPU only while voicing: voice_user_lines() (TTS, GPU) → render_videos() (ffmpeg).
Progress goes to log(key, **args); the web page translates the keys.
"""
import json
import re
import time
from pathlib import Path

import numpy as np

from ..backend.settings import path
from . import fonts
from .render import Line, Theme, read_wav, render

MODES = ("corrected", "upgraded")

# Text burned into the video, in the UI language
LABELS = {
    "en": {"corrected": "Corrected", "model": "Model answer", "said": "You said", "reason": "Why: ",
           "point": "Key point: ", "shadow": "Your turn ▶ say it", "corrected_title": "Corrected version",
           "upgraded_title": "Model version", "shadow_suffix": " · shadowing"},
    "zh-TW": {"corrected": "修正", "model": "範本", "said": "你原本說的", "reason": "原因：",
              "point": "重點：", "shadow": "跟著唸 ▶  請跟讀一次", "corrected_title": "修正版",
              "upgraded_title": "範本版", "shadow_suffix": "・跟讀"},
}


def load_review(sdir: Path) -> dict:
    return json.loads((sdir / "review.json").read_text(encoding="utf-8"))


def user_line(t: dict, mode: str) -> tuple[str, str, str, str, str]:
    """(text, kind, note, translation, emotion) for a learner turn in this mode."""
    rv = t.get("review") or {}
    emo = rv.get("emotion", "neutral")
    if mode == "corrected":
        return rv.get("corrected") or t["text"], "corrected", rv.get("corrected_reason", ""), "", emo
    return rv.get("upgraded") or t["text"], "model", rv.get("upgrade_note", ""), rv.get("translation", ""), emo


def to_voice(review: dict, modes) -> list[tuple[str, str]]:
    """Unique (text, emotion) pairs the review voice has to say."""
    out = []
    for mode in modes:
        for t in review["session"]["turns"]:
            if t["role"] != "user":
                continue
            text, _, _, _, emo = user_line(t, mode)
            if (text, emo) not in out:
                out.append((text, emo))
    return out


def voice_user_lines(review: dict, modes, say_many, log) -> dict:
    """say_many([(text, emotion), ...]) -> [(wav path, verified, attempts), ...] (batched TTS).
    Returns {(text, emotion): int16 audio}."""
    pairs = to_voice(review, modes)
    log("voicing", n=len(pairs))
    spoken = {}
    for (text, emo), (wav, ok, attempts) in zip(pairs, say_many(pairs)):
        spoken[(text, emo)] = read_wav(wav)
        if not ok or attempts > 1:
            log("voice_retry", emotion=emo, ok=ok, retries=attempts - 1, text=text)
    return spoken


def tutor_lines(s, sdir: Path, t: dict) -> list[Line]:
    """One frame per sentence (the tutor's audio was recorded per sentence), so subtitles follow the voice."""
    sents = s.lang.split_sentences(t["text"])
    wavs = [read_wav(sdir / a) for a in t["audio"]]
    tr = t.get("translation", "")
    if len(sents) == len(wavs) and len(sents) > 1:
        parts = [p.strip() for p in re.split(r"(?<=[。！？!?.])\s*", tr) if p.strip()]
        if len(parts) != len(sents):  # can't align the translation; show it on the last sentence
            parts = [""] * (len(sents) - 1) + [tr]
        return [Line("tutor", x, p, t["emotion"], w) for x, p, w in zip(sents, parts, wavs)]
    audio = np.concatenate(wavs) if wavs else np.zeros(1, np.int16)
    return [Line("tutor", t["text"], tr, t["emotion"], audio)]


def theme(s) -> Theme:
    rvc = s.cfg.get("review_video", {})
    fd = str(path(rvc["font_dir"])) if rvc.get("font_dir") else None
    ui = s.cfg.get("ui_language", "en")
    chars = rvc.get("characters") or {}
    # unset → data/characters/<role> (images dropped there work with older config files too)
    char_dir = lambda key, role: str(path(chars[key])) if chars.get(key) else str(s.data / "characters" / role)
    return Theme(
        target_bold=fonts.find(s.lang.CODE, True, fd), target_regular=fonts.find(s.lang.CODE, False, fd),
        native_regular=fonts.find(s.native_code, False, fd), ui_regular=fonts.find(ui, False, fd),
        ui_bold=fonts.find(ui, True, fd),
        names={"tutor": s.persona["name"], "user": s.cfg.get("learner", {}).get("name", "You")},
        labels=LABELS.get(ui, LABELS["en"]),
        characters={"tutor": char_dir("tutor", "tutor"), "user": char_dir("learner", "learner")})


IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


def find_background(rvc: dict, scenario_id: str, default_dir: Path):
    """review_video.backgrounds[scenario] > background (a file, or a folder holding <scenario_id>.* or default.*);
    unset → default_dir (data/backgrounds), so dropping an image there works with older config files too."""
    explicit = (rvc.get("backgrounds") or {}).get(scenario_id)
    if explicit:
        return path(explicit)
    p = path(rvc["background"]) if rvc.get("background") else default_dir
    if p.is_dir():
        for stem in (scenario_id, "default"):
            for ext in IMAGE_EXT:
                if (p / f"{stem}{ext}").exists():
                    return p / f"{stem}{ext}"
        return None
    return p if p.exists() else None


def render_videos(s, sdir: Path, review: dict, spoken: dict, modes, shadow: bool, log) -> list[Path]:
    """s = Settings. Writes review/<mode>[_shadow].{mp4,mp3} in the session folder."""
    rvc = s.cfg.get("review_video", {})
    session = review["session"]
    sc = session["scenario"]
    bg = find_background(rvc, sc["id"], s.data / "backgrounds")
    th = theme(s)
    out_dir = sdir / "review"
    out_dir.mkdir(exist_ok=True)
    written = []
    for mode in modes:
        lines = []
        for t in session["turns"]:
            if t["role"] == "tutor":
                lines += tutor_lines(s, sdir, t)
                continue
            text, kind, note, tr, emo = user_line(t, mode)
            said = t["text"] if (mode == "upgraded" or note) else ""
            lines.append(Line("user", text, tr, emo, spoken[(text, emo)], said, kind, note))
        for sh in ((False, True) if shadow else (False,)):
            base = out_dir / f"{mode}{'_shadow' if sh else ''}"
            t0 = time.time()
            title = th.labels[f"{mode}_title"] + (th.labels["shadow_suffix"] if sh else "")
            mp4, mp3 = render(lines, base, s.scenario_title(sc, s.lang.CODE), title, th, bg, sh)
            log("video_done", file=mp4.name, seconds=round(time.time() - t0))
            written += [mp4, mp3]
    return written

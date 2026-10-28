"""Settings loading, the setup wizard's config edits, and review-video line selection."""
import yaml

from tutor.backend import settings
from tutor.setup import set_line, slug
from tutor.video.review_video import to_voice


def test_example_config_loads(tmp_path):
    s = settings.load(settings.ROOT / "config.example.yaml")
    assert s.lang.CODE == "ja" and s.persona["name"] and len(s.scenarios) >= 8
    assert all(sc["title"] and sc["setting"] for sc in s.scenarios.values())
    assert s.warmup_pool() and all(w["text"] for w in s.warmup_pool())


def test_set_line_keeps_comment_and_yaml_valid():
    text = (settings.ROOT / "config.example.yaml").read_text(encoding="utf-8")
    out = set_line(text, "level", '"中級: 読めるけど話せない"', "  ")
    out = set_line(out, "ui_language", "zh-TW")
    cfg = yaml.safe_load(out)
    assert cfg["language"]["level"] == "中級: 読めるけど話せない" and cfg["ui_language"] == "zh-TW"
    assert "# free text, goes into the prompts" in out


def test_slug():
    assert slug("Genzo Hayashibara") == "genzo_hayashibara" and slug("!!!") == "topic"


def test_to_voice_dedupes_identical_lines():
    turn = {"role": "user", "text": "はい", "review": {"corrected": "はい。", "upgraded": "はい、そうです。", "emotion": "happy"}}
    review = {"session": {"turns": [turn, dict(turn)]}}
    assert to_voice(review, ["corrected", "upgraded"]) == [("はい。", "happy"), ("はい、そうです。", "happy")]


def test_native_language_names():
    from faster_whisper.tokenizer import _LANGUAGE_CODES
    from tutor.lang import names
    assert set(names.WHISPER) == set(_LANGUAGE_CODES)          # every language Whisper can hear
    assert names.normalize("Vietnamese") == "vi" and names.normalize(" VI ") == "vi"
    assert names.normalize("zh-tw") == "zh-TW" and names.normalize("Traditional Chinese") == "zh-TW"
    assert names.normalize("越南語") is None and names.normalize("") is None
    assert names.whisper_code("zh-TW") == "zh" and names.name("zh-TW").startswith("Traditional")


def test_art_emotion_names_and_background():
    from PIL import Image, ImageDraw
    from tutor.art import emotion_of, remove_background, set_character
    from pathlib import Path
    assert emotion_of(Path("02_笑顔.png")) == "happy" and emotion_of(Path("Haruka-SHY.webp")) == "shy"
    assert emotion_of(Path("照れ.png")) == "shy" and emotion_of(Path("portrait.png")) is None
    # green screen: background and enclosed green pockets go, the figure (incl. white parts) stays
    img = Image.new("RGB", (100, 100), (0, 255, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((30, 20, 70, 90), fill=(250, 250, 250), outline=(20, 20, 20))   # white clothes
    d.rectangle((45, 40, 55, 50), fill=(0, 255, 0))                               # green pocket inside
    a = remove_background(img).getchannel("A")
    assert a.getpixel((5, 5)) == 0 and a.getpixel((50, 45)) == 0 and a.getpixel((35, 80)) == 255
    # white background: only background connected to the edges goes, white inside the outline stays
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    ImageDraw.Draw(img).rectangle((30, 20, 70, 90), fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    a = remove_background(img).getchannel("A")
    assert a.getpixel((5, 5)) == 0 and a.getpixel((50, 50)) == 255
    cfg = set_character((settings.ROOT / "config.example.yaml").read_text(encoding="utf-8"), "tutor", "data/characters/tutor")
    c = yaml.safe_load(cfg)
    assert c["review_video"]["characters"]["tutor"] == "data/characters/tutor" and c["voices"]["tutor"]["sovits"]


def test_panel_avoids_characters():
    from tutor.video.render import panel_span, W
    for spans in ([(810, 1110)], [(330, 630), (1290, 1590)], []):
        x0, x1 = panel_span(spans)
        assert x1 - x0 >= 480 and 0 <= x0 and x1 <= W
        assert all(x1 <= l or x0 >= r for l, r in spans)


def test_memory_save_caps_and_brief(tmp_path):
    from tutor.backend import memory
    assert memory.brief(memory.load(tmp_path)) == ""          # nothing yet → nothing in the prompt
    saved = memory.save(tmp_path, {"level": " ok ", "errors": [f"e{i}" for i in range(30)] + ["", "  "],
                                   "about": ["likes RPGs"], "junk": ["x"]})
    assert saved["level"] == "ok" and len(saved["errors"]) == memory.FIELDS["errors"][0] and "junk" not in saved
    mem = memory.load(tmp_path)
    assert "likes RPGs" in memory.brief(mem) and mem["updated"]


def test_prompts_include_memory_and_lesson():
    from tutor.backend import prompts, settings
    from tutor.backend.review import review_system
    s = settings.load("config.example.yaml")
    sc = next(iter(s.scenarios.values()))
    lesson = {"phrases": [{"text": "ちょっと…", "translation": "", "note": ""}],
              "grammar": {"point": "〜たいんですが", "explanation": "", "examples": []}, "dialogue": [], "culture": ""}
    text = prompts.reply_system(s, sc, {"level": "", "errors": [], "mastered": [], "topics": [],
                                        "about": ["planning a trip to Kanazawa"]}, lesson)
    assert "Kanazawa" in text and "ちょっと…" in text and "〜たいんですが" in text
    assert "remember" not in prompts.reply_system(s, sc)       # no memory, no lesson → no extra sections
    assert "ちょっと…" in review_system(s, lesson) and "empty array" in review_system(s)

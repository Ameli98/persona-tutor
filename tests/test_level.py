"""The learner's level: the band moves slowly by rule, and the assessed level replaces the self-rating (no API calls)."""
from types import SimpleNamespace as NS

from tutor.backend import memory, prompts, settings
from tutor.lang import ja  # noqa: F401


def band(mem, estimate):
    return {**mem, **memory.apply_band(mem, estimate, "why", "2026-10-30")}


def test_first_assessment_is_taken_as_it_is():
    mem = band({"band": ""}, "elementary")
    assert mem["band"] == "elementary" and mem["band_history"][-1]["from"] == ""


def test_one_session_does_not_move_it():
    mem = band({"band": "intermediate"}, "beginner")
    assert mem["band"] == "intermediate" and mem["band_pending"] == -1 and not mem["band_history"]


def test_two_in_a_row_move_one_step_only():
    mem = band(band({"band": "beginner"}, "advanced"), "advanced")
    assert mem["band"] == "elementary" and mem["band_pending"] is None
    assert mem["band_history"][-1] == {"date": "2026-10-30", "from": "beginner", "to": "elementary", "why": "why"}


def test_a_session_in_between_resets_the_count():
    assert band(band(band({"band": "intermediate"}, "advanced"), "intermediate"), "advanced")["band"] == "intermediate"
    assert band(band(band({"band": "intermediate"}, "advanced"), "beginner"), "advanced")["band"] == "intermediate"


def test_ends_of_the_scale_stay_in_range():
    assert band(band({"band": "advanced"}, "advanced"), "advanced")["band"] == "advanced"
    assert band(band({"band": "beginner"}, "beginner"), "beginner")["band"] == "beginner"


def test_old_learner_json_still_loads(tmp_path):
    memory.path(tmp_path).write_text('{"level": "ok", "errors": ["e"]}', encoding="utf-8")
    mem = memory.load(tmp_path)
    assert mem["band"] == "" and mem["band_history"] == [] and mem["errors"] == ["e"]
    assert memory.level_text(mem) == "ok"


def test_page_edit_keeps_history_and_counts_a_band_change(tmp_path):
    memory.save(tmp_path, {"level": "a", "band": "intermediate", "band_pending": 1, "band_history": [{"date": "x", "from": "", "to": "intermediate", "why": ""}]})
    same = memory.apply_edit(tmp_path, {"level": "b", "band": "intermediate"})
    assert same["level"] == "b" and same["band_pending"] == 1 and len(same["band_history"]) == 1
    moved = memory.apply_edit(tmp_path, {"band": "advanced"})
    assert moved["band"] == "advanced" and moved["band_pending"] is None and moved["band_history"][-1]["manual"]
    assert memory.apply_edit(tmp_path, {"band": "nonsense"})["band"] == "advanced"


def test_update_applies_the_rule_not_the_models_band(tmp_path):
    s = settings.load("config.example.yaml")
    memory.save(tmp_path, {"level": "a", "band": "beginner"})
    out = {"level": "b", "errors": [], "mastered": [], "topics": [], "about": [], "band": "advanced", "band_why": "w"}
    llm = NS(json_with_cost=lambda *a, **k: (dict(out), 0.0))
    review = {"session": {"started": "2026-10-30", "scenario": {"title": "t"}, "turns": []}}
    assert memory.update(llm, s, tmp_path, review)[0]["band"] == "beginner"
    second = memory.update(llm, s, tmp_path, review)[0]
    assert second["band"] == "elementary"
    assert memory.load(tmp_path)["band"] == "elementary"


def test_assessed_level_reaches_every_prompt():
    s = settings.load("config.example.yaml")
    self_rated = s.level
    s.assessed_level = memory.level_text({"band": "elementary", "level": "ASSESSED"})
    sc = next(iter(s.scenarios.values()))
    for text in (prompts.reply_system(s, sc), prompts.feedback_system(s), prompts.explain_system(s), prompts.ask_system(s)):
        assert "ASSESSED" in text and self_rated not in text
    assert self_rated in memory.update_system(s)

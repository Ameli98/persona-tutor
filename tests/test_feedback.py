"""Live feedback verdicts: what counts against the learner, and what the review and memory hear about it (no API calls)."""
from types import SimpleNamespace as NS

import pytest

from tutor.backend import memory, mistakes, settings
from tutor.backend.llm import fallback_args
from tutor.backend.review import live_note, without_excused
from tutor.backend.session import Session


@pytest.fixture
def s():
    return settings.load("config.example.yaml")


def feedback_from(s, out):
    llm = NS(json=lambda *a, **k: dict(out), last_cost=0.0)
    return Session(s, next(iter(s.scenarios.values())), minutes=5).feedback(llm, "prev", "line")


def test_natural_verdict_has_no_rewrite(s):
    fb = feedback_from(s, {"verdict": "natural", "natural_rewrite": "extra", "feedback": "extra", "category": "none"})
    assert fb["natural"] and fb["natural_rewrite"] == "" and fb["feedback"] == ""


def test_other_verdicts_are_not_natural(s):
    for verdict in ("suggestion", "error", "misheard"):
        assert not feedback_from(s, {"verdict": verdict, "natural_rewrite": "x", "feedback": "y", "category": "none"})["natural"]


def test_review_note_per_verdict():
    assert live_note(None) == ""
    assert live_note({"natural": True}) == ""
    assert "suggested: x" in live_note({"natural": False, "natural_rewrite": "x"})          # sessions from before the verdicts
    assert "misheard" in live_note({"natural": False, "verdict": "misheard", "natural_rewrite": "x"})
    assert "not a mistake" in live_note({"natural": False, "verdict": "error", "natural_rewrite": "x", "dismissed": True})


def test_listing_has_ids_newest_first_and_the_tool_result_does_not(tmp_path):
    db = tmp_path / "m.db"
    assert mistakes.listing(db) == []
    first = mistakes.add(db, "a", "b", "particle", created="2026-10-01 10:00:00")
    second = mistakes.add(db, "c", "d", "register", created="2026-10-02 10:00:00")
    assert [r["id"] for r in mistakes.listing(db)] == [second, first]
    assert "id" not in mistakes.lookup(db)[0]


def test_delete_removes_only_that_mistake(tmp_path):
    db = tmp_path / "m.db"
    a = mistakes.add(db, "a", "b", "particle")
    mistakes.add(db, "c", "d", "particle")
    mistakes.delete(db, a)
    assert [r["said"] for r in mistakes.lookup(db)] == ["c"]


def test_memory_is_told_misheard_and_dismissed_lines_are_not_mistakes(s, tmp_path):
    seen = {}

    def json_with_cost(system, msgs, schema, max_tokens):
        seen["msg"] = msgs[0]["content"]
        return {"level": "", "errors": [], "mastered": [], "topics": [], "about": []}, 0.0
    fix = {"review": {"corrected": "x", "corrected_reason": "why"}}
    review = {"session": {"started": "2026-10-30", "scenario": {"title": "t"}, "turns": [
        {"role": "user", "text": "聞き間違い", "feedback": {"verdict": "misheard"}, **fix},
        {"role": "user", "text": "取り消し", "feedback": {"verdict": "error", "dismissed": True}, **fix},
        {"role": "user", "text": "本当の間違い", "feedback": {"verdict": "error"}, **fix},
    ]}}
    memory.update(NS(json_with_cost=json_with_cost), s, tmp_path, review)
    lines = seen["msg"].splitlines()
    assert "corrected" not in next(x for x in lines if "聞き間違い" in x)
    assert "corrected" not in next(x for x in lines if "取り消し" in x)
    assert "corrected: x" in next(x for x in lines if "本当の間違い" in x)


def test_haiku_gets_no_server_side_fallback():
    assert fallback_args("claude-haiku-5-5") == {}
    assert fallback_args("claude-sonnet-5-5")["fallbacks"] == "default"


def test_session_cost_adds_up_by_feature(s):
    sess = Session(s, next(iter(s.scenarios.values())), minutes=5)
    sess.charge("reply", 0.25)
    sess.charge("reply", 0.25)
    sess.charge("review", 0.5)
    assert sess.cost == 1.0 and sess.costs == {"reply": 0.5, "review": 0.5}


def test_misheard_and_dismissed_lines_dont_become_key_expressions():
    session = {"turns": [
        {"role": "tutor", "text": "そうですか"},
        {"role": "user", "text": "飴が降っていました。", "feedback": {"verdict": "misheard"}},
        {"role": "user", "text": "取り消した文です", "feedback": {"verdict": "error", "dismissed": True}},
        {"role": "user", "text": "バスを乗りました", "feedback": {"verdict": "error"}},
    ]}
    keep = {"said": "バスを乗りました", "better": "バスに乗りました", "reason": ""}
    drop = [{"said": "飴が降っていました", "better": "x", "reason": ""}, {"said": "取り消した文です。", "better": "x", "reason": ""}]
    assert without_excused([*drop, keep], session) == [keep]

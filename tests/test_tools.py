"""lookup_past_mistakes: the store, input validation, the tool-use loop in AnthropicLLM.stream_json and the Ask tab
(with a fake client, so no API calls)."""
import json
from types import SimpleNamespace as NS

import pytest

from tutor.backend import ask, mistakes, prompts, settings
from tutor.backend.llm import AnthropicLLM
from tutor.lang import ja

CATS = ja.MISTAKE_CATEGORIES


@pytest.fixture
def example_settings():
    return settings.load("config.example.yaml")


def test_store_newest_first_and_filter(tmp_path):
    db = tmp_path / "m.db"
    assert mistakes.lookup(db) == []                          # no database yet → empty, not an error
    mistakes.add(db, "公園で散歩します", "公園を散歩します", "particle", created="2026-10-01 10:00:00")
    mistakes.add(db, "気づかれなくて", "気づかなくて", "conjugation", created="2026-10-02 10:00:00")
    mistakes.add(db, "君が一番大事", "あなたが一番大事", "register", created="2026-10-03 10:00:00")
    assert [r["category"] for r in mistakes.lookup(db)] == ["register", "conjugation", "particle"]
    assert [r["said"] for r in mistakes.lookup(db, "particle")] == ["公園で散歩します"]
    assert len(mistakes.lookup(db, limit=2)) == 2
    assert mistakes.lookup(db, "word_order") == []


def test_run_tool_validates_input(tmp_path):
    db = tmp_path / "m.db"
    mistakes.add(db, "a", "b", "particle")
    out, err = mistakes.run_tool(db, CATS, mistakes.TOOL_NAME, {"category": "particle"})
    assert not err and json.loads(out)["count"] == 1
    out, err = mistakes.run_tool(db, CATS, mistakes.TOOL_NAME, {})        # both arguments optional
    assert not err and json.loads(out)["count"] == 1
    for bad in ({"category": "tense"}, {"limit": 0}, {"limit": "5"}, {"limit": True}, "not an object"):
        assert mistakes.run_tool(db, CATS, mistakes.TOOL_NAME, bad)[1], bad
    assert mistakes.run_tool(db, CATS, "other_tool", {})[1]


class FakeStream:
    def __init__(self, resp):
        self.resp = resp
        self.text_stream = [b.text for b in resp.content if b.type == "text"]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.resp


def reply(text_or_tools, stop):
    blocks = [NS(type="tool_use", id=f"t{i}", name=n, input=a) for i, (n, a) in enumerate(text_or_tools)] \
        if stop == "tool_use" else [NS(type="text", text=text_or_tools)]
    return NS(content=blocks, stop_reason=stop, stop_details=None,
              usage=NS(input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0))


def fake_llm(responses):
    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model, llm.effort, requests = "claude-opus-5-5", "low", []

    def stream(**kw):
        requests.append({**kw, "messages": list(kw["messages"])})
        return FakeStream(responses.pop(0))
    llm.client = NS(beta=NS(messages=NS(stream=stream)))
    return llm, requests


def test_loop_runs_consecutive_tool_calls_then_answers(tmp_path):
    final = json.dumps({"text": "はい"})
    llm, requests = fake_llm([
        reply([(mistakes.TOOL_NAME, {"category": "particle"}), (mistakes.TOOL_NAME, {"category": "register"})], "tool_use"),
        reply([(mistakes.TOOL_NAME, {})], "tool_use"),
        reply(final, "end_turn"),
    ])
    seen = []
    run = lambda name, args: (seen.append(args) or json.dumps({"mistakes": [], "count": 0}), False)
    out = llm.stream_json("sys", [{"role": "user", "content": "q"}], {}, lambda c: None,
                          tools=[{"name": mistakes.TOOL_NAME}], run_tool=run)
    assert out == {"text": "はい"} and len(seen) == 3 and len(llm.last_tool_calls) == 3
    second = requests[1]["messages"]
    # both results of the first (parallel) round come back in one user message, matched by id
    assert second[-1]["role"] == "user" and [r["tool_use_id"] for r in second[-1]["content"]] == ["t0", "t1"]
    assert all(r["tool_choice"]["type"] == "auto" for r in requests)


def test_loop_stops_offering_tools_after_max_rounds():
    always_tool = [reply([(mistakes.TOOL_NAME, {})], "tool_use") for _ in range(2)]
    llm, requests = fake_llm(always_tool + [reply(json.dumps({"text": "ok"}), "end_turn")])
    out = llm.stream_json("sys", [{"role": "user", "content": "q"}], {}, lambda c: None,
                          tools=[{"name": mistakes.TOOL_NAME}], run_tool=lambda n, a: ("{}", False),
                          max_tool_rounds=2)
    assert out == {"text": "ok"} and requests[-1]["tool_choice"] == {"type": "none"}


def test_no_tools_is_a_single_plain_request():
    llm, requests = fake_llm([reply(json.dumps({"text": "ok"}), "end_turn")])
    assert llm.stream_json("sys", [{"role": "user", "content": "q"}], {}, lambda c: None) == {"text": "ok"}
    assert "tools" not in requests[0] and llm.last_tool_calls == []


def test_ask_runs_the_tool_and_trims_old_messages(tmp_path, example_settings):
    db = tmp_path / "m.db"
    mistakes.add(db, "友達が会いました", "友達に会いました", "particle")
    llm, requests = fake_llm([reply([(mistakes.TOOL_NAME, {"category": "particle"})], "tool_use"),
                              reply(json.dumps({"answer": "「友達に会いました」です"}), "end_turn")])
    long_chat = [{"role": r, "content": "x"} for r in ["user", "assistant"] * 15] + [{"role": "user", "content": "q"}]
    out = ask.answer(llm, example_settings, None, db, long_chat, lambda c: None)
    assert out["answer"] == "「友達に会いました」です"
    assert ask.summarize(out["calls"]) == [{"name": mistakes.TOOL_NAME, "input": {"category": "particle"},
                                            "is_error": False, "count": 1}]
    first = requests[0]["messages"]
    assert first[0]["role"] == "user" and first[-1]["content"] == "q" and len(first) <= ask.MAX_MESSAGES
    assert requests[0]["tools"][0]["name"] == mistakes.TOOL_NAME


def test_practice_has_no_tool(example_settings):
    s = example_settings
    assert mistakes.TOOL_NAME not in prompts.reply_system(s, next(iter(s.scenarios.values())))
    assert mistakes.TOOL_NAME in prompts.ask_system(s)

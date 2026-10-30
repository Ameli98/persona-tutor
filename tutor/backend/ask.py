"""The Ask tab: a text chat with the tutor, separate from practice, open at any time. Questions about the language,
or about the learner's own mistakes (the lookup_past_mistakes tool). The page holds the conversation and sends it
with each question; nothing is saved here."""
from functools import partial
from pathlib import Path

from . import mistakes, prompts
from .settings import Settings

MAX_MESSAGES = 20    # the page sends the whole chat; older messages are dropped so a question's cost has a ceiling


def answer(llm, s: Settings, mem: dict | None, db: Path, messages: list, on_text) -> dict:
    """messages: [{"role": "user" | "assistant", "content": text}], ending with the question.
    Returns {"answer", "calls" (the tool calls, see summarize), "cost"}."""
    msgs = messages[-MAX_MESSAGES:]
    while msgs and msgs[0]["role"] != "user":
        msgs = msgs[1:]
    cats = s.lang.MISTAKE_CATEGORIES
    out = llm.stream_json(prompts.ask_system(s, mem), msgs, prompts.ASK_SCHEMA, on_text,
                          tools=[mistakes.tool_definition(cats)], run_tool=partial(mistakes.run_tool, db, cats))
    return {"answer": out["answer"], "calls": llm.last_tool_calls, "cost": llm.last_cost}


def summarize(calls: list) -> list:
    """What the page shows: which lookups ran and how many rows came back, not the rows."""
    return [{"name": c["name"], "input": c["input"], "is_error": c["is_error"],
             "count": None if c["is_error"] else mistakes.result_count(c["result"])} for c in calls]

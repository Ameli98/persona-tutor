"""Conversation session: scenario, history, and the reply / feedback LLM calls."""
import json
import random
import time
import uuid
from dataclasses import dataclass, field

from . import prompts
from .settings import Settings


@dataclass
class Session:
    settings: Settings
    scenario: dict
    minutes: float
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started: float = field(default_factory=time.time)
    # messages for the reply LLM (append-only, cache-friendly). Assistant turns keep only
    # emotion + target-language text: translation/hints are ~60% of each reply and the model never needs them again.
    history: list = field(default_factory=list)
    last_line: str = ""
    closed: bool = False
    wrap_up_sent: bool = False
    max_turns: int = 40      # history window: older turns are dropped, so per-turn cost has a ceiling
    max_cost: float = 1.0    # $ per session; at this point the tutor wraps up
    cost: float = 0.0        # $ spent in this session (API-reported usage)
    memory: dict | None = None   # learner.json at the start (what the tutor remembers)
    lesson: dict | None = None   # the lesson studied right before, if any

    @property
    def elapsed_min(self) -> float:
        return (time.time() - self.started) / 60

    def reply(self, llm, user_text: str | None, force_wrap_up: bool = False, on_text=None) -> dict:
        """The tutor's next line. user_text=None starts the session. on_text streams the raw JSON."""
        self.history.append({"role": "user", "content": user_text or prompts.kickoff_message()})
        if len(self.history) > 2 * self.max_turns:
            # drop the oldest whole turns (user+assistant pairs); history must still start with a user turn
            self.history = self.history[-(2 * self.max_turns - 1):]
        msgs = list(self.history)
        over = self.elapsed_min >= self.minutes or self.cost >= self.max_cost
        if force_wrap_up or over:
            # turn-local note appended to the user's message (not stored in history), repeated on every
            # turn until she closes: a one-time note was sometimes ignored and the session ran on
            msgs[-1] = {"role": "user", "content": msgs[-1]["content"] + "\n\n" + prompts.WRAP_UP}
            self.wrap_up_sent = True
        system = prompts.reply_system(self.settings, self.scenario, self.memory, self.lesson)
        if on_text:
            out = llm.stream_json(system, msgs, prompts.REPLY_SCHEMA, on_text)
        else:
            out = llm.json(system, msgs, prompts.REPLY_SCHEMA)
        self.cost += llm.last_cost
        self.history.append({"role": "assistant", "content": self._slim(out["emotion"], out["text"])})
        self.last_line = out["text"]
        self.closed = bool(out.get("closing"))
        return out

    @staticmethod
    def _slim(emotion: str, text: str) -> str:
        return json.dumps({"emotion": emotion, "text": text}, ensure_ascii=False)

    def replace_last_text(self, old: str, new: str):
        """A sentence was re-phrased because TTS couldn't say it; keep history in sync."""
        last = json.loads(self.history[-1]["content"])
        last["text"] = last["text"].replace(old, new)
        self.history[-1]["content"] = self._slim(last["emotion"], last["text"])
        self.last_line = last["text"]

    def feedback(self, llm, prev_line: str, user_text: str) -> dict:
        msgs = [{"role": "user", "content": prompts.feedback_user(prev_line, user_text)}]
        schema = prompts.feedback_schema(self.settings)
        out = llm.json(prompts.feedback_system(self.settings), msgs, schema, max_tokens=2000)
        self.cost += llm.last_cost
        if out["feedback"] and self.settings.lang.script_ratio(out["feedback"]) >= 0.3:
            # the reason drifted into the target language; ask once more, explicitly
            msgs[0]["content"] += f"\n\n(Write the feedback sentence in {self.settings.native}.)"
            out = llm.json(prompts.feedback_system(self.settings), msgs, schema, max_tokens=2000)
            self.cost += llm.last_cost
        out["natural"] = out["verdict"] == "natural"
        if out["natural"]:
            out["natural_rewrite"] = out["feedback"] = ""
        return out


def pick_scenario(scenarios: dict, scenario_id: str | None = None) -> dict:
    if scenario_id and scenario_id in scenarios:
        return scenarios[scenario_id]
    return random.choice(list(scenarios.values()))

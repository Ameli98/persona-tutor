"""LLM backends (Anthropic / Ollama) returning schema-validated JSON."""
import json
import os
import re
import threading
import urllib.request
from pathlib import Path


class LLMError(RuntimeError):
    pass


class FieldWatcher:
    """Pull a string field out of a JSON object while it is still being streamed.

    feed(chunk) returns the field's decoded value so far (or None before it starts);
    .done becomes True once its closing quote has arrived.
    """

    def __init__(self, field: str):
        self.start_re = re.compile(r'"%s"\s*:\s*"' % re.escape(field))
        self.buf, self.start, self.done = "", None, False

    def feed(self, chunk: str):
        self.buf += chunk
        if self.start is None:
            m = self.start_re.search(self.buf)
            if not m:
                return None
            self.start = m.end()
        raw, i = [], self.start
        while i < len(self.buf):
            c = self.buf[i]
            if c == "\\":
                if i + 1 >= len(self.buf):
                    break  # escape split across chunks
                if self.buf[i + 1] == "u" and i + 6 > len(self.buf):
                    break
                n = 6 if self.buf[i + 1] == "u" else 2
                raw.append(self.buf[i:i + n])
                i += n
                continue
            if c == '"':
                self.done = True
                break
            raw.append(c)
            i += 1
        return json.loads('"' + "".join(raw) + '"')


# $ per million tokens: input, output, cache read, cache write (5-minute TTL = 1.25x input)
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


def usage_cost(model: str, u) -> float:
    pi, po, pr, pw = PRICES.get(model, (0, 0, 0, 0))
    return (u.input_tokens * pi + u.output_tokens * po
            + (getattr(u, "cache_read_input_tokens", 0) or 0) * pr
            + (getattr(u, "cache_creation_input_tokens", 0) or 0) * pw) / 1e6


class _CostMixin:
    """last_cost is per thread: one LLM object serves concurrent calls (feedback, explain, ...),
    each running in its own worker thread, and the caller reads it right after its own call."""

    _tl = threading.local()

    @property
    def last_cost(self) -> float:
        return getattr(self._tl, "cost", 0.0)

    @last_cost.setter
    def last_cost(self, v: float):
        self._tl.cost = v

    def json_with_cost(self, *args, **kwargs) -> tuple[dict, float]:
        out = self.json(*args, **kwargs)
        return out, self.last_cost


KEY_FILE = Path.home() / ".config" / "persona-tutor" / "api_key"


def read_key_file() -> str:
    """The key saved by tutor.setup (mode 600). Read here so every entry point (run.sh, voice.*) finds it."""
    try:
        return KEY_FILE.read_text().strip()
    except OSError:
        return ""


class AnthropicLLM(_CostMixin):
    def __init__(self, model: str, effort: str = "low", key_env: str = "PERSONA_TUTOR_API_KEY"):
        import anthropic

        key = os.environ.get(key_env) or read_key_file()
        if not key:
            raise LLMError(f"no API key: put it in {KEY_FILE} (python -m tutor.setup does this) or set {key_env}")
        self.client = anthropic.Anthropic(api_key=key)
        self.model, self.effort = model, effort

    def json(self, system: str, messages: list, schema: dict, max_tokens: int = 4000) -> dict:
        # Anthropic needs the first message to come from the user
        if not messages or messages[0]["role"] != "user":
            messages = [{"role": "user", "content": "（開始）"}] + messages
        resp = self.client.beta.messages.create(
            model=self.model, max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",  # rescue policy declines
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            cache_control={"type": "ephemeral"},  # also cache the growing conversation prefix
            messages=messages,
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
        )
        self.last_cost = usage_cost(self.model, resp.usage)
        if resp.stop_reason == "refusal":
            raise LLMError(f"refusal: {resp.stop_details}")
        if resp.stop_reason == "max_tokens":
            raise LLMError("max_tokens reached")
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)

    def stream_json(self, system: str, messages: list, schema: dict, on_text, max_tokens: int = 4000) -> dict:
        """Like json(), but calls on_text(chunk) for each streamed piece of the JSON text."""
        if not messages or messages[0]["role"] != "user":
            messages = [{"role": "user", "content": "（開始）"}] + messages
        with self.client.beta.messages.stream(
            model=self.model, max_tokens=max_tokens,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            cache_control={"type": "ephemeral"},
            messages=messages,
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
        ) as stream:
            for chunk in stream.text_stream:
                on_text(chunk)
            resp = stream.get_final_message()
        self.last_cost = usage_cost(self.model, resp.usage)
        if resp.stop_reason == "refusal":
            raise LLMError(f"refusal: {resp.stop_details}")
        if resp.stop_reason == "max_tokens":
            raise LLMError("max_tokens reached")
        return json.loads("".join(b.text for b in resp.content if b.type == "text"))


class OllamaLLM(_CostMixin):  # local: last_cost stays 0
    def __init__(self, model: str, host: str = "http://127.0.0.1:11434"):
        self.model, self.host = model, host

    def json(self, system: str, messages: list, schema: dict, max_tokens: int = 4000) -> dict:
        body = json.dumps({
            "model": self.model, "stream": False, "format": schema, "think": False,
            "messages": [{"role": "system", "content": system}] + messages,
            "options": {"temperature": 0.7, "num_predict": max_tokens}, "keep_alive": "30m",
        }).encode()
        req = urllib.request.Request(f"{self.host}/api/chat", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(json.loads(r.read())["message"]["content"])

    def stream_json(self, system: str, messages: list, schema: dict, on_text, max_tokens: int = 4000) -> dict:
        body = json.dumps({
            "model": self.model, "stream": True, "format": schema, "think": False,
            "messages": [{"role": "system", "content": system}] + messages,
            "options": {"temperature": 0.7, "num_predict": max_tokens}, "keep_alive": "30m",
        }).encode()
        req = urllib.request.Request(f"{self.host}/api/chat", body, {"Content-Type": "application/json"})
        parts = []
        with urllib.request.urlopen(req, timeout=300) as r:
            for ln in r:
                chunk = json.loads(ln).get("message", {}).get("content", "")
                if chunk:
                    parts.append(chunk)
                    on_text(chunk)
        return json.loads("".join(parts))


def make_llm(cfg: dict):
    if cfg["provider"] == "anthropic":
        return AnthropicLLM(cfg["model"], cfg.get("effort", "low"), cfg.get("key_env", "PERSONA_TUTOR_API_KEY"))
    if cfg["provider"] == "ollama":
        return OllamaLLM(cfg["model"], cfg.get("host", "http://127.0.0.1:11434"))
    raise ValueError(f"unknown provider {cfg['provider']}")

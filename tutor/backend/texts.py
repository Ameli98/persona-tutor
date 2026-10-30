"""Texts the learner imports to study from (novels, game scripts as .txt): <data_dir>/texts/<id>/.

A book is far too long to put in a prompt, so it is cut into passages and searched by meaning: embeddings run locally
(multilingual-e5-small on the CPU: free, nothing leaves the machine, no GPU needed next to STT and TTS). Only passages
the learner picks, or the tutor finds for them, go to the Claude API.
"""
import json
import random
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

import numpy as np

MODEL = "intfloat/multilingual-e5-small"
TOOL_NAME = "search_texts"
MAX_BYTES = 5 * 1024 * 1024
CHUNK_CHARS = 400
MAX_LIMIT = 10
_SPEAKER = re.compile(r"^\s*([^\s:：「『（(]{1,16})\s*[:：]\s*(\S.*)$")
_NOTATION = re.compile(r"《[^》]*》|［＃[^］]*］|｜")     # ruby and editor's notes in Aozora Bunko files


class Embedder:
    """Mean-pooled, normalized e5 embeddings. e5 wants "query: " / "passage: " prefixes."""

    def __init__(self, model: str = MODEL):
        from transformers import AutoModel, AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(model)
        self.net = AutoModel.from_pretrained(model).eval().to("cpu")
        self.lock = threading.Lock()

    def __call__(self, texts: list[str], kind: str, on_progress=None) -> np.ndarray:
        import torch
        out = []
        for i in range(0, len(texts), 32):
            with self.lock, torch.inference_mode():
                batch = self.tok([f"{kind}: {t}" for t in texts[i:i + 32]], padding=True, truncation=True,
                                 max_length=256, return_tensors="pt")
                mask = batch["attention_mask"].unsqueeze(-1)
                vec = (self.net(**batch).last_hidden_state * mask).sum(1) / mask.sum(1)
                out.append(torch.nn.functional.normalize(vec, dim=1).numpy())
            if on_progress:
                on_progress(min(i + 32, len(texts)) / len(texts))
        return np.vstack(out) if out else np.zeros((0, 384), dtype=np.float32)


def decode(raw: bytes) -> str:
    """UTF-8 or Shift-JIS, the two encodings Japanese .txt files come in. ValueError for anything else."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError("not UTF-8 or Shift-JIS")


def clean_lines(text: str) -> list[str]:
    """Non-empty lines without Aozora notation; `name: line` and `name：line` become `name：line`."""
    lines = []
    for line in _NOTATION.sub("", text).splitlines():
        line = line.strip()
        if line:
            m = _SPEAKER.match(line)
            lines.append(f"{m.group(1)}：{m.group(2)}" if m else line)
    return lines


def speakers(lines: list[str]) -> list[str]:
    """Names with more than one line, most frequent first (a one-off match is more likely a colon in the prose)."""
    counts: dict = {}
    for line in lines:
        if (m := _SPEAKER.match(line)):
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return [k for k, v in sorted(counts.items(), key=lambda x: -x[1]) if v > 1]


def chunks_of(lines: list[str], size: int = CHUNK_CHARS) -> list[str]:
    """Passages of about `size` characters that end on a line boundary, so nobody's line is cut in two. A single line
    longer than `size` (a paragraph of a novel) is split after a sentence."""
    pieces = []
    for line in lines:
        while len(line) > size:
            cut = line.rfind("。", 0, size) + 1 or size
            pieces.append(line[:cut])
            line = line[cut:]
        if line:
            pieces.append(line)
    out, current = [], ""
    for piece in pieces:
        if current and len(current) + len(piece) > size:
            out.append(current)
            current = ""
        current += ("\n" if current else "") + piece
    return out + [current] if current else out


class Library:
    def __init__(self, root: Path, make_embedder=Embedder):
        self.root, self.make_embedder = Path(root), make_embedder
        self.embedder = None
        self.lock = threading.Lock()
        self.cache: dict = {}    # id → (chunks, vectors)
        self.progress: dict = {}

    def _embedder(self):
        with self.lock:
            if self.embedder is None:
                self.embedder = self.make_embedder()
            return self.embedder

    def _meta(self, wid: str) -> dict:
        return json.loads((self.root / wid / "meta.json").read_text(encoding="utf-8"))

    def _save_meta(self, meta: dict):
        (self.root / meta["id"] / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    def works(self) -> list[dict]:
        metas = [self._meta(d.name) for d in self.root.iterdir() if (d / "meta.json").exists()] if self.root.exists() else []
        return [{**m, "progress": self.progress.get(m["id"])} for m in sorted(metas, key=lambda m: m["created"], reverse=True)]

    def ready(self) -> list[dict]:
        return [m for m in self.works() if m["status"] == "ready"]

    def add(self, title: str, raw: bytes, script_ratio=None) -> dict:
        """Store a text and its passages; index() makes it searchable. ValueError if it can't be read."""
        lines = clean_lines(decode(raw))
        chunks = chunks_of(lines)
        if not chunks:
            raise ValueError("no text")
        meta = {"id": uuid.uuid4().hex[:12], "title": title, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "indexing",
                "chars": sum(map(len, lines)), "chunks": len(chunks), "speakers": speakers(lines)[:20], "studied": [], "error": "",
                "other_language": bool(script_ratio) and script_ratio("".join(lines)[:5000]) < 0.3}
        (self.root / meta["id"]).mkdir(parents=True)
        (self.root / meta["id"] / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
        self._save_meta(meta)
        return meta

    def index(self, wid: str):
        """Embed a text's passages (slow on a whole book: run in the background). Failures are recorded, not raised."""
        meta = self._meta(wid)
        try:
            chunks = json.loads((self.root / wid / "chunks.json").read_text(encoding="utf-8"))
            vectors = self._embedder()(chunks, "passage", lambda p: self.progress.__setitem__(wid, round(p, 3)))
            np.save(self.root / wid / "vectors.npy", vectors)
            meta["status"] = "ready"
        except Exception as e:  # noqa: BLE001 - shown on the page; the rest of the tutor doesn't depend on it
            meta["status"], meta["error"] = "error", f"{type(e).__name__}: {e}"
        self.progress.pop(wid, None)
        if (self.root / wid).exists():   # it may have been deleted meanwhile
            self._save_meta(meta)

    def resume(self):
        """Texts left half-indexed when the tutor last stopped."""
        for m in self.works():
            if m["status"] == "indexing":
                self.index(m["id"])

    def delete(self, wid: str):
        self.cache.pop(wid, None)
        shutil.rmtree(self.root / wid, ignore_errors=True)

    def _load(self, wid: str):
        if wid not in self.cache:
            chunks = json.loads((self.root / wid / "chunks.json").read_text(encoding="utf-8"))
            self.cache[wid] = (chunks, np.load(self.root / wid / "vectors.npy"))
        return self.cache[wid]

    def search(self, query: str, limit: int = 3, work: str | None = None) -> list[dict]:
        """The closest passages, best first. There is always a best one, related or not: whoever reads them judges."""
        works = [m for m in self.ready() if not work or work in (m["id"], m["title"])]
        if not works or not query.strip():
            return []
        q = self._embedder()([query], "query")[0]
        hits = []
        for m in works:
            chunks, vectors = self._load(m["id"])
            scores = vectors @ q
            for i in np.argsort(-scores)[:limit]:
                hits.append({"work": m["id"], "title": m["title"], "chunk": int(i), "text": chunks[i],
                             "score": round(float(scores[i]), 3), "studied": int(i) in m["studied"]})
        return sorted(hits, key=lambda h: -h["score"])[:limit]

    def random_passage(self, work: str | None = None) -> dict | None:
        """A passage not studied yet if there is one, for "surprise me"."""
        works = [m for m in self.ready() if not work or work == m["id"]]
        if not works:
            return None
        m = random.choice(works)
        chunks = self._load(m["id"])[0]
        fresh = [i for i in range(len(chunks)) if i not in m["studied"]] or list(range(len(chunks)))
        i = random.choice(fresh)
        return {"work": m["id"], "title": m["title"], "chunk": i, "text": chunks[i], "score": None, "studied": i in m["studied"]}

    def scene(self, wid: str, chunk: int) -> tuple[dict, str]:
        """(meta, the passage with one on each side), so a lesson sees the whole scene."""
        meta = self._meta(wid)
        chunks = self._load(wid)[0]
        if not 0 <= chunk < len(chunks):
            raise IndexError(chunk)
        return meta, "\n".join(chunks[max(0, chunk - 1):chunk + 2])

    def mark_studied(self, wid: str, chunk: int):
        meta = self._meta(wid)
        if chunk not in meta["studied"]:
            meta["studied"].append(chunk)
            self._save_meta(meta)


def scene_scenario(meta: dict) -> dict:
    """A practice topic for a scene from an imported text; the lesson carries the passage itself."""
    return {"id": f"text_{meta['id']}", "title": meta["title"], "titles": {},
            "setting": "The learner just studied a scene from a text they chose. You read it too, and you're chatting about it as yourself, not acting it out.",
            "goal": "Talk about the scene and use what the lesson taught",
            "angles": ["what happens in the scene", "how the characters feel and why", "what the learner would have done"]}


def tool_definition(titles: list[str]) -> dict:
    return {
        "name": TOOL_NAME,
        "description": (
            "Search the texts the learner imported, by meaning, in any language: what happens, what a character says, "
            "where something is mentioned. Returns the closest passages, best first, with their title. The closest may "
            "still be unrelated: read them and judge. Imported texts: " + "; ".join(titles)),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for."},
                "work": {"type": "string", "enum": titles, "description": "Only this text. Omit to search all."},
                "limit": {"type": "integer", "description": f"How many passages, 1–{MAX_LIMIT}. Default 5."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
        # streamed request: inputs arrive unvalidated, run_tool checks them
        "eager_input_streaming": True,
    }


def run_tool(library: Library, args) -> tuple[str, bool]:
    """Bad input becomes an error result the model can correct, never an exception."""
    if not isinstance(args, dict) or not isinstance(args.get("query"), str) or not args["query"].strip():
        return "INVALID_JSON: the input must be an object like {\"query\": \"the argument at the station\", \"limit\": 5}", True
    limit = args.get("limit", 5)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        return f"limit must be an integer from 1 to {MAX_LIMIT}", True
    work = args.get("work") or None
    if work and work not in [m["title"] for m in library.ready()]:
        return f"unknown text {work!r}", True
    rows = [{k: h[k] for k in ("title", "text")} for h in library.search(args["query"], limit, work)]
    return json.dumps({"passages": rows, "count": len(rows)}, ensure_ascii=False), False

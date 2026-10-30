"""The learner's mistakes, one row per live correction (<data_dir>/mistakes.db, SQLite), and the
`lookup_past_mistakes` tool the tutor can call to talk about them.

Rows come from the per-turn feedback (said / corrected / category / reason). The learner memory
(memory.py) keeps a summary of recurring mistakes; this table keeps the concrete sentences, which is what
the tutor needs when the learner asks "what do I keep getting wrong?" or wants practice on it.
"""
import json
import sqlite3
import time
from pathlib import Path

TOOL_NAME = "lookup_past_mistakes"
MAX_LIMIT = 20


def connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE IF NOT EXISTS mistakes (
        id INTEGER PRIMARY KEY, created TEXT NOT NULL, session TEXT, said TEXT NOT NULL,
        corrected TEXT NOT NULL, category TEXT NOT NULL, reason TEXT)""")
    return con


def add(db: Path, said: str, corrected: str, category: str, reason: str = "", session: str = "",
        created: str | None = None) -> int:
    """Returns the row's id."""
    with connect(db) as con:
        cur = con.execute("INSERT INTO mistakes (created, session, said, corrected, category, reason) VALUES (?, ?, ?, ?, ?, ?)",
                    (created or time.strftime("%Y-%m-%d %H:%M:%S"), session, said, corrected, category, reason))
        return cur.lastrowid


def delete(db: Path, row: int):
    with connect(db) as con:
        con.execute("DELETE FROM mistakes WHERE id = ?", (row,))


def lookup(db: Path, category: str | None = None, limit: int = 5) -> list[dict]:
    """Most recent first."""
    if not db.exists():
        return []
    with connect(db) as con:
        con.row_factory = sqlite3.Row
        q, args = "SELECT created, said, corrected, category, reason FROM mistakes", []
        if category:
            q, args = q + " WHERE category = ?", [category]
        rows = con.execute(q + " ORDER BY created DESC, id DESC LIMIT ?", [*args, limit]).fetchall()
    return [dict(r) for r in rows]


def listing(db: Path) -> list[dict]:
    """Every row with its id, newest first, for the Memory page (the tool's lookup leaves ids out)."""
    if not db.exists():
        return []
    with connect(db) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT id, created, said, corrected, category, reason FROM mistakes "
                                             "ORDER BY created DESC, id DESC")]


def result_count(content: str) -> int:
    return json.loads(content)["count"]


def tool_definition(categories: dict) -> dict:
    """The tool as the Claude API takes it; categories come from the target-language module."""
    kinds = "; ".join(f"{k}: {v}" for k, v in categories.items())
    return {
        "name": TOOL_NAME,
        "description": (
            "Look up mistakes the learner actually made in earlier practice sessions, as recorded by the live "
            "corrections: what they said, the corrected sentence, the kind of mistake and why. Newest first. "
            "Use it to ground personal feedback, advice on what to work on, or targeted practice in sentences the "
            "learner really said, instead of general tips. Returns an empty list when nothing matches. "
            "Kinds of mistake: " + kinds),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": list(categories),
                             "description": "Only this kind of mistake. Omit for all kinds."},
                "limit": {"type": "integer", "description": f"How many to return, 1–{MAX_LIMIT}. Default 5."},
            },
            "additionalProperties": False,
        },
        "strict": True,
        # streamed request: inputs arrive unvalidated, run_tool checks them
        "eager_input_streaming": True,
    }


def run_tool(db: Path, categories: dict, name: str, args) -> tuple[str, bool]:
    """Execute a tool call. Returns (tool_result content, is_error); bad input becomes an error result the model
    can correct, never an exception."""
    if name != TOOL_NAME:
        return f"unknown tool {name}", True
    if not isinstance(args, dict):
        return "INVALID_JSON: the input must be an object like {\"category\": \"particle\", \"limit\": 5}", True
    category = args.get("category") or None
    if category is not None and category not in categories:
        return f"unknown category {category!r}; use one of: {', '.join(categories)}", True
    limit = args.get("limit", 5)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        return f"limit must be an integer from 1 to {MAX_LIMIT}", True
    rows = lookup(db, category, limit)
    return json.dumps({"mistakes": rows, "count": len(rows)}, ensure_ascii=False), False

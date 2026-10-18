"""Persist practice sessions under <data_dir>/sessions (runtime/ is wiped on every start)."""
import json
import shutil
import time
from pathlib import Path


class SessionRecord:
    """<data_dir>/sessions/<YYYYmmdd-HHMMSS>_<scenario>/{session.json, audio/}. Written after every turn."""

    def __init__(self, root: Path, session_id: str, scenario: dict, models: dict):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.dir = root / "sessions" / f"{stamp}_{scenario['id']}"
        (self.dir / "audio").mkdir(parents=True, exist_ok=True)
        self.data = {
            "id": session_id, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "ended": None,
            "scenario": {k: scenario.get(k) for k in ("id", "title", "titles")},
            "models": models, "cost_usd": 0.0, "turns": [],
        }
        self._n = 0

    def _keep(self, src: Path, prefix: str) -> str:
        name = f"{prefix}_{self._n:03d}{src.suffix}"
        self._n += 1
        shutil.copy2(src, self.dir / "audio" / name)
        return f"audio/{name}"

    def add_user(self, text: str, lang: str, wav: Path) -> dict:
        turn = {"role": "user", "text": text, "lang": lang, "audio": self._keep(wav, "user"), "feedback": None}
        self.data["turns"].append(turn)
        self.save()
        return turn

    def add_tutor(self, out: dict, text: str, audio_files: list[Path]) -> dict:
        turn = {"role": "tutor", "emotion": out["emotion"], "text": text, "translation": out["translation"],
                "note": out.get("note", ""), "closing": out.get("closing", False),
                "audio": [self._keep(f, "tutor") for f in audio_files]}
        self.data["turns"].append(turn)
        self.save()
        return turn

    def set_feedback(self, turn: dict, fb: dict):
        turn["feedback"] = fb
        self.save()

    def finish(self, cost: float):
        self.data["ended"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.data["cost_usd"] = round(cost, 4)
        self.save()

    def save(self):
        tmp = self.dir / "session.json.tmp"
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.dir / "session.json")

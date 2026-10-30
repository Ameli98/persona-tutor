"""Synthesized sentences kept on disk (<data_dir>/tts_cache/), for fixed text the learner replays: lesson phrases,
dialogues, warm-up sentences. Only verified audio goes in, so a misread sentence gets another try next time. The
tutor's live lines don't come here: they hardly ever repeat."""
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

MAX_ITEMS = 2000     # ~200 MB; the least recently used go first


def voice_id(voice: dict) -> str:
    """Changes when the voice is retrained, so old audio isn't replayed in a new voice."""
    return "|".join(f"{voice[k]}:{Path(voice[k]).stat().st_mtime_ns}" for k in ("sovits", "gpt"))


class TTSCache:
    def __init__(self, folder: Path, voice: str, max_items: int = MAX_ITEMS):
        self.folder, self.voice, self.max_items = Path(folder), voice, max_items
        self.folder.mkdir(parents=True, exist_ok=True)

    def key(self, text: str, emotion: str) -> str:
        return hashlib.sha256(f"{self.voice}\n{emotion}\n{text}".encode()).hexdigest()[:32]

    def get(self, text: str, emotion: str, audio_dir: Path) -> dict | None:
        """The stored segment with its audio copied to audio_dir (what /audio serves), or None."""
        k = self.key(text, emotion)
        wav, meta = self.folder / f"{k}.wav", self.folder / f"{k}.json"
        if not (wav.exists() and meta.exists()):
            return None
        out = Path(audio_dir) / f"{uuid.uuid4().hex[:12]}.wav"
        shutil.copy(wav, out)
        os.utime(wav)
        return {**json.loads(meta.read_text(encoding="utf-8")), "audio": f"/audio/{out.name}", "cached": True}

    def put(self, seg: dict, wav: Path):
        k = self.key(seg["text"], seg["emotion"])
        shutil.copy(wav, self.folder / f"{k}.wav")
        (self.folder / f"{k}.json").write_text(json.dumps({x: v for x, v in seg.items() if x != "audio"}, ensure_ascii=False),
                                               encoding="utf-8")
        self._prune()

    def _prune(self):
        wavs = sorted(self.folder.glob("*.wav"), key=lambda p: p.stat().st_mtime)
        for old in wavs[:max(0, len(wavs) - self.max_items)]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)

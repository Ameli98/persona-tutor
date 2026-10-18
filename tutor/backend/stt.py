"""Speech-to-text with faster-whisper."""
import subprocess
from pathlib import Path

from faster_whisper import WhisperModel


class STT:
    def __init__(self, model: str, compute_type: str = "float16", target: str = "ja", native: str = "en"):
        """target / native: Whisper language codes of the practised language and the learner's own."""
        self.model = WhisperModel(model, device="cuda", compute_type=compute_type)
        self.target, self.native = target, native

    def transcribe(self, path: Path, vad: bool = False) -> str:
        """Transcribe as the target language (practice attempts, TTS verification)."""
        # vad=True for user recordings (leading/trailing silence around push-to-talk);
        # False for short synthesized clips, which VAD can clip
        segs, _ = self.model.transcribe(str(path), language=self.target, beam_size=5,
                                        vad_filter=vad, without_timestamps=True,
                                        condition_on_previous_text=False)
        return "".join(s.text for s in segs).strip()

    def transcribe_auto(self, path: Path, context: str = "") -> tuple[str, str]:
        """For user turns: they may answer in the target language or ask in their own.
        Returns (text, "target"|"native").

        context = the tutor's previous line, given to Whisper as initial_prompt: knowing the topic it
        hears topic words correctly more often (tested on real Japanese recordings)."""
        prompt = context or None
        segs, info = self.model.transcribe(str(path), language=None, beam_size=5, vad_filter=True,
                                           without_timestamps=True, condition_on_previous_text=False,
                                           initial_prompt=prompt)
        lang = info.language
        if lang not in (self.target, self.native):
            # e.g. a short clip detected as English: re-run as whichever of the two is more likely
            probs = dict(info.all_language_probs or [])
            lang = self.native if probs.get(self.native, 0) > probs.get(self.target, 0) else self.target
            segs, _ = self.model.transcribe(str(path), language=lang, beam_size=5, vad_filter=True,
                                            without_timestamps=True, condition_on_previous_text=False,
                                            initial_prompt=prompt)
        text = "".join(s.text for s in segs).strip()
        return ("" if is_hallucination(text) else text), ("target" if lang == self.target else "native")


# Whisper's well-known output on near-silent or noisy clips (learned from video subtitles).
# Specific phrases only, so a real sentence about videos or subtitles still gets through.
HALLUCINATIONS = ("次の動画", "ご視聴ありがとう", "チャンネル登録", "高評価", "請不吝點贊", "訂閱", "字幕由", "感謝觀看")


def is_hallucination(text: str) -> bool:
    return any(h in text for h in HALLUCINATIONS)


def to_wav16k(src: Path, dst: Path) -> Path:
    """Browser recordings (webm/opus, mp4/aac) → 16 kHz mono wav."""
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src),
                    "-ac", "1", "-ar", "16000", str(dst)], check=True)
    return dst

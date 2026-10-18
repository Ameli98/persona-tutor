"""GPT-SoVITS synthesis with emotion-based reference selection and ASR verification."""
import os
import random
import sys
import tempfile
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch

from .quiet import install as _install_quiet, quiet



@dataclass
class Ref:
    path: str
    text: str


@dataclass
class SynthResult:
    text: str
    emotion: str
    audio: Path
    ref: str
    verified: bool
    attempts: int
    asr: str
    cer: float
    tried: list = field(default_factory=list)


class TTS:
    def __init__(self, gsv_root: Path, sovits: Path, gpt: Path, refs_list: Path, version: str = "v2Pro",
                 lang=None):
        """lang: target-language module (tutor/lang/*): its CODE goes to GPT-SoVITS, compare() checks the ASR."""
        if lang is None:
            from ..lang import ja as lang
        self.lang = lang
        self.refs = self._load_refs(refs_list)
        self.voice = (str(sovits), str(gpt), str(refs_list))

        # GPT-SoVITS resolves its pretrained paths relative to the repo root
        os.chdir(gsv_root)
        sys.path[:0] = [str(gsv_root), str(gsv_root / "GPT_SoVITS")]
        _install_quiet()  # GPT-SoVITS prints dozens of lines per sentence; keep them off the console
        with quiet():
            from GPT_SoVITS.TTS_infer_pack.TTS import TTS as _TTS, TTS_Config

            self.tts = _TTS(TTS_Config({"custom": {
                "device": "cuda", "is_half": True, "version": version,
                "t2s_weights_path": str(gpt), "vits_weights_path": str(sovits),
                "bert_base_path": "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large",
                "cnhuhbert_base_path": "GPT_SoVITS/pretrained_models/chinese-hubert-base",
            }}))
        # Warm up once: the first run lazily imports GPT_SoVITS.Accel, which sets
        # cudnn.benchmark=True. With benchmark on, every new input length triggers a
        # CPU-side cuDNN algorithm search (~20 s per sentence here); off, it's <1 s.
        warm = Path(tempfile.gettempdir()) / "gsv_warmup.wav"
        ref = self.pick_ref("neutral")
        self._synth_once(ref.text, ref, 0, warm)  # any sentence works; the reference's own text is in the right language
        warm.unlink(missing_ok=True)

    @staticmethod
    def _load_refs(refs_list: Path) -> dict[str, list[Ref]]:
        refs: dict[str, list[Ref]] = {}
        for line in open(refs_list, encoding="utf-8"):
            path, _, _, text = line.rstrip("\n").split("|")
            emo = Path(path).parent.name  # refs*/<emotion>/<clip>.wav
            refs.setdefault(emo, []).append(Ref(path, text))
        return refs

    def use_voice(self, sovits: Path, gpt: Path, refs_list: Path):
        """Swap to another character's weights and reference clips (a few seconds; no-op if current).
        Swapping in place keeps GPU memory flat instead of loading a second model."""
        voice = (str(sovits), str(gpt), str(refs_list))
        if voice == self.voice:
            return
        with quiet():
            self.tts.init_t2s_weights(str(gpt))
            self.tts.init_vits_weights(str(sovits))
        self.tts.prompt_cache["ref_audio_path"] = None  # cached prompt features belong to the old voice
        self.refs = self._load_refs(refs_list)
        self.voice = voice
        torch.cuda.empty_cache()

    def pick_ref(self, emotion: str, exclude: set = frozenset()) -> Ref:
        pool = self.refs.get(emotion) or self.refs["neutral"]
        choices = [r for r in pool if r.path not in exclude] or pool
        return random.choice(choices)

    def _synth_once(self, text: str, ref: Ref, seed: int, out: Path) -> Path:
        torch.backends.cudnn.benchmark = False  # see __init__
        with quiet():
            results = list(self.tts.run({
                "text": text, "text_lang": self.lang.CODE, "ref_audio_path": ref.path,
                "prompt_text": ref.text, "prompt_lang": self.lang.CODE,
                "top_k": 15, "top_p": 1.0, "temperature": 1.0,
                "text_split_method": "cut0",  # caller already split into sentences
                "batch_size": 1, "seed": seed,
            }))
        sr = results[-1][0]
        return _write(out, sr, np.concatenate([a for _, a in results]).astype(np.int16))

    def _synth_batch(self, texts: list[str], ref: Ref, seed: int, batch_size: int) -> tuple[int, list] | None:
        """Several sentences in one run (batched autoregressive decoding); one int16 array per text.
        GPT-SoVITS normally concatenates the outputs, so its postprocess step is swapped for one that
        keeps them apart. None if the fragments don't map 1:1 onto texts."""
        torch.backends.cudnn.benchmark = False  # see __init__
        tts, got = self.tts, {}

        def keep_apart(audio, sr, batch_index_list=None, speed_factor=1.0, split_bucket=True, *_, **__):
            frags = tts.recovery_order(audio, batch_index_list) if split_bucket else sum(audio, [])
            out = []
            for a in frags:
                a = a.float()
                peak = a.abs().max()
                a = ((a / peak if peak > 1 else a).cpu().numpy() * 32767).astype(np.int16)
                out.append(np.concatenate([a, np.zeros(int(sr * 0.3), np.int16)]))  # same tail as say()
            got["sr"], got["frags"] = sr, out
            return sr, np.zeros(1, np.int16)

        tts.audio_postprocess = keep_apart  # instance attribute shadows the method
        try:
            with quiet():
                list(tts.run({
                    "text": "\n".join(texts), "text_lang": self.lang.CODE, "ref_audio_path": ref.path,
                    "prompt_text": ref.text, "prompt_lang": self.lang.CODE,
                    "top_k": 15, "top_p": 1.0, "temperature": 1.0,
                    "text_split_method": "cut0",  # one fragment per line
                    "batch_size": batch_size, "split_bucket": True, "parallel_infer": True,
                    "fragment_interval": 0, "seed": seed,
                }))
        finally:
            del tts.audio_postprocess
        if len(got.get("frags", [])) != len(texts):
            return None
        return got["sr"], got["frags"]

    def say_many(self, items: list[tuple[str, str]], out_dir: Path, stt, max_attempts: int = 3,
                 max_cer: float = 0.05, batch_size: int = 8) -> list[SynthResult]:
        """Batch version of say() for offline use (review videos): sentences with the same emotion are
        synthesized together, then each is ASR-checked; only the failures go through say()'s retries."""
        results: list = [None] * len(items)
        groups: dict[str, list[int]] = {}
        for i, (text, emo) in enumerate(items):
            if len(text) < 6:  # GPT-SoVITS merges very short lines into their neighbours
                results[i] = self.say(text, emo, out_dir, stt, max_attempts, max_cer)
            else:
                groups.setdefault(emo, []).append(i)
        for emo, idx in groups.items():
            ref = self.pick_ref(emo)
            batch = self._synth_batch([items[i][0] for i in idx], ref, random.randint(0, 2**31 - 1), batch_size)
            for k, i in enumerate(idx):
                text = items[i][0]
                if batch is None:
                    results[i] = self.say(text, emo, out_dir, stt, max_attempts, max_cer)
                    continue
                out = _write(out_dir / f"{uuid.uuid4().hex[:12]}.wav", batch[0], batch[1][k])
                asr = stt.transcribe(out)
                err = self.lang.compare(text, asr)["cer"]
                if err <= max_cer:
                    results[i] = SynthResult(text, emo, out, Path(ref.path).name, True, 1, asr, err)
                    continue
                out.unlink(missing_ok=True)
                r = self.say(text, emo, out_dir, stt, max_attempts, max_cer)
                r.attempts += 1
                results[i] = r
        return results

    def say(self, text: str, emotion: str, out_dir: Path, stt=None,
            max_attempts: int = 3, max_cer: float = 0.05) -> SynthResult:
        """Synthesize one sentence; if stt is given, re-synthesize until the ASR reading matches.

        Attempts 1–2 change the seed; attempt 3 also switches to another reference clip.
        Returns the best attempt (lowest CER), with verified=False if none passed.
        """
        ref = self.pick_ref(emotion)
        best, tried = None, []
        for attempt in range(1, max_attempts + 1):
            if attempt == 3:
                ref = self.pick_ref(emotion, exclude={ref.path})
            out = out_dir / f"{uuid.uuid4().hex[:12]}.wav"
            self._synth_once(text, ref, random.randint(0, 2**31 - 1), out)
            if stt is None:
                return SynthResult(text, emotion, out, Path(ref.path).name, False, attempt, "", -1.0)
            asr = stt.transcribe(out)
            err = self.lang.compare(text, asr)["cer"]
            tried.append({"attempt": attempt, "ref": Path(ref.path).name, "asr": asr, "cer": err})
            if best is None or err < best.cer:
                if best is not None:
                    best.audio.unlink(missing_ok=True)
                best = SynthResult(text, emotion, out, Path(ref.path).name, err <= max_cer, attempt, asr, err)
            else:
                out.unlink(missing_ok=True)
            if err <= max_cer:
                break
        best.tried = tried
        best.attempts = len(tried)
        return best


def _write(out: Path, sr: int, audio: np.ndarray) -> Path:
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.tobytes())
    return out

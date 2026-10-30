"""The on-disk TTS cache and which lesson text gets synthesized ahead (no GPU)."""
from tutor.backend import lesson
from tutor.backend.tts_cache import TTSCache, voice_id

SEG = {"text": "はい", "emotion": "neutral", "ref": "a.wav", "verified": True, "attempts": 1, "asr": "はい", "cer": 0.0,
       "audio": "/audio/x.wav"}


def wav(tmp_path, name="x.wav", data=b"RIFF"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_put_then_get_copies_audio_and_marks_cached(tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    c = TTSCache(tmp_path / "c", "voice")
    assert c.get("はい", "neutral", audio) is None
    c.put(SEG, wav(tmp_path))
    seg = c.get("はい", "neutral", audio)
    assert seg["cached"] and seg["ref"] == "a.wav" and seg["audio"] != SEG["audio"]
    assert (audio / seg["audio"].rsplit("/", 1)[1]).read_bytes() == b"RIFF"
    assert c.get("はい", "happy", audio) is None                       # another emotion is another entry


def test_another_voice_misses(tmp_path):
    TTSCache(tmp_path / "c", "voice").put(SEG, wav(tmp_path))
    assert TTSCache(tmp_path / "c", "retrained").get("はい", "neutral", tmp_path) is None


def test_voice_id_changes_when_retrained(tmp_path):
    v = {"sovits": str(wav(tmp_path, "s.pth")), "gpt": str(wav(tmp_path, "g.ckpt"))}
    before = voice_id(v)
    import os
    os.utime(v["gpt"], (1, 1))
    assert voice_id(v) != before


def test_oldest_are_dropped_over_the_cap(tmp_path):
    import os
    c = TTSCache(tmp_path / "c", "voice", max_items=2)
    for i, text in enumerate(["一", "二"]):
        c.put({**SEG, "text": text}, wav(tmp_path))
        os.utime(c.folder / f"{c.key(text, 'neutral')}.wav", (i + 1, i + 1))
    c.put({**SEG, "text": "三"}, wav(tmp_path))
    assert c.get("一", "neutral", tmp_path) is None
    assert c.get("二", "neutral", tmp_path) and c.get("三", "neutral", tmp_path)
    assert len(list(c.folder.glob("*.json"))) == 2


def test_lesson_spoken_lists_every_line_with_a_play_button():
    les = {"phrases": [{"text": "A"}], "grammar": {"examples": [{"text": "B"}]}, "dialogue": [{"text": "C"}, {"text": "A"}]}
    assert lesson.spoken(les) == ["A", "B", "C", "A"]

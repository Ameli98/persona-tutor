"""Voice pipeline pieces that need no GPU: long-recording split logic and clip checks."""
from tutor.lang import ja
from voice.check import flags_for
from voice.ingest import merge_regions


def test_regions_join_across_short_pauses_only():
    # two lines separated by a 1.2 s pause must stay separate; a 0.3 s breath inside a line is joined
    regions = [(0.0, 2.0), (2.3, 4.5), (5.7, 9.0)]
    assert merge_regions(regions) == [(0.0, 4.5), (5.7, 9.0)]


def test_short_piece_joins_neighbour_across_dramatic_pause():
    # "そうですね……（0.8 s）申し訳ありません": too short alone, joined with the nearer neighbour
    regions = [(0.0, 1.2), (2.0, 4.5), (6.0, 10.0)]
    assert merge_regions(regions)[0] == (0.0, 4.5)


def test_regions_never_exceed_max_length():
    regions = [(i * 2.2, i * 2.2 + 2.0) for i in range(10)]  # continuous speech with 0.2 s gaps
    assert all(b - a <= 10 for a, b in merge_regions(regions))


def test_flags():
    text = "今日はいい天気ですね、散歩にでも行きましょうか"   # ~24 morae in 4 s: a normal speaking rate
    row = {"dur": "4.0", "text": text, "text_src": "given", "cer": "0.9", "hf_db": "-40", "clipped": "0"}
    assert set(flags_for(row, ja)) == {"mismatch", "muffled"}
    ok = {"dur": "4.0", "text": text, "text_src": "asr", "cer": "", "hf_db": "-17", "clipped": "0"}
    slow = {**ok, "dur": "9.5", "text": "はい……"}
    assert "slow_or_nonspeech" in flags_for(slow, ja)
    assert flags_for(ok, ja) == []


def test_transcript_formats(tmp_path):
    from voice.ingest import find_transcripts, load_transcripts
    (tmp_path / "a.csv").write_text("file,text\nsub/clip01.wav,こんにちは\nclip02.ogg,さようなら\n", encoding="utf-8")
    assert load_transcripts(tmp_path / "a.csv") == {"clip01": "こんにちは", "clip02": "さようなら"}
    (tmp_path / "b.tsv").write_text("clip01\tこんにちは\n", encoding="utf-8")          # no header, tab
    assert load_transcripts(tmp_path / "b.tsv") == {"clip01": "こんにちは"}
    (tmp_path / "metadata.csv").write_text("clip01|こんにちは。|こんにちは\n", encoding="utf-8")   # LJSpeech
    assert load_transcripts(tmp_path / "metadata.csv") == {"clip01": "こんにちは。"}
    (tmp_path / "x.list").write_text("/d/clip01.wav|spk|ja|こんにちは\n", encoding="utf-8")       # GPT-SoVITS
    assert load_transcripts(tmp_path / "x.list") == {"clip01": "こんにちは"}


def test_sidecar_transcripts(tmp_path):
    from voice.ingest import find_transcripts
    (tmp_path / "clip03.wav").write_bytes(b"")
    (tmp_path / "clip03.txt").write_text("おはよう\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a transcript", encoding="utf-8")   # no audio of that name
    texts, source = find_transcripts(tmp_path, None)
    assert texts == {"clip03": "おはよう"} and ".txt" in source

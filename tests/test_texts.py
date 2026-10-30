"""Imported texts: reading, passages, the library and its tool (a fake embedder, so no model download)."""
import json

import numpy as np
import pytest

from tutor.backend import lesson, prompts, settings, texts


def fake_embedder():
    """Same words → same vector: enough to test ranking without the model."""
    def embed(items, kind, on_progress=None):
        vecs = np.zeros((len(items), 16), dtype=np.float32)
        for i, x in enumerate(items):
            for c in x.replace("passage: ", "").replace("query: ", ""):
                vecs[i, ord(c) % 16] += 1
            vecs[i] /= np.linalg.norm(vecs[i]) or 1
        return vecs
    return embed


@pytest.fixture
def lib(tmp_path):
    return texts.Library(tmp_path / "texts", make_embedder=fake_embedder)


def test_decode_accepts_utf8_and_shift_jis_and_refuses_the_rest():
    assert texts.decode("吾輩は猫".encode("utf-8")) == "吾輩は猫"
    assert texts.decode("吾輩は猫".encode("utf-8-sig")) == "吾輩は猫"
    assert texts.decode("吾輩は猫".encode("cp932")) == "吾輩は猫"
    with pytest.raises(ValueError):
        texts.decode(bytes(range(128, 256)) * 3)


def test_clean_lines_strips_notation_and_reads_speakers():
    lines = texts.clean_lines("吾輩《わがはい》は｜猫である［＃ここまで］\n\n太郎: こんにちは\n花子：はい\n太郎：ええ\n")
    assert lines == ["吾輩は猫である", "太郎：こんにちは", "花子：はい", "太郎：ええ"]
    assert texts.speakers(lines) == ["太郎"]          # one line isn't enough: it may be a colon in the prose


def test_passages_end_on_line_boundaries_and_long_lines_split_after_a_sentence():
    lines = [f"行{i}" + "あ" * 90 for i in range(10)]
    chunks = texts.chunks_of(lines, 200)
    assert all(len(c) <= 200 for c in chunks)
    assert "\n".join(chunks).split("\n") == lines
    long = texts.chunks_of(["あ" * 150 + "。" + "い" * 150], 200)
    assert long == ["あ" * 150 + "。", "い" * 150]


def test_library_add_index_search_scene_delete(lib):
    meta = lib.add("本", "\n".join(["あ" * 390, "い" * 390, "う" * 390]).encode(), lambda x: 1.0)
    assert meta["status"] == "indexing" and meta["chunks"] == 3 and not meta["other_language"]
    assert lib.search("あ") == []                    # not searchable until indexed
    lib.index(meta["id"])
    assert lib.works()[0]["status"] == "ready"
    hits = lib.search("いいい", 1)
    assert hits[0]["chunk"] == 1 and hits[0]["title"] == "本"
    _, scene = lib.scene(meta["id"], 1)
    assert "あ" in scene and "い" in scene and "う" in scene     # the passage with one on each side
    with pytest.raises(IndexError):
        lib.scene(meta["id"], 99)
    lib.delete(meta["id"])
    assert lib.works() == []


def test_empty_file_and_other_language(lib):
    with pytest.raises(ValueError):
        lib.add("空", b"  \n\n", None)
    assert lib.add("英", b"hello there", lambda x: 0.0)["other_language"]


def test_a_failed_index_is_recorded_not_raised(tmp_path):
    def broken():
        raise RuntimeError("no model")
    lib = texts.Library(tmp_path, make_embedder=broken)
    meta = lib.add("本", "本文".encode())
    lib.index(meta["id"])
    assert lib.works()[0]["status"] == "error" and "no model" in lib.works()[0]["error"]


def test_studied_passages_are_marked_and_random_prefers_new_ones(lib):
    meta = lib.add("本", "\n".join(["あ" * 390, "い" * 390]).encode())
    lib.index(meta["id"])
    lib.mark_studied(meta["id"], 0)
    assert lib.search("あああ", 1)[0]["studied"]
    assert all(lib.random_passage()["chunk"] == 1 for _ in range(10))


def test_tool_validates_input_and_returns_passages(lib):
    meta = lib.add("本", "あいう".encode())
    lib.index(meta["id"])
    out, err = texts.run_tool(lib, {"query": "あ"})
    assert not err and json.loads(out)["passages"][0]["title"] == "本"
    for bad in ({}, {"query": " "}, {"query": "あ", "limit": 0}, {"query": "あ", "limit": True}, {"query": "あ", "work": "他"}, "x"):
        assert texts.run_tool(lib, bad)[1], bad


def test_lesson_and_ask_prompts_use_the_passage_and_titles():
    s = settings.load("config.example.yaml")
    sc = texts.scene_scenario({"id": "abc", "title": "本"})
    system = lesson.lesson_system(s, sc, {}, "場面の本文")
    assert "場面の本文" in system and "3–5" in system
    assert "場面の本文" not in lesson.lesson_system(s, sc, {})
    assert "本文" in lesson.brief({"phrases": [], "grammar": {}, "passage": "本文"})
    assert "search_texts" in prompts.ask_system(s, None, ["本"]) and "search_texts" not in prompts.ask_system(s)
    assert prompts.reply_system(s, sc)    # a scene topic has what the practice prompt needs

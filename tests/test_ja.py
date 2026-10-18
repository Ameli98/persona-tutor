"""Japanese language module: sentence splitting, reading comparison, script detection, clickable units."""
from tutor.lang import ja


def test_split_keeps_punctuation_runs_together():
    # "！？" must not leave a lone "？" sentence (it would be sent to TTS on its own)
    assert ja.split_sentences("えっ、来月なんですか！？すごいですね。") == ["えっ、来月なんですか！？", "すごいですね。"]
    assert ja.split_sentences("そう！？") == ["そう！？"]


def test_split_keeps_quotes_closed():
    assert ja.split_sentences("「本当？」って聞いたら、「うん。」って。") == ["「本当？」って聞いたら、「うん。」って。"]


def test_split_long_sentence_on_commas():
    long = "、".join(["これはとても長い文の一部です"] * 6) + "。"
    parts = ja.split_sentences(long, max_len=40)
    assert len(parts) > 1 and "".join(parts) == long and all(len(p) <= 40 + 15 for p in parts)


def test_compare_ignores_spelling_differences():
    # same pronunciation, different kanji/kana choices: ASR spelling must not count as an error
    r = ja.compare("私は研究しています", "わたしはけんきゅうしています")
    assert r["cer"] == 0 and r["score"] == 100


def test_compare_marks_missing_part():
    r = ja.compare("今日はいい天気ですね", "今日はいいですね")
    assert r["score"] < 100 and any(o["op"] == "missing" for o in r["ops"])


def test_script_ratio_ignores_quoted_examples():
    chinese = "「要求しました」太生硬，口語會用「〜させるように言われました」的被動表達。"
    japanese = "「効果」は「精度」にしたほうが自然です。"
    assert ja.script_ratio(chinese) < 0.3 <= ja.script_ratio(japanese)


def test_tokens_attach_auxiliaries():
    units = [t["surface"] for t in ja.tokens("言われていますね") if t["click"]]
    assert units[0].startswith("言われ")

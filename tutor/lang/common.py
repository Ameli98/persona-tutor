"""Language-independent helpers shared by the language modules."""
import difflib


def cer(ref, hyp) -> float:
    """Edit distance / len(ref) over any sequence (characters, kana, words)."""
    if not ref:
        return 0.0 if not hyp else 1.0
    d = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, hc in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rc != hc))
    return d[len(hyp)] / len(ref)


def compare_units(ref, hyp, joiner: str = "") -> dict:
    """Score and diff segments for display. ref/hyp are sequences of comparison units
    (a kana string for Japanese, a list of words for English, ...).

    ops: equal / missing (in target, not said) / extra (said, not in target) / wrong
    """
    j = joiner.join
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ref, hyp, autojunk=False).get_opcodes():
        op = {"equal": "equal", "delete": "missing", "insert": "extra"}.get(tag, "wrong")
        ops.append({"op": op, "ref": j(ref[i1:i2]), "hyp": j(hyp[j1:j2])})
    err = cer(ref, hyp)
    return {"target_reading": j(ref), "said_reading": j(hyp), "cer": round(err, 3),
            "score": max(0, round(100 * (1 - err))), "ops": ops}

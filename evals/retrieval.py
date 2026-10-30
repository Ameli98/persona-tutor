"""Evaluate text search (texts.py) on a whole novel. Local and free: no API calls.

  python -m evals.retrieval --label v1      # writes evals/results/retrieval_<label>.md

Downloads the book once (public domain, kept under runtime/, not in git). hit@k = the expected words are in one of the
top k passages, with shared words alone as the baseline (mixing the two scored no better, see results/retrieval_v1.md,
so search uses embeddings only). There is no "nothing relates" case: search always returns its closest passages and a person or the
tutor judges them, so only recall matters here.
"""
import argparse
import io
import re
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import yaml

from tutor.backend import settings, texts

HERE = Path(__file__).resolve().parent


def book(url: str) -> bytes:
    """The novel as Shift-JIS bytes, with Aozora's header and footer notes removed."""
    cache = settings.path("runtime") / "eval_cache" / Path(url).name
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(urllib.request.urlopen(url, timeout=60).read())
    with zipfile.ZipFile(io.BytesIO(cache.read_bytes())) as z:
        raw = z.read(next(n for n in z.namelist() if n.endswith(".txt")))
    text = raw.decode("cp932")
    text = text.split("-------------------------------------------------------", 2)[-1]
    return text.split("底本：")[0].encode("cp932")


def word_set(text: str) -> set[str]:
    """Latin words, and bigrams of Japanese / Chinese text (which has no spaces)."""
    out = set()
    for run in re.findall(r"[a-z0-9]+|[\u3040-\u30ff\u4e00-\u9fff]+", text.lower()):
        out |= {run} if run.isascii() else ({run[i:i + 2] for i in range(len(run) - 1)} or {run})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="latest")
    args = ap.parse_args()
    spec = yaml.safe_load((HERE / "retrieval_cases.yaml").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        lib = texts.Library(Path(tmp))
        meta = lib.add("Botchan", book(spec["source"]))
        t0 = time.time()
        lib.index(meta["id"])
        secs = time.time() - t0
        assert lib._meta(meta["id"])["status"] == "ready", lib._meta(meta["id"])
        rows, misses = [], {}
        cases = spec["cases"]
        chunks = lib._load(meta["id"])[0]
        chunk_words = [word_set(c) for c in chunks]
        for name in ("embedding", "shared words"):
            found = {1: 0, 3: 0, 5: 0}
            missed = []
            for c in cases:
                if name == "embedding":
                    top = [h["text"] for h in lib.search(c["q"], 5)]
                else:
                    qw = word_set(c["q"])
                    top = [chunks[i] for i in sorted(range(len(chunks)), key=lambda i: -len(qw & chunk_words[i]))[:5]]
                rank = next((i for i, x in enumerate(top) if c["expect"] in x), None)
                for k in found:
                    found[k] += rank is not None and rank < k
                if rank is None or rank >= 3:
                    missed.append(c["id"])
            n = len(cases)
            rows.append(f"| {name} | {found[1]}/{n} | {found[3]}/{n} | {found[5]}/{n} |")
            misses[name] = missed
    report = "\n".join([f"## retrieval — {args.label}", "", f"{meta['chars']} characters, {meta['chunks']} passages, indexed in {secs:.0f} s on the CPU.", "",
                        "| search | hit@1 | hit@3 | hit@5 |", "|---|---|---|---|", *rows, "",
                        *(f"- {k}, not in the top 3: {', '.join(v) or 'none'}" for k, v in misses.items()), ""])
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / f"retrieval_{args.label}.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()

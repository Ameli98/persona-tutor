"""End-to-end smoke test against a running backend: start a session, then send one spoken turn.

The "user" audio is synthesized by the backend itself (the tutor's voice) and re-encoded as webm,
which is what the browser's MediaRecorder sends. Prints each streamed event with its arrival time.

  python -m tutor.tools.e2e_turn [--scenario work_or_study] [--utterance "..." ...] [--end] [--review]
"""
import argparse
import json
import subprocess
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8765"  # --base to change
KEEP = ("type", "text", "emotion", "verified", "attempts", "verdict", "natural", "natural_rewrite", "feedback",
        "lang", "note", "key", "closing", "message", "rephrased", "cost")


def stream(path, data, headers):
    req = urllib.request.Request(BASE + path, data, headers)
    t0, evs = time.time(), []
    with urllib.request.urlopen(req, timeout=300) as r:
        for ln in r:
            e = json.loads(ln)
            e["_t"] = round(time.time() - t0, 1)
            evs.append(e)
    return evs


def show(tag, evs):
    last_text = None
    for e in evs:
        if e["type"] == "reply_text":  # print only the first growing-text event
            if last_text is None:
                print(f"{tag} {e['_t']:5.1f}s reply_text (first chunk): {e['text'][:30]}")
            last_text = e
            continue
        k = {k: v for k, v in e.items() if k in KEEP}
        print(f"{tag} {e['_t']:5.1f}s {json.dumps(k, ensure_ascii=False)[:200]}")


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--scenario", default="work_or_study")
    ap.add_argument("--utterance", nargs="+", help="what 'you' say (target language); default is a Japanese sample",
                    default=["私の研究は、病気を見つけるAIを作っています。効果はとても高いです、でも計算量が大きすぎます。"])
    ap.add_argument("--end", action="store_true", help="end the session after the turns")
    ap.add_argument("--review", action="store_true", help="then build the review")
    args = ap.parse_args()
    BASE = args.base
    js = {"Content-Type": "application/json"}

    evs = stream("/api/session/start", json.dumps({"scenario": args.scenario}).encode(), js)
    show("START", evs)
    sid = next(e for e in evs if e["type"] == "session")["id"]

    for utt in args.utterance:
        webm = speak(utt, js)
        b = uuid.uuid4().hex
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"session_id\"\r\n\r\n{sid}\r\n"
                f"--{b}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"rec.webm\"\r\n"
                f"Content-Type: audio/webm\r\n\r\n").encode() + webm.read_bytes() + f"\r\n--{b}--\r\n".encode()
        show("TURN ", stream("/api/turn", body, {"Content-Type": f"multipart/form-data; boundary={b}"}))
    if args.end:
        show("END  ", stream("/api/session/end", json.dumps({"session_id": sid}).encode(), js))
    if args.review:
        t0 = time.time()
        req = urllib.request.Request(BASE + "/api/session/review", json.dumps({"session_id": sid}).encode(), js)
        with urllib.request.urlopen(req, timeout=300) as r:
            rv = json.loads(r.read())
        print(f"REVIEW {time.time() - t0:.1f}s cost={rv['cost']} review_cost={rv['review_cost']} dir={rv['dir']}")
        for e in rv["expressions"]:
            print(f"  EXP  {e['said']}  →  {e['better']}  | {e['reason']}")
        for t in rv["turns"]:
            print(f"  SAID {t['said']}\n  FIX  {t.get('corrected')} | {t.get('corrected_reason')}\n  UP   {t.get('upgraded')} | {t.get('upgrade_note')}")


def speak(utt, js):
    """Synthesize the 'user' utterance with the backend's TTS and re-encode as browser-style webm."""
    tmp = Path(tempfile.mkdtemp())
    segs = [e for e in stream("/api/say", json.dumps({"text": utt, "emotion": "neutral"}).encode(), js)
            if e["type"] == "segment"]
    files = []
    for i, s in enumerate(segs):
        f = tmp / f"u{i}.wav"
        urllib.request.urlretrieve(BASE + s["audio"], f)
        files.append(f)
    (tmp / "list.txt").write_text("".join(f"file '{f}'\n" for f in files))
    webm = tmp / "user.webm"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(tmp / "list.txt"), "-c:a", "libopus", str(webm)], check=True)
    return webm


if __name__ == "__main__":
    main()

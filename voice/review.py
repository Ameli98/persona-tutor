"""Step 5: listen to the reference-clip candidates and decide which ones the tutor may use.

  python -m voice.review <voice name> [--port 8767]

Opens a local page (127.0.0.1 only, no GPU needed): per emotion, play each candidate, keep or reject it,
or move it to another emotion; "more clips" lists every other usable clip of that emotion. Decisions go
to review.json; "write references" rebuilds refs/ and refs.list.

What makes a good reference (it sets the tone of everything the voice says):
  - the emotion is clear from this line alone, without the story around it
  - clean, close-mic audio: no breathiness, whisper, effect, muffling (through a door) or background noise
  - one complete sentence, not cut off or interrupted
"""
import argparse
import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from tutor.backend import settings as settings_mod

from .common import EMOTIONS, read_clips, voice_dir
from .select import CANDIDATES_PER_EMOTION, REFS_PER_EMOTION, apply_refs, emotion_of, load_review, save_review

PAGE = Path(__file__).with_name("review.html")


def make_app(name: str, speaker: str) -> FastAPI:
    s = settings_mod.load()
    d = voice_dir(name)
    rows = read_clips(d)
    by_id = {r["id"]: r for r in rows}
    if not rows:
        raise SystemExit(f"no clips in {d}")
    app = FastAPI()

    def clip(r, review):
        dec = review["decisions"].get(r["id"], {})
        return {"id": r["id"], "text": r["text"], "dur": round(float(r["dur"]), 1), "emotion": emotion_of(r, review),
                "auto": r.get("emotion_src") == "auto", "standalone": r.get("standalone") == "true",
                "status": dec.get("status", ""), "source": r.get("source", ""),
                "screen_bad": review.get("screen", {}).get(r["id"], {}).get("bad", False)}

    @app.get("/", response_class=HTMLResponse)
    def page():
        return PAGE.read_text(encoding="utf-8")

    @app.get("/api/state")
    def state():
        review = load_review(d)
        usable = [r for r in rows if not r.get("flags") and r.get("text")]
        cand = {i for ids in review["candidates"].values() for i in ids}
        out = {}
        for emo in EMOTIONS:
            listed = [i for i in review["candidates"].get(emo, []) if emotion_of(by_id[i], review) == emo]
            moved_in = [i for i, x in review["decisions"].items() if i in by_id and emotion_of(by_id[i], review) == emo
                        and i not in listed]
            more = [r for r in usable if emotion_of(r, review) == emo and r["id"] not in cand and r["id"] not in moved_in]
            out[emo] = {"candidates": [clip(by_id[i], review) for i in listed + moved_in],
                        "more": [clip(r, review) for r in more]}
        return {"name": name, "emotions": EMOTIONS, "target": REFS_PER_EMOTION, "per_emotion": CANDIDATES_PER_EMOTION,
                "ui_language": s.cfg.get("ui_language", "en"), "clips": out}

    class Decision(BaseModel):
        id: str
        status: str = ""          # keep | reject | "" (undecided)
        emotion: str | None = None

    @app.post("/api/decide")
    def decide(x: Decision):
        if x.id not in by_id or x.status not in ("keep", "reject", "") or (x.emotion and x.emotion not in EMOTIONS):
            raise HTTPException(400, "bad decision")
        review = load_review(d)
        dec = review["decisions"].get(x.id, {})
        if x.emotion:
            dec["emotion"] = None if x.emotion == by_id[x.id].get("emotion") else x.emotion
        dec["status"] = x.status
        if dec.get("status") or dec.get("emotion"):
            review["decisions"][x.id] = dec
        else:
            review["decisions"].pop(x.id, None)
        save_review(d, review)
        return {"ok": True}

    @app.post("/api/apply")
    def apply():
        picked = apply_refs(d, rows, load_review(d), speaker, s.lang.CODE)
        return {"counts": {e: len(v) for e, v in picked.items()}, "next": next_step(name)}

    @app.get("/clip/{cid}.wav")
    def audio(cid: str):
        if cid not in by_id:
            raise HTTPException(404)
        return FileResponse(d / by_id[cid]["file"], media_type="audio/wav")

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--speaker", help="speaker name for refs.list (default: the voice name)")
    ap.add_argument("--port", type=int, default=8767)
    args = ap.parse_args()
    app = make_app(args.name, args.speaker or args.name)
    print(f"Open http://localhost:{args.port} in your browser and listen to the candidates.\n"
          f"When you're done, press \"Write references\" on the page, then Ctrl+C here.", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    print(f"\nnext: {next_step(args.name)}")


def next_step(name: str) -> str:
    trained = (voice_dir(name) / "sovits.pth").exists()
    return f"python -m voice.screen {name}   (test each reference with the trained voice)" if trained \
        else f"python -m voice.train {name}   (10–15 minutes; you can come back to this page any time)"


if __name__ == "__main__":
    main()

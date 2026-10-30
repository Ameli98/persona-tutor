"""persona-tutor backend (FastAPI, local only).

- Warm-up: shadowing (record → STT → reading comparison), streaming TTS.
- Lesson: a short lesson for the topic (phrases, a grammar point, a model dialogue) pitched by the learner's memory.
- Conversation: the persona leads a scenario (reply LLM, streamed sentence by sentence into TTS) while a
  second LLM call gives feedback on each answer; hints, word explanations, questions in either language.
- Ask: a text chat with the tutor, open at any time, which can look up the learner's past mistakes (ask.py).
- After a session: review (corrected / model versions, key expressions, lesson phrases used), the learner's
  memory updated (data/learner.json, editable on the page), review videos, and a recap of the key expressions
  at the start of the next session.

Messages meant for the learner are sent as keys ({"type": "progress", "key": ..., "args": ...}) and
translated by the web page, so the backend has no UI language.
"""
import asyncio
import json
import random
import re
import shutil
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..video.review_video import MODES, load_review, render_videos, voice_user_lines
from . import ask as ask_mod
from . import lesson as lesson_mod
from . import memory, mistakes, prompts
from . import settings as settings_mod
from .llm import FieldWatcher, LLMError, make_llm
from .progress import SessionRecord
from .review import append_log, build_review, latest_recap, mark_recap
from .session import Session, pick_scenario
from .stt import STT, to_wav16k
from .tts_cache import TTSCache, voice_id

S = settings_mod.load()
CFG = S.cfg
L = S.lang
EMOTIONS = set(prompts.EMOTIONS)
WEB = Path(__file__).resolve().parent.parent / "web"

RUNTIME = settings_mod.path("runtime")    # synthesized audio and uploads; wiped on every start
AUDIO = RUNTIME / "audio"
UPLOADS = RUNTIME / "uploads"
DATA = S.data
SESSIONS = DATA / "sessions"
MISTAKES_DB = DATA / "mistakes.db"   # one row per live correction; the Ask tab's lookup_past_mistakes tool reads it
CATEGORIES = getattr(L, "MISTAKE_CATEGORIES", {"other": "any mistake"})

state: dict = {"sessions": {}, "records": {}, "lessons": {}, "explain_cache": {}, "say_locks": {}, "presynth": None}
# one GPU, two models: never run STT and TTS at the same time
gpu_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    shutil.rmtree(RUNTIME, ignore_errors=True)
    AUDIO.mkdir(parents=True)
    UPLOADS.mkdir(parents=True)
    SESSIONS.mkdir(parents=True, exist_ok=True)
    from .quiet import install, quiet
    install()
    with quiet():  # model download/load chatter
        state["stt"] = STT(CFG["stt"]["model"], CFG["stt"]["compute_type"], L.CODE, S.native_whisper)
    try:
        v = S.voice("tutor")
    except FileNotFoundError as e:
        raise SystemExit(f"tutor voice not found: {e}\n"
                         "train one (python -m voice.ingest tutor <recordings> ..., see README.md) or point config.yaml voices.tutor at an existing model") from None
    from .tts import TTS  # imports GPT-SoVITS (changes cwd), so load after paths are resolved
    state["tts"] = TTS(settings_mod.path(CFG["paths"]["gsv_root"]), v["sovits"], v["gpt"], v["refs_list"],
                       CFG["tts"]["version"], L)
    state["tts_cache"] = TTSCache(DATA / "tts_cache", voice_id(v))
    try:
        state["reply_llm"] = make_llm(CFG["llm"]["reply"])
        state["feedback_llm"] = make_llm(CFG["llm"]["feedback"])
        state["review_llm"] = make_llm(CFG["llm"].get("review", CFG["llm"]["feedback"]))
    except LLMError as e:  # warm-up still works without an LLM
        state["llm_error"] = str(e)
        print(f"note: conversation is off — {e}", flush=True)
    # GPT-SoVITS sets the root logger to INFO, which turns on a line per API call (httpx) and per
    # transcribed clip (faster_whisper); keep warnings and errors only
    import logging
    logging.getLogger().setLevel(logging.WARNING)
    for name in ("httpx", "httpx2", "httpcore", "anthropic", "faster_whisper", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    port = CFG["server"]["port"]
    print(f"persona-tutor ready → open http://localhost:{port} in your browser (Ctrl+C to stop)", flush=True)
    yield


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def revalidate(request, call_next):
    """Browsers would otherwise keep using cached page files (app.js, i18n.js) after an update."""
    resp = await call_next(request)
    resp.headers.setdefault("Cache-Control", "no-cache")
    return resp


def line(obj) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


def require_llm():
    if "llm_error" in state:
        raise HTTPException(503, state["llm_error"])


# ---------------------------------------------------------------- TTS


async def synth(text: str, emotion: str, allow_rephrase: bool = True, sess: Session | None = None) -> dict:
    """Synthesize one sentence (with ASR verification). If it still fails, ask the LLM for
    another wording once and synthesize that instead."""
    t = CFG["tts"]
    async with gpu_lock:
        r = await run_in_threadpool(state["tts"].say, text, emotion, AUDIO,
                                    state["stt"] if t["verify"] else None, t["max_attempts"], t["max_cer"])
    seg = {"text": text, "audio": f"/audio/{r.audio.name}", "emotion": r.emotion, "ref": r.ref,
           "verified": r.verified, "attempts": r.attempts, "asr": r.asr, "cer": r.cer}
    if t["verify"] and not r.verified and allow_rephrase and "feedback_llm" in state:
        try:
            res, cost = await run_in_threadpool(state["feedback_llm"].json_with_cost, prompts.rephrase_system(S),
                                                [{"role": "user", "content": text}], prompts.REPHRASE_SCHEMA, 1000)
            alt = res["text"]
            if sess:
                sess.cost += cost
            seg2 = await synth(alt, emotion, allow_rephrase=False)
            if seg2["verified"] or seg2["cer"] < r.cer:
                seg2["rephrased_from"] = text
                return seg2
        except LLMError:
            pass
    return seg


async def say_cached(text: str, emotion: str) -> dict:
    """One sentence of fixed text: from the cache, or synthesized and kept if it passed the check. The lock per
    sentence means a play button pressed while the same line is being prepared ahead waits for it, not a second run."""
    cache = state["tts_cache"]
    lock = state["say_locks"].setdefault(cache.key(text, emotion), asyncio.Lock())
    async with lock:
        if (seg := cache.get(text, emotion, AUDIO)):
            return seg
        seg = await synth(text, emotion, allow_rephrase=False)
        if seg["verified"]:
            cache.put(seg, AUDIO / Path(seg["audio"]).name)
        return seg


async def presynth(token: str, texts: list[str]):
    """Synthesize a lesson's lines ahead, one sentence at a time so a play button or the microphone waits for one
    sentence at most. It stops when practice starts or another lesson replaces it; never cancelled mid-sentence,
    because the GPU thread would keep running after gpu_lock was released."""
    try:
        for text in dict.fromkeys(texts):
            for sentence in L.split_sentences(text):
                if state["presynth"] != token:
                    return
                await say_cached(sentence, "neutral")
    except Exception:  # noqa: BLE001 - only a head start; the play button still works
        traceback.print_exc()


EMOTION_RE = re.compile(r'"emotion"\s*:\s*"(\w+)"')


async def reply_and_speak(q: asyncio.Queue, sess: Session, user_text: str | None, force_wrap_up: bool = False):
    """Stream the tutor's reply from the LLM and start TTS on each sentence as soon as it is complete.

    Events: reply_text (growing text, for display) → segment (audio per sentence) → reply (final,
    with translation / hints / clickable tokens).
    """
    loop = asyncio.get_running_loop()
    inbox: asyncio.Queue = asyncio.Queue()
    watch = FieldWatcher("text")
    st = {"cut": 0, "emotion": None}

    def on_text(chunk: str):  # LLM worker thread
        val = watch.feed(chunk)
        if st["emotion"] is None and (m := EMOTION_RE.search(watch.buf)):
            st["emotion"] = m.group(1) if m.group(1) in EMOTIONS else "neutral"
        if val is None:
            return
        loop.call_soon_threadsafe(inbox.put_nowait, ("text", val))
        pending = val[st["cut"]:]
        last_end = max((pending.rfind(c) for c in L.SENTENCE_END), default=-1)
        if watch.done:
            last_end = len(pending) - 1
        if last_end >= 0:
            for sent in L.split_sentences(pending[:last_end + 1]):
                loop.call_soon_threadsafe(inbox.put_nowait, ("sentence", sent))
            st["cut"] += last_end + 1

    llm_task = asyncio.ensure_future(run_in_threadpool(
        sess.reply, state["reply_llm"], user_text, force_wrap_up, on_text))
    seg_i, replaced, shown, audio_files = 0, [], "", []
    while True:
        getter = asyncio.ensure_future(inbox.get())
        done, _ = await asyncio.wait({getter, llm_task}, return_when=asyncio.FIRST_COMPLETED)
        if getter not in done:
            getter.cancel()
            if inbox.empty():
                break  # LLM finished and every sentence has been handled
            continue
        kind, val = getter.result()
        if kind == "text" and val != shown:
            shown = val
            q.put_nowait(line({"type": "reply_text", "text": val, "emotion": st["emotion"] or "neutral"}))
        elif kind == "sentence":
            if not re.search(r"\w", val):  # a stray punctuation mark split off by streaming: nothing to say
                continue
            seg = await synth(val, st["emotion"] or "neutral", sess=sess)
            seg.update(type="segment", index=seg_i)
            seg_i += 1
            if "rephrased_from" in seg:
                replaced.append((seg["rephrased_from"], seg["text"]))
            audio_files.append(AUDIO / Path(seg["audio"]).name)
            q.put_nowait(line(seg))
    out = llm_task.result()  # re-raises LLM errors
    for old, new in replaced:
        sess.replace_last_text(old, new)
    text = sess.last_line
    if (rec := state["records"].get(sess.id)):
        rec.add_tutor(out, text, audio_files)
        rec.data["cost_usd"] = round(sess.cost, 4)
        if out.get("closing"):
            rec.finish(sess.cost)
    q.put_nowait(line({"type": "reply", "emotion": out["emotion"], "text": text, "reading": L.reading_display(text),
                       "tokens": L.tokens(text), "translation": out["translation"], "note": out.get("note", ""),
                       "hints": out.get("hints", []), "closing": out.get("closing", False),
                       "rephrased": bool(replaced), "cost": round(sess.cost, 4)}))


def ndjson(producer):
    """Run producer(queue) in the background and stream whatever it puts on the queue."""
    async def gen():
        q: asyncio.Queue = asyncio.Queue()

        async def run():
            try:
                await producer(q)
            except Exception as e:  # noqa: BLE001 - surface to the UI
                traceback.print_exc()
                q.put_nowait(line({"type": "error", "message": f"{type(e).__name__}: {e}"}))
            q.put_nowait(None)

        task = asyncio.create_task(run())
        while (item := await q.get()) is not None:
            yield item
        yield line({"type": "done"})
        await task

    return StreamingResponse(gen(), media_type="application/x-ndjson")


# ---------------------------------------------------------------- warm-up


class SayRequest(BaseModel):
    text: str
    emotion: str = "neutral"
    fresh: bool = False    # always synthesize (the TTS test page)


def scenario_info(sc: dict) -> dict:
    """Title in the target language, plus every translation; the page shows the one for its UI language."""
    return {"id": sc["id"], "title": S.scenario_title(sc, L.CODE), "titles": sc.get("titles", {}), "title_en": sc["title"]}


def tutor_icon() -> Path | None:
    folder = (CFG.get("review_video", {}).get("characters") or {}).get("tutor")
    icon = (settings_mod.path(folder) if folder else S.data / "characters" / "tutor") / "icon.png"
    return icon if icon.exists() else None


@app.get("/api/avatar")
def get_avatar():
    """<tutor art folder>/icon.png for the page's avatar; without it the page shows the name's first letter."""
    if not tutor_icon():
        raise HTTPException(404)
    return FileResponse(tutor_icon())


@app.get("/api/config")
def get_config():
    return {"avatar": bool(tutor_icon()), "level": S.level, "ui_language": CFG.get("ui_language", "en"), "target": L.CODE, "target_name": L.NAME,
            "native": S.native_code, "tutor_name": S.persona["name"],
            "learner_name": CFG.get("learner", {}).get("name", "You"),
            "warmup_count": CFG["warmup"]["count"], "session_minutes": CFG["session"]["minutes"],
            "max_cost_usd": CFG["session"].get("max_cost_usd", 1.0), "llm_error": state.get("llm_error"),
            "llm": {k: v["model"] for k, v in CFG["llm"].items()}}


@app.get("/api/warmup")
def warmup():
    pool = S.warmup_pool()
    picks = random.sample(pool, min(CFG["warmup"]["count"], len(pool)))
    return [{"text": s["text"], "reading": L.reading_display(s["text"]), "translation": s["translation"],
             "emotion": CFG["warmup"]["emotion"]} for s in picks]


@app.post("/api/say")
async def say(req: SayRequest):
    """Stream one NDJSON line per sentence as soon as its audio is ready."""
    if req.emotion not in EMOTIONS:
        raise HTTPException(400, f"unknown emotion {req.emotion}")

    async def produce(q):
        sentences = L.split_sentences(req.text)
        q.put_nowait(line({"type": "plan", "segments": sentences}))
        for i, s in enumerate(sentences):
            # fixed text (warm-up, lesson, hint demo)
            seg = await (synth(s, req.emotion, allow_rephrase=False) if req.fresh else say_cached(s, req.emotion))
            seg.update(type="segment", index=i, total=len(sentences))
            q.put_nowait(line(seg))

    return ndjson(produce)


async def save_upload(audio: UploadFile) -> Path:
    raw = UPLOADS / f"{uuid.uuid4().hex[:12]}{Path(audio.filename or '').suffix or '.webm'}"
    raw.write_bytes(await audio.read())
    return await run_in_threadpool(to_wav16k, raw, raw.with_name(raw.stem + "_16k.wav"))


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...), target: str = Form("")):
    wav = await save_upload(audio)
    async with gpu_lock:
        text = await run_in_threadpool(state["stt"].transcribe, wav, True)
    out = {"text": text, "reading": L.reading_display(text)}
    if target:
        out["compare"] = L.compare(target, text)
    return out


# ---------------------------------------------------------------- conversation


@app.get("/api/scenarios")
def scenarios():
    return [scenario_info(s) for s in S.scenarios.values()]


class StartRequest(BaseModel):
    scenario: str | None = None
    lesson: str | None = None   # id from /api/lesson: practise that lesson (its topic wins over scenario)


def with_readings(lesson: dict) -> dict:
    """Pronunciation lines for the page (the stored lesson stays as the LLM wrote it)."""
    add = lambda x: {**x, "reading": L.reading_display(x["text"])}
    g = lesson["grammar"]
    return {**lesson, "phrases": [add(p) for p in lesson["phrases"]], "dialogue": [add(d) for d in lesson["dialogue"]],
            "grammar": {**g, "examples": [add(e) for e in g["examples"]]}}


@app.post("/api/lesson")
async def make_lesson(req: StartRequest):
    require_llm()
    sc = pick_scenario(S.scenarios, req.scenario)
    out, cost = await run_in_threadpool(lesson_mod.make, state["review_llm"], S, sc, DATA)
    lid = uuid.uuid4().hex[:12]
    state["lessons"][lid] = {"scenario": sc, "lesson": out, "cost": cost}
    lesson_mod.save(DATA, lid, sc, out)
    state["presynth"] = lid
    state["presynth_task"] = asyncio.create_task(presynth(lid, lesson_mod.spoken(out)))
    return {"id": lid, "scenario": scenario_info(sc), "lesson": with_readings(out), "cost": round(cost, 4)}


@app.get("/api/lessons")
def past_lessons():
    """Every lesson made so far, newest first, for reading again (practising one again makes a new lesson)."""
    out = []
    for r in lesson_mod.saved(DATA):
        sc = r["scenario"]
        out.append({"id": r["id"], "date": r["created"], "lesson": with_readings(r["lesson"]),
                    "scenario": {"id": sc.get("id"), "title": S.scenario_title(sc, L.CODE), "titles": sc.get("titles") or {},
                                 "title_en": sc.get("title")}})
    return out


@app.post("/api/session/start")
async def session_start(req: StartRequest):
    require_llm()
    state["presynth"] = None   # the conversation gets the GPU; lines not ready yet are made when played
    sc = CFG["session"]
    les = state["lessons"].get(req.lesson or "")
    sess = Session(S, les["scenario"] if les else pick_scenario(S.scenarios, req.scenario), sc["minutes"],
                   max_turns=sc.get("max_history_turns", 40), max_cost=sc.get("max_cost_usd", 1.0),
                   memory=memory.load(DATA), lesson=les["lesson"] if les else None, cost=les["cost"] if les else 0.0)
    state["sessions"][sess.id] = sess
    rec = SessionRecord(DATA, sess.id, sess.scenario, {k: v["model"] for k, v in CFG["llm"].items()})
    if les:
        rec.data["lesson"] = les["lesson"]
    state["records"][sess.id] = rec

    async def produce(q):
        q.put_nowait(line({"type": "session", "id": sess.id, "scenario": scenario_info(sess.scenario)}))
        await reply_and_speak(q, sess, None)

    return ndjson(produce)


@app.post("/api/turn")
async def turn(session_id: str = Form(...), audio: UploadFile = File(...)):
    require_llm()
    sess = state["sessions"].get(session_id)
    if not sess:
        raise HTTPException(404, "session not found")
    wav = await save_upload(audio)

    async def produce(q):
        async with gpu_lock:
            text, lang = await run_in_threadpool(state["stt"].transcribe_auto, wav, sess.last_line)
        q.put_nowait(line({"type": "transcript", "text": text, "lang": lang,
                           "reading": L.reading_display(text) if lang == "target" else ""}))
        if not text:
            q.put_nowait(line({"type": "error", "key": "no_speech"}))
            return
        rec = state["records"][sess.id]
        user_turn = rec.add_user(text, lang, wav)
        turn_index = len(rec.data["turns"]) - 1
        prev = sess.last_line

        async def feedback():
            # questions in the learner's own language are not practice; don't grade them
            if lang != "target":
                return
            try:
                fb = await run_in_threadpool(sess.feedback, state["feedback_llm"], prev, text)
                if fb["verdict"] == "error" and fb["natural_rewrite"]:
                    category = fb["category"] if fb["category"] != "none" else "other"
                    fb["mistake_id"] = mistakes.add(MISTAKES_DB, text, fb["natural_rewrite"], category, fb["feedback"], rec.dir.name)
                rec.set_feedback(user_turn, fb)
                q.put_nowait(line({"type": "feedback", **fb, "turn": turn_index}))
            except Exception as e:  # noqa: BLE001 - feedback is optional; keep the conversation going
                q.put_nowait(line({"type": "feedback_error", "message": f"{type(e).__name__}: {e}"}))

        fb_task = asyncio.create_task(feedback())
        try:
            await reply_and_speak(q, sess, text)
        finally:
            await fb_task

    return ndjson(produce)


class EndRequest(BaseModel):
    session_id: str


class DismissRequest(BaseModel):
    session_id: str
    turn: int


@app.post("/api/feedback/dismiss")
def dismiss_feedback(req: DismissRequest):
    """The learner says this wasn't a mistake: out of the mistakes table, and the review and memory ignore it."""
    rec = state["records"].get(req.session_id)
    fb = rec.data["turns"][req.turn].get("feedback") if rec and 0 <= req.turn < len(rec.data["turns"]) else None
    if not fb:
        raise HTTPException(404, "no feedback on that line")
    if "mistake_id" in fb:
        mistakes.delete(MISTAKES_DB, fb.pop("mistake_id"))
    fb["dismissed"] = True
    rec.save()
    return {"ok": True}


@app.post("/api/session/end")
async def session_end(req: EndRequest):
    require_llm()
    sess = state["sessions"].get(req.session_id)
    if not sess:
        raise HTTPException(404, "session not found")

    async def produce(q):
        await reply_and_speak(q, sess, "(The learner would like to stop here for today.)", force_wrap_up=True)

    return ndjson(produce)


@app.post("/api/session/review")
async def session_review(req: EndRequest):
    """Corrected + upgraded versions of the user's lines and 3–5 key expressions; saved under data/."""
    require_llm()
    rec = state["records"].get(req.session_id)
    if not rec:
        raise HTTPException(404, "session not found")
    sess = state["sessions"][req.session_id]
    if not rec.data["ended"]:
        rec.finish(sess.cost)
    review, cost = await run_in_threadpool(build_review, state["review_llm"], S, rec.dir)
    append_log(DATA, rec.dir, review)
    try:
        _, mem_cost = await run_in_threadpool(memory.update, state["review_llm"], S, DATA, review)
        cost += mem_cost
        mem_updated = True
    except Exception:  # noqa: BLE001 - the review itself is done; memory catches up next time
        traceback.print_exc()
        mem_updated = False
    sess.cost += cost
    rec.finish(sess.cost)
    user_turns = [{"said": t["text"], "lang": t["lang"], **t.get("review", {})}
                  for t in review["session"]["turns"] if t["role"] == "user"]
    return {"dir": rec.dir.name, "expressions": review["expressions"], "turns": user_turns,
            "lesson_use": review.get("lesson_use", []), "memory_updated": mem_updated,
            "cost": round(sess.cost, 4), "review_cost": round(cost, 4), "videos": video_files(rec.dir)}


class AskMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class AskRequest(BaseModel):
    messages: list[AskMessage]


@app.post("/api/ask")
async def ask(req: AskRequest):
    """The Ask tab. No session and no GPU: it works before, during and after practice."""
    require_llm()
    if not req.messages or req.messages[-1].role != "user" or not req.messages[-1].text.strip():
        raise HTTPException(400, "empty question")
    msgs = [{"role": m.role, "content": m.text} for m in req.messages]

    async def produce(q):
        loop = asyncio.get_running_loop()
        watcher = FieldWatcher("answer")

        def on_text(chunk):
            if (text := watcher.feed(chunk)) is not None:
                loop.call_soon_threadsafe(q.put_nowait, line({"type": "delta", "text": text}))

        out = await run_in_threadpool(ask_mod.answer, state["reply_llm"], S, memory.load(DATA), MISTAKES_DB, msgs, on_text)
        q.put_nowait(line({"type": "answer", "text": out["answer"], "tool_calls": ask_mod.summarize(out["calls"]),
                           "cost": round(out["cost"], 4)}))

    return ndjson(produce)


@app.get("/api/memory")
def get_memory():
    """What the tutor remembers about the learner (data/learner.json)."""
    return memory.load(DATA)


@app.put("/api/memory")
def put_memory(mem: dict):
    """The learner's own edits; the next review keeps them unless the session clearly shows otherwise."""
    return memory.save(DATA, mem)


# ---------------------------------------------------------------- after the session


def session_dir(name: str) -> Path:
    d = (SESSIONS / name).resolve()
    if d.parent != SESSIONS.resolve() or not (d / "session.json").exists():
        raise HTTPException(404, "session not found")
    return d


def video_files(d: Path) -> list[dict]:
    files = []
    for mode in MODES:
        for suffix in ("", "_shadow"):
            if (d / "review" / f"{mode}{suffix}.mp4").exists():
                files.append({"mode": mode, "shadow": bool(suffix), "mp4": f"/sessions/{d.name}/{mode}{suffix}.mp4",
                              "mp3": f"/sessions/{d.name}/{mode}{suffix}.mp3"})
    return files


@app.get("/api/recap")
def recap():
    """Last session's key expressions; the warm-up starts by recalling them."""
    r = latest_recap(DATA)
    if not r:
        return None
    return {"dir": r["dir"], "date": r["date"], "scenario": r["scenario"],
            "items": [{"said": e["said"], "said_reading": L.reading_display(e["said"]), "better": e["better"],
                       "reading": L.reading_display(e["better"]), "reason": e["reason"]} for e in r["expressions"]]}


class RecapMark(BaseModel):
    dir: str
    index: int
    score: int | None = None


@app.post("/api/recap/mark")
def recap_mark(req: RecapMark):
    if not mark_recap(DATA, req.dir, req.index, req.score):
        raise HTTPException(404, "expression not found")
    return {"ok": True}


@app.get("/api/history")
def history():
    """Past sessions that have a review, newest first, with their videos."""
    out = []
    for d in sorted(SESSIONS.glob("*/review.json"), reverse=True):
        r = json.loads(d.read_text(encoding="utf-8"))
        sc = r["session"]["scenario"]
        out.append({"dir": d.parent.name, "date": r["session"]["started"],
                    "scenario": {"title": S.scenario_title(sc, L.CODE), "titles": sc.get("titles") or {},
                                 "title_en": sc.get("title")},
                    "expressions": len(r["expressions"]), "videos": video_files(d.parent)})
    return out


class VideoRequest(BaseModel):
    dir: str
    shadow: bool | None = None


@app.post("/api/session/video")
async def session_video(req: VideoRequest):
    """Voice the user's lines with the review voice (GPU, swapped in place and back), then render (CPU)."""
    d = session_dir(req.dir)
    if not (d / "review.json").exists():
        raise HTTPException(400, "no_review")
    if state.get("rendering"):
        raise HTTPException(409, "already_rendering")
    rvc, t = CFG["review_video"], CFG["tts"]
    shadow = rvc.get("shadow", False) if req.shadow is None else req.shadow
    modes = list(MODES)

    async def produce(q):
        state["rendering"] = True
        loop = asyncio.get_running_loop()

        def log(key: str, **args):
            loop.call_soon_threadsafe(q.put_nowait, line({"type": "progress", "key": key, "args": args}))

        def say_many(pairs):
            rs = state["tts"].say_many(pairs, AUDIO, state["stt"], t["max_attempts"], t["max_cer"])
            return [(r.audio, r.verified, r.attempts) for r in rs]

        def voice_all(review):
            tts = state["tts"]
            tts.use_voice(*S.voice("review").values())
            try:
                return voice_user_lines(review, modes, say_many, log)
            finally:
                tts.use_voice(*S.voice("tutor").values())
                log("voice_restored")

        try:
            review = load_review(d)
            log("voice_loading")
            async with gpu_lock:
                spoken = await run_in_threadpool(voice_all, review)
            log("rendering")
            await run_in_threadpool(render_videos, S, d, review, spoken, modes, shadow, log)
            q.put_nowait(line({"type": "videos", "videos": video_files(d)}))
        finally:
            state["rendering"] = False

    return ndjson(produce)


@app.get("/sessions/{name}/{file}")
def session_file(name: str, file: str):
    d = session_dir(name)
    f = (d / "review" / file).resolve()
    if f.parent != (d / "review").resolve() or f.suffix not in (".mp4", ".mp3") or not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="video/mp4" if f.suffix == ".mp4" else "audio/mpeg")


class ExplainRequest(BaseModel):
    word: str
    base: str = ""
    sentence: str
    session_id: str | None = None


@app.post("/api/explain")
async def explain(req: ExplainRequest):
    require_llm()
    key = (req.word, req.sentence)
    if key not in state["explain_cache"]:
        out, cost = await run_in_threadpool(
            state["feedback_llm"].json_with_cost, prompts.explain_system(S),
            [{"role": "user", "content": f"Sentence: {req.sentence}\nWord: {req.word} (dictionary form: {req.base or req.word})"}],
            prompts.EXPLAIN_SCHEMA, 1000)
        state["explain_cache"][key] = out
        if (sess := state["sessions"].get(req.session_id or "")):
            sess.cost += cost
    return state["explain_cache"][key]


@app.get("/audio/{name}")
def audio_file(name: str):
    f = (AUDIO / name).resolve()
    if f.parent != AUDIO or not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/wav")


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")

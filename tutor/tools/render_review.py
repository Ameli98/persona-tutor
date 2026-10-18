"""Render a finished session's review into videos (+ mp3): corrected / model version (× shadowing).

  python -m tutor.tools.render_review data/sessions/<dir> [--only corrected|upgraded] [--shadow]

The tutor's lines use the audio recorded during the session; the learner's lines are re-spoken by the
review voice and ASR-verified. Run while the backend is stopped (GPU memory); with the backend running,
use the "make review video" button instead.
"""
import argparse
from pathlib import Path

from ..backend import settings as settings_mod
from ..backend.stt import STT
from ..video.review_video import MODES, load_review, render_videos, voice_user_lines

LOG_FORMAT = {
    "voicing": "voicing {n} lines…", "voice_retry": "  [{emotion}] {ok} after {retries} retries: {text}",
    "video_done": "wrote {file} ({seconds}s)",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir")
    ap.add_argument("--only", choices=list(MODES))
    ap.add_argument("--shadow", action="store_true", help="also render shadowing versions (gap after your lines)")
    args = ap.parse_args()
    sdir = Path(args.session_dir).resolve()
    s = settings_mod.load()
    cfg, tc = s.cfg, s.cfg["tts"]
    review = load_review(sdir)
    modes = [args.only] if args.only else list(MODES)

    stt = STT(cfg["stt"]["model"], cfg["stt"]["compute_type"], s.lang.CODE, s.native_whisper)
    from ..backend.tts import TTS  # changes cwd to GPT-SoVITS
    v = s.voice("review")
    tts = TTS(settings_mod.path(cfg["paths"]["gsv_root"]), v["sovits"], v["gpt"], v["refs_list"], tc["version"], s.lang)
    tmp = sdir / "render_tmp"
    tmp.mkdir(exist_ok=True)

    def say_many(pairs):
        rs = tts.say_many(pairs, tmp, stt, tc["max_attempts"], tc["max_cer"])
        return [(r.audio, r.verified, r.attempts) for r in rs]

    def log(key, **a):
        print(LOG_FORMAT.get(key, key).format(**a), flush=True)

    spoken = voice_user_lines(review, modes, say_many, log)
    render_videos(s, sdir, review, spoken, modes, args.shadow or cfg["review_video"].get("shadow", False), log)


if __name__ == "__main__":
    main()

# persona-tutor — notes for coding agents

A local speaking tutor: FastAPI backend + single-page front end, faster-whisper (STT), GPT-SoVITS (TTS),
an LLM for conversation / feedback / review. Users customize it through config and YAML; code changes are
for new behaviour.

## Run and check

- Environment: `bash install.sh` (conda env `persona-tutor` with GPT-SoVITS; idempotent), then `source activate.sh` in each terminal.
- Start: `./run.sh` → http://localhost:8765 (activates the env from `.conda-env`). Needs `config.yaml` (copy `config.example.yaml`
  or run `python -m tutor.setup`) and trained voices (the `voice.*` steps in README.md).
- Unit tests (no GPU, no API): `python -m pytest tests` — run after any change to `tutor/lang`, `voice/`,
  `tutor/setup.py` or the example YAML files.
- End-to-end smoke test against a running server (costs a few cents of API usage):
  `python -m tutor.tools.e2e_turn --base http://127.0.0.1:8765 --end --review`.
- GPU steps (`voice.check/emotion/train/screen`, `tutor.tools.render_review`) need the tutor stopped on an 8 GB GPU.

## Where things live

| Change | Edit |
|---|---|
| Tutor character | a persona YAML (`personas/`, or a private one under `data/`) referenced by `config.yaml: persona` |
| Topics | scenario YAMLs: `id`, `title` (English), `titles: {code: ...}`, `setting`, `goal`, `angles` |
| Prompts | `tutor/backend/prompts.py` (reply / feedback / word explanation / rephrase), `tutor/backend/review.py` (after-session review), `voice/emotion.py` |
| Lesson before the conversation | `tutor/backend/lesson.py` (prompt + schema; saved to `data/lessons/`); the reply prompt's `lesson_section`; the review's `lesson_use` |
| Ask tab, tool calling (`lookup_past_mistakes`) | `tutor/backend/ask.py`, `tutor/backend/mistakes.py` (SQLite store, tool definition, input validation), the loop in `llm.AnthropicLLM.stream_json`, the rule in `prompts.ask_system`; eval: `python -m evals.tool_calling` (cases in `evals/tool_calling_cases.yaml`) — rerun it after changing that rule or the tool description |
| Fixed-text audio | `tutor/backend/tts_cache.py` (`data/tts_cache/`), `say_cached` and `presynth` in `tutor/backend/app.py` (a lesson's lines are made ahead; live tutor lines aren't cached) |
| Live feedback | `prompts.feedback_system` (verdicts: natural / suggestion / error / misheard; only error reaches `mistakes.db` and memory), `/api/feedback/dismiss`; eval: `python -m evals.feedback` (cases in `evals/feedback_cases.yaml`) — rerun it after changing that prompt |
| Models | `llm` in `config.yaml`, one role per task: reply, ask, lesson, feedback (also word explanations and rephrasing), review (also memory). Spending by task: `Session.charge`, saved as `costs` in `session.json` |
| Imported texts | `tutor/backend/texts.py` (`data/texts/`: decode, passages, embeddings on the CPU, search, the `search_texts` tool), `lesson.passage_rules`; eval: `python -m evals.retrieval` (free) |
| What the tutor remembers | `tutor/backend/memory.py` (`data/learner.json`: fields, caps, update prompt); edited on the page's Memory view |
| Tutor and learner relationship | `learner.relationship` in `config.yaml` (`Settings.relationship`, `Settings.speech`): tone of replies, lessons, model answers and what feedback counts as a register mistake |
| Learner level | `Settings.level` is what prompts use: the assessed level from memory, else the self-rating in config. The band moves by `memory.apply_band` in code: one step, two sessions in a row; the model only reports where a session points |
| Target-language behaviour | `tutor/lang/<code>.py` — interface documented in `tutor/lang/__init__.py`; warm-up sentences in `tutor/lang/<code>_warmup.yaml` |
| UI text | `tutor/web/i18n.js` (every key in `en` must exist; other languages fall back to `en`) |
| Video look and labels | `tutor/video/render.py` (layout), `tutor/video/review_video.py` (`LABELS`, theme from config) |
| Settings access | `tutor/backend/settings.py` (`Settings`: `lang`, `persona`, `scenarios`, `voice(role)`, `native`, ...) |

## Voice pipeline (voice/): why it works this way

Steps: ingest (clips; long recordings cut at pauses with Silero VAD) → check (Whisper transcript vs given text,
flags unusable clips) → emotion → select (emotion-balanced training set + 12 reference candidates per emotion)
→ review (web page, user confirms references by ear) → train (GPT-SoVITS v2Pro, experiment `pt-<name>`) →
screen. Everything lands in `data/voices/<name>/`: `clips.csv` (one row per clip; every step adds columns),
`review.json` (the user's decisions; rerunning `select` keeps them), `train.list`, `refs/<emotion>/` +
`refs/refs.list`, `sovits.pth`, `gpt.ckpt`. Names `tutor` and `review` are picked up without config.

- **Reference clips decide the tone** of everything the voice says, so they are confirmed by ear; training-set
  emotion labels only balance the mix and may be approximate.
- **Emotion from audio alone is unreliable on expressive speech.** On a hand-checked set of acted lines,
  emotion2vec+ agreed with a listener 28% of the time, the transcript alone 67%, both together 77%. The
  Claude API takes no audio, so `voice/emotion.py` turns emotion2vec+ scores and pitch/loudness/rate relative to
  the speaker's own median into text and sends it with the line. Don't replace this with the audio model alone.
- **A good reference carries its emotion without context**: clean close-mic audio, one complete sentence, no
  whisper/breath/effect. The emotion step asks which lines qualify (`standalone`) and ranks those first.
- **Bad references cause prompt leakage** (the model re-reads the reference text); `voice.screen` synthesizes
  test sentences with each reference and flags misread ones.
- `voice.emotion` computes prosody in worker processes *before* loading the CUDA model and warms librosa's
  numba cache in the parent first (parallel first compiles once wrote a corrupt cache that segfaulted later runs).
- `voice.train` deletes GPT-SoVITS's `logs/pt-<name>/` before data prep, or stale features from an earlier run
  break the count check on retraining.

## Conventions and invariants

- **Never commit personal data.** `data/` and `config.yaml` are git-ignored: recordings, weights, reference
  clips, practice sessions, private personas/scenarios, art and font paths. Keep it that way; don't add
  sample audio or weights to the repository.
- Prompts are written in English and name the target and native languages through `Settings`; explanations
  shown to the learner must be in their native language (`review.py` and `session.feedback` re-ask when a
  field drifts into the target language — keep those checks).
- The backend sends UI messages as keys (`{"type": "progress", "key": ...}`, HTTP `detail` = key); the page
  translates them. Don't put UI-language text in Python.
- One GPU: any STT/TTS call in the backend goes through `gpu_lock`. Swapping voices uses `TTS.use_voice`
  (in place), not a second model.
- `tts.py` forces `torch.backends.cudnn.benchmark = False` before every synthesis; GPT-SoVITS's accelerator
  turns it on and it costs ~20 s per new sentence length.
- Sentence splitting must never produce punctuation-only pieces (they fail TTS verification and trigger a
  rephrase that corrupts the line); see `tests/test_ja.py`.
- The API key comes from `PERSONA_TUTOR_API_KEY` (set by `run.sh` from `~/.config/persona-tutor/api_key`).
  Don't read or write `ANTHROPIC_API_KEY`, and never write keys into files in the repository.
- Match the surrounding style: small functions, docstrings that say *why*, no new dependencies without need.

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`Ameli98/persona-tutor`, via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

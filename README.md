# persona-tutor

## About

A local, voice-first speaking tutor. Each session is a short lesson on the topic (key phrases, a grammar point, a
model dialogue), a 5-minute conversation with a character you design, speaking in a voice you trained yourself
(GPT-SoVITS, ~25 minutes of recordings), then corrections and a review video. The tutor remembers your level,
recurring mistakes and past topics, and the next lesson builds on them. Runs on Linux or WSL2 with an NVIDIA GPU (6 GB+).
**Requires a [Claude API](https://console.anthropic.com/) key** (pay as you go, about $0.15 per session).

## Quick start

### Build the tutor

```bash
git clone https://github.com/Ameli98/persona-tutor
cd persona-tutor
bash install.sh                  # conda env, PyTorch, GPT-SoVITS and models
source activate.sh               # in every new terminal
python -m tutor.setup            # languages, level, the character you want, API key → config.yaml

# change the argument 'tutor' into 'review' for reviewer model, which read your lines in the review video.

# train the tutor's voice from your recordings
# data dir should contain training data and corresponding transcript
# format of transcript can be transcripts.csv (file, text) or txt files w/ same name of each voice file

python -m voice.ingest tutor "<data dir>"
python -m voice.check tutor # filter data
python -m voice.emotion tutor # label emotion w/ Claude API
# Use python -m voice.emotion tutor --no-llm instead if you want to do it all manually

python -m voice.select tutor 
python -m voice.review tutor # open a localhost to modify label manually
python -m voice.train tutor
python -m voice.screen tutor # check the performance

./run.sh
```

Run `python -m tutor.setup` again, or edit `data/personas/<name>.yaml` to modify your character.

### Style the review videos (optional)

Drop files into these folders and restart the tutor; nothing to configure.
Character sprite should name as `neutral.png`, `happy.png`, `angry.png`, `sad.png`, `shy.png`, `surprised.png`.

| What | Where |
|---|---|
| Sprites | `data/characters/tutor/` and `data/characters/learner/` (you)|
| Background | `data/backgrounds/default.png`, or `<topic id>.png` per topic |
| Tutor's icon | `data/characters/tutor/icon.png`|

## Tool calling: looking up past mistakes

Every live correction is stored as a row in `data/mistakes.db` (SQLite: what you said, the corrected sentence, the
kind of mistake, why). The **Ask** tab is a text chat with the tutor, open at any time, separate from speaking
practice so practice stays on the lesson. It has one tool, `lookup_past_mistakes(category?, limit=5)`, called through
the Claude API's native tool use (`tool_use` → `tool_result`) inside the streamed answer. Ask "what do I keep getting
wrong?", "how can I improve?" or "drill me on my particle mistakes" and it answers with sentences you actually said;
general language questions don't trigger it, and with no matching records it says so instead of making mistakes up.
Mistake kinds come from the target-language module (`MISTAKE_CATEGORIES` in `tutor/lang/ja.py`).

```bash
python -m evals.tool_calling --label mine    # ~$0.3; table in evals/results/tool_calling_mine.md
python -m pytest tests                       # the loop itself, with a fake client (no API calls)
```

23 cases in `evals/tool_calling_cases.yaml`: should call (11), should not call (9), should call but nothing
matches (3). Each checks whether the tool was called, with the implied arguments, and whether the reply makes
sense given the result (Claude Sonnet 5.5 as judge). Synthetic data only.

The v1–v4 runs were measured while the tool still lived inside speaking practice. The cases were then rewritten
for the Ask tab.

| Run | Cases | Passed |
|---|---|---|
| v1: first prompt | 15 original | 15/15 |
| v1: first prompt | +8 harder | 7/8 |
| v2: revised prompt and tool description | all 23 | 23/23 |
| v3: "lead back to the topic" added; judge now also sees the learner memory | all 23 | 21/23 |
| v4: answer "was that right?"; own examples must not look like records | all 23 | 22/23 (`show_all` 2/2 after the judge fix below) |
| ask-v1: moved to the Ask tab, cases rewritten | all 23 | 23/23 |

**Problems and fixes**

- *An eval that can't fail.* v1 passed every case because every case was unambiguous. I added indirect requests,
  two kinds at once, an out-of-range `limit`, and requests that sound related but need a different source (past
  topics, the sentence just said, general advice about mistakes).
- *Indirect requests didn't trigger the tool.* "How can I get better?" got generic advice, 3 runs out of 3. The prompt
  listed trigger phrases ("asks what mistakes they make…"), and "don't use it in ordinary conversation" pushed the
  model to be conservative. The tool description said what it returns, not when it helps. Fix: state the principle
  (call it whenever the answer should be about *this learner's* weak points), name what doesn't count (general
  advice not about the learner), and say in the tool description that it grounds personal advice in real
  sentences. The case passed 3 runs out of 3 afterwards; its counter-case ("tips for not fearing mistakes") still
  doesn't call the tool.
- *A judge that sees less than the tutor.* After v3 the first run scored 19/23, but the replies matched v2's, which
  passed. The tutor also has the learner memory ("particles, 4 times"), so "particles are your most common slip" is
  grounded; the judge only saw the tool result and called it invented. The judge now gets the memory too, and is
  told the on-screen note counts as part of the reply (it once failed `show_all` for listing the 8 mistakes there).
  Lesson: before changing the prompt, check whether the failure is the model's or the grader's.
- *Two real rule conflicts the harder cases exposed.* "Never correct the learner" made the tutor refuse "was that
  sentence right?"; it now answers in one sentence. And it sometimes slipped its own example sentence in next to
  the real records as if the learner had said it; the rule now forbids that.
- *The wrong place for it.* A question about your mistakes pulled lesson-focused practice off topic, so the tool moved
  out of practice into its own Ask tab.
- *Streaming and tools together.* The answer is JSON (structured output) shown on the page as it is written, so
  the SDK's tool runner doesn't fit. A manual loop runs inside the streamed call: every `tool_use` in a response
  is answered in one `tool_result` message, inputs are validated by the tool (bad input returns an error result
  the model can fix), and after 3 rounds tools are disabled (`tool_choice: none`) so a reply always arrives.

## Live feedback: errors, suggestions and misheard words

Each line gets one of four verdicts: **natural**, **suggestion** (nothing wrong, another common way to say it),
**error** (a native speaker would find it wrong) or **misheard** (probably the speech recogniser's fault). Only errors
go into `data/mistakes.db` and the learner memory, and a "Not a mistake" button takes one back out.

```bash
python -m evals.feedback --label mine --models claude-sonnet-5-5    # ~$0.04; table in evals/results/feedback_mine.md
```

40 synthetic lines: fine (8), stiff but acceptable (7), real errors (15), misheard (8), error or misheard (2).

| Run | Lines | Passed | Fine lines called mistakes |
|---|---|---|---|
| Old prompt (natural / unnatural only), Sonnet 5.5 | first 24 | 14/24 | 4/12 |
| New prompt, Sonnet 5.5 | first 24 | 24/24 | 0/12 |
| New prompt, Sonnet 5.5 | all 36, harder ones added | 32/36 | 1/15 |
| Revised prompt, Sonnet 5.5 (run twice) | all 36 | 36/36 | 0/15 |
| Revised prompt, Opus 5.5 | all 36 | 35/36 | 0/15 |
| Revised prompt, Haiku 5.5 | all 36 | 31/36 | 1/15 |
| Rewrites must keep the learner's words, Sonnet 5.5 | all 40 | 40/40 | 0/15 |

The old prompt can't say "misheard", so its 0/6 on those lines is by design; the point is that it recorded them as
mistakes. Median time was about 2 s on all three models, so feedback stays on Sonnet: Opus costs twice as much without
being more accurate here, and Haiku fixed the wrong thing more often.

**Problems and fixes**

- *Style graded as error.* The prompt said "strict" and had only natural / unnatural, so stiff but correct lines
  counted as mistakes. "Would a native speaker find it wrong?" now decides, and style is at most a suggestion.
- *Whisper's word confidence looked like the answer and wasn't.* On 14 real recordings the words actually misheard had
  no low-confidence marks while correct rare words did, and turning it on changed the transcript of 6 lines, once adding
  a hallucinated phrase. So the model judges from context and sound alone. Speech has no spelling, so a wrong kanji for
  the right sound always counts as misheard.
- *Faulty test cases.* After the harder lines were added, two failures were my own: one expected answer rejected another
  correct form, and one line was too garbled to call. I fixed those two cases and say so here, since editing a failing
  test can hide a real failure. The README's first 32/36 is from before that fix.
- *A correction that changed what I meant.* In real use, a vague answer was "corrected" with a verb lifted from the
  tutor's question and called misheard, so a real grammar mistake was excused and the rewrite said something I never
  said. A rewrite now has to keep the learner's words, and a wrong particle or verb form is always the learner's.
- *Haiku wasn't faster.* The plan was Haiku for word explanations because they're simple and should be quick. Measured on
  6 words it took 3.5 s (median) against Sonnet's 2.7 s, so they stay on Sonnet. Lessons moved to Opus: 15.3 s against
  Sonnet's 15.5 s, for $0.03 instead of $0.02 a lesson. These are small samples.
- *Still a risk:* a real mistake that sounds like another word gets excused as misheard. Nothing here measures how often
  that happens with real learners.

## Credits

[GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) (MIT) ·
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT) ·
[Silero VAD](https://github.com/snakers4/silero-vad) (MIT) ·
[pyopenjtalk](https://github.com/r9y9/pyopenjtalk) (MIT) ·
[emotion2vec+](https://github.com/ddlBoJack/emotion2vec) (FunASR model licence; downloaded on first use) ·
[FunASR](https://github.com/modelscope/FunASR) (MIT)

MIT License © 2026 Ameli98

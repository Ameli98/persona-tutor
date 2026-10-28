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

## Credits

[GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) (MIT) ·
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT) ·
[Silero VAD](https://github.com/snakers4/silero-vad) (MIT) ·
[pyopenjtalk](https://github.com/r9y9/pyopenjtalk) (MIT) ·
[emotion2vec+](https://github.com/ddlBoJack/emotion2vec) (FunASR model licence; downloaded on first use) ·
[FunASR](https://github.com/modelscope/FunASR) (MIT)

MIT License © 2026 Ameli98

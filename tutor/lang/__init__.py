"""Target-language modules. Each module (ja.py, ...) provides:

  CODE, NAME            language code for Whisper / GPT-SoVITS, and its English name
  SENTENCE_END          characters that end a sentence (streaming TTS cuts on these)
  FEEDBACK_FOCUS        language-specific points for the feedback editor (prompt text)
  REGISTER              default speaking register for corrections and model answers
  READING_HINT          what the word-explanation 'reading' field should contain
  MISTAKE_CATEGORIES    {name: description}: kinds of mistake the feedback labels and the tutor can look up
  reading(text)         pronunciation used to compare speech with a target ("" if not applicable)
  reading_display(text) reading shown under a line to help the learner ("" to hide)
  split_sentences(text) sentences small enough for one TTS call
  tokens(text)          clickable units: [{"surface", "base", "click"}]
  compare(target, said) dict from common.compare_units
  script_ratio(text)    0..1, how much the text is written in this language's script

GPT-SoVITS speaks zh / en / ja / ko / yue, so those are the languages a module can target.
"""
import importlib


def load(code: str):
    try:
        return importlib.import_module(f"{__name__}.{code}")
    except ModuleNotFoundError as e:
        raise ValueError(f"no language module for '{code}' (see tutor/lang/__init__.py)") from e

"""Find CJK-capable fonts for the review video.

Order: review_video.font_dir from config.yaml → fontconfig (fc-list) → Windows fonts (when running in WSL).
Returns (file, index) pairs, since .ttc collections hold several faces.
"""
import subprocess
from functools import lru_cache
from pathlib import Path

# language → name fragments that identify a font for it (font_dir) and fontconfig lang tag
TAGS = {
    "ja": (["JP", "jp", "Japanese"], "ja"),
    "zh-TW": (["TC", "tc", "HK", "TW", "jh"], "zh-tw"),
    "zh-CN": (["SC", "sc", "CN", "yh"], "zh-cn"),
    "zh": (["SC", "sc", "CN", "yh"], "zh-cn"),
    "ko": (["KR", "kr", "malgun"], "ko"),
}
WINDOWS = Path("/mnt/c/Windows/Fonts")
WINDOWS_FONTS = {  # (bold, regular)
    "ja": ("YuGothB.ttc", "YuGothR.ttc"),
    "zh-TW": ("msjhbd.ttc", "msjh.ttc"),
    "zh-CN": ("msyhbd.ttc", "msyh.ttc"),
    "zh": ("msyhbd.ttc", "msyh.ttc"),
    "ko": ("malgunbd.ttf", "malgun.ttf"),
}
FONT_EXT = {".otf", ".ttf", ".ttc", ".otc"}


def _is_bold(name: str) -> bool:
    return any(w in name.lower() for w in ("bold", "heavy", "black", "bd.", "-b."))


def _from_dir(font_dir: Path, lang: str, bold: bool):
    frags = TAGS.get(lang, ([], ""))[0]
    files = sorted(f for f in font_dir.iterdir() if f.suffix.lower() in FONT_EXT)
    for pick_lang in (True, False):  # prefer a font named for the language, else any CJK-looking font
        for f in files:
            if pick_lang and not any(t in f.name for t in frags):
                continue
            if _is_bold(f.name) == bold:
                return str(f), 0
    return None


def _from_fontconfig(lang: str, bold: bool):
    tag = TAGS.get(lang, ([], lang))[1]
    try:
        out = subprocess.run(["fc-list", f":lang={tag}", "file", "index", "style"], capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    rows = []
    for ln in out.splitlines():  # "/path/x.ttc: :style=Bold:index=2" (field order varies)
        path, _, rest = ln.partition(":")
        style = rest.split("style=")[1].split(":")[0] if "style=" in rest else ""
        index = int(rest.split("index=")[1].split(":")[0]) if "index=" in rest else 0
        rows.append((path.strip(), index, _is_bold(style + " ")))
    for path, index, is_bold in sorted(rows):
        if is_bold == bold:
            return path, index
    return (rows[0][0], rows[0][1]) if rows else None


def _from_windows(lang: str, bold: bool):
    names = WINDOWS_FONTS.get(lang)
    if names and (WINDOWS / names[0 if bold else 1]).exists():
        return str(WINDOWS / names[0 if bold else 1]), 0
    return None


@lru_cache(maxsize=None)
def find(lang: str, bold: bool, font_dir: str | None = None) -> tuple[str, int]:
    """A font file for text in `lang` (ja, zh-TW, en, vi, ...). Video text mixes languages (an English note
    quoting a Japanese word), so languages without their own entry use a CJK font, which also has Latin,
    Greek and Cyrillic; their own font is the last resort."""
    if lang in TAGS:
        finders = [(lambda: _from_dir(Path(font_dir), lang, bold)) if font_dir else None,
                   lambda: _from_fontconfig(lang, bold), lambda: _from_windows(lang, bold)]
    else:  # Latin-script text here still quotes CJK words (titles, examples): a CJK font covers both
        finders = [(lambda: _from_dir(Path(font_dir), "ja", bold)) if font_dir else None,
                   lambda: _from_fontconfig("ja", bold), lambda: _from_windows("ja", bold),
                   lambda: _from_fontconfig(lang, bold)]  # e.g. no CJK font installed at all
    for finder in finders:
        if finder and (hit := finder()):
            return hit
    raise FileNotFoundError(
        f"no font for '{lang}' text: install one (e.g. `sudo apt install fonts-noto-cjk`) "
        f"or set review_video.font_dir in config.yaml")

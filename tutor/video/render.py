"""Render a session review as video + audio: the tutor's lines (audio recorded during the session) and
the learner's lines re-spoken by the review voice (corrected or model version), with optional character
art by emotion and burned-in subtitles, corrections and reasons. Optional shadowing mode leaves a gap
after each learner line.

Frames are static per line, so each line = one PNG shown for the line's audio duration.
"""
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
SR = 32000
CACHE = Path(__file__).resolve().parent / "cache"
WIN_H = 390         # subtitle window height: 4–5 lines of text
GAP = 0.45          # silence between lines (s)
SHADOW_MIN = 2.0    # shadowing gap: max(SHADOW_MIN, duration * SHADOW_RATIO)
SHADOW_RATIO = 1.3


@dataclass
class Line:
    who: str            # "tutor" | "user"
    text: str           # what is spoken (target language)
    translation: str
    emotion: str
    audio: np.ndarray   # int16 mono @ SR
    said: str = ""      # user: original utterance
    fix_kind: str = ""  # user: "corrected" | "model"
    fix_note: str = ""


@dataclass
class Theme:
    """Everything that varies between users: fonts per role, names, labels, art."""
    target_bold: tuple       # (font file, index)
    target_regular: tuple
    native_regular: tuple
    ui_regular: tuple
    ui_bold: tuple
    names: dict              # {"tutor": ..., "user": ...}
    labels: dict             # see review_video.LABELS
    characters: dict = field(default_factory=dict)   # {"tutor": Path | None, "user": Path | None}


@lru_cache(maxsize=None)
def font(spec: tuple, size: int):  # CJK fonts are large (~16 MB); load each size once
    return ImageFont.truetype(spec[0], size, index=spec[1])


NO_LINE_START = "」』）)、。，．・…ー！？!?,.;:ぁぃぅぇぉっゃゅょァィゥェォッャュョ"


def wrap(draw, text, fnt, width):
    """Wrap by width. Text with spaces (English, Korean) breaks between words; CJK breaks anywhere except
    before closing brackets / punctuation / small kana (kinsoku)."""
    spaced = sum(c.isascii() and c.isalpha() for c in text) > 0.3 * len(text) or \
        any("가" <= c <= "힣" for c in text)
    if spaced:
        lines, cur = [], ""
        for word in text.split():
            cand = f"{cur} {word}" if cur else word
            if draw.textlength(cand, font=fnt) > width and cur:
                lines.append(cur)
                cur = word
            else:
                cur = cand
        return lines + ([cur] if cur else [])
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=fnt) > width and cur and ch not in NO_LINE_START:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def draw_block(draw, xy, text, fnt, width, fill, spacing=1.25):
    x, y = xy
    for ln in wrap(draw, text, fnt, width):
        draw.text((x, y), ln, font=fnt, fill=fill)
        y += int(fnt.size * spacing)
    return y


def background(path: Path | None) -> Image.Image:
    """The image scaled to cover the frame (transparent margins cropped, slightly blurred), or a gradient."""
    if path and Path(path).exists():
        path = Path(path)
        cached = CACHE / f"bg_{path.stem}_{path.stat().st_mtime_ns}.png"
        if cached.exists():
            return Image.open(cached).convert("RGB")
        bg = Image.open(path)
        if bg.mode == "RGBA":
            bg = bg.crop(bg.getchannel("A").point(lambda a: 255 if a > 250 else 0).getbbox())
        bg = bg.convert("RGB")
        scale = max(W / bg.width, H / bg.height)
        bg = bg.resize((round(bg.width * scale), round(bg.height * scale)), Image.LANCZOS)
        left, top = (bg.width - W) // 2, (bg.height - H) // 2
        bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(1.5))
        CACHE.mkdir(exist_ok=True)
        bg.save(cached)
        return bg
    grad = np.linspace(0, 1, H)[:, None, None]
    top, bot = np.array([238, 226, 214]), np.array([196, 178, 170])
    return Image.fromarray((top * (1 - grad) + bot * grad).astype(np.uint8).repeat(W, axis=1))


def dim(img: Image.Image) -> Image.Image:
    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b)).point(lambda v: int(v * 0.55))
    return Image.merge("RGBA", (*rgb.split(), a))


@lru_cache(maxsize=None)
def _character(folder: str | None, emotion: str, dimmed: bool) -> Image.Image | None:
    """<folder>/<emotion>.png (falls back to neutral.png), scaled to 1000 px tall; None without art."""
    if not folder:
        return None
    f = Path(folder) / f"{emotion}.png"
    if not f.exists():
        f = Path(folder) / "neutral.png"
    if not f.exists():
        return None
    img = Image.open(f).convert("RGBA")
    img = img.crop(img.getbbox())
    img = img.resize((round(img.width * 1000 / img.height), 1000), Image.LANCZOS)
    return dim(img) if dimmed else img


PANEL_MAX, PANEL_MIN, MARGIN = 840, 480, 40


def panel_span(spans: list[tuple[int, int]]) -> tuple[int, int]:
    """x range of the correction panel: the widest gap beside/between the characters, at most PANEL_MAX wide
    and centred in it. If no gap is PANEL_MIN wide (very wide art), it overlaps the art in the middle."""
    edges, x = [], MARGIN
    for left, right in sorted(spans):
        edges.append((x, left - MARGIN))
        x = max(x, right + MARGIN)
    edges.append((x, W - MARGIN))
    a, b = max(edges, key=lambda e: e[1] - e[0])
    if b - a < PANEL_MIN:
        a, b = (W - PANEL_MAX) // 2, (W + PANEL_MAX) // 2
    w = min(b - a, PANEL_MAX)
    x0 = a + (b - a - w) // 2
    return x0, x0 + w


@lru_cache(maxsize=1)
def _window() -> Image.Image:
    """Translucent subtitle window across the bottom, full-frame RGBA."""
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    d.rounded_rectangle((40, H - WIN_H + 20, W - 40, H - 20), 28, fill=(22, 22, 32, 200),
                        outline=(255, 255, 255, 90), width=2)
    return over


def frame(bg: Image.Image, ln: Line, scenario: str, mode_label: str, tutor_emotion: str,
          user_emotion: str, th: Theme, shadow_cue: bool = False) -> Image.Image:
    img = bg.copy().convert("RGBA")
    learner = _character(th.characters.get("user"), user_emotion, ln.who == "tutor")
    tutor = _character(th.characters.get("tutor"), tutor_emotion, ln.who != "tutor")
    # one character stands in the middle; with both, the learner at 1/4 of the width and the tutor at 3/4
    # (leaves the gap between them for the correction panel)
    spans = []  # horizontal extent of each character above the subtitle window
    for char, cx in ((learner, W // 4 if tutor else W // 2), (tutor, 3 * W // 4 if learner else W // 2)):
        if char:
            left, top = cx - char.width // 2, H - char.height + 120
            img.alpha_composite(char, (left, top))
            box = char.crop((0, 0, char.width, H - WIN_H - top)).getbbox()
            if box:
                spans.append((left + box[0], left + box[2]))

    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    over.alpha_composite(_window())
    lb = th.labels
    # header
    head = f"{scenario}　|　{mode_label}"
    hf = font(th.ui_regular, 28)
    d.rounded_rectangle((32, 28, 32 + d.textlength(head, font=hf) + 40, 84), 14, fill=(20, 20, 28, 150))
    d.text((52, 36), head, font=hf, fill=(240, 240, 240, 255))
    top = H - WIN_H
    accent = (255, 190, 205, 255) if ln.who == "tutor" else (175, 210, 255, 255)
    d.text((140, top + 58), th.names[ln.who], font=font(th.ui_bold, 34), fill=accent,
           stroke_width=3, stroke_fill=(40, 30, 40, 255))
    tx, ty, tw = 140, top + 112, W - 280
    for k in (1.0, 0.9, 0.8, 0.72, 0.65, 0.58):
        fj, fz = font(th.target_bold, int(46 * k)), font(th.native_regular, int(28 * k))
        need = (len(wrap(d, ln.text, fj, tw)) * fj.size * 1.3
                + (len(wrap(d, ln.translation, fz, tw)) * fz.size * 1.25 + 8 if ln.translation else 0))
        if ty + need <= H - 26:
            break
    stroke = {"stroke_width": 2, "stroke_fill": (30, 30, 36, 255)}
    y = ty
    for t in wrap(d, ln.text, fj, tw):
        d.text((tx, y), t, font=fj, fill=(255, 255, 255, 255), **stroke)
        y += int(fj.size * 1.3)
    if ln.translation:
        y += 8
        for t in wrap(d, ln.translation, fz, tw):
            d.text((tx + 2, y), t, font=fz, fill=(240, 230, 170, 255), **stroke)
            y += int(fz.size * 1.25)
    # correction panel for the learner's lines (corrected version only; the model version just plays the model answer)
    if ln.who == "user" and ln.fix_kind == "corrected" and (ln.said or ln.fix_note):
        x0, x1 = panel_span(spans)
        y0 = 110
        panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        pd = ImageDraw.Draw(panel)
        yy = y0 + 22
        pd.text((x0 + 26, yy), lb["said"], font=font(th.ui_regular, 22), fill=(200, 200, 200, 255))
        yy += 34
        said_font = font(th.target_regular, 32)
        for s in wrap(pd, ln.said, said_font, x1 - x0 - 52):
            pd.text((x0 + 26, yy), s, font=said_font, fill=(255, 150, 150, 255))
            sw = pd.textlength(s, font=said_font)
            pd.line((x0 + 26, yy + 22, x0 + 26 + sw, yy + 22), fill=(255, 110, 110, 255), width=3)
            yy += 44
        yy += 6
        pd.text((x0 + 26, yy), f"→ {lb[ln.fix_kind]}", font=font(th.ui_bold, 24), fill=(150, 230, 170, 255))
        yy = draw_block(pd, (x0 + 26, yy + 34), ln.text, font(th.target_bold, 34), x1 - x0 - 52, (170, 240, 185, 255))
        if ln.fix_note:
            prefix = lb["point"] if ln.fix_kind == "model" else lb["reason"]
            yy = draw_block(pd, (x0 + 26, yy + 8), prefix + ln.fix_note, font(th.native_regular, 26), x1 - x0 - 52,
                            (240, 240, 240, 255))
        box = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(box).rounded_rectangle((x0, y0, x1, yy + 22), 20, fill=(18, 26, 22, 215))
        over.alpha_composite(box)
        over.alpha_composite(panel)
    if shadow_cue:
        cue = lb["shadow"]
        cf = font(th.ui_bold, 32)
        cw = d.textlength(cue, font=cf)
        d.rounded_rectangle((W - cw - 80, 28, W - 32, 92), 16, fill=(60, 140, 90, 230))
        d.text((W - cw - 56, 38), cue, font=cf, fill=(255, 255, 255, 255))
    img.alpha_composite(over)
    return img.convert("RGB")


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if w.getframerate() != SR:
            raise ValueError(f"{path}: expected {SR} Hz")
    return a


def silence(sec: float) -> np.ndarray:
    return np.zeros(int(SR * sec), dtype=np.int16)


def render(lines: list[Line], out_base: Path, scenario: str, mode_label: str, theme: Theme,
           bg_path: Path | None = None, shadow: bool = False) -> tuple[Path, Path]:
    """Write <out_base>.mp4 and <out_base>.mp3."""
    bg = background(bg_path)
    tmp = Path(tempfile.mkdtemp())
    clips, audio = [], []
    tutor_emo, user_emo = "neutral", "neutral"
    for i, ln in enumerate(lines):
        if ln.who == "tutor":
            tutor_emo = ln.emotion
        else:
            user_emo = ln.emotion
        f = tmp / f"f{i:03d}.png"
        frame(bg, ln, scenario, mode_label, tutor_emo, user_emo, theme).save(f, compress_level=1)
        dur = len(ln.audio) / SR + GAP
        clips.append((f, dur))
        audio += [ln.audio, silence(GAP)]
        if shadow and ln.who == "user":
            g = max(SHADOW_MIN, len(ln.audio) / SR * SHADOW_RATIO)
            fs = tmp / f"f{i:03d}s.png"
            frame(bg, ln, scenario, mode_label, tutor_emo, user_emo, theme, shadow_cue=True).save(fs, compress_level=1)
            clips.append((fs, g))
            audio.append(silence(g))
    wav = tmp / "audio.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.concatenate(audio).tobytes())
    listing = "".join(f"file '{f}'\nduration {d:.3f}\n" for f, d in clips) + f"file '{clips[-1][0]}'\n"
    (tmp / "frames.txt").write_text(listing)
    mp4, mp3 = out_base.with_suffix(".mp4"), out_base.with_suffix(".mp3")
    # still frames: 10 fps is plenty. NVENC (the GPU's separate video encoder, ~no VRAM) if available, else x264
    for codec in (["h264_nvenc", "-preset", "p4", "-cq", "28"], ["libx264", "-tune", "stillimage", "-preset", "veryfast"]):
        try:
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                            "-i", str(tmp / "frames.txt"), "-i", str(wav), "-c:v", *codec, "-pix_fmt", "yuv420p",
                            "-r", "10", "-c:a", "aac", "-b:a", "128k", "-shortest", str(mp4)], check=True)
            break
        except subprocess.CalledProcessError:
            if codec[0] == "libx264":
                raise
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(wav), "-c:a", "libmp3lame", "-q:a", "4", str(mp3)],
                   check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return mp4, mp3

"""Character art for the review videos: one image per emotion, shown beside the subtitles.

  python -m tutor.art import IMAGE_OR_FOLDER... [--role tutor|learner]

Images live in data/characters/<role>/<emotion>.png (neutral, happy, angry, sad, shy, surprised); an optional
data/characters/tutor/icon.png is the page's avatar. You can
also copy transparent PNGs there yourself and set review_video.characters.<role> in config.yaml.

import: each file goes to the emotion named in its file name (happy.png, 02_笑顔.png, tutor-shy.webp …);
a single image is used for every emotion. Backgrounds are removed when they are a plain colour (what image
generators give when asked for a plain background); images that already have transparency are kept as they
are. A transparent or solid green (#00FF00) background works best; a white background can take white
clothes with it. The result goes to data/characters/<role>/<emotion>.png and config.yaml is updated.
"""
import argparse
import re
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .backend import settings as settings_mod

EMOTIONS = ["neutral", "happy", "angry", "sad", "shy", "surprised"]
# file-name keywords per emotion (English, Chinese, Japanese)
KEYWORDS = {
    "neutral": ["neutral", "normal", "default", "calm", "base", "平靜", "平静", "普通", "通常", "平常"],
    "happy": ["happy", "smile", "joy", "laugh", "開心", "开心", "笑", "嬉"],
    "angry": ["angry", "anger", "mad", "annoyed", "生氣", "生气", "怒"],
    "sad": ["sad", "cry", "upset", "難過", "难过", "悲", "泣"],
    "shy": ["shy", "blush", "embarrass", "害羞", "照れ", "恥"],
    "surprised": ["surprise", "shock", "驚", "惊", "びっくり"],
}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
def emotion_of(path: Path) -> str | None:
    name = path.stem.lower()
    for emo, words in KEYWORDS.items():
        if any(w in name for w in words):
            return emo
    return None


def remove_background(img: Image.Image, tolerance: int = 60) -> Image.Image:
    """Make a plain-coloured background transparent: flood-fill from the edges through pixels close to the
    corner colour (so the same colour inside the character survives), then soften the outline and remove the
    background colour that bleeds into edge pixels (green fringe)."""
    img = img.convert("RGBA")
    if img.getchannel("A").getextrema()[0] < 250:  # already has transparency
        return img
    rgb = img.convert("RGB")
    w, h = rgb.size
    corners = [rgb.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    bg = max(set(corners), key=corners.count)
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg)).convert("L")
    marker = diff.point(lambda v: 255 if v <= tolerance else 0)     # pixels that look like background
    green = bg[1] > 200 and bg[0] < 80 and bg[2] < 80
    if green:  # no character is that green: key it everywhere (also pockets between hair strands)
        marker = marker.point(lambda v: 128 if v == 255 else 0)
    for x, y in [(x, 0) for x in range(0, w, 8)] + [(x, h - 1) for x in range(0, w, 8)] + \
                [(0, y) for y in range(0, h, 8)] + [(w - 1, y) for y in range(0, h, 8)]:
        if marker.getpixel((x, y)) == 255:
            ImageDraw.floodfill(marker, (x, y), 128)               # only background connected to the edges
    alpha = marker.point(lambda v: 0 if v == 128 else 255).filter(ImageFilter.MinFilter(3)) \
        .filter(ImageFilter.GaussianBlur(0.8))                     # eat the fringe, soften the cut
    out = img.copy()
    out.putalpha(ImageChops.multiply(img.getchannel("A"), alpha))
    if green:  # spill suppression: semi-transparent hair and edges blended with the green → neutralize it
        px = np.array(out)
        px[..., 1] = np.minimum(px[..., 1], np.maximum(px[..., 0], px[..., 2]))
        out = Image.fromarray(px)
    return out


def prepare(path: Path) -> Image.Image:
    img = remove_background(Image.open(path))
    box = img.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
    return img.crop(box) if box else img


def collect(paths: list[str]) -> list[Path]:
    files = []
    for p in map(Path, paths):
        files += sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXT) if p.is_dir() else [p]
    return files


def cmd_import(args):
    s = settings_mod.load()
    files = collect(args.images)
    if not files:
        raise SystemExit("no images found (png, jpg, webp)")
    if len(files) == 1:
        mapping = {"neutral": files[0]}
    else:
        mapping, unknown = {}, []
        for f in files:
            emo = emotion_of(f)
            if emo is None or emo in mapping:
                unknown.append(f)
            else:
                mapping[emo] = f
        if unknown:
            print("not matched to an emotion (name the file after one, e.g. happy.png): "
                  + ", ".join(f.name for f in unknown))
        if not mapping:
            raise SystemExit(f"none of the file names mention an emotion ({', '.join(EMOTIONS)})")
    out = s.data / "characters" / args.role
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        if old.name != "icon.png":  # the page's avatar, placed by the user
            old.unlink()
    for emo, f in mapping.items():
        prepare(f).save(out / f"{emo}.png")
        print(f"  {emo:9} ← {f.name}")
    if "neutral" not in mapping:  # the renderer falls back to neutral.png for missing emotions
        first = next(iter(mapping))
        Image.open(out / f"{first}.png").save(out / "neutral.png")
        print(f"  neutral   ← (same as {first})")
    missing = [e for e in EMOTIONS if e not in mapping and e != "neutral"]
    if missing:
        print(f"  {', '.join(missing)}: not provided — the neutral image is shown for these")

    cfg_path = settings_mod.path("config.yaml")
    key = "tutor" if args.role == "tutor" else "learner"
    rel = str(out.relative_to(settings_mod.ROOT)) if out.is_relative_to(settings_mod.ROOT) else str(out)
    text = set_character(cfg_path.read_text(encoding="utf-8"), key, rel)
    cfg_path.write_text(text, encoding="utf-8")
    if (yaml.safe_load(text).get("review_video", {}).get("characters") or {}).get(key) == rel:
        print(f"config.yaml: review_video.characters.{key} = {rel} — the next review video shows them\n"
              f"(if the tutor is running, restart it — ./run.sh — so it reads the new setting)")
    else:
        print(f"couldn't edit config.yaml; set review_video.characters.{key}: {rel} yourself")


def set_character(text: str, key: str, value: str) -> str:
    """Set review_video.characters.<key> in the config text, keeping comments. Only lines inside the
    characters: block are touched (voices: has a `tutor:` line too)."""
    m = re.search(r"^  characters:[^\n]*\n((?:    .*\n?)*)", text, flags=re.M)
    if not m:
        return text
    block = re.sub(rf"^(    {key}:\s*)\S+", lambda x: x.group(1) + value, m.group(1), count=1, flags=re.M)
    return text[:m.start(1)] + block + text[m.end(1):]


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    im = sub.add_parser("import", help="import character images (one per emotion, or one for all)")
    im.add_argument("images", nargs="+")
    im.add_argument("--role", choices=["tutor", "learner"], default="tutor")
    cmd_import(ap.parse_args())


if __name__ == "__main__":
    main()

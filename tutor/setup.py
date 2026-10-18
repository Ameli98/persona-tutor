"""First-time setup: a few questions → config.yaml, a persona and conversation topics made for you.

  python -m tutor.setup                     # interactive
  python -m tutor.setup --scenarios-only    # new topics for the current config (keeps the persona)

Answers go into config.yaml (created from config.example.yaml, or edited in place so your voice paths
and comments stay). With an API key, Claude writes a persona from your one-line idea and topics that fit
who you are; without one, the example persona and topics are used. Generated files go to data/
(git-ignored), so your own setup never ends up in the repository.
"""
import argparse
import getpass
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import yaml

from . import lang as langs
from .lang import names
from .backend import settings as settings_mod
from .backend.llm import KEY_FILE, LLMError, make_llm

ROOT = settings_mod.ROOT
# What a new learner gets by pressing Enter: generic, so the tutor still has something sensible to go on
DEFAULT_LEVEL = "intermediate: can follow conversations but is slow to speak"
DEFAULT_PROFILE = "Someone who wants to get comfortable speaking in everyday conversations."
DEFAULT_INTERESTS = "daily life, food, travel, hobbies"
DEFAULT_PERSONA = "a friendly, patient conversation partner"
DEFAULT_NAME = "You"

Q = {
    "en": {
        "target": "Language you want to practise", "native": "Your own language (for translations and explanations)",
        "level": "Your level, in your own words", "profile": "A sentence or two about you (job, studies, situation)",
        "interests": "Things you like talking about (comma-separated)", "name": "Your name in review videos",
        "persona": "Describe the tutor character you'd like in a sentence",
        "n": "How many conversation topics", "gsv": "Where is your GPT-SoVITS folder?",
        "gsv_bad": "  (no GPT_SoVITS/ inside {path} — check the path; you can fix paths.gsv_root in config.yaml later)", "key": "Anthropic API key (hidden; Enter to keep / skip)",
        "overwrite": "config.yaml exists — update it?",
        "intro": "Defaults are in (parentheses): press Enter to use them, or type your own answer.",
        "optional": "optional", "required": "  Please answer this one.",
        "native_examples": "code or English name, e.g. en/zh-TW/vi/French; ? = full list",
        "native_bad": "  Unknown language — use a code like vi or es, or an English name like Vietnamese (? = full list).", "making": "Asking Claude for a persona and topics…",
        "no_llm": "No API key: using the example persona and topics. Run `python -m tutor.setup --scenarios-only` later.",
        "done": "Done.", "next": "Next steps",
        "art": "Optional, for review videos — just drop images in:\n"
               "  {data}/characters/tutor/    the tutor: neutral.png happy.png angry.png sad.png shy.png surprised.png\n"
               "  {data}/characters/learner/  you (same names)\n"
               "  {data}/backgrounds/         default.png, or <topic id>.png per topic\n"
               "  (python -m tutor.art import <folder> removes plain backgrounds from character images)\n\n"
               "Optional: a second voice that re-speaks your lines in review videos (otherwise the tutor's voice does).\n"
               "  Run the voice pipeline again with the name review:\n"
               "  python -m voice.ingest review <recordings>, then check, emotion, select, review, train, screen\n"
               "  It's used automatically once trained.",
    },
    "zh-TW": {
        "target": "想練習的語言", "native": "你的母語（翻譯和說明用）", "level": "你的程度（用自己的話說）",
        "profile": "用一兩句話介紹自己（工作、學業、近況）", "interests": "喜歡聊的話題（用逗號分隔）",
        "name": "你在復盤影片裡的名字", "persona": "用一句話描述你想要的家教角色",
        "n": "要幾個對話話題", "gsv": "GPT-SoVITS 資料夾在哪裡？",
        "gsv_bad": "  （{path} 裡沒有 GPT_SoVITS/，請確認路徑；之後也可以在 config.yaml 的 paths.gsv_root 修改）", "key": "Anthropic API 金鑰（輸入時不顯示；直接 Enter＝保留或略過）",
        "overwrite": "config.yaml 已存在，要更新嗎？",
        "intro": "括號 ( ) 裡是預設值：直接按 Enter 就會使用，或輸入你自己的答案。",
        "optional": "可留空", "required": "  這題需要回答。",
        "native_examples": "語言代碼或英文名稱，例如 en/zh-TW/vi/French；輸入 ? 看全部",
        "native_bad": "  不認得這個語言，請用代碼（例如 vi、es）或英文名稱（例如 Vietnamese）；輸入 ? 看全部。", "making": "請 Claude 產生人設和話題中…",
        "no_llm": "沒有 API 金鑰：先用範例人設和話題。之後可執行 `python -m tutor.setup --scenarios-only`。",
        "done": "完成。", "next": "接下來",
        "art": "選用，復盤影片用——圖片直接放進這些資料夾就好：\n"
               "  {data}/characters/tutor/    家教：neutral.png happy.png angry.png sad.png shy.png surprised.png\n"
               "  {data}/characters/learner/  你自己（同樣的檔名）\n"
               "  {data}/backgrounds/         default.png，或依話題命名的 <話題 id>.png\n"
               "  （角色圖要去背的話：python -m tutor.art import <資料夾>）\n\n"
               "選用：影片裡念你台詞的第二個聲音（沒有的話用家教的聲音）。\n"
               "  用 review 這個名字再跑一次聲音流程：\n"
               "  python -m voice.ingest review <錄音資料夾>，接著 check、emotion、select、review、train、screen\n"
               "  訓練完會自動使用。",
    },
}

GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "persona": {"type": "object", "properties": {
            "name": {"type": "string"}, "profile": {"type": "string"}, "personality": {"type": "string"},
            "speech": {"type": "string"}}, "required": ["name", "profile", "personality", "speech"],
            "additionalProperties": False},
        "scenarios": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "title": {"type": "string"}, "title_target": {"type": "string"},
            "title_native": {"type": "string"}, "setting": {"type": "string"}, "goal": {"type": "string"},
            "angles": {"type": "array", "items": {"type": "string"}}},
            "required": ["id", "title", "title_target", "title_native", "setting", "goal", "angles"],
            "additionalProperties": False}},
    },
    "required": ["persona", "scenarios"],
    "additionalProperties": False,
}


def gen_system(target: str, native: str, n: int) -> str:
    return f"""You design a speaking-practice setup for a language learner. They practise {target} by talking with an AI tutor that plays a character; the tutor leads the conversation and asks follow-up questions.

persona: turn the learner's character idea into a short brief (name, profile, personality, speech). The character must be original — never an existing character from a game, anime, film or book, even if the idea resembles one. speech describes how they talk in {target} (politeness, tone, how they refer to themselves). Write the brief in English. If there is no idea, invent a warm, curious character who fits the learner's interests.

scenarios: exactly {n} conversation topics fitted to this learner (their situation, interests and level). Mix: explaining their own work or studies, opinions and disagreeing politely, requests and declining, storytelling about recent events, small talk that goes deeper, and situations they will really meet. Each topic:
- id: short snake_case English
- title: English; title_target: the title in {target}; title_native: the title in {native}
- setting: what the tutor does in this conversation (refer to the tutor as "the tutor")
- goal: the speaking skill practised, concrete for this learner's level
- angles: 4–5 follow-up directions the tutor can take
Output JSON only."""


def config_path(f: Path) -> str:
    """How config.yaml refers to a file: relative inside the repository, absolute outside it."""
    f = f.resolve()
    return str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else str(f)


def find_gsv(current: str) -> str:
    """Guess the GPT-SoVITS checkout: where install.sh put it (.conda-env line 3), the configured path,
    then a few usual places."""
    installed = (ROOT / ".conda-env").read_text().splitlines()[2:3] if (ROOT / ".conda-env").exists() else []
    for c in (*[Path(x) for x in installed], settings_mod.path(current), ROOT.parent / "GPT-SoVITS", Path.home() / "GPT-SoVITS",
              *sorted(Path.home().glob("*/GPT-SoVITS")), *sorted(Path.home().glob("*/*/GPT-SoVITS"))):
        if (c / "GPT_SoVITS").is_dir():
            return config_path(c)
    return current


DIM = "\033[2m" if sys.stdout.isatty() else ""
RESET = "\033[0m" if sys.stdout.isatty() else ""


HELP_WORDS = {"?", "help", "list", "ls", "more"}


def ask(t: dict, key: str, default: str = "", choices: str = "", show_help=None, optional=False,
        required=False) -> str:
    """Unix convention: the default in parentheses (shown dim), Enter accepts it; options listed first.
    With show_help, typing ? (or help / list) prints the full list and asks again."""
    label = t[key] + (f" {DIM}[{choices}]{RESET}" if choices else "") + (f" {DIM}[{t['optional']}]{RESET}" if optional else "")
    shown = f" {DIM}({default}){RESET}" if default else ""
    while True:
        ans = input(f"{label}{shown}: ").strip()
        if show_help and ans.lower() in HELP_WORDS:
            show_help()
            continue
        if required and not (ans or default):
            print(t["required"])
            continue
        return ans or default


def print_languages():
    """Every language the learner can use as their own: code and English name, in columns."""
    items = [f"{c:<6} {n}" for c, (n, _) in names.VARIANTS.items()] + \
            [f"{c:<6} {n}" for c, n in sorted(names.WHISPER.items(), key=lambda kv: kv[1])]
    width = max(len(x) for x in items) + 2
    cols = max(1, min(4, shutil.get_terminal_size((100, 20)).columns // width))
    rows = -(-len(items) // cols)
    for r in range(rows):
        print("  " + "".join(items[r + c * rows].ljust(width) for c in range(cols) if r + c * rows < len(items)))


def yes(t: dict, key: str) -> bool:
    """[y/N]: the capital letter is the default (no)."""
    return input(f"{t[key]} [y/N]: ").strip().lower() in ("y", "yes")


def yaml_str(v: str) -> str:
    return json.dumps(v, ensure_ascii=False)  # a JSON string is a valid YAML scalar


def set_line(text: str, key: str, value: str, indent: str = "") -> str:
    """Replace the value of `key:` (first match at this indent), keeping the comment after it."""
    pat = re.compile(rf"^({re.escape(indent)}{re.escape(key)}:\s*)([^#\n]*?)(\s*#.*)?$", re.M)
    if not pat.search(text):
        raise ValueError(f"{key} not found in config")
    return pat.sub(lambda m: f"{m.group(1)}{value}{(m.group(3) or '')}", text, count=1)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_") or "topic"


def save_key(key: str):
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(KEY_FILE.parent, 0o700)
    KEY_FILE.write_text(key.strip() + "\n")
    os.chmod(KEY_FILE, 0o600)


def write_persona(p: dict, data: Path) -> Path:
    (data / "personas").mkdir(parents=True, exist_ok=True)
    f = data / "personas" / f"{slug(p['name'])}.yaml"
    f.write_text("# Generated by `python -m tutor.setup`; edit freely.\n" +
                 yaml.safe_dump(p, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8")
    return f


def write_scenarios(scenarios: list[dict], data: Path, target: str, native: str) -> Path:
    """data/scenarios/NN_<id>.yaml; an existing folder is kept as scenarios.bak-<time>."""
    sdir = data / "scenarios"
    if sdir.exists() and any(sdir.iterdir()):
        shutil.move(str(sdir), str(data / f"scenarios.bak-{time.strftime('%Y%m%d-%H%M%S')}"))
    sdir.mkdir(parents=True)
    seen = set()
    for k, sc in enumerate(scenarios, 1):
        sid = slug(sc["id"])
        while sid in seen:
            sid += "_2"
        seen.add(sid)
        doc = {"id": sid, "title": sc["title"], "titles": {target: sc["title_target"], native: sc["title_native"]},
               "setting": sc["setting"], "goal": sc["goal"], "angles": sc["angles"]}
        (sdir / f"{k:02d}_{sid}.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100),
                                                  encoding="utf-8")
    return sdir


def generate(cfg: dict, target: str, native_name: str, profile: str, level: str, interests: str, idea: str, n: int):
    llm = make_llm(cfg["llm"].get("review", cfg["llm"]["feedback"]))
    msg = (f"Learner: {profile}\nLevel in {target}: {level}\nInterests: {interests or '(not given)'}\n"
           f"Native language: {native_name}\nCharacter idea: {idea or '(none)'}")
    out, cost = llm.json_with_cost(gen_system(target, native_name, n), [{"role": "user", "content": msg}], GEN_SCHEMA, 16000)
    return out, cost


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--data", default=None, help="where generated persona/topics go (default: data_dir from config)")
    ap.add_argument("--scenarios-only", action="store_true", help="only make new topics for the current config")
    args = ap.parse_args()
    cfg_path = ROOT / args.config
    exists = cfg_path.exists()
    text = (cfg_path if exists else ROOT / "config.example.yaml").read_text(encoding="utf-8")
    cfg = yaml.safe_load(text)
    print(f"config.yaml: {cfg_path}" + ("" if exists else "  (new / 新建)"))
    mine = cfg if exists else {}  # a new config doesn't offer the example's level and profile as defaults

    ui_default = cfg.get("ui_language", "en")
    ui = input(f"Interface language / 介面語言 {DIM}[en/zh-TW]{RESET} {DIM}({ui_default}){RESET}: ").strip() or ui_default
    t = Q.get(ui, Q["en"])
    print(t["intro"])
    if exists and not args.scenarios_only and not yes(t, "overwrite"):
        return

    available = sorted(p.stem for p in Path(langs.__file__).parent.glob("*.py") if p.stem not in ("__init__", "common", "names"))
    lg = cfg["language"]
    if args.scenarios_only:
        target, native, level = lg["target"], lg["native"], lg["level"]
        profile = cfg.get("learner", {}).get("profile", "")
        interests = ask(t, "interests", DEFAULT_INTERESTS)
        n = int(ask(t, "n", "8"))
        idea = ""
    else:
        target = ask(t, "target", lg["target"], "/".join(available))
        if target not in available:
            raise SystemExit(f"no language module for '{target}' (available: {', '.join(available)}; see tutor/lang/)")
        while True:  # any language Whisper knows, as a code or an English name
            native = names.normalize(ask(t, "native", lg["native"], t["native_examples"], print_languages))
            if native:
                print(f"  → {names.name(native)} ({native})")
                break
            print(t["native_bad"])
        level = ask(t, "level", mine.get("language", {}).get("level") or DEFAULT_LEVEL, required=True)
        profile = ask(t, "profile", mine.get("learner", {}).get("profile") or DEFAULT_PROFILE)
        interests = ask(t, "interests", DEFAULT_INTERESTS)
        name = ask(t, "name", mine.get("learner", {}).get("name") or DEFAULT_NAME)
        gsv = ask(t, "gsv", find_gsv(cfg["paths"]["gsv_root"]))
        if not (settings_mod.path(gsv) / "GPT_SoVITS").is_dir():
            print(t["gsv_bad"].format(path=gsv))
        idea = ask(t, "persona", DEFAULT_PERSONA)
        n = int(ask(t, "n", "8"))
        key = getpass.getpass(t["key"] + ": ").strip()
        if key:
            save_key(key)
            print(f"  → {KEY_FILE} (600)")

    target_name = langs.load(target).NAME
    native_name = names.name(native)
    data = Path(args.data) if args.data else settings_mod.path(cfg.get("data_dir", "data"))

    persona_rel = scen_rel = None
    try:
        print(t["making"], flush=True)
        out, cost = generate(cfg, target_name, native_name, profile, level, interests, idea, n)
        if not args.scenarios_only:
            persona_rel = config_path(write_persona(out["persona"], data))
            print(f"  persona: {out['persona']['name']} → {persona_rel}")
        scen_rel = config_path(write_scenarios(out["scenarios"], data, target, native))
        for sc in out["scenarios"]:
            print(f"  · {sc['title_target']}  ({sc['title_native']})")
        print(f"  cost ${cost:.3f}")
    except LLMError as e:
        print(f"{t['no_llm']} ({e})")

    if not args.scenarios_only:
        text = set_line(text, "target", target, "  ")
        text = set_line(text, "native", native, "  ")
        text = set_line(text, "level", yaml_str(level), "  ")
        text = set_line(text, "ui_language", ui)
        text = set_line(text, "profile", yaml_str(profile), "  ")
        text = set_line(text, "name", yaml_str(name), "  ")
        text = set_line(text, "gsv_root", yaml_str(gsv), "  ")
        if persona_rel:
            text = set_line(text, "persona", persona_rel)
    if scen_rel:
        text = set_line(text, "scenarios", scen_rel)
    cfg_path.write_text(text, encoding="utf-8")
    yaml.safe_load(cfg_path.read_text(encoding="utf-8"))  # fail loudly if the edit broke the YAML
    for sub in ("characters/tutor", "characters/learner", "backgrounds"):
        (data / sub).mkdir(parents=True, exist_ok=True)
    print(f"\n{t['done']} {cfg_path.name}\n{t['next']}:\n"
          f"  1. python -m voice.ingest tutor <your recordings>, then the other voice steps (README.md)\n"
          f"  2. ./run.sh  →  http://localhost:{cfg['server']['port']}\n"
          f"{t['art'].format(data=config_path(data))}")


if __name__ == "__main__":
    main()

"""Load config.yaml, the persona, scenarios and the target-language module in one place."""
import glob
from dataclasses import dataclass
from pathlib import Path

import yaml

from .. import lang as langs
from ..lang import names

ROOT = Path(__file__).resolve().parents[2]


def path(rel: str | Path) -> Path:
    return (ROOT / rel).resolve()


def resolve(pattern: str) -> Path:
    """A config path that may contain a glob (sovits_e8_s*.pth); the last match in sort order wins."""
    hits = sorted(glob.glob(str(path(pattern))))
    if not hits:
        raise FileNotFoundError(f"{pattern} (relative to {ROOT})")
    return Path(hits[-1])


@dataclass
class Settings:
    cfg: dict
    lang: object            # tutor.lang.<target> module
    persona: dict
    scenarios: dict
    assessed_level: str = ""   # from the learner's memory, once there is one (app.py keeps it current)

    @property
    def target(self) -> str:
        return self.lang.NAME

    @property
    def native_code(self) -> str:
        return self.cfg["language"]["native"]

    @property
    def native(self) -> str:
        return names.name(self.native_code)

    @property
    def native_whisper(self) -> str:
        return names.whisper_code(self.native_code)

    @property
    def self_rated_level(self) -> str:
        return self.cfg["language"]["level"]

    @property
    def level(self) -> str:
        """What every prompt goes by: the self-rating in config.yaml is only the starting point."""
        return self.assessed_level or self.self_rated_level

    @property
    def learner(self) -> str:
        return self.cfg.get("learner", {}).get("profile", "")

    @property
    def relationship(self) -> str:
        """Who the learner and the tutor are to each other ("" = friends, the language's default register)."""
        return self.cfg.get("learner", {}).get("relationship") or ""

    @property
    def speech(self) -> str:
        """How corrections and model answers should sound."""
        return f"spoken {self.target} the way people talk who are: {self.relationship}" if self.relationship else f"natural spoken {self.lang.REGISTER}"

    @property
    def data(self) -> Path:
        return path(self.cfg.get("data_dir", "data"))

    def voice(self, role: str) -> dict:
        """{sovits, gpt, refs_list} as resolved paths. A role missing from config.yaml uses
        data/voices/<role>/ when a trained voice is there ("review" falls back to the tutor's voice)."""
        voices = self.cfg["voices"]
        default = {"sovits": f"data/voices/{role}/sovits.pth", "gpt": f"data/voices/{role}/gpt.ckpt",
                   "refs_list": f"data/voices/{role}/refs/refs.list"}
        v = voices.get(role) or (default if all(path(f).exists() for f in default.values()) else voices["tutor"])
        return {k: resolve(v[k]) for k in ("sovits", "gpt", "refs_list")}

    def scenario_title(self, sc: dict, code: str) -> str:
        return sc.get("titles", {}).get(code) or sc["title"]

    def warmup_pool(self) -> list[dict]:
        f = Path(self.lang.__file__).with_name(f"{self.lang.CODE}_warmup.yaml")
        if not f.exists():
            return []
        return [{"text": s["text"], "translation": s.get(self.native_code, "")}
                for s in yaml.safe_load(open(f, encoding="utf-8"))]


def read_yaml(f: Path):
    """yaml.safe_load with an error a hand-editing user can act on instead of a parser traceback."""
    try:
        return yaml.safe_load(open(f, encoding="utf-8"))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f", line {mark.line + 1}" if mark else ""
        raise SystemExit(f"can't read {f}{where}: {getattr(e, 'problem', e)}\n"
                         f"(usually a \": \" or \" #\" inside a text — put that text in quotes, or write it without them)")


def load_scenarios(directory: Path) -> dict:
    out = {}
    for f in sorted(directory.glob("*.yaml")):
        s = read_yaml(f)
        out[s["id"]] = s
    return out


def load(config: str | Path = "config.yaml") -> Settings:
    f = path(config)
    if not f.exists():
        raise SystemExit(f"{f} not found: copy config.example.yaml to config.yaml and edit it")
    cfg = read_yaml(f)
    persona = read_yaml(path(cfg["persona"]))
    return Settings(cfg, langs.load(cfg["language"]["target"]), persona, load_scenarios(path(cfg["scenarios"])))

"""Step 6: train GPT-SoVITS (v2Pro) on train.list and copy the weights into the voice folder.

  python -m voice.train <voice name> [--stage all|prep|s2|s1] [--s2-epochs 8] [--s1-epochs 15] [--batch 4]

Runs GPT-SoVITS's own dataset preparation and training scripts (what its web UI does), single GPU.
Experiments are named pt-<voice name>, so existing models in your GPT-SoVITS folder are never touched.
Stop the tutor first (GPU memory). On an 8 GB laptop GPU (RTX 4070), ~25 min of audio takes 10–15 minutes.
Afterwards data/voices/<name>/ holds sovits.pth and gpt.ckpt; point config.yaml `voices:` at them.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from tutor.backend import settings as settings_mod

from .common import voice_dir

VERSION = "v2Pro"
PRE = "GPT_SoVITS/pretrained_models"
BERT = f"{PRE}/chinese-roberta-wwm-ext-large"
HUBERT = f"{PRE}/chinese-hubert-base"
SV = f"{PRE}/sv/pretrained_eres2netv2w24s4ep4.ckpt"
S2G = f"{PRE}/v2Pro/s2Gv2Pro.pth"
S2D = f"{PRE}/v2Pro/s2Dv2Pro.pth"
S1 = f"{PRE}/s1v3.ckpt"


def env_for(gsv: Path, extra: dict) -> dict:
    env = os.environ.copy()
    # the module paths GPT-SoVITS's web UI adds for its scripts
    env["PYTHONPATH"] = os.pathsep.join(str(gsv / p) for p in ["", "GPT_SoVITS/BigVGAN", "tools", "tools/asr",
                                                              "GPT_SoVITS", "tools/uvr5"]) + os.pathsep + env.get("PYTHONPATH", "")
    env.update({k: str(v) for k, v in extra.items()})
    return env


LOG: Path | None = None   # data/voices/<name>/train.log — GPT-SoVITS's full output goes here


def run(gsv: Path, args: list[str], extra: dict | None = None, label: str = "", epochs: int = 0,
        epoch_re: str = ""):
    """Run a GPT-SoVITS script with its output going to train.log; show one status line instead
    (per-file messages and per-step losses mean nothing to the user). On failure, show the log's tail."""
    import re
    import time
    t0, epoch = time.time(), 0
    tty = sys.stdout.isatty()
    pat = re.compile(epoch_re) if epoch_re else None

    def status(done=False):
        el = time.time() - t0
        if done:
            line = f"{label}  ✓ {el / 60:.0f} min" if el >= 90 else f"{label}  ✓ {el:.0f} s"
        elif epochs and epoch:
            left = el / epoch * (epochs - epoch)
            line = f"{label}  epoch {epoch}/{epochs}  ~{left / 60:.0f} min left"
        else:
            line = f"{label}…"
        if tty:
            sys.stdout.write("\r" + line.ljust(60) + ("\n" if done else ""))
            sys.stdout.flush()
        else:
            print(line, flush=True)  # a log file: one line per stage start, finished epoch and stage end

    status()
    with open(LOG, "a", encoding="utf-8") as log:
        log.write(f"\n===== {label}: {' '.join(args)}\n")
        log.flush()
        start = log.tell()
        proc = subprocess.Popen([sys.executable, "-s", *args], cwd=gsv, env=env_for(gsv, extra or {}),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        buf = ""
        for ch in iter(lambda: proc.stdout.read(256), ""):
            log.write(ch)
            buf += ch
            *done_lines, buf = re.split(r"[\r\n]", buf)
            for ln in done_lines:
                if pat and (m := pat.search(ln)) and int(m.group(1)) > epoch:
                    epoch = int(m.group(1))
                    status()
        proc.wait()
    if proc.returncode != 0:
        if tty:
            print()
        with open(LOG, encoding="utf-8", errors="replace") as f:  # only this stage's output
            f.seek(start)
            tail = f.read().splitlines()[-40:]
        print("\n".join(tail))
        raise SystemExit(f"{label} failed — full output in {LOG}")
    status(done=True)


def prep(gsv: Path, list_path: str, exp: str):
    opt = f"logs/{exp}"
    shutil.rmtree(gsv / opt, ignore_errors=True)  # retraining: features of clips no longer in train.list must go
    base = {"inp_text": list_path, "inp_wav_dir": "", "exp_name": exp, "opt_dir": opt, "i_part": 0, "all_parts": 1,
            "_CUDA_VISIBLE_DEVICES": 0, "is_half": True, "version": VERSION}
    run(gsv, ["GPT_SoVITS/prepare_datasets/1-get-text.py"], {**base, "bert_pretrained_dir": BERT},
        "preparing data 1/4: text")
    (gsv / opt / "2-name2text-0.txt").rename(gsv / opt / "2-name2text.txt")
    run(gsv, ["GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py"], {**base, "cnhubert_base_dir": HUBERT, "sv_path": SV},
        "preparing data 2/4: audio features")
    run(gsv, ["GPT_SoVITS/prepare_datasets/2-get-sv.py"], {**base, "sv_path": SV}, "preparing data 3/4: speaker features")
    run(gsv, ["GPT_SoVITS/prepare_datasets/3-get-semantic.py"],
        {**base, "pretrained_s2G": S2G, "s2config_path": f"GPT_SoVITS/configs/s2{VERSION}.json"},
        "preparing data 4/4: semantic tokens")
    sem = gsv / opt / "6-name2semantic-0.tsv"
    (gsv / opt / "6-name2semantic.tsv").write_text(
        "item_name\tsemantic_audio\n" + sem.read_text(encoding="utf8").strip("\n") + "\n", encoding="utf8")
    sem.unlink()
    n = {"list": sum(1 for _ in open(list_path, encoding="utf8")),
         "text": sum(1 for _ in open(gsv / opt / "2-name2text.txt", encoding="utf8")),
         "wav32k": len(list((gsv / opt / "5-wav32k").glob("*.wav"))),
         "hubert": len(list((gsv / opt / "4-cnhubert").glob("*.pt"))),
         "sv": len(list((gsv / opt / "7-sv_cn").glob("*.pt"))),
         "semantic": sum(1 for _ in open(gsv / opt / "6-name2semantic.tsv", encoding="utf8")) - 1}
    if len(set(n.values())) != 1:
        print("[prep]", n)
        raise SystemExit("[prep] counts differ — some clips failed; see the log above")


def train_s2(gsv: Path, exp: str, epochs: int, batch: int, save_every: int):
    cfg = json.loads((gsv / f"GPT_SoVITS/configs/s2{VERSION}.json").read_text())
    d = f"logs/{exp}"
    (gsv / d / f"logs_s2_{VERSION}").mkdir(parents=True, exist_ok=True)
    cfg["train"].update(batch_size=batch, epochs=epochs, text_low_lr_rate=0.4, pretrained_s2G=S2G, pretrained_s2D=S2D,
                        if_save_latest=True, if_save_every_weights=True, save_every_epoch=save_every, gpu_numbers="0",
                        grad_ckpt=False, lora_rank=32)
    cfg["model"]["version"] = cfg["version"] = VERSION
    cfg["data"]["exp_dir"] = cfg["s2_ckpt_dir"] = d
    cfg["save_weight_dir"] = f"SoVITS_weights_{VERSION}"
    cfg["name"] = exp
    (gsv / "TEMP" / f"{exp}_s2.json").write_text(json.dumps(cfg))
    run(gsv, ["GPT_SoVITS/s2_train.py", "--config", f"TEMP/{exp}_s2.json"], label="training SoVITS",
        epochs=epochs, epoch_re=r"====> Epoch: (\d+)")


def train_s1(gsv: Path, exp: str, epochs: int, batch: int, save_every: int):
    cfg = yaml.safe_load((gsv / "GPT_SoVITS/configs/s1longer-v2.yaml").read_text())
    d = f"logs/{exp}"
    (gsv / d / "logs_s1").mkdir(parents=True, exist_ok=True)
    cfg["train"].update(batch_size=batch, epochs=epochs, save_every_n_epoch=save_every, if_save_every_weights=True,
                        if_save_latest=True, if_dpo=False, half_weights_save_dir=f"GPT_weights_{VERSION}", exp_name=exp)
    cfg.update(pretrained_s1=S1, train_semantic_path=f"{d}/6-name2semantic.tsv", train_phoneme_path=f"{d}/2-name2text.txt",
               output_dir=f"{d}/logs_s1_{VERSION}")
    (gsv / "TEMP" / f"{exp}_s1.yaml").write_text(yaml.dump(cfg, default_flow_style=False))
    # Lightning counts epochs from 0 and prints "Epoch N:" while N is running → N finished when N+1 appears
    run(gsv, ["GPT_SoVITS/s1_train.py", "--config_file", f"TEMP/{exp}_s1.yaml"], {"_CUDA_VISIBLE_DEVICES": 0, "hz": "25hz"},
        "training GPT", epochs=epochs, epoch_re=r"Epoch (\d+):")


def newest(paths) -> Path:
    paths = sorted(paths, key=lambda p: p.stat().st_mtime)
    if not paths:
        raise SystemExit("no trained weights found")
    return paths[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--stage", default="all", choices=["all", "prep", "s2", "s1", "copy"])
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--s2-epochs", type=int, default=8)
    ap.add_argument("--s2-save-every", type=int, default=4)
    ap.add_argument("--s1-epochs", type=int, default=15)
    ap.add_argument("--s1-save-every", type=int, default=5)
    args = ap.parse_args()
    s = settings_mod.load()
    gsv = settings_mod.path(s.cfg["paths"]["gsv_root"])
    d = voice_dir(args.name)
    exp = f"pt-{args.name}"
    if not (d / "train.list").exists():
        raise SystemExit("no train.list; run python -m voice.select first")
    global LOG
    LOG = d / "train.log"
    LOG.write_text("", encoding="utf-8")
    print(f"training '{args.name}' (GPT-SoVITS output: {LOG})")
    for sub in (f"SoVITS_weights_{VERSION}", f"GPT_weights_{VERSION}", "TEMP"):
        (gsv / sub).mkdir(exist_ok=True)  # GPT-SoVITS's web UI creates these on startup

    if args.stage in ("all", "prep"):
        prep(gsv, str(d / "train.list"), exp)
    if args.stage in ("all", "s2"):
        train_s2(gsv, exp, args.s2_epochs, args.batch, args.s2_save_every)
    if args.stage in ("all", "s1"):
        train_s1(gsv, exp, args.s1_epochs, args.batch, args.s1_save_every)
    if args.stage in ("all", "s1", "copy"):
        sovits = newest((gsv / f"SoVITS_weights_{VERSION}").glob(f"{exp}_e*.pth"))
        gpt = newest((gsv / f"GPT_weights_{VERSION}").glob(f"{exp}-e*.ckpt"))
        shutil.copy2(sovits, d / "sovits.pth")
        shutil.copy2(gpt, d / "gpt.ckpt")
        rel = d.relative_to(settings_mod.ROOT)
        print(f"copied {sovits.name} → {d / 'sovits.pth'}\ncopied {gpt.name} → {d / 'gpt.ckpt'}")
        if args.name == "review":
            print("review videos will use this voice for your lines automatically (restart the tutor)")
        elif args.name != "tutor":  # tutor: config.example.yaml already points at data/voices/tutor/
            print(f"\nto use it, set in config.yaml:\nvoices:\n  tutor:   # or review:\n"
                  f"    sovits: {rel}/sovits.pth\n    gpt: {rel}/gpt.ckpt\n    refs_list: {rel}/refs/refs.list")
        print(f"\nnext: python -m voice.screen {args.name}")


if __name__ == "__main__":
    main()

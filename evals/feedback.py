"""Evaluate the live feedback on synthetic lines, on one or more models.

  python -m evals.feedback --label v1 --models claude-sonnet-5-5     # writes evals/results/feedback_<label>.md

A case passes on the verdict alone (and the rewrite containing the expected fix for error / misheard), so no judge
model is needed. Prints pass counts per kind, how often a fine line was called a mistake, and latency. About $0.03 per
Sonnet run. Uses config.example.yaml.
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from tutor.backend import settings
from tutor.backend.llm import make_llm
from tutor.backend.session import Session

HERE = Path(__file__).resolve().parent
ALLOWED = {"fine": {"natural"}, "stiff": {"natural", "suggestion"}, "error": {"error"}, "misheard": {"misheard"},
           "either": {"error", "misheard"}}


def run_case(s, model: str, case: dict) -> dict:
    sess = Session(s, next(iter(s.scenarios.values())), minutes=99)
    llm = make_llm({"provider": "anthropic", "model": model, "effort": "low"})
    t0 = time.time()
    fb = sess.feedback(llm, case["tutor"], case["say"])
    secs = time.time() - t0
    fix_ok = ("fix" not in case or case["fix"] in fb["natural_rewrite"]) and case.get("avoid", "\0") not in fb["natural_rewrite"]
    return {"id": case["id"], "kind": case["kind"], "say": case["say"], "verdict": fb["verdict"], "rewrite": fb["natural_rewrite"],
            "why": fb["feedback"], "passed": fb["verdict"] in ALLOWED[case["kind"]] and fix_ok, "cost": sess.cost, "seconds": round(secs, 2)}


def summary(model: str, results: list[dict]) -> str:
    kinds = {k: [r for r in results if r["kind"] == k] for k in ALLOWED}
    per_kind = " | ".join(f"{sum(r['passed'] for r in v)}/{len(v)}" for v in kinds.values())
    wrongly = sum(r["verdict"] == "error" for k in ("fine", "stiff") for r in kinds[k])
    secs = sorted(r["seconds"] for r in results)
    return (f"| {model} | {sum(r['passed'] for r in results)}/{len(results)} | {per_kind} | {wrongly}/{len(kinds['fine']) + len(kinds['stiff'])} "
            f"| {secs[len(secs) // 2]:.1f} s | ${sum(r['cost'] for r in results):.3f} |")


def evaluate(models: list[str], label: str, s=None):
    s = s or settings.load("config.example.yaml")
    cases = yaml.safe_load((HERE / "feedback_cases.yaml").read_text(encoding="utf-8"))["cases"]
    rows, detail = [], {}
    for model in models:
        with ThreadPoolExecutor(4) as ex:
            detail[model] = list(ex.map(lambda c: run_case(s, model, c), cases))
        rows.append(summary(model, detail[model]))
    misses = [f"- {m} `{r['id']}`: {r['say']} → {r['verdict']} {r['rewrite']}" for m, rs in detail.items() for r in rs if not r["passed"]]
    report = "\n".join([f"## feedback — {label}", "",
                        "| model | passed | fine | stiff | error | misheard | either | fine lines called mistakes | median time | cost |",
                        "|---|---|---|---|---|---|---|---|---|---|", *rows, "", "Failures:", *misses, ""])
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / f"feedback_{label}.md").write_text(report, encoding="utf-8")
    (out / f"feedback_{label}.json").write_text(json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--models", nargs="+", default=["claude-sonnet-5-5"])
    args = ap.parse_args()
    evaluate(args.models, args.label)

"""Evaluate the tutor's use of lookup_past_mistakes.

  python -m evals.tool_calling --label v1        # writes evals/results/tool_calling_v1.{md,json}

For every case in tool_calling_cases.yaml: seed a temporary mistakes database (synthetic records, or none),
ask the question through the real path of the Ask tab (ask.answer → AnthropicLLM.stream_json with the tool), then check
  - call:  did it call lookup_past_mistakes exactly when it should?
  - args:  when the request implies a category / limit, did the call use it?
  - reply: is the final answer sensible given what the tool returned? (an LLM judge, see JUDGE)
A case passes when all three hold. The tutor has both tools throughout, so the cases also check it picks the right one. Uses config.example.yaml (example persona, Japanese, native English), so the
result doesn't depend on anyone's private setup. Costs about $0.3 per run (Opus answers, Sonnet judge).

Results before the "ask-" labels were measured with the tool inside practice, where it used to live.
"""
import argparse
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from tutor.backend import ask, mistakes, settings, texts
from tutor.backend.llm import make_llm

HERE = Path(__file__).resolve().parent
JUDGE_MODEL = {"provider": "anthropic", "model": "claude-sonnet-5-5", "effort": "low"}
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"reasonable": {"type": "boolean"}, "why": {"type": "string"}},
    "required": ["reasonable", "why"],
    "additionalProperties": False,
}
JUDGE = """You grade one answer of a Japanese tutor (a character answering questions in a text chat, for a learner whose
native language is English). The tutor has a tool that returns the learner's recorded past mistakes, and it also has a
summary memory of the learner (shown to you too; claims that match it are grounded). You get the question, what the
tool returned (if it was called) and the answer. Decide if the answer meets the expectation. Judge only the stated
expectation and obvious problems (presenting a mistake that is in neither the tool result nor the memory as the
learner's record, ignoring what the learner asked). Style and length don't matter.
why: one short sentence. Output JSON only."""


def run_case(s, case: dict, spec: dict, reply_cfg: dict, library) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "mistakes.db"
        if case.get("db", "seeded") == "seeded":
            for i, m in enumerate(spec["seed_mistakes"]):
                mistakes.add(db, m["said"], m["corrected"], m["category"], m["reason"],
                             created=f"2026-10-{10 + i:02d} 20:00:00")
        t0 = time.time()
        out = ask.answer(make_llm(reply_cfg), s, spec["memory"], db, [{"role": "user", "content": case["say"]}], lambda chunk: None, library)
        secs = time.time() - t0
        all_calls = [{"name": c["name"], "input": c["input"], "is_error": c["is_error"], "result": c["result"]} for c in out["calls"]]
        calls = [c for c in all_calls if c["name"] == mistakes.TOOL_NAME]
        searched = any(c["name"] == texts.TOOL_NAME for c in all_calls)
    exp = case["expect"]
    called = bool(calls)
    args = [c["input"] or {} for c in calls if not c["is_error"]]
    calls_out = [{"input": c["input"], "is_error": c["is_error"],
                  "count": None if c["is_error"] else mistakes.result_count(c["result"])} for c in calls]
    args_ok = True
    if exp.get("call") and "category" in exp:
        args_ok = any(a.get("category") == exp["category"] for a in args)
    if exp.get("call") and "category2" in exp:
        args_ok = args_ok and any(a.get("category") == exp["category2"] for a in args)
    if exp.get("call") and "limit" in exp:
        args_ok = args_ok and any(a.get("limit") == exp["limit"] for a in args)
    if exp.get("call") and "min_limit" in exp:  # successful calls together returned at least this many rows
        args_ok = args_ok and sum(c["count"] for c in calls_out if c["count"] is not None) >= exp["min_limit"]
    judge_llm = make_llm(JUDGE_MODEL)
    tool_seen = "\n".join(f"{c['name']} {json.dumps(c['input'], ensure_ascii=False)} → {c['result']}" for c in all_calls) or "(not called)"
    search_ok = searched == bool(exp.get("search"))
    verdict, judge_cost = judge_llm.json_with_cost(JUDGE, [{"role": "user", "content": (
        f"Learner memory: {json.dumps(spec['memory'], ensure_ascii=False)}\nThe learner's imported texts, which the tutor knows the titles of: {', '.join(spec['imported_texts'])}\n\nLearner: {case['say']}\n\nTool: {tool_seen}\n\n"
        f"Answer: {out['answer']}\n\n"
        f"Expectation: {case['judge']}")}], JUDGE_SCHEMA, 1000)
    return {"id": case["id"], "kind": case["kind"], "say": case["say"], "expect": exp,
            "called": called, "calls": calls_out,
            "searched": searched, "call_ok": called == bool(exp.get("call")) and search_ok, "args_ok": args_ok, "reply_ok": verdict["reasonable"],
            "why": verdict["why"], "reply": out["answer"],
            "passed": called == bool(exp.get("call")) and search_ok and args_ok and verdict["reasonable"],
            "cost": round(out["cost"] + judge_cost, 4), "seconds": round(secs, 1)}


def table(results: list[dict], label: str) -> str:
    def mark(ok):
        return "✓" if ok else "✗"
    rows = ["| case | kind | learner says | expected | called with | call | args | reply | pass | judge |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        e = r["expect"]
        exp = "search_texts" if e.get("search") else " ".join(["call", *(e[k] for k in ("category", "category2") if k in e),
                        *(f"{k}={e[k]}" for k in ("limit", "min_limit") if k in e)]) if e.get("call") else "no call"
        got = "; ".join(f"{json.dumps(c['input'], ensure_ascii=False)}→{'error' if c['is_error'] else c['count']}"
                        for c in r["calls"]) or ("search_texts" if r["searched"] else "—")
        rows.append(f"| {r['id']} | {r['kind']} | {r['say']} | {exp} | {got} | {mark(r['call_ok'])} | {mark(r['args_ok'])} "
                    f"| {mark(r['reply_ok'])} | **{mark(r['passed'])}** | {r['why']} |")
    by_kind = {}
    for r in results:
        by_kind.setdefault(r["kind"], []).append(r["passed"])
    summary = " · ".join(f"{k} {sum(v)}/{len(v)}" for k, v in by_kind.items())
    total = sum(r["passed"] for r in results)
    cost = sum(r["cost"] for r in results)
    return (f"## tool_calling — {label}\n\npassed **{total}/{len(results)}** ({summary}) · cost ${cost:.3f}\n\n" +
            "\n".join(rows) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--only", nargs="*", help="case ids to run")
    args = ap.parse_args()
    s = settings.load("config.example.yaml")
    spec = yaml.safe_load((HERE / "tool_calling_cases.yaml").read_text(encoding="utf-8"))
    cases = [c for c in spec["cases"] if not args.only or c["id"] in args.only]
    with tempfile.TemporaryDirectory() as tmp:
        library = texts.Library(Path(tmp))
        for title, body in spec["imported_texts"].items():
            library.index(library.add(title, body.encode())["id"])
        with ThreadPoolExecutor(4) as ex:
            results = list(ex.map(lambda c: run_case(s, c, spec, s.cfg["llm"]["ask"], library), cases))
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    report = table(results, args.label)
    (out / f"tool_calling_{args.label}.md").write_text(report, encoding="utf-8")
    (out / f"tool_calling_{args.label}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()

"""Evaluate the coach on the buggy submissions in eval/buggy/.

Every buggy submission was made by mutating a correct solution, so we know the
line that is wrong. For each one we grade it, ask the coach for a hint, and check:

  root cause   does the line the coach blames fall on the injected change?
  baseline     the rule layer alone: is the injected line among its candidates,
               and is its own pick right?
  safety       how often a hint leaked and had to be rewritten or replaced
  cost         latency and tokens per hint

Usage:
    python scripts/eval_coach.py --model ultra --level 2            # all 173
    python scripts/eval_coach.py --model super --level 2 --limit 20
    python scripts/eval_coach.py --summary                          # rebuild eval/coach_eval.json

Per-item results are appended to eval/coach_runs/<model>_L<level>.jsonl, so an
interrupted run resumes where it stopped.
"""

import argparse
import json
import re
import statistics as st
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from w2a import coach, grader, llm, server, tutor  # noqa: E402

OUT_DIR = ROOT / "eval" / "coach_runs"
PRICE = {"ultra": (1.0, 3.0)}  # USD per million input / output tokens; others reported as tokens only
MISSING_OPS = {"drop_assign"}  # the bug is a deleted line: there is no wrong line to point at
NAMES_MISSING = re.compile(
    r"never (assign|drive|set|give)s?|never (assigned|driven|set|given)|not (assigned|driven|connected|set)|"
    r"does not (assign|drive)|doesn't (assign|drive)|undriven|unassigned|no (assignment|driver|value|logic drives)|"
    r"missing|left (floating|unconnected)|nothing (drives|assigns)|floating|unknown \(x\)|"
    r"no (later )?assign|high.impedance", re.I)


def items() -> list[dict]:
    out = []
    for f in sorted((ROOT / "eval" / "buggy").glob("*.json")):
        for i, b in enumerate(json.loads(f.read_text())):
            span_end = b["line"] + b["before"].count("\n")
            out.append({"id": f"{f.stem}:{i}", "slug": f.stem, "op": b["op"], "concept": b["concept"],
                        "line": b["line"], "line_end": span_end, "src": b["src"]})
    return out


def judge(line: int | None, item: dict, tol: int = 0) -> bool:
    return line is not None and item["line"] - tol <= line <= item["line_end"] + tol


def run_one(item: dict, client, model: str, level: int) -> dict:
    pdir = ROOT / "problems" / item["slug"]
    res = grader.grade(pdir, item["src"])
    fb = coach.feedback(item["slug"], pdir, item["src"], res)
    cands = [c["line"] for c in fb["hints"]["L2"]]
    rule_pick = (cands[-1] if len(cands) > 1 else cands[0]) if cands else (fb["compile"] or {}).get("line")
    out = tutor.hint(pdir, server._spec(item["slug"]), item["src"], res, fb, level=level, llm=client, model=model)
    return {
        "id": item["id"], "slug": item["slug"], "op": item["op"], "concept": item["concept"],
        "status": res.status, "line": item["line"], "line_end": item["line_end"],
        "model_line": out["root_cause_line"], "hint": out["hint"],
        "rule_candidates": cands, "rule_pick": rule_pick,
        "fallback": out["fallback"], "retries": out.get("retries", []),
        "latency_s": out["latency_s"], "prompt_tokens": out["prompt_tokens"],
        "completion_tokens": out["completion_tokens"],
    }


def summarise(rows: list[dict], model: str) -> dict:
    n = len(rows)
    if not n:
        return {}
    pct = lambda k: round(100 * k / n, 1)
    lat = sorted(r["latency_s"] for r in rows)
    pin, pout = PRICE.get(model, (None, None))
    cost = (sum(r["prompt_tokens"] for r in rows) * pin + sum(r["completion_tokens"] for r in rows) * pout) / 1e6 if pin else None
    by_status = {}
    for r in rows:
        by_status.setdefault(r["status"], []).append(r)
    located = [r for r in rows if r["op"] not in MISSING_OPS]
    missing = [r for r in rows if r["op"] in MISSING_OPS]
    return {
        "n": n,
        "root_cause_exact_pct": pct(sum(judge(r["model_line"], r) for r in rows)),
        "located_bugs": {"n": len(located),
                         "root_cause_exact_pct": round(100 * sum(judge(r["model_line"], r) for r in located) / len(located), 1) if located else None,
                         "rule_pick_exact_pct": round(100 * sum(judge(r["rule_pick"], r) for r in located) / len(located), 1) if located else None},
        "missing_statement_bugs": {"n": len(missing),
                                   "hint_names_unassigned_signal_pct": round(100 * sum(bool(NAMES_MISSING.search(r["hint"])) for r in missing) / len(missing), 1) if missing else None},
        "root_cause_pm1_pct": pct(sum(judge(r["model_line"], r, 1) for r in rows)),
        "rule_pick_exact_pct": pct(sum(judge(r["rule_pick"], r) for r in rows)),
        "rule_candidates_contain_pct": pct(sum(any(judge(c, r) for c in r["rule_candidates"]) for r in rows)),
        "by_status": {s: {"n": len(v), "root_cause_exact_pct": round(100 * sum(judge(r["model_line"], r) for r in v) / len(v), 1)}
                      for s, v in by_status.items()},
        "leak_rewrites_pct": pct(sum("leak" in r["retries"] for r in rows)),
        "fallback_leak_pct": pct(sum(r["fallback"] == "leak" for r in rows)),
        "fallback_error_pct": pct(sum(r["fallback"] == "error" for r in rows)),
        "latency_p50_s": round(st.median(lat), 2),
        "latency_p90_s": round(lat[int(0.9 * (n - 1))], 2),
        "tokens_mean": round(st.mean(r["prompt_tokens"] + r["completion_tokens"] for r in rows)),
        "cost_usd_total": round(cost, 3) if cost is not None else None,
        "cost_usd_per_hint": round(cost / n, 4) if cost is not None else None,
    }


def write_summary() -> dict:
    summary = {}
    for f in sorted(OUT_DIR.glob("*.jsonl")):
        rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        model = f.stem.split("_L")[0]
        summary[f.stem] = summarise(rows, model)
    (ROOT / "eval" / "coach_eval.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="ultra", choices=sorted(llm.MODELS))
    ap.add_argument("--level", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--status", choices=["mismatch", "compile_error"], help="only items with this grader status")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()
    if args.summary:
        print(json.dumps(write_summary(), indent=2))
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{args.model}_L{args.level}.jsonl"
    done = {json.loads(l)["id"] for l in path.read_text().splitlines() if l.strip()} if path.is_file() else set()
    todo = [i for i in items() if i["id"] not in done]
    if args.status:
        todo = [i for i in todo if grader.grade(ROOT / "problems" / i["slug"], i["src"]).status == args.status]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(done)} done, {len(todo)} to run with {args.model} at L{args.level}", flush=True)

    client = llm.TokenFactory(timeout=90.0, max_retries=1)
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as pool, path.open("a") as fh:
        futures = {pool.submit(run_one, i, client, args.model, args.level): i for i in todo}
        for k, fut in enumerate(as_completed(futures), 1):
            row = fut.result()
            with lock:
                fh.write(json.dumps(row) + "\n")
                fh.flush()
            ok = "OK " if judge(row["model_line"], row) else "-- "
            print(f"[{k}/{len(todo)}] {ok}{row['id']:22s} {row['op']:24s} line {row['line']} -> {row['model_line']} "
                  f"{row['latency_s']}s {row['fallback'] or ''}", flush=True)
    print(json.dumps(write_summary().get(path.stem, {}), indent=2))


if __name__ == "__main__":
    main()

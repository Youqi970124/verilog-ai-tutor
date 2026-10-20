"""Mutation-test every problem that has a reference solution.

For each problem, the reference solution is turned into beginner-style buggy
versions (w2a/mutate.py) and graded. Writes:

  eval/buggy/<slug>.json   killed mutants = buggy submissions for evaluating the coach
  eval/mutation_report.json  per-problem counts, survivors listed for review

Usage:
    python scripts/mutation_report.py [slug ...]
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from w2a import mutate  # noqa: E402


def solution_for(problem_dir: Path) -> str | None:
    """A learner-style solution: solution.sv if the problem has one, else the reference."""
    if (problem_dir / "solution.sv").is_file():
        return (problem_dir / "solution.sv").read_text()
    if (problem_dir / "ref.sv").is_file():
        return re.sub(r"\bmodule\s+RefModule\b", "module top_module", (problem_dir / "ref.sv").read_text())
    return None


def main() -> None:
    curriculum = json.loads((ROOT / "curriculum" / "curriculum.json").read_text())
    slugs = [p["slug"] for s in curriculum["stages"] for p in s["problems"]]
    if len(sys.argv) > 1:
        slugs = [s for s in slugs if s in sys.argv[1:]]

    out_dir = ROOT / "eval" / "buggy"
    out_dir.mkdir(parents=True, exist_ok=True)
    report, totals = {}, {"killed": 0, "survived": 0, "equivalent": 0, "stillborn": 0}
    for slug in slugs:
        pdir = ROOT / "problems" / slug
        sol = solution_for(pdir)
        if sol is None:
            print(f"{slug:14s} (no solution yet)")
            continue
        results = mutate.evaluate(pdir, sol)
        sc = mutate.score(results)
        for k in totals:
            totals[k] += sc[k]
        report[slug] = {**sc, "survivors": [r.mutant.description + f" [{r.mutant.op}]"
                                             for r in results if r.status == "survived"]}
        buggy = [{"op": r.mutant.op, "concept": r.mutant.concept, "line": r.mutant.line,
                  "before": r.mutant.before, "after": r.mutant.after, "detail": r.detail, "src": r.mutant.src}
                 for r in results if r.status in ("killed", "stillborn")]
        (out_dir / f"{slug}.json").write_text(json.dumps(buggy, indent=2) + "\n")
        print(f"{slug:14s} killed {sc['killed']:2d}  survived {sc['survived']:2d}  "
              f"equivalent {sc['equivalent']:2d}  stillborn {sc['stillborn']:2d}  kill rate {sc['kill_rate']}")

    judged = totals["killed"] + totals["survived"]
    totals["kill_rate"] = round(totals["killed"] / judged, 3) if judged else None
    (ROOT / "eval" / "mutation_report.json").write_text(json.dumps({"totals": totals, "problems": report}, indent=2) + "\n")
    print("\nTOTAL", totals)


if __name__ == "__main__":
    main()

"""Run the authoring agent on the outlines in curriculum/outlines.json.

Usage:
    python scripts/author.py --dry-run               # print the prompts, no model calls
    python scripts/author.py module_add              # one problem with Nemotron 3 Ultra
    python scripts/author.py --model super --rounds 3 module_add module_cseladd
    python scripts/author.py --overwrite             # all 9, replacing existing ones

Each finished problem lands in problems/<slug>/ with review: "pending" and an
authoring_log.json holding every round, the token usage and the transcript.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from w2a import authoring, llm  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--model", default=authoring.DEFAULT_MODEL, choices=sorted(llm.MODELS))
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    outlines = json.loads((ROOT / "curriculum" / "outlines.json").read_text())["problems"]
    slugs = args.slugs or list(outlines)
    unknown = [s for s in slugs if s not in outlines]
    if unknown:
        sys.exit(f"no outline for {unknown}")

    if args.dry_run:
        for slug in slugs:
            print(f"===== {slug}\n{authoring.first_prompt(slug, outlines[slug])}\n")
        print(f"(system prompt: {len(authoring.SYSTEM)} characters; no model was called)")
        return

    client = llm.TokenFactory()
    summary = []
    for slug in slugs:
        res = authoring.author(slug, outlines[slug], client, out_root=ROOT / "problems", model=args.model,
                               max_rounds=args.rounds, overwrite=args.overwrite)
        tokens = sum((r.usage.get("total_tokens") or 0) for r in res.rounds)
        summary.append((slug, res.ok, len(res.rounds), tokens, len(res.survivors)))

    print("\nslug             ok     rounds  tokens  survivors")
    for slug, ok, rounds, tokens, surv in summary:
        print(f"{slug:16s} {str(ok):6s} {rounds:6d} {tokens:7d} {surv:9d}")


if __name__ == "__main__":
    main()

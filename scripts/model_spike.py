"""Day-1 check: can each Nemotron model on Nebius Token Factory solve the imported problems?

Sends each VerilogEval spec-to-RTL prompt to each model once (temperature 0),
grades the answer with our own grader, and writes results/model_spike.json.

Usage:
    export NEBIUS_API_KEY=...
    python scripts/model_spike.py [--models lightning,super,ultra] [--problems wire,andgate]
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from w2a import grader  # noqa: E402

MODELS = {
    "lightning": "nvidia/Nemotron-3_5-Lightning",
    "super": "nvidia/nemotron-3-super-120b-a12b",
    "ultra": "nvidia/Nemotron-3-Ultra-550b-a55b",
}
BASE_URLS = [
    os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"),
    "https://api.tokenfactory.us-central1.nebius.com/v1/",  # the cookbook uses this for Super and Ultra
]
SYSTEM = ("You are an expert digital designer. Answer with one complete Verilog module named TopModule "
          "inside a single ```verilog code block. Do not include a testbench.")


def _dotenv() -> dict[str, str]:
    path = ROOT / ".env"  # git-ignored
    if not path.is_file():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))
    return {k.strip(): v.strip().strip("\"'") for k, v in pairs}


def extract_verilog(text: str) -> str | None:
    blocks = re.findall(r"```(?:verilog|systemverilog|sv)?\s*\n(.*?)```", text, flags=re.S)
    for block in reversed(blocks):
        if "module" in block and "endmodule" in block:
            return block
    m = re.findall(r"(module\s+TopModule\b.*?endmodule)", text, flags=re.S)
    return m[-1] if m else None


def ask(clients: list[OpenAI], model: str, prompt: str) -> tuple[str, dict]:
    last_err = None
    for client in clients:
        try:
            t0 = time.time()
            resp = client.chat.completions.create(
                model=model, temperature=0, max_tokens=8192,
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            )
            usage = resp.usage.model_dump() if resp.usage else {}
            return resp.choices[0].message.content or "", {
                "latency_s": round(time.time() - t0, 2), "base_url": str(client.base_url), **usage}
        except Exception as exc:  # try the next region on model-not-found style errors
            last_err = exc
    raise RuntimeError(f"{model}: {last_err}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--problems", default="")
    args = ap.parse_args()

    key = os.environ.get("NEBIUS_API_KEY") or _dotenv().get("NEBIUS_API_KEY")
    if not key:
        sys.exit("Set NEBIUS_API_KEY, or put NEBIUS_API_KEY=... in .env at the repo root.")
    clients = [OpenAI(base_url=u, api_key=key) for u in dict.fromkeys(BASE_URLS)]

    curriculum = json.loads((ROOT / "curriculum" / "curriculum.json").read_text())
    slugs = [p["slug"] for s in curriculum["stages"] for p in s["problems"] if p["verilogeval"]]
    if args.problems:
        slugs = [s for s in slugs if s in args.problems.split(",")]

    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    rows = []
    for short in args.models.split(","):
        model = MODELS[short]
        for slug in slugs:
            prompt = (ROOT / "problems" / slug / "prompt.txt").read_text()
            row = {"model": model, "problem": slug}
            try:
                text, meta = ask(clients, model, prompt)
                row.update(meta)
                code = extract_verilog(text)
                if code is None:
                    row.update(status="no_code", category="-", reply=text[:4000])
                else:
                    res = grader.grade(ROOT / "problems" / slug, code)
                    row.update(status=res.status, category=res.category, mismatches=res.mismatches)
                    if not res.passed:  # keep what failed; temperature 0 is not deterministic here
                        log = (res.compile_log + res.sim_log).splitlines()
                        row.update(code=code, log=[l for l in log if "Hint" in l or "error" in l.lower()][:20])
            except Exception as exc:
                row.update(status="api_error", category="-", error=str(exc)[:300])
            rows.append(row)
            print(f"{short:9s} {slug:12s} {row['status']:14s} {row.get('latency_s', '')}", flush=True)

    (out_dir / "model_spike.json").write_text(json.dumps(rows, indent=2) + "\n")
    print("\npass@1 (temperature 0)")
    for short in args.models.split(","):
        mine = [r for r in rows if r["model"] == MODELS[short]]
        passed = sum(r["status"] == "pass" for r in mine)
        toks = sum(r.get("total_tokens", 0) or 0 for r in mine)
        print(f"  {short:9s} {passed}/{len(mine)}  total tokens {toks}")


if __name__ == "__main__":
    main()

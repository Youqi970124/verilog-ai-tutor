"""Copy what the web app needs into a Hugging Face Space checkout.

Usage:
    git clone https://huggingface.co/spaces/<user>/wire-to-adder ../space
    python scripts/build_space.py ../space [--github https://github.com/<user>/wire-to-adder]
    cd ../space && git add -A && git commit -m "Deploy" && git push

The Space gets the Dockerfile, the app and the problems, plus a README whose
front matter tells Spaces to build with Docker and serve port 8000. Tests,
scripts and evaluation data stay in the GitHub repository.
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPY = ["Dockerfile", ".dockerignore", "LICENSE", "THIRD_PARTY_NOTICES.md", "w2a", "web", "curriculum", "problems"]

README = """---
title: Wire-to-Adder
emoji: 🔌
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
license: mit
short_description: Verilog coach from a single wire to a 32-bit adder
---

# Wire-to-Adder

A Verilog coaching agent for the first 28 [HDLBits](https://hdlbits.01xz.net/) problems, from connecting a
single wire to building a 32-bit adder-subtractor. You write the circuit; Icarus Verilog simulates it; the
coach shows the first wrong sample, the lines that drive it, and hints from NVIDIA Nemotron 3 Ultra on
Nebius Token Factory that never hand over the answer.

Built for the Nebius x NVIDIA Global AI Hackathon, Coding & Agentic Engineering track.
{github}
The AI coach needs the `NEBIUS_API_KEY` secret. Without it, everything else still works and the hint
ladder uses the rule-based hints.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--github", default="")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    if not (target / ".git").is_dir():
        sys.exit(f"{target} is not a git checkout of the Space; clone it first")
    if target == ROOT or ROOT in target.parents:
        sys.exit("target must be outside the source repository")

    for item in target.iterdir():  # replace everything except the Space's own git data
        if item.name in (".git", ".gitattributes"):
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    for name in COPY:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, target / name)
    gh = f"\nSource, tests and evaluation: {args.github}\n" if args.github else ""
    (target / "README.md").write_text(README.format(github=gh))
    files = sum(1 for p in target.rglob("*") if p.is_file() and ".git" not in p.parts)
    print(f"Space files ready in {target} ({files} files). Next: git add -A, commit, push.")


if __name__ == "__main__":
    main()

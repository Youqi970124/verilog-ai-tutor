"""Copy the VerilogEval problems used by the curriculum into problems/<slug>/.

Usage:
    python scripts/import_verilogeval.py path/to/verilog-eval

The prompt, reference solution and testbench are copied unmodified. Each
problem directory also gets a SOURCE.json recording where the files came from.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {"prompt.txt": "_prompt.txt", "ref.sv": "_ref.sv", "test.sv": "_test.sv"}


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    veval = Path(sys.argv[1]).resolve()
    dataset = veval / "dataset_spec-to-rtl"
    commit = subprocess.run(
        ["git", "-C", str(veval), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    curriculum = json.loads((ROOT / "curriculum" / "curriculum.json").read_text())
    copied = 0
    for stage in curriculum["stages"]:
        for prob in stage["problems"]:
            pid = prob["verilogeval"]
            if pid is None:
                continue
            dest = ROOT / "problems" / prob["slug"]
            dest.mkdir(parents=True, exist_ok=True)
            for name, suffix in FILES.items():
                src = dataset / f"{pid}{suffix}"
                if not src.is_file():
                    sys.exit(f"missing {src}")
                shutil.copyfile(src, dest / name)
            (dest / "SOURCE.json").write_text(json.dumps({
                "source": "NVlabs/verilog-eval (MIT License)",
                "url": "https://github.com/NVlabs/verilog-eval",
                "commit": commit,
                "problem": pid,
                "task": "spec-to-rtl",
            }, indent=2) + "\n")
            copied += 1
    print(f"copied {copied} problems from {dataset} @ {commit[:12]}")


if __name__ == "__main__":
    main()

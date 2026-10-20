"""Formal equivalence of two learner-style designs with Yosys.

Used when a mutant passes the testbench: either the mutant is equivalent to the
solution (nothing to catch) or the testbench is too weak. A bounded SAT proof
over a miter tells the two apart.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

SEQ_STEPS = 12
TIMEOUT_S = 60

_SCRIPT = """\
{read} gold.sv
hierarchy -top top_module
proc; flatten; opt_clean
rename top_module gold
design -stash gold
{read} gate.sv
hierarchy -top top_module
proc; flatten; opt_clean
rename top_module gate
design -stash gate
design -copy-from gold -as gold gold
design -copy-from gate -as gate gate
miter -equiv -flatten -make_assert gold gate miter
hierarchy -top miter
sat -verify -prove-asserts -set-init-zero -seq {seq} miter
"""


def yosys_path() -> str | None:
    bindir = os.environ.get("W2A_TOOLCHAIN_BIN")
    return shutil.which("yosys", path=bindir) if bindir else shutil.which("yosys")


def _top(src: str) -> str:
    return re.sub(r"\bmodule\s+(TopModule|RefModule)\b", "module top_module", src)


def equivalent(gold_src: str, gate_src: str, given_src: str = "", *, seq: int = SEQ_STEPS) -> bool | None:
    """True if equivalent for `seq` cycles from a zero reset state, False if a
    difference exists, None if Yosys is missing or could not decide.

    Each SAT step is one clock cycle, so clock-edge polarity is abstracted away:
    a posedge and a negedge flip-flop compare as equivalent. None of the
    mutation operators changes clock edges."""
    yosys = yosys_path()
    if not yosys:
        return None
    with tempfile.TemporaryDirectory(prefix="w2a-eq-") as tmp:
        work = Path(tmp)
        (work / "gold.sv").write_text(_top(gold_src))
        (work / "gate.sv").write_text(_top(gate_src))
        read = "read_verilog -sv"
        if given_src.strip():
            (work / "given.sv").write_text(given_src)
            read = "read_verilog -sv given.sv"
        (work / "eq.ys").write_text(_SCRIPT.format(read=read, seq=seq))
        try:
            proc = subprocess.run([yosys, "-q", "-s", "eq.ys"], cwd=work, capture_output=True,
                                  text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return None
        log = proc.stdout + proc.stderr
        if proc.returncode == 0:
            return True
        if "SAT proof finished - model found: FAIL" in log or "Called with -verify and proof did fail" in log:
            return False
        return None

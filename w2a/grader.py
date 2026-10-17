"""Compile and simulate learner code against a problem's reference solution.

Uses the same Icarus Verilog flags and timeout as the VerilogEval harness, and
the same failure categories as its scripts/sv-iv-analyze.
"""

import json
import os
import re
import resource
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import safety, vcd

IVERILOG_FLAGS = ["-Wall", "-Winfloop", "-Wno-timescale", "-g2012", "-s", "tb"]
SIM_TIMEOUT_S = 30
COMPILE_TIMEOUT_S = 30

# Failure codes from VerilogEval's scripts/sv-iv-analyze, plus "X" for code we refuse to run.
CATEGORIES = {
    ".": "pass",
    "S": "syntax error",
    "e": "assignment needs an explicit cast",
    "0": "sized constant with zero width",
    "n": "always block with no sensitivities never runs",
    "w": "procedural assignment to a wire",
    "m": "unknown module type",
    "p": "undeclared signal or bad port connection",
    "c": "clock is not connected",
    "C": "other compile error",
    "T": "simulation timed out",
    "r": "outputs mismatch (check reset handling)",
    "R": "outputs mismatch",
    "X": "rejected before compiling",
    "M": "simulation passes but required module instances are missing",
}

_HINT_RE = re.compile(r"^Hint: Output '([^']+)' has (\d+) mismatches\. First mismatch occurred at time (\d+)\.$")
_OK_RE = re.compile(r"^Hint: Output '([^']+)' has no mismatches\.$")
_TOTAL_RE = re.compile(r"^Mismatches: (\d+) in (\d+) samples$")


@dataclass
class OutputResult:
    name: str
    mismatches: int
    first_mismatch_time: int | None


@dataclass
class GradeResult:
    status: str  # pass | mismatch | compile_error | timeout | rejected | error
    category: str
    category_text: str
    mismatches: int | None = None
    samples: int | None = None
    outputs: list[OutputResult] = field(default_factory=list)
    compile_log: str = ""
    sim_log: str = ""
    counterexample: dict | None = None
    history: list[dict] = field(default_factory=list)
    reject_line: int | None = None
    structure_issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict:
        return asdict(self)


def _tool(name: str) -> str:
    bindir = os.environ.get("W2A_TOOLCHAIN_BIN")
    path = shutil.which(name, path=bindir) if bindir else shutil.which(name)
    if not path:
        raise FileNotFoundError(f"{name} not found; install Icarus Verilog 12 or set W2A_TOOLCHAIN_BIN")
    return path


def _limits(cpu_s: int):
    def apply():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 << 20, 64 << 20))
    return apply


def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int | None, str]:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, errors="replace",
            timeout=timeout, preexec_fn=_limits(timeout + 5), env={"PATH": "/usr/bin:/bin"},
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"") + (exc.stderr or b"")
        return None, out.decode("utf-8", "replace") if isinstance(out, bytes) else str(out)
    return proc.returncode, proc.stdout + proc.stderr


def to_testbench_name(src: str) -> str:
    """Learners write HDLBits' top_module; the VerilogEval testbench expects TopModule."""
    return re.sub(r"\bmodule\s+top_module\b", "module TopModule", src)


def classify(log: str) -> str:
    """Same precedence as VerilogEval's sv-iv-analyze."""
    error_c = error_p = False
    no_mismatch = False
    for line in log.splitlines():
        if "syntax error" in line:
            return "S"
        if "error" in line:
            error_c = True
        if "error: This assignment requires an explicit cast" in line:
            return "e"
        if "error: Sized numeric constant must have a size greater than zero" in line:
            return "0"
        if "warning: always_comb process has no sensitivities" in line:
            return "n"
        if "found no sensitivities so it will never trigger" in line:
            return "n"
        if "is declared here as wire" in line:
            return "w"
        if "Unknown module type" in line:
            return "m"
        if "Unable to bind wire/reg" in line:
            error_p = True
        if "Unable to bind wire/reg/memory `clk'" in line:
            return "c"
        if "TIMEOUT" in line:
            return "T"
        m = _TOTAL_RE.match(line.strip())
        if m and int(m.group(1)) == 0:
            no_mismatch = True
    if error_p:
        return "p"
    if error_c:
        return "C"
    if no_mismatch:
        return "."
    return "?"


def grade(problem_dir: str | Path, learner_src: str, *, sim_timeout: int = SIM_TIMEOUT_S,
          keep_dir: str | Path | None = None) -> GradeResult:
    problem_dir = Path(problem_dir)
    check = safety.check(learner_src)
    if not check.ok:
        return GradeResult("rejected", "X", check.message, reject_line=check.line)

    with tempfile.TemporaryDirectory(prefix="w2a-") as tmp:
        work = Path(keep_dir) if keep_dir else Path(tmp)
        work.mkdir(parents=True, exist_ok=True)
        (work / "TopModule.sv").write_text(to_testbench_name(learner_src))
        shutil.copyfile(problem_dir / "test.sv", work / "test.sv")
        shutil.copyfile(problem_dir / "ref.sv", work / "ref.sv")
        sources = ["TopModule.sv", "test.sv", "ref.sv"]
        if (problem_dir / "given.sv").is_file():  # submodules the problem provides, e.g. add16
            shutil.copyfile(problem_dir / "given.sv", work / "given.sv")
            sources.append("given.sv")

        rc, compile_log = _run(
            [_tool("iverilog"), *IVERILOG_FLAGS, "-o", "sim", *sources],
            work, COMPILE_TIMEOUT_S,
        )
        if rc != 0:
            code = classify(compile_log)
            code = code if code not in (".", "?") else "C"
            return GradeResult("compile_error", code, CATEGORIES[code], compile_log=compile_log)

        rc, sim_log = _run([_tool("vvp"), "-n", "sim"], work, sim_timeout)
        if rc is None:
            return GradeResult("timeout", "T", CATEGORIES["T"], compile_log=compile_log,
                               sim_log=sim_log + "\nTIMEOUT")

        result = _parse_sim(sim_log, compile_log)
        if result.status == "mismatch":
            _attach_waveform(result, work / "wave.vcd")
        result.structure_issues = missing_instances(learner_src, _meta(problem_dir).get("require_instances", {}))
        if result.status == "pass" and result.structure_issues:
            result.status, result.category, result.category_text = "structure", "M", CATEGORIES["M"]
        return result


def _meta(problem_dir: Path) -> dict:
    path = problem_dir / "problem.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def missing_instances(src: str, required: dict[str, int]) -> list[str]:
    """Problems such as module_add are about building from submodules, so a
    behavioural `assign sum = a + b;` should not count as solved."""
    code = safety.strip_comments_and_strings(src)
    issues = []
    for module, count in required.items():
        found = len(re.findall(rf"\b{re.escape(module)}\s*(?:#\s*\([^;]*?\)\s*)?\w+\s*\(", code))
        if found < count:
            issues.append(f"Expected at least {count} instance(s) of {module}, found {found}.")
    return issues


def _parse_sim(sim_log: str, compile_log: str) -> GradeResult:
    outputs, mismatches, samples = [], None, None
    for raw in sim_log.splitlines():
        line = raw.strip()
        if m := _HINT_RE.match(line):
            outputs.append(OutputResult(m.group(1), int(m.group(2)), int(m.group(3))))
        elif m := _OK_RE.match(line):
            outputs.append(OutputResult(m.group(1), 0, None))
        elif m := _TOTAL_RE.match(line):
            mismatches, samples = int(m.group(1)), int(m.group(2))

    code = classify(compile_log + "\n" + sim_log)
    if code == "T":
        status = "timeout"
    elif mismatches is None:
        status, code = "error", "C"
    elif mismatches == 0:
        status, code = "pass", "."
    else:
        status = "mismatch"
        code = code if code in ("r", "R") else "R"
    return GradeResult(status, code, CATEGORIES[code], mismatches, samples, outputs,
                       compile_log=compile_log, sim_log=sim_log)


def _attach_waveform(result: GradeResult, vcd_path: Path) -> None:
    if not vcd_path.is_file():
        return
    first = min((o.first_mismatch_time for o in result.outputs if o.first_mismatch_time is not None),
                default=None)
    if first is None:
        return
    signals = vcd.parse(vcd_path.read_text(errors="replace"))
    result.counterexample = vcd.counterexample(signals, first)
    result.history = vcd.history(signals, first)

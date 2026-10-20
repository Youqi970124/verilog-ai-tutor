"""Coach, rule layer: everything that can be said from the grader's facts alone.

  explain_compile   compile errors and safety rejections in plain words, with the line
  counterexample    L1: the exact inputs, expected and actual outputs at the first mismatch
  locate            L2: the lines that drive the wrong outputs, one hop back through wires
  concept_hint      L0: the concept note for the problem
  structure_hint    L3: the authored structural hint, if the problem has one

A model can later rephrase these or pick the root cause among the candidates,
but it never has to invent facts: they come from the simulator.
"""

import json
import re
from pathlib import Path

from . import safety
from .grader import GradeResult

ROOT = Path(__file__).resolve().parent.parent
_CONCEPTS = json.loads((ROOT / "curriculum" / "concepts.json").read_text())["concepts"]
_CURRICULUM = json.loads((ROOT / "curriculum" / "curriculum.json").read_text())
_PROBLEM_CONCEPTS = {p["slug"]: p["concepts"] for s in _CURRICULUM["stages"] for p in s["problems"]}
_KEYWORDS = {"assign", "wire", "reg", "logic", "input", "output", "module", "endmodule", "always", "begin", "end",
             "if", "else", "case", "endcase", "posedge", "negedge", "or", "and", "not", "genvar", "generate",
             "endgenerate", "for", "integer", "signed", "default"}


# ---------------------------------------------------------------- compile errors

def _first_error(log: str) -> tuple[int | None, str]:
    """(line, message) of the first error in the learner's file."""
    for line in log.splitlines():
        m = re.match(r"\s*TopModule\.sv:(\d+):\s*(.*)", line)
        if m and ("error" in line.lower() or "syntax" in line.lower()):
            return int(m.group(1)), m.group(2).strip()
    for line in log.splitlines():
        if "error" in line.lower():
            return None, line.strip()
    return None, ""


def _src_line(src: str, n: int | None) -> str:
    lines = src.splitlines()
    return lines[n - 1].strip() if n and 0 < n <= len(lines) else ""


def explain_compile(result: GradeResult, src: str, given_modules: list[str] | None = None) -> dict | None:
    if result.status == "rejected":
        return {"line": result.reject_line, "code": _src_line(src, result.reject_line),
                "explanation": result.category_text}
    if result.status == "timeout":
        return {"line": None, "code": "", "explanation":
                "The simulation never finished. Look for a loop that never ends, or a signal that depends on itself."}
    if result.status == "structure":
        return {"line": None, "code": "", "explanation":
                "Your outputs are right, but this problem is about building the circuit from the given modules. "
                + " ".join(result.structure_issues)}
    if result.status not in ("compile_error", "error"):
        return None

    line, msg = _first_error(result.compile_log)
    code = _src_line(src, line)
    cat = result.category
    name = None
    if m := re.search(r"Unable to bind wire/reg/memory `([^']+)'", msg + result.compile_log):
        name = m.group(1).split(".")[-1]
    if cat == "S":
        prev = next((l.strip() for l in reversed(src.splitlines()[: (line or 1) - 1]) if l.strip()), "")
        if prev and not prev.endswith((";", "(", ",", "begin", ")", "endmodule")) and not prev.startswith("//"):
            text = f"Line {line - 1 if line else '?'} probably needs a semicolon at the end: `{prev}`."
        else:
            text = f"Line {line} has a syntax error. Check for a missing semicolon, and that every (, {{ and begin is closed."
    elif cat == "p":
        text = f"`{name}` is used but never declared. Check the spelling, or declare it with `wire`." if name else \
            "A signal is used but never declared. Check the spelling of each name on this line."
    elif cat == "w":
        m = re.search(r"(\w+) is not a valid l-value", result.compile_log)
        target = m.group(1) if m else "this signal"
        text = (f"`{target}` is assigned inside an always block but declared as a wire. "
                "Use `assign` for it, or declare it as `reg`.")
    elif cat == "m":
        m = re.search(r"Unknown module type: (\w+)", result.compile_log)
        avail = f" The modules you can use here are: {', '.join(given_modules)}." if given_modules else ""
        text = f"There is no module called `{m.group(1) if m else '?'}`. Check the spelling.{avail}"
    elif cat == "n":
        text = "An always block has nothing in its sensitivity list, so it never runs. Use `always @(*)` for combinational logic."
    elif cat == "e":
        text = "This assignment mixes types that need an explicit conversion. Check the widths and types on both sides."
    elif cat == "0":
        text = "A sized number has width zero, for example 0'b0. Every sized constant needs at least one bit."
    elif cat == "c":
        text = "The clock is not connected. Make sure your module has an input named clk and uses it."
    else:
        text = f"The compiler reported: {msg}" if msg else "The design did not compile."
    return {"line": line, "code": code, "explanation": text, "compiler_message": msg}


def warnings(result: GradeResult) -> list[str]:
    """Compiler warnings worth showing a beginner even when the design compiles."""
    out = []
    for m in re.finditer(r"TopModule\.sv:(\d+): warning: implicit definition of wire '([^']+)'", result.compile_log):
        out.append(f"Line {m.group(1)}: `{m.group(2)}` was never declared, so Verilog silently created a 1-bit wire. "
                   "If you meant an existing signal, check the spelling; if it should be wider, declare it.")
    return out


# ---------------------------------------------------------------- L1: counterexample

def fmt_value(value: str | None, width: int) -> str:
    if value is None:
        return "?"
    if any(c in value for c in "xz"):
        return f"{width}'b{value}" if width <= 8 else "unknown (x)"
    n = int(value, 2)
    if 1 < width <= 8:
        return f"{n} ({width}'b{value})"
    if width > 8 and n >= 256:  # hex shows sign bits and patterns that decimal hides
        return f"{n} ({width}'h{n:x})"
    return str(n)


def counterexample(result: GradeResult) -> dict | None:
    cx = result.counterexample
    if not cx:
        return None
    inputs = ", ".join(f"{k} = {fmt_value(v['value'], v['width'])}" for k, v in cx["inputs"].items())
    wrong = []
    for name in cx.get("mismatched_outputs", []):
        o = cx["outputs"][name]
        wrong.append(f"`{name}` should be {fmt_value(o.get('expected'), o['width'])} "
                     f"but your circuit gives {fmt_value(o.get('got'), o['width'])}")
    text = (f"With {inputs}: " if inputs else "At the first wrong sample: ") + "; ".join(wrong) + "."
    return {"text": text, "time": cx["time"], "inputs": cx["inputs"], "outputs": cx["outputs"],
            "mismatched_outputs": cx.get("mismatched_outputs", [])}


# ---------------------------------------------------------------- L2: locate lines

def _statements(code: str) -> list[tuple[int, int, str]]:
    """(start, end, text) of each statement in comment-free code."""
    out, start = [], 0
    for m in re.finditer(r";|\bbegin\b|\bend\b", code):
        out.append((start, m.end(), code[start:m.end()]))
        start = m.end()
    return out


def _identifiers(text: str) -> set[str]:
    text = re.sub(r"\d+'[bdhoBDHO][0-9a-fA-FxXzZ_]+", " ", text)
    return {w for w in re.findall(r"\b[A-Za-z_]\w*\b", text)} - _KEYWORDS


def _drives(stmt: str, signal: str) -> bool:
    s = stmt.strip()
    if re.match(rf"assign\s+(\{{[^}}]*\b{signal}\b[^}}]*\}}|{signal}\b)", s):
        return True
    if re.search(rf"(^|[\s;)])({signal})\s*(\[[^\]]*\])?\s*(<=|=)(?!=)", s) and not s.startswith(("input", "output")):
        return True
    if re.search(rf"\b(wire|reg|logic)\b[^;=]*\b{signal}\b\s*=", s):
        return True
    # instance output connection: .port(signal) where the module drives it; cannot tell
    # direction without the module, so any instance mentioning the signal counts
    if re.match(r"[A-Za-z_]\w*\s+(#\s*\(.*?\)\s*)?[A-Za-z_]\w*\s*\(", s) and re.search(rf"\b{signal}\b", s) \
            and not s.startswith(("assign", "wire", "reg", "logic", "input", "output", "module")):
        return True
    return False


def locate(src: str, outputs: list[str], *, hops: int = 2) -> list[dict]:
    """Lines that drive the given outputs, then the lines driving the wires they read."""
    code = safety.strip_comments_and_strings(src)
    stmts = _statements(code)
    ports = set()
    if m := re.search(r"\bmodule\s+\w+\s*\((.*?)\)\s*;", code, re.S):
        ports = _identifiers(m.group(1))
    found, frontier, seen = [], list(outputs), set(outputs)
    for depth in range(hops + 1):
        nxt = []
        for sig in frontier:
            for start, end, text in stmts:
                if _drives(text, sig):
                    line = code.count("\n", 0, start + len(text) - len(text.lstrip())) + 1
                    if not any(f["line"] == line for f in found):
                        found.append({"line": line, "code": src[start:end].strip(), "signal": sig,
                                      "why": "drives" if depth == 0 else f"feeds a signal that reaches {', '.join(outputs)}"})
                    for ident in _identifiers(text) - ports - seen:
                        if ident != sig and re.search(rf"\b(wire|reg|logic)\b[^;]*\b{ident}\b", code):
                            seen.add(ident)
                            nxt.append(ident)
        frontier = nxt
        if not frontier:
            break
    return found


# ---------------------------------------------------------------- L0 / L3

def concept_hint(slug: str) -> list[dict]:
    return [{"concept": c, **_CONCEPTS[c]} for c in _PROBLEM_CONCEPTS.get(slug, []) if c in _CONCEPTS]


def structure_hint(problem_dir: Path) -> str | None:
    meta = problem_dir / "problem.json"
    if meta.is_file():
        return (json.loads(meta.read_text()).get("hints") or {}).get("L3")
    return None


# ---------------------------------------------------------------- facade

def feedback(slug: str, problem_dir: Path, src: str, result: GradeResult) -> dict:
    """Everything the rule layer can say about one submission."""
    given = []
    if (problem_dir / "given.sv").is_file():
        given = re.findall(r"\bmodule\s+(\w+)", (problem_dir / "given.sv").read_text())
    mismatched = [o.name for o in result.outputs if o.mismatches]
    return {
        "status": result.status,
        "summary": _summary(result),
        "compile": explain_compile(result, src, given),
        "warnings": warnings(result),
        "hints": {
            "L0": concept_hint(slug),
            "L1": counterexample(result),
            "L2": locate(src, mismatched) if mismatched else [],
            "L3": structure_hint(problem_dir),
        },
    }


def _summary(result: GradeResult) -> str:
    if result.status == "pass":
        return f"All {result.samples} samples match. Well done."
    if result.status == "mismatch":
        bad = ", ".join(f"`{o.name}` ({o.mismatches} wrong)" for o in result.outputs if o.mismatches)
        return f"{result.mismatches} of {result.samples} samples are wrong: {bad}."
    if result.status == "structure":
        return "Outputs match, but the required module instances are missing."
    if result.status == "timeout":
        return "The simulation did not finish."
    if result.status == "rejected":
        return "This code was not run."
    return "The design did not compile."

"""Coach, model layer: one hint written by Nemotron, grounded in the simulator's facts.

The model sees the problem, the learner's numbered code, what the simulator
found (status, first wrong sample, compile error), the candidate lines from the
rule layer and a hidden reference solution. It writes one hint at the requested
level and names the line it thinks is the root cause.

Every hint passes the leak check before it is returned. A leaking hint is sent
back once with the reason; if it leaks again, or the model fails, the learner
gets the rule layer's hint for that level instead.
"""

import json
import re
import time
from pathlib import Path

from . import coach, leak
from .grader import GradeResult

DEFAULT_MODEL = "ultra"  # fastest and correct in our spot check with reasoning on; see README
MAX_HINT_CHARS = 700
MAX_TOKENS = 4096  # reasoning tokens count against this; 2048 cut some replies off
LANGS = {"en": "English", "zh-TW": "Traditional Chinese as used in Taiwan"}

SYSTEM = """You are a patient Verilog tutor for complete beginners working through HDLBits-style problems.
You receive the problem, the learner's code with line numbers, facts from a simulator, candidate
lines found by a program, and a hidden reference solution. The simulator facts are ground truth:
use their numbers and never invent other values.

Write ONE hint at the requested level:
  L0: name the idea the learner should revisit. No line numbers, no fix.
  L1: trace the first wrong sample through the circuit with the simulator's numbers, showing where
      the value first goes wrong. Do not name the cause (operator, width rule, line). No fix.
  L2: point to the line that causes the problem and explain what that line actually does. No fix.
  L3: describe in words what to change. Still no code.

Never show the reference solution, never write corrected code, and never write the corrected
expression, even partially. At most three short sentences. Reply with one JSON object:
{"root_cause_line": <line number or null>, "hint": "<the hint>"}"""


def _numbered(src: str, limit: int = 120) -> str:
    lines = src.splitlines()[:limit]
    return "\n".join(f"{i:3d}| {l}" for i, l in enumerate(lines, 1))


def solution_source(problem_dir: Path) -> str:
    """What a correct learner would write: solution.sv for authored problems, else the reference."""
    if (problem_dir / "solution.sv").is_file():
        return (problem_dir / "solution.sv").read_text()
    return re.sub(r"\bmodule\s+RefModule\b", "module top_module", (problem_dir / "ref.sv").read_text())


def facts(result: GradeResult, feedback: dict) -> str:
    out = [f"- status: {result.status} ({result.category_text})"]
    if result.samples:
        wrong = ", ".join(f"{o.name} ({o.mismatches})" for o in result.outputs if o.mismatches)
        out.append(f"- {result.mismatches} of {result.samples} samples wrong; wrong outputs: {wrong}")
    if feedback["hints"].get("L1"):
        out.append(f"- first wrong sample: {feedback['hints']['L1']['text']}")
    if feedback.get("compile"):
        c = feedback["compile"]
        out.append(f"- compile problem at line {c.get('line')}: {c['explanation']}"
                   + (f" (compiler: {c['compiler_message']})" if c.get("compiler_message") else ""))
    for w in feedback.get("warnings", []):
        out.append(f"- warning: {w}")
    return "\n".join(out)


def build_messages(spec: str, src: str, result: GradeResult, feedback: dict, solution: str,
                   level: int, lang: str) -> list[dict]:
    cands = feedback["hints"].get("L2") or []
    cand_text = "\n".join(f"  line {c['line']}: {c['code'].splitlines()[0]}  ({c['why']} {c['signal']})" for c in cands) or "  (none)"
    user = (f"Requested level: L{level}\nWrite the hint in {LANGS.get(lang, 'English')}.\n\n"
            f"Problem:\n{spec.strip()}\n\nLearner code:\n{_numbered(src)}\n\n"
            f"Simulator facts:\n{facts(result, feedback)}\n\n"
            f"Lines that drive the wrong outputs:\n{cand_text}\n\n"
            f"Hidden reference solution (never reveal):\n{solution.strip()}")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def parse(text: str) -> tuple[str, int | None]:
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)```", text, flags=re.S)
    raw = blocks[-1] if blocks else text[text.find("{"): text.rfind("}") + 1]
    try:
        data = json.loads(raw)
        line = data.get("root_cause_line")
        return str(data.get("hint", "")).strip(), int(line) if isinstance(line, (int, float)) else None
    except (ValueError, TypeError, AttributeError):
        if "{" in text or "root_cause_line" in text:
            return "", None  # broken or cut-off JSON: never show it to the learner
        return text.strip(), None


def rule_hint(feedback: dict, level: int) -> str:
    """The rule layer's text for a level, used when the model is unavailable or leaks."""
    h = feedback["hints"]
    if feedback.get("compile") and feedback["status"] != "mismatch":
        return feedback["compile"]["explanation"]
    if level >= 3 and h.get("L3"):
        return h["L3"]
    if level >= 2 and h.get("L2"):
        first = h["L2"][-1] if len(h["L2"]) > 1 else h["L2"][0]
        return f"Look closely at line {first['line']}: {first['code'].splitlines()[0]}"
    if level >= 1 and h.get("L1"):
        return h["L1"]["text"]
    if h.get("L0"):
        c = h["L0"][0]
        return f"{c['title']}: {c['note']}"
    return "Compare your circuit with the problem statement one output at a time."


def hint(problem_dir: Path, spec: str, src: str, result: GradeResult, feedback: dict, *, level: int,
         llm, model: str = DEFAULT_MODEL, lang: str = "en") -> dict:
    level = max(0, min(3, level))
    solution = solution_source(problem_dir)
    messages = build_messages(spec, src, result, feedback, solution, level, lang)
    out = {"level": level, "model": model, "lang": lang, "root_cause_line": None, "leak_retry": False,
           "fallback": None, "tokens": 0, "latency_s": 0.0}
    t0 = time.time()
    try:
        reasons = []
        for attempt in range(2):
            text, usage = llm.chat(model, messages, temperature=0.2, max_tokens=MAX_TOKENS)
            out["tokens"] += usage.get("total_tokens") or 0
            text_hint, line = parse(text)
            text_hint = text_hint[:MAX_HINT_CHARS]
            if not text_hint:
                reasons.append("incomplete")
                ask = "Your reply was cut off or was not valid JSON. Reply again with only the JSON object."
            else:
                leaks, why = leak.check(text_hint, solution, src)
                if not leaks:
                    out.update(hint=text_hint, root_cause_line=line)
                    break
                reasons.append("leak")
                out["leak_retry"] = True
                ask = f"That hint gives the answer away ({why}). Rewrite it without any code or corrected expression."
            messages = messages + [{"role": "assistant", "content": text}, {"role": "user", "content": ask}]
        else:
            out.update(hint=rule_hint(feedback, level), fallback="leak" if "leak" in reasons else "error")
        out["retries"] = reasons
    except Exception as exc:  # network, rate limit, model errors: the learner still gets a hint
        out.update(hint=rule_hint(feedback, level), fallback="error", error=type(exc).__name__)
    out["latency_s"] = round(time.time() - t0, 2)
    return out

"""Authoring agent: turn a one-line outline into a verified problem.

The model writes the problem text, the provided submodules, a behavioural
reference, a learner-style solution, directed test vectors and hints. Everything
else is checked by tools, and failures go back to the model as feedback:

  1. ports of the reference and the solution match the outline exactly
  2. the testbench is generated from the interface (tbgen), not written by the model
  3. the learner-style solution passes against the reference, using the required submodules
  4. every beginner-style mutant of the solution is caught, or proven equivalent by Yosys

A problem that passes is written to problems/<slug>/ with review: "pending"
until a person has read it.
"""

import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import grader, mutate, ports, tbgen

DEFAULT_MODEL = "ultra"
RANDOM_SAMPLES = 300
MAX_SURVIVORS_SHOWN = 6

SYSTEM = """You write Verilog practice problems for complete beginners and verify nothing yourself:
your output is checked by a simulator and by mutation testing, and any failure comes back to you.

Reply with ONE JSON object in a ```json code block and nothing else. Keys:
  "spec": plain-English problem statement, 50-150 words. Say what top_module must do and what
          each provided module does. Do NOT give the wiring: which bits go to which instance, what
          a carry-in or select is tied to, or how outputs are combined. Working that out is the
          exercise; the hints reveal it step by step. Never include code.
  "given_sv": Verilog source of every provided module, or "" if none.
  "ref_sv": "module RefModule(...)" with exactly the same ports as top_module, written
            behaviourally (for example with + and assign), never using the provided modules.
  "solution_sv": what a good learner submits: "module top_module(...)" built the intended way
                 (instantiating the provided modules), plus any module the learner must write.
  "directed": list of input assignments as integers, e.g. [{"a": 5, "b": 3}]. Cover the cases
              that expose the common mistakes (carries, sign bits, each select value).
  "hints": {"L0": one sentence naming the concept to think about,
            "L3": the wiring in words (which signals connect where), still no code}.
  "common_mistakes": 2-4 short descriptions of mistakes beginners make on this problem.

Rules: Verilog-2005 (logic is allowed). No system tasks ($display etc.), no `include, no initial
blocks in ref_sv or solution_sv. Clocked logic uses posedge clk. Port names and widths must match
the given top_module header exactly. Declare ports ANSI-style in every module header, e.g.
"module RefModule(input [31:0] a, output [31:0] sum);". The spec is read by the learner only:
no notes about testing, mutation or how the provided module was chosen."""


@dataclass
class Round:
    n: int
    ok: bool
    problems: list[str]
    usage: dict
    mutation: dict | None = None


@dataclass
class AuthoringResult:
    slug: str
    ok: bool
    rounds: list[Round] = field(default_factory=list)
    survivors: list[str] = field(default_factory=list)
    out_dir: str | None = None


def first_prompt(slug: str, outline: dict) -> str:
    lines = [f"Problem id: {slug}", f"Outline: {outline['outline']}", f"top_module header: {outline['top']};"]
    if outline.get("given"):
        lines.append(f"Provided module(s): {outline['given']}")
    if outline.get("given_behaviour_hint"):
        lines.append(f"Provided module behaviour: {outline['given_behaviour_hint']}")
    if outline.get("learner_writes"):
        lines.append(f"The learner also writes: {outline['learner_writes']}")
    if outline.get("require_instances"):
        req = ", ".join(f"{n} x {m}" for m, n in outline["require_instances"].items())
        lines.append(f"The solution must instantiate: {req}")
    if outline.get("directed_hint"):
        lines.append(f"Directed vectors: {outline['directed_hint']}")
    if outline.get("clocked"):
        lines.append("This problem is clocked: clk is driven by the testbench.")
    return "\n".join(lines)


def parse_reply(text: str) -> dict:
    m = re.findall(r"```(?:json)?\s*\n(.*?)```", text, flags=re.S)
    raw = m[-1] if m else text[text.find("{"): text.rfind("}") + 1]
    data = json.loads(raw)
    missing = [k for k in ("spec", "given_sv", "ref_sv", "solution_sv", "directed", "hints", "common_mistakes") if k not in data]
    if missing:
        raise ValueError(f"missing keys: {missing}")
    return data


def _static_checks(data: dict, outline: dict, top_ports: list[dict]) -> list[str]:
    problems = []
    try:
        _, ref_ports = ports.parse_header(data["ref_sv"], "RefModule")
        if ref_ports != top_ports:
            problems.append(f"RefModule ports {ref_ports} differ from top_module ports {top_ports}.")
    except ValueError as exc:
        problems.append(f"ref_sv: {exc}")
    try:
        _, sol_ports = ports.parse_header(data["solution_sv"], "top_module")
        if sol_ports != top_ports:
            problems.append(f"solution_sv top_module ports {sol_ports} differ from {top_ports}.")
    except ValueError as exc:
        problems.append(f"solution_sv: {exc}")
    for module in outline.get("require_instances", {}):
        if module not in ports.module_names(data["given_sv"]):
            problems.append(f"given_sv must define module {module}.")
    if re.search(r"\$\w+|`include|\binitial\b", data["ref_sv"] + data["solution_sv"]):
        problems.append("ref_sv and solution_sv must not use system tasks, `include or initial blocks.")
    inputs = {p["name"] for p in top_ports if p["dir"] == "input"} - ({"clk"} if outline.get("clocked") else set())
    for vec in data["directed"]:
        if not isinstance(vec, dict) or set(vec) - inputs or not all(isinstance(v, int) and v >= 0 for v in vec.values()):
            problems.append(f"directed vector {vec} must map input names {sorted(inputs)} to non-negative integers.")
            break
    return problems


def _write_problem(work: Path, slug: str, data: dict, outline: dict, top_ports: list[dict]) -> dict:
    clocked = bool(outline.get("clocked"))
    spec = {
        "slug": slug,
        "interface": ports.interface(top_ports, clocked),
        "directed": data["directed"],
        "random_samples": RANDOM_SAMPLES,
        "require_instances": outline.get("require_instances", {}),
        "hints": data["hints"],
        "common_mistakes": data["common_mistakes"],
        "top": outline["top"],
        "learner_writes": outline.get("learner_writes"),
        "review": "pending",
    }
    (work / "prompt.txt").write_text(data["spec"].strip() + "\n")
    if data["given_sv"].strip():
        (work / "given.sv").write_text(data["given_sv"].strip() + "\n")
    (work / "ref.sv").write_text(data["ref_sv"].strip() + "\n")
    (work / "solution.sv").write_text(data["solution_sv"].strip() + "\n")
    (work / "test.sv").write_text(tbgen.generate(spec))
    (work / "problem.json").write_text(json.dumps(spec, indent=2) + "\n")
    return spec


def _feedback(problems: list[str]) -> str:
    return ("Your problem failed these checks. Fix them and reply with the complete JSON object again.\n- "
            + "\n- ".join(problems))


def author(slug: str, outline: dict, llm, *, out_root: Path, model: str = DEFAULT_MODEL,
           max_rounds: int = 4, overwrite: bool = False, log=print) -> AuthoringResult:
    out_dir = Path(out_root) / slug
    if out_dir.exists() and not overwrite:
        raise FileExistsError(f"{out_dir} exists; pass overwrite=True to replace it")
    _, top_ports = ports.parse_header(outline["top"] + ";", "top_module")
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": first_prompt(slug, outline)}]
    result = AuthoringResult(slug, False)

    with tempfile.TemporaryDirectory(prefix=f"w2a-author-{slug}-") as tmp:
        work = Path(tmp)
        for n in range(1, max_rounds + 1):
            text, usage = llm.chat(model, messages, temperature=0.2, max_tokens=8192)
            messages.append({"role": "assistant", "content": text})
            problems, mut = [], None
            try:
                data = parse_reply(text)
            except (ValueError, json.JSONDecodeError) as exc:
                problems = [f"Reply was not the required JSON object ({exc})."]
                data = None
            if data is not None:
                problems = _static_checks(data, outline, top_ports)
            if data is not None and not problems:
                for f in work.iterdir():
                    f.unlink()
                _write_problem(work, slug, data, outline, top_ports)
                res = grader.grade(work, data["solution_sv"])
                if not res.passed:
                    detail = res.category_text
                    if res.structure_issues:
                        detail += ": " + " ".join(res.structure_issues)
                    if res.counterexample:
                        detail += f"; first mismatch: {json.dumps(res.counterexample['inputs'])} " \
                                  f"outputs {json.dumps(res.counterexample['outputs'])}"
                    log_lines = [l for l in (res.compile_log + res.sim_log).splitlines() if "error" in l.lower()][:5]
                    problems.append(f"solution_sv does not pass against ref_sv ({detail}). {' '.join(log_lines)}")
                else:
                    results = mutate.evaluate(work, data["solution_sv"])
                    mut = mutate.score(results)
                    survivors = [r.mutant.description for r in results if r.status == "survived"]
                    result.survivors = survivors
                    if survivors:
                        problems.append(
                            "These buggy versions of solution_sv pass the testbench and are not equivalent to it. "
                            "Add directed vectors that expose them: " + "; ".join(survivors[:MAX_SURVIVORS_SHOWN]))
            ok = not problems
            result.rounds.append(Round(n, ok, problems, usage, mut))
            log(f"[{slug}] round {n}: {'OK' if ok else 'FAIL'}"
                + (f" mutation {mut}" if mut else "") + ("" if ok else " | " + " | ".join(p[:160] for p in problems)))
            if ok:
                if out_dir.exists():
                    shutil.rmtree(out_dir)
                shutil.copytree(work, out_dir)
                result.ok, result.out_dir = True, str(out_dir)
                break
            messages.append({"role": "user", "content": _feedback(problems)})

    log_path = (out_dir if result.ok else Path(out_root) / f"_failed_{slug}")
    log_path.mkdir(parents=True, exist_ok=True)
    (log_path / "authoring_log.json").write_text(json.dumps({
        "slug": slug, "ok": result.ok, "model": model, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rounds": [r.__dict__ for r in result.rounds], "survivors": result.survivors,
        "transcript": messages,
    }, indent=2) + "\n")
    return result

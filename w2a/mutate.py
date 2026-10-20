"""Beginner-style mutations of a working Verilog solution.

Each operator mimics a mistake learners make in the first 28 HDLBits problems
and is tagged with the curriculum concept it exercises. Mutants serve two jobs:
they prove a testbench is strong enough (every real bug must be caught), and
they form the evaluation set of buggy submissions for the coach.
"""

import re
from dataclasses import dataclass

from pathlib import Path

from . import equiv, grader, safety

MAX_PER_OPERATOR = 4
_DECL_KW = re.compile(r"\b(input|output|inout|wire|reg|logic|integer|genvar|parameter|localparam)\b")
_NOT_INSTANCE = {"module", "assign", "always", "always_comb", "always_ff", "if", "else", "case", "casez",
                 "for", "begin", "end", "function", "task", "initial", "generate", "wire", "reg", "logic",
                 "input", "output", "inout", "genvar", "integer", "while", "repeat"}


@dataclass
class Mutant:
    op: str
    concept: str
    line: int
    before: str
    after: str
    src: str

    @property
    def description(self) -> str:
        return f"line {self.line}: {self.before.strip()!r} -> {self.after.strip()!r}"


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _match_close(code: str, open_idx: int) -> int:
    """Index of the bracket closing the one at open_idx, or -1."""
    pairs = {"(": ")", "{": "}", "[": "]"}
    want, depth = pairs[code[open_idx]], 0
    for i in range(open_idx, len(code)):
        if code[i] == code[open_idx]:
            depth += 1
        elif code[i] == want:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_top(code: str, start: int, end: int) -> list[tuple[int, int]]:
    """Spans of the comma-separated items in code[start:end], ignoring nested brackets."""
    spans, depth, s = [], 0, start
    for i in range(start, end):
        c = code[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            spans.append((s, i))
            s = i + 1
    spans.append((s, end))
    return [(a, b) for a, b in spans if code[a:b].strip()]


def _in_declaration(code: str, pos: int) -> bool:
    start = max(code.rfind(";", 0, pos), code.rfind("(", 0, pos), code.rfind(",", 0, pos)) + 1
    seg = code[start:pos]
    return bool(_DECL_KW.search(seg)) and "=" not in seg


class _Builder:
    def __init__(self, src: str):
        self.src = src
        self.code = safety.strip_comments_and_strings(src)
        self.out: list[Mutant] = []
        self.count: dict[str, int] = {}

    def add(self, op: str, concept: str, start: int, end: int, replacement: str) -> None:
        if self.count.get(op, 0) >= MAX_PER_OPERATOR:
            return
        before = self.src[start:end]
        if before == replacement:
            return
        new_src = self.src[:start] + replacement + self.src[end:]
        if any(m.src == new_src for m in self.out):
            return
        self.count[op] = self.count.get(op, 0) + 1
        self.out.append(Mutant(op, concept, _line(self.src, start), before, replacement, new_src))


def mutants(src: str) -> list[Mutant]:
    b = _Builder(src)
    code = b.code

    # Bitwise operators: & <-> |, bitwise -> logical, dropped inversion, XOR <-> XNOR.
    for m in re.finditer(r"(?<![&|^~!=<>])&(?![&=])", code):
        b.add("and_to_or", "bitwise_ops", m.start(), m.end(), "|")
        b.add("bitwise_to_logical", "bitwise_vs_logical", m.start(), m.end(), "&&")
    for m in re.finditer(r"(?<![&|^~!=<>])\|(?![|=])", code):
        b.add("or_to_and", "bitwise_ops", m.start(), m.end(), "&")
        b.add("bitwise_to_logical", "bitwise_vs_logical", m.start(), m.end(), "||")
    for m in re.finditer(r"~(?=\s*[\w(\[{])", code):
        b.add("drop_not", "bitwise_ops", m.start(), m.end(), "")
    for m in re.finditer(r"~\^|\^~", code):
        b.add("xnor_to_xor", "bitwise_ops", m.start(), m.end(), "^")
    for m in re.finditer(r"(?<![~])\^(?!~)", code):
        b.add("xor_to_xnor", "bitwise_ops", m.start(), m.end(), "~^")

    # Replication {n{x}}: drop it (the b ^ sub bug) or zero-fill instead of sign-extending.
    for m in re.finditer(r"\{\s*([\w']+)\s*\{", code):
        inner_open = m.end() - 1
        inner_close = _match_close(code, inner_open)
        outer_close = _match_close(code, m.start())
        if inner_close < 0 or outer_close < 0 or code[inner_close + 1:outer_close].strip():
            continue
        inner = src[inner_open + 1:inner_close].strip()
        b.add("drop_replication", "replication", m.start(), outer_close + 1, inner)
        count = m.group(1)
        if count.isdigit() and re.fullmatch(r"\w+\s*\[\s*\d+\s*\]", inner):
            b.add("zero_extend", "sign_extend", m.start(), outer_close + 1, f"{count}'b0")

    # Concatenation order: swap the first two items of {a, b, ...}.
    for m in re.finditer(r"\{", code):
        if re.match(r"\{\s*[\w']+\s*\{", code[m.start():]) or code[m.start() - 1:m.start()] == "{":
            continue  # replication, handled above
        close = _match_close(code, m.start())
        if close < 0:
            continue
        items = _split_top(code, m.start() + 1, close)
        if len(items) >= 2:
            (a0, a1), (b0, b1) = items[0], items[1]
            first, second = src[a0:a1], src[b0:b1]
            if first.strip() != second.strip():
                swapped = src[m.start():a0] + second.strip() + src[a1:b0] + " " + first.strip() + src[b1:close + 1]
                b.add("concat_swap", "concat", m.start(), close + 1, swapped)

    # Bit and part selects in expressions: off by one.
    for m in re.finditer(r"(?<=\w)\s*\[\s*(\d+)\s*\]", code):
        if _in_declaration(code, m.start()):
            continue
        k = int(m.group(1))
        b.add("index_off_by_one", "part_select", m.start(), m.end(), f"[{k - 1 if k > 0 else k + 1}]")
    for m in re.finditer(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", code):
        hi, lo = int(m.group(1)), int(m.group(2))
        if _in_declaration(code, m.start()):
            # Declaring [0:7] instead of [7:0] flips the bit order.
            if hi != lo:
                b.add("reverse_declared_range", "vector_decl", m.start(), m.end(), f"[{lo}:{hi}]")
        elif hi > lo:
            shifted = f"[{hi - 1}:{lo - 1}]" if lo > 0 else f"[{hi + 1}:{lo + 1}]"
            b.add("range_off_by_one", "part_select", m.start(), m.end(), shifted)

    # Module instances: swapped connections, carry-in tied to 0.
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s+(?:#\s*\([^;]*?\)\s*)?([A-Za-z_]\w*)\s*\(", code):
        if m.group(1) in _NOT_INSTANCE or m.group(2) in _NOT_INSTANCE:
            continue
        open_idx = m.end() - 1
        close = _match_close(code, open_idx)
        if close < 0 or not code[close + 1:].lstrip().startswith(";"):
            continue
        args = _split_top(code, open_idx + 1, close)
        named = [re.match(r"\s*\.\s*(\w+)\s*\((.*)\)\s*$", code[a:z], re.S) for a, z in args]
        if all(named) and len(args) >= 2:
            for (a0, a1), (b0, b1), na, nb in zip(args, args[1:], named, named[1:]):
                ea, eb = src[a0:a1][na.start(2):na.end(2)], src[b0:b1][nb.start(2):nb.end(2)]
                if ea.strip() and eb.strip() and ea.strip() != eb.strip():
                    new = f".{na.group(1)}({eb.strip()}), .{nb.group(1)}({ea.strip()})"
                    b.add("swap_named_ports", "port_by_name", a0, b1, new)
            for (a0, a1), na in zip(args, named):
                if na.group(1) == "cin" and not re.fullmatch(r"\s*1'b0\s*", na.group(2)):
                    b.add("carry_in_zero", "carry_chain", a0, a1, f".cin(1'b0)")
        elif not any(named) and len(args) >= 2:
            (a0, a1), (b0, b1) = args[0], args[1]
            if src[a0:a1].strip() != src[b0:b1].strip():
                b.add("swap_positional_ports", "port_by_position", a0, b1,
                      f"{src[b0:b1].strip()}, {src[a0:a1].strip()}")

    # Constants, mux arms, clocked assignments, dropped statements.
    for m in re.finditer(r"1'b([01])", code):
        b.add("flip_constant", "assign", m.start(), m.end(), "1'b" + ("1" if m.group(1) == "0" else "0"))
    for m in re.finditer(r"\?([^?:;]+):([^;]+);", code):
        x, y = m.group(1), m.group(2)
        if x.strip() != y.strip():
            b.add("swap_mux_arms", "mux", m.start(), m.end(), f"? {y.strip()} : {x.strip()};")
    for m in re.finditer(r"always\s*@\s*\(\s*posedge[^)]*\)", code):
        nxt = re.search(r"\balways\b|\bendmodule\b|\bassign\b", code[m.end():])
        end = m.end() + (nxt.start() if nxt else len(code) - m.end())
        block = src[m.end():end]
        if "<=" in code[m.end():end]:
            b.add("blocking_in_clocked", "chaining", m.end(), end, re.sub(r"<=", "=", block))
    for m in re.finditer(r"^[ \t]*assign\b[^;]*;[ \t]*\n?", code, re.M):
        b.add("drop_assign", "assign", m.start(), m.end(), "")

    return b.out


@dataclass
class MutantResult:
    mutant: Mutant
    status: str  # killed | stillborn | survived | equivalent
    detail: str = ""


def evaluate(problem_dir: str | Path, solution_src: str, candidates: list[Mutant] | None = None,
             *, check_equivalence: bool = True) -> list[MutantResult]:
    """Run every mutant through the grader.

    killed      the testbench catches it (what we want)
    stillborn   it does not compile or is rejected, so it says nothing about the testbench
    equivalent  it passes, and Yosys proves it behaves like the solution
    survived    it passes and is not proven equivalent: the testbench may be too weak
    """
    problem_dir = Path(problem_dir)
    given = (problem_dir / "given.sv").read_text() if (problem_dir / "given.sv").is_file() else ""
    results = []
    for m in candidates if candidates is not None else mutants(solution_src):
        res = grader.grade(problem_dir, m.src)
        if res.status in ("compile_error", "rejected"):
            results.append(MutantResult(m, "stillborn", res.category_text))
        elif res.status != "pass":
            results.append(MutantResult(m, "killed", res.category_text))
        else:
            same = equiv.equivalent(solution_src, m.src, given) if check_equivalence else None
            results.append(MutantResult(m, "equivalent" if same else "survived",
                                        "proven equivalent" if same else "not proven equivalent"))
    return results


def score(results: list[MutantResult]) -> dict:
    counts = {k: sum(r.status == k for r in results) for k in ("killed", "survived", "equivalent", "stillborn")}
    judged = counts["killed"] + counts["survived"]
    counts["kill_rate"] = round(counts["killed"] / judged, 3) if judged else None
    return counts

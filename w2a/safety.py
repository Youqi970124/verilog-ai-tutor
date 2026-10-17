"""Static checks on learner code before it is compiled and simulated.

Learner code runs on our server, so anything that could touch the file system
or tamper with the testbench is rejected up front. None of the 28 curriculum
problems needs these constructs.
"""

import re
from dataclasses import dataclass

MAX_SOURCE_BYTES = 20_000

# Names that belong to the testbench. Declaring or referencing them from
# learner code could hijack or bypass the comparison.
TESTBENCH_NAMES = ("tb", "stimulus_gen", "RefModule", "stim1", "good1", "top_module1", "stats1")
ALLOWED_DIRECTIVES = ("timescale", "default_nettype")


@dataclass
class SafetyResult:
    ok: bool
    code: str = ""
    message: str = ""
    line: int | None = None


def strip_comments_and_strings(src: str) -> str:
    """Blank out comments and string literals, keeping newlines so line numbers survive."""
    out = []
    i, n = 0, len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j == -1 else j
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j]))
            i = j
        elif src[i] == '"':
            j = i + 1
            while j < n and src[j] != '"' and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(" " * (j - i))
            i = j
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def check(src: str) -> SafetyResult:
    if len(src.encode("utf-8")) > MAX_SOURCE_BYTES:
        return SafetyResult(False, "too_large", f"Source is larger than {MAX_SOURCE_BYTES} bytes.")

    code = strip_comments_and_strings(src)

    m = re.search(r"\$[A-Za-z_]\w*", code)
    if m:
        return SafetyResult(
            False, "system_task",
            f"System tasks such as {m.group(0)} are not needed for these problems and are disabled here.",
            _line_of(code, m.start()),
        )

    for m in re.finditer(r"`\s*([A-Za-z_]\w*)", code):
        if m.group(1) not in ALLOWED_DIRECTIVES:
            return SafetyResult(
                False, "directive",
                f"Compiler directive `{m.group(1)} is disabled here. Only `timescale and `default_nettype are allowed.",
                _line_of(code, m.start()),
            )

    m = re.search(r"\b(force|release)\b", code)
    if m:
        return SafetyResult(
            False, "force",
            f"'{m.group(1)}' is a simulation-only construct and is disabled here.",
            _line_of(code, m.start()),
        )

    names = "|".join(TESTBENCH_NAMES)
    m = re.search(rf"\bmodule\s+({names})\b", code)
    if m:
        return SafetyResult(
            False, "reserved_module",
            f"The module name '{m.group(1)}' is used by the testbench. Name your module top_module.",
            _line_of(code, m.start()),
        )
    m = re.search(rf"\b({names})\s*\.", code)
    if m:
        return SafetyResult(
            False, "hierarchical_ref",
            f"Your design refers to the testbench ('{m.group(1)}.'). A design may only use its own ports and signals.",
            _line_of(code, m.start()),
        )

    if not re.search(r"\bmodule\s+(top_module|TopModule)\b", code):
        return SafetyResult(False, "no_top", "Could not find 'module top_module'. Keep the module name from the problem.")

    return SafetyResult(True)

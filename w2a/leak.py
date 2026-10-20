"""Does a hint give away the answer?

Rule check run on every model-written hint before the learner sees it. The
statements of the reference solution that the learner's code is missing are
the answer; a hint leaks if it contains one of them, or the whole right-hand
side of one. Naming an operator (`{32{sub}}`) is allowed; writing the fixed
line (`b ^ {32{sub}}`) is not.
"""

import re

from . import safety

MIN_LEN = 6        # ignore fragments shorter than this (normalised)
COVERAGE = 0.6     # a fragment covering this much of a missing statement leaks


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _statements(src: str) -> list[str]:
    code = safety.strip_comments_and_strings(src)
    code = re.sub(r"\bmodule\b.*?\);", "", code, count=1, flags=re.S)  # the header is given to everyone
    return [s.strip() for s in re.split(r";|\bbegin\b|\bend\b|\bendmodule\b", code) if s.strip()]


def missing_statements(solution_src: str, learner_src: str) -> list[str]:
    learner = _norm(safety.strip_comments_and_strings(learner_src))
    return [s for s in _statements(solution_src) if _norm(s) not in learner]


def _fragments(hint: str) -> list[str]:
    frags = re.findall(r"`([^`]+)`", hint)
    frags += re.findall(r"```(?:\w+)?\n(.*?)```", hint, flags=re.S)
    frags += [l for l in hint.splitlines() if re.search(r";\s*$|\bassign\b|\balways\b|<=", l)]
    return [f for f in frags if len(_norm(f)) >= MIN_LEN]


def check(hint: str, solution_src: str, learner_src: str) -> tuple[bool, str]:
    """(leaks, reason)."""
    if len(re.findall(r"```", hint)) >= 2 and len(re.findall(r";", hint)) >= 2:
        return True, "hint contains a code block with several statements"
    missing = missing_statements(solution_src, learner_src)
    for frag in _fragments(hint):
        f = _norm(frag)
        for stmt in missing:
            s = _norm(stmt)
            rhs = _norm(stmt.split("=", 1)[1]) if "=" in stmt else ""
            if s in f:
                return True, f"hint contains the missing statement `{stmt}`"
            if rhs and len(rhs) >= MIN_LEN and rhs in f:
                return True, f"hint contains the right-hand side of `{stmt}`"
            if f in s and len(f) / len(s) >= COVERAGE:
                return True, f"hint covers most of `{stmt}`"
    return False, ""

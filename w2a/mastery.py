"""Learner progress: solved problems, mastered concepts, unlocked stages.

Stateless: the browser keeps the progress object and sends it back, so the
server stores nothing about learners.

A concept is mastered when the learner solves a problem that uses it within two
attempts and without hints beyond L1 (the counterexample). A stage unlocks when
every problem in the previous stage is solved.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRICULUM = json.loads((ROOT / "curriculum" / "curriculum.json").read_text())
MAX_ATTEMPTS_FOR_MASTERY = 2
MAX_HINT_FOR_MASTERY = 1


def empty() -> dict:
    return {"problems": {}, "concepts": {}}


def record(progress: dict, slug: str, *, passed: bool, hint_level: int = -1) -> dict:
    """Add one graded attempt. hint_level is the highest hint seen before it (-1 = none)."""
    p = progress.setdefault("problems", {}).setdefault(slug, {"attempts": 0, "max_hint": -1, "solved": False})
    if p["solved"]:
        return progress
    p["attempts"] += 1
    p["max_hint"] = max(p["max_hint"], hint_level)
    if passed:
        p["solved"] = True
        clean = p["attempts"] <= MAX_ATTEMPTS_FOR_MASTERY and p["max_hint"] <= MAX_HINT_FOR_MASTERY
        for c in _concepts(slug):
            entry = progress.setdefault("concepts", {}).setdefault(c, {"mastered": False, "solved_with_help": []})
            if clean:
                entry["mastered"] = True
            elif slug not in entry["solved_with_help"]:
                entry["solved_with_help"].append(slug)
    return progress


def view(progress: dict) -> dict:
    """Curriculum annotated with what is solved and what is open."""
    stages, prev_done = [], True
    probs = progress.get("problems", {})
    for stage in CURRICULUM["stages"]:
        items = [{"slug": p["slug"], "title": p["title"], "solved": probs.get(p["slug"], {}).get("solved", False),
                  "attempts": probs.get(p["slug"], {}).get("attempts", 0)} for p in stage["problems"]]
        done = all(i["solved"] for i in items)
        stages.append({"id": stage["id"], "title": stage["title"], "unlocked": prev_done, "done": done, "problems": items})
        prev_done = prev_done and done
    concepts = progress.get("concepts", {})
    review = sorted(c for c, v in concepts.items() if not v["mastered"])
    return {"stages": stages, "mastered": sorted(c for c, v in concepts.items() if v["mastered"]), "review": review}


def _concepts(slug: str) -> list[str]:
    for s in CURRICULUM["stages"]:
        for p in s["problems"]:
            if p["slug"] == slug:
                return p["concepts"]
    return []

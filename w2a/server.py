"""Web API and static site.

Run locally:
    uvicorn w2a.server:app --reload
"""

import json
import re
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import coach, grader, mastery, ports

ROOT = Path(__file__).resolve().parent.parent
PROBLEMS = ROOT / "problems"
WEB = ROOT / "web"
CURRICULUM = json.loads((ROOT / "curriculum" / "curriculum.json").read_text())
CONCEPTS = json.loads((ROOT / "curriculum" / "concepts.json").read_text())["concepts"]
GRADES_PER_MINUTE = 30

app = FastAPI(title="Wire-to-Adder")


# ---------------------------------------------------------------- helpers

def _problem_meta(slug: str) -> tuple[dict, dict]:
    for stage in CURRICULUM["stages"]:
        for p in stage["problems"]:
            if p["slug"] == slug:
                return stage, p
    raise HTTPException(404, f"Unknown problem {slug}")


def _available(slug: str) -> bool:
    d = PROBLEMS / slug
    return (d / "test.sv").is_file() and (d / "ref.sv").is_file()


def _template(slug: str) -> str:
    d = PROBLEMS / slug
    meta = json.loads((d / "problem.json").read_text()) if (d / "problem.json").is_file() else {}
    _, ps = ports.parse_header(meta["top"] + ";" if meta.get("top") else (d / "ref.sv").read_text(),
                               "top_module" if meta.get("top") else "RefModule")
    decls = []
    for p in ps:
        rng = f"[{p['width'] - 1}:0] " if p["width"] > 1 else ""
        decls.append(f"  {p['dir']} {rng}{p['name']}")
    body = "module top_module (\n" + ",\n".join(decls) + "\n);\n\n  // Write your circuit here.\n\nendmodule\n"
    if meta.get("learner_writes"):
        body = f"{meta['learner_writes']};\n\n  // Write this module too.\n\nendmodule\n\n" + body
    return body


def _spec(slug: str) -> str:
    text = (PROBLEMS / slug / "prompt.txt").read_text().strip()
    return re.sub(r"\bTopModule\b", "top_module", text)


def _given_interfaces(slug: str) -> list[str]:
    """Headers of the provided modules; their insides stay hidden, as on HDLBits."""
    path = PROBLEMS / slug / "given.sv"
    if not path.is_file():
        return []
    code = path.read_text()
    return [re.sub(r"\s+", " ", m.group(0)).strip() for m in re.finditer(r"\bmodule\s+\w+\s*\(.*?\)\s*;", code, re.S)]


class _RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute, self.hits, self.lock = per_minute, {}, threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self.lock:
            recent = [t for t in self.hits.get(key, []) if now - t < 60]
            if len(recent) >= self.per_minute:
                self.hits[key] = recent
                return False
            recent.append(now)
            self.hits[key] = recent
            return True


_grade_limit = _RateLimiter(GRADES_PER_MINUTE)


# ---------------------------------------------------------------- API

@app.get("/api/curriculum")
def curriculum() -> dict:
    stages = []
    for s in CURRICULUM["stages"]:
        stages.append({"id": s["id"], "title": s["title"], "problems": [
            {"slug": p["slug"], "title": p["title"], "available": _available(p["slug"]), "concepts": p["concepts"]}
            for p in s["problems"]]})
    return {"name": CURRICULUM["name"], "stages": stages,
            "concepts": {k: {"title": v["title"]} for k, v in CONCEPTS.items()}}


@app.get("/api/problem/{slug}")
def problem(slug: str) -> dict:
    stage, p = _problem_meta(slug)
    base = {"slug": slug, "title": p["title"], "stage": {"id": stage["id"], "title": stage["title"]},
            "hdlbits_url": CURRICULUM["hdlbits_base_url"] + slug, "concepts": p["concepts"],
            "source": "VerilogEval (NVIDIA, MIT)" if p["verilogeval"] else "Wire-to-Adder authoring agent"}
    if not _available(slug):
        return {**base, "available": False}
    return {**base, "available": True, "spec": _spec(slug), "template": _template(slug),
            "given": _given_interfaces(slug)}


class GradeRequest(BaseModel):
    slug: str
    code: str = Field(max_length=20_000)


@app.post("/api/grade")
def grade(req: GradeRequest, request: Request) -> dict:
    _problem_meta(req.slug)
    if not _available(req.slug):
        raise HTTPException(409, "This problem is not ready yet.")
    client = request.client.host if request.client else "?"
    if not _grade_limit.allow(client):
        raise HTTPException(429, f"Too many submissions. Try again in a minute (limit {GRADES_PER_MINUTE} per minute).")
    pdir = PROBLEMS / req.slug
    res = grader.grade(pdir, req.code)
    return {
        "status": res.status,
        "category": res.category,
        "mismatches": res.mismatches,
        "samples": res.samples,
        "outputs": [o.__dict__ for o in res.outputs],
        "feedback": coach.feedback(req.slug, pdir, req.code, res),
        "waveform": res.history,
    }


class ProgressRequest(BaseModel):
    progress: dict = Field(default_factory=mastery.empty)
    slug: str | None = None
    passed: bool = False
    hint_level: int = -1


@app.post("/api/progress")
def progress(req: ProgressRequest) -> dict:
    prog = req.progress or mastery.empty()
    if req.slug:
        _problem_meta(req.slug)
        mastery.record(prog, req.slug, passed=req.passed, hint_level=req.hint_level)
    return {"progress": prog, "view": mastery.view(prog)}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


# ---------------------------------------------------------------- static site

if WEB.is_dir():
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

"""Web API and static site.

Run locally:
    uvicorn w2a.server:app --reload
"""

import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import coach, grader, llm, mastery, ports, tutor

ROOT = Path(__file__).resolve().parent.parent
PROBLEMS = ROOT / "problems"
WEB = ROOT / "web"
CURRICULUM = json.loads((ROOT / "curriculum" / "curriculum.json").read_text())
CONCEPTS = json.loads((ROOT / "curriculum" / "concepts.json").read_text())["concepts"]
GRADES_PER_MINUTE = 30
COACH_PER_MINUTE = int(os.environ.get("W2A_COACH_PER_MINUTE", "10"))
COACH_PER_DAY = int(os.environ.get("W2A_COACH_PER_DAY", "200"))       # about $0.6 a day at most with Ultra
COACH_MODEL = os.environ.get("W2A_COACH_MODEL", tutor.DEFAULT_MODEL)
COACH_CACHE_SIZE = 2000

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
_coach_limit = _RateLimiter(COACH_PER_MINUTE)


class _DailyBudget:
    def __init__(self, per_day: int):
        self.per_day, self.day, self.used, self.lock = per_day, None, 0, threading.Lock()

    def take(self) -> bool:
        with self.lock:
            today = time.strftime("%Y-%m-%d")
            if today != self.day:
                self.day, self.used = today, 0
            if self.used >= self.per_day:
                return False
            self.used += 1
            return True


_coach_budget = _DailyBudget(COACH_PER_DAY)
_coach_cache: "OrderedDict[str, dict]" = OrderedDict()
_coach_lock = threading.Lock()
_llm_client = None


def _client():
    """The Token Factory client, or None when no API key is configured."""
    global _llm_client
    if _llm_client is None and llm.api_key():
        _llm_client = llm.TokenFactory(timeout=45.0, max_retries=1)
    return _llm_client


def _normalise(code: str) -> str:
    return re.sub(r"\s+", " ", code).strip()


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


class CoachRequest(BaseModel):
    slug: str
    code: str = Field(max_length=20_000)
    level: int = Field(default=1, ge=0, le=3)
    lang: str = Field(default="en", pattern="^(en|zh-TW)$")


@app.get("/api/coach/status")
def coach_status() -> dict:
    return {"enabled": _client() is not None, "model": llm.MODELS.get(COACH_MODEL, COACH_MODEL)}


@app.post("/api/coach")
def coach_hint(req: CoachRequest, request: Request) -> dict:
    _problem_meta(req.slug)
    if not _available(req.slug):
        raise HTTPException(409, "This problem is not ready yet.")
    client = _client()
    if client is None:
        raise HTTPException(503, "The AI coach is not configured on this server.")
    key = hashlib.sha256(f"{req.slug}|{req.level}|{req.lang}|{COACH_MODEL}|{_normalise(req.code)}".encode()).hexdigest()
    with _coach_lock:
        if key in _coach_cache:
            _coach_cache.move_to_end(key)
            return {**_coach_cache[key], "cached": True}
    ip = request.client.host if request.client else "?"
    if not _coach_limit.allow(ip):
        raise HTTPException(429, f"The coach answers at most {COACH_PER_MINUTE} questions per minute. Try again shortly.")
    pdir = PROBLEMS / req.slug
    res = grader.grade(pdir, req.code)
    if res.status == "pass":
        return {"hint": "Your circuit already matches the reference on every sample.", "level": req.level,
                "model": None, "fallback": None, "cached": False}
    fb = coach.feedback(req.slug, pdir, req.code, res)
    if not _coach_budget.take():
        return {**{"hint": tutor.rule_hint(fb, req.level), "level": req.level, "model": None,
                   "fallback": "daily_limit"}, "cached": False}
    out = tutor.hint(pdir, _spec(req.slug), req.code, res, fb, level=req.level, llm=client,
                     model=COACH_MODEL, lang=req.lang)
    out["model"] = llm.MODELS.get(out["model"], out["model"])
    if req.level < 2:
        out["root_cause_line"] = None  # pointing at a line is the L2 step
    if out.get("fallback") is None:
        with _coach_lock:
            _coach_cache[key] = out
            if len(_coach_cache) > COACH_CACHE_SIZE:
                _coach_cache.popitem(last=False)
    return {**out, "cached": False}


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

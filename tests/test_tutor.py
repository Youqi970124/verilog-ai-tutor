import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from w2a import coach, grader, llm, server, tutor

ROOT = Path(__file__).resolve().parent.parent
ADDSUB = ROOT / "problems" / "module_addsub"
pytestmark = pytest.mark.skipif(not (ADDSUB / "solution.sv").is_file(), reason="module_addsub not authored")


def demo_bug() -> str:
    return (ADDSUB / "solution.sv").read_text().replace("b ^ {32{sub}}", "b ^ sub")


def reply(hint: str, line=3) -> str:
    return "```json\n" + json.dumps({"root_cause_line": line, "hint": hint}) + "\n```"


def graded(src):
    res = grader.grade(ADDSUB, src)
    return res, coach.feedback("module_addsub", ADDSUB, src, res)


def test_prompt_carries_simulator_facts_and_hidden_solution():
    src = demo_bug()
    res, fb = graded(src)
    msgs = tutor.build_messages("spec", src, res, fb, tutor.solution_source(ADDSUB), 2, "zh-TW")
    user = msgs[1]["content"]
    assert "Requested level: L2" in user and "Traditional Chinese" in user
    assert "`sum` should be 2 but your circuit gives 8" in user       # ground truth from the VCD
    assert "  3| " in user and "b ^ sub" in user                    # numbered learner code
    assert "never reveal" in user and "{32{sub}}" in user             # reference given to the model only


def test_good_hint_is_returned_with_line():
    src = demo_bug()
    res, fb = graded(src)
    fake = llm.Scripted([reply("On line 3, sub is one bit wide, so only bit 0 of b gets flipped.")])
    out = tutor.hint(ADDSUB, "spec", src, res, fb, level=2, llm=fake)
    assert out["fallback"] is None and out["root_cause_line"] == 3 and "bit 0" in out["hint"]


def test_leaking_hint_is_rewritten_once():
    src = demo_bug()
    res, fb = graded(src)
    fake = llm.Scripted([reply("Change line 3 to `b ^ {32{sub}}`."), reply("Make sub as wide as b before the XOR.")])
    out = tutor.hint(ADDSUB, "spec", src, res, fb, level=3, llm=fake)
    assert out["leak_retry"] and out["fallback"] is None
    assert "gives the answer away" in fake.calls[1][-1]["content"]
    assert "{32{sub}}" not in out["hint"]


def test_two_leaks_fall_back_to_rule_hint():
    src = demo_bug()
    res, fb = graded(src)
    fake = llm.Scripted([reply("Use `b ^ {32{sub}}`.")] * 2)
    out = tutor.hint(ADDSUB, "spec", src, res, fb, level=3, llm=fake)
    assert out["fallback"] == "leak" and out["hint"] == fb["hints"]["L3"]


def test_model_error_falls_back():
    src = demo_bug()
    res, fb = graded(src)
    out = tutor.hint(ADDSUB, "spec", src, res, fb, level=1, llm=llm.Scripted([]))
    assert out["fallback"] == "error" and "should be 2" in out["hint"]


def test_plain_text_reply_is_accepted():
    assert tutor.parse("Think about how wide sub is.") == ("Think about how wide sub is.", None)


# ------------------------------------------------------------------ endpoint

@pytest.fixture
def api(monkeypatch):
    fake = llm.Scripted([reply("sub is one bit, so only bit 0 of b is inverted.")] * 5)
    monkeypatch.setattr(server, "_client", lambda: fake)
    monkeypatch.setattr(server, "_coach_cache", server.OrderedDict())
    monkeypatch.setattr(server, "_coach_limit", server._RateLimiter(100))
    return TestClient(server.app), fake


def test_coach_endpoint_and_cache(api):
    client, fake = api
    body = {"slug": "module_addsub", "code": demo_bug(), "level": 2, "lang": "en"}
    first = client.post("/api/coach", json=body).json()
    assert first["root_cause_line"] == 3 and not first["cached"]
    assert first["model"].startswith("nvidia/")
    second = client.post("/api/coach", json=body).json()
    assert second["cached"] and len(fake.calls) == 1   # the repeat cost nothing


def test_coach_endpoint_hides_line_below_l2(api):
    client, _ = api
    r = client.post("/api/coach", json={"slug": "module_addsub", "code": demo_bug(), "level": 1}).json()
    assert r["root_cause_line"] is None


def test_coach_endpoint_daily_limit(api, monkeypatch):
    client, fake = api
    monkeypatch.setattr(server, "_coach_budget", server._DailyBudget(0))
    r = client.post("/api/coach", json={"slug": "module_addsub", "code": demo_bug(), "level": 1}).json()
    assert r["fallback"] == "daily_limit" and "should be 2" in r["hint"] and not fake.calls


def test_coach_disabled_without_key(monkeypatch):
    monkeypatch.setattr(server, "_client", lambda: None)
    client = TestClient(server.app)
    assert client.get("/api/coach/status").json()["enabled"] is False
    r = client.post("/api/coach", json={"slug": "module_addsub", "code": demo_bug(), "level": 1})
    assert r.status_code == 503


def test_coach_rejects_bad_language(api):
    client, _ = api
    r = client.post("/api/coach", json={"slug": "module_addsub", "code": demo_bug(), "level": 1, "lang": "fr"})
    assert r.status_code == 422


def test_cut_off_json_is_retried_not_shown():
    src = demo_bug()
    res, fb = graded(src)
    cut = '{"root_cause_line": 3, "hint": "When a=5, b=3 and sub=1, b_xor becomes'
    fake = llm.Scripted([cut, reply("b_xor is 2 here, but subtracting needs every bit of b flipped.")])
    out = tutor.hint(ADDSUB, "spec", src, res, fb, level=1, llm=fake)
    assert out["fallback"] is None and out["retries"] == ["incomplete"]
    assert "cut off" in fake.calls[1][-1]["content"] and "{" not in out["hint"]


def test_cut_off_twice_falls_back_as_error():
    src = demo_bug()
    res, fb = graded(src)
    out = tutor.hint(ADDSUB, "spec", src, res, fb, level=1, llm=llm.Scripted(['{"hint": "half'] * 2))
    assert out["fallback"] == "error" and "should be 2" in out["hint"]

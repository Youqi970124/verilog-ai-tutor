import re
from pathlib import Path

from fastapi.testclient import TestClient

from w2a import server

ROOT = Path(__file__).resolve().parent.parent
client = TestClient(server.app)


def test_curriculum_marks_unauthored_problems():
    data = client.get("/api/curriculum").json()
    probs = {p["slug"]: p for s in data["stages"] for p in s["problems"]}
    assert len(probs) == 28
    assert probs["andgate"]["available"] is True
    assert probs["module_addsub"]["available"] is (ROOT / "problems" / "module_addsub" / "test.sv").is_file()


def test_problem_has_spec_and_template():
    p = client.get("/api/problem/vector4").json()
    assert p["available"] and "top_module" in p["spec"] and "TopModule" not in p["spec"]
    assert p["template"].startswith("module top_module (\n  input [7:0] in,\n  output [31:0] out\n);")
    assert p["hdlbits_url"].endswith("/vector4")


def test_template_compiles_but_fails():
    tpl = client.get("/api/problem/andgate").json()["template"]
    r = client.post("/api/grade", json={"slug": "andgate", "code": tpl}).json()
    assert r["status"] == "mismatch"  # an empty body leaves out undriven
    assert r["feedback"]["hints"]["L0"][0]["concept"] == "bitwise_ops"


def test_grade_reference_and_bug():
    ref = re.sub(r"\bmodule\s+RefModule\b", "module top_module", (ROOT / "problems" / "vector4" / "ref.sv").read_text())
    ok = client.post("/api/grade", json={"slug": "vector4", "code": ref}).json()
    assert ok["status"] == "pass" and ok["feedback"]["summary"].startswith("All")
    bad = client.post("/api/grade", json={"slug": "vector4", "code": ref.replace("{24{in[7]}}", "24'b0")}).json()
    assert bad["status"] == "mismatch"
    assert bad["waveform"] and "in" in bad["waveform"][-1]["inputs"]
    assert bad["feedback"]["hints"]["L1"]["mismatched_outputs"] == ["out"]


def test_unknown_and_unavailable_problems():
    assert client.get("/api/problem/nope").status_code == 404
    if not (ROOT / "problems" / "module_add" / "test.sv").is_file():
        r = client.post("/api/grade", json={"slug": "module_add", "code": "module top_module(); endmodule"})
        assert r.status_code == 409
        assert client.get("/api/problem/module_add").json()["available"] is False


def test_progress_roundtrip():
    r = client.post("/api/progress", json={"slug": "step_one", "passed": True}).json()
    assert r["progress"]["problems"]["step_one"]["solved"]
    assert r["view"]["stages"][0]["problems"][0]["solved"]


def test_rate_limit(monkeypatch):
    monkeypatch.setattr(server, "_grade_limit", server._RateLimiter(2))
    code = "module top_module(output one); assign one = 1; endmodule"
    codes = [client.post("/api/grade", json={"slug": "step_one", "code": code}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200 and "wire" in r.text
    assert client.get("/static/app.js").status_code == 200

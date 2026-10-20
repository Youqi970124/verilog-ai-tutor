import json
import shutil
from pathlib import Path

import pytest

from w2a import coach, grader, leak, mastery, tbgen

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "addsub"
ROOT = Path(__file__).resolve().parent.parent

GOOD = """module top_module(input [31:0] a, input [31:0] b, input sub, output [31:0] sum);
  wire c;
  wire [31:0] bx = b ^ {32{sub}};
  add16 lo (.a(a[15:0]), .b(bx[15:0]), .cin(sub), .sum(sum[15:0]), .cout(c));
  add16 hi (.a(a[31:16]), .b(bx[31:16]), .cin(c), .sum(sum[31:16]), .cout());
endmodule
"""
DEMO_BUG = GOOD.replace("b ^ {32{sub}}", "b ^ sub")


@pytest.fixture
def addsub(tmp_path):
    for name in ("given.sv", "ref.sv", "problem.json"):
        shutil.copyfile(FIXTURE / name, tmp_path / name)
    (tmp_path / "test.sv").write_text(tbgen.generate(json.loads((FIXTURE / "problem.json").read_text())))
    return tmp_path


def test_good_solution_passes(addsub):
    assert grader.grade(addsub, GOOD).status == "pass"


def test_demo_bug_counterexample_and_lines(addsub):
    res = grader.grade(addsub, DEMO_BUG)
    fb = coach.feedback("module_addsub", addsub, DEMO_BUG, res)
    l1 = fb["hints"]["L1"]
    assert "a = 5, b = 3, sub = 1" in l1["text"]
    assert "`sum` should be 2 but your circuit gives 8" in l1["text"]
    lines = {h["line"]: h for h in fb["hints"]["L2"]}
    assert 3 in lines and "b ^ sub" in lines[3]["code"]       # the root cause, one hop back through bx
    assert {4, 5} <= set(lines)                              # the instances that drive sum
    assert fb["hints"]["L3"].startswith("Invert every bit")
    assert [c["concept"] for c in fb["hints"]["L0"]] == ["add_sub", "replication"]


def test_missing_semicolon(addsub):
    src = GOOD.replace("wire c;", "wire c")
    fb = coach.feedback("module_addsub", addsub, src, grader.grade(addsub, src))
    assert fb["status"] == "compile_error"
    assert "Line 2 probably needs a semicolon" in fb["compile"]["explanation"]


def test_undeclared_and_unknown_module(addsub):
    src = GOOD.replace(".cin(c)", ".cin(carry)").replace("wire c;\n", "")
    res = grader.grade(addsub, src)
    fb = coach.feedback("module_addsub", addsub, src, res)
    assert fb["status"] in ("compile_error", "mismatch")
    src2 = GOOD.replace("add16 hi", "adder16 hi")
    fb2 = coach.feedback("module_addsub", addsub, src2, grader.grade(addsub, src2))
    assert "no module called `adder16`" in fb2["compile"]["explanation"]
    assert "add16" in fb2["compile"]["explanation"]


def test_implicit_wire_warning(addsub):
    src = GOOD.replace(".cout(c));", ".cout(cc));").replace("wire c;\n", "wire c;\n")
    res = grader.grade(addsub, src)
    ws = coach.warnings(res)
    assert any("`cc` was never declared" in w for w in ws)


def test_wire_assigned_in_always():
    andgate = ROOT / "problems" / "andgate"
    src = "module top_module(input a, input b, output out);\n  always @(*) out = a & b;\nendmodule\n"
    res = grader.grade(andgate, src)
    fb = coach.feedback("andgate", andgate, src, res)
    assert res.category == "w"
    assert "declared as a wire" in fb["compile"]["explanation"]


def test_structure_feedback(addsub):
    src = "module top_module(input [31:0] a, input [31:0] b, input sub, output [31:0] sum);\n" \
          "  assign sum = sub ? a - b : a + b;\nendmodule\n"
    fb = coach.feedback("module_addsub", addsub, src, grader.grade(addsub, src))
    assert fb["status"] == "structure" and "add16" in fb["compile"]["explanation"]


@pytest.mark.parametrize("hint,leaks", [
    ("Replicate `sub` to 32 bits, for example with `{32{sub}}`.", False),
    ("Change it to `b ^ {32{sub}}`.", True),
    ("Use `wire [31:0] bx = b ^ {32{sub}};` instead.", True),
    ("Think about how wide sub is compared to b.", False),
    ("```verilog\nwire c;\nassign x = y;\n```", True),
])
def test_leak_check(hint, leaks):
    got, reason = leak.check(hint, GOOD, DEMO_BUG)
    assert got == leaks, reason


def test_mastery_and_unlocks():
    p = mastery.empty()
    for slug in ("step_one", "zero", "wire"):
        mastery.record(p, slug, passed=True)
    v = mastery.view(p)
    assert v["stages"][0]["unlocked"] and not v["stages"][0]["done"] and not v["stages"][1]["unlocked"]
    mastery.record(p, "wire4", passed=False, hint_level=2)
    mastery.record(p, "wire4", passed=True, hint_level=2)
    v = mastery.view(p)
    assert v["stages"][0]["done"] and v["stages"][1]["unlocked"]
    assert "assign" in v["mastered"] and "multi_assign" in v["review"]
    mastery.record(p, "wire4", passed=True)  # solved problems do not count again
    assert p["problems"]["wire4"]["attempts"] == 2

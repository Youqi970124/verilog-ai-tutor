import json
import re
from pathlib import Path

import pytest

from w2a import grader, safety, vcd

ROOT = Path(__file__).resolve().parent.parent
PROBLEMS = ROOT / "problems"
CURRICULUM = json.loads((ROOT / "curriculum" / "curriculum.json").read_text())
IMPORTED = [p["slug"] for s in CURRICULUM["stages"] for p in s["problems"] if p["verilogeval"]]


def ref_as_learner(slug: str) -> str:
    src = (PROBLEMS / slug / "ref.sv").read_text()
    return re.sub(r"\bmodule\s+RefModule\b", "module top_module", src)


def test_curriculum_has_28_problems():
    slugs = [p["slug"] for s in CURRICULUM["stages"] for p in s["problems"]]
    assert len(slugs) == 28 and len(set(slugs)) == 28
    assert slugs[-1] == "module_addsub"
    assert len(IMPORTED) == 19


@pytest.mark.parametrize("slug", IMPORTED)
def test_reference_solution_passes(slug):
    result = grader.grade(PROBLEMS / slug, ref_as_learner(slug))
    assert result.status == "pass", result.compile_log + result.sim_log
    assert result.mismatches == 0 and result.samples > 0


def test_wrong_gate_gives_counterexample():
    src = ref_as_learner("andgate").replace("a & b", "a | b")
    result = grader.grade(PROBLEMS / "andgate", src)
    assert result.status == "mismatch" and result.category == "R"
    cx = result.counterexample
    assert cx and cx["mismatched_outputs"] == ["out"]
    a, b = (vcd.to_int(cx["inputs"][n]["value"]) for n in ("a", "b"))
    expected = vcd.to_int(cx["outputs"]["out"]["expected"])
    got = vcd.to_int(cx["outputs"]["out"]["got"])
    # The counterexample must be a real one: the reference agrees with a & b, the learner with a | b.
    assert expected == (a & b) and got == (a | b) and expected != got


def test_logical_vs_bitwise_or_is_caught():
    src = ref_as_learner("vectorgates").replace("a | b", "a || b")
    result = grader.grade(PROBLEMS / "vectorgates", src)
    assert result.status == "mismatch"
    bad = {o.name for o in result.outputs if o.mismatches}
    assert bad == {"out_or_bitwise"}
    cx = result.counterexample
    a = vcd.to_int(cx["inputs"]["a"]["value"])
    b = vcd.to_int(cx["inputs"]["b"]["value"])
    assert vcd.to_int(cx["outputs"]["out_or_bitwise"]["expected"]) == a | b


def test_missing_sign_extension_is_caught():
    src = ref_as_learner("vector4").replace("{24{in[7]}}", "24'b0")
    result = grader.grade(PROBLEMS / "vector4", src)
    assert result.status == "mismatch"
    cx = result.counterexample
    value = vcd.to_int(cx["inputs"]["in"]["value"])
    assert value >= 0x80  # only negative inputs expose the bug
    assert len(result.history) > 0


def test_syntax_error_category():
    result = grader.grade(PROBLEMS / "andgate", "module top_module(input a, input b, output out);\n assign out = a & b\nendmodule\n")
    assert result.status == "compile_error" and result.category == "S"


def test_undeclared_signal_category():
    src = "module top_module(input a, input b, output out);\n assign out = a & c;\nendmodule\n"
    result = grader.grade(PROBLEMS / "andgate", src)
    assert result.status == "compile_error" and result.category in ("p", "C")


def test_always_without_delay_is_caught_at_compile_time():
    src = ("module top_module(input a, input b, output out);\n"
           " reg r = 0;\n always r = ~r;\n assign out = a & b;\nendmodule\n")
    result = grader.grade(PROBLEMS / "andgate", src)
    assert result.status == "compile_error"
    assert "does not have any delay" in result.compile_log


def test_endless_loop_times_out():
    src = ("module top_module(input a, input b, output out);\n"
           " reg r = 0;\n initial while (1) r = ~r;\n assign out = a & b;\nendmodule\n")
    result = grader.grade(PROBLEMS / "andgate", src, sim_timeout=3)
    assert result.status == "timeout" and result.category == "T"


@pytest.mark.parametrize("snippet,code", [
    ('initial $fopen("x.txt");', "system_task"),
    ("`include \"/etc/passwd\"", "directive"),
    ("initial force tb.stats1.errors = 0;", "force"),
    ("assign out = tb.good1.out;", "hierarchical_ref"),
])
def test_safety_rejects(snippet, code):
    src = f"module top_module(input a, input b, output out);\n {snippet}\nendmodule\n"
    check = safety.check(src)
    assert not check.ok and check.code == code and check.line == 2
    assert grader.grade(PROBLEMS / "andgate", src).status == "rejected"


def test_safety_ignores_comments_and_strings():
    src = ("// $fopen in a comment is fine\n"
           "module top_module(input a, input b, output out); /* tb.x */\n"
           " assign out = a & b;\nendmodule\n")
    assert safety.check(src).ok


def test_reserved_module_name_rejected():
    assert safety.check("module RefModule(); endmodule\nmodule top_module(); endmodule").code == "reserved_module"

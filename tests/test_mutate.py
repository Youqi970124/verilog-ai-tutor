import json
import re
import shutil
from pathlib import Path

import pytest

from w2a import equiv, mutate, safety, tbgen

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "add4"

ADDSUB = """module top_module(input [31:0] a, input [31:0] b, input sub, output [31:0] sum);
  wire c;
  wire [31:0] bx = b ^ {32{sub}};
  add16 lo (.a(a[15:0]), .b(bx[15:0]), .cin(sub), .sum(sum[15:0]), .cout(c));
  add16 hi (.a(a[31:16]), .b(bx[31:16]), .cin(c), .sum(sum[31:16]), .cout());
endmodule
"""

ADD4 = """module top_module(input [3:0] a, input [3:0] b, output [3:0] sum, output cout);
  wire c1;
  add2 lo (.a(a[1:0]), .b(b[1:0]), .cin(1'b0), .sum(sum[1:0]), .cout(c1));
  add2 hi (.a(a[3:2]), .b(b[3:2]), .cin(c1), .sum(sum[3:2]), .cout(cout));
endmodule
"""


def by_op(mutants):
    out = {}
    for m in mutants:
        out.setdefault(m.op, []).append(m)
    return out


def test_strip_keeps_positions():
    src = "assign y = a; // note with $fopen\n/* block\n */ assign z = \"s\";\n"
    code = safety.strip_comments_and_strings(src)
    assert len(code) == len(src) and code.count("\n") == src.count("\n")
    assert "$fopen" not in code and code.index("assign z") == src.index("assign z")


def test_demo_bug_is_generated():
    ms = by_op(mutate.mutants(ADDSUB))
    dropped = ms["drop_replication"][0]
    assert dropped.concept == "replication"
    assert "b ^ sub;" in dropped.src  # the b ^ sub mistake from the demo
    assert any(m.after == ".cin(1'b0)" for m in ms["carry_in_zero"])
    assert ms["swap_named_ports"]


def test_comments_are_not_mutated():
    src = "module top_module(input a, input b, output out);\n  // a & b would be wrong\n  assign out = a | b;\nendmodule\n"
    assert all(m.line != 2 for m in mutate.mutants(src))


def test_positional_swap():
    src = "module top_module(input a, input b, output out);\n  mod_a u1 (a, b, out);\nendmodule\n"
    m = by_op(mutate.mutants(src))["swap_positional_ports"][0]
    assert "mod_a u1 (b, a, out);" in m.src


@pytest.fixture
def add4(tmp_path):
    spec = json.loads((FIXTURE / "problem.json").read_text())
    for name in ("given.sv", "ref.sv", "problem.json"):
        shutil.copyfile(FIXTURE / name, tmp_path / name)
    (tmp_path / "test.sv").write_text(tbgen.generate(spec))
    return tmp_path


def test_structural_mutants_are_caught(add4):
    results = mutate.evaluate(add4, ADD4)
    statuses = {r.mutant.op: r.status for r in results}
    assert statuses["carry_in_zero"] == "killed"
    sc = mutate.score(results)
    assert sc["survived"] == 0 and sc["killed"] >= 5


def test_reference_mutants_all_caught_on_andgate():
    sol = re.sub(r"\bmodule\s+RefModule\b", "module top_module", (ROOT / "problems" / "andgate" / "ref.sv").read_text())
    sc = mutate.score(mutate.evaluate(ROOT / "problems" / "andgate", sol))
    assert sc["kill_rate"] == 1.0 and sc["survived"] == 0


@pytest.mark.skipif(equiv.yosys_path() is None, reason="yosys not installed")
def test_equivalence_with_given_modules():
    given = (FIXTURE / "given.sv").read_text()
    swapped = ADD4.replace(".a(a[1:0]), .b(b[1:0])", ".a(b[1:0]), .b(a[1:0])")  # addition commutes
    assert equiv.equivalent(ADD4, swapped, given) is True
    assert equiv.equivalent(ADD4, ADD4.replace(".cin(c1)", ".cin(1'b0)"), given) is False

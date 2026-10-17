import json
import re
import shutil
from pathlib import Path

import pytest

from w2a import grader, tbgen, vcd

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "add4"

STRUCTURAL = """module top_module(input [3:0] a, input [3:0] b, output [3:0] sum, output cout);
  wire c1;
  add2 lo (.a(a[1:0]), .b(b[1:0]), .cin(1'b0), .sum(sum[1:0]), .cout(c1));
  add2 hi (.a(a[3:2]), .b(b[3:2]), .cin(c1), .sum(sum[3:2]), .cout(cout));
endmodule
"""


@pytest.fixture
def add4(tmp_path):
    spec = json.loads((FIXTURE / "problem.json").read_text())
    for name in ("given.sv", "ref.sv", "problem.json"):
        shutil.copyfile(FIXTURE / name, tmp_path / name)
    (tmp_path / "test.sv").write_text(tbgen.generate(spec))
    return tmp_path


def test_structural_solution_passes(add4):
    result = grader.grade(add4, STRUCTURAL)
    assert result.status == "pass", result.compile_log + result.sim_log
    assert result.samples > 100 and not result.structure_issues


def test_behavioural_shortcut_flagged(add4):
    src = "module top_module(input [3:0] a, input [3:0] b, output [3:0] sum, output cout);\n" \
          "  assign {cout, sum} = a + b;\nendmodule\n"
    result = grader.grade(add4, src)
    assert result.status == "structure" and result.category == "M"
    assert "add2" in result.structure_issues[0]


def test_dropped_carry_gives_real_counterexample(add4):
    result = grader.grade(add4, STRUCTURAL.replace(".cin(c1)", ".cin(1'b0)"))
    assert result.status == "mismatch"
    cx = result.counterexample
    a, b = (vcd.to_int(cx["inputs"][n]["value"]) for n in ("a", "b"))
    assert vcd.to_int(cx["outputs"]["sum"]["expected"]) == (a + b) & 0xF
    # The first directed vector (3 + 1) carries out of the low half, so it is the first failure.
    assert (a, b) == (3, 1)
    assert vcd.to_int(cx["outputs"]["sum"]["got"]) == 0


def test_generated_testbench_matches_verilogeval_on_vector4(tmp_path):
    """Our generator must accept and reject the same designs as VerilogEval's own testbench."""
    src_dir = ROOT / "problems" / "vector4"
    shutil.copyfile(src_dir / "ref.sv", tmp_path / "ref.sv")
    spec = {"interface": {"inputs": [{"name": "in", "width": 8}], "outputs": [{"name": "out", "width": 32}]},
            "random_samples": 100}
    (tmp_path / "test.sv").write_text(tbgen.generate(spec))
    ref = re.sub(r"\bmodule\s+RefModule\b", "module top_module", (src_dir / "ref.sv").read_text())
    wrong = ref.replace("{24{in[7]}}", "24'b0")
    for design, expected in ((ref, "pass"), (wrong, "mismatch")):
        assert grader.grade(tmp_path, design).status == expected
        assert grader.grade(src_dir, design).status == expected


def test_clocked_interface(tmp_path):
    (tmp_path / "ref.sv").write_text(
        "module RefModule(input clk, input [7:0] d, output reg [7:0] q);\n"
        "  always @(posedge clk) q <= d;\nendmodule\n")
    spec = {"interface": {"inputs": [{"name": "d", "width": 8}], "outputs": [{"name": "q", "width": 8}],
                          "clock": True}, "random_samples": 50}
    (tmp_path / "test.sv").write_text(tbgen.generate(spec))
    good = "module top_module(input clk, input [7:0] d, output reg [7:0] q);\n" \
           "  always @(posedge clk) q <= d;\nendmodule\n"
    assert grader.grade(tmp_path, good).status == "pass"
    assert grader.grade(tmp_path, good.replace("posedge", "negedge")).status == "mismatch"


def test_rejects_unknown_directed_input():
    with pytest.raises(ValueError):
        tbgen.generate({"interface": {"inputs": [{"name": "a", "width": 1}], "outputs": [{"name": "y", "width": 1}]},
                        "directed": [{"b": 1}]})

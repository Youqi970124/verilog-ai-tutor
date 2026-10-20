import json
from pathlib import Path

import pytest

from w2a import authoring, llm, ports

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "add4"
OUTLINE = {
    "outline": "Build a 4-bit adder from two provided 2-bit adders; the low carry feeds the high half.",
    "given": "module add2(input [1:0] a, input [1:0] b, input cin, output [1:0] sum, output cout)",
    "top": "module top_module(input [3:0] a, input [3:0] b, output [3:0] sum, output cout)",
    "require_instances": {"add2": 2},
}
SOLUTION = """module top_module(input [3:0] a, input [3:0] b, output [3:0] sum, output cout);
  wire c1;
  add2 lo (.a(a[1:0]), .b(b[1:0]), .cin(1'b0), .sum(sum[1:0]), .cout(c1));
  add2 hi (.a(a[3:2]), .b(b[3:2]), .cin(c1), .sum(sum[3:2]), .cout(cout));
endmodule"""
REF = """module RefModule(input [3:0] a, input [3:0] b, output [3:0] sum, output cout);
  assign {cout, sum} = a + b;
endmodule"""


def reply(ref=REF, directed=None, solution=SOLUTION) -> str:
    data = {
        "spec": "Connect two 2-bit adders into a 4-bit adder.",
        "given_sv": (FIXTURE / "given.sv").read_text(),
        "ref_sv": ref,
        "solution_sv": solution,
        "directed": directed if directed is not None else [{"a": 3, "b": 1}],
        "hints": {"L0": "Think about where the carry goes.", "L3": "Feed the low adder's carry-out into the high adder."},
        "common_mistakes": ["Tying the high carry-in to 0."],
    }
    return "Here you go:\n```json\n" + json.dumps(data) + "\n```"


def test_parse_header_inherits_direction():
    name, ps = ports.parse_header("module top_module(input [3:0] a, b, input sub, output reg [7:0] q);")
    assert name == "top_module"
    assert ps == [{"name": "a", "dir": "input", "width": 4}, {"name": "b", "dir": "input", "width": 4},
                  {"name": "sub", "dir": "input", "width": 1}, {"name": "q", "dir": "output", "width": 8}]


def test_feedback_loop_fixes_a_wrong_reference(tmp_path):
    fake = llm.Scripted([reply(ref=REF.replace("a + b", "a - b")), reply()])
    res = authoring.author("add4", OUTLINE, fake, out_root=tmp_path, log=lambda *_: None)
    assert res.ok and len(res.rounds) == 2
    assert "does not pass" in res.rounds[0].problems[0]
    # the second request carried the simulator's complaint back to the model
    assert "first mismatch" in fake.calls[1][-1]["content"]
    out = tmp_path / "add4"
    meta = json.loads((out / "problem.json").read_text())
    assert meta["review"] == "pending" and meta["require_instances"] == {"add2": 2}
    assert {f.name for f in out.iterdir()} >= {"prompt.txt", "given.sv", "ref.sv", "solution.sv", "test.sv", "authoring_log.json"}
    assert res.rounds[1].mutation["survived"] == 0


def test_weak_directed_vectors_are_sent_back(tmp_path, monkeypatch):
    monkeypatch.setattr(authoring, "RANDOM_SAMPLES", 0)  # only directed vectors drive the testbench
    exhaustive = [{"a": a, "b": b} for a in range(16) for b in range(16)]
    fake = llm.Scripted([reply(directed=[]), reply(directed=exhaustive)])
    res = authoring.author("add4", OUTLINE, fake, out_root=tmp_path, log=lambda *_: None)
    assert res.ok and len(res.rounds) == 2
    assert "Add directed vectors" in res.rounds[0].problems[-1]
    assert res.rounds[1].mutation["kill_rate"] == 1.0


def test_port_mismatch_and_bad_json_are_reported(tmp_path):
    bad_ports = REF.replace("output cout", "output carry").replace("{cout, sum}", "{carry, sum}")
    fake = llm.Scripted(["not json at all", reply(ref=bad_ports), reply()])
    res = authoring.author("add4", OUTLINE, fake, out_root=tmp_path, log=lambda *_: None)
    assert res.ok and len(res.rounds) == 3
    assert "JSON" in res.rounds[0].problems[0]
    assert "RefModule ports" in res.rounds[1].problems[0]


def test_gives_up_after_max_rounds(tmp_path):
    fake = llm.Scripted([reply(ref=REF.replace("a + b", "a - b"))] * 2)
    res = authoring.author("add4", OUTLINE, fake, out_root=tmp_path, max_rounds=2, log=lambda *_: None)
    assert not res.ok and not (tmp_path / "add4").exists()
    assert (tmp_path / "_failed_add4" / "authoring_log.json").is_file()


def test_refuses_to_overwrite(tmp_path):
    (tmp_path / "add4").mkdir()
    with pytest.raises(FileExistsError):
        authoring.author("add4", OUTLINE, llm.Scripted([]), out_root=tmp_path)

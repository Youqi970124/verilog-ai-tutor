# Wire-to-Adder

A Verilog coaching agent that takes a complete beginner through the first 28 [HDLBits](https://hdlbits.01xz.net/) problems, from connecting a single wire to building a 32-bit adder-subtractor. The learner writes the circuit. The simulator tests it. NVIDIA Nemotron models on Nebius Token Factory explain what went wrong and give graded hints without handing over the answer.

Built for the Nebius × NVIDIA Global AI Hackathon, Coding & Agentic Engineering track.

> **Status: work in progress.** The grader, the testbench generator and the curriculum are done and tested. The authoring agent, the coach agent and the web app are not built yet.

## What works today

| Part | State |
|---|---|
| Curriculum: 28 problems in 8 stages (`curriculum/curriculum.json`) | Done |
| 19 problems imported from NVIDIA's VerilogEval (MIT) | Done; all reference solutions pass |
| Grader: compile and simulate with Icarus Verilog 12, VerilogEval failure categories | Done |
| Counterexample extraction: the exact inputs, expected and actual outputs at the first mismatch, read from the VCD | Done |
| Safety checks on learner code (system tasks, directives, `force`, testbench references) | Done |
| Structural checks (for example "use two `add16` instances", so `assign sum = a + b;` does not count) | Done |
| Testbench generator for new problems, VerilogEval-compatible output | Done |
| Authoring agent for the 9 Modules problems VerilogEval lacks | Inputs written (`curriculum/outlines.json`); agent not built |
| Coach agent: hint ladder L0 to L3, leak check, mastery tracking | Not started |
| Web app | Not started |

## Setup

```bash
conda env create -f environment.yml
conda activate w2a
pytest -q
```

VerilogEval requires Icarus Verilog 12; version 13 is not supported. If `iverilog` is not on your `PATH`, set `W2A_TOOLCHAIN_BIN` to the directory that contains it.

To re-import the VerilogEval problems:

```bash
git clone https://github.com/NVlabs/verilog-eval.git ../third_party/verilog-eval
python scripts/import_verilogeval.py ../third_party/verilog-eval
```

## Model check

`scripts/model_spike.py` sends each imported problem to Nemotron 3.5 Lightning, Nemotron 3 Super and Nemotron 3 Ultra on Nebius Token Factory and grades the answers:

```bash
export NEBIUS_API_KEY=...
python scripts/model_spike.py
```

## Layout

```
curriculum/   curriculum.json (28 problems), outlines.json (authoring inputs)
problems/     one directory per problem: prompt.txt, ref.sv, test.sv, SOURCE.json
w2a/          grader.py, safety.py, vcd.py, tbgen.py
scripts/      import_verilogeval.py, model_spike.py
tests/        grader and testbench-generator tests
```

## Credits

Problems 1 to 19 come from [VerilogEval](https://github.com/NVlabs/verilog-eval) (NVIDIA, MIT License), which adapts them from HDLBits. HDLBits was created by Henry Wong. See `THIRD_PARTY_NOTICES.md`.

## License

MIT

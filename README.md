# Wire-to-Adder

A Verilog coaching agent that takes a complete beginner through the first 28 [HDLBits](https://hdlbits.01xz.net/) problems, from connecting a single wire to building a 32-bit adder-subtractor. The learner writes the circuit. The simulator tests it. NVIDIA Nemotron models on Nebius Token Factory explain what went wrong and give graded hints without handing over the answer.

Built for the Nebius × NVIDIA Global AI Hackathon, Coding & Agentic Engineering track.

> **Status: work in progress.** All 28 problems are playable. The 9 Modules problems were written by the authoring agent with Nemotron 3 Ultra and verified by tools. Model-written hints in the coach are not connected yet.

## How it works

```
 offline   outline ──▶ Authoring agent (Nemotron 3 Ultra) ──▶ problem, reference, solution, vectors, hints
                         ▲                                        │
                         └── feedback: port check, simulation, ◀──┘
                             mutation testing, Yosys equivalence

 online    learner code ──▶ safety check ──▶ Icarus Verilog ──▶ coach ──▶ hints L0..L3 ──▶ learner
                                                 │                 ▲
                                                 └── VCD waveform ─┘   counterexample and lines come from
                                                                       the simulator, never from the model
```

- **Grader.** Compiles and simulates with Icarus Verilog 12 using VerilogEval's flags and failure categories. Reads the first mismatch straight from the VCD: the exact inputs, the expected and the actual outputs.
- **Safety.** Learner code runs on the server, so system tasks, `include, `force` and references into the testbench are rejected before compiling. Simulation has CPU, memory, file-size and time limits.
- **Coach, rule layer.** L0 concept note, L1 counterexample, L2 the lines that drive the wrong output (traced back through internal wires), L3 a structural hint written at authoring time. Compile errors get a plain explanation with the line.
- **Leak check.** Before a model-written hint reaches the learner, it is compared with the reference statements the learner is missing. Naming an operator is fine; writing the fixed line is not.
- **Authoring agent.** The model writes the problem text, the provided modules, a behavioural reference, a learner-style solution, directed vectors and hints. Tools decide whether it is right: the testbench is generated from the interface, the solution must pass and use the required submodules, and every beginner-style mutant must be caught or proven equivalent by Yosys. Failures go back to the model.
- **Web app.** Stage map, editor, waveform with dec/hex/bin, hint ladder. Progress stays in the browser.

## Results so far

**Authoring agent** (`python scripts/author.py`, Nemotron 3 Ultra): all 9 Modules problems verified in 17 rounds, 60k tokens, about $0.15. Eight needed feedback first: old-style port headers, a procedural assignment to a wire, a syntax error in a provided module, and one learner solution that disagreed with the reference until the simulator's counterexample went back to the model. A review pass by our coding assistant (team sign-off pending) then trimmed three specs that gave away the wiring and added a missing port mapping to one; see `review_notes` in each `problem.json`.

| Problem | Rounds | Tokens | First failure |
|---|---|---|---|
| module | 3 | 7.1k | port header the checker could not read |
| module_pos | 2 | 5.3k | port header |
| module_name | 2 | 8.2k | port header |
| module_shift | 2 | 5.8k | procedural assignment to a wire |
| module_shift8 | 2 | 9.8k | procedural assignment to a wire |
| module_add | 1 | 3.1k | none |
| module_fadd | 2 | 9.6k | syntax error in the provided module |
| module_cseladd | 1 | 5.1k | none |
| module_addsub | 2 | 6.4k | solution disagreed with reference |

**Mutation testing of all 28 problems** (`python scripts/mutation_report.py`): 219 beginner-style mutants. 149 caught by the testbenches, 0 missed, 46 proven equivalent to the reference by Yosys, 24 do not compile. The 173 caught or non-compiling mutants are saved under `eval/buggy/` as the evaluation set for the coach.

**Model check** (`python scripts/model_spike.py`, 19 problems, temperature 0, graded by our grader):

| Model | Solved | Median latency | Tokens |
|---|---|---|---|
| Nemotron 3 Ultra | 19/19 | 1.1 s | 12k |
| Nemotron 3.5 Lightning | 19/19 | 2.0 s | 27k |
| Nemotron 3 Super | 17/19 | 2.4 s | 12k |

Temperature 0 was not deterministic: one Super failure passed on a rerun. That is why every model output goes through the simulator before anyone sees it.

## Setup

```bash
conda env create -f environment.yml
conda activate w2a
pytest -q
```

VerilogEval requires Icarus Verilog 12; version 13 is not supported. If `iverilog` is not on your `PATH`, set `W2A_TOOLCHAIN_BIN` to the directory that contains it.

## Run the web app

```bash
uvicorn w2a.server:app --reload        # http://127.0.0.1:8000
```

With Docker:

```bash
docker build -t wire-to-adder .
docker run --read-only --tmpfs /tmp -p 8000:8000 wire-to-adder
```

## Authoring and model scripts

```bash
python scripts/author.py --dry-run              # show the prompts, no model calls
python scripts/author.py module_add             # author one problem with Nemotron 3 Ultra
python scripts/mutation_report.py               # mutation testing of every problem
python scripts/model_spike.py                   # Nemotron models on the imported problems
```

The scripts read `NEBIUS_API_KEY` from the environment or from a git-ignored `.env` file.

To re-import the VerilogEval problems:

```bash
git clone https://github.com/NVlabs/verilog-eval.git ../third_party/verilog-eval
python scripts/import_verilogeval.py ../third_party/verilog-eval
```

## Layout

```
curriculum/   curriculum.json (28 problems), outlines.json (authoring inputs), concepts.json (L0 notes)
problems/     one directory per problem: prompt.txt, ref.sv, test.sv, and for authored ones given.sv, solution.sv, problem.json
w2a/          grader, safety, vcd, tbgen, mutate, equiv, authoring, coach, leak, mastery, llm, server
web/          index.html, app.js, style.css
scripts/      import_verilogeval.py, author.py, mutation_report.py, model_spike.py
eval/         mutation report and buggy submissions for evaluating the coach
tests/        73 tests
```

## Credits

Problems 1 to 19 come from [VerilogEval](https://github.com/NVlabs/verilog-eval) (NVIDIA, MIT License), which adapts them from HDLBits. HDLBits was created by Henry Wong; we link to its problems and reuse their module interfaces, and copy none of its text. See `THIRD_PARTY_NOTICES.md`.

## License

MIT

# Verilog AI Tutor

An AI Verilog tutor that follows the [HDLBits](https://hdlbits.01xz.net/) problem path (unofficial; not affiliated with HDLBits). It takes a complete beginner through the first 28 problems, from connecting a single wire to building a 32-bit adder-subtractor. The learner writes the circuit. The simulator tests it. NVIDIA Nemotron models on Nebius Token Factory explain what went wrong and give graded hints without handing over the answer.

Built for the Nebius × NVIDIA Global AI Hackathon, Coding & Agentic Engineering track.

**Live demo:** https://verilog-ai-tutor.onrender.com (free instance: after 15 idle minutes the first load takes up to a minute)

**Demo video (2.5 min):** https://youtu.be/5nN6dzE9evE

All 28 problems are playable. The 9 Modules problems were written by the authoring agent with Nemotron 3 Ultra and verified by tools. The coach asks Nemotron 3 Ultra for hints and has been evaluated on 173 buggy submissions.

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
- **Coach, model layer.** "Ask the coach" sends Nemotron 3 Ultra the problem, the learner's numbered code, the simulator's findings, the candidate lines and a hidden reference solution. It answers at the next hint level (L0 concept, L1 trace the wrong sample, L2 the line and what it does, L3 the change in words) and names the line it blames.
- **Leak check.** Every model-written hint is compared with the reference statements the learner is missing before anyone sees it. Naming an operator is fine; writing the fixed line is not. A leaking or cut-off answer goes back to the model once; if it fails again, the learner gets the rule layer's hint. Answers are cached, rate limited per IP and capped per day to protect the credit balance.
- **Authoring agent.** The model writes the problem text, the provided modules, a behavioural reference, a learner-style solution, directed vectors and hints. Tools decide whether it is right: the testbench is generated from the interface, the solution must pass and use the required submodules, and every beginner-style mutant must be caught or proven equivalent by Yosys. Failures go back to the model.
- **Web app.** Stage map, editor, waveform with dec/hex/bin, hint ladder. Progress stays in the browser.

## NVIDIA Nemotron and Nebius Token Factory

Every model call goes through Nebius Token Factory's OpenAI-compatible API (`https://api.tokenfactory.nebius.com/v1/`), so switching models is a one-word change. The models do two jobs: write and verify new problems offline, and coach learners live. In both, a simulator checks or grounds what the model says.

| NVIDIA model or asset | Where it is used | Result |
|---|---|---|
| **Nemotron 3 Ultra** (`nvidia/Nemotron-3-Ultra-550b-a55b`) | Authoring agent: wrote the 9 Modules problems (spec, provided modules, reference, learner solution, test vectors, hints) | 9/9 verified with 0 surviving mutants, 17 rounds, about $0.15 |
| **Nemotron 3 Ultra** | Live coach behind "Ask the coach", reasoning on | Blamed the right line in 97.8% of bugs that have one; about 3 s median and $0.003 per hint |
| **Nemotron 3 Super** (`nvidia/nemotron-3-super-120b-a12b`) | Coach comparison | 94.9% on the same bugs |
| **Nemotron 3.5 Lightning** (`nvidia/Nemotron-3_5-Lightning`) | Day-one model check on the 19 imported problems | 19/19 |
| **VerilogEval** (NVlabs, MIT) | Problems 1 to 19 with their testbenches | Graded with the same flags and failure categories |

Where Token Factory sped up the work:

- **Choosing models took minutes.** One endpoint served Lightning, Super and Ultra, so the day-one check of all three cost about $0.04.
- **Problems were authored by the model, not by hand.** The authoring loop ran end to end on Ultra for about $0.15. Without that loop, the 9 missing problems, their reference solutions and their testbench vectors would have been written by hand.
- **Evaluation was cheap enough to run in full.** We graded 519 hints: 173 bugs, each run through Ultra at L2, Ultra at L3 and Super at L2. The two Ultra runs cost about $1.10, and the Super run used fewer tokens than either.
- **The usage data fed back into the design.** Usage reports include reasoning tokens. That showed reasoning shares `max_tokens` with the answer: one reply was cut off at 2,048, so the coach now uses 4,096.

Development and evaluation together have cost about $1.50 so far. Other Nebius services: the credits came from the Nebius AI Builder Program. Nebius AI Cloud is not used. The simulator is CPU-only and the web app runs on Render's free tier, so Token Factory is the only Nebius service the app calls at runtime.

## Results so far

**Authoring agent** (`python scripts/author.py`, Nemotron 3 Ultra): all 9 Modules problems verified in 17 rounds, 60k tokens, about $0.15. Seven needed feedback first: old-style port headers, a procedural assignment to a wire, a syntax error in a provided module, and one learner solution that disagreed with the reference until the simulator's counterexample went back to the model. A first review pass then trimmed three specs that gave away the wiring and added a missing port mapping to one; see `review_notes` in each `problem.json`.

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

**Coach evaluation** (`python scripts/eval_coach.py`, per-item results in `eval/coach_runs/`). Each buggy submission was made by mutating a correct solution, so the wrong line is known. The coach was asked for an L2 hint ("which line, and what does it do") and scored on the line it blamed.

| | Nemotron 3 Ultra | Nemotron 3 Super | Rule layer alone |
|---|---|---|---|
| Blamed the injected line (137 bugs with a wrong line) | **97.8%** | 94.9% | 48.2% |
| Named the unassigned signal (36 bugs where a line was deleted) | 100% | 100% | – |
| Hints that leaked and had to be rewritten | 0% | 0% | – |
| Median / 90th percentile latency | 3.3 s / 7.2 s | 3.2 s / 5.1 s | – |
| Mean tokens per hint | 1,705 | 1,319 | – |

The three Ultra misses all explain the bug correctly but point at a neighbouring line of the same statement, for example the first line of a multi-line instance. Ultra costs about $0.003 per hint. A second run at L3, the level closest to the answer, produced no leaks and fell back to the rule hint once (0.6%) after two cut-off replies. Known limit: when the fix is a single declaration range such as `[31:0]`, an L3 hint that names it is effectively the answer; the leak check does not look at the module header.

**Model check** (`python scripts/model_spike.py`, 19 problems, temperature 0, graded by our grader):

| Model | Solved | Median latency | Tokens |
|---|---|---|---|
| Nemotron 3 Ultra | 19/19 | 1.1 s | 12k |
| Nemotron 3.5 Lightning | 19/19 | 2.0 s | 27k |
| Nemotron 3 Super | 17/19 | 2.4 s | 12k |

Temperature 0 was not deterministic: one Super failure passed on a rerun. That is why every model output goes through the simulator before anyone sees it.

**Coach spot check** (one question, reasoning on and off): "a 32-bit `b` XORed with a 1-bit `sub`, what goes wrong?" With reasoning off, all three models answered wrongly (for example "inverts all 32 bits"). With reasoning on, Ultra was right in 1.9 s, Super right in 5.3 s, and Lightning right but slow (94 s at the time). The coach therefore uses Ultra with reasoning on. On eight buggy submissions Ultra blamed the injected line every time, with no leaks, at 1 to 10 s and about 1k to 2.5k tokens per hint (about $0.005). One reply was cut off by a 2,048-token cap; the cap is now 4,096 and cut-off replies are retried.

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
docker build -t verilog-ai-tutor .
docker run --read-only --tmpfs /tmp -p 8000:8000 verilog-ai-tutor
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
w2a/          grader, safety, vcd, tbgen, mutate, equiv, authoring, coach, tutor, leak, mastery, llm, server
web/          index.html, app.js, style.css
scripts/      import_verilogeval.py, author.py, mutation_report.py, model_spike.py
eval/         mutation report, buggy submissions, coach evaluation runs and summary
tests/        86 tests
```

## Credits

Problems 1 to 19 come from [VerilogEval](https://github.com/NVlabs/verilog-eval) (NVIDIA, MIT License), which adapts them from HDLBits. HDLBits was created by Henry Wong; we link to its problems and reuse their module interfaces, and copy none of its text. See `THIRD_PARTY_NOTICES.md`.

## License

MIT

"""Generate a VerilogEval-style testbench from a problem's interface.

The authoring agent writes the problem text, the reference solution and the
directed test vectors. The comparison logic is generated here instead, so a
model can never ship a testbench that silently checks nothing. The output
format matches the VerilogEval testbenches, so grader.py parses both.
"""

from math import ceil


def _range(width: int) -> str:
    return f"[{width - 1}:0] " if width > 1 else ""


def _random(width: int) -> str:
    n = ceil(width / 32)
    return "$random" if n == 1 else "{" + ", ".join(["$random"] * n) + "}"


def generate(spec: dict) -> str:
    iface = spec["interface"]
    ins, outs = iface["inputs"], iface["outputs"]
    clocked = bool(iface.get("clock"))
    directed = spec.get("directed", [])
    n_random = int(spec.get("random_samples", 200))

    if not outs:
        raise ValueError("interface needs at least one output")
    for vec in directed:
        unknown = set(vec) - {p["name"] for p in ins}
        if unknown:
            raise ValueError(f"directed vector sets unknown inputs: {sorted(unknown)}")

    widths = {p["name"]: p["width"] for p in ins}
    L = ["`timescale 1 ps/1 ps", "`define OK 12", "`define INCORRECT 13", "", ""]

    # stimulus
    L.append("module stimulus_gen (")
    L.append("\tinput clk" + ("," if ins else ""))
    L.append(",\n".join(f"\toutput logic {_range(p['width'])}{p['name']}" for p in ins))
    L += [");", "", "\tinitial begin"]
    for vec in directed:
        assigns = " ".join(f"{k} <= {widths[k]}'d{int(v)};" for k, v in vec.items())
        L.append(f"\t\t@(posedge clk) begin {assigns} end")
    if ins and n_random:
        rand = " ".join(f"{p['name']} <= {_random(p['width'])};" for p in ins)
        L.append(f"\t\trepeat({n_random}) @(posedge clk, negedge clk) begin {rand} end")
    else:
        L.append(f"\t\trepeat({max(n_random, 10)}) @(posedge clk);")
    L += ["\t\t#1 $finish;", "\tend", "", "endmodule", "", "module tb();", ""]

    # stats and signals
    L.append("\ttypedef struct packed {")
    L += ["\t\tint errors;", "\t\tint errortime;"]
    for o in outs:
        L += [f"\t\tint errors_{o['name']};", f"\t\tint errortime_{o['name']};"]
    L += ["", "\t\tint clocks;", "\t} stats;", "", "\tstats stats1;", ""]
    L += ["\treg clk=0;", "\tinitial forever", "\t\t#5 clk = ~clk;", ""]
    for p in ins:
        L.append(f"\tlogic {_range(p['width'])}{p['name']};")
    for o in outs:
        L.append(f"\tlogic {_range(o['width'])}{o['name']}_ref;")
        L.append(f"\tlogic {_range(o['width'])}{o['name']}_dut;")

    dumped = ["stim1.clk", "tb_mismatch"] + (["clk"] if clocked else []) + [p["name"] for p in ins]
    dumped += [f"{o['name']}{s}" for o in outs for s in ("_ref", "_dut")]
    L += ["", "\tinitial begin", '\t\t$dumpfile("wave.vcd");', f"\t\t$dumpvars(1, {', '.join(dumped)});", "\tend", ""]
    L += ["\twire tb_match;", "\twire tb_mismatch = ~tb_match;", ""]

    in_conns = [f".{p['name']}" for p in ins]
    clk_conn = [".clk"] if clocked else []
    L.append("\tstimulus_gen stim1 (" + ", ".join([".clk"] + in_conns) + ");")
    ref_conns = clk_conn + in_conns + [f".{o['name']}({o['name']}_ref)" for o in outs]
    dut_conns = clk_conn + in_conns + [f".{o['name']}({o['name']}_dut)" for o in outs]
    L.append("\tRefModule good1 (" + ", ".join(ref_conns) + ");")
    L.append("\tTopModule top_module1 (" + ", ".join(dut_conns) + ");")
    L.append("")

    # report, in the exact format grader.py and VerilogEval expect
    L.append("\tfinal begin")
    for o in outs:
        n = o["name"]
        L.append(f'\t\tif (stats1.errors_{n}) $display("Hint: Output \'%s\' has %0d mismatches. '
                 f'First mismatch occurred at time %0d.", "{n}", stats1.errors_{n}, stats1.errortime_{n});')
        L.append(f'\t\telse $display("Hint: Output \'%s\' has no mismatches.", "{n}");')
    L.append('\t\t$display("Hint: Total mismatched samples is %1d out of %1d samples\\n", stats1.errors, stats1.clocks);')
    L.append('\t\t$display("Simulation finished at %0d ps", $time);')
    L.append('\t\t$display("Mismatches: %1d in %1d samples", stats1.errors, stats1.clocks);')
    L += ["\tend", ""]

    # X in the reference matches anything; X in the design only matches X.
    refs = "{ " + ", ".join(f"{o['name']}_ref" for o in outs) + " }"
    duts = "{ " + ", ".join(f"{o['name']}_dut" for o in outs) + " }"
    L.append(f"\tassign tb_match = ( {refs} === ( {refs} ^ {duts} ^ {refs} ) );")
    L += ["", "\talways @(posedge clk, negedge clk) begin", "\t\tstats1.clocks++;",
          "\t\tif (!tb_match) begin", "\t\t\tif (stats1.errors == 0) stats1.errortime = $time;",
          "\t\t\tstats1.errors++;", "\t\tend"]
    for o in outs:
        n = o["name"]
        L.append(f"\t\tif ({n}_ref !== ( {n}_ref ^ {n}_dut ^ {n}_ref ))")
        L.append(f"\t\tbegin if (stats1.errors_{n} == 0) stats1.errortime_{n} = $time;")
        L.append(f"\t\t\tstats1.errors_{n} = stats1.errors_{n}+1'b1; end")
    L += ["\tend", "", "\tinitial begin", "\t\t#1000000", '\t\t$display("TIMEOUT");', "\t\t$finish();",
          "\tend", "", "endmodule", ""]
    return "\n".join(L)

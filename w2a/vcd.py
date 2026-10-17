"""Minimal VCD reader for the waveforms the VerilogEval testbenches dump.

The testbench dumps the inputs, `<out>_ref`, `<out>_dut`, `clk` and
`tb_mismatch` at the top level of `tb`. That is enough to rebuild the exact
input that produced the first mismatch, without asking a model.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field


@dataclass
class Signal:
    name: str
    width: int
    times: list[int] = field(default_factory=list)
    values: list[str] = field(default_factory=list)

    def at(self, t: int, *, before: bool = False) -> str | None:
        """Value at time t; with before=True, the value just before t."""
        idx = (bisect_left if before else bisect_right)(self.times, t) - 1
        return self.values[idx] if idx >= 0 else None


def parse(text: str) -> dict[str, Signal]:
    by_id: dict[str, list[Signal]] = {}
    signals: dict[str, Signal] = {}
    depth = 0
    t = 0
    tokens = iter(text.split())
    for tok in tokens:
        if tok in ("$date", "$version", "$timescale", "$comment"):
            while next(tokens) != "$end":
                pass
        elif tok == "$scope":
            depth += 1
        elif tok == "$upscope":
            depth -= 1
        elif tok == "$var":
            _kind, width, ident, name = next(tokens), next(tokens), next(tokens), next(tokens)
            while next(tokens) != "$end":
                pass
            # Keep the testbench's top-level signals. Some testbenches dump the
            # clock only as stim1.clk, one scope down; take it as the clock.
            if name not in signals and (depth == 1 or name == "clk"):
                signals[name] = Signal(name, int(width))
            if name in signals and (depth == 1 or name == "clk"):
                by_id.setdefault(ident, []).append(signals[name])
        elif tok.startswith("#"):
            t = int(tok[1:])
        elif tok[0] in "bBrR":
            value, ident = tok[1:], next(tokens)
            _record(by_id.get(ident, ()), t, value.lower())
        elif tok[0] in "01xzXZ" and len(tok) > 1:
            _record(by_id.get(tok[1:], ()), t, tok[0].lower())
    return signals


def _record(sigs, t: int, value: str) -> None:
    for sig in sigs:
        width = sig.width
        if len(value) < width:  # VCD drops leading zeros; x/z extend themselves
            pad = value[0] if value[0] in "xz" else "0"
            value = pad * (width - len(value)) + value
        if sig.times and sig.times[-1] == t:
            sig.values[-1] = value
        else:
            sig.times.append(t)
            sig.values.append(value)


def to_int(value: str | None) -> int | None:
    if value is None or any(c in value for c in "xz"):
        return None
    try:
        return int(value, 2)
    except ValueError:
        return None


def clock_edges(signals: dict[str, Signal], until: int) -> list[int]:
    clk = signals.get("clk")
    if clk is None:
        return []
    return [t for t in clk.times[: bisect_right(clk.times, until)] if t > 0]


def snapshot(signals: dict[str, Signal], t: int, *, before: bool) -> dict:
    """Split the dumped signals at time t into inputs and expected/actual outputs."""
    inputs, outputs = {}, {}
    for name, sig in signals.items():
        if name in ("clk", "tb_mismatch", "tb_match"):
            continue
        if name.endswith("_ref") or name.endswith("_dut"):
            base, which = name[:-4], ("expected" if name.endswith("_ref") else "got")
            outputs.setdefault(base, {"width": sig.width})[which] = sig.at(t, before=before)
        else:
            inputs[name] = {"width": sig.width, "value": sig.at(t, before=before)}
    return {"time": t, "inputs": inputs, "outputs": outputs}


def counterexample(signals: dict[str, Signal], t: int) -> dict | None:
    """The sample the testbench flagged at time t.

    The testbench checks on each clock edge while the stimulus updates with
    non-blocking assignments on the same edge, so the values it compared are
    the ones just before t. Fall back to the values at t if those disagree.
    """
    for before in (True, False):
        snap = snapshot(signals, t, before=before)
        wrong = [o for o, v in snap["outputs"].items() if v.get("expected") != v.get("got")]
        if wrong:
            snap["mismatched_outputs"] = sorted(wrong)
            return snap
    return None


def history(signals: dict[str, Signal], t: int, edges: int = 6) -> list[dict]:
    """The last few sampled points up to and including time t, for waveform display."""
    times = clock_edges(signals, t)[-edges:]
    return [snapshot(signals, et, before=True) for et in times]

"""Parse ANSI-style module headers such as
`module top_module(input [31:0] a, input [31:0] b, input sub, output [31:0] sum)`."""

import re

from . import safety

_HEADER = re.compile(r"\bmodule\s+(\w+)\s*(?:#\s*\(.*?\)\s*)?\((.*?)\)\s*;?", re.S)


def parse_header(text: str, module: str | None = None) -> tuple[str, list[dict]]:
    """Return (module name, ports). Each port is {name, dir, width}.

    A port without its own direction inherits the previous one, as in
    `input a, b`. Widths must be numeric ranges.
    """
    code = safety.strip_comments_and_strings(text)
    for m in _HEADER.finditer(code):
        if module and m.group(1) != module:
            continue
        ports, direction, width = [], None, 1
        for item in (s.strip() for s in m.group(2).split(",")):
            if not item:
                continue
            d = re.match(r"(input|output|inout)\b\s*(?:wire|reg|logic)?\s*(?:signed\s*)?(\[\s*\d+\s*:\s*\d+\s*\])?\s*(\w+)$", item)
            if d:
                direction = d.group(1)
                width = _width(d.group(2))
                name = d.group(3)
            elif re.fullmatch(r"\w+", item) and direction:
                name = item
            else:
                raise ValueError(f"cannot parse port declaration {item!r}")
            ports.append({"name": name, "dir": direction, "width": width})
        return m.group(1), ports
    raise ValueError(f"no module header found{' for ' + module if module else ''}")


def _width(rng: str | None) -> int:
    if not rng:
        return 1
    hi, lo = map(int, re.findall(r"\d+", rng))
    return abs(hi - lo) + 1


def interface(ports: list[dict], clocked: bool) -> dict:
    """Testbench interface for tbgen: the clock is driven by the testbench, not the stimulus."""
    ins = [{"name": p["name"], "width": p["width"]} for p in ports if p["dir"] == "input" and not (clocked and p["name"] == "clk")]
    outs = [{"name": p["name"], "width": p["width"]} for p in ports if p["dir"] == "output"]
    return {"inputs": ins, "outputs": outs, "clock": clocked}


def module_names(src: str) -> list[str]:
    return re.findall(r"\bmodule\s+(\w+)", safety.strip_comments_and_strings(src))

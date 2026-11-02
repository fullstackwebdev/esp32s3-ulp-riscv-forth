#!/usr/bin/env python3
"""Ask the BOARD which of a file's names already exist, before any of them is defined.

    python3 tools/namecheck.py --port /dev/ttyUSB1 file.fs [file.fs ...]

WHY: `tools/hashcheck.py` compares against `resident_names.txt`, which holds 109 names while the baked kernel has
more, so it reports "clean" for names the chip will refuse - measured: `TP`, `SB`, `T` and `XT` were all called
clean and all refused on the board. The machine itself is the authority, and `' NAME .` costs one line.

Exit 0 = every name is free, 1 = at least one is taken (listed), 2 = the port did not answer.
GUARDRAIL: judge the LAST line of the reply: a free name answers `NAME?`, a taken one answers `<xt> ok`. A name with
a digit in it (RD2) breaks any parser that just looks for numbers - `RD2?` contains a '2'.
"""
import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from devio import Dev  # noqa: E402


def names(path):
    out = []
    text = pathlib.Path(path).read_text(errors="replace")
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("\\") or not s:
            continue
        m = re.match(r":\s+(\S+)", s) or re.match(r"CREATE\s+(\S+)", s) or \
            re.match(r"\S+\s+CONSTANT\s+(\S+)", s)
        if m:
            out.append(m.group(1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB1")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    d = Dev(port=a.port)
    d.reset()                                   # a reset also proves the dictionary is fresh
    taken = []
    for f in a.files:
        for n in names(f):
            d.cmd("0 .", timeout=5.0, allow_error=True)
            rep = d.cmd(f"' {n} .", timeout=6.0, allow_error=True)
            last = [s.strip() for s in rep.strip().splitlines() if s.strip()][-1]
            if last != f"{n}?":
                taken.append((f, n, last))
    if taken:
        for f, n, last in taken:
            print(f"{pathlib.Path(f).name}: `{n}` is already on the machine (reply {last!r})")
        print(f"namecheck: {len(taken)} taken name(s) - rename them before loading")
        return 1
    print(f"namecheck: all names free on {a.port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

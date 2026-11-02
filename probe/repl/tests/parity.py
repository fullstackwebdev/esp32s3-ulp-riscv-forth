#!/usr/bin/env python3
"""parity.py — run ONE program with ONE key sequence on BOTH backends and diff the two 24x80 grids cell by cell.

    tests/parity.py ../../examples/tui_min.fs --entry RUN --keys jj
    tests/parity.py <phase.fs> --keys jjq --block 96

This is the tool that turns "works on host, fails on device" into a test. docs/26's G4 gate is exactly this: the same
test against /dev/ttyACM1, and a gate fails when host != device. Before it existed, the difference was found by an
operator looking at a screen, i.e. after the app shipped.

The backend code lives in tools/screen.py and is IMPORTED, never re-derived: two implementations of "read a frame"
would agree with each other and say nothing about the machine (R6/R9).

Exit codes: 0 the grids are identical; 1 a cell differs; 2 a harness/program failure (named, with the reason);
3 the stream carried a code screen.py cannot interpret; 4 SKIPPED - no board answered, so parity was NOT proven.

GUARDRAIL: a skip is exit 4, never 0. "No board" and "the two machines agree" are different facts, and the failure
this project keeps paying for is a green run that measured nothing (tests/run.sh's 0 PASS 0 FAIL, R9).

GUARDRAIL: only the KEY SEQUENCE is shared between the backends; the transport is not. The host feeds bytes on stdin
(KEY = getchar(), EOF ends the run), the board gets one keystroke per write into the raw keybox and is released with
`q` afterwards (screen.run_device strips that `q` and the console echo from the stream). Anything else that differs -
timing, idle frames, a KEY? poll - is a real host/device difference and screen.py's header lists the three known ones.
"""
import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import screen                                     # noqa: E402  (tools/screen.py: the grid, the two backends)

ROWS, COLS = screen.ROWS, screen.COLS
DUMP = pathlib.Path(__file__).resolve().parent.parent / ".auto" / "tmp"
CELLS_SHOWN = 20


def report(want, got, bad, program):
    """Say what differs, in the terms a person debugging a screen uses: row, column, cell, then the whole row."""
    rows = sorted({r for r, _, _, _ in bad})
    print(f"PARITY FAILED: {program.name}: {len(bad)} of {ROWS * COLS} cells differ in {len(rows)} of {ROWS} rows")
    for r in rows:
        marks = "".join("^" if want[r][c] != got[r][c] else " " for c in range(COLS))
        n = sum(1 for c in range(COLS) if want[r][c] != got[r][c])
        print(f"\n  row {r + 1:2d}  {n} cell(s) differ")
        print(f"    host   |{want[r]}|")
        print(f"    device |{got[r]}|")
        print(f"    diff   |{marks}|")
    print("\n  first differences (host -> device):")
    for r, c, w, g in bad[:CELLS_SHOWN]:
        print(f"    {screen.describe_cell(r, c, w, g)}")
    if len(bad) > CELLS_SHOWN:
        print(f"    ... {len(bad) - CELLS_SHOWN} more")


def dump(program, host_stream, dev_stream):
    """Keep the raw bytes of a mismatch: the grid loses the escape codes, and the fix usually needs them.

    GUARDRAIL: a cell-level diff says WHERE the two machines disagree, never WHY, and the raw streams are the only
    record of the ordering that produced it (a lost space, a swallowed `\` comment and a dropped out_ring byte all
    read as "a cell differs"). Writing them on the failure path - and only then - turns the next look at this into a
    diff of bytes instead of another board session.
    """
    DUMP.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, data in (("host", host_stream), ("device", dev_stream)):
        p = DUMP / f"parity-{program.stem}.{name}.bin"
        p.write_bytes(data)
        paths.append(str(p.relative_to(DUMP.parent.parent)))
    print(f"\n  raw streams: {'  '.join(paths)}")
    print("  re-render one with: tools/screen.py --grid on the same program, or read these bytes directly")


def main(argv):
    ap = argparse.ArgumentParser(description="run one program on both backends and diff the grids cell by cell")
    ap.add_argument("program", metavar="PROGRAM", help="the .fs source (a phase defines one word and does not run it)")
    ap.add_argument("--entry", metavar="WORD", default=None,
                    help="the word to run after loading (default: the file's name uppercased, docs/26)")
    ap.add_argument("--keys", metavar="STR", default="",
                    help=r"keys to type, in order; \e is ESC (\e[B = Down), \r = Enter")
    ap.add_argument("--block", type=int, default=64, metavar="N", help="first block of the program, default 64")
    ap.add_argument("--host", metavar="BIN", default=str(screen.HOST_APP), help="host engine at device geometry")
    ap.add_argument("--port", default=screen.PORT)
    ap.add_argument("--timeout", type=float, default=60.0, help="host run cap in seconds (default 60)")
    a = ap.parse_args(argv)

    program = pathlib.Path(a.program)
    if not program.exists():
        raise screen.HarnessError(f"no such program: {program}")
    entry = a.entry or program.stem.upper()
    keys = screen.decode_keys(a.keys)
    # One block preflight for both backends, with cli.py's own splitter: it is the check that refuses here what the
    # board would refuse three steps later (see screen.check_blocks).
    screen.check_blocks(program, a.block)

    print(f"parity: {program.name} entry {entry} keys {keys!r} block {a.block}")
    host_stream = screen.run_host(program, entry, keys, binary=a.host, timeout=a.timeout)
    host = screen.Terminal()
    host.feed(host_stream)
    print(f"  host:   {len(host_stream)} B of drawing from {a.host}")

    try:
        dev_stream = screen.run_device(program, entry, keys, first_block=a.block, port=a.port)
    except screen.NoBoard as e:
        print(f"  SKIP    device: {e}", file=sys.stderr)
        print("  parity NOT proven: the host grid above was not compared against a board")
        return 4
    device = screen.Terminal()
    device.feed(dev_stream)
    print(f"  device: {len(dev_stream)} B of drawing from {a.port}")

    for tag, term in (("host", host), ("device", device)):
        for w in dict.fromkeys(term.warnings):
            print(f"  WARNING {tag}: {w}", file=sys.stderr)

    want, got = host.grid.lines(), device.grid.lines()
    bad = screen.diff_grid(want, got)
    if bad:
        report(want, got, bad, program)
        dump(program, host_stream, dev_stream)
        return 1
    print(f"  PARITY ok: {ROWS * COLS} cells identical (host {a.host} == device {a.port})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except screen.NoBoard as e:
        print(f"parity: NO BOARD: {e}", file=sys.stderr)
        sys.exit(4)
    except screen.Uninterpreted as e:
        print(f"parity: {e}", file=sys.stderr)
        sys.exit(3)
    except screen.HarnessError as e:
        print(f"parity: {e}", file=sys.stderr)
        sys.exit(2)

#!/usr/bin/env python3
"""demo.py — show the App Store.

    ./demo.py                the shelf and one app, on the HOST engine (renders correctly today)
    ./demo.py --device       build it on the board and open the shelf (see the F-137 warning below)
    ./demo.py --keys 'jj'    walk the shelf with your own keys

Why the default is the host: a full-screen phase draws ~1 KB in one burst and the ULP's output ring is 128 B, so on the
chip the HEAD of the frame is lost and the screen appears shifted up by several rows (F-137, open). The host runs the same
`src/uforth.c`, the same geometry and the same `src/image.h`, so what it draws is what the chip draws - the difference is
only how the bytes reach the screen.

GUARDRAIL: this script orchestrates the tools that already exist (`tools/screen.py` for a grid, `cli.py --appstore` for the
board build) and re-implements neither. An earlier wave grew a second terminal driver beside the first and the two then
disagreed about what a frame is; a demo is not a reason to fork a reader.

GUARDRAIL: every frame shown here comes from a program that was actually compiled and run - no canned art. If a grid comes
back wrong the script says so and exits non-zero, because a demo that prints a pretty picture regardless of the machine is
worse than no demo.
"""
import argparse
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent          # probe/repl
REPO = HERE.parents[1]
SCREEN = HERE / "tools" / "screen.py"
HOST_APP = HERE / "artifacts" / "host_app"
REGISTRY = REPO / "examples" / "apps" / "registry.fs"
LAUNCHER = REPO / "examples" / "appstore.fs"


def need(path, build_hint):
    if not path.exists():
        sys.exit(f"demo: {path} is missing - {build_hint}")
    return path


def grid(program, entry, keys, content=()):
    """Run one phase on the host engine and return its 70x24 grid as text. Raises on any harness refusal."""
    cmd = [sys.executable, str(SCREEN), str(program),
           "--prelude", str(REGISTRY), "--prelude", str(LAUNCHER),
           "--host", str(HOST_APP), "--entry", entry, "--keys", keys, "--grid"]
    for app in content:
        cmd += ["--content", app]
    # GUARDRAIL: the harness writes its own progress (compile lines, "seeded N blocks") to stderr, and the grid to stdout -
    # mixing them would put a compile line inside the picture. Capture separately and only show stderr when it failed.
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=str(HERE))
    if out.returncode:
        sys.stderr.write(out.stderr)
        sys.exit(f"demo: {program.name} refused to run (exit {out.returncode})")
    return out.stdout.rstrip("\n")


# the grid is 70 columns wide, plus the two-space indent below
NEED_COLS = 72


def terminal_width():
    return shutil.get_terminal_size((80, 24)).columns


def show(title, text, crop=True):
    cols = terminal_width()
    print(f"\n  {title}\n")
    if crop and cols < NEED_COLS:
        # GUARDRAIL: a row is 70 columns and this print adds two, so a terminal narrower than 72 WRAPS every line - and a
        # wrapped card row interleaves with the row below it, which reads as "the demo is broken" rather than "the window
        # is narrow". Measured from the operator's own paste (`rw/cl` merged into `0/0`, borders split across lines).
        # Say the requirement out loud and cut the rows to fit instead of letting the terminal do it silently.
        print(f"  ! this terminal is {cols} columns; the grid is {NEED_COLS}. Rows are cut at the right edge -")
        print(f"    widen the window (or run `./demo.py | less -S`) to see the cards in full.\n")
        for line in text.splitlines():
            body = ("  " + line.rstrip())
            print(body[:cols - 1] + ("\u203a" if len(body) > cols - 1 else ""))
        return
    for line in text.splitlines():
        print("  " + line.rstrip())


def main(argv):
    ap = argparse.ArgumentParser(description="show the App Store (host by default, board with --device)")
    ap.add_argument("--device", action="store_true", help="build on the board and open the shelf there")
    ap.add_argument("--no-crop", action="store_true", help="never cut rows to the terminal width (for piping)")
    ap.add_argument("--keys", default="jj", help="keys to walk the shelf with (default 'jj' = two cards right)")
    a = ap.parse_args(argv)

    if a.device:
        print("  building the App Store on the board (resident + 5 phases + content) ...")
        rc = subprocess.run([sys.executable, str(REPO / "cli.py"), "--appstore"], cwd=str(REPO))
        print("\n  NOTE: on the chip the frame's head is lost while F-137 is open (128 B output ring against a ~1 KB")
        print("  frame), so the screen will look shifted up. `./demo.py` without --device shows the same build drawn")
        print("  correctly by the host engine.")
        return rc.returncode

    need(HOST_APP, "build it with probe/repl/tests/build_host_app.sh")
    need(SCREEN, "it is part of the tree")
    shelf = REPO / "examples" / "apps" / "shelf" / "shelf1.fs"
    mail = REPO / "examples" / "apps" / "mail" / "mail1.fs"

    crop = not a.no_crop
    show("App Store, initial", grid(shelf, "RUNSHELF", ""), crop)
    show(f"App Store, after {a.keys!r}", grid(shelf, "RUNSHELF", a.keys), crop)
    # the app screens are their own phases, so they are shown by running them; the SWITCH that would take you from a card
    # to its app is the dispatcher's job and needs the board (it adopts a descriptor through the block layer).
    show("MAIL, inbox (the same phase the shelf opens with Enter)", grid(mail, "MAIL1", "", content=("mail",)), crop)
    show("MAIL, after 'j' then Enter (the selected message)", grid(mail, "MAIL1", "j\r", content=("mail",)), crop)
    print("\n  cards open with Enter on the board; this host run shows each screen as its own frame.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

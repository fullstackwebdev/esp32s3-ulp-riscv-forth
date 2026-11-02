#!/usr/bin/env python3
"""shelf_host.py - the App Store shelf's HOST gate (docs/26 G2): keys in, grid out, cells asserted.

    python3 tests/apps/shelf_host.py            # needs probe/repl/artifacts/host_app

WHY this file exists: the shelf's claims are all cell assertions - "slot 5 is selected after jljk",
"the CALC card shows the accumulator cell", "Enter sets APP and CHAINs to the app's descriptor" - and a
grep for `APP STORE` in a 1 KB frame proves none of them (R12: a green check certifies only what it reads).

GUARDRAIL: the bytes are read through probe/repl/tools/screen.py (its HOST backend, which feeds the engine
at the chip's geometry and expands the message codes), never by running host_app here. A second driver is
how "works in one tool, not the other" starts.

GUARDRAIL: a phase's dictionary is keyed by a 12-bit hash of the NAME (probe/repl/src/uforth.c hash_pad),
so two words that hash alike silently dispatch the wrong one - measured in this very lane: a card-border
word named H1 ran instead of the `XOR` inside the cursor word, and the screen printed a border where a
page cell should have been read. Check 6 keeps that from coming back.
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROBE = ROOT / "probe" / "repl"
SCREEN = PROBE / "tools" / "screen.py"
HOST = PROBE / "artifacts" / "host_app"
PHASE = ROOT / "examples" / "apps" / "shelf" / "shelf1.fs"
REGISTRY = ROOT / "examples" / "apps" / "registry.fs"
LAUNCHER = ROOT / "examples" / "appstore.fs"
COLS = 70

fails = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'' if ok else '  ' + detail}")
    if not ok:
        fails.append(name)


def run(keys, entry="RUNSHELF", seed=None):
    """screen.py's HOST backend on the phase, with the resident preludes in the order the board uploads them.

    GUARDRAIL: a second positional file would land in screen.py's `program` slot, not after it - the driver
    word and anything that follows it travel in `--entry`, which screen.py writes as its own driver file
    (`entry + "\n"`). Passing a .drv as an extra argv is how this test first ran the phase twice.
    """
    cmd = [sys.executable, str(SCREEN), str(PHASE), "--prelude", str(REGISTRY), "--prelude", str(LAUNCHER)]
    if seed:
        cmd += ["--prelude", str(seed)]
    cmd += ["--host", str(HOST), "--entry", entry, "--keys", keys, "--grid"]
    p = subprocess.run(cmd, capture_output=True, timeout=120)
    return p.returncode, p.stdout.decode("latin-1"), p.stderr.decode("latin-1")


def rows(out):
    return out.splitlines()


def frame_cells(grid):
    """The grid's rows, cut at the machine's own width so a ragged 80-column line cannot pass as 70."""
    return [ln[:COLS] for ln in grid]


def main():
    if not HOST.exists():
        print(f"no {HOST} - build it with probe/repl/tests/build_host_app.sh", file=sys.stderr)
        return 2

    # ---- 1. the screen exists at the machine's geometry -------------------------------------------------
    rc, out, err = run("jljk")
    g = rows(out)
    check("renders (screen.py exits 0)", rc == 0, err.strip()[:300])
    check("24 rows of the grid are read", len(g) == 24, f"{len(g)} rows")
    check("row 1 is the inverse title bar", g[0][:9] == "APP STORE", repr(g[0][:20]))
    # GUARDRAIL: the geometry is 70 columns, the launcher's own FILL constant (docs/26). A 71st cell is a
    # ragged edge against the launcher's bar, so the check is on the raw grid, not on the whole 80-wide line.
    check("nothing is drawn past column 70", all(ln[COLS:].strip() == "" for ln in g),
          next((f"row {i + 1}: {ln[COLS:].strip()!r}" for i, ln in enumerate(g) if ln[COLS:].strip()), ""))

    # ---- 2. six cards, two bands, 22 wide ---------------------------------------------------------------
    borders = [i for i, ln in enumerate(g) if "+--------------------+" in ln and "|" not in ln]
    check("four horizontal edges (two bands of 7 rows)", borders == [2, 8, 10, 16], str([i + 1 for i in borders]))
    card_rows = [i for i, ln in enumerate(g) if ln.count("+--------------------+") == 3]
    check("three cards across, both bands", len(card_rows) == 4, str([i + 1 for i in card_rows]))
    titles = {r: [ln for ln in [g[r]]] for r in (3, 11)}
    check("band 1 titles", re.findall(r"\| (\w+)", g[3]) == ["CALC", "SHEET", "MAIL"], repr(g[3][:60]))
    check("band 2 titles + an empty 6th card", re.findall(r"\| (\w+)", g[11]) == ["GOPH", "READ"], repr(g[11][:60]))

    # ---- 3. the cursor cell decides the selected slot, and the keys move it -----------------------------
    slot = {}
    for keys in ("", "j", "jj", "l", "jljk"):
        rc, out, _ = run(keys)
        row1 = rows(out)[0]
        # GUARDRAIL: the slot number is drawn at 1-based column 68 (HDR: `1 68 AT`), so it is index 67;
        # reading the last two cells of the row silently returned 0 and every key check passed for free.
        slot[keys] = int(row1[67:69].strip() or 0)
    # j/k move within the band (a wrap of the column), l/h flip the band: so the slot number is band*3+col+1.
    check("slot 1 with no key", slot[""] == 1, str(slot[""]))
    check("j advances the column (2, then 3)", (slot["j"], slot["jj"]) == (2, 3), str(slot))
    check("l flips the band, same column (slot 4)", slot["l"] == 4, str(slot["l"]))
    check("jljk = band 1, column 1 -> slot 5", slot["jljk"] == 5, str(slot["jljk"]))

    # ---- 4. live values, never placeholders ------------------------------------------------------------
    seed = PHASE.parent / "shelf1.seed.fs"
    seed.write_text("\n".join([f"{v} {c} !" for c, v in (
        ("CALC_ST", 42), ("SHEET_ST", 3), ("MAIL_ST", 6), ("GOPH_ST", 2), ("READ_ST", 5),
        ("CALC_ST 4 +", 7), ("SHEET_ST 4 +", 9), ("READ_ST 4 +", 4))]) + "\n")
    try:
        rc, out, err = run("jljk", seed=seed)
    finally:
        seed.unlink(missing_ok=True)
    g = rows(out)
    values = {"CALC": g[5][3:22].strip(), "SHEET": g[5][26:45].strip(), "MAIL": g[5][49:68].strip(),
              "GOPH": g[13][3:22].strip(), "READ": g[13][26:45].strip()}
    check("CALC shows its two cells (42/7)", values["CALC"] == "42/7", values["CALC"])
    check("SHEET shows row/col (3/9)", values["SHEET"] == "3/9", values["SHEET"])
    check("MAIL shows msg/page (6/0)", values["MAIL"] == "6/0", values["MAIL"])
    check("GOPH shows page/back (2/0)", values["GOPH"] == "2/0", values["GOPH"])
    check("READ shows page/col (5/4)", values["READ"] == "5/4", values["READ"])
    rc, out, _ = run("jljk")
    check("with the cells at boot the cards are 0/0 (not a copy of the seed)",
          rows(out)[5][3:22].strip() == "0/0" and rows(out)[13][26:45].strip() == "0/0",
          f"{rows(out)[5][3:22].strip()!r}")

    # ---- 5. always-on: the cells are the state, and Enter hands the app to the dispatcher ----------------
    driver = ("RUNSHELF\n"
              "SHELF_ST @ . 32 EMIT SHELF_ST 4 + @ . 32 EMIT APP @ . 32 EMIT APP_PG @ . 32 EMIT NXT @ .")
    rc, out, err = run("jl\\r", entry=driver)
    # GUARDRAIL: the driver's output is not a trailing line - it is DRAWN at the cursor the last frame left
    # (row 20, after the footer), so it is a substring of some grid row. `.strip().splitlines()[-1]` read the
    # host block server's boot line instead and the check could never pass.
    got = [ln.strip() for ln in out.splitlines() if "1 1 80 0 80" in ln]
    # GUARDRAIL: 192 is not a magic number - it is read off the frame: after 'j','l' the cells hold cursor=1,
    # page(band)=1; Enter opens slot 4 (band 1 col 1) = READ, whose descriptor is the start of its block range
    # (docs/26: 80-95), so APP=80, APP_PG=0 and CHAIN leaves NXT=80 for the dispatcher.
    check("Enter writes APP/APP_PG and CHAINs (1 1 80 0 80)", len(got) == 1, str(out.strip().splitlines()[-1:]))

    # ---- 6. the 12-bit name hash is injective over the phase's dictionary -------------------------------
    # GUARDRAIL: this is the check that would have caught this lane's real bug (H1 vs the primitive XOR).
    # The machine keeps no names, so the only witness is recomputing djb2/m33 & 0xfff over every name the
    # dictionary will hold: the prims, the baked prelude, the registry, the launcher and the phase.
    def h(name):
        v = 5381
        for ch in name.encode():
            v = (v * 33 + ch) & 0xFFFFFFFF
        return v & 0xFFF

    names = re.findall(r'X\([A-Z0-9_]+,"([^"]+)"', (PROBE / "src" / "p31_prims.inc").read_text())
    for src in (PROBE / "src" / "p39_prelude.fs", REGISTRY, LAUNCHER, PHASE):
        text = re.sub(r"\\.*", "", src.read_text())
        text = re.sub(r"\([^)]*\)", "", text)
        names += re.findall(r"(?:^|\s)(?::|CREATE|CONSTANT|VARIABLE)\s+(\S+)", text)
    seen = {}
    clash = [(k, v, n) for n in names for k in [h(n)] if seen.setdefault(k, n) != n]
    check("no two word names share a 12-bit hash", not clash, str(clash[:3]))

    print(f"\n{'PASS' if not fails else 'FAIL'}  {len(fails)} finding(s)")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())

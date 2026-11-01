#!/usr/bin/env python3
"""cli.py - talk to the Forth machine on the ESP32-S3 ULP through its serial TTY.

    ./cli.py                       interactive Forth REPL
    ./cli.py -i app.fs             upload a program (split into blocks, compiled on the chip) then REPL
    ./cli.py -i app.fs --term RUN  upload, then hand the whole terminal to the program
    ./cli.py --geometry            print the compiler-side constants the board must agree with (no board)

REPL commands (start with a dot, handled here, not by the chip):
    .help              this list
    .term [WORD]       give the terminal to a running program (optional WORD is sent first, e.g. .term RUN)
    .load FILE         upload another program now
    .status            block store state: blocks, erases, wear
    .quit              leave
Anything else is sent to the chip as Forth. Ctrl-C always gives your terminal back.
"""
import argparse
import os
import re
import pathlib
import select
import sys
import runpy
import termios
import time
import tty

ROOT = pathlib.Path(__file__).resolve().parent
PROBE = ROOT / "probe" / "repl"
sys.path.insert(0, str(PROBE / "tools"))
sys.path.insert(0, str(PROBE))

CY, YL, DM, OFF = "\033[36m", "\033[33m", "\033[2m", "\033[0m"
# GUARDRAIL: these three sequences are the whole reason a crashed session can ruin a terminal. Every exit path -
# .term, Ctrl-C, Ctrl-D, an exception, SIGTERM - must emit all three: leave the alternate screen, show the cursor,
# reset colours. Once a terminal is left in the alternate buffer, the operator's shell "disappears".
RESTORE = "\033[?1049l\033[?25h\033[0m"


def say(s="", c=""):
    print(f"{c}{s}{OFF if c else ''}", flush=True)


def port_holders(port):
    """Who else has this tty open. Linux answers in /proc, and "the board is dead" vs "something else holds the cable"
    are different facts with different fixes.

    GUARDRAIL: measured the hard way - a crashed test harness left `cli.py --library` alive on /dev/ttyACM1, and every
    later run spent 21-36 s retrying resets and then said "the board did not come back to a fresh dictionary". That
    message sent me looking at hardware for a bug in a process table.
    """
    try:
        st = os.stat(port)
    except OSError:
        return ""
    me = {os.getpid(), os.getppid()}
    found = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) in me:
            continue
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    s = os.stat(f"/proc/{pid}/fd/{fd}")
                except OSError:
                    continue
                if s.st_ino == st.st_ino and s.st_rdev == st.st_rdev:
                    cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode("latin-1").strip()
                    found.append(f"pid {pid} ({cmd[:60]})")
                    break
        except OSError:
            continue
    return ", ".join(found)


def connect(port, settle):
    from devio import Dev
    # GUARDRAIL: ask who holds the port BEFORE any reset. This check used to sit after `pulse_reset`, which - now that a
    # pulse is verified and falls back - spent ~9 s resetting a port it could never reach, and only then named the other
    # process. Measured: a stale `cli.py` from a previous run made every later run pay 9 s and then refuse.
    holders = port_holders(port)
    if holders:
        say(f"  {port} is already open by: {holders}", YL)
        say("  close that program (or kill it) and run this again.", YL)
        return None
    try:
        dev = Dev(port=port)
        # GUARDRAIL: go straight to the esptool reset. On this board the DTR/RTS pulse is a no-op (USB-Serial-JTAG
        # emulates the modem bits, F-126), so paying for a pulse first bought 1.3 s and a fallback every single run.
        dev.reset(settle=0.25)
    except Exception:
        say(f"no board on {port}.", YL)
        say("  * cable in?  * Linux: sudo usermod -aG dialout $USER (log out, in)", YL)
        say("  * other port: PORT=/dev/ttyACM0 ./cli.py", YL)
        return None
    # GUARDRAIL: after a hard reset the ULP may still be booting, and .bss carries the previous image's block state
    # (the RTC "already booted" magic survives a reset). Both showed up as a FIRST command that timed out or answered
    # ERR_STACK/ERR_DIRTY. Retry, then clear the block latch by name.
    # GUARDRAIL: a reset that did not happen must not be accepted as one. Measured, twice: an RTS pulse silently does
    # nothing, the still-running ULP answers politely, and the next upload compiles on top of the previous app - the
    # dictionary runs out mid-upload and the operator sees a wall of ERR_DICT from block 70 on, which looks like the app
    # being too big. Assert a FRESH machine (baked HERE ~786 and >900 B free), and fall back to esptool's slower reset.
    #
    # GUARDRAIL: this loop used to burn 21-36 s and then blame the board. The holder check is above (a held port is a
    # different fact from a non-fresh dictionary, with a different fix), the probe timeout is 1.5 s because a live ULP
    # answers `HERE .` in 40 ms - a longer timeout only hides a dead one - and `!LINE` goes first, because a previous
    # session may leave the board in raw mode where a probe is read as a keystroke.
    fresh, answered, here, free = False, False, 0, 0
    for attempt in range(4):
        if attempt:
            say(f"  retrying reset ({attempt + 1}/4)...", DM)
            dev.reset(settle=0.3)
        try:
            dev.cmd("!LINE", timeout=1.5, allow_error=True)
            here = dev.num("HERE .", timeout=1.5)
            free = dev.num("LATEST HERE - .", timeout=1.5)
        except Exception:
            continue
        answered = True
        if here < 900 and free > 900:
            fresh = True
            break
    if not fresh:
        if answered:
            say(f"  the dictionary is not fresh (HERE {here}, {free} B free).", YL)
            say("  unplug the USB cable, plug it back in, and run this again.", YL)
        else:
            say("  the board did not answer at all.", YL)
            say(f"  * is another program holding the port?  (fuser -v {port})", YL)
            say("  * cable in?  * Linux: sudo usermod -aG dialout $USER (log out, in)", YL)
        return None
    dev.cmd("0 2 BLKXFER", timeout=6.0, allow_error=True)
    # GUARDRAIL: prove the block server ANSWERS before handing the port to a caller. The freshness probe above talks to
    # the ULP, and the ULP is armed ~500 ms before the main core creates the block task - so `connect()` could return
    # while `blocksrv` did not exist yet, and the first block operation then collided with its start. Measured as
    # `ERR_CRC` on the first `LOAD` after reset in 3 of 12 trials (and as the boot banner `blocksrv up` arriving in the
    # middle of that very reply), with the block log showing the task servicing its first requests at ms 1760 - i.e.
    # AFTER the host had already asked. A readiness check has to test the capability, not a banner (the banner is printed
    # once and is consumed by this function's own earlier drains): read block 0 and require status 0.
    served = False
    for _ in range(25):
        # GUARDRAIL: `BLKXFER` leaves ( addr st ), so `DROP .` prints the ADDRESS (2476) and every caller read that as the
        # status - it "failed" forever while the server was answering perfectly (measured: `2476 ok` four times in a row).
        # `SWAP DROP .` is the idiom tests/adopt_sum.py already used.
        rep = dev.cmd("0 0 BLKXFER SWAP DROP .", timeout=8.0, allow_error=True)
        # GUARDRAIL: the block task's own debug lines carry numbers (blk=%u buf=%u sum=%u) and arrive AFTER the status
        # while the ULP is still booting, so "the last number in the reply" was the transfer address 2476, not a status.
        # Strip the server's diagnostics before parsing, exactly as tests/loader_tests.py does for the same reason.
        kept = "\n".join(ln for ln in rep.splitlines()
                         if not any(p in ln for p in ("info:", "blksrv", "dump:", "load:", "poke:", "seed:", "store:")))
        nums = [int(m) for m in re.findall(r"-?\d+", kept.split("ok")[0])]
        if nums and nums[-1] == 0:
            served = True
            break
        time.sleep(0.1)
    if not served:
        say("  the block server never answered a read (status "
            f"{nums[-1] if nums else 'none'}).", YL)
        say("  the main core did not start its block task - check the boot banner for 'blocksrv FAILED'.", YL)
        dev.close()
        return None
    say(f"  connected: fresh dictionary, {free} B free, block server answering.", DM)
    return dev


def upload(dev, path, first_block, staging=None):
    """Split a Forth program into legal blocks, write them, and ask the chip to compile them.

    `staging` is the number of blocks the caller's range can hold (docs/26: the staging range is 120..127 = 8). A real
    phase source is 20-30 blocks, so it is uploaded in passes: seed the first `staging` blocks, LOAD them in file order,
    then reuse the same blocks for the next pass. That is safe precisely because a block is a self-contained line with an
    empty stack at its start (`run_line: sp = 0`, R10) - the same property `fsplit` guarantees when it splits. Without
    this, every App Store phase was refused with "27 blocks from 120 would pass block 127".
    """
    from fsplit import split_defs
    src = pathlib.Path(path).read_text()
    bs = split_defs(src, 92)
    if first_block + min(len(bs), staging or len(bs)) > 128:
        raise RuntimeError(f"{len(bs)} blocks from {first_block} would pass block 127, which the server refuses")
    t0 = time.time()
    bad = {}
    win = staging or len(bs)
    for base in range(0, len(bs), win):
        chunk = bs[base:base + win]
        missing = dev.seed_many([(first_block + i, b) for i, b in enumerate(chunk)])
        if missing:
            raise RuntimeError(f"block(s) {missing} did not acknowledge - is the cable loose?")
        for i in range(len(chunk)):
            # GUARDRAIL: `settle=0.004` because a LOAD answers with exactly one line. The 20 ms default per block was 0.7 s
            # of the build's 4.8 s, spent waiting for a second line that never comes.
            rep = dev.cmd(f"{first_block + i} LOAD", timeout=25.0, allow_error=True, settle=0.004)
            errs = [l.strip() for l in rep.splitlines() if l.strip().endswith("?") or "ERR_" in l]
            if errs:
                bad[base + i + 1] = errs[0]     # 1-based SOURCE block: the store block numbers repeat across passes
            # GUARDRAIL: report EVERY block, not every tenth. Seven seconds of silence is what "really slow" feels like,
            # and the operator cannot tell a slow build from a wedged board - measured complaint, twice.
            sys.stdout.write(f"\r  compiling {base + i + 1}/{len(bs)} blocks"); sys.stdout.flush()
    sys.stdout.write("\r" + " " * 40 + "\r")
    say(f"  {path}: {len(bs)} blocks, {time.time() - t0:.1f} s", DM)
    for blk, err in bad.items():
        say(f"  block {blk}: {err}", YL)          # named, never swallowed
    return len(bs), bad


LIB_FIRST, DEMO_FIRST = 70, 30          # launcher source; phase source is reused for every build
# The App Store build (docs/26). (name, source, descriptor block, entry word). The descriptor numbers are the table's:
# 8 calc1, 16 calc2, 24 sheet, 32 mail, 40 gopher, 48 reader, 56 the shelf itself. The shelf OPENs with 8/24/32/40/48
# (slot -> descriptor, verified by printing OPND for slots 0..4) and every phase returns with `SHELF CHAIN`, i.e. 56.
APPSTORE = [
    ("calc",   "examples/apps/calc/calc1.fs",    8,  "CALC1"),
    ("tape",   "examples/apps/calc/calc2.fs",    16, "CALC2"),
    ("mail",   "examples/apps/mail/mail1.fs",    32, "MAIL1"),
    ("reader", "examples/apps/reader/read1.fs",  48, "READ1"),
    ("shelf",  "examples/apps/shelf/shelf1.fs",  56, "RUNSHELF"),
]
APPSTORE_RESIDENT = ["examples/apps/registry.fs", "examples/appstore.fs"]
STAGING, STAGING_BLOCKS = 120, 8         # docs/26: the source of ANY phase is staged here, 8 blocks per pass
# GUARDRAIL: every descriptor a CARD can open, whether or not this build produces it. The shelf maps slot -> descriptor
# (8 calc, 24 sheet, 32 mail, 40 gopher, 48 reader) and a card for an app that was never built would otherwise adopt
# whatever an older build left in that block - measured as "GOPHER crashes and won't let me exit", adopt answering
# BK_RANGE (-5) because the stale header named a block outside the store. Anything here without a build gets blanked.
CARD_DESCS = (8, 24, 32, 40, 48)
# The window is DECLARED, not inherited. It is what is left above the seal after the resident launcher and its headers,
# and every phase must fit in it. Measured drift in one afternoon: 346 -> 290 -> 237 B as the launcher grew, and at
# 237 B a working 222 B program stopped fitting - which read as "the demo broke", not as "the budget moved". A floor
# makes that a build error with numbers.
# GUARDRAIL: the floor is the App Store figure (docs/26), not a tuned one. Re-measured while the dispatcher was
# folded into the launcher: 346 -> 290 -> 237 -> 254 B, a 92 B move in one afternoon with no test noticing, and the
# dispatcher-only launcher (`--library` on a fresh board) now leaves a 1 193 B window per phase. 1 000 B is that
# baseline minus the 193 B of launcher growth a floor is meant to allow. Do NOT re-tune this by feel: a change here
# must carry a fresh `./cli.py --library` window measurement, because a floor picked from memory is the drift.
# GUARDRAIL: two floors, because they answer two different questions. MIN_WINDOW is what ANY launcher must leave - it is
# the end of the drift (346 -> 290 -> 237 -> 254 B) and a real regression if it falls further. APP_WINDOW is the App Store
# contract (docs/26): the shelf era needs ~1 000 B of phase window, and the shipping menu launcher does NOT meet it (it
# leaves 254 B on purpose, with three phases that fit). Applying the App Store floor to the menu launcher refused a build
# that works - measured immediately: `./cli.py --library` refused, and programs.py + tui_cli.py both failed on a launcher
# that is correct for its own design.
MIN_WINDOW = 200
APP_WINDOW = 1000
# ---- the store budget, from the numbers that own it ------------------------------------------------
# GUARDRAIL: BLOCK and DESC_HEADER are copies of numbers defined on the BOARD side (`BLKSZ` in
# probe/repl/src/ulp_repl.c, the descriptor prelude in main/repl_main.c's `#d`). They exist here so the build can
# REFUSE without a dump; `--geometry` prints the compiler-side values that must equal `#u`/`#i` on the board.
BLOCK = 128                     # probe/repl/src/ulp_repl.c: BLKSZ
DESC_HEADER = 20                # main/repl_main.c `#d`: descriptor v2 header packed in front of the payload
STORE_BLOCKS = 128              # main/repl_main.c: BLK_N (128 blocks x 128 B)
# A PROGRAM is a chain of PHASES. One phase = one image = at most the window above the seal. The first phase's
# descriptor is what the launcher is handed; every later one is reached by the phase itself calling `CHAIN`.
LIBRARY = (
    ("bars", (("examples/demo_bars.fs", 40, "RUNB"),)),
    ("gauge", (("examples/gauge1.fs", 60, "GAUGE1"), ("examples/gauge2.fs", 62, "GAUGE2"),
               ("examples/gauge3.fs", 64, "GAUGE3"))),
)


def check_chains(root):
    """Every phase's `N CHAIN` literal must match the descriptor map in LIBRARY.

    GUARDRAIL: a phase names its successor as a LITERAL (`62 CHAIN`) while the descriptor map lives in this file, so a
    stale chain is silent: the phase jumps to a block holding a different image (or an empty one) and the only symptom
    is the wrong thing drawn. Cheap to check, and it needs no board - the map was edited twice while this feature was
    written and the phases had to be re-pointed by hand each time.
    """
    for program, phases in LIBRARY:
        for i, (path, desc, _entry) in enumerate(phases):
            src = (root / path).read_text()
            want = phases[i + 1][1] if i + 1 < len(phases) else 0
            m = re.search(r"(\d+)\s+CHAIN\b", src)
            got = int(m.group(1)) if m else None
            # GUARDRAIL: the LAST phase of a program may omit `CHAIN` altogether - the dispatcher cleared NXT before
            # EXECUTE, so "say nothing" and "chain to 0" mean the same thing. Treating absent as a mismatch refused
            # every single-phase program (measured on demo_bars.fs).
            if got is None and want == 0:
                continue
            if got != want:
                say(f"  {path}: chains to {got!r}, the map says {want} - fix the phase or LIBRARY", YL)
                return False
    return True


def geometry(root):
    """The compiler-side constants the board must agree with: [(name, bytes, where)], or None after saying why.

    GUARDRAIL: read the defines, never retype them. E-079 was an image baked at one MEMSZ and an engine compiled at
    another; a hand-kept copy in this file is the same drift one level up, and it would make `--geometry` agree with
    itself instead of with the board. `#u` prints blk off/sz and the ring sizes, `#i` the store's blocks x B - those
    are the rows these are diffed against.
    GUARDRAIL: refuse loudly on a missing or renamed define. A default (say 128 for the block size) prints a
    geometry that looks right for the wrong reason and hides the rename - the silent default this wave bans.
    """
    def define(path, name):
        p = root / path
        if not p.exists():
            say(f"  {path} is missing - --geometry cannot read {name}, refusing", YL)
            return None
        m = re.search(rf"^#define\s+{name}\s+(\d+)u?\b", p.read_text(), re.M)
        if not m:
            say(f"  {path} no longer defines {name} - --geometry would be a guess, refusing", YL)
            return None
        return int(m.group(1))

    memsz = define("probe/repl/src/ulp_repl.c", "MEMSZ")
    blksz = define("probe/repl/src/ulp_repl.c", "BLKSZ")
    cmd = define("probe/repl/src/ulp_repl.c", "CMD_SIZE")
    pool = define("probe/repl/main/repl_main.c", "ULP_POOL_BUDGET")
    if None in (memsz, blksz, cmd, pool):
        return None
    ulp = (root / "probe/repl/src/ulp_repl.c").read_text()
    eng = (root / "probe/repl/src/uforth.c").read_text()
    # GUARDRAIL: header top and transfer offset are DERIVED (MEMSZ - BLKSZ), so the derivation is asserted against
    # the engine's own source. If someone re-shapes HDRTOP/BLKADR this must say so, not print a number that used to
    # be right - a geometry check that agrees with yesterday is worse than none.
    if "#define P33_BLOCK 1" not in ulp:
        say("  ulp_repl.c builds without P33_BLOCK - there is no block window, so header top and transfer offset are"
            " not the shipping layout, refusing", YL)
        return None
    for line in ("#define HDRTOP BLKADR", "#define BLKADR (MEMSZ - BLKSZ)"):
        if line not in eng:
            say(f"  uforth.c no longer carries `{line}` - refusing rather than guessing the derivation", YL)
            return None
    top = memsz - blksz                 # HDRTOP = BLKADR with blocks on: the header area stops at the block window
    return [
        ("memory size",     memsz, "probe/repl/src/ulp_repl.c: MEMSZ"),
        ("header top",      top,   "uforth.c: HDRTOP = BLKADR = MEMSZ - BLKSZ"),
        ("transfer offset", top,   "uforth.c: BLKADR = MEMSZ - BLKSZ  (#u: blk off)"),
        ("block size",      blksz, "probe/repl/src/ulp_repl.c: BLKSZ  (#u: blk sz, #i: blocks x B)"),
        ("cmd ring",        cmd,   "probe/repl/src/ulp_repl.c: CMD_SIZE  (#u: cmd ... B)"),
        ("pool budget",     pool,  "probe/repl/main/repl_main.c: ULP_POOL_BUDGET (flash_safe.sh refuses over it)"),
    ]


def print_geometry(root):
    """Print the geometry table. Returns the rows, or None when it cannot be read (nothing is guessed)."""
    rows = geometry(root)
    if rows is None:
        return None
    say("  geometry: the compiler side - diff these against the board's `#u` and `#i`", CY)
    for name, value, where in rows:
        say(f"    {name:<16}{value:>6} B  {where}", DM)
    return rows


def registry_cells(root):
    """(cells, bytes) declared in examples/apps/registry.fs, or None when the file is not there.

    GUARDRAIL: these are RESIDENT state below the seal, so every cell costs 4 B of the window each phase is built
    against - they belong in the budget, not in a comment. A missing registry.fs refuses: counting zero cells by
    default would report a 20 B smaller footprint than the machine actually carries.
    """
    path = root / "examples/apps/registry.fs"
    if not path.exists():
        return None
    cells = 0
    for ln in path.read_text().splitlines():
        cells += ln.split("\\", 1)[0].count(",")      # a `\` comment is not state
    return cells, cells * 4


def budget(built, window, launcher_blocks, cells):
    """Print the phase budget table and return True; False means REFUSED (the reason is already on screen).

    GUARDRAIL: the image is code + headers read back FROM THE BOARD, and a phase's blocks are the descriptor's real
    payload (`20 + image bytes`), never the source length. Source length was the number that looked fine while a
    phase failed to adopt: the descriptor carries the headers too, so a 1 100 B source can still be a 10-block
    image. GUARDRAIL: the refusal is the point of the table - a phase over the window, or a set over 128 blocks, has
    to fail the BUILD with a name and a number, not the board with an error nobody connects to the budget.
    """
    say(f"  budget: {len(built)} phase(s) against a {window} B window (floor {MIN_WINDOW} B); a phase's blocks are"
        f" source + ceil(({DESC_HEADER} + image) / {BLOCK})", CY)
    say(f"    {'program':<9}{'phase':>6}{'image':>8}{'window':>8}{'headroom':>10}{'blocks':>8}", DM)
    total_code = total_img = total_blocks = 0
    for b in built:
        payload = DESC_HEADER + b["image"]
        desc_blocks = -(-payload // BLOCK)                 # ceil: a partial block is still a block
        phase_blocks = b["blocks"] + desc_blocks
        total_code += b["code"]
        total_img += b["image"]
        total_blocks += phase_blocks
        flag = "" if b["image"] <= window else "  OVER"
        say(f"    {b['program']:<9}{b['phase']:>3}/{b['of']:<2}{b['image']:>8}{window:>8}"
            f"{window - b['image']:>+10}{phase_blocks:>8}{flag}", CY if not flag else YL)
    blocks = launcher_blocks + total_blocks
    say(f"    {'totals':<9}{len(built):>3} phase(s) {total_img:>5} B image, {total_code} B of code, {blocks} block(s)"
        f" of {BLOCK} (launcher {launcher_blocks} + phase source/descriptors {total_blocks}) of {STORE_BLOCKS}", DM)
    say(f"    resident cells: {cells[0]} ({cells[1]} B, examples/apps/registry.fs - state below the seal)", DM)
    for b in built:
        if b["image"] > window:
            say(f"  REFUSED: {b['path']} phase {b['phase']}/{b['of']} is a {b['image']} B image, {b['image'] - window}"
                f" B over the {window} B window - move a feature into another phase (docs/26 G0)", YL)
            return False
    if blocks > STORE_BLOCKS:
        say(f"  REFUSED: the phase set needs {blocks} blocks, the store has {STORE_BLOCKS} - "
            f"{blocks - STORE_BLOCKS} over; split an app or delete a phase (docs/26 block allocation)", YL)
        return False
    return True


def library(dev, root):
    """Build the program library: a resident launcher, then each demo as a behaviour image.

    Returns the built descriptors ({path, desc, cs, ce, entry}), or None after printing why it refused. Callers
    (tests/programs.py, tests/tui_cli.py) assert on the returned values instead of re-deriving them: two copies of
    "what a good image looks like" is how one of them silently stops checking anything (R6).

    GUARDRAIL: order is the whole trick. The launcher is compiled FIRST and sealed, so it stays resident while `BLKXFER`
    op 3 rewinds the dictionary over the demos - code that performs an adopt cannot live in the region it replaces.
    GUARDRAIL: rewind before every demo build. Without it the second demo is compiled on top of the first, the image
    spans both, and adopting it runs whatever happened to be compiled last.
    GUARDRAIL: the rewind is `RW` (the launcher's own `bh @ VH ! bl @ VL !`), NOT `2 OVL`. `OVL` is `( blk -- )`: it
    rewinds AND arms a block as the interpreter's source, so inside a running word it queues a block to be COMPILED
    instead of returning to the seal. It happened to work from the console and is wrong everywhere else.
    """
    if not check_chains(root):
        return None
    here = dev.num("HERE .")
    if here > 900:
        # GUARDRAIL: a library built onto a non-fresh dictionary fails later as `ERR_DICT` in the middle of an upload,
        # which reads like "the app is too big". Refuse here with the reason instead.
        say(f"  the machine already has a program loaded (HERE {here}); reset it first", YL)
        return None
    n, bad = upload(dev, str(root / "examples/menu.fs"), LIB_FIRST)
    if bad:
        return None
    # GUARDRAIL: capture the launcher's block count HERE. The loop below reuses `n` for each phase, so reading it
    # after the builds counts the LAST phase's source and reports a launcher that does not exist.
    launcher_blocks = n
    dev.cmd("SEAL")
    base = dev.num("bh @ .")
    say(f"  launcher sealed at {base} ({n} blocks)", DM)
    # GUARDRAIL: report the window ONCE, before building, and refuse a launcher that leaves the phases too little.
    # `LATEST` here is the SEALED latest (the launcher's header base), so `LATEST - seal` is exactly the space a phase
    # gets - not an estimate. `base` is the seal, read from the machine, so this cannot drift from what SEAL did.
    built = []
    window = dev.num("LATEST .") - base
    say(f"  phase window: {window} B above the seal (launcher {base - 52} B of code + "
        f"{dev.num('LATEST .')} headers)", CY if window >= MIN_WINDOW else YL)
    # GUARDRAIL: `library()` builds the MENU launcher (examples/menu.fs, 254 B window, three phases that fit), so it is
    # held to MIN_WINDOW. APP_WINDOW belongs to the App Store build (examples/appstore.fs), which is a separate path -
    # applying the App Store floor here refused a launcher that is correct for its own design (measured: programs.py and
    # tui_cli.py went red at 254 B).
    floor = MIN_WINDOW
    if window < floor:
        say(f"  the launcher leaves {window} B, under the {floor} B floor for this launcher - move a feature into a phase", YL)
        return None
    for program, phases in LIBRARY:
        for i, (path, desc, entry) in enumerate(phases):
            dev.cmd("RW")                       # back to the seal, so this phase owns the space above it
            n, bad = upload(dev, str(root / path), DEMO_FIRST)
            if bad:
                return None
            cs, ce = dev.num("bh @ ."), dev.num("HERE .")
            hs, he = dev.num("LATEST ."), dev.num("bl @ .")
            ent = dev.num(f"' {entry} .")
            # GUARDRAIL: a stub image is what a failed LOAD leaves behind (measured: 10 B), and EXECUTE then jumps into
            # never-compiled bytes and spins with no error at all. The stub that actually hung the machine was 10 B, and
            # a legitimate demo was once 92 B, so the minimum is 48 B - not the 120 B a phase-sized heuristic guessed.
            if cs != base or ce - cs < 48 or not (cs <= ent < ce):
                say(f"  {path}: code {cs}..{ce} ({ce - cs} B) entry {ent} - not buildable above the seal at {base}", YL)
                return None
            dev.cmd(f"#d {desc} {cs} {ce} {hs} {he} {ent}")
            # GUARDRAIL: `hs` is the phase's LATEST (it grows DOWN) and `he` is the sealed LATEST, so the headers are
            # [hs, he) and the IMAGE is code + headers. The window is `he - base` (measured before the builds): the
            # engine's own rule is that code growing up from the seal and headers growing down must not meet, so
            # `code + hdr > window` is exactly ERR_DICT seen from the host, one build earlier and with numbers.
            hdr = he - hs
            built.append(dict(program=program, phase=i + 1, of=len(phases), path=path, desc=desc,
                              cs=cs, ce=ce, code=ce - cs, hdr=hdr, image=(ce - cs) + hdr, entry=ent, blocks=n))
            say(f"  {path}: {ce - cs} B of code + {hdr} B of headers -> block {desc}, entry {ent}", DM)
    dev.cmd("RW")
    # GUARDRAIL: `built` entries are the SAME dicts tests/programs.py reads; `hdr`/`image` are added, nothing renamed.
    cells = registry_cells(root)
    if cells is None:
        say("  REFUSED: examples/apps/registry.fs is missing - the resident cell budget cannot be counted, and zero"
            " cells is not the truth", YL)
        return None
    if not budget(built, window, launcher_blocks, cells):
        return None
    say(f"  library ready: {len(LIBRARY)} programs; Enter runs one, q returns, q on the menu quits", CY)
    return built


def appstore(dev, root, only=()):
    """Build the App Store: resident + SEAL, then every phase's descriptor, then hand the terminal to the shelf.

    GUARDRAIL: the phases are COMPILED AFTER `SEAL`, never before. The fresh dictionary is 1 366 B and the shelf's image
    alone is 1 021 B, so `resident + phase` overflows the fresh space (measured: ERR_DICT on the host when SEAL was
    omitted). SEAL moves the resident headers down and gives each phase the 1 037 B window that is its real budget.
    GUARDRAIL: descriptors are written with `#d` and then FLUSHED with `#f`. `#d` lands in the flash sector cache, so a
    build that skips the flush looks correct and is gone after a power cycle (lane R measured it).
    """
    win = 0
    for rel in APPSTORE_RESIDENT:
        n, bad = upload(dev, str(root / rel), STAGING, staging=STAGING_BLOCKS)
        if bad:
            say(f"  {rel} did not compile: {bad}", YL)
            return None
    dev.cmd("SEAL", timeout=30.0, allow_error=True)
    win = dev.num("LATEST .") - dev.num("bh @ .")
    say(f"  resident sealed; phase window {win} B", CY)
    built = []
    for name, rel, desc, entry in APPSTORE:
        # GUARDRAIL: the shelf is ALWAYS built, even when the caller names one app. It is the entry point (`RUNSHELF`) and
        # every phase returns to it with `SHELF CHAIN` - so `--appstore mail` without it handed the terminal to a word that
        # did not exist, dropped into the REPL, and looked like the feature was broken. `only` filters the APPS.
        if only and name not in only and name != "shelf":
            continue
        path = root / rel
        # GUARDRAIL: rewind to the seal before EVERY phase. Each phase is compiled into the same window, so without this
        # the previous phase's 900-1000 B are still there: measured on the tape phase as `ESC?`, `IV?`, `HDR?` (words the
        # previous phase had defined, now absent because its definitions were never recorded) and then ERR_DICT for the
        # rest. `RW` is the launcher's own rewind: `bh @ VH ! bl @ VL !`.
        dev.cmd("RW", timeout=5.0, allow_error=True)
        n, bad = upload(dev, str(path), STAGING, staging=STAGING_BLOCKS)
        if bad:
            say(f"  {name}: compile failed: {bad}", YL)
            return None
        cs, ce = dev.num("bh @ ."), dev.num("HERE .")
        hs, he = dev.num("LATEST ."), dev.num("bl @ .")
        ent = dev.num(f"' {entry} .")
        if ent in (0, -1):
            say(f"  {name}: `' {entry}` did not resolve - the phase did not compile", YL)
            return None
        image = (ce - cs) + (he - hs)
        # GUARDRAIL: refuse an over-window image HERE. The device would adopt it and jump past the pasted code (the
        # 41 Hz re-entry), so the build has to be the gate - the same rule cli.budget() applies to the library.
        if image > win:
            say(f"  {name}: {image} B image is {image - win} B over the {win} B window - not building it", YL)
            return None
        rep = dev.cmd(f"#d {desc} {cs} {ce} {hs} {he} {ent}", timeout=20.0, allow_error=True)
        if "REFUSED" in rep or "ERR_" in rep:
            say(f"  {name}: descriptor refused: {rep.strip()[-70:]}", YL)
            return None
        built.append((name, desc, image))
        say(f"  {name:<7} desc {desc:<3} {image:>5} B of {win}  entry {ent}", DM)
    # GUARDRAIL: POISON the descriptor of every app this build did not write. A card can point at a block that still holds
    # an image from an older build (or a different table), and the adopt then either jumps into stale code or fails with
    # BK_RANGE if the stale header names a block outside the store - measured as "GOPHER crashes and won't let me exit",
    # because gopher has no phase yet and block 44 held leftovers. Seeding an EMPTY payload blanks the block (the seeder
    # fills with spaces first), so any later adopt fails the magic check and PICKX returns NOOP instead.
    want = {desc for _n, _r, desc, _e in APPSTORE}
    poisoned = []
    for desc in CARD_DESCS:
        if desc in want and any(d == desc for _n, d, _i in built):
            continue
        dev.seed_many([(desc, "")])
        poisoned.append(str(desc))
    if poisoned:
        dev.cmd("#f", timeout=30.0, allow_error=True)
        say(f"  no phase built - descriptors blanked so those cards refuse cleanly: {', '.join(poisoned)}", DM)
    dev.cmd("#f", timeout=30.0, allow_error=True)
    return built


def term(dev, word=None):
    """Hand the terminal to a Forth program: raw bytes in, everything out, full-screen escapes intact."""
    if word:
        # GUARDRAIL: do NOT wait for a reply here. The program starts drawing immediately, and a waiting read would
        # consume the first frame (measured: the alternate screen was entered and restored with nothing drawn).
        os.write(dev.fd, (word + "\r").encode())
        time.sleep(0.05)
    # GUARDRAIL: !RAW must be sent AFTER the word that starts the program. Sent first, the start word itself would be
    # forwarded as raw bytes and never executed as a line. The CR that ends this line is swallowed by the board. This is
    # also written without waiting, for the reason above: whatever the host prints next belongs on the operator's screen.
    os.write(dev.fd, b"!RAW\r")
    time.sleep(0.1)
    fin = sys.stdin.fileno()
    # GUARDRAIL: a piped stdin is not a terminal, and termios.tcgetattr raises ENOTTY - measured while scripting a
    # Ctrl-C test. Terminal modes are applied only when there is a terminal to apply them to; the byte proxy is identical
    # either way, so scripts and CI can drive a full-screen program too.
    interact = os.isatty(fin)
    old = termios.tcgetattr(fin) if interact else None
    ok = True
    interrupted = False
    try:
        if interact:
            tty.setraw(fin)
        sys.stdout.write("\033[?1049h")           # let the program own a clean alternate screen
        sys.stdout.flush()
        while True:
            r, _, _ = select.select([fin, dev.fd], [], [], 0.2)
            if fin in r:
                b = os.read(fin, 1)
                if os.environ.get("DEBUG"):
                    say(f"  [term] stdin {b!r}", DM)
                if not b:
                    break
                if b == b"\x03":                   # Ctrl-C: always ours, never the program's
                    interrupted = True
                    break
                os.write(dev.fd, b)
            if dev.fd in r:
                try:
                    chunk = os.read(dev.fd, 4096)
                except OSError:
                    break
                os.write(sys.stdout.fileno(), chunk)
                # GUARDRAIL: this break means "the PROGRAM restored the screen". It fired on the very first frame of a
                # working launcher, and the trace below is what shows whether the program or this host exited.
                if os.environ.get("DEBUG"):
                    rest = b"\x1b[?1049l" in chunk
                    say(f"  [term] chunk {len(chunk)}B restore={rest}", DM)
                if b"\x1b[?1049l" in chunk:        # the program restored the screen: it is done
                    break
    finally:
        if old is not None:
            termios.tcsetattr(fin, termios.TCSADRAIN, old)
        sys.stdout.write(RESTORE)
        sys.stdout.flush()
        # GUARDRAIL: `!LINE` has NO REPLY. It switches the host's own line discipline and prints nothing (`raw_mode = 0;
        # rawn = 0; break;` in repl_main.c). Waiting for a marker therefore waited for UNSOLICITED output - the ` ok`
        # the REPL prints for the word that started the program - so it passed whenever that line happened to still be in
        # the buffer and crashed with `devio.Timeout: no reply to '!LINE' within 8.0s` when it had already been consumed.
        # Measured in the operator's terminal as a traceback AFTER a successful build, with the machine fine and the
        # terminal half restored: a cleanup step must never be able to raise. Send it without waiting, then prove the
        # machine is back with a command that DOES answer.
        if interrupted:
            # GUARDRAIL: Ctrl-C stops the PROXY, not the PROGRAM. The machine is inside the app's KEY loop, and once the
            # host stops forwarding raw bytes the app can never return - `!LINE` then answers nothing and the board looks
            # dead (measured: the 8 s timeout this cleanup used to raise, in the operator's terminal).
            # GUARDRAIL: send `q` REPEATEDLY, and stop at the first ` ok`. A program can be nested - the launcher's menu
            # runs a demo, so one `q` leaves the demo and the MENU is still waiting; measured as "no ok" with a single
            # key. The ` ok` is printed when the *line* that started the program finishes, so it is the exact signal
            # that nothing is left running. Stopping there also avoids a stale key: a `q` sent after the app has gone
            # would sit in the keybox and quit the NEXT program on its first poll.
            buf = b""
            for _ in range(3):
                os.write(dev.fd, b"q")
                end = time.time() + 1.0
                while time.time() < end and b"ok" not in buf:
                    r, _, _ = select.select([dev.fd], [], [], 0.1)
                    if r:
                        try:
                            buf += os.read(dev.fd, 4096)
                        except OSError:
                            break
                if b"ok" in buf:
                    break
            if b"ok" not in buf:
                say("  the program did not stop on Ctrl-C - the board needs a reset (unplug/replug).", YL)
                ok = False
        os.write(dev.fd, b"!LINE\r")
        try:
            dev.num("HERE .", timeout=4.0)
        except Exception as e:
            # GUARDRAIL: set a flag, do NOT `return` from `finally`. A return there discards whatever exception brought us
            # here - the exact silent-failure shape this project bans - so the original error would vanish and the
            # operator would be told the board stopped answering instead.
            ok = False
            say(f"  the board stopped answering after the program exited ({type(e).__name__}).", YL)
            say("  unplug the USB cable, plug it back in, and run this again.", YL)
    say("  (back at the line prompt)", DM)
    return ok


def status(dev):
    for ln in dev.cmd("#i", timeout=10.0).splitlines():
        if "info:" in ln:
            say("  " + ln.split("info:", 1)[1].strip(), CY)


def repl(dev, first_block):
    say("  Forth REPL. Lines are limited to 63 characters. .help for commands, .quit to leave.", DM)
    while True:
        try:
            line = input(f"{CY}>{OFF} ")
        except (EOFError, KeyboardInterrupt):
            say()
            return
        s = line.strip()
        if not s:
            continue
        if s in (".quit", ".q", "quit"):
            return
        if s == ".help":
            say("  .term [WORD]  hand the terminal to a program   .load FILE  upload a program", DM)
            say("  .status       block store state                .quit        leave", DM)
            continue
        if s == ".status":
            status(dev)
            continue
        if s.startswith(".term"):
            parts = s.split(None, 1)
            term(dev, parts[1] if len(parts) > 1 else None)
            continue
        if s.startswith(".load"):
            parts = s.split(None, 1)
            if len(parts) < 2:
                say("  usage: .load FILE", YL)
                continue
            try:
                upload(dev, parts[1], first_block)
            except Exception as e:
                say(f"  {e}", YL)
            continue
        if len(s) > 63:
            say(f"  {len(s)} characters - the machine holds 63.", YL)
            continue
        try:
            out = dev.cmd(s, timeout=25.0, allow_error=True)
        except Exception:
            say("  no answer (the machine may be busy or the line was lost)", YL)
            continue
        for ln in out.splitlines():
            if ln.strip() and ln.strip() != s and ln.strip() != "ok":
                print("  " + ln, flush=True)


def main():
    ap = argparse.ArgumentParser(description="Forth REPL and program loader for the ULP machine")
    ap.add_argument("-i", "--include", action="append", default=[], metavar="FILE",
                    help="Forth program to upload and compile (repeatable)")
    ap.add_argument("--term", metavar="WORD", nargs="?", const="RUN", default=None,
                    help="after loading, hand the terminal to the program (default word: RUN)")
    ap.add_argument("--library", action="store_true",
                    help="build the program library (resident launcher + demo images) and run the menu")
    ap.add_argument("--appstore", nargs="*", metavar="APP", default=None,
                    help="build the App Store (docs/26) and open the shelf; a list builds only those apps")
    ap.add_argument("--geometry", action="store_true",
                    help="print the compiler-side constants the board must agree with, then exit (needs no board)")
    ap.add_argument("--repl", action="store_true",
                    help="after --library's app exits, stay in the REPL instead of leaving (it holds the port)")
    ap.add_argument("--block", type=int, default=64, metavar="N", help="first block to use (default 64)")
    ap.add_argument("--port", default=os.environ.get("PORT", "/dev/ttyACM1"))
    ap.add_argument("--settle", type=float, default=1.0, help="seconds to wait after reset (default 1.0)")
    a = ap.parse_args()
    if a.library and a.include:
        ap.error("--library builds its own sources; do not combine it with -i")
    # GUARDRAIL: --geometry answers from the SOURCE TREE, so it must return before connect(). A geometry check that
    # needs the board it is supposed to be checked against is unusable exactly when it is wanted (a wrong image).
    if a.geometry:
        return 0 if print_geometry(ROOT) is not None else 1

    dev = connect(a.port, a.settle)
    if not dev:
        return 2
    try:
        blk = a.block
        failed = False
        if a.appstore is not None:
            root = pathlib.Path(__file__).resolve().parent
            # GUARDRAIL: content first, and only for the apps being built. A content phase that reads an unseeded block
            # draws the store's padding (spaces on the chip, the fake server's pattern on the host) and looks broken
            # rather than empty - measured while wiring this command.
            apps = a.appstore or [n for n, _r, _d, _e in APPSTORE if n in ("mail", "reader", "gopher")]
            if built := appstore(dev, root, only=set(a.appstore or ())):
                seeded = [x for x in apps if x in ("mail", "reader", "gopher")]
                if seeded:
                    # GUARDRAIL: seed_pages computes its own ROOT from __file__, so running it through runpy gets the
                    # same page arithmetic the device seeder uses - no second copy of "which block is page 2".
                    rc = runpy.run_path(str(root / "tools" / "seed_pages.py"))
                    for app_name in seeded:
                        for _p, blk, text in rc["pages"](app_name):
                            dev.seed_many([(blk, text)])
                    dev.cmd("#f", timeout=30.0, allow_error=True)
                    say(f"  content seeded: {', '.join(seeded)}", DM)
                # the shelf is the entry point: it OPENs an app with slot -> descriptor and returns via SHELF (56)
                # GUARDRAIL: enter through the DISPATCHER (`56 GO` = the shelf's descriptor), not `RUNSHELF`. The shelf
                # and every app are phases: a phase sets NXT and RETURNS, and the loop that adopts the next descriptor
                # lives in `SWITCH`. Calling RUNSHELF directly ran the shelf with nothing dispatching - `Enter` set NXT
                # and the shelf exited into the REPL, and an app's `q` (`SHELF CHAIN`) set NXT=56 with nobody to adopt it,
                # so "q does not go back". Measured by the operator: entering worked, returning never did.
                if a.term is None:
                    a.term = "56 GO"
            else:
                return 1
        if a.library:
            root = pathlib.Path(__file__).resolve().parent
            if not library(dev, root):
                return 1
            # GUARDRAIL: `--term`'s default (const) is `RUN`, and the launcher has no such word - the menu's entry is
            # `RUNP`. Left as RUN, the terminal was handed over and the machine answered `RUN?` into an invisible
            # screen: the tool looked hung on its own menu. `--library` therefore RUNS the menu unless a word is given.
            if a.term is None or a.term == "RUN":
                a.term = "RUNP"
        for path in a.include:
            n, bad = upload(dev, path, blk)
            blk += n
            failed = failed or bool(bad)
        if failed:
            # GUARDRAIL: do not start the program after a failed compile. The word it needs is missing, so --term would
            # show an empty screen with no explanation - and the operator would blame the app rather than the upload.
            say("  upload had errors - fix them above, then run again.", YL)
            return 1
        if a.term is not None:
            if not term(dev, a.term):
                return 3
            # GUARDRAIL: `--library` RUNS the library; when the app exits, the run is over. Dropping into the REPL left a
            # live process holding /dev/ttyACM1 for as long as the terminal stayed open, so the NEXT `./cli.py --library`
            # had to be told "already open by pid ...". Measured: the operator's second run paid a 9 s reset attempt and
            # then refused. Staying is available, explicitly: `--repl`.
            if a.library and not a.repl:
                return 0
        repl(dev, blk)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write(RESTORE)                 # never leave the terminal in a strange state
        sys.stdout.flush()
        dev.close()


if __name__ == "__main__":
    sys.exit(main())

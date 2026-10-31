#!/usr/bin/env python3
"""device_ceiling.py — the MEASURED store-bound ceiling on the chip.

Seeds window-sized phases (several blocks of source each) and escalates until the store runs out, reporting the
last phase that loaded and compiled. The stop is real here: the next phase needs blocks past 128.

GUARDRAIL: the host seeder PADS each block with spaces before writing the payload. Writing only the payload leaves
the rest of the block holding a previous seed's bytes; LOAD then compiles the new text, trips over the stale tail,
errors the line and REWINDS the phase - measured as a phase whose own definitions vanished (Z6?) and reproduced as
`: ZZ 42 . ;` in block 8 + `ZZ` in block 9 answering ZZ?.
GUARDRAIL: both comment kinds are stripped before chunking: `\\` swallows the rest of a block (no line structure)
and `(` consumes to `)` so a 128-byte cut inside `( -- )` eats real code.
GUARDRAIL: every seed line is verified and retried; fire-and-forget silently dropped blocks.
"""
import os, re, select, sys, termios, time, pathlib

EXPECTED = 516      # a full phase compiles to this on both host and chip (tests/ceiling.sh)
TOL = 40            # accept +-40 B for a different dictionary shape on the device

PORT = "/dev/ttyACM1"
FIRST = 8


def strip_all(text):
    text = re.sub(r"\\.*", "", text)
    text = re.sub(r"\([^)]*\)", "", text)
    return " ".join(text.split())


def chunk(text, size=128):
    # GUARDRAIL: cut ONLY at interpret-state boundaries (tools/fsplit.py), never mid-definition. A block boundary
    # is not a line boundary: if a `:` definition is still open when the block ends, the machine is in COMPILE
    # state, so the next `N LOAD` is COMPILED into the open definition instead of executed - the remaining blocks
    # are never loaded, no error is raised and LATEST never moves. Measured on the chip (block 10 -> S2?, blocks
    # 11/12 -> ERR_STACK) and traced on the host (last tokens `10 LOAD 11 LOAD ...` all with ST=1, refusals 0).
    sys.path.insert(0, "tools")
    from fsplit import split_defs
    return split_defs(text, size)


def open_port():
    fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY)
    a = termios.tcgetattr(fd); a[0]=0; a[1]=0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL; a[3]=0
    a[4]=a[5]=termios.B115200; a[6][termios.VMIN]=0; a[6][termios.VTIME]=0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd


def drain(fd, quiet=0.30, cap=6.0):
    buf=b""; end=time.time()+cap; last=time.time()
    while time.time()<end:
        r,_,_=select.select([fd],[],[],0.05)
        if r:
            c=os.read(fd,4096)
            if c: buf+=c; last=time.time()
        elif time.time()-last>quiet: break
    return buf.decode("ascii","replace")


def line(fd, s, quiet=0.30, cap=6.0):
    os.write(fd, s.encode()+b"\r")
    return drain(fd, quiet, cap)


def nums(out):
    return [int(x) for x in out.replace("\r"," ").replace("\n"," ").split() if x.isdigit()]


def main():
    phases = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    # GUARDRAIL: the deliberate-failure mode must exist, or no check in this file has ever been shown to fail.
    skip_block = int(sys.argv[2]) if len(sys.argv) > 2 else -1
    chunks = chunk(strip_all(pathlib.Path("tests/ph1.fsx").read_text()))
    per = len(chunks)
    print(f"phase source -> {per} blocks each")
    # GUARDRAIL: HARD-RESET before seeding. Without it the previous run's SEALed, rewound dictionary is still in
    # RAM, so the phase's own definitions collide and the transcript carries a `?` that has nothing to do with this
    # run - measured: the same 8-block phase passes clean after a reset and "fails" without one.
    import subprocess
    subprocess.run(["python3", "-m", "esptool", "--port", PORT, "--after", "hard_reset", "chip_id"],
                   capture_output=True)
    time.sleep(2.0)
    fd = open_port(); time.sleep(1.2); drain(fd, 0.8)
    line(fd, "0 BLOCK CONSTANT W")
    line(fd, ": BLKBLANK 0 BEGIN DUP 128 < WHILE 32 OVER W + C! 1 + REPEAT DROP ;")
    line(fd, "2 BLOCK DROP BLKBLANK UPDATE SAVE DROP")
    line(fd, "SEAL")
    sealed = nums(line(fd, "HERE .", 0.6))[-1]
    print(f"sealed HERE = {sealed}")

    seeded = 0; high = 0; total = 0
    for p in range(phases):
        base = FIRST + p * per
        if base + per > 128:
            print(f"  stop: phase {p+1} needs blocks {base}..{base+per-1}, past the 128-block store")
            break
        for k, ch in enumerate(chunks):
            if skip_block == base + k:       # deliberate-failure mode: leave this block unseeded
                print(f"  (skipping block {base+k} on purpose)")
                continue
            ok = False
            for _ in range(3):
                out = line(fd, f"#b {base+k} {ch.encode().hex()}", 0.25, 3.0)
                if f"seed: block {base+k} <-" in out: ok = True; break
            if not ok:
                print(f"  stop: seed of block {base+k} not acknowledged"); break
            seeded += 1
        line(fd, "2 OVL", 0.8)
        # GUARDRAIL: ONE LOAD PER LINE. With the deferred source switch, the rest of the CURRENT line is consumed
        # before the armed block runs, so `8 LOAD 9 LOAD` arms 9 before 8's text has been read - block 8 is skipped
        # and the phase assembles from fragments. Measured on the chip: loading the seven blocks one per line
        # compiles the whole phase; loading them six-per-line fails with IDX? at block 12.
        out = ""
        for k in range(per):
            out += line(fd, f"{base+k} LOAD", 1.1)
        # GUARDRAIL: three checks, all of which must pass; a size>0 test alone counts PARTIAL phases as successes.
        # An earlier version accepted any phase that compiled anything, and reported 17 "phases" of 70 B each where
        # a full one is ~516 B - i.e. it turned a failing run into a passing one. Never relax a check to get green.
        size = nums(line(fd, "HERE .", 0.5))[-1] - sealed
        if "?" in out.replace("ok", "") or "ERR_" in out:
            print(f"  stop: phase {p+1} transcript has an error: {out.strip()[-50:]!r}"); break
        if abs(size - EXPECTED) > TOL:
            print(f"  stop: phase {p+1} compiled {size} B, expected {EXPECTED}+-{TOL} (partial assembly)"); break
        total += size; high = p + 1
        print(f"  phase {p+1:2d}: {size:4d} B   (blocks {base}..{base+per-1})")
    print(f"  HIGH SCORE (device, measured): {high} phases, {total} B compiled, {seeded} blocks seeded")
    os.close(fd)
    return 0 if high >= 3 else 1


sys.exit(main())

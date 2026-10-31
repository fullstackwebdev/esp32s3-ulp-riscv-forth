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

PORT = "/dev/ttyACM1"
FIRST = 8


def strip_all(text):
    text = re.sub(r"\\.*", "", text)
    text = re.sub(r"\([^)]*\)", "", text)
    return " ".join(text.split())


def chunk(text, size=128):
    out = []; i = 0
    while i < len(text):
        e = min(i + size, len(text))
        if e < len(text):
            c = text.rfind(" ", i + 1, e)
            if c > i:
                e = c + 1
        out.append(text[i:e]); i = e
    return out


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
    chunks = chunk(strip_all(pathlib.Path("tests/ph1.fsx").read_text()))
    per = len(chunks)
    print(f"phase source -> {per} blocks each")
    fd = open_port(); time.sleep(1.0); drain(fd, 0.6)
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
            ok = False
            for _ in range(3):
                out = line(fd, f"#b {base+k} {ch.encode().hex()}", 0.25, 3.0)
                if f"seed: block {base+k} <-" in out: ok = True; break
            if not ok:
                print(f"  stop: seed of block {base+k} not acknowledged"); break
            seeded += 1
        line(fd, "2 OVL", 0.8)
        out = ""
        parts = [f"{base+k} LOAD" for k in range(per)]
        for i in range(0, len(parts), 6):
            out += line(fd, " ".join(parts[i:i+6]), 0.9)
        if "?" in out.replace("ok",""):
            print(f"  stop: phase {p+1} failed to load: {out.strip()[-40:]!r}"); break
        size = nums(line(fd, "HERE .", 0.5))[-1] - sealed
        if size <= 0:
            print(f"  stop: phase {p+1} compiled nothing"); break
        total += size; high = p + 1
        print(f"  phase {p+1:2d}: {size:4d} B   (blocks {base}..{base+per-1})")
    print(f"  HIGH SCORE (device, measured): {high} phases, {total} B compiled, {seeded} blocks seeded")
    os.close(fd)
    return 0 if high >= 3 else 1


sys.exit(main())

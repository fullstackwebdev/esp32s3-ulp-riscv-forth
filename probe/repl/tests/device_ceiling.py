#!/usr/bin/env python3
"""device_ceiling.py — the MEASURED ceiling escalation, on the chip.

The host probe stops on a COMPUTED store bound because each phase is measured in a fresh process. Here the store is
real: phases are seeded into blocks (through the host's fast `#b <block> <hex>` path, one UART line per block) and
then loaded on the ULP by successive LOADs, escalating until a load fails. The last phase that loads and compiles
is the high score, and it is store-bound for real.

GUARDRAIL: a phase's source is cut at NEWLINES, never at a fixed 128-byte boundary. Successive LOADs concatenate
blocks into one token stream, so a cut mid-token splices a word across two blocks (measured earlier as `ETER?` from
LITERAL).
GUARDRAIL: the rewind between phases is `2 OVL` (block 2, blanked first), not a second load: phases must not
accumulate in the overlay area, or the dictionary fills and a resident word vanishes.
"""
import os, select, sys, termios, time, pathlib

PORT = "/dev/ttyACM1"
HERE0 = None

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

def strip_comments(text):
    """Drop backslash comments and join to one line.

    GUARDRAIL: a block has no line structure - blk_refill maps newlines to spaces - so a single `\\` comment
    swallows the rest of the BLOCK, not the rest of the line. Measured on the device: phase 1 failed with IDX?
    because its first block was entirely a comment. The host generator already learned this; this was the same
    lesson in a new script.
    """
    out = []
    for line in text.splitlines():
        cut = line.find("\\")
        out.append((line if cut < 0 else line[:cut]).rstrip())
    return " ".join(x for x in out if x)


def chunk_at_spaces(text, size=128):
    out = []; i = 0
    while i < len(text):
        end = min(i + size, len(text))
        if end < len(text):
            cut = text.rfind(" ", i + 1, end)
            if cut > i:
                end = cut + 1
        out.append(text[i:end]); i = end
    return out

def main():
    phases = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    src = pathlib.Path("tests/ph1.fsx").read_text()
    chunks = chunk_at_spaces(strip_comments(src))
    blocks_per_phase = len(chunks)
    print(f"phase source {len(src)} B -> {blocks_per_phase} blocks each")

    fd = open_port(); time.sleep(1.0); drain(fd, 0.6)
    # blank block 2 (the rewind target) the ordinary way, so OVL 2 compiles nothing
    line(fd, "0 BLOCK CONSTANT W")
    line(fd, ": BLKBLANK 0 BEGIN DUP 128 < WHILE 32 OVER W + C! 1 + REPEAT DROP ;")
    line(fd, "2 BLOCK DROP BLKBLANK UPDATE SAVE DROP")

    seeded = []
    for p in range(phases):
        base = 8 + p * blocks_per_phase
        for k, chunk in enumerate(chunks):
            if base + k >= 128:
                break
            hexs = chunk.encode().hex()
            out = line(fd, f"#b {base+k} {hexs}", quiet=0.10, cap=2.0)
            if "REJECTED" in out:
                print("  seed rejected:", out.strip()); return 2
            seeded.append(base+k)
    print(f"seeded {len(seeded)} blocks")

    line(fd, "SEAL")
    h0 = line(fd, "HERE .", quiet=0.5).replace("HERE .","").replace("\r"," ").replace("\n"," ").split()
    base_here = int([x for x in h0 if x.isdigit()][-1])
    print(f"sealed HERE = {base_here}")

    high = 0; total = 0
    for p in range(phases):
        base = 8 + p * blocks_per_phase
        if base + blocks_per_phase > 128:
            print(f"  stop: phase {p+1} needs blocks {base}..{base+blocks_per_phase-1}, past the 128-block store")
            break
        line(fd, "2 OVL", quiet=0.6)
        loads = " ".join(f"{base+k} LOAD" for k in range(blocks_per_phase))
        # six LOADs per line keeps the line under the chip's TIBSZ
        parts = [f"{base+k} LOAD" for k in range(blocks_per_phase)]
        out = ""
        for i in range(0, len(parts), 6):
            out += line(fd, " ".join(parts[i:i+6]), quiet=0.8)
        if "?" in out or "ERR_" in out:
            print(f"  stop: phase {p+1} failed to load: {out.strip()[-40:]!r}")
            break
        h = line(fd, "HERE .", quiet=0.5)
        digits = [x for x in h.replace("HERE .","").split() if x.isdigit()]
        if not digits:
            print(f"  stop: phase {p+1} produced no HERE"); break
        size = int(digits[-1]) - base_here
        total += size; high = p + 1
        print(f"  phase {p+1:2d}: {size:4d} B compiled")
    print(f"  HIGH SCORE (device): {high} phases, {total} B compiled")
    os.close(fd)
    return 0

sys.exit(main())

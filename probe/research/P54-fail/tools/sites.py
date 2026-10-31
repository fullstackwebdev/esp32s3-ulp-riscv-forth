#!/usr/bin/env python3
"""sites.py — price every err()/msg() call site in one ELF, instruction by instruction.

  ./tools/sites.py out/dbg.elf            # per source line: instruction count and bytes
  ./tools/sites.py out/dbg.elf --calls    # a window around every call to pl_emit/err
  ./tools/sites.py out/dbg.elf --table    # one row per message site: code, argument bytes, call bytes

Method: disassemble, map every instruction to a source line with addr2line, then print, per line, the
instructions whose DWARF line is that line and their byte sizes. Nothing here estimates: the per-site
number is the sum of encoded instruction lengths that the compiler attributed to the statement.

GUARDRAIL: the listing must come from a -g twin whose .text sha256 equals the shipping image, or the
line attribution describes a build nobody priced — tools/disasm.sh exists because of exactly that.
GUARDRAIL: sum instruction LENGTHS from the disassembly, not (next_addr - addr) of a symbol: err() and
msg() are static and msg() is inlined, so there is no msg symbol to read a size from and `nm -S` on it
prints nothing (a silent zero).
GUARDRAIL: addr2line output is one LINE per address and can carry ' (discriminator 1)'; never
whitespace-split it, or every discriminator line becomes a second bogus token and every per-address
lookup silently shifts by one.
"""
import re
import subprocess
import sys

BIN = "/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin/"
elf = sys.argv[1]
verbose = sys.argv[2:] if len(sys.argv) > 2 else []

dis = subprocess.run([BIN + "riscv32-esp-elf-objdump", "-d", "--no-show-raw-insn", elf],
                     capture_output=True, text=True, check=True).stdout
insns = []          # [addr, bytes, text]
for line in dis.splitlines():
    m = re.match(r"^\s+([0-9a-f]+):\t(.*)$", line)
    if m:
        insns.append([int(m.group(1), 16), 0, m.group(2).strip()])
for i, ins in enumerate(insns):
    nxt = insns[i + 1][0] if i + 1 < len(insns) else ins[0] + 4
    ins[1] = nxt - ins[0]

at = {ins[0]: k for k, ins in enumerate(insns)}
addrs = [f"{ins[0]:x}" for ins in insns]
out = subprocess.run([BIN + "riscv32-esp-elf-addr2line", "-e", elf] + addrs,
                     capture_output=True, text=True, check=True).stdout.splitlines()
assert len(out) == len(insns), f"addr2line gave {len(out)} lines for {len(insns)} instructions"

sites = {}
locs = []
for ins, loc in zip(insns, out):
    # keep the basename and drop the discriminator suffix, which is not part of the source line
    loc = re.sub(r"\s*\(discriminator \d+\)$", "", loc).split("/")[-1]
    locs.append(loc)
    sites.setdefault(loc, []).append(ins)

if "--table" in verbose:
    # One row per site: the `li a0,<code>` that names the message plus the transfer that follows it, or a
    # bare `jal <err>` (err() takes no code). GUARDRAIL: the argument load and the call are counted
    # TOGETHER, in encoded bytes — a site priced as "just the call" reads 2 B and hides the 4 B that
    # actually put the code in a0, which is two thirds of what a message site costs.
    tot = 0
    for i, (a, b, t) in enumerate(insns):
        m = re.match(r"li\s+a0,(\d+)$", t)
        if m and 129 <= int(m.group(1)) <= 144:
            # GUARDRAIL: the transfer is NOT always the next instruction — at uforth.c:818 the compiler
            # interleaves the two stack resets (`sb`/`sh`) between `li a0,137` and the `jal pl_emit`, so a
            # strictly-adjacent scan loses that site and the total silently drops by 8 B. Look ahead four
            # instructions; the unrelated stores in between are not charged to the message (they are the
            # site's own work and would exist without it).
            nxt = (0, 0, "")
            for k in range(i + 1, min(i + 5, len(insns))):
                if re.search(r"<pl_emit>|^j\s", insns[k][2]):
                    nxt = insns[k]
                    break
            if not nxt[2]:
                continue
            size = b + nxt[1]
            # the transfer may be a direct call, or a jump to a tail the compiler merged 6 cases onto
            # (GUARDRAIL: skipping the `j tail` form silently under-counts by 36 B — half the sites
            # here reach pl_emit through one shared `jal`, which IS the shared tail shape (c) asks for)
            how = "call"
            if "pl_emit" not in nxt[2]:
                jm = re.match(r"j\s+([0-9a-f]+)", nxt[2])
                if not jm or "pl_emit" not in insns[at[int(jm.group(1), 16)] + 0][2]:
                    continue
                how = f"j->{int(jm.group(1), 16):04x}"
            tot += size
            print(f"msg  0x{a:04x} code=0x{int(m.group(1)):02x} li={b} + {how}={nxt[1]} = {size}  {locs[i]}")
        elif re.search(r"jal\s+\S+\s+<err>", t):
            tot += b
            print(f"err  0x{a:04x} call={b}  {locs[i]}")
    print(f"TOTAL {tot} B in {len([1 for a,b,t in insns if re.search(r'<pl_emit>|<err>', t)])} transfer instructions")
    sys.exit(0)

if "--calls" in verbose:
    # GUARDRAIL: msg() is inlined, so its `li a0,code` is attributed to msg's own source line and the
    # errf store to the caller's — read both in one window or every site looks cheaper than it is.
    for i, (a, b, t) in enumerate(insns):
        if re.search(r"jal\s+\S+\s+<(pl_emit|err)>", t):
            print(f"---- call at {a:04x} ({t})")
            for j in range(max(0, i - 3), min(len(insns), i + 4)):
                mark = ">>" if j == i else "  "
                print(f" {mark} {insns[j][0]:04x} +{insns[j][1]}  {locs[j]:20s} {insns[j][2]}")
    sys.exit(0)

def key(loc):
    f, _, rest = loc.partition(":")
    n = re.match(r"\d+", rest)
    return (f, int(n.group(0)) if n else 0)

total = 0
for loc in sorted(sites, key=key):
    n = len(sites[loc])
    size = sum(i[1] for i in sites[loc])
    total += size
    print(f"{loc:22s} insns={n:3d} bytes={size:4d}")
    if loc in verbose:
        for a, b, t in sites[loc]:
            print(f"        {a:04x} +{b}  {t}")
print(f"TOTAL attributed {total} of {sum(i[1] for i in insns)} insn bytes")

#!/usr/bin/env python3
"""P24: per-group dictionary bytes (with/without headers) and working-set page sets.

Walks the header chain of the image the host build actually produced (img_last.h), so the
with-headers and headerless columns are measured, not extrapolated. Groups are the five .fs files in
load order; the entry count of each group is counted from the source, and the walk order is checked
against it (the layer is the last thing compiled, so its entries are contiguous at the end).

GUARDRAIL: the header link is 2 bytes wide in this engine (P02 widened tokens, not links) and W@ was
trimmed from the 40, so the link has to be rebuilt from two C@ here as well.
"""
import pathlib, re, sys

root = pathlib.Path(__file__).resolve().parent
GROUPS = ["os_tasks.fs", "os_events.fs", "os_repl.fs", "os_introspect.fs", "os_device.fs"]

txt = (root / "img_last.h").read_text()
body = txt[txt.index("{") + 1:txt.rindex("}")]
mem = bytes(int(x, 16) for x in re.findall(r"0x([0-9a-f]{2})", body))
rd8 = lambda a: mem[a]
rd16 = lambda a: mem[a] | mem[a + 1] << 8
rd32 = lambda a: mem[a] | mem[a + 1] << 8 | mem[a + 2] << 16 | mem[a + 3] << 24

here, latest = rd32(4), rd32(8)
entries = []
a = latest
while a:
    n = rd8(a + 2) & 31
    name = bytes(mem[a + 3:a + 3 + n]).decode()
    cf = (a + 3 + n + 3) & ~3
    entries.append({"h": a, "n": n, "name": name, "cf": cf, "imm": rd8(a + 2) >> 7})
    a = rd16(a)
entries.sort(key=lambda e: e["h"])
for i, e in enumerate(entries):
    end = entries[i + 1]["h"] if i + 1 < len(entries) else here
    e["end"] = end
    e["hdr"] = e["cf"] - e["h"]                 # link + flags|len + name + pad
    e["used"] = e["end"] - e["cf"]              # code field + body

NB = 78                                          # boot_min.fs definitions (P22)
layer = entries[NB:]
counts = []
for g in GROUPS:
    src = (root / g).read_text().splitlines()
    c = 0
    for ln in src:
        s = ln.split("\\")[0]
        if re.match(r"^:\s", s) or re.search(r"\bCONSTANT\s+\S+", s) or \
           re.search(r"\bCREATE\s+\S+", s) or re.search(r"\bVARIABLE\s+\S+", s):
            c += 1
    counts.append(c)
if sum(counts) != len(layer):
    print(f"WARNING: source count {counts} = {sum(counts)} != walked {len(layer)}", file=sys.stderr)

print(f"boot layer: {NB} definitions, {entries[NB-1]['end']} B")
print(f"layer: {len(layer)} definitions, {here - entries[NB-1]['end']} B\n")
print(f"{'group':16}{'defs':>6}{'with hdrs':>11}{'hdrs':>8}{'headerless':>12}{'B/def':>8}{'hdr/def':>9}")
tot = dict(d=0, w=0, h=0, hl=0, hd=0)
i = 0
gstart = {}
for g, c in zip(GROUPS, counts):
    sel = layer[i:i + c]
    w = sum(e["used"] + e["hdr"] for e in sel)
    hd = sum(e["hdr"] for e in sel)
    hl = w - hd
    gstart[g] = (sel, w, hd, hl)
    print(f"{g:16}{c:>6}{w:>11}{hd:>8}{hl:>12}{w/c:>8.1f}{hd/c:>9.1f}")
    tot["d"] += c; tot["w"] += w; tot["h"] += hd; tot["hl"] += hl
    i += c
print(f"{'total':16}{tot['d']:>6}{tot['w']:>11}{tot['h']:>8}{tot['hl']:>12}"
      f"{tot['w']/tot['d']:>8.1f}{tot['h']/tot['d']:>9.1f}")
print(f"\nbytes per definition: with headers {tot['w']/tot['d']:.1f}, "
      f"headerless {tot['hl']/tot['d']:.1f}  (P02 32-bit ratio was 39.2 / 28)")

byname = {e["name"]: e for e in entries}


def pages(names, extra_ranges=()):
    """Distinct 512 B pages touched by these words plus their own data ranges."""
    out = set()
    for nm in names:
        e = byname[nm]
        lo, hi = e["cf"], e["end"]      # code field + body incl. inline tokens/literals
        for p in range(lo // 512, (hi - 1) // 512 + 1):
            out.add(p)
    for lo, hi in extra_ranges:
        for p in range(lo // 512, (hi - 1) // 512 + 1):
            out.add(p)
    return sorted(out)


def var(name):
    e = byname[name]
    return (e["cf"], e["end"])


idle_code = ["TICK+", "WAKE-1", "WAKE-ALL", "NEXT-TASK", "YIELD", "WAKE-MASK",
             "EV-GPIO-DO", "POLL-EVENTS"]
idle_data = [var(n) for n in ["EV-H", "EV-T", "EV-N", "EA", "EN", "TASK-POOL", "RUNQ", "CUR",
                              "TICK", "TMP", "WM", "GPIOMASK", "GPIOXT"]]
idle = pages(idle_code, idle_data)

line_code = ["SLEEP-TICKS", "YIELD", "NEXT-TASK", "WAKE-ALL", "WAKE-1", "TICK+", "T-STATE!",
             "TASKS", ".S", ".", "U.", ".DIGIT", "POLL-EVENTS", "WAKE-MASK", "EV-GPIO-DO",
             "EMIT"]
line_data = idle_data + [var("DIAG")]
line = pages(line_code, line_data)

comp_code = ["COLON", "SEMI", "COMMA", "LATEST", "HERE", "STATE", ":", ";"]
comp = pages([n for n in ["LATEST", "HERE", "STATE"] if n in byname] +
             [n for n in ["EXIT", "LIT"] if n in byname])
# compiling touches the dictionary page HERE currently points at, the compiler's own
# code (COLON/SEMI/COMMA are primitives inside the engine, not in the Forth dictionary)
comp.append(here // 512)
comp = sorted(set(comp))

for label, ps in (("idle event loop", idle), ("line: 10 SLEEP-TICKS TASKS .S", line),
                  ("compile one definition", comp)):
    print(f"\n{label}: {len(ps)} distinct 512 B pages {ps}")
    if len(ps) <= 4:
        print(f"  first pass {len(ps)} faults, steady state 0 (fits 4 frames)")
    else:
        print(f"  first pass {len(ps)} faults, steady state THRASH (LRU evicts every pass)")

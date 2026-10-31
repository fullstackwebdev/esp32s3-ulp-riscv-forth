#!/usr/bin/env python3
"""P26: per-group dictionary bytes (with/without headers) and working-set page sets.

Walks the header chain of the image the host build actually produced (img_last.h), so both columns
are measured, not extrapolated. Archive it with the image it describes; re-run per image file.

GUARDRAIL: the header link is 2 bytes wide in this engine (P02 widened tokens, not links) and W@ was
trimmed from the 40, so the link has to be rebuilt from two C@ here as well.
"""
import pathlib, re, sys

root = pathlib.Path(__file__).resolve().parent
# GUARDRAIL: the group counts are read from the sources, so the image and the sources must
# describe the SAME layer. The PAUSE variant lives in its own file for exactly this reason -
# measuring img_with_pause.h against os_tasks.fs shifts every group slice and quietly
# attributes YIELD to the events group.
GROUPS = ["os_tasks.fs", "os_events.fs", "os_repl.fs", "os_introspect.fs", "os_device.fs"]
img = root / (sys.argv[1] if len(sys.argv) > 1 else "img_last.h")
if "pause" in img.name:
    GROUPS[0] = "os_tasks_pause.fs"

txt = img.read_text()
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
    entries.append({"h": a, "n": n, "name": bytes(mem[a + 3:a + 3 + n]).decode(),
                    "cf": (a + 3 + n + 3) & ~3})
    a = rd16(a)
entries.sort(key=lambda e: e["h"])
for i, e in enumerate(entries):
    e["end"] = entries[i + 1]["h"] if i + 1 < len(entries) else here
    e["hdr"] = e["cf"] - e["h"]
    e["used"] = e["end"] - e["cf"]          # code field + body + any ALLOT'ed data

NB = 78                                      # boot_min.fs definitions (P22)
layer_all = entries[NB:]
counts = []
for g in GROUPS:
    c = 0
    for ln in (root / g).read_text().splitlines():
        s = ln.split("\\")[0]
        if re.match(r"^:\s", s) or re.search(r"\bCONSTANT\s+\S+", s) or \
           re.search(r"\bCREATE\s+\S+", s):
            c += 1
    counts.append(c)
if sum(counts) != len(layer_all):
    print(f"WARNING: source count {sum(counts)} != walked {len(layer_all)}", file=sys.stderr)

layer = layer_all[:sum(counts)]
print(f"boot layer: {NB} definitions, {entries[NB-1]['end']} B  (P22: 1716)")
print(f"layer: {len(layer)} definitions, {here - entries[NB-1]['end']} B with headers\n")
print(f"{'group':16}{'defs':>6}{'with hdrs':>11}{'hdrs':>8}{'headerless':>12}")
tot = dict(d=0, w=0, h=0, hl=0)
i = 0
for g, c in zip(GROUPS, counts):
    sel = layer[i:i + c]
    w = sum(e["used"] + e["hdr"] for e in sel)
    hd = sum(e["hdr"] for e in sel)
    hl = w - hd
    print(f"{g:16}{c:>6}{w:>11}{hd:>8}{hl:>12}")
    print("   " + ", ".join(f"{e['name']}={e['used']}" for e in sel))
    tot["d"] += c; tot["w"] += w; tot["h"] += hd; tot["hl"] += hl
    i += c
print(f"{'total':16}{tot['d']:>6}{tot['w']:>11}{tot['h']:>8}{tot['hl']:>12}")

byname = {e["name"]: e for e in entries}


def pages(names, extra=()):
    out = set()
    for nm in names:
        e = byname[nm]
        for p in range(e["cf"] // 512, (e["end"] - 1) // 512 + 1):
            out.add(p)
    for lo, hi in extra:
        for p in range(lo // 512, (hi - 1) // 512 + 1):
            out.add(p)
    return sorted(out)


def var(name):
    e = byname[name]
    return (e["cf"], e["end"])


idle_code = ["YIELD", "SLEEP-TICKS", "POLL-EVENTS", "POST", "GOTKEY", "QUIT"]
idle_data = [var(n) for n in ["TICK", "CUR", "SLOTS", "RING", "RN", "PIN", "PXT", "KIN", "DIAG"]]
idle = pages(idle_code, idle_data)

# GUARDRAIL: page 0 is not optional - V_STATE/V_HERE/V_LATEST live below the first header,
# so every interpreted line and every compile touches page 0. Leaving it out understates
# the working set by one page, which is the whole margin at this layer size.
line = pages(["SLEEP-TICKS", "YIELD", ".S", "U."], idle_data + [(0, 28)])
comp = sorted(set([0] + [byname[n]["cf"] // 512 for n in ("CUR", "TICK", "DIAG")]
                    + [here // 512]))  # page 0 = V_STATE/V_HERE/V_LATEST

for label, ps in (("(a) idle event loop", idle),
                  ("(b) line: 10 SLEEP-TICKS YIELD .S", line),
                  ("(c) compile one definition", comp)):
    print(f"\n{label}: {len(ps)} distinct 512 B pages {ps}")
    if len(ps) <= 4:
        print(f"  first pass {len(ps)} faults, steady state 0 (fits 4 frames)")
    else:
        print(f"  first pass {len(ps)} faults, steady state THRASH (LRU cannot hold {len(ps)} in 4)")

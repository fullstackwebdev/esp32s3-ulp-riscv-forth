#!/usr/bin/env python3
"""P25: page histogram + 4-frame LRU fault simulation over the engine's own page-touch trace.

The trace comes from `uforth_p25 -w <workload> -t <file>`: one byte per dictionary access, the page
index the access landed on, in execution order, recorded inside P() so it covers the instruction
stream AND the variable/record cells. Faults are counted with 512 B pages, 4 frames and true LRU,
with k frames optionally pinned to the first k pages of the idle block.

GUARDRAIL: fault counts must come from an LRU run over the trace, not from `distinct pages <= 4`.
That shortcut is right for a 6-page working set against 4 frames and wrong for a pinned one, where a
page is held in a frame the rest cannot evict.
"""
import pathlib, re, sys, collections

root = pathlib.Path(__file__).resolve().parent
PG, FRAMES = 512, 4
# P24/P22 treat pages 0-2 (system variables, primitive headers, the compiled prelude's code) as
# resident: the resident split keeps code fields and bodies out of the paged name directory. The
# probe is about where the LAYER puts its own definitions, so the working set is the layer's pages
# (>= 3) and that is what the LRU simulation sees; the resident pages are reported, not simulated.
MINPAGE = 3


def walk(img):
    """[(name, cf, end)] from the header chain of a dumped image."""
    txt = (root / img).read_text()
    body = txt[txt.index("{") + 1:txt.rindex("}")]
    mem = bytes(int(x, 16) for x in re.findall(r"0x([0-9a-f]{2})", body))
    rd8 = lambda a: mem[a]
    rd16 = lambda a: mem[a] | mem[a + 1] << 8
    rd32 = lambda a: mem[a] | mem[a + 1] << 8 | mem[a + 2] << 16 | mem[a + 3] << 24
    here, latest, out, a = rd32(4), rd32(8), [], rd32(8)
    while a:
        n = rd8(a + 2) & 31
        cf = (a + 3 + n + 3) & ~3
        out.append([bytes(mem[a + 3:a + 3 + n]).decode(), cf, 0])
        a = rd16(a)
    out.sort(key=lambda e: e[1])
    for i, e in enumerate(out):
        e[2] = out[i + 1][1] if i + 1 < len(out) else here
    return out, here


def pages_of(entries, names):
    sel = [e for e in entries if not names or e[0] in names]
    ps = set()
    for _, cf, end in sel:
        for p in range(cf // PG, (max(end, cf + 4) - 1) // PG + 1):
            ps.add(p)
    return sorted(ps)


def hist(trace):
    return collections.Counter(trace)


def passes(n, trace):
    if n <= 1:
        return [trace]
    k = len(trace) // n
    return [trace[i * k:(i + 1) * k] for i in range(n)]


def report(label, img, tracefile, npss, hotnames):
    entries, here = walk(img)
    tr = list((root / tracefile).read_bytes())
    if not tr:
        sys.exit(f"empty trace: {tracefile}")
    res = hist([p for p in tr if p < MINPAGE])
    tr = [p for p in tr if p >= MINPAGE]
    h = hist(tr)
    hot = pages_of(entries, hotnames)
    seg = passes(npss, tr)
    print(f"\n== {label} ({img}, HERE={here}) ==")
    print(f"  idle block pages: {hot}")
    print(f"  resident pages 0-{MINPAGE - 1} ({sum(res.values())} of {sum(h.values()) + sum(res.values())} "
          f"accesses): " + " ".join(f"p{p}:{c}" for p, c in sorted(res.items())))
    print("  layer page histogram: " + " ".join(f"p{p}:{c}" for p, c in sorted(h.items())))
    print(f"  distinct pages: {len(h)} {sorted(h)}")
    n = len(tr) // len(seg)
    for k in range(0, 4):
        pinned = hot[:k]
        cum = per_pass(tr, pinned)
        print(f"  k={k} pinned={pinned}: first pass {cum[n - 1]} faults, "
              f"steady state {cum[-1] - cum[-n - 1]}/pass, total {cum[-1]}")
    for fr in (5, 6, 7):
        cum = per_pass(tr, (), fr)
        print(f"  bound, {fr} frames: steady state {cum[-1] - cum[-n - 1]}/pass")
    return h, hot, len(seg)


def per_pass(trace, pinned=(), frames=FRAMES):
    """Fault count per pass, ONE continuous LRU across the whole trace (frames stay warm).

    GUARDRAIL: simulating each pass from an empty frame set reports only compulsory faults and hides
    thrash — a 5-page loop looked like "5 faults/pass, so give it 5 frames" when the steady state at
    5 frames is 0 and at 4 frames is 14. Warm the frames across passes, then report the last pass.
    """
    hold = set(pinned)
    nslot = frames - len(hold)
    live, out, n = [], [], 0
    for pg in trace:
        if pg not in hold:
            if pg in live:
                live.remove(pg)
                live.append(pg)
            else:
                n += 1
                if len(live) < nslot:
                    live.append(pg)
                else:
                    live.pop(0)
                    live.append(pg)
        out.append(n)
    return out


if __name__ == "__main__":
    HOTNAMES = """VARIABLE ALLOT CELLS TASK-SZ T>NEXT T>DSP T>RSP T>IP T>STATE T>WAKE T>WAIT T>USER
#FREE #READY #SLEEP #BLOCK #DEAD #MAXTASK TASK-POOL RUNQ CUR #TASKS TICK TMP DIAG WM
#EVQ EV-SZ #EV-KEY #EV-GPIO #EV-TICK EV-RING EV-H EV-T EV-N EA EN KIN GPIOMASK GPIOXT
EV! T-STATE! NEXT-TASK TICK+ WAKE-1 WAKE-ALL YIELD WAKE-MASK ON-GPIO EV-GPIO-DO
POLL-EVENTS PAUSE SLEEP-TICKS""".split()
    args = sys.argv[1:]
    which = args[0] if args else "all"
    if which in ("all", "base"):
        report("baseline (P24 order), idle", "img_base.h", "tr_idle_before.bin", 10, HOTNAMES)
        report("baseline (P24 order), line", "img_base.h", "tr_line_before.bin", 10, HOTNAMES)
        report("baseline (P24 order), compile", "img_base.h", "tr_compile_before.bin", 10, HOTNAMES)
    if which in ("all", "reval"):
        # P24's and P26's idle loops re-measured with the fixed tracer (see RESULT.md §1.3).
        # GUARDRAIL: P26's layer has its own word set (POST/GOTKEY, no EMIT-EVENT/TASKS), so it needs
        # its own hot-name list — reusing P24's names on the P26 image silently pages_of() -> [] and
        # reports "0 pinned" for every k, which is indistinguishable from a passing pin.
        HOT26 = """SLOTS CUR TICK DIAG RING RN PIN PXT KIN GOTKEY ?ERR QUIT ON-EVENT POST
POLL-EVENTS YIELD SLEEP-TICKS""".split()
        report("P24 order, idle, FIXED tracer", "img_base.h", "tr_idle_p24_fixed.bin", 10, HOTNAMES)
        report("P24 order, idle, BUGGY tracer (no instruction fetch)", "img_base.h",
               "tr_idle_p24_buggy.bin", 10, HOTNAMES)
        report("P26 minimal layer, idle, FIXED tracer", "img_p26.h", "tr_idle_p26_fixed.bin", 10, HOT26)
        report("P26 minimal layer, idle, BUGGY tracer (no instruction fetch)", "img_p26.h",
               "tr_idle_p26_buggy.bin", 10, HOT26)
    if which in ("all", "hot"):
        report("reordered, idle", "img_hot.h", "tr_idle_after.bin", 10, HOTNAMES)
        report("reordered, line", "img_hot.h", "tr_line_after.bin", 10, HOTNAMES)
        report("reordered, compile", "img_hot.h", "tr_compile_after.bin", 10, HOTNAMES)

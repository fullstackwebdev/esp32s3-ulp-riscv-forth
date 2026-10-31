#!/usr/bin/env python3
"""P21: build the call graph from objdump -dr and sum the deepest chain.

Inputs (both produced by the exact flags of the P12 ULP build):
  ulp_engine.su   -fstack-usage output, one line per out-of-line function
  ulp_engine.dis  objdump -dr; each function has its own .text.<name> section, so a
                  section is a function body and every R_RISCV_CALL* relocation in it
                  is a real (not inlined) call to another function.

GUARDRAIL: a call that GCC inlined leaves NO relocation, so relocations are exactly the
edges that push a new frame; treating every source-level call as an edge would
double-count the inlined callee's locals (they are already inside the caller's .su
frame). — the chain would be inflated, not wrong-but-safe. — Build edges from
relocations only, and take frames from .su only.
"""
import re
import sys
from collections import defaultdict

SU = "ulp_engine.su"
DIS = "ulp_engine.dis"
if len(sys.argv) > 3:
    SU, DIS = sys.argv[2], sys.argv[3]


def frames(path=SU):
    f = {}
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            loc = parts[0].split(":")  # file:line:col:name
            name = loc[3]
            size = int(re.sub(r"[^0-9]", "", parts[1]) or 0)
            f[name] = size
    return f


def call_graph(path=DIS):
    edges = defaultdict(set)
    cur = None
    pending = False
    sec = re.compile(r"^Disassembly of section \.text\.(\S+):$")
    sym = re.compile(r"^[0-9a-f]+ <(\S+)>:$|^00000000 <(\S+)>:$|^[0-9a-f]+ <([^>]+)>:")
    rel = re.compile(r"^\s+[0-9a-f]+:\s+R_RISCV_(?:CALL|CALL_PLT|JAL)\s+(\S+)$")
    with open(path) as fh:
        for line in fh:
            m = sec.match(line.rstrip("\n"))
            if m:
                cur = m.group(1)
                pending = True
                continue
            # GUARDRAIL: the .su key is the function name, but objdump's section name is
            # .text.startup.main for a static main; keying by the section name silently gives
            # main a 0 B frame and the reported chain shrinks to a callee's own size. — the
            # lookup must use the symbol printed inside the section body.
            if pending:
                if line.strip() == "":
                    continue  # objdump puts a blank line between the header and the symbol
                m = sym.match(line.rstrip("\n"))
                if m:
                    cur = next(g for g in m.groups() if g)
                    pending = False
                    continue
                pending = False
            m = rel.match(line)
            if m and cur:
                tgt = m.group(1)
                if not tgt.startswith(".L"):
                    edges[cur].add(tgt)
    return edges


def deepest(edges, frame, root):
    """max-sum path root -> leaf, with the path"""
    best = {}
    path = {}

    def go(n, stack):
        if n in best:
            return best[n], path[n]
        if n in stack:  # cycle: the engine is not recursive; guard anyway
            return 0, []
        stack.add(n)
        bn, bp = 0, []
        for c in sorted(edges.get(n, ())):
            v, p = go(c, stack)
            if v > bn:
                bn, bp = v, p
        stack.discard(n)
        best[n] = frame.get(n, 0) + bn
        path[n] = [n] + bp
        return best[n], path[n]

    total, p = go(root, set())
    return total, p, best


if __name__ == "__main__":
    fr = frames()
    ed = call_graph()
    root = sys.argv[1] if len(sys.argv) > 1 else "main"
    total, p, best = deepest(ed, fr, root)
    print("frames (.su):")
    for k in sorted(fr, key=lambda k: (-fr[k], k)):
        print("  %-14s %4d" % (k, fr[k]))
    print("\nedges (real calls, from relocations):")
    for k in sorted(ed):
        print("  %-14s -> %s" % (k, ", ".join(sorted(ed[k])) or "(leaf)"))
    print("\nper-function chain sum to leaf (sum of its own frame + best callee):")
    for k in sorted(best, key=lambda k: -best[k]):
        print("  %-14s %4d" % (k, best[k]))
    print("\nDEEPEST CHAIN from %s: %s = %d B" % (root, " -> ".join(p), total))

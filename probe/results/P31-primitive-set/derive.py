#!/usr/bin/env python3
"""P31: turn the engine's own name lookups into the primitive set B is built from.

Input: artifacts/p31_host_trace.txt — `PRIM <name>` lines printed by find() during a real host
load of boot_min.fs + the P26 layer (src/uforth.c built with -DP31_TRACE -DHOST).

The traced names are what the layer and prelude *ask for by name*. Three more things are required
and can never appear in a trace, so they are added explicitly, each with its reason:

  EXIT   `;` compiles rd16(V_XEXIT); boot_init sets V_XEXIT only if the EXIT entry exists. Drop it
         and every colon word ends with token 0 = DOCOL, i.e. infinite recursion, not an error.
  LIT    clit() (numbers, `[']`) compiles rd16(V_XLIT); same mechanism, same silent failure.
  DOCOL DOVAR DOCON  the three pseudo tokens `:`, CREATE and CONSTANT write directly; they are not
         in the PRIMS table at all but they are still three case bodies in the switch.

GUARDRAIL: the trace is the *only* trustworthy source for the named set — a grep of the .fs files
cannot tell a word the layer defines from one it calls, and P26's layer defines words that shadow
primitives (PAUSE, ALLOT, =, >). Names are matched through the PRIMS table, not by prettifying the
Forth spelling, so `[']` maps to BTICK and `!` to STORE exactly once.
"""
import pathlib, re, sys

root = pathlib.Path(__file__).resolve().parent
src = root / "src"
trace = (root / "artifacts" / "p31_host_trace.txt").read_text()
named = [m.group(1) for m in re.finditer(r"^PRIM (.+)$", trace, re.M)]
if len(named) < 20:
    sys.exit(f"only {len(named)} primitive names traced — the host load did not complete")

body = (src / "uforth.c.bak").read_text()
prims = (src / "p31_prims.inc").read_text()
table = [(i, bytes(n, "utf-8").decode("unicode_escape"), f)
         for i, n, f in re.findall(r'X\((\w+),"((?:[^"\\]|\\.)*)",(\d)\)', prims)]
name2id = {t[1]: t[0] for t in table}
missing = [n for n in named if n not in name2id]

required = [(name2id[n], n) for n in dict.fromkeys(named) if n in name2id]
for pid in ("EXIT", "LIT", "DOCOL", "DOVAR", "DOCON"):
    if pid not in [p for p, _ in required]:
        required.append((pid, pid))

(src / "p31_required.defs").write_text("".join(f"-DP_HAVE_{p}\n" for p, _ in required))
dropped = [(p, n) for p, n, _ in table if p not in {p for p, _ in required}]
print(f"table entries: {len(table)}; traced names: {len(dict.fromkeys(named))}; "
      f"required: {len(required)}; dropped: {len(dropped)}")
if missing:
    print("traced names with no PRIMS entry:", missing, file=sys.stderr)
print("REQUIRED:", " ".join(sorted(n for _, n in required)))
print("DROPPED: ", " ".join(sorted(f"{n}({p})" for p, n in dropped)))

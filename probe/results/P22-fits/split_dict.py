#!/usr/bin/env python3
"""P22: split the compiled prelude's dictionary into resident bytes and directory bytes.

Resolution A (docs/01-proposal.md 4.3): the resident dictionary keeps code fields and bodies only;
links, flags/length and names move to a separate, paged name directory. This walks the header chain of
the dictionary the host build actually produced (artifacts/image_p22.h, 1716 B = P20 variant C exactly)
instead of extrapolating 44 %.

Directory entry as measured: [link:2][flags|len:1][name:n][xt:4] — the xt has to live in the directory
because find() returns it, and the resident code field is exactly what is no longer reachable from a
name. Header as compiled: [link:2][flags|len:1][name:n][pad][cf:4].

GUARDRAIL: the link field is 2 bytes wide in this engine (P02 widened tokens, not links), so a header
walk cannot see past 64 KB — fine for a 1716 B dictionary, wrong the day R5 needs a bigger one.
"""
import pathlib, re, sys

h = pathlib.Path(__file__).resolve().parent / "artifacts/image_p22.h"
txt = h.read_text()
body = txt[txt.index("{") + 1:txt.rindex("}")]
mem = bytes(int(x, 16) for x in re.findall(r"0x([0-9a-f]{2})", body))
rd8 = lambda a: mem[a]
rd16 = lambda a: mem[a] | mem[a + 1] << 8
rd32 = lambda a: mem[a] | mem[a + 1] << 8 | mem[a + 2] << 16 | mem[a + 3] << 24

here, latest = rd32(4), rd32(8)
hdrs = []
a = latest
while a:
    n = rd8(a + 2) & 31
    hdrs.append((a, n, rd8(a + 2) >> 7))
    a = rd16(a)
hdrs.sort()
if not hdrs:
    sys.exit("no headers found")
first = hdrs[0][0]

resident = first          # everything below the first header: system variables, PAD
directory = 0
for i, (a, n, imm) in enumerate(hdrs):
    x = (a + 3 + n + 3) & ~3                      # code field, 4-byte aligned
    end = hdrs[i + 1][0] if i + 1 < len(hdrs) else here
    resident += 4 + (end - (x + 4))               # code field + body
    directory += 2 + 1 + n + 4                    # link + flags|len + name + xt

print(f"prelude dictionary as compiled (headers in): {here} B")
print(f"  headers: {here - resident:.0f} B" if False else
      f"  header bytes removed: {sum((hdrs[i+1][0] if i+1 < len(hdrs) else here) - a - (4 + ((hdrs[i+1][0] if i+1 < len(hdrs) else here) - (((a + 3 + n + 3) & ~3) + 4))) for i, (a, n, imm) in enumerate(hdrs))} B")
print(f"resident (system vars + PAD + code fields + bodies): {resident} B")
print(f"name directory (links + flags + names + xts):        {directory} B")
print(f"total Forth memory needed:                           {resident + directory} B")
print(f"definitions: {len(hdrs)}, first header at {first}, HERE={here}")

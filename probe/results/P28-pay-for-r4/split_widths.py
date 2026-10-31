#!/usr/bin/env python3
"""P28: the P22 resident/directory split, run on both token widths, plus a per-word resident table.

P22 measured 1104 resident / 812 directory for the 32-bit build by walking the compiled header chain.
The 16-bit build of the same prelude is a *different layout*, not a ratio: the code field halves (4 -> 2)
and so does its alignment, while names and links do not move at all. So the 16-bit column is measured on
the 16-bit image (artifacts/image16.h, 1352 B = P02's a16 boot dictionary) with the same walk.

GUARDRAIL: the code-field offset depends on the token width (pad is `& ~3` at 32-bit, `& ~1` at 16-bit);
running the 32-bit walk over the 16-bit image finds headers but computes a body start 2 bytes past the
real code field, which inflates resident by 2 B/word and silently shifts every body boundary.
"""
import pathlib, re, sys

CF = int(sys.argv[1])          # code-field width: 4 (32-bit tokens) or 2 (16-bit tokens)
IMG = sys.argv[2]
ALIGN = ~(CF - 1)

txt = pathlib.Path(IMG).read_text()
body = txt[txt.index("{") + 1:txt.rindex("}")]
mem = bytes(int(x, 16) for x in re.findall(r"0x([0-9a-f]{2})", body))
rd8 = lambda a: mem[a]
rd16 = lambda a: mem[a] | mem[a + 1] << 8
rd32 = lambda a: mem[a] | mem[a + 1] << 8 | mem[a + 2] << 16 | mem[a + 3] << 24

here, latest = rd32(4), rd32(8)
hdrs, a = [], latest
while a:
    n = rd8(a + 2) & 31
    hdrs.append((a, n))
    a = rd16(a)
hdrs.sort()
first = hdrs[0][0]

resident, directory, words = first, 0, []
for i, (a, n) in enumerate(hdrs):
    x = (a + 3 + n + (CF - 1)) & ALIGN          # code field
    end = hdrs[i + 1][0] if i + 1 < len(hdrs) else here
    body_b = end - (x + CF)
    resident += CF + body_b
    directory += 2 + 1 + n + CF
    # GUARDRAIL: the name starts at h+3 and the pad bytes sit *before* the code field, so slicing
    # backwards from x (`x-n-1 .. x-1`) picks up padding and mangles every name whose header is
    # aligned — the byte totals stay right, so a name table built that way looks plausible and is wrong.
    name = bytes(mem[a + 3:a + 3 + n]).decode("latin1") if n else "?"
    words.append((name, a, CF + body_b, body_b))

print(f"image {IMG}: dictionary {here} B as compiled, {len(hdrs)} definitions, cf={CF}B")
print(f"resident (sysvars + code fields + bodies): {resident} B")
print(f"name directory (link+flags+name+xt):      {directory} B")
print(f"total Forth memory:                       {resident + directory} B")
print("--- per-word resident (cf+body), descending ---")
for name, a, tot, bb in sorted(words, key=lambda w: -w[2]):
    print(f"  {tot:4d}  (body {bb:4d})  {name}")

#!/usr/bin/env python3
"""Host-only check of the seed-ack parser: a short ack must NOT count as seeded."""
import re
def got(out):
    return {int(m.group(1)): int(m.group(2)) for m in re.finditer(r"seed: block (\d+) <- (\d+) bytes", out)}

cases = [
    # the ack reports the payload in BYTES (the seeder prints w/2), so a full 128-char block acks 128
    ("seed: block 8 <- 128 bytes\n", 8, "A" * 128, True),
    ("seed: block 8 <- 57 bytes\n", 8, "A" * 128, False),    # bytes lost mid-line, the real failure
    ("seed: block 8 <- 3 bytes\n", 8, "A" * 128, False),     # nearly empty
    ("", 8, "A" * 128, False),                                # no ack at all
]
ok = True
for out, blk, text, want in cases:
    good = got(out).get(blk) == len(text)
    ok = ok and good == want
    print(f"  {out.strip() or '(no ack)':32s} -> accepted={good} (want {want})")
print(f"  seed-ack logic: {'PASS' if ok else 'FAIL'}")
raise SystemExit(0 if ok else 1)

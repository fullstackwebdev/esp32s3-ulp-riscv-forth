#!/usr/bin/env python3
"""check_strings.py — prove the host table in src/msg_codes.h is byte-for-byte the text the SHIPPING
ULP image carries, for all eight messages, including the four a host run cannot reach.

    ./tools/check_strings.py /path/to/ulp_main.elf

Reads .rodata, splits it into "message text" and "the dispatch jump table" by looking for the first
4-aligned offset from which EVERY following word is a plausible .text address, then requires:

  1. each MSG_LIST text occurs verbatim, NUL-terminated, in the text region;
  2. the text region is exactly sum(round_up(len+1,4)) bytes — no orphan string, no invented one;
  3. the jump table is still there and is the rest (it is code addresses, i.e. NOT movable to the host).

GUARDRAIL: this exists because four messages (banner, line-too-long, tasks-need-an-empty-stack,
ERR_DICT) cannot be produced by any host-only test run. Checking them "by reading the header" is how a
typo in one character of a message survives to the operator; comparing against the shipping image is the
only check that does not depend on trusting the copy.
"""
import re
import struct
import subprocess
import sys
import pathlib

RVBIN = pathlib.Path(
    "/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin")
HDR = pathlib.Path(__file__).resolve().parent.parent / "src" / "msg_codes.h"


def rodata(elf):
    return subprocess.run([RVBIN / "riscv32-esp-elf-objcopy", "-O", "binary",
                           "--only-section=.rodata", elf, "/dev/stdout"],
                          check=True, capture_output=True).stdout


def text_size(elf):
    out = subprocess.run([RVBIN / "riscv32-esp-elf-size", "-A", elf],
                         check=True, capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.split() and line.split()[0] == ".text":
            return int(line.split()[1])
    raise SystemExit("check_strings: no .text")


def messages():
    src = HDR.read_text()
    body = src.split("#define MSG_LIST(X)", 1)[1]
    out = []
    for name, code, text in re.findall(r'X\(\s*(\w+)\s*,\s*(0x[0-9a-fA-F]+)\s*,\s*"((?:[^"\\]|\\.)*)"\s*\)', body):
        raw = text.encode().decode("unicode_escape").encode("latin-1")
        out.append((name, int(code, 16), raw))
    return out


def main(elf):
    blob = rodata(elf)
    tsize = text_size(elf)
    # GUARDRAIL: search for the SMALLEST offset whose whole suffix decodes as code addresses (scanning
    # up and taking the first hit found a bogus 3-word "table" at the end of the string region and
    # reported 360 B of "message text"). Every string in the region decodes to a word far above .text
    # (e.g. "stack?\n\0" = 0x63617473), so the split is unambiguous once the scan goes downward and
    # insists on the whole suffix plus a plausible entry count. Entry alignment is deliberately NOT
    # checked: the image is RV32C, so a computed-goto target may be only 2-byte aligned (0x5b6 here).
    table_at = None
    for off in range(0, len(blob) - 3, 4):
        words = struct.unpack_from(f"<{len(blob[off:]) // 4}I", blob, off)
        if len(words) >= 16 and all(0x100 <= w < tsize for w in words):
            table_at = off
            break
    if table_at is None:
        raise SystemExit("check_strings: could not find the dispatch table")
    text_region, table = blob[:table_at], blob[table_at:]

    fails = 0
    total = 0
    pos = 0
    seen = []
    # GUARDRAIL: do NOT assume the messages appear in MSG_LIST order. .rodata is laid out in the order of
    # first use in the source (ERR_DICT comes first here, the banner third), so a positional check reports
    # eight failures on a perfectly correct build. Match greedily, longest first, and then require the
    # region to be FULLY covered — that is what proves no text was invented and none was left behind.
    msgs = sorted(messages(), key=lambda m: -len(m[2]))
    while pos < len(text_region):
        for name, code, raw in msgs:
            want = raw + b"\0"
            if text_region[pos:pos + len(want)] != want:
                continue
            seen.append(name)
            pos += (len(raw) + 1 + 3) & ~3
            break
        else:
            print(f"FAIL  no message matches the ULP text region at byte {pos}: "
                  f"{text_region[pos:pos + 16]!r}")
            pos += 4
            fails += 1
    for name, code, raw in messages():
        total += (len(raw) + 1 + 3) & ~3
        if name not in seen:
            print(f"FAIL  {name} 0x{code:02x} is not in the shipping image "
                  f"(host text {raw!r})")
            fails += 1
    if total != len(text_region) or len(seen) != len(messages()):
        print(f"FAIL  text region is {len(text_region)} B, the list accounts for {total} B "
              f"({len(seen)}/{len(messages())} matched) — a message exists on one side only")
        fails += 1
    print(f"{'ok ' if not fails else 'FAIL'} {len(messages())} messages, {len(text_region)} B of ULP "
          f"message text (was {total} B of .rodata), dispatch table {len(table)} B "
          f"({len(table) // 4} entries) still in the image")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

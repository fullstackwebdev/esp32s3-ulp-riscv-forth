#!/usr/bin/env python3
"""Compare a kept flash backup against a fresh read of the chip, partition by partition.

    tools/backup_compare.py backup/<name>.bin probe/results/reverify.bin

WHY THIS EXISTS: a second read of the same board a few minutes after the backup did NOT match it - 463 bytes
disagreed (0.006 %). Every one of those bytes sat inside `nvs` or `spiffs`, and both `app0` and `app1` were
byte-identical. That is the board's own firmware writing NVS entries and SPIFFS files while it runs, not a bad
dump: a full-flash backup is a SNAPSHOT, so comparing raw sha256 across sessions produces a false alarm on a
perfectly good backup - and a check that cries wolf is a check someone disables.

The rule this encodes, by PARTITION TYPE (0 = app, 1 = data) rather than by partition label, so a renamed
partition cannot dodge it:
  * every app-type partition MUST match byte for byte - that is the code a restore reinstates;
  * data-type partitions are reported as drift, with sizes and offsets, and are not an error;
  * the partition table itself MUST match - if it differs, the two dumps are not the same layout and no
    comparison below it means anything.
Exit 1 only for a real problem, so this can gate a restore rehearsal.
"""
import argparse
import hashlib
import pathlib
import struct
import sys

PT_OFF = 0x8000
PT_MAGIC = 0x50AA


def partitions(blob):
    """(label, type, subtype, offset, size) for each entry in the partition table at 0x8000."""
    out = []
    for off in range(PT_OFF, PT_OFF + 0x1000, 32):
        magic, ptype, subtype, o, size, label, _flags = struct.unpack("<HBBII16sI", blob[off:off + 32])
        if magic != PT_MAGIC:
            break
        out.append((label.rstrip(b"\0").decode(errors="replace"), ptype, subtype, o, size))
    if not out:
        raise SystemExit("REFUSED: no partition table at 0x8000 - this is not a full-flash dump")
    return out


def regions(a, b, o, size):
    """Byte ranges where two blobs differ inside [o, o+size)."""
    seg_a, seg_b = a[o:o + size], b[o:o + size]
    if seg_a == seg_b:
        return []
    diffs = [i for i in range(len(seg_a)) if seg_a[i] != seg_b[i]]
    runs, start, prev = [], None, None
    for i in diffs:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            runs.append((start, prev))
            start = prev = i
    if start is not None:
        runs.append((start, prev))
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kept")
    ap.add_argument("fresh")
    a = ap.parse_args()
    ka, fr = pathlib.Path(a.kept).read_bytes(), pathlib.Path(a.fresh).read_bytes()
    if len(ka) != len(fr):
        print(f"REFUSED: sizes differ ({len(ka)} vs {len(fr)})")
        return 1
    parts = partitions(ka)
    if ka[PT_OFF:PT_OFF + 32 * len(parts)] != fr[PT_OFF:PT_OFF + 32 * len(parts)]:
        print("REFUSED: the partition tables differ - these are not the same layout, nothing below is comparable")
        return 1

    bad = 0
    print(f"{'partition':12s} {'type':5s} {'offset':>9s} {'size':>9s}  verdict")
    for label, ptype, _sub, o, size in parts:
        runs = regions(ka, fr, o, size)
        kind = "app" if ptype == 0 else "data"
        if not runs:
            verdict = "byte-identical"
        elif ptype == 0:
            n = sum(e - s + 1 for s, e in runs)
            verdict = f"DIFFERS in {len(runs)} range(s), {n} B - CODE CHANGED"
            bad += 1
        else:
            n = sum(e - s + 1 for s, e in runs)
            verdict = f"drift {n} B in {len(runs)} range(s) - runtime writes, expected"
        print(f"{label:12s} {kind:5s} 0x{o:07X} {size:>8d}  {verdict}")
        if ptype == 0 and runs:
            for s, e in runs[:4]:
                print(f"             first differences at 0x{o + s:07X}-0x{o + e:07X}")
                print(f"             kept {ka[o + s:o + s + 8].hex()}  fresh {fr[o + s:o + s + 8].hex()}")

    code = hashlib.sha256()
    for label, ptype, _sub, o, size in parts:
        if ptype == 0:
            code.update(ka[o:o + size])
    print(f"\napp-partition digest: {code.hexdigest()[:32]}")
    if bad:
        print(f"FAIL: {bad} app partition(s) differ - the kept dump is NOT the code on this chip")
        return 1
    print("PASS: every app partition matches; data partitions drifted, which a snapshot cannot promise")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Refuse any Forth name whose 12-bit dictionary hash collides with a name already in the vocabulary.

    python3 probe/repl/tools/hashcheck.py [--resident NAMES.txt] file.fs [file.fs ...]

WHY THIS EXISTS AS A BUILD STEP: the dictionary stores NO names (P54: 24-bit entry = imm1 | xt11 | hash12),
so a 12-bit djb2 hash is the ONLY identity a word has. The engine therefore refuses a definition whose hash
already belongs to another word - and at the plain prompt that refusal is the WHOLE message: `9 CONSTANT SCK`
answers `SCK?` and the driver goes on to compile against a constant that does not exist, which is how the LoRa
driver spent more than 165 probe cycles "failing to drive the pads". Nothing else about that failure was ever
true. See docs/30 F-176k.

Measured refusal rate, from the engine's own comment: about 2.3 % per definition against 98 resident words -
so with the driver's 20-odd names a collision is close to certain, and this file makes it a build error.

Resident vocabulary comes from the engine itself (build the host bake with -DP54_NAMES and capture stderr:
each interned name is printed by mkentry, the one place a name becomes a header). Re-deriving that list by
regex over the prelude is forbidden by rule R6 and is exactly what this tool does not do: if a name is missing
from the dump, the search never sees it, and the bake already checks stored keys pairwise and exits 3.

Exit 0 = every name is free. Exit 1 = at least one collision, listed as `name -> hash -> already-taken-by`.
"""
import argparse
import pathlib
import re
import sys

# The engine's hash, transcribed: djb2, seed 5381, multiplier 33, masked to 12 bits.
MASK = 0xFFF


def h(name):
    v = 5381
    for ch in name.encode():
        v = (v * 33 + ch) & 0xFFFFFFFF
    return v & MASK


# GUARDRAIL: names are interned from PAD, which the tokeniser fills UPPERCASE, so the hash is over the
# upper-cased token. Hashing the raw case would agree with nothing the chip does.
def norm(t):
    return t.upper()


# Definition forms the engine interns. `( ...` and `." ...` are skipped by the tokeniser, not interned.
# GUARDRAIL: `5 FOO CONSTANT` is backwards - the NAME follows CONSTANT, and the value comes first. The first
# version of this pattern captured the VALUE (`9` from `9 CONSTANT SCK`), so the checker hashed a digit, found
# every file clean, and said nothing about the collision that made the chip refuse SCK/MISO/BUSY/SET/IN.
# A checker that sees no names must not report "clean": see the count assertion below.
DEFN_COLON = re.compile(r"^\s*:\s+(?P<n>\S+)")
DEFN_CONST = re.compile(r"^\s*\S+\s+(?:CONSTANT|VARIABLE)\s+(?P<n>\S+)")
DEFN_CREATE = re.compile(r"^\s*CREATE\s+(?P<n>\S+)")
DEFN_SHORT = re.compile(r"^\s*:(?:CONSTANT|TOKEN)\s+(?P<n>\S+)")


def defined_names(path):
    """Names this file interns, in the order the chip will intern them."""
    out = []
    text = path.read_text()
    # Strip parenthesised and line comments so a `( -- )` stack effect is never read as a definition.
    for raw in text.splitlines():
        line = raw
        if line.lstrip().startswith("\\" if len(line.lstrip()) > 1 else ""):
            continue
        line = re.sub(r"\(.*?\)", " ", line)
        for pat in (DEFN_COLON, DEFN_CONST, DEFN_CREATE, DEFN_SHORT):
            m = pat.match(line)
            if m:
                out.append(norm(m.group("n").split()[0]))
                break
    if not out:
        # GUARDRAIL: never "clean" on an empty extraction - that is how a broken regex lies.
        print(f"hashcheck: FAIL - no definitions found in {path}; refusing to call that clean", file=sys.stderr)
        raise SystemExit(2)
    return out


def load_resident(path):
    names = []
    for line in path.read_text().splitlines():
        if line.startswith("NAME "):
            names.append(norm(line[5:].strip()))
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resident", default=str(pathlib.Path(__file__).resolve().parent / "resident_names.txt"))
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()

    rpath = pathlib.Path(a.resident)
    if not rpath.exists():
        # GUARDRAIL: no silent pass. A checker that cannot see the vocabulary says "clean" about everything.
        print(f"hashcheck: FAIL - resident vocabulary {rpath} is missing.\n"
              "  regenerate it: gcc <bake flags> -DP54_NAMES -o artifacts/names_bin src/uforth.c && "
              "./artifacts/names_bin -d /dev/null src/p39_prelude.fs src/p39b_overlay.fs src/line.fs 2>artifacts/names.txt",
              file=sys.stderr)
        return 2
    resident = load_resident(rpath)
    buckets = {}
    for n in resident:
        buckets.setdefault(h(n), n)

    bad = 0
    for f in a.files:
        for name in defined_names(pathlib.Path(f)):
            b = h(name)
            owner = buckets.get(b)
            if owner is not None and owner != name:
                print(f"{f}: R25 hash: `{name}` hashes to {b}, already taken by `{owner}` "
                      f"- the chip will REFUSE this definition and answer `{name}?`")
                bad += 1
            else:
                buckets[b] = name
    if bad:
        print(f"hashcheck: {bad} collision(s) - rename the words (longer, unique names) before typing them")
        return 1
    print("hashcheck: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())

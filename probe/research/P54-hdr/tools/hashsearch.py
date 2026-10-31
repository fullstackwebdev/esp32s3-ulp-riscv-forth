#!/usr/bin/env python3
"""hashsearch.py — find a 13-bit dictionary hash that is INJECTIVE over the baked vocabulary.

Why this exists: a 13-bit key over 85 words has an expected collision count of
85*84/2/8192 = 0.44, so "it probably works" is a coin flip, and the failure mode is the one
the machine cannot report: find() returns the first matching entry, so a colliding pair makes
one word silently answer for another. This tool answers the only question that matters —
does a collision-free (hash function, multiplier, seed) triple exist for the CURRENT 85 names —
and the bake-time check in uforth.c is what keeps the answer true after a word is added.

Input is the name list dumped by the engine itself (-DP54_NAMES, see uforth.c), not a regex
over the prelude: a second derivation of the vocabulary would eventually disagree with the
first (R6), and a name the search never sees is exactly the collision it fails to find.

usage: tools/hashsearch.py out/names.log
"""
import sys

BITS = 13
MASK = (1 << BITS) - 1
COLLIDE_ALLOWED = 0            # a hash with any colliding pair is not a candidate


def load_names(path):
    names = [l[5:].strip() for l in open(path) if l.startswith("NAME ")]
    if not names:
        sys.exit(f"hashsearch: no NAME lines in {path} — was the dump built with -DP54_NAMES?")
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        sys.exit(f"hashsearch: duplicate names in the vocabulary {sorted(dup)} — the dictionary is broken")
    return names


def djb2_low(name_bytes, mult, seed, fold=None):
    """The engine's loop shape: h = h*mult + c over the bytes, then fold to BITS.

    `fold` is applied to the whole 32-bit h at the end, which is what the C code does — folding
    per character would be a different function and would not be what gets baked."""
    h = seed
    for c in name_bytes:
        h = (h * mult + c) & 0xFFFFFFFF
    if fold is None:
        return h & MASK
    if fold == "xor13":
        return (h ^ (h >> 13)) & MASK
    if fold == "add13":
        return (h + (h >> 13)) & MASK
    if fold == "shift5":
        return (h >> 5) & MASK
    if fold == "shift9":
        return (h >> 9) & MASK
    raise SystemExit(f"hashsearch: unknown fold {fold}")


def collisions(names, mult, seed, fold):
    seen = {}
    hits = []
    for n in names:
        v = djb2_low(n.encode(), mult, seed, fold)
        if v in seen:
            hits.append((seen[v], n, v))
        else:
            seen[v] = n
    return hits


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "out/names.log"
    names = load_names(path)
    n = len(names)
    print(f"vocabulary: {n} words, {BITS}-bit key ({MASK + 1} values), "
          f"expected collisions for a random hash = {n * (n - 1) / 2 / (MASK + 1):.3f}")

    # The shipping function, measured rather than assumed: this is the baseline the search must beat.
    base = collisions(names, 33, 5381, None)
    print(f"baseline djb2 m=33 seed=5381 low{BITS}: {len(base)} colliding pairs")
    for a, b, v in base:
        print(f"    COLLISION {a!r} vs {b!r} at 0x{v:04x}")

    folds = [None, "xor13", "add13", "shift5", "shift9"]
    seeds = [5381, 0, 1, 33, 271, 2561]
    found = []
    tested = 0
    for mult in range(3, 1024, 2):            # odd multipliers only: an even one throws away bits
        for seed in seeds:
            for fold in folds:
                tested += 1
                if not collisions(names, mult, seed, fold):
                    found.append((mult, seed, fold))
    print(f"searched {tested} (multiplier, seed, fold) triples: {len(found)} collision-free")
    # Ordering is for reading, not for choosing: prefer the constants already in hash_pad (keeping them
    # means only the mask moves, so bake-time and run-time cannot disagree), then no fold (a fold is two
    # extra instructions), then the smallest multiplier.
    found.sort(key=lambda t: (t != (33, 5381, None), t[2] is not None, t[0], t[1]))
    for mult, seed, fold in found[:20]:
        print(f"    OK mult={mult:<5} seed={seed:<6} fold={fold}")
    if not found:
        print("NO-GO: no collision-free 13-bit hash in the searched family")
        return 1
    mult, seed, fold = found[0]
    ship = (33, 5381, None) in found
    print(f"\nchosen: mult={mult} seed={seed} fold={fold}"
          f"{'  (the shipping constants: only the mask changes)' if ship else ''}")
    if not ship:
        print("NOTE: the shipping djb2 constants collide at this width — hash_pad would have to change,")
        print("      and any change there has to be re-checked at bake time, not just here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

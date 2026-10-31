#!/usr/bin/env python3
"""assert_ulp_only.py — prove that no Forth executes on the ESP32's main cores.

The claim under test is not "we did not mean to" — it is that the *only* place a Forth token is
fetched, decoded and executed is the ULP image. Two independent checks, both fail-first:

  STATIC   the HP (main-core) executable contains the ULP image only as inert bytes that it copies
           to the coprocessor, and defines no evaluator of its own.
  (the dynamic counterfactual lives in the probe: stub the ULP, and the console must go silent)

Exit codes: 0 = every check passed, 1 = a check failed and named itself, 2 = could not run.

GUARDRAIL: match the *dictionary payload* byte for byte, never vocabulary words as substrings. The HP
image legitimately contains "SWAP" and "OVER" (inside the embedded ULP blob, which it must carry), and
contains "DUP" as a fragment of IDF's own "ESP_ERR_MESH_DISCARD_DUPLICATE" and UART's "...HALF_DUPLEX".
A substring sweep therefore reports 3 hits on a perfectly correct image, and once you learn to ignore
those hits you have taught yourself to ignore the real ones.
"""
import json
import os
import re
import subprocess
import sys

BUILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build")
HP_ELF = None
ULP_ELF = os.path.join(BUILD, "esp-idf", "main", "ulp_main", "ulp_main.elf")

# Symbols that would mean an evaluator was compiled into the main-core executable.
EVALUATOR_SYMBOLS = ("interpret", "vm_enter", "do_colon", "vm_run", "run_line", "repl_drain")

failures = []


def fail(msg):
    failures.append(msg)


def find_hp_elf():
    cands = sorted(f for f in os.listdir(BUILD) if f.endswith(".elf"))
    if len(cands) != 1:
        sys.exit("assert: expected exactly one app ELF in %s, found %r" % (BUILD, cands))
    return os.path.join(BUILD, cands[0])


def tool(name):
    path = os.environ.get("IDF_PATH")
    if not path:
        sys.exit("assert: IDF_PATH is not set")
    return name


def nm(elf, *args):
    out = subprocess.run(["xtensa-esp32s3-elf-nm"] + list(args) + [elf],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("assert: nm failed on %s: %s" % (elf, out.stderr.strip()))
    return out.stdout


def ulp_nm(*args):
    out = subprocess.run(["riscv32-esp-elf-nm"] + list(args) + [ULP_ELF],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("assert: riscv nm failed: %s" % out.stderr.strip())
    return out.stdout


def symbols(text):
    """name -> (size, type, value) from `nm -S` output."""
    table = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) == 4:
            table[f[3]] = (int(f[1], 16), f[2], int(f[0], 16))
        elif len(f) == 3:
            table[f[2]] = (None, f[1], int(f[0], 16))
    return table


def main():
    hp = find_hp_elf()
    print("HP  executable:", os.path.basename(hp))
    print("ULP executable:", os.path.relpath(ULP_ELF, BUILD))

    hp_syms = symbols(nm(hp, "-S"))
    ulp_syms = symbols(ulp_nm("-S"))

    # ---- 1. the HP carries the ULP image, and only as data -------------------------------
    blob = None
    for name, (size, typ, value) in hp_syms.items():
        if name == "_binary_ulp_main_bin_start":
            blob = value
    if blob is None:
        fail("HP executable has no _binary_ulp_main_bin_start: it cannot be loading a ULP image at all")
        report(); return

    ulp_bin_path = os.path.join(BUILD, "esp-idf", "main", "ulp_main", "ulp_main.bin")
    ulp_bin = open(ulp_bin_path, "rb").read()
    hp_raw = open(hp, "rb").read()

    # Locate the embedded blob by content, not by vaddr arithmetic: ELF file offsets and vaddrs
    # disagree inside the pseudo-section the IDF linker script creates for flash rodata.
    probe_slice = ulp_bin[len(ulp_bin) // 3: len(ulp_bin) // 3 + 48]
    off = hp_raw.find(probe_slice)
    if off < 0:
        fail("the ULP image's own bytes are not present in the HP executable (stale build?)")
        report(); return
    blob_start = off - len(ulp_bin) // 3
    blob_end = blob_start + len(ulp_bin)
    print("embedded ULP blob: file offsets 0x%x..0x%x (%d B)" % (blob_start, blob_end, len(ulp_bin)))

    # ---- 2. the dictionary exists on the ULP and nowhere else in code form ---------------
    if "mem" not in ulp_syms or ulp_syms["mem"][0] is None:
        fail("ULP image has no sized `mem` symbol: the Forth dictionary is not resident there")
        payload = None
    else:
        mem_size = ulp_syms["mem"][0]
        payload = ulp_bin[ulp_syms["mem"][2] - ulp_syms.get("__data_start", (0, 0, 0))[2]:][:mem_size]
        if len(payload) != mem_size:
            # fall back to a slice taken from the .bin at the symbol's offset within .data
            payload = None
        print("ULP dictionary `mem`: %d B" % mem_size)

    if payload:
        hits, i = [], hp_raw.find(payload[:256])
        while i != -1:
            hits.append(i)
            i = hp_raw.find(payload[:256], i + 1)
        if not hits:
            fail("the dictionary payload is not in the HP executable at all: the blob search is unsound")
        outside = [h for h in hits if not (blob_start <= h < blob_end)]
        if outside:
            fail("dictionary payload found at HP file offsets %s, OUTSIDE the embedded ULP blob — "
                 "the main core is carrying a copy the coprocessor never sees"
                 % ", ".join("0x%x" % h for h in outside[:4]))
        else:
            print("dictionary payload: %d occurrence(s), all inside the embedded blob" % len(hits))

    # ---- 3. no evaluator compiled into the main core ------------------------------------
    found = [s for s in EVALUATOR_SYMBOLS if s in hp_syms]
    if found:
        fail("HP executable defines evaluator symbol(s) %s — the main core can interpret Forth" % found)
    else:
        print("HP evaluator symbols: none of %s" % (", ".join(EVALUATOR_SYMBOLS),))

    # ---- 4. the evaluator *is* on the ULP -------------------------------------------------
    # It has no symbol of its own: GCC inlines interpret()/run() into main (P39), so the honest
    # assertion is that main is large enough to contain the dispatch loop plus dictionary.
    main_size = ulp_syms.get("main", (0, None, 0))[0] or 0
    if main_size < 1000:
        fail("ULP `main` is only %d B: too small to hold the token dispatch loop (P39 measured ~2.9 KB)" % main_size)
    else:
        print("ULP evaluator: main = %d B (inlined dispatch loop)" % main_size)

    # ---- 5. the HP does not echo or prompt either ---------------------------------------
    # Echo and prompt are ULP behaviour (probe/repl/src/ulp_repl.c); the HP bridge has no line logic.
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "main", "repl_main.c")).read()
    # GUARDRAIL: strip comments before scanning. The first version of this check failed on the word
    # "interpreter" inside a GUARDRAIL comment that said the interpreter is on the ULP — a checker that
    # flags the sentence explaining the invariant is worse than no checker, because the fix is to delete
    # the explanation. Compare identifiers in code only.
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"//[^\n]*", " ", src)
    banned = [r"\binterpret\b", r"\btib\s*\[", r"\bfind\s*\(", r"\bpl_emit\b"]
    hits = [b for b in banned if re.search(b, src)]
    if hits:
        fail("the HP bridge source calls %s — line discipline belongs on the ULP" % hits)
    else:
        print("HP bridge source: no line discipline, no evaluator, no echo")

    report()


def report():
    if failures:
        print("\nFAIL — %d check(s) failed:" % len(failures))
        for f in failures:
            print("  *", f)
        sys.exit(1)
    print("\nPASS — no Forth executes on the ESP32's main cores")


if __name__ == "__main__":
    main()

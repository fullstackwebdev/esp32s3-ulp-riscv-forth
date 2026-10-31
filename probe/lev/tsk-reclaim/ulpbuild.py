#!/usr/bin/env python3
"""Reproduce the shipping ULP link for THIS directory's src/, into ./out.elf.

The compile flags and include list are taken verbatim from the shipping build's
compile_commands.json (read-only), with the source path swapped to this workspace and -o
pointed at ./out/objs/. The link line is the shipping build.ninja LINK_FLAGS with -Map and
-T pointed at local files (the ld script is the IDF template preprocessed with the shipping
build's own ld_args.txt, which is how CONFIG_ULP_COPROC_RESERVE_MEM becomes the region size).

Usage: python3 ulpbuild.py [--src SRC] [--ld LDSCRIPT] [--out NAME.elf]
"""
import json, os, shlex, subprocess, sys, glob

ROOT = os.path.dirname(os.path.abspath(__file__))
REF = "/home/user/research/esp32-rv32/probe/repl/build/esp-idf/main/ulp_main"
REF_SRC = "/home/user/research/esp32-rv32/probe/repl/src/ulp_repl.c"
IDF = "/home/user/research/esp32/esp-idf"
ULP_CORE = IDF + "/components/ulp/ulp_riscv/ulp_core"
TC = "/home/user/.espressif/tools/riscv32-esp-elf/esp-14.2.0_20241119/riscv32-esp-elf/bin"
GCC = TC + "/riscv32-esp-elf-gcc"
SIZE = TC + "/riscv32-esp-elf-size"

args = sys.argv[1:]
def opt(name, default):
    if name in args:
        return args[args.index(name) + 1]
    return default

src = os.path.join(ROOT, opt("--src", "src/ulp_repl.c"))
lds = os.path.join(ROOT, opt("--ld", "ulp_riscv_gen.ld"))
outelf = os.path.join(ROOT, opt("--out", "out.elf"))
objdir = os.path.join(ROOT, "out", os.path.splitext(os.path.basename(outelf))[0])
os.makedirs(objdir, exist_ok=True)

cc = json.load(open(REF + "/compile_commands.json"))

def entry_for(path):
    # GUARDRAIL: this workspace's src/ is a byte-identical copy of the shipping src/, so the
    # shipping compile line is reused with only the source path swapped — matching on basename
    # is what keeps a copy at a different path from looking like "no compile entry".
    for e in cc:
        if e["file"] == path:
            return shlex.split(e["command"])
    base = os.path.basename(path)
    for e in cc:
        if e["file"] == REF_SRC and os.path.basename(path) == os.path.basename(REF_SRC):
            return shlex.split(e["command"])
    for e in cc:
        if os.path.basename(e["file"]) == base:
            return shlex.split(e["command"])
    raise SystemExit("no compile entry for " + path)

def build_cflags(path):
    a = entry_for(path)
    keep = []
    for t in a[1:]:
        if t in ("-c", "-o"):
            continue
        keep.append(t)
    # drop the object file argument and the (possibly foreign-path) source token: the entry we
    # reuse may name the shipping src path, so match by extension, not by equality.
    keep = [t for t in keep if not t.endswith(".obj")]
    keep = [t for t in keep if not (t.endswith(".c") or t.endswith(".S"))]
    return keep

def compile_one(path, asm=False):
    base = os.path.basename(path)
    obj = os.path.join(objdir, base + ".obj")
    flags = build_cflags(path)
    cmd = ["nice", "-n", "15", "timeout", "120", GCC] + flags + ["-o", obj, "-c", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("FAILED:", " ".join(cmd))
        print(r.stdout, r.stderr)
        raise SystemExit(1)
    return obj

# 1. preprocess the IDF ld template exactly as the shipping build does
ldargs = shlex.split(open(REF + "/ulp_riscv.ld_args.txt").read().strip())
if not os.path.exists(lds):
    gen = list(ldargs)
    i = gen.index("-o")
    gen[i + 1] = lds
    cmd = ["nice", "-n", "15", "timeout", "120", GCC] + gen
    if subprocess.run(cmd, capture_output=True, text=True).returncode != 0:
        raise SystemExit("ld script preprocessing failed")
    print("ld script:", lds, "(from IDF template)")

# 2. compile this directory's ULP source + the ulp_core set the shipping link uses
objs = [compile_one(src)]
for name in ["ulp_riscv_vectors.S", "start.S",
             "ulp_riscv_adc.c", "ulp_riscv_lock.c", "ulp_riscv_uart.c", "ulp_riscv_print.c",
             "ulp_riscv_i2c.c", "ulp_riscv_utils.c", "ulp_riscv_touch.c", "ulp_riscv_gpio.c",
             "ulp_riscv_interrupt.c"]:
    objs.append(compile_one(ULP_CORE + "/" + name))

# 3. link with the shipping LINK_FLAGS
mapfile = outelf + ".map"
link = [GCC, "-march=rv32imc_zicsr_zifencei", "--specs=nano.specs", "--specs=nosys.specs",
        "-nostartfiles", "-Wl,--gc-sections", "-Wl,--no-warn-rwx-segments",
        "-Wl,-Map=" + mapfile, "-T", lds, IDF + "/components/ulp/ld/esp32s3.peripherals.ld"]
cmd = ["nice", "-n", "15", "timeout", "120"] + link + objs + ["-o", outelf]
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode != 0:
    print("LINK FAILED")
    print(r.stdout, r.stderr)
    raise SystemExit(1)

print("\nCOMPILE:", " ".join(objs and [GCC, "..."]))
print("LINK:", " ".join(cmd))
print()
r = subprocess.run([SIZE, outelf], capture_output=True, text=True)
print(r.stdout.strip())
row = r.stdout.strip().splitlines()[-1].split()
text, data, bss, dec = int(row[1]), int(row[2]), int(row[3]), int(row[4])
print("text=%d data=%d bss=%d  pool used (text+data+bss)=%d of 7856, spare=%d" % (text, data, bss, dec, 7856 - dec))
for s in ("__stack_top",):
    r2 = subprocess.run([TC + "/riscv32-esp-elf-nm", outelf], capture_output=True, text=True)
    for line in r2.stdout.splitlines():
        if line.endswith(" " + s):
            print("%s = 0x%x (%d)" % (s, int(line.split()[0], 16), int(line.split()[0], 16)))

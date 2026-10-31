#!/usr/bin/env python3
"""P29: link the shipping engine — 16-bit tokens (P28) + vm_switch/records (P27) + paging, frames and
budget arrays (P29) + the layer's four hooks — at MEMSZ 908 with three tasks, and report the size.
Same recipe as P29: IDF's own compile/link flags, stub-subtraction for the harness.

Recipe: P12/P20's stub-subtraction build. The compile and link flags are the ones IDF itself generated
for P20's variant A build (read-only), so this is the same compiler, the same -march, the same startup
(ulp_riscv_vectors.S + start.S) and the same peripherals script; only the engine TU and the linker
script's ram LENGTH change. P20 calibrated this path against a real `idf.py build` and reproduced its
4116 B .bin exactly, so the number below is comparable to P12/P20's.

GUARDRAIL: the linker script is P29's own copy with LENGTH = 8176 - 320 (P21's C stack). The stock
script puts __stack_top at the top of the 8176 B pool and the C stack then grows down into .bss, so a
link against the stock script proves nothing about the C stack line.
"""
import json, pathlib, re, shlex, subprocess, sys

root = pathlib.Path(__file__).resolve().parent
src = root / "src"
art = root / "artifacts"
p20 = root.parent / "P20-native-accessors" / "idfproj/build/esp-idf/main/ulp_main"
cc = json.load(open(p20 / "compile_commands.json"))
stub_cc = next(e for e in cc if e["file"].endswith("ulp_stubs.c"))
args = shlex.split(stub_cc["command"])
gcc = args[0]
ninja = (p20 / "build.ninja").read_text()
link_flags = re.search(r"^  LINK_FLAGS = (.*)$", ninja, re.M).group(1)
objs = re.search(r"^build ulp_main\.elf: \S+ (.*?)(?: \|\| ld_script)$", ninja, re.M).group(1).split()
objs = [str((p20 / o).resolve()) for o in objs]
stub_obj = next(o for o in objs if o.endswith("ulp_stubs.c.obj"))
rest = [o for o in objs if o != stub_obj]


def compile_stub(out, extra):
    # GUARDRAIL: the source path appears twice in the IDF compile command (input and after -c);
    # rewriting only one makes gcc see two inputs and die with "cannot specify -o with multiple files".
    a = [str(src / "ulp_stubs.c") if x.endswith("ulp_stubs.c") else x for x in args]
    a[a.index("-o") + 1] = str(out)
    a += extra
    print("+ cc", out.name, extra, file=sys.stderr)
    subprocess.run(a, check=True)


def link(out, obj, extra=()):
    cmd = [gcc] + shlex.split(link_flags)
    cmd[cmd.index("-Wl,-Map=" + str(p20 / "ulp_main.map"))] = f"-Wl,-Map={out.with_suffix('.map')}"
    # swap the stock linker script for P29's (LENGTH = 7856) and drop the stock map/peripherals dupes
    i = cmd.index(str(p20 / "ulp_riscv.ld"))
    cmd[i] = str(src / "ulp_p29.ld")
    cmd += list(extra) + ["-o", str(out), obj] + rest
    print("+ link", out.name, file=sys.stderr)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr, file=sys.stderr)
        raise SystemExit("LINK FAILED rc=%d" % r.returncode)


def measure(name, elf):
    binpath = elf.with_suffix(".bin")
    subprocess.run(["riscv32-esp-elf-objcopy", "-O", "binary", str(elf), str(binpath)], check=True)
    sec = subprocess.run(["riscv32-esp-elf-size", "-A", str(elf)], capture_output=True, text=True,
                         check=True).stdout
    sizes = {}
    for line in sec.splitlines():
        f = line.split()
        if len(f) == 3 and f[0].startswith("."):
            sizes[f[0]] = int(f[1])
    n = binpath.stat().st_size
    print(f"{name}: bin={n} text={sizes.get('.text')} rodata={sizes.get('.rodata', 0)} "
          f"srodata={sizes.get('.srodata.seed.0', 0)} data={sizes.get('.data', 0)} "
          f"bss={sizes.get('.bss')}", file=sys.stderr)
    return sizes, n


compile_stub(art / "ulp_stubs_only.o", ["-DP29_HARNESS_ONLY"])
link(art / "ulp_stub_only.elf", art / "ulp_stubs_only.o")
ctrl, ctxt = measure("control", art / "ulp_stub_only.elf")

# MEMSZ comes from the command line so the number in RESULT.md is the number that was linked.
memsz = int(sys.argv[1]) if len(sys.argv) > 1 else 1390
# GUARDRAIL: TIBSZ must be <= the 128 B command ring and SD must be a power of two — the brief's
# 128 B line buffer and SD=16 are part of the budget, not defaults; drop either and the link gets
# 48 B cheaper for a machine that is not the one in 4.3.
compile_stub(art / "ulp_stubs.o", [f"-DMEMSZ={memsz}", "-DSD=16", "-DTIBSZ=128", "-DNTSK=3"])
link(art / "ulp_main_p29.elf", art / "ulp_stubs.o")
sec, n = measure("P29", art / "ulp_main_p29.elf")

text = sec.get(".text", 0) - ctrl.get(".text", 0)
rodata = sec.get(".rodata", 0) - ctrl.get(".rodata", 0)
engine = n - ctxt
print(f"engine: text={text} rodata={rodata} total(.bin - control)={engine}", file=sys.stderr)
# everything the link actually placed in the 7856 B region: .text+.rodata+.data+.bss
total = sum(v for k, v in sec.items() if k in (".text", ".rodata", ".data", ".bss"))
ctrl_total = sum(v for k, v in ctrl.items() if k in (".text", ".rodata", ".data", ".bss"))
design = total - ctrl_total
print(f"region use: {total} of 7856 (harness {ctrl_total}) -> design {design}, "
      f"{7856 - design} left (MEMSZ was {memsz})", file=sys.stderr)
print("OK", file=sys.stderr)

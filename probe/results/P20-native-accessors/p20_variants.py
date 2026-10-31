#!/usr/bin/env python3
"""P20: build and measure the four variants with P12's recipe.

Variant A comes from the real `idf.py build` (artifacts/ulp_main.bin) so the 3986 B reproduction is
checked against the identical path P12 used. B/C/D are compiled from the same IDF flags
(compile_commands.json) and linked with the same LINK_FLAGS (build.ninja) — the P01 stub-subtraction
recipe: `.bin - 130` (control `.bin` 84 + pl_emit 38 + seed string 8).

GUARDRAIL: the control link must reuse the same object list minus the engine, because the ULP startup
(ulp_riscv_vectors.S + start.S, 76 B) is linked in unconditionally; subtracting the whole control .bin
would also subtract the startup the real image shares. The 130 B stub floor is compile-time
independent of the primitive set, which is why one control link serves all four variants.
"""
import json, pathlib, re, shlex, subprocess, sys

root = pathlib.Path(__file__).resolve().parent
ubu = root / "idfproj/build/esp-idf/main/ulp_main"
cc = json.load(open(ubu / "compile_commands.json"))
stub_cc = next(e for e in cc if e["file"].endswith("ulp_stubs.c"))
args = shlex.split(stub_cc["command"])
gcc = args[0]
ninja = (ubu / "build.ninja").read_text()
link_flags = re.search(r"^  LINK_FLAGS = (.*)$", ninja, re.M).group(1)
objs = re.search(r"^build ulp_main\.elf: \S+ (.*?)(?: \|\| ld_script)$", ninja, re.M).group(1).split()
objs = [str((ubu / o).resolve()) for o in objs]
stub_obj = next(o for o in objs if o.endswith("ulp_stubs.c.obj"))
rest = [o for o in objs if o != stub_obj]


def compile_stub(src, out, extra):
    # GUARDRAIL: the source path appears twice in the IDF compile command (once as the input, once
    # after -c); rewriting only one of them makes gcc see two input files and fail with
    # "cannot specify -o ... with multiple files", so replace every occurrence.
    a = [str(src) if x.endswith("ulp_stubs.c") else x for x in args]
    a[a.index("-o") + 1] = str(out)
    a += extra
    print("+", " ".join(x for x in a if not x.startswith("-I")), file=sys.stderr)
    subprocess.run(a, check=True)


def link(out, obj):
    cmd = [gcc] + shlex.split(link_flags)
    cmd[cmd.index("-Wl,-Map=" + str(ubu / "ulp_main.map"))] = f"-Wl,-Map={out.with_suffix('.map')}"
    cmd += ["-o", str(out), obj] + rest
    print("+ link", out.name, file=sys.stderr)
    subprocess.run(cmd, check=True)


def measure(name, elf):
    binpath = elf.with_suffix(".bin")
    raw = subprocess.run(["riscv32-esp-elf-objcopy", "-O", "binary", str(elf), str(binpath)],
                         check=True)
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
    return name, n, sizes


vdir = root / "variants"
compile_stub(root / "ulp_stubs.c", vdir / "ulp_stubs_only.o", ["-DP01_STUB_ONLY"])
link(vdir / "ulp_stub_only.elf", vdir / "ulp_stubs_only.o")
measure("control", vdir / "ulp_stub_only.elf")

for v in ("B", "C", "D"):
    extra = ["-DIMAGE"] if v == "D" else []
    obj = vdir / v / f"ulp_stubs_{v}.o"
    compile_stub(vdir / v / "ulp_stubs.c", obj, extra)
    link(vdir / v / f"ulp_main_{v}.elf", obj)
    measure(v, vdir / v / f"ulp_main_{v}.elf")
print("OK", file=sys.stderr)

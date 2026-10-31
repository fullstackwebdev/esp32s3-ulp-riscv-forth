#!/usr/bin/env python3
"""P12 variants: the stub-only control link and the MEMSZ=4096 blob.

Reuses the flags IDF itself generated (compile_commands.json + build.ninja), so the variants are the
supported build with one -D or one -T changed — the P01 recipe, not a new build path.

GUARDRAIL: the control link must reuse the very same object list minus the engine, because the ULP
startup (ulp_riscv_vectors.S + start.S, 76 B) is linked in unconditionally; subtracting the whole
control .bin would otherwise also subtract the startup it shares with the real image.
"""
import json, pathlib, re, shlex, subprocess, sys

root = pathlib.Path(__file__).resolve().parent
ubu = root / "idfproj/build/esp-idf/main/ulp_main"
cc = json.load(open(ubu / "compile_commands.json"))
stub_cc = next(e for e in cc if e["file"].endswith("ulp_stubs.c"))
args = shlex.split(stub_cc["command"])
cc_path = str(ubu / "CMakeFiles/ulp_main.dir/__p12__.obj")

def compile_stub(out, extra):
    a = list(args)
    a[a.index("-o") + 1] = str(out)
    a += extra
    print("+", " ".join(x for x in a if not x.startswith("-I")), file=sys.stderr)
    subprocess.run(a, check=True)

ninja = (ubu / "build.ninja").read_text()
link_flags = re.search(r"^  LINK_FLAGS = (.*)$", ninja, re.M).group(1)
objs = re.search(r"^build ulp_main\.elf: \S+ (.*?)(?: \|\| ld_script)$", ninja, re.M).group(1).split()
objs = [str((ubu / o).resolve()) for o in objs]
stub_obj = next(o for o in objs if o.endswith("ulp_stubs.c.obj"))
rest = [o for o in objs if o != stub_obj]
gcc = shlex.split(stub_cc["command"])[0]

def link(out, obj, ld_script=None):
    cmd = [gcc] + shlex.split(link_flags)
    cmd[cmd.index("-Wl,-Map=" + str(ubu / "ulp_main.map"))] = f"-Wl,-Map={out.with_suffix('.map')}"
    # GUARDRAIL: replace the generated -T script in place; appending a second -T leaves two linker
    # scripts in the command and ld silently keeps the first (that is how a "MEMSZ=4096" variant
    # gets measured against the wrong region and reports a bogus link failure).
    if ld_script is not None:
        cmd[cmd.index("-T") + 1] = str(ld_script)
    cmd += ["-o", str(out), obj] + rest
    print("+ link", out.name, file=sys.stderr)
    subprocess.run(cmd, check=True)

# 1. control image: the stub with the engine compiled out (--gc-sections drops everything it calls)
compile_stub(root / "variants/ulp_stubs_only.o", ["-DP01_STUB_ONLY"])
link(root / "variants/ulp_stub_only.elf", root / "variants/ulp_stubs_only.o")

# 2. the design's MEMSZ (P02: 32-bit xts need >= 4096): .bin only, region length raised so the
#    link succeeds — P01 F3, region length is not part of the blob.
for m in (2048, 4096):
    o = root / f"variants/ulp_stubs_memsz{m}.o"
    compile_stub(o, [f"-DMEMSZ={m}"])
    ld = ubu / "ulp_riscv.ld"
    if m == 4096:
        ld = root / "variants/ulp_riscv_bigregion.ld"
    link(root / f"variants/ulp_main_memsz{m}.elf", o, ld)
print("OK", file=sys.stderr)

#!/usr/bin/env python3
"""P35: maximise MEMSZ by construction — link until the link fails, in the shipping variant.

Starting point is P33's variant E, which IS this probe's variant: D (P32: C + I J UNLOOP GPIO! '
CONSTANT ( ." (.")) with -DP33_NOPAGE (frames, table, paged fetch out) and -DP33_BLOCK (one 512 B
buffer at the top of mem[] plus the BLKXFER primitive). No engine source is edited here; the copy in
src/ is P33's, verbatim.

Two link conventions, same objects:
  opt    src/ulp_p35_opt.ld    LENGTH 7856, __stack_top = 7856 -> sections may use all 7856
  stack  src/ulp_p35_stack.ld  LENGTH 7536, __stack_top = 7856 -> 320 B C stack carved into the pool

Search: bracketing bisection on MEMSZ, 4-byte granularity (mem[] is word-addressed), starting from the
P33-known-good 1420 and escalating until a link fails, then bisecting to the boundary. The reported
maximum is therefore a link result plus a failing link 4 B above it, not arithmetic.

GUARDRAIL: MEMSZ is only meaningful together with the script it was linked under. P22/P29/P31 quoted
MEMSZ from the 7856 LENGTH script while __stack_top sat at the region top, i.e. 320 B of the quoted
dictionary was C stack. Both scripts are measured and both numbers reported (P32 §1.2).
"""
import json, pathlib, re, shlex, subprocess, sys, time

root = pathlib.Path(__file__).resolve().parent
src = root / "src"
art = root / "artifacts"
p20 = root.parent / "P20-native-accessors" / "idfproj/build/esp-idf/main/ulp_main"

req = [l.strip() for l in (src / "p31_required.defs").read_text().split() if l.strip()]
RESTORED = ["-DP_HAVE_I", "-DP_HAVE_J", "-DP_HAVE_UNLOOP", "-DP_HAVE_GPIOS", "-DP_HAVE_TICK",
            "-DP_HAVE_CONSTANT", "-DP_HAVE_PAREN", "-DP_HAVE_DOTQ", "-DP_HAVE_PDOTQ"]
# GUARDRAIL: E's defines are P33's, not re-derived: P33_NOPAGE is the removal and P33_BLOCK is the
# buffer + BLKXFER. Re-typing them here would make this a second, differently-built machine (P31).
DEFS = ["-DP31_SUBSET"] + req + ["-DP30_HANDCOPY"] + RESTORED + ["-DP33_NOPAGE", "-DP33_BLOCK"]
BASE = ["-DSD=16", "-DTIBSZ=128", "-DNTSK=3"]

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

T0 = time.time()
DEADLINE = float(sys.argv[1]) if len(sys.argv) > 1 else 280.0


def late():
    return time.time() - T0 > DEADLINE


def compile_stub(out, extra):
    # GUARDRAIL: the source path appears twice in the IDF compile command (input and after -c);
    # rewriting only one makes gcc see two inputs and die ("cannot specify -o with multiple files").
    a = [str(src / "ulp_stubs.c") if x.endswith("ulp_stubs.c") else x for x in args]
    a[a.index("-o") + 1] = str(out)
    a += extra
    subprocess.run(a, check=True)


def link(out, obj, ld):
    cmd = [gcc] + shlex.split(link_flags)
    cmd[cmd.index("-Wl,-Map=" + str(p20 / "ulp_main.map"))] = f"-Wl,-Map={out.with_suffix('.map')}"
    cmd[cmd.index(str(p20 / "ulp_riscv.ld"))] = str(src / ld)
    cmd += ["-o", str(out), obj] + rest
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        over = re.search(r"address (0x[0-9a-f]+)", r.stderr)
        msg = (f"LINK-FAIL first over-budget address {over.group(1)}" if over
               else "LINK-FAIL " + " ".join(r.stderr.split())[:300])
        return False, msg
    return True, "OK"


def sections(elf):
    out = subprocess.run(["riscv32-esp-elf-size", "-A", str(elf)], capture_output=True, text=True,
                         check=True).stdout
    s = {}
    for line in out.splitlines():
        f = line.split()
        if len(f) == 3 and f[0].startswith("."):
            s[f[0]] = int(f[1])
    return s


def total(s):
    return s.get(".text", 0) + s.get(".rodata", 0) + s.get(".srodata.seed.0", 0) + s.get(".data", 0) \
        + s.get(".bss", 0)


compile_stub(art / "ulp_stubs_only_A.o", ["-DP29_HARNESS_ONLY"])
ok, msg = link(art / "p35_control.elf", art / "ulp_stubs_only_A.o", "ulp_p31_diag.ld")
if not ok:
    raise SystemExit("control link failed: " + msg)
ctrl_sec = sections(art / "p35_control.elf")
ctrl_bin = subprocess.run(["riscv32-esp-elf-objcopy", "-O", "binary", str(art / "p35_control.elf"),
                           str(art / "p35_control.bin")], check=True)
ctrl_n = (art / "p35_control.bin").stat().st_size
print(f"control: bin={ctrl_n} text={ctrl_sec.get('.text')} bss={ctrl_sec.get('.bss')}", file=sys.stderr)

RESULTS = {}


def attempt(mode, ld, limit, memsz):
    """One build+link at one MEMSZ. Returns (ok, total_bytes, msg)."""
    tag = f"{mode}_{memsz}"
    obj = art / f"ulp_stubs_{tag}.o"
    elf = art / f"p35_{tag}.elf"
    compile_stub(obj, [f"-DMEMSZ={memsz}"] + BASE + DEFS)
    ok, msg = link(elf, obj, ld)
    tot = total(sections(elf)) if ok else None
    print(f"[{time.time()-T0:6.1f}s] {mode:5s} MEMSZ={memsz:5d} limit={limit} -> {msg}"
          + (f", sections {tot} ({limit-tot} B left)" if ok else ""), file=sys.stderr)
    return ok, tot, msg


for mode, ld, limit in (("stack", "ulp_p35_stack.ld", 7536), ("opt", "ulp_p35_opt.ld", 7856)):
    # 1. the P33-known-good point must still link (P35's regression check)
    ok908, _, msg = attempt(mode, ld, limit, 1420)
    if not ok908:
        RESULTS[mode] = ("REGRESSION: 1420 does not link", 1420, None)
        continue
    lo, lo_tot = 1420, None
    # 2. escalate until a link fails (bounded: 8 doublings of a 128 B step is 1 KB)
    step, hi = 128, None
    while hi is None:
        cand = lo + step
        if late():
            print(f"[{time.time()-T0:6.1f}s] deadline during escalation at {mode}", file=sys.stderr)
            break
        ok, tot, msg = attempt(mode, ld, limit, cand)
        if ok:
            lo, lo_tot = cand, tot
            step *= 2
        else:
            hi = cand
    if hi is None:
        RESULTS[mode] = ("deadline in escalation", lo, lo_tot)
        continue
    # 3. bisect (lo links, hi fails) to 4-byte granularity: the largest linking MEMSZ
    while hi - lo > 4 and not late():
        mid = ((lo + hi) // 2) // 4 * 4
        if mid <= lo or mid >= hi:
            break
        ok, tot, msg = attempt(mode, ld, limit, mid)
        if ok:
            lo, lo_tot = mid, tot
        else:
            hi = mid
    # 4. prove maximality: lo links, lo+4 must fail
    if hi - lo > 4:
        ok, tot, msg = attempt(mode, ld, limit, lo + 4)
        if ok:
            lo, lo_tot = lo + 4, tot
        else:
            hi = lo + 4
    # GUARDRAIL: mem[] is a byte array and bss need not end 4-aligned, so MEMSZ is not always
    # 4-granular: at the winning image sections sat 3-5 B short of the limit, i.e. lo+1..lo+3 could
    # still link. Step them one at a time or the "largest MEMSZ" reported is up to 3 B pessimistic.
    for extra in (1, 2, 3):
        if late():
            break
        ok, tot, msg = attempt(mode, ld, limit, lo + 1)
        if not ok:
            hi = lo + 1
            break
        lo, lo_tot = lo + 1, tot
    RESULTS[mode] = (None, lo, lo_tot, hi)
    # 5. nm -S on the winning image: mem must equal MEMSZ, frm/ptab must be gone
    win = art / f"p35_{mode}_{lo}.elf"
    nm = subprocess.run(["riscv32-esp-elf-nm", "-S", str(win)], capture_output=True, text=True,
                        check=True).stdout
    (art / f"p35_{mode}_nm.txt").write_text(nm)
    sizes = {}
    for line in nm.splitlines():
        f = line.split()
        if len(f) == 4:
            try:
                sizes[f[3]] = int(f[1], 16)
            except ValueError:
                pass
    arrays = ["mem", "frm", "ptab", "ptab_lru_reserve", "tsk", "tib", "mailbox", "out_ring",
              "cmd_ring", "vm_live", "blk_out"]
    print(f"{mode} WINNER MEMSZ={lo}: " + " ".join(
        f"{a}={sizes.get(a, 'GONE')}" for a in arrays)
        + f" | sections={lo_tot} of {limit} left={limit-lo_tot}"
        + f" | boundary: {lo} links, {hi} fails", file=sys.stderr)
    subprocess.run(["riscv32-esp-elf-objcopy", "-O", "binary", str(win),
                    str(art / f"p35_{mode}_{lo}.bin")], check=True)
    print(f"  {mode} engine (.bin - control) = "
          f"{(art / f'p35_{mode}_{lo}.bin').stat().st_size - ctrl_n}", file=sys.stderr)

print(json.dumps({k: v for k, v in RESULTS.items()}, default=str), file=sys.stderr)
print("OK", file=sys.stderr)

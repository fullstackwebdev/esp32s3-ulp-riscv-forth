#!/usr/bin/env python3
# GUARDRAIL: this generator now lives in the tree that SHIPS its output. It used to exist only in a research
# copy, so probe/repl/src/p54_*.inc were files nobody could regenerate from within the shipping tree — the
# ownership gap the project forbids elsewhere ("one owner per thing"). It was verified against the shipped
# files first: running it reproduces p54_ops.h and p54_cases.inc BYTE-FOR-BYTE, so there was no drift to
# reconcile. Re-run it after editing the OP list, then re-bake: the table slots are _Static_assert'ed
# against the real enum, so a drift is a compile error rather than a wrong arithmetic operation.
#!/usr/bin/env python3
"""p54_gen.py — emit P54's table-driven binary-op artifacts from ONE ordered list.

    ./tools/p54_gen.py            # (re)write src/p54_ops.h, src/p54_cases.inc, src/p54_subset.inc

WHY A GENERATOR
Three things have to agree about the same ten primitives: the leaf that computes an op, the table slot
that names it, and the `case P_*:` label that routes the token there. Writing them by hand is the F-74 /
F-107 failure class of this project (two copies of one ordering, discovered only when a word misbehaves),
so the ordering lives here once and every artifact is derived from it.

GUARDRAIL: the table slot is derived from pids.h (`ID_<id> - ID_ADD`), and the emitted header re-asserts
every slot with a _Static_assert against the real `P_*` enum. A slot off by one does not fail — it
dispatches the WRONG arithmetic, and nothing in the suite would notice until a number came out wrong, so
the index has to be checked by the compiler, not by a comment.

GUARDRAIL: the rank of an op in OPS is the ladder rung: `-DP54_BINOPS=n` converts the first n ranks and
leaves the rest on their original hand-written bodies via `P31_SUBSET`/`P_HAVE_*`. The ranks are in enum
order on purpose, so a rung is always a prefix of the enum's id order and the table can be sized from it.
"""
import pathlib
import re
import sys

# rank, primitive id, expression. `a` is the existing top of stack, `b` the popped operand — the same
# expression is used as a leaf body (`return (expr)`) and as an inline arm (`a = (expr)`), so the two
# P54 mechanisms are guaranteed to compute the same thing.
OPS = [
    (1,  "ADD",    "a + b"),
    (2,  "SUB",    "a - b"),
    (3,  "MUL",    "a * b"),
    (4,  "AND",    "a & b"),
    (5,  "OR",     "a | b"),
    (6,  "XOR",    "a ^ b"),
    (7,  "LSHIFT", "a << (b & 31u)"),
    (8,  "RSHIFT", "a >> (b & 31u)"),
    (9,  "LT",     "((i32)a < (i32)b) ? ~0u : 0u"),
    (10, "ULT",    "(a < b) ? ~0u : 0u"),
]

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def die(msg):
    sys.exit(f"p54_gen: {msg} (refusing to emit a shape it does not understand)")


def read_ids():
    """id -> number, straight from the generated pids.h (the same file the engine's asserts check)."""
    txt = (SRC / "pids.h").read_text()
    ids = {m.group(1): int(m.group(2)) for m in re.finditer(r"#define ID_(\w+) (\d+)u?", txt)}
    if "ADD" not in ids:
        die("pids.h has no ID_ADD")
    return ids


def read_prims():
    """Every primitive id whose case body lives in p31_cases.inc, in declaration order.

    GUARDRAIL: DOCOL/DOVAR/DOCON are enum-only — they are NOT X entries in p31_prims.inc, but p31_cases.inc
    emits `case P_DOCOL:` under the same `P_HAVE_*` guard. Omitting them from the subset list deletes the
    three cases that make a colon word run at all, and the symptom is not a size regression: every compiled
    word answers `?` and tests/suite.fs fails on its first definition. Measured: -DP54_BINOPS=10 compiled and
    linked fine with .text 12 B smaller than the correct shape, which is exactly the kind of fake win a
    missing case buys.
    """
    out = ["DOCOL", "DOVAR", "DOCON"]
    for m in re.finditer(r'^X\((\w+),', (SRC / "p31_prims.inc").read_text(), re.M):
        out.append(m.group(1))
    if len(out) < 4:
        die("p31_prims.inc has no X(...) entries")
    return out


def read_extra_ids():
    """p33_prims.inc's own X entries: they have hand-written cases in p33_cases.inc, not P_HAVE_* bodies."""
    base = set(re.findall(r'^X\((\w+),', (SRC / "p31_prims.inc").read_text(), re.M))
    return [m.group(1) for m in re.finditer(r'^X\((\w+),', (SRC / "p33_prims.inc").read_text(), re.M)
            if m.group(1) not in base]


def slots():
    ids = read_ids()
    prims = read_prims()
    got = []
    for rank, pid, expr in OPS:
        if pid not in ids:
            die(f"pids.h has no ID_{pid}")
        if pid not in prims:
            die(f"p31_prims.inc has no primitive {pid}")
        got.append((rank, pid, expr, ids[pid] - ids["ADD"]))
    if [g[3] for g in got] != sorted(g[3] for g in got):
        die("OPS is not in enum order, so a -DP54_BINOPS rung is not a prefix of the table")
    return got


def emit_ops(got):
    """src/p54_ops.h — the leaves and the function-pointer table (the -DP54_BINOPS mechanism)."""
    lines = []
    w = lines.append
    w("/* p54_ops.h — GENERATED by tools/p54_gen.py. Do not edit; edit the OP list in the generator.")
    w(" *")
    w(" * GUARDRAIL: every slot is `P_<id> - P_ADD` and every one is _Static_assert'ed against the real")
    w(" * enum. P54's saving is that ten 38-44 B case bodies become one body plus one 4-6 B leaf each; a")
    w(" * table indexed one off from the enum would dispatch the WRONG arithmetic and no test would catch")
    w(" * it until a number came out wrong (F-107's shape) — hence a compiler check per slot, not a comment.")
    w(" * GUARDRAIL: an unconverted slot holds p54_op_unreachable, never 0. A null function pointer is a")
    w(" * call to address 0, i.e. DOCOL — the machine would silently run a different primitive instead of")
    w(" * reporting the hole, which is the one failure class this engine is not allowed to have.")
    w(" */")
    w("#ifndef P54_OPS_H")
    w("#define P54_OPS_H")
    w("")
    w("typedef u32 (*p54_binop_t)(u32 a, u32 b);")
    w("")
    w("/* no per-op leaf FUNCTIONS: every expression is a label inside p54_binop below. 14 leaves each paid")
    w(" * their own call framing and 4-byte table slot; as labels the table is 2 bytes per slot and the")
    w(" * expressions keep the same code. */")
    w("")
    last = max(s for _, _, _, s in got)
    for rank, pid, expr, slot in got:
        w(f'_Static_assert(P_{pid} == P_ADD + {slot}, "P54 slot drift: {pid}");')
    w("")
    w("/* the array is sized to the last slot a given rung converts, so a small rung pays a small table */")
    rungs = sorted({(r, max(s for rr, _, _, s in got if rr <= r) + 1) for r, _, _, _ in got},
                   reverse=True)
    first = True
    for rank, nslot in rungs:
        if rank < 1:
            continue
        w(f"#{'if' if first else 'elif'} P54_BINOPS >= {rank}")
        w(f"#define P54_NSLOT {nslot}")
        first = False
    w("#else")
    w('#error "P54_BINOPS must be >= 1 (it selects a rung of the P54 ladder)"')
    w("#endif")
    w("")
    w("#if !defined(P54_OPSW)")
    w("/* GUARDRAIL: one function, labels not pointers. The table is a ONE-BYTE offset from L_bad on the ULP")
    w(" * (a 4-byte pointer on the host, whose code can exceed a 16-bit span — measured: a truncated offset")
    w(" * there is a jump into nowhere). GUARDRAIL: every slot defaults to L_bad, never to 0, because 0 is a")
    w(" * valid offset (it means L_bad itself) — a zero hole would send a real operation to the halt path.")
    w(" * GUARDRAIL: u8 SPANS AT MOST 255 BYTES, so every arm must stay within 255 B of L_bad. That is not a")
    w(" * hope: the whole function was 102 B when the width was cut (nm -S p54_binop), so the arms had 2.5x")
    w(" * headroom. If arms are ever added or a body grows, CHECK THE FUNCTION'S SIZE FIRST — a truncated")
    w(" * offset does not fail, it jumps into the middle of another arm and computes the wrong operator.")
    w(" */")
    w("static u32 p54_binop(u32 cf, u32 a, u32 b)")
    w("{")
    w("#ifdef HOST")
    w("    typedef const void *p54_ent_t;")
    w("#define P54_ENT(l) ((const void *)&&l)")
    w("#else")
    w("    typedef u8 p54_ent_t;")
    w("#define P54_ENT(l) ((u8)(&&l - &&L_bad))")
    w("#endif")
    w("    static const p54_ent_t t[P54_NSLOT] = {")
    w("        [0 ... P54_NSLOT - 1] = P54_ENT(L_bad),")
    converted = {}
    for rank, pid, expr, slot in got:
        w(f"#if P54_BINOPS >= {rank}")
        w(f"        [{slot}] = P54_ENT(L_{pid}),")
        w("#endif")
        converted[slot] = rank
    w("    };")
    w("#undef P54_ENT")
    w("#ifdef HOST")
    w("    goto *t[cf - P_ADD];")
    w("#else")
    w("    goto *(&&L_bad + t[cf - P_ADD]);")
    w("#endif")
    w("L_bad: pl_halt(0x54u); return 0u;")
    for rank, pid, expr, slot in got:
        w(f"#if P54_BINOPS >= {rank}")
        w(f"L_{pid}: return ({expr});   /* slot {slot} */")
        w("#endif")
    w("}")
    w("#endif /* !P54_OPSW */")
    w("")
    w("#endif /* P54_OPS_H */")
    (SRC / "p54_ops.h").write_text("\n".join(lines) + "\n")


def emit_cases(got):
    """src/p54_cases.inc — the case labels and the ONE shared body, included inside vm_enter's switch."""
    lines = []
    w = lines.append
    w("/* p54_cases.inc — GENERATED by tools/p54_gen.py. Do not edit; edit the OP list in the generator.")
    w(" *")
    w(" * Included from p33_cases.inc INSIDE vm_enter()'s switch. The p31 bodies for these ids are gated out")
    w(" * by src/p54_subset.inc, so each token reaches exactly one body and this one is it.")
    w(" * GUARDRAIL: the labels come from the same list as the arms/table. A label without an arm would")
    w(" * compute some other operation; an arm without a label is dead code. Both are ordering bugs of the")
    w(" * kind P31's one-entry-per-line rule exists to prevent, so neither is written by hand.")
    w(" * GUARDRAIL: `b = POP()` runs before the top-of-stack address is taken, exactly as in the bodies this")
    w(" * replaces: POP() decrements V->SP (a u8, so it wraps to 255 below 0) and the (SD-1) mask is what")
    w(" * maps that to slot 15. Reordering the two changes which cell is read on an underflow.")
    w(" */")
    for rank, pid, expr, slot in got:
        w(f"#if P54_BINOPS >= {rank}")
        # GUARDRAIL: emit a LABEL, not `case`. P57 replaced the switch with a 2-byte label-offset table, so
        # every case body in this tree is a label now; regenerating with `case` produced a file whose labels
        # did not exist and the dispatch table referenced them (compile error, loud — which is why this is a
        # generated-source change and not a hand edit).
        w(f"        L_P_{pid}:" + (f"   /* P54 op {rank}, slot {slot} */" if rank == 1 else ""))
        w("#endif")
    w("")
    w("#if P54_BINOPS >= 1")
    w("        {")
    w("#if defined(P54_OPSW)")
    w("            u32 *px; u32 a;")
    w("            b = POP();")
    w("            px = &ds[(sp - 1) & (SD - 1)];   /* TOS as an lvalue: one address, one load, one store */")
    w("            a = *px;")
    w("            switch (cf - P_ADD) {")
    for rank, pid, expr, slot in got:
        w(f"#if P54_BINOPS >= {rank}")
        w(f"            case {slot}: a = ({expr}); break;")
        w("#endif")
    w("            /* a slot with no label cannot be reached; if one ever is, stop instead of computing */")
    w("            default: pl_halt(0x54u); a = 0u; break;")
    w("            }")
    w("            *px = a;")
    w("#else")
    w("            b = POP();")
    w("            TOS = p54_binop(cf, TOS, b);")
    w("#endif")
    # GUARDRAIL: `goto tail`, not `break`. Since P57 the dispatch has no switch — every body ends by jumping
    # to the loop tail. A `break` here compiles (the enclosing `for(;;)` is in scope) but exits vm_enter's
    # loop entirely, so a single P54 operation ended the word: measured as the whole prelude failing to load
    # with a garbage token. This is why the generated file must be regenerated after any dispatch change.
    w("            goto tail;")
    w("        }")
    w("#endif")
    (SRC / "p54_cases.inc").write_text("\n".join(lines) + "\n")


def emit_headers(got):
    """src/p54_headers.inc — the OTHER half of the subset gate, included before boot_init's X loop.

    GUARDRAIL: `P_HAVE_<id>` gates TWO different things — p31_cases.inc's case body AND p31_prims.inc's
    dictionary header (`#if !defined(P31_SUBSET) || defined(P_HAVE_ADD)`). P54 wants the body gone and the
    header kept, so the two include sites must disagree. Measured the other way round: -DP54_BINOPS=10 built
    cleanly with 54 of 64 dictionary words, i.e. ten primitives silently stopped existing — `1 2 OR .`
    answered `OR?`. Nothing in the suite noticed until tests/binops.fs existed, because that is the first
    test that types OR.
    GUARDRAIL: this file must be included AFTER vm_enter() (which pulls in p31_cases.inc) and BEFORE
    boot_init() (which pulls in p33_prims.inc for the headers). The macros are additive, so putting it on
    the wrong side of the cases include compiles to a duplicate `case P_ADD:` — that direction fails loudly;
    the reverse order (boot_init first) silently shrinks the dictionary again, which is why tests/run.sh
    builds host_binops and runs tests/binops.fs, a file that names all ten words.
    """
    lines = []
    w = lines.append
    w("/* p54_headers.inc — GENERATED by tools/p54_gen.py. Do not edit; edit the OP list in the generator.")
    w(" *")
    w(" * GUARDRAIL: P54 removes only the CASE BODIES of the converted ops; their dictionary headers must still")
    w(" * be laid down by boot_init() or the words stop existing. P_HAVE_* gates both sites, so this file")
    w(" * re-enables the header half after vm_enter() has consumed the body half. Include it before boot_init.")
    w(" */")
    for rank, pid, expr, slot in got:
        w(f"#if P54_BINOPS >= {rank}")
        w(f"#define P_HAVE_{pid} 1   /* header yes, body no: the P54 kernel is the body */")
        w("#endif")
    (SRC / "p54_headers.inc").write_text("\n".join(lines) + "\n")


def emit_subset(got):
    """src/p54_subset.inc — -DP31_SUBSET's P_HAVE_* list: everything except the converted ids."""
    ids = read_ids()
    prims = read_prims()
    extras = read_extra_ids()
    # GUARDRAIL: an id the generator has never heard of is a case body that silently disappears from the
    # subset build, so the whole enum is checked against what this file knows how to name — refusing to emit
    # beats emitting a subset that is one primitive short (that is how DOCOL/DOVAR/DOCON went missing).
    known = set(prims) | set(extras)
    unknown = sorted(set(ids) - known)
    if unknown:
        die(f"pids.h ids this file cannot place in the subset: {unknown}")
    converted = {pid: rank for rank, pid, _, _ in got}
    lines = []
    w = lines.append
    w("/* p54_subset.inc — GENERATED by tools/p54_gen.py. Do not edit; edit the OP list in the generator.")
    w(" *")
    w(" * GUARDRAIL: -DP31_SUBSET makes p31_cases.inc emit ONLY the bodies named P_HAVE_*: every primitive")
    w(" * that is NOT converted by P54 must be named here or its token falls through vm_enter's switch to")
    w(" * `default: err()` and the word becomes unknown — a regression no existing test covers, because")
    w(" * tests/suite.fs exercises 8 of the 63 primitives. Generated from the same list as the case bodies,")
    w(" * so the two cannot drift apart.")
    w(" * GUARDRAIL: this file defines P31_SUBSET itself so that ONE -D (-DP54_BINOPS=<rung>) is the whole")
    w(" * knob. Leaving it to the caller is how a build ends up with a subset list but no subset build.")
    w(" */")
    w("#define P31_SUBSET 1")
    w("/* the three enum-only primitives come first: their cases are in p31_cases.inc too */")
    for pid in prims:
        rank = converted.get(pid)
        if rank is not None:
            w(f"#if P54_BINOPS < {rank}")
            w(f"#define P_HAVE_{pid} 1   /* not converted at this rung: keep P31's body */")
            w("#endif")
        else:
            w(f"#define P_HAVE_{pid} 1")
    (SRC / "p54_subset.inc").write_text("\n".join(lines) + "\n")


def main():
    got = slots()
    emit_ops(got)
    emit_cases(got)
    emit_subset(got)
    emit_headers(got)
    print(f"p54_gen: {len(got)} ops, slots {[g[3] for g in got]}")
    for name in ("p54_ops.h", "p54_cases.inc", "p54_subset.inc", "p54_headers.inc"):
        print(f"  wrote src/{name}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""gen_uc.py — produce the unchecked-accessor body files from the checked ones.

    ./tools/gen_uc.py   ->  src/p33_cases_uc.inc      (switch shape)
                            src/p33_cases_cg_uc.inc   (computed-goto shape)

The rule is deliberately mechanical and deliberately narrow, because getting it wrong is a memory-safety
bug rather than a slow path:

    on a body line that mentions neither TOS nor POP(), every accessor becomes its unchecked variant.

Why that line is the boundary: an accessor whose address operand comes off the DATA stack is `! @ c@ c!
w@ w!` and TYPE, i.e. a pointer the Forth program chose, and it may be wild — the checked form answers a
wild address with a read/write of `junk` and that is the behaviour `P()` exists for. Every other address
in these bodies is V_* (an offset into mem[]), PAD, the dictionary cursor, or a token address (w, ip):
in range by construction. Lines carrying TOS/POP() keep the checked forms, so the subset is provable by
reading one predicate instead of auditing 60 bodies.

# GUARDRAIL: do not "improve" this into a per-accessor rewrite inside a mixed line. `a = rd32(V_HERE);
# wr32(a, POP());` is one line with one internal and one stack address; a substitution that fires on the
# first would also fire on the second (POP() is the operand), and `wr32u` at a stack address writes past
# mem[] into .bss — the dictionary corruption with no error, which is exactly the failure `junk` prevents.
# GUARDRAIL: names are appended with a `u` suffix, never redefined over the checked ones. If the generator
# emitted `#define rd8 rd8u` the checked accessors would vanish from find/word/mkhdr/interpret too and the
# measurement would silently describe a different program than the one the flag names.
"""
import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parent.parent
NAMES = ["rd32_paged", "rd16_paged", "rd32", "rd16", "rd8", "wr32", "wr16", "wr8"]
# longest first so rd32_paged is not half-matched by rd32
NAMES.sort(key=len, reverse=True)

STACK = re.compile(r"\bTOS\b|\bPOP\(\)")
# the unchecked accessor names exist only under -DUC_ACCESS; the paged ones keep their paged behaviour
# through the alias in uforth.c.


def convert_line(line, all_lines=False, stack_only=False):
    # `all_lines` is the CEILING measurement only: it converts the stack-operand lines too, which is a
    # memory-safety bug (see the GUARDRAIL above), so it exists to put a number on the upper bound of the
    # lever and must never be the shipping shape.
    # `stack_only` is the OTHER half of the decomposition: it converts only the unsafe lines, to show how
    # much of an "all lines" number came from the primitive bodies the safe rule refuses to touch.
    # GUARDRAIL: test stack_only BEFORE the skip-the-stack-lines test. Written the other way round the
    # stack-only run converts nothing, exits 0 on the later file, and the build then silently picks up the
    # previous shape's .inc — a row that looks like a measurement and is a copy of another row.
    if stack_only:
        if not STACK.search(line):
            return line, False
    elif STACK.search(line) and not all_lines:
        return line, False
    # GUARDRAIL: convert only the code part of the line. A trailing comment that names an accessor
    # (`/* re-fetch rd16(w) in the new machine */`) would otherwise be rewritten too, and then the
    # generated file's diff claims a change that no instruction backs — a comment-level lie inside the
    # artifact an acceptance review reads.
    code, sep, comment = line.partition("/*")
    out = code
    for n in NAMES:
        # a word boundary on both sides: rd8( -> rd8u( , but not inside an identifier
        if n.endswith("_paged"):
            out = re.sub(r"\b" + n + r"\(", n + "_u(", out)
        else:
            out = re.sub(r"\b" + n + r"\(", n + "u(", out)
    out = out + sep + comment
    return out, out != line


def convert(text, name, all_lines=False, stack_only=False):
    hits = 0
    lines = []
    for line in text.splitlines(keepends=True):
        new, changed = convert_line(line, all_lines, stack_only)
        hits += changed
        lines.append(new)
    if hits == 0:
        sys.exit(f"gen_uc: no accessor converted in {name} — the flag would price nothing")
    return "".join(lines), hits


ALL = "--all" in sys.argv
STACKONLY = "--stack" in sys.argv
SUFFIX = "_all" if ALL else ("_stack" if STACKONLY else "")
for src_name, dst_name in (("p31_cases.inc", f"p33_cases_uc{SUFFIX}.inc"),
                           ("p33_cases_cg.inc", f"p33_cases_cg_uc{SUFFIX}.inc")):
    src = root / "src" / src_name
    if not src.exists():
        sys.exit(f"gen_uc: {src_name} missing — run tools/gen_cg.py first")
    text = src.read_text()
    # the switch shape is three files (p33 wrapper -> p31 bodies), the computed-goto shape is already
    # flat: compose the wrapper here so both outputs are self-contained and can be included directly.
    if src_name == "p31_cases.inc":
        w33 = (root / "src" / "p33_cases.inc").read_text()
        INC = '#include "p31_cases.inc"'
        if INC not in w33:
            sys.exit("gen_uc: p33_cases.inc no longer includes p31_cases.inc — refusing to guess the layout")
        head33, tail33 = w33.split(INC)
        text = text + "\n" + tail33
        prefix = head33 + "\n"
    else:
        prefix = ""
    body, hits = convert(text, src_name, ALL, STACKONLY)
    head = (
        f"/* {dst_name} — GENERATED by tools/gen_uc.py from {src_name}. Do not edit.\n"
        " * Same bodies, with the bounds-checked accessors replaced by the unchecked ones on every line\n"
        " * whose address operand is not a stack cell (see the rule in tools/gen_uc.py). */\n"
    )
    (root / "src" / dst_name).write_text(head + prefix + body)
    print(f"gen_uc: {src_name} -> {dst_name}: {hits} lines converted")

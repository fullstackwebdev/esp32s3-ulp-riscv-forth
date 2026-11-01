#!/usr/bin/env python3
"""lint_forth.py - static checks for Forth programs that will be compiled on the chip.

Four rules, each one earned by a real bug (see docs/24-dispatch.md):

  R1 comment    a `\\` comment in a block source compiles as WORDS (blocks have no line boundaries).
                Measured: a comment containing "poll:" produced `POLL:?` at compile time.
  R2 order      a word used before it is defined / not defined at all. Measured: `JK?`, `ACT?`.
  R3 underflow  a body pops more than it can hold. Measured: `: JK ... 107 = ... DROP ;` - the second
                comparison consumed the key, the trailing DROP underflowed, and the sticky overflow
                killed a running program three steps later with ERR_STACK.
  R4 leak       a body leaves items nobody asked for. Measured: `: INV ESC CSI 55 M ;` pushed the digit
                '7' and never emitted it - one cell per colour change, ~8 per frame = overflow.

Stack effects come from a table for the machine's own words, plus `( in -- out )` declarations for the
program's words. A definition without a declaration is assumed ( -- ), which is what most of them are; a
word that genuinely passes values must say so, and that declaration is documentation too.

    tools/lint_forth.py examples/tui_min.fs        lint a file (exit 1 on findings)
    tools/lint_forth.py --selftest                 prove every rule fires on the bug it came from
"""
import re
import sys

# (name, pops, pushes). Control-flow words are listed so a body can use them, handled specially below.
PRIMS = {
    # GUARDRAIL: the words the launcher needs that the first table missed - EXECUTE (1,0), BLKXFER (2,2), KEY?/LOAD.
    # A missing entry reads as "undefined word" in perfectly good code, which is the fastest way to make a linter hated.
    "EXECUTE": (1, 0), "OVL": (1, 0), "BLKXFER": (2, 2), "KEY?": (0, 1), "LOAD": (1, 0), "SAVE": (0, 0), "UPDATE": (0, 0),
    # GUARDRAIL: machine variables are WORDS that push an address: `W @` is 1 push, not 0. Listing them as unknown
    # made a real launcher look like it used an undefined word.
    "HERE": (0, 1), "LATEST": (0, 1), "bh": (0, 1), "bl": (0, 1), "VH": (0, 1), "VL": (0, 1), "SEAL": (0, 0), "SD": (0, 1),
    "!": (2, 0), "*": (2, 1), "+": (2, 1), "-": (2, 1), "<": (2, 1), "=": (2, 1), "<>": (2, 1),
    "0=": (1, 1), "1+": (1, 1), "1-": (1, 1), "@": (1, 1), "AND": (2, 1), "OR": (2, 1), "XOR": (2, 1),
    "INVERT": (1, 1), "LSHIFT": (2, 1), "RSHIFT": (2, 1), "U<": (2, 1), "U/MOD": (2, 2),
    "/MOD": (2, 2), "C@": (1, 1), "C!": (2, 0), "W@": (1, 1), "W!": (2, 0), "@!": (2, 0),
    "DUP": (1, 2), "DROP": (1, 0), "SWAP": (2, 2), "OVER": (2, 3), "ROT": (3, 3), "NIP": (2, 1),
    "EMIT": (1, 0), "TYPE": (2, 0), ".": (1, 0), "MS": (1, 0), "KEY": (0, 1), "KEY?": (0, 1),
    "HERE": (0, 1), "LATEST": (0, 1), "STATE": (0, 1), "BLOCK": (1, 1), "UPDATE": (0, 0),
    "SAVE": (0, 1), "LOAD": (1, 0), "BLKXFER": (2, 2), "CREATE": (0, 0), ",": (1, 0), "ALLOT": (1, 0),
    "PAUSE": (0, 0), "WAKE": (0, 0), ">R": (1, 0), "R>": (0, 1), "I": (0, 1), "J": (0, 1),
    "UNLOOP": (0, 0), '."': (0, 0), "SPACE": (0, 0), "CR": (0, 0),
}
CONTROL = {"IF", "ELSE", "THEN", "BEGIN", "UNTIL", "WHILE", "REPEAT", "AGAIN", "DO", "LOOP", "+LOOP", "EXIT"}


def tokens(text):
    """Tokenise one definition body: drop `( ... )` declarations and `."` strings, keep everything else."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1; continue
        if c == "(":                                    # declaration / comment
            j = text.find(")", i)
            i = n if j < 0 else j + 1
            continue
        if text.startswith('."', i):                    # string literal up to the next quote
            j = text.find('"', i + 2)
            out.append('."')
            i = n if j < 0 else j + 1
            continue
        j = i
        while j < n and text[j] not in " \t\r\n":
            j += 1
        out.append(text[i:j]); i = j
    return out


def is_num(t):
    return bool(re.fullmatch(r"-?\d+", t))


def declared(body):
    """Read `( a b -- c )` from a definition body: returns (pops, pushes) or None."""
    m = re.search(r"\(([^)]*)\)", body)
    if not m:
        return None
    parts = m.group(1).split("--")
    left = [t for t in parts[0].split() if t not in ("",)]
    right = [t for t in parts[1].split()] if len(parts) > 1 else []
    return len(left), len(right)


def collect_vocab(src):
    """Vocabulary a resident file exports: `CREATE`/`CONSTANT` names and every `: name ( in -- out )` effect.

    GUARDRAIL: a program image is compiled against the RESIDENT dictionary but is a separate file, so linting it alone
    reports every resident word as undefined. That is a false positive on the one layout the machine actually ships.
    """
    v = {}
    for m in re.finditer(r"(?:CREATE|CONSTANT)\s+(\S+)", src):
        v[m.group(1)] = (0, 1)
    for m in re.finditer(r":\s+(\S+)(.*?);", src, re.S):
        v[m.group(1)] = declared(m.group(2)) or (0, 0)
    return v


def lint_definitions(src, base=None):
    """Yield findings for a source file. R1 runs over raw lines; R2/R3/R4 run per definition."""
    findings = []
    # GUARDRAIL: R1 must scan OUTSIDE parentheses and `."` strings. The earlier regex missed a comment that followed
    # code on the same line, and the app then compiled the words `poll:` and `the` - which is exactly what R1 exists for.
    i, line_no, in_str = 0, 1, False
    while i < len(src):
        c = src[i]
        if c == "\n":
            line_no += 1; i += 1; in_str = False; continue
        if in_str:
            if c == '"': in_str = False
            i += 1; continue
        if src.startswith('."', i):
            in_str = True; i += 2; continue
        if c == "(":
            j = src.find(")", i)
            if j < 0: break
            line_no += src[i:j].count("\n"); i = j + 1; continue
        if c == "\\":
            findings.append((line_no, "R1 comment",
                             "`\\` comment in a block source: a block has no line boundaries, so this compiles as words"))
            j = src.find("\n", i); i = len(src) if j < 0 else j
            continue
        i += 1
    vocab = dict(PRIMS)
    if base:
        vocab.update(base)
    # GUARDRAIL: a CREATE'd or CONSTANT word PUSHES its address/value - (0, 1), not (0, 0). Modelling it as "pushes
    # nothing" made every later `SEL @` look like an underflow, which is a false positive on perfectly good code.
    for m in re.finditer(r"(?:CREATE|CONSTANT)\s+(\S+)", src):
        vocab[m.group(1)] = (0, 1)
    for m in re.finditer(r":\s+(\S+)(.*?);", src, re.S):
        name, body = m.group(1), m.group(2)
        lineno = src[:m.start()].count("\n") + 1
        eff = declared(body)
        pops_in, pushes_out = eff if eff else (0, 0)
        depth = pops_in
        frames = []          # BEGIN/WHILE frames: {"entry": depth, "exit": depth-or-None}
        bad = False
        import os as _os
        if _os.environ.get('LINTDBG'): print(f'  [dbg] {name}: start depth={depth} pops={pops_in} pushes={pushes_out}')
        # GUARDRAIL: `0 UNTIL` never loops back, so everything after that loop is dead and the definition's end depth
        # is unreachable. A demo that runs until `q` returns through EXIT, so its leftover loop counter is not a leak -
        # the rule is "the end depth must balance IF the end can be reached".
        toks = tokens(body)
        infinite = any(toks[i - 1] == "0" and toks[i] == "UNTIL" for i in range(1, len(toks)))
        skip = 0
        for tk in toks:
            if skip:                # inside a dead arm: only track nesting, touch neither depth nor vocab
                if tk in ("IF", "BEGIN"): skip += 1
                elif tk in ("THEN", "ELSE", "UNTIL", "REPEAT"):
                    skip -= 1
                    if skip == 0:
                        if tk == "THEN" and frames:
                            fr = frames.pop()
                            if fr.get("if"): depth = fr["z0"]
                        elif tk == "ELSE" and frames:
                            depth = frames[-1]["z0"]
                continue
            if tk == "EXIT":      # after EXIT the rest of the arm is dead: skip to ELSE/THEN, keep the join depth
                if frames and frames[-1].get("if"):
                    skip = 1
                    continue
                bad = True; break
            if tk in CONTROL:
                if tk == "IF":
                    depth -= 1
                    if depth < 0:
                        findings.append((lineno, "R3 underflow", f"{name}: IF with nothing on the stack")); bad = True; break
                    # GUARDRAIL: IF saves the JOIN depth (after popping the flag). Both arms must end there, and the
                    # fall-through path certainly does - the then-arm ends with EXIT, whose dead code must not decide
                    # the depth. Without this, `DUP 113 = IF ... EXIT THEN` looked like it left nothing.
                    # GUARDRAIL: record BOTH the join depth (z0, for the dead-arm path) and each arm's end. A well-formed
                    # IF/ELSE/THEN leaves the same depth on both arms; `.N` legitimately consumes `n` in each arm, so
                    # forcing `depth = z0` at THEN reported a leak in perfect code. z0 is only the answer when the
                    # then-arm ends in EXIT, because then the fall-through is the path that runs.
                    frames.append({"entry": depth, "exit": None, "if": True, "z0": depth,
                                   "then_end": None, "has_else": False})
                elif tk == "ELSE":
                    if not frames or not frames[-1].get("if"):
                        findings.append((lineno, "R3 underflow", f"{name}: ELSE without IF")); bad = True; break
                    frames[-1]["then_end"] = depth       # remember where the then-arm ended
                    frames[-1]["has_else"] = True
                    depth = frames[-1]["z0"]             # the else-arm starts from the join depth
                elif tk == "THEN":
                    if frames:
                        fr = frames.pop()
                        if fr.get("if") and fr["has_else"] and depth != fr["then_end"]:
                            findings.append((lineno, "R6 if/else", f"{name}: arms leave {fr['then_end']} vs {depth} item(s)"))
                            bad = True; break
                elif tk == "BEGIN":
                    frames.append({"entry": depth, "exit": None})
                elif tk == "WHILE":
                    depth -= 1
                    if depth < 0:
                        findings.append((lineno, "R3 underflow", f"{name}: WHILE with nothing to test")); bad = True; break
                    if frames: frames[-1]["exit"] = depth
                elif tk == "UNTIL":
                    depth -= 1
                    if depth < 0:
                        findings.append((lineno, "R3 underflow", f"{name}: UNTIL with nothing to test")); bad = True; break
                    if frames:
                        fr = frames.pop()
                        if depth != fr["entry"]:
                            findings.append((lineno, "R5 loop leak",
                                             f"{name}: loop body leaves {depth - fr['entry']:+d} item(s) per iteration"))
                            bad = True; break
                elif tk == "REPEAT":
                    if frames:
                        fr = frames.pop()
                        # GUARDRAIL: REPEAT does NOT restore the entry depth. The loop-back path must leave exactly the
                        # entry depth (checked here - this is the rule that catches a poll loop leaking the "no key" -1),
                        # and the continuation after the loop starts from the depth recorded at the matching WHILE.
                        if depth != fr["entry"]:
                            findings.append((lineno, "R5 loop leak",
                                             f"{name}: loop body leaves {depth - fr['entry']:+d} item(s) per iteration"))
                            bad = True; break
                        depth = fr["exit"] if fr["exit"] is not None else fr["entry"]
                elif tk == "EXIT":
                    bad = True            # other paths continue; a linear walk cannot follow them
                    break
                continue
            if is_num(tk):
                depth += 1
                continue
            if tk not in vocab:
                findings.append((lineno, "R2 order", f"{name}: `{tk}` is not defined before this point"))
                bad = True
                break
            if _os.environ.get('LINTDBG'): print(f'  [dbg] {name}: tk={tk!r} depth={depth} vocab={vocab.get(tk)}')
            p_in, p_out = vocab[tk]
            depth -= p_in
            if depth < 0:
                findings.append((lineno, "R3 underflow",
                                 f"{name}: `{tk}` needs {p_in} item(s), the body only has {p_in + depth}"))
                bad = True
                break
            depth += p_out
        if _os.environ.get('LINTDBG'): print(f'  [dbg] {name}: end depth={depth} bad={bad}')
        if not bad and not infinite and depth != pushes_out:
            findings.append((lineno, "R4 leak",
                             f"{name}: leaves {depth} item(s) but declares {pushes_out} - add `( ... -- ... )` or fix the body"))
        vocab[name] = (pops_in, pushes_out)
    return findings


BUGS = {
 "missing DUP (our JK bug)": """: JK DUP 106 = IF DROP NEXT EXIT THEN 107 = IF PREV EXIT THEN DROP ;
: ACT DUP 13 = IF DROP PICKED EXIT THEN JK ;
: PICKED ;
: NEXT ; : PREV ;
""",
 "leaking digit (our INV bug)": """: M 109 EMIT ;
: INV ( -- ) ESC CSI 55 M ;
: ESC ( -- ) ;
: CSI ( -- ) ;
""",
 "used before defined (our ACT bug)": """: ACT ( -- ) JK ;
: JK ( -- ) ;
""",
 "poll loop leak (our K0 bug)": """: KEY ( -- c ) ;
: K0 ( -- c ) BEGIN KEY DUP -1 = 0= UNTIL ;
""",
 "comment compiles as words": """\\ poll: drop the -1 marker
: K0 ( -- ) ;
""",
}
GOOD = """: WAIT ( -- c ) BEGIN KEY DUP -1 = WHILE DROP REPEAT ;
: JK ( c -- ) DUP 106 = IF DROP WAIT DROP EXIT THEN DUP 107 = IF DROP WAIT DROP EXIT THEN DROP ;
"""


def selftest():
    ok = True
    for name, src in BUGS.items():
        f = lint_definitions(src)
        hit = bool(f)
        ok = ok and hit
        print(f"  {'caught' if hit else 'MISSED'}  {name:38} {f[0][1] if f else ''}")
    f = lint_definitions(GOOD)
    ok = ok and not f
    print(f"  {'clean ' if not f else 'FALSE+'}  good source (must be silent)      {f[:1] if f else ''}")
    print(f"  selftest: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv):  # GUARDRAIL: argument order matters - `--use` files must be collected BEFORE the target is linted.
    if "--selftest" in argv:
        return selftest()
    if not argv:
        print(__doc__); return 2
    base, rest = {}, []
    i = 0
    while i < len(argv):
        if argv[i] == "--use":
            base.update(collect_vocab(open(argv[i + 1]).read())); i += 2
        else:
            rest.append(argv[i]); i += 1
    src = open(rest[0]).read()
    findings = lint_definitions(src, base)
    for ln, rule, msg in findings:
        print(f"  {argv[0]}:{ln}: {rule}: {msg}")
    print(f"  {len(findings)} finding(s)" if findings else "  clean")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

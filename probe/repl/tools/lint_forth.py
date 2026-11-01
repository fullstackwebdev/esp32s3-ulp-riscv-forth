#!/usr/bin/env python3
"""lint_forth.py - static checks for Forth programs that will be compiled on the chip.

Each rule was earned by a real bug (see docs/24-dispatch.md, docs/25-program-library.md):

  R1 comment    a `\\` comment in a block source compiles as WORDS (blocks have no line boundaries).
                Measured: a comment containing "poll:" produced `POLL:?` at compile time.
  R2 order      a word used before it is defined / not defined at all. Measured: `JK?`, `ACT?`.
  R3 underflow  a body pops more than it can hold. Measured: `: JK ... 107 = ... DROP ;` - the second
                comparison consumed the key, the trailing DROP underflowed, and the sticky overflow
                killed a running program three steps later with ERR_STACK.
  R4 leak       a body leaves items nobody asked for. Measured: `: INV ESC CSI 55 M ;` pushed the digit
                '7' and never emitted it - one cell per colour change, ~8 per frame = overflow.
  R7 byte range an EMIT argument that is not provably 32..126. EMIT is the RAW byte path, and every byte
                >= 0x80 is the console's MESSAGE-CODE space (src/msg_codes.h), so a "digit" built with
                `48 +` stops being a digit at 897 and prints other people's messages: measured on the
                device, `900 .N` answered `ERR_BUSY` and `1000 .N` answered `ERR_ULPCODE 0x94`.
  R8 key -1     KEY returns -1 for "no key". A body that reads KEY, never tests -1 and has no other
                pacing treats "nothing" as a keystroke, so its loop runs flat out: measured as a spinner
                drawing 267 frames/s (16 KB in 4 s) instead of one frame per press.
  R10 block start  a block may not BEGIN with a word that consumes the stack. A block is a LINE and every line
                starts with an empty stack (`run_line()` does `sp = 0`), so anything the previous block pushed is
                gone. Measured: `fsplit` cut `: SWITCH ... ; 40` | `CONSTANT IMGP ...`, and the device answered
                `block 87: ERR_STACK` plus five `NAME?` lines naming words that were fine.
  R11 fit       a definition that cannot fit one 92 B block. The splitter refuses it at UPLOAD time - a board round
                trip to learn something a parser can see. Measured: two demo phases were written at 94 and 96 B and
                only failed when the chip was already flashing.
  R9 (RETIRED)  `MS does not sleep` was earned when the primitive returned the wake count (measured: twenty
                `200 MS` in 0.05 s). MS now busy-waits on rdcycle (tests/ms_clock.py: 100 MS = +100 ms,
                300 MS = +301 ms), so the rule's premise is gone and it was removed instead of left as
                folklore. `MS` still SPINS - nothing else runs during it - but that is a property, not a bug:
                a paced loop that ignores -1 for 250 ms is normal terminal code (examples/demo_spin.fs).

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
    "HERE": (0, 1), "LATEST": (0, 1), "bh": (0, 1), "bl": (0, 1), "VH": (0, 1), "VL": (0, 1), "SEAL": (0, 0), 
    "!": (2, 0), "*": (2, 1), "+": (2, 1), "-": (2, 1), "<": (2, 1),  "=": (2, 1), "<>": (2, 1),
    # GUARDRAIL: `>` was missing while `<` was present - a gap the lint selftest caught the moment a fixture used
    # it, and the kind of gap that reports "undefined word" in code the chip compiles happily.
    "0=": (1, 1), "1+": (1, 1), "1-": (1, 1), "@": (1, 1), "AND": (2, 1), "OR": (2, 1), "XOR": (2, 1),
    "INVERT": (1, 1), "LSHIFT": (2, 1), "RSHIFT": (2, 1), "U<": (2, 1), "U/MOD": (2, 2),
    # GUARDRAIL: `MOD` does NOT exist (only `/MOD`), and neither do `/`, `>`, `@!`, `ALLOT`, `CR`, `SD` or `SPACE`.
    # This table said MOD existed, linted a launcher containing `100 MOD` as CLEAN, and the chip answered `MOD?` while
    # compiling block 79 - a linter that certifies a word the machine lacks is worse than no linter, because it is
    # believed. tests/lint_vocab.py now asks the DEVICE about every entry here, and the duplicates that used to sit in
    # this dict (KEY?, HERE, LATEST, UPDATE, SAVE, LOAD, BLKXFER, silently won by whichever came last) are gone.
    "/MOD": (2, 2), "C@": (1, 1), "C!": (2, 0), "W@": (1, 1), "W!": (2, 0),
    "DUP": (1, 2), "DROP": (1, 0), "SWAP": (2, 2), "OVER": (2, 3), "ROT": (3, 3), "NIP": (2, 1),
    "EMIT": (1, 0), "TYPE": (2, 0), ".": (1, 0), "MS": (1, 0), "KEY": (0, 1),
    "STATE": (0, 1), "BLOCK": (1, 1), "CREATE": (0, 0), ",": (1, 0),
    "PAUSE": (0, 0), "WAKE": (0, 0), ">R": (1, 0), "R>": (0, 1), "I": (0, 1), "J": (0, 1),
    "UNLOOP": (0, 0), '."': (0, 0),
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


# ---- R7: a tiny interval analysis, only for the byte an EMIT receives -------------------------------------
# Intervals are (lo, hi) or None = "unknown". None is the answer for anything read from memory, a key, or a
# word whose body we have not modelled; that is deliberate, because a wrong bound is how a linter lies.
def r_add(a, b):
    return None if a is None or b is None else (a[0] + b[0], a[1] + b[1])


def r_sub(a, b):
    return None if a is None or b is None else (a[0] - b[1], a[1] - b[0])


def r_mul(a, b):
    if a is None or b is None:
        return None
    c = [a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1]]
    return (min(c), max(c))


def xfer(tk, rs):
    """Apply one token to the interval stack `rs` in place. `rs` is padded to the current depth by the caller."""
    def pop(n=1):
        out = []
        for _ in range(n):
            out.append(rs.pop() if rs else None)
        return out

    if tk == "DUP":
        rs.append(rs[-1] if rs else None); return []
    if tk == "DROP":
        pop(); return []
    if tk == "SWAP":
        a, b = pop(2); rs.extend([a, b]); return []
    if tk == "OVER":
        rs.append(rs[-2] if len(rs) >= 2 else None); return []
    if tk == "NIP":
        a, b = pop(2); rs.append(a); return []
    if tk == "ROT":
        a, b, c = pop(3); rs.extend([b, c, a]); return []
    if tk == "1+":
        rs.append(r_add(pop()[0], (1, 1))); return []
    if tk == "1-":
        rs.append(r_add(pop()[0], (-1, -1))); return []
    if tk == "+":
        b, a = pop(2); rs.append(r_add(a, b)); return []
    if tk == "-":
        b, a = pop(2); rs.append(r_sub(a, b)); return []
    if tk == "*":
        b, a = pop(2); rs.append(r_mul(a, b)); return []
    if tk == "AND":
        # GUARDRAIL: `x m AND` clears every bit above m, so the result is 0..m for ANY x - true for a negative x
        # too, because the mask is applied to the 32-bit two's complement. This is the one bound worth trusting.
        b, a = pop(2)
        m = None
        for r in (a, b):
            if r is not None and r[0] == r[1] and r[0] >= 0:
                m = r[0]
        rs.append((0, m) if m is not None else None); return []
    if tk == "MOD":
        b, a = pop(2)
        # GUARDRAIL: only when the dividend is provably non-negative. Forth leaves MOD's sign open for a negative
        # dividend, and inventing (0, m-1) there would hide exactly the negative byte R7 exists to catch.
        if b is not None and b[0] == b[1] and b[0] > 0 and a is not None and a[0] >= 0:
            rs.append((0, b[1] - 1))
        else:
            rs.append(None)
        return []
    if tk in ("/MOD", "U/MOD"):
        b, a = pop(2)
        if b is not None and b[0] == b[1] and b[0] > 0 and a is not None and a[0] >= 0:
            rs.extend([(0, b[1] - 1), (0, a[1] // b[0])])
        else:
            rs.extend([None, None])
        return []
    if tk == "C@":
        pop(); rs.append((0, 255)); return []
    if tk == "KEY":
        # GUARDRAIL: -1 is a real KEY value here, so the low bound is negative, not 0. R8 is what complains about it.
        rs.append((-1, 255)); return []
    return None            # not modelled: caller pushes p_out unknowns


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
        rs = []              # R7: interval per stack item, kept in step with `depth`
        toks = tokens(body)
        # GUARDRAIL: R8, whole-definition (not per token). KEY yields -1 for "no key" on this machine, and a body that
        # reads it without ever testing -1 treats "nothing" as a keystroke: measured as a spinner drawing 267 frames/s
        # and printing 16 KB in 4 s, whose counter then walked into the message-code space. A filter counts as a test:
        # `KEY 0 >` separates -1 from a real byte just as well as `KEY -1 =`.
        # GUARDRAIL: the "and no pacing" clause is not a loophole, it is the measurement. The runaway happened because
        # -1 counted as a keystroke AND nothing bounded the loop; a loop that waits 250 ms per pass with `MS` cannot
        # flood even though it too ignores -1 (examples/demo_spin.fs). Firing on that one would teach the operator to
        # ignore R8, which is how a linter dies.
        if ("KEY" in toks and "-1" not in toks and "MS" not in toks
                and not any(toks[i] == "0" and toks[i + 1] in (">", "<") for i in range(len(toks) - 1))):
            findings.append((lineno, "R8 key -1",
                             f"{name}: reads KEY, never tests -1, and has no pacing - `nothing` counts as a keystroke,"
                             " so this loop runs flat out"))
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
                while len(rs) < depth: rs.append(None)
                rs[-1] = (int(tk), int(tk))
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
            # GUARDRAIL: `rs` must hold exactly the items this word CONSUMES before its transfer runs, and exactly
            # `depth` after it - padding it to the post-word depth first made DUP look like it pushed two items and
            # desynchronised every later judgement.
            while len(rs) < depth + p_in: rs.append(None)
            while len(rs) > depth + p_in: rs.pop()
            if tk == "EMIT":
                # GUARDRAIL: R7. `EMIT` writes the byte as-is and the host reads anything >= 0x80 as a MESSAGE CODE,
                # so an out-of-range "character" prints someone else's sentence or `ERR_ULPCODE`. Only a provable
                # 32..126 passes; `AND`/`MOD` are how a body proves it (see DIGIT in examples/menu.fs).
                # GUARDRAIL: the boundary is 0x7F, not 32. Control bytes below 32 are the ANSI escapes this machine
                # draws with (`ESC` = 27, `SENT` = 0), and src/msg_codes.h says so: the reserved space starts at 0x80.
                # A rule that rejected 27 would have flagged every working drawing word and been turned off.
                r = rs[-1] if rs else None
                if r is None or r[0] < 0 or r[1] > 127:
                    findings.append((lineno, "R7 byte range",
                                     f"{name}: EMIT gets {('an unbounded value' if r is None else f'{r[0]}..{r[1]}')}" +
                                     ", not a provable 0..127 - bytes >= 0x80 are the console's message codes"))
                    bad = True
                    break
            # GUARDRAIL: R9 (`MS` does not sleep) lived here and is RETIRED, not silently dropped: the primitive now
            # busy-waits on rdcycle, so keeping the rule would make it a lie about the machine it runs on. The fixture
            # below still measures the thing that mattered - see tests/ms_clock.py.
            else:
                if xfer(tk, rs) is None:
                    for _ in range(p_out):
                        rs.append(None)
            depth += p_out
            while len(rs) < depth: rs.append(None)
            while len(rs) > depth: rs.pop()
        if _os.environ.get('LINTDBG'): print(f'  [dbg] {name}: end depth={depth} bad={bad}')
        if not bad and not infinite and depth != pushes_out:
            findings.append((lineno, "R4 leak",
                             f"{name}: leaves {depth} item(s) but declares {pushes_out} - add `( ... -- ... )` or fix the body"))
        vocab[name] = (pops_in, pushes_out)
    return findings


# (source, the ONE rule it exists to prove). Naming the rule matters: the first version only asserted "something
# fired", so a fixture with an unrelated leak counted as a catch, and three of these bugs were never actually proven.
def check_blocks(src, base=None, blocks=None):
    """R10 + R11: checks that are about the BLOCK SPLIT, not about a definition."""
    from fsplit import split_defs
    findings = []
    if blocks is None:
        try:
            blocks = split_defs(src, 92)
        except SystemExit as e:
            return [(1, "R11 fit", str(e))]
    vocab = dict(PRIMS)
    # GUARDRAIL: the DEFINITION-time effects of the words that build the dictionary. `CONSTANT` pops the value it is
    # named with, and `,` pops the cell it appends - modelling them as (0,0) made R10 blind to the exact cut that bit
    # us (`... ; 40` | `CONSTANT IMGP ...`), which the selftest caught immediately.
    vocab.setdefault("CONSTANT", (1, 0))
    vocab.setdefault(",", (1, 0))
    vocab.setdefault("VARIABLE", (0, 0))
    if base:
        vocab.update(base)
    for m in re.finditer(r"(?:CREATE|CONSTANT)\s+(\S+)", src):
        vocab[m.group(1)] = (0, 1)
    for m in re.finditer(r":\s+(\S+)(.*?);", src, re.S):
        vocab[m.group(1)] = declared(m.group(2)) or (0, 0)
    for i, blk in enumerate(blocks, start=1):
        toks = tokens(blk)
        if not toks:
            continue
        first = toks[0]
        if first in (";", ",", "THEN", "ELSE", "UNTIL", "REPEAT", "AGAIN") or first in CONTROL:
            # GUARDRAIL: a cut landed on a token that cannot start anything. That is a splitter defect, and the chip's
            # symptom is an error naming a word several blocks away - `block 87: ERR_STACK`, then `HDR0?`, `IMGS?`.
            findings.append((i, "R10 block start",
                             f"block {i} begins with `{first}`, which cannot start a block"))
            continue
        if is_num(first):
            continue
        p_in, _ = vocab.get(first, (0, 0))
        if p_in > 0:
            findings.append((i, "R10 block start",
                             f"block {i} begins with `{first}`, which needs {p_in} item(s) from the stack - a block is a "
                             "line, and every line starts empty (run_line: sp = 0)"))
    return findings


BUGS = {
 "missing DUP (our JK bug)":
   (""": JK DUP 106 = IF DROP NEXT EXIT THEN 107 = IF PREV EXIT THEN DROP ;
: ACT DUP 13 = IF DROP PICKED EXIT THEN JK ;
: PICKED ;
: NEXT ; : PREV ;
""", "R3 underflow"),
 "leaking digit (our INV bug)":
   (""": M 109 EMIT ;
: INV ( -- ) ESC CSI 55 M ;
""", "R2 order"),
 "used before defined (our ACT bug)":
   (""": ACT ( -- ) JK ;
: JK ( -- ) ;
""", "R2 order"),
 "poll loop leak (our K0 bug)":
   (""": K0 ( -- c ) BEGIN KEY DUP -1 = 0= UNTIL ;
""", "R5 loop leak"),
 "value crossing a block boundary (our CONSTANT split)":
   ("""KIND_BLOCKS""", "R10 block start"),
 "comment compiles as words":
   ("""\\ poll: drop the -1 marker
: K0 ( -- ) ;
""", "R1 comment"),
 # The two below are today's spinner flood, and each one is a separate cause of it. (A third rule, R9, said "MS does
# not sleep"; it was retired when MS got a clock, and the paced-fixture line in GOOD keeps that pattern covered.)
 "unbounded EMIT (our ERR_ULPCODE flood)":
   (""": DIGIT ( n -- ) 48 + EMIT ;
: N2 ( n -- ) DIGIT ;
""", "R7 byte range"),
 "KEY without the -1 test (our flat-out spinner)":
   (""": RUNS ( -- ) BEGIN KEY DUP 113 = IF DROP EXIT THEN DROP 0 UNTIL ;
""", "R8 key -1"),
}
# The corrected versions of every bug above, in one source: it must lint SILENT, or the rules are just noise.
GOOD = """: WAIT ( -- c ) BEGIN KEY DUP -1 = WHILE DROP REPEAT ;
: JK ( c -- ) DUP 106 = IF DROP WAIT DROP EXIT THEN DUP 107 = IF DROP WAIT DROP EXIT THEN DROP ;
: DIGIT ( n -- ) 15 AND 48 + EMIT ;
: .N ( n -- ) 100 /MOD DROP DUP 10 < IF DIGIT ELSE 10 /MOD DIGIT DIGIT THEN ;
: RUNS ( -- ) BEGIN WAIT DUP 113 = IF DROP EXIT THEN DROP 0 UNTIL ;
: PACE ( -- ) BEGIN 0 . 250 MS KEY DUP 113 = IF DROP EXIT THEN DROP 0 UNTIL ;
"""

# A split that puts a value on the far side of a boundary: the fixture is the BLOCK LIST, because the splitter now
# refuses to produce this one (tools/fsplit.py selftest asserts that). R10 is the belt to that braces: it catches a
# regression in the splitter, or a hand-made multi-block upload.
KIND_BLOCKS = [": SWITCH ( desc -- ) NXT ! ; 40", "CONSTANT IMGP : HDR0 ( -- ) CLR HOME ;"]
GOOD_BLOCKS = ": A 1 ; 40 CONSTANT X : B 2 + . ;"


def selftest():
    ok = True
    for name, (src, rule) in BUGS.items():
        if src == "KIND_BLOCKS":
            f = check_blocks("", blocks=KIND_BLOCKS)
        else:
            f = lint_definitions(src) + check_blocks(src)
        hit = any(r == rule for _, r, _ in f)
        ok = ok and hit
        print(f"  {'caught' if hit else 'MISSED'}  {name:44} {rule}"
              + ("" if hit else f"  (got {sorted({r for _, r, _ in f})})"))
    f = lint_definitions(GOOD)
    ok = ok and not f
    print(f"  {'clean ' if not f else 'FALSE+'}  good source (must be silent)      {f[:1] if f else ''}")
    f = check_blocks(GOOD_BLOCKS)
    ok = ok and not f
    print(f"  {'clean ' if not f else 'FALSE+'}  good blocks (must be silent)      {f[:1] if f else ''}")
    # R11: a definition too long for one block is a lint finding, not a flash-time surprise
    f = check_blocks(": LONG " + " ".join(["1"] * 60) + " ;")
    ok = ok and any(r == "R11 fit" for _, r, _ in f)
    print(f"  {'caught' if f else 'MISSED'}  over-long definition (our 94/96 B demos)  R11 fit")
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
    # GUARDRAIL: the block checks need the splitter, and a file that cannot be split must fail HERE rather than at the
    # first upload - the chip already has a compiled dictionary when it reports it.
    findings = lint_definitions(src, base) + check_blocks(src, base)
    for ln, rule, msg in findings:
        print(f"  {argv[0]}:{ln}: {rule}: {msg}")
    print(f"  {len(findings)} finding(s)" if findings else "  clean")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

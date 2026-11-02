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
  R12 tick      bare `'` inside a definition. It calls word() at RUN time, so a body compiled with `' NOOP` pushes
                nothing and parses whatever input arrives next: measured as `?` lines from `: T ( -- ) ' NOOP EXECUTE ;`
                on the board, and as the launcher's failed-adopt arm being a no-op (F-134). `[']` is the immediate
                compile-time form.
  R10 block start  a block may not BEGIN with a word that consumes the stack. A block is a LINE and every line
                starts with an empty stack (`run_line()` does `sp = 0`), so anything the previous block pushed is
                gone. Measured: `fsplit` cut `: SWITCH ... ; 40` | `CONSTANT IMGP ...`, and the device answered
                `block 87: ERR_STACK` plus five `NAME?` lines naming words that were fine.
  R11 fit       a definition that cannot fit one 92 B block. The splitter refuses it at UPLOAD time - a board round
                trip to learn something a parser can see. Measured: two demo phases were written at 94 and 96 B and
                only failed when the chip was already flashing.
  R16 phase state (PHASE sources only, `--phase`) a phase may not CREATE/VARIABLE/CONSTANT its own storage. A phase
                is REPLACED on every adopt (docs/26): its cells and its dictionary are gone the moment another phase
                is loaded, so state kept there resets silently on the way in - which reads as "the cursor jumps home"
                and not as a storage bug. State belongs in examples/apps/registry.fs, below the seal.
  R18 no return (PHASE sources only, `--phase`) a phase that never names its return path (no CHAIN, no `NXT !`, no
                SHELF) cannot be left except by resetting the machine. docs/26 anti-slop item 4: every phase returns
                to the shelf with q/Esc, and `q` returning to a dispatcher that then has nowhere to go is a reset.
  R21 line length (--repl only) a source line over 63 B. The device input ring holds CMD_SIZE-1 = 63 and REFUSES the
                rest with `line too long: N bytes, the ring holds 63 - NOT sent`, so the line never reaches the machine,
                the definition never exists, and the failure shows up later as `NAME?` on an innocent line. Measured four
                times in one LoRa session on COMMENT lines of 64..80 B. Block uploads are exempt: the corpus compiles
                72 and 77 B lines today, because they travel as 92 B blocks through `#b` + `LOAD`.
  R22 definition a `:` that opens while a previous definition has not reached `;`, or a name defined twice. Measured:
                a stray duplicate `: !P ...` (left by an edit) swallowed the next definition, so the load answered `S?`
                on the line that USED it, two definitions away from the mistake. Duplicates matter twice as much here
                because the dictionary is a 12-bit hash (R15 in docs/14): the second definition is silent.
  R23 access width  `W!`/`W@`/`C!`/`C@` on a literal >= 0x10000, i.e. a register: RTCIO does not answer byte or
                halfword accesses, so those read 0 and write nothing while `!`/`@` work. Measured twice on the board
                (F-151 stores, F-153 loads) - every probe read 0x00, with no error.
  R24 pad register  writing 1610646528 (RTC_GPIO_OUT_REG). Measurement: `12345 1610646528 !` REBOOTS the S3
                (`ESP-ROM:esp32s3-20210327` on the console) - bits 0..21 are RTC GPIO 0..21 including the pads tied to
                flash, PSRAM and the brownout detector. Single pads go through OUT_W1TS 41988 / W1TC 1610646536.
  R9 (RETIRED)  `MS does not sleep` was earned when the primitive returned the wake count (measured: twenty
                `200 MS` in 0.05 s). MS now busy-waits on rdcycle (tests/ms_clock.py: 100 MS = +100 ms,
                300 MS = +301 ms), so the rule's premise is gone and it was removed instead of left as
                folklore. `MS` still SPINS - nothing else runs during it - but that is a property, not a bug:
                a paced loop that ignores -1 for 250 ms is normal terminal code (examples/demo_spin.fs).

Stack effects come from a table for the machine's own words, plus `( in -- out )` declarations for the
program's words. A definition without a declaration is assumed ( -- ), which is what most of them are; a
word that genuinely passes values must say so, and that declaration is documentation too.

    tools/lint_forth.py examples/tui_min.fs        lint a file (exit 1 on findings)
    tools/lint_forth.py --phase examples/apps/x.fs  lint a PHASE source: R1-R12 plus R16 and R18
    tools/lint_forth.py --repl examples/apps/lora/lora1.fs  add R21: no line over 63 B (typed path only)
    tools/lint_forth.py --selftest                 prove every rule fires on the bug it came from
    tools/sink.py                                  the CORPUS: 14 programs with their expected verdicts

    Run tools/sink.py after EVERY change to a rule. --selftest proves a rule fires on its own fixture; the corpus
    proves it does not fire on good code and still fires on bad code that was written before the rule existed. A rule
    that starts flagging 01_arith.fs is a false positive; a rule that stops flagging bad_r07.fs is a false negative.
"""
import re
import sys

# (name, pops, pushes). Control-flow words are listed so a body can use them, handled specially below.
PRIMS = {
    # GUARDRAIL: the words the launcher needs that the first table missed - EXECUTE (1,0), BLKXFER (2,2), KEY?/LOAD.
    # A missing entry reads as "undefined word" in perfectly good code, which is the fastest way to make a linter hated.
    "EXECUTE": (1, 0), "OVL": (1, 0), "BLKXFER": (2, 2), "KEY?": (0, 1), "LOAD": (1, 0), "UPDATE": (0, 0),
    # GUARDRAIL: `SAVE` PUSHES a status - p_blk_save ends with PUSH(st) (src/uforth.c:1257). This table said (0, 0), so the
    # only lint-clean way to call it was a bare `SAVE`, which leaks one stack cell per press and kills the phase with
    # ERR_STACK after 16; consuming the status (`SAVE 0= IF ...`) was reported as R3 underflow / R4 leak. Lane SHEET hit
    # this: the linter was forcing the buggy form. Check a pushed status against the C before trusting the table.
    "SAVE": (0, 1),
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
        # GUARDRAIL: `'` (tick) PUSHES the xt of the word that follows and does NOT call it. Modelling only the push
    # reported `' NOOP` as "NOOP needs nothing, fine" - but on a word that takes arguments it would subtract them and
    # report a phantom underflow. The walk skips the operand instead (see `tick` below).
    "'": (0, 1),
    # GUARDRAIL: `[']` is the COMPILE-TIME tick (p31_prims.inc: `X(BTICK,"[']",1)`, immediate, `clit(x)`), and it is the
    # only form that works inside a definition: bare `'` (P_TICK) calls `word()` at RUN time, so a `' NOOP` compiled into
    # a body pushes nothing and executes a parse of whatever input comes next - measured on the board as two `?` lines
    # from `: T ( -- ) ' NOOP EXECUTE ;`. The launcher's failed-adopt path carried exactly that bug: PICKX returned an xt
    # only on the success arm, and the safety arm printed NAME? instead of running NOOP (F-134).
    "[']": (0, 1),
    "UNLOOP": (0, 0), '."': (0, 0),
}
# GUARDRAIL: `DO`/`LOOP`/`+LOOP` are NOT in this machine - src/p31_prims.inc defines BEGIN/WHILE/REPEAT, BEGIN/UNTIL,
# BEGIN/AGAIN and `I`, and nothing else (checked against the prim list, not against memory). They sat in this set anyway,
# so the linter certified a calculator loop that the engine refused to compile at line 11 - a linter that accepts a word
# the machine lacks is the failure this whole tool exists to prevent (its own docstring says so about MOD). Anything
# removed here has to come back only with a prim in that file. The loop-counter word `I` is real but has no DO to pair
# with, so a counted loop is BEGIN/WHILE/REPEAT with a cell or an unrolled body.
CONTROL = {"IF", "ELSE", "THEN", "BEGIN", "UNTIL", "WHILE", "REPEAT", "AGAIN", "EXIT"}


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


def code_only(src):
    """`src` with `\` comments, `( ... )` declarations and `."` strings removed, newlines kept.

    GUARDRAIL: the `\` comments are cut FIRST, line by line, before the `( ... )` pass. Measured on lora1.fs: a `(`
    inside a comment opened a "declaration" that blanked real code up to the first `)` far away, and the prose that
    survived then counted as WORDS - the comment "... a bare `1 MOSIPAD PIN!` then moves OUT to" produced a THEN, and
    R29 refused the driver for a control structure that line does not contain. Every token-based rule (R16, R23, R26,
    R29) reads through this function, so the order is the whole point.
    """
    lines = []
    for ln in src.split("\n"):
        cut = None
        for k, ch in enumerate(ln):
            if ch == chr(92) and (k == 0 or ln[k - 1] in " \t"):
                cut = k
                break
        lines.append(ln if cut is None else ln[:cut])
    src = "\n".join(lines)
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        if src[i] == "(":
            j = src.find(")", i)
            j = n if j < 0 else j + 1
        elif src.startswith('."', i):
            j = src.find('"', i + 2)
            j = n if j < 0 else j + 1
        else:
            i += 1
            continue
        for k in range(i, j):
            if out[k] != "\n":
                out[k] = " "
        i = j
    return "".join(out)


def lint_phase(src):
    """R16 + R18: the two rules that only mean something for a PHASE source (docs/26), so only `--phase` runs them.

    GUARDRAIL: these must NOT run on an ordinary program. 05_cells.fs legitimately CREATEs its cell, and every REPL
    demo legitimately ends by returning to the line prompt (examples/demo_bars.fs has no CHAIN), so a default-on
    R16/R18 is a false positive on the two files the corpus already trusts - and the operator would turn the linter
    off. The mode is the contract: a phase is adopted into the window and replaced on the next adopt.
    """
    findings = []
    code = code_only(src)
    for m in re.finditer(r"\b(CREATE|VARIABLE|CONSTANT)\s+(\S+)", code):
        ln = code[:m.start()].count("\n") + 1
        findings.append((ln, "R16 phase state",
                         f"{m.group(1)} {m.group(2)}: a phase is REPLACED on every adopt, so this storage vanishes"
                         " with it - keep state in examples/apps/registry.fs, below the seal"))
    # GUARDRAIL: the return path is NAMED, not inferred. `NXT !` and `CHAIN` and `SHELF` are the three ways a phase
    # hands the next phase to the dispatcher; an EXIT only returns to the adopt loop, which then has nowhere to go.
    if not (re.search(r"\bCHAIN\b", code) or re.search(r"\bNXT\s*!", code) or re.search(r"\bSHELF\b", code)):
        findings.append((1, "R18 no return",
                         "the phase names no return path (no CHAIN, no `NXT !`, no SHELF) - once adopted it can only"
                         " be left by resetting the machine"))
    return findings


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
    raw = src          # GUARDRAIL: the ORIGINAL, captured BEFORE the blanking below. Taking it after (as the first
                       # version did) gave every `--use` word the effect (0, 0) because its `( a -- b )` declaration had
                       # already been turned into spaces, so `CHAIN ( desc -- )` stopped consuming its descriptor and four
                       # lanes reported "R4 leak" on their return path. A comment is not code, but a declaration IS data.
    # GUARDRAIL: `collect_vocab` reads a BASE file, so a GUARDRAIL comment in it that quotes `CREATE X` invented a cell in
    # the vocabulary every lane is linted against - the same comment-is-not-code bug the definition scan had. Blank first.
    if "(" in src:
        out, i, n = [], 0, len(src)
        while i < n:
            if src[i] == "(":
                j = src.find(")", i)
                if j < 0:
                    out.append(src[i:]); break
                out.append(" " * (j + 1 - i)); i = j + 1; continue
            out.append(src[i]); i += 1
        src = "".join(out)
    for m in re.finditer(r"(?:CREATE|CONSTANT)\s+(\S+)", src):
        v[m.group(1)] = (0, 1)
    # GUARDRAIL: the body must be sliced from the ORIGINAL text, because a stack declaration `( a -- b )` IS a
    # parenthesised comment and the blanking above turns it into spaces. Reading the blanked copy gave every
    # `--use` word the effect (0, 0): `CHAIN ( desc -- )` stopped consuming its descriptor, so every phase that ends
    # `X CHAIN` reported "R4 leak: ... leaves 1 item" (four lanes at once - mail, calc1, calc2, shelf - which is what
    # said "the tool is wrong, not the code"). Offsets are identical in both strings.
    toks = list(re.finditer(r"\S+", src))
    i = 0
    while i < len(toks):
        if toks[i].group(0) == ":" and i + 1 < len(toks):
            name = toks[i + 1].group(0)
            tail = raw[toks[i + 1].end():toks[i + 1].end() + 120]
            v[name] = (declared(tail) if re.match(r"\s*\(", tail) else None) or (0, 0)
            i += 2
            continue
        i += 1
    return v


def check_source_shape(src, phase=False, repl=False):
    """R21-R24: rules about the FILE, not about a definition's stack effect.

    Every one of these is from the 2026-11-01 LoRa bring-up, and every one of them produced a failure with NO error
    message on the device - which is the only reason they are worth a rule.
    """
    findings = []
    lines = src.split("\n")
    # GUARDRAIL: R21. The device input ring holds CMD_SIZE-1 = 63 bytes per line and REFUSES longer ones silently - the
    # phrase is `line too long: N bytes, the ring holds 63 - NOT sent`, printed by the HP bridge, and the definition then
    # simply does not exist, so the failure surfaces later as `NAME?` on an innocent line. Measured four times in one
    # session on COMMENT lines of 64..80 B that nobody thought of as code. Block sources (--phase) are cut by the
    # splitter against 92 B blocks and are exempt; this is the REPL-typed path.
    # GUARDRAIL: opt-in, not default. The corpus and every phase are uploaded as BLOCKS (`cli.upload` ->
    # `split_defs(src, 92)` -> `#b` seed -> `LOAD`), so their source lines may legally be up to 92 B and the ring never
    # sees them - the first version of this rule fired on 02_loops.fs (72 B) and 03_digits.fs (77 B), both of which the
    # board compiles today. A rule that flags working code is worse than no rule. `--repl` is for sources a harness TYPES
    # line by line (tools/lora_device.py).
    if repl and not phase:
        for i, ln in enumerate(lines, 1):
            if len(ln.encode()) > 63:
                findings.append((i, "R21 line length",
                                 f"{len(ln.encode())} B: the device input ring holds 63 and refuses the rest silently, "
                                 "so this line never reaches the machine and its definition never exists"))
    # GUARDRAIL: R22. A `:` line that opens while a previous definition has not reached `;` SWALLOWS the next
    # definition. Measured: a stray duplicate `: !P ( level pin -- ) 10 + 1 SWAP LSHIFT SWAP` (left by an edit) ate
    # `: S ... ;`, so `S` did not exist and the load failed with `S?` on the line that USED it - two definitions away
    # from the mistake. The same check catches a name defined twice, which on this machine is worse than it looks: the
    # dictionary is a 12-bit hash (R15 in docs/14), so a duplicate is silent, and a duplicate with a DIFFERENT body is
    # a live word whose behaviour depends on load order.
    # GUARDRAIL: scan TOKENS, not lines. The first version tracked state per line and reported every ordinary
    # `: NAME ... ;` as "unterminated", because a definition that opens and closes on one line set `open` and the
    # closing `;` was never examined - 6 false positives on the corpus, which is how a rule gets switched off.
    # GUARDRAIL: walk TOKENS, not regexes. The prose in this very file contains
    # `BUDGET: this driver needs MEMSZ >= 2550`, and a regex `:\\s+(\\S+)` read
    # the colon at the end of `BUDGET:` as a definition opener and reported a
    # word named `this` - a false positive on a comment, which is how a rule
    # gets switched off. `\\`-comments are dropped line by line first (a `\\`
    # runs to the end of the line, and a line whose first token is `\\` is a
    # comment), and a definition opens only on a STANDALONE `:` token.
    kept = []
    for line in code_only(src).split("\n"):
        if line.split() and line.split()[0] == "\\":
            continue                      # `\` runs to the end of the line
        kept.append(line)
    scan = "\n".join(kept)
    scan_lines = scan.split("\n")
    pend, seen = None, {}
    for lineno, line in enumerate(scan_lines, 1):
        toks = line.split()
        for i, tk in enumerate(toks):
            if tk == ";":
                pend = None
            elif tk == ":" and i + 1 < len(toks):
                name = toks[i + 1]
                if pend is not None:
                    findings.append((lineno, "R22 definition",
                                     f"`:` {name} opens while the definition of {pend[1]} (line {pend[0]}) has not ended with "
                                     "`;` - the earlier body swallows this one and neither word exists"))
                if name in seen:
                    findings.append((lineno, "R22 definition",
                                     f"{name} is defined twice (first on line {seen[name]}): the 12-bit hash makes the "
                                     "second definition silent, so load order decides which body runs"))
                seen.setdefault(name, lineno)
                pend = (lineno, name)
    # GUARDRAIL: R23. A peripheral address needs a 32-bit access. `wr32`/`rd32` decompose into byte accesses for MEMORY
    # (correct) and RTCIO does not answer byte accesses, so `W!`/`W@`/`C!`/`C@` on a register read 0 and write nothing -
    # measured twice on the board (F-151 stores, F-153 loads): every register probe returned 0x00 while the same address
    # round-tripped through `!`/`@`. Any literal >= 0x10000 is a register address on this machine: MEMSZ is ~2.5 KB, so
    # nothing that large can be memory.
    # GUARDRAIL: the range test has to know BOTH address forms. It used to be `>= 0x10000` alone, which was sound
    # while drivers used SoC addresses - and went silently blind the moment pool code moved to the ALIAS WINDOW
    # (RTCIO 0xA400, SENS 0xC800), where every register literal is BELOW 0x10000 and no narrow access was reported.
    # 0xA400..0xD3FF cannot be pool memory (MEMSZ is ~2.5 KB), so in that range a literal is always a register.
    for i, ln in enumerate(lines, 1):
        for tok in tokens(code_only(ln)):
            if not tok.isdigit():
                continue
            v = int(tok)
            if not (0x60000000 <= v <= 0x6003FFFF or 0xA400 <= v < 0xD400):
                continue
            for narrow in ("W!", "W@", "C!", "C@"):
                if narrow in tokens(code_only(ln)):
                    findings.append((i, "R23 access width",
                                     f"{narrow} at register address {tok}: write/read registers with `!`/`@` only - the "
                                     "narrow accesses are not answered by the peripheral and fail with no error"))
                    break
            break
    # GUARDRAIL: R24. 1610646528 is RTC_GPIO_OUT_REG (0x60008400) and writing an arbitrary value there REBOOTS the S3:
    # bits 0..21 are RTC GPIO 0..21, which include the pads tied to flash, PSRAM and the brownout detector. Measured:
    # `12345 1610646528 !` produced `ESP-ROM:esp32s3-20210327` on the console. Single pads go through OUT_W1TS (…404)
    # and OUT_W1TC (…408), which touch one bit each.
    # GUARDRAIL: R28. An ODD number of interpret-state `C,` bytes leaves HERE odd, and mkhdr_pad refuses EVERY
    # later definition while HERE is odd (`if (x + 2u > h || (x & 1u)) errf_msg(MSG_ERR_DICT)`, uforth.c) because
    # xt is stored as xt/2 and an odd offset would halve into a wrong-word dispatch. Measured: a 69-byte config table
    # made the next eleven definitions answer ERR_DICT with 848 B still free - the message names the dictionary and
    # the fault is alignment, which cost an hour of hunting space that was never the problem. Count only
    # interpret-state uses: a `C,` inside a definition runs later and does not move the load-time parity.
    carity, in_def, odd_at = 0, False, None
    for line in scan_lines:
        body = [tk for tk in line.split() if not tk.startswith("\\")]
        head = bool(body) and (body[0] == ":" or body[0] in ("CREATE", "CONSTANT", "VARIABLE"))
        if head and not in_def and carity % 2 and odd_at is None:
            odd_at = (body[1] if len(body) > 1 else body[0])
        for tk in body:
            if tk == ":":
                in_def = True
            elif tk == ";":
                in_def = False
            elif tk == "C," and not in_def:
                carity += 1
    if odd_at is not None:
        findings.append((1, "R28 alignment",
                         f"HERE is ODD at `{odd_at}`: an earlier interpret-state data block ended on an odd byte, so "
                         "this and EVERY later definition is refused with ERR_DICT however much room is left. Give the "
                         "offending block an even size (2 B cells, or one filler `0 C,`)"))
    elif carity % 2:
        findings.append((1, "R28 alignment",
                         f"{carity} interpret-state `C,` bytes is ODD: HERE stays odd and every later definition is "
                         "refused with ERR_DICT however much room is left. Add one filler `0 C,`"))
    # ---- R29 balance within one typed line
    if repl:
        for i, ln in enumerate(code_only(src).split("\n"), 1):
            toks = [tk.upper() for tk in tokens(ln)]
            n = lambda w: sum(1 for tk in toks if tk == w)
            if n("IF") != n("THEN"):
                findings.append((i, "R29 per-line control",
                                 f"{n('IF')} IF against {n('THEN')} THEN on one line: the engine closes a structure "
                                 "only inside the line it was opened on, so this answers ERR_STACK and the word does "
                                 "not exist"))
            if n("BEGIN") != n("UNTIL") + n("REPEAT") or n("WHILE") != n("REPEAT"):
                findings.append((i, "R29 per-line control",
                                 f"BEGIN {n('BEGIN')} / WHILE {n('WHILE')} / UNTIL {n('UNTIL')} / REPEAT "
                                 f"{n('REPEAT')} do not balance on this line: a structure split across typed lines "
                                 "answers ERR_STACK and the definition never exists"))
    # GUARDRAIL: R26. The coprocessor does NOT decode the SoC address map: A10/A11 are dropped, so an absolute
    # 0x6000_84xx access from pool code lands in RTC_CNTL and nothing answers it - the root cause that cost months,
    # and the reason every driver constant is written in the ALIAS WINDOW (`esp32s3.peripherals.ld`: RTCIO 0xA400,
    # SENS 0xC800). It fails by silence: the value looks right, the store runs, the pad does not move. A literal in
    # the SoC peripheral range is therefore a defect even when it decodes to the correct register.
    for i, ln in enumerate(lines, 1):
        for tk in tokens(code_only(ln)):
            v = None
            if re.fullmatch(r"\d{6,}", tk) or re.fullmatch(r"0[xX][0-9a-fA-F]{6,}", tk):
                v = int(tk, 0)
            if v is not None and 0x60000000 <= v < 0x61000000:
                findings.append((i, "R26 alias window",
                                 f"{tk} = 0x{v:08X} is a SoC address; the coprocessor drops A10/A11 and it lands in "
                                 "RTC_CNTL. Use the alias window the linker defines: RTCIO 41984 (0xA400), "
                                 "SENS 51200 (0xC800)"))
    # GUARDRAIL: R27. A second BEGIN inside an open BEGIN in the SAME definition is refused by the loader with no
    # message at all - measured on a phase upload where `RUNSHELF` simply vanished (no ERR_DICT, no `NAME?`): the
    # control-structure stack has 3 slots and nesting counted loops in one definition overruns it on the way in.
    # Depth rule: BEGIN +1, WHILE -1 (it consumes BEGIN's forward ref), REPEAT no change, UNTIL -1.
    depth = 0
    for lineno, line in enumerate(scan_lines, 1):
        for tk in line.split():
            if tk == ":":
                depth = 0
            elif depth and tk == "BEGIN":
                findings.append((lineno, "R27 nested loop",
                                 "BEGIN inside an open BEGIN: the loader drops the whole definition silently, so "
                                 "the loop that looks present is not - keep one loop per definition and call a "
                                 "bounded wait word instead"))
                depth += 1
            elif tk == "BEGIN":
                depth += 1
            elif tk in ("WHILE", "UNTIL"):
                depth = max(0, depth - 1)
            elif tk == ";":
                depth = 0
    for i, ln in enumerate(lines, 1):
        toks = tokens(code_only(ln))
        if "1610646528" in toks and "!" in toks:
            findings.append((i, "R24 pad register",
                             "writing RTC_GPIO_OUT_REG reboots the S3 (flash/PSRAM/brownout pads share those bits): set "
                             "one pad at a time through OUT_W1TS 41988 / OUT_W1TC 1610646536"))
    return findings


def lint_definitions(src, base=None, repl=False):
    """Yield findings for a source file. R1 runs over raw lines; R2/R3/R4 run per definition."""
    findings = check_source_shape(src, repl=repl)
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
        # GUARDRAIL: R1 is a BLOCK rule, so `--repl` suppresses it: in typed source a `\` comment is legal and measured to
        # work on the chip (the LoRa driver is written with them). Leaving it on made every typed file report a finding
        # whose message - "a block has no line boundaries" - was false about the file in hand.
        if c == "\\":
            if not repl:
                findings.append((line_no, "R1 comment",
                                 "`\\` comment in a block source: a block has no line boundaries, so this compiles as words"))
            # GUARDRAIL: skip the comment text in BOTH modes. Only the R1 finding is mode-specific, and the first
            # version stopped walking at `\` in --repl mode instead of skipping past the text, so prose like
            # `BUDGET: this driver needs MEMSZ >= 2550` was scanned as code: its colon opened a definition named
            # `this`, that body swallowed `: PIN! ... ;`, and every later use of PIN! reported "not defined" - a
            # false report that sent me hunting through a correct driver.
            j = src.find("\n", i)
            if j < 0:
                break
            line_no += 1
            i = j + 1
            continue
        i += 1
    vocab = dict(PRIMS)
    if base:
        vocab.update(base)
    # GUARDRAIL: a CREATE'd or CONSTANT word PUSHES its address/value - (0, 1), not (0, 0). Modelling it as "pushes
    # nothing" made every later `SEL @` look like an underflow, which is a false positive on perfectly good code.
    for m in re.finditer(r"(?:CREATE|CONSTANT)\s+(\S+)", src):
        vocab[m.group(1)] = (0, 1)
    # GUARDRAIL: blank `( ... )` comments BEFORE scanning for definitions. A GUARDRAIL comment that quotes code - e.g.
    # `( GUARDRAIL: `: W ... ;` must be clean )` - was parsed as a definition of its own, so R2/R10 fired on comment text
    # and the only way to keep a phase lint-clean was to write comments that avoid colons and semicolons (lane MAIL did
    # exactly that, and said so). Comments are not code; make them spaces, keep the line structure so line numbers hold.
    def _blank_comments(text):
        out, i, n = [], 0, len(text)
        while i < n:
            if text[i] == "(":
                j = text.find(")", i)
                if j < 0:
                    out.append(text[i:]); break
                chunk = text[i:j + 1]
                out.append("".join(c if c == "\n" else " " for c in chunk)); i = j + 1; continue
            out.append(text[i]); i += 1
        return "".join(out)

    # GUARDRAIL: scan the BLANKED text for definition boundaries but slice the ORIGINAL for the body, because the body's
    # `( a b -- c )` declaration IS a parenthesised comment - blanking it removed every stack effect and the selftest went
    # red on rules that depend on depth. The blanks preserve length, so the offsets are the same in both strings.
    # GUARDRAIL: `\`-comments are blanked FIRST, before the `( ... )` pass. Order is everything: the prose line
    # `\ never reaches the board. Lines stay under 63 bytes (the` ends with an opening paren, and the paren pass ran
    # first it opened a comment that swallowed to the next `)` two lines down and left `BUDGET: this driver needs`
    # exposed as code - which then parsed as `: this ... ;` and hid `: PIN! ... ;`. One false "not defined" and the
    # operator learns to distrust the linter.
    blank = re.sub(r"\\[^\n]*", lambda m: " " * len(m.group(0)), src)
    blank = _blank_comments(blank)
    # GUARDRAIL: `\` comments must be blanked too, for the same reason the `( ... )` ones are - and the failure is
    # sneakier. A comment reading `\ BUSY settle, no loop: run_line zeroes the stack each line,` was parsed as a
    # DEFINITION of `run_line`, whose body then swallowed the real `: WB ... ;` two lines below it, and the linter
    # reported "R2 order: RST: WB is not defined before this point" - a true statement about a false world. R1 still
    # reports `\` in block sources because it scans the RAW text, so blanking here hides nothing.
    blank = re.sub(r"\\[^\n]*", lambda m: " " * len(m.group(0)), blank)
    for m in re.finditer(r":\s+(\S+)(.*?);", blank, re.S):
        name = m.group(1)
        body = src[m.start(2):m.end(2)]
        lineno = blank[:m.start()].count("\n") + 1
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
        # GUARDRAIL: R19. `BASE n + @` is only safe when n is a multiple of 4. A cell is 4 bytes and this machine has no
        # `CELLS` word, so every cell index is hand arithmetic - and `BASE 1 + @` is an UNALIGNED 32-bit load, which traps
        # on rv32 (F-78) while x86 reads it happily. Measured: the mail phase drew its rows on the host and hung on the
        # chip at its first `MAIL_ST 1 + @`, after the title bar, with no error anywhere. Flag a literal offset that is
        # not a multiple of 4; C@/C! are bytes and stay fine.
        for i in range(2, len(toks)):
            if toks[i] in ("@", "!") and toks[i - 1] == "+" and toks[i - 2].isdigit():
                off = int(toks[i - 2])
                if off % 4:
                    findings.append((lineno, "R19 alignment",
                                     f"{name}: `{off} + {toks[i]}` is an unaligned 32-bit access - a cell is 4 bytes and "
                                     f"there is no CELLS word; write `{off * 4 if off < 8 else off} +` (or the byte "
                                     f"offset as a multiple of 4). It traps on rv32 and works on the host"))
        # GUARDRAIL: R20. `10 EMIT` is a bare LF: on a real terminal that moves DOWN and keeps the column, so a definition
        # that builds rows with LF alone draws every row starting where the last one ended, and the terminal wraps - the
        # operator's screen showed split borders and `rw/cl` merged into `0/0`. The shelf had `: NL 10 EMIT ;` while mail
        # had `13 EMIT 10 EMIT`. Flag a body that emits 10 without also emitting 13 (a CR before the LF, in any order).
        if "10" in toks and "EMIT" in toks and "13" not in toks:
            for i in range(len(toks) - 1):
                if toks[i] == "10" and toks[i + 1] == "EMIT":
                    findings.append((lineno, "R20 newline",
                                     f"{name}: `10 EMIT` is a bare LF - a terminal keeps the COLUMN on LF, so rows start "
                                     f"where the last one ended and wrap. Emit CR first: `13 EMIT 10 EMIT`"))
                    break
        infinite = any(toks[i - 1] == "0" and toks[i] == "UNTIL" for i in range(1, len(toks)))
        skip = 0
        tick = False
        for tk in toks:
            if tick:
                tick = False
                # GUARDRAIL: skipping the operand is right for the STACK EFFECT and wrong for EXISTENCE. `'` is parsed by
                # the outer interpreter at compile time, so a ticked word must already exist - `' UNDEF` is `NAME?` on
                # the chip, and because the walk skipped the operand the linter called it clean. Measured while adding
                # the dispatcher: `boot.fs` ticks NOOP, and a typo there would have been a device session, not a lint.
                if tk not in vocab and not tk[0].isdigit():
                    findings.append((lineno, "R2 order",
                                     f"`' {tk}` ticks a word that is not defined - NAME? at compile time"))
                continue
            if tk == "[']":
                depth += 1
                tick = True
                continue
            if tk == "'":
                # GUARDRAIL: R12. `'` inside a definition compiles a runtime parse, not a literal - the xt is NOT on the
                # stack when the body runs. Reported at the definition, with the fix in the message, because the symptom
                # (`?` lines from a running word) sends you looking at the wrong word entirely.
                findings.append((lineno, "R12 tick",
                                 f"{name}: `' {toks[toks.index(tk) + 1] if toks.index(tk) + 1 < len(toks) else '?'}`"
                                 " compiles a RUNTIME parse - inside a definition use `[']` (the immediate, compile-time tick)"))
                depth += 1
                tick = True
                continue
            if tk == "'":
                depth += 1
                tick = True
                continue
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
        # GUARDRAIL: `' NAME` is a push plus a NAME - the operand must not be looked up, or `' NOOP` at the start of a
        # block reads as a call to NOOP.
        if toks[0] == "'" and len(toks) > 1:
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
 "odd number of C, bytes leaves HERE odd (ERR_DICT on everything after)":
   ("""CREATE T 1 C, 2 C, 3 C,\n: X 5 ;\n""", "R28 alignment"),
   # four 1-byte cells: total is EVEN, but HERE is odd at every intermediate CREATE - the case that cost 40 definitions
 "per-boundary parity: four 1-byte cells total EVEN but HERE odd at each CREATE":
   ("""CREATE A 0 C,\nCREATE B 0 C,\nCREATE C 0 C,\nCREATE D 0 C,\n: X 5 ;\n""", "R28 alignment"),
 "loop split across two typed lines (SND in loratx.fs, 488 B free)":
   (""": SND ( n -- )\n  BEGIN DUP WHILE 1-\n  REPEAT DROP ;\n""", "R29 per-line control"),
 "valid loop on one line (must stay quiet)":
   (""": SND ( n -- ) BEGIN DUP WHILE 1- REPEAT DROP ;\n""", None),
 "SoC absolute address from pool code (the alias-window root cause)":
   (""": PADSET 1610646532 ! ;\n""", "R26 alias window"),
 "nested counted loop in one definition (loader refuses it silently)":
   (""": RUNSHELF BEGIN KEY 1+ BEGIN KEY UNTIL UNTIL ;\n""", "R27 nested loop"),
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
 # GUARDRAIL: R16/R18 carry a THIRD field, `phase`, because they only apply to a phase source (--phase): the selftest
 # runs those two through lint_phase instead of the ordinary walk. Running them on everything would refuse
 # tests/sink/05_cells.fs (a legitimate CREATE) and examples/demo_bars.fs (a demo that quits to the prompt).
 "over-long line (the ring refuses it):":
   ("""\ lora1.fs - SX1262 transmit driver in Forth, registers through the HW gate.
: A ( -- ) ;
""", "R21 line length"),
 "definition swallowed by a stray duplicate (our `S?`)":
   (""": !P ( level pin -- ) 1 SWAP LSHIFT ;
: !P ( level pin -- ) 1 SWAP LSHIFT SWAP
: S ( b -- b*2 ) DUP 2 * ;
""", "R22 definition"),
 "narrow access to a register (F-151/F-153)":
   (""": STA ( -- ) 42000 W@ DROP ;
""", "R23 access width"),
 # a KEY WORD, not an address: R23 fired on every one of these when it treated any literal >= 0x10000 as a register
 "data constant is NOT a register address (must stay quiet)":
   ("""4008632343 0 W! 88542 ;\n""", None),
 "arbitrary write to OUT_REG (the `#h` reboot)":
   (""": OUT ( v -- ) 1610646528 ! ;
""", "R24 pad register"),
 "phase with its own storage":
   ("""CREATE X 0 ,
: PH1 ( -- ) 96 CHAIN ;
""", "R16 phase state", "phase"),
 "phase with no return path":
   (""": PH1 ( -- ) 1 DROP ;
""", "R18 no return", "phase"),
}
# The corrected versions of every bug above, in one source: it must lint SILENT, or the rules are just noise.
# GUARDRAIL: the fixture's own lines stay under 63 B. The first version had an 85 B `PACE` line and R21 fired on it -
# correctly: this text is what a REPL uploads, and the ring would have refused that line while the suite stayed green.
GOOD = """: WAIT ( -- c ) BEGIN KEY DUP -1 = WHILE DROP REPEAT ;
: JK ( c -- ) DUP 106 = IF DROP WAIT DROP EXIT THEN
  DUP 107 = IF DROP WAIT DROP EXIT THEN DROP ;
: DIGIT ( n -- ) 15 AND 48 + EMIT ;
: .N ( n -- ) 100 /MOD DROP DUP 10 < IF DIGIT
  ELSE 10 /MOD DIGIT DIGIT THEN ;
: RUNS ( -- ) BEGIN WAIT DUP 113 = IF DROP EXIT THEN
  DROP 0 UNTIL ;
: PACE ( -- ) BEGIN 0 . 250 MS KEY DUP 113 = IF DROP EXIT
  THEN DROP 0 UNTIL ;
"""

# A split that puts a value on the far side of a boundary: the fixture is the BLOCK LIST, because the splitter now
# refuses to produce this one (tools/fsplit.py selftest asserts that). R10 is the belt to that braces: it catches a
# regression in the splitter, or a hand-made multi-block upload.
KIND_BLOCKS = [": SWITCH ( desc -- ) NXT ! ; 40", "CONSTANT IMGP : HDR0 ( -- ) CLR HOME ;"]
GOOD_BLOCKS = ": A 1 ; 40 CONSTANT X : B 2 + . ;"
# GUARDRAIL: the tick fixture earns its place: `'` was added to the effect table for the dispatcher and the operand is
# SKIPPED, which is exactly the shape that makes an undefined ticked word invisible. Both directions are proven here -
# a ticked resident word is silent, a ticked unknown word is R2.
# GUARDRAIL: the fixture uses `[']`, because `'` inside a definition is the BUG (R12) - the first version of this test
# asserted the broken form was clean, which is how a linter certifies the mistake it is supposed to catch.
# GUARDRAIL: the fixture that would have caught the SAVE table entry: a body that CONSUMES the status is correct code
# (p_blk_save pushes it), so it must lint clean. With SAVE modelled as (0, 0) this fixture reports R3 underflow.
GOOD_SAVE = ": W ( -- ) UPDATE SAVE DROP ;"
# GUARDRAIL: R20's two directions - the shelf's bug (`10 EMIT` alone) and the correct pair mail had all along.
BAD_NL = ": NL ( -- ) 10 EMIT ;"
GOOD_NL = ": NL ( -- ) 13 EMIT 10 EMIT ;"
# GUARDRAIL: R19's two directions. `2 + @` is a trap on rv32 (the mail phase's bug); `8 + @` is a legal cell offset.
BAD_ALIGN = ": C ( -- ) STATE 2 + @ . ;"
GOOD_ALIGN = ": C ( -- ) STATE 8 + @ . ;"
GOOD_TICK = ": NOOP ; : A ( -- ) ['] NOOP EXECUTE ;"
BAD_TICK = ": NOOP ; : A ( -- ) ['] NOXX EXECUTE ;"
BAD_R12 = ": NOOP ; : A ( -- ) ' NOOP EXECUTE ;"
# The corrected phase: a return path, no storage, and the two words that LOOK like storage inside text.
# GUARDRAIL: the `." CREATE X"` string is the point of this fixture - R16 blanks strings before it looks, and the
# version that scanned raw text refused a phase for drawing a word it never compiles.
GOOD_PHASE = """: PH1 ( -- ) ." CREATE X" 96 CHAIN ;
: PH2 ( -- ) 96 NXT ! ;
: PH3 ( -- ) SHELF CHAIN ;
"""
# GUARDRAIL: R21-R24's two directions, one line each. The register fixture uses OUT_W1TS with a single bit and `!`, which
# is the correct shape the LoRa driver ended up with - if the rules ever fire on this, they will fire on the driver.
GOOD_REG = ": NSS_HI ( -- ) 262144 41988 ! ;\n: RD ( -- v ) 42000 @ ;"


def selftest():
    ok = True
    for name, fx in BUGS.items():
        src, rule = fx[0], fx[1]
        mode = fx[2] if len(fx) > 2 else "lint"
        if src == "KIND_BLOCKS":
            f = check_blocks("", blocks=KIND_BLOCKS)
        elif mode == "phase":
            f = lint_phase(src)
        else:
            # GUARDRAIL: R21 only exists in `--repl` mode, so its fixture has to run with it - otherwise the selftest
            # would report the rule as MISSED for the trivial reason that it was never enabled.
            want_repl = rule is None or "R21" in rule or "R29" in rule
            f = lint_definitions(src, repl=want_repl) + check_blocks(src)
        hit = any(r == rule for _, r, _ in f)
        if rule is None:      # negative fixture: the code is VALID and any finding is a bug in the rule
            ok = ok and not f
            print(f"  {'quiet ' if not f else 'FALSE POSITIVE'}  {name:44}"
                  + ("" if not f else f"  (got {sorted({r for _, r, _ in f})})"))
            continue
        ok = ok and hit
        print(f"  {'caught' if hit else 'MISSED'}  {name:44} {rule}"
              + ("" if hit else f"  (got {sorted({r for _, r, _ in f})})"))
    v = collect_vocab("\\ BUDGET: this needs memory\n: AA ( a -- b )\n  ;\n: BB\n  1 ;\n")
    ok = ok and v.get("AA") == (1, 1) and v.get("BB") == (0, 0) and "this" not in v
    print(f"  {'clean ' if v.get('AA') == (1, 1) and v.get('BB') == (0, 0) and 'this' not in v else 'WRONG'}  "
          f"vocab scan: comment colon ignored, multi-line defs seen, effects not borrowed  AA={v.get('AA')} "
          f"BB={v.get('BB')}")
    f = lint_definitions(GOOD)
    ok = ok and not f
    print(f"  {'clean ' if not f else 'FALSE+'}  good source (must be silent)      {f[:1] if f else ''}")
    f = check_blocks(GOOD_BLOCKS)
    ok = ok and not f
    print(f"  {'clean ' if not f else 'FALSE+'}  good blocks (must be silent)      {f[:1] if f else ''}")
    f = lint_definitions(GOOD_ALIGN)
    ok = ok and not f
    print(f"  {'clean ' if not f else 'FALSE+'}  aligned cell offset (4-byte)   {f[:1] if f else ''}")
    f = lint_definitions(GOOD_REG)
    ok = ok and not f
    print(f"  {'clean ' if not f else 'FALSE+'}  32-bit register access         {f[:1] if f else ''}")
    f = lint_definitions(BAD_ALIGN)
    hit = any(r == "R19 alignment" for _, r, _ in f)
    ok = ok and hit
    print(f"  {'caught' if hit else 'MISSED'}  UNALIGNED cell offset           R19 alignment"
          + ("" if hit else f"  (got {sorted({r for _, r, _ in f})})"))
    f = lint_definitions(GOOD_NL)
    ok = ok and not f
    print(f"  {'clean ' if not f else 'FALSE+'}  CR LF newline (mail's form)   {f[:1] if f else ''}")
    f = lint_definitions(BAD_NL)
    hit = any(r == "R20 newline" for _, r, _ in f)
    ok = ok and hit
    print(f"  {'caught' if hit else 'MISSED'}  LF without CR (the shelf's)       R20 newline"
          + ("" if hit else f"  (got {sorted({r for _, r, _ in f})})"))
    f = lint_definitions(GOOD_SAVE)
    ok = ok and not f
    print(f"  {'clean ' if not f else 'FALSE+'}  SAVE's status is consumed        {f[:1] if f else ''}")
    f = lint_definitions(GOOD_TICK)
    ok = ok and not f
    print(f"  {'clean ' if not f else 'FALSE+'}  ticked resident word (must be silent) {f[:1] if f else ''}")
    f = lint_definitions(BAD_TICK)
    hit = any(r == "R2 order" for _, r, _ in f)
    ok = ok and hit
    print(f"  {'caught' if hit else 'MISSED'}  ticked UNKNOWN word                R2 order"
          + ("" if hit else f"  (got {sorted({r for _, r, _ in f})})"))
    f = lint_definitions(BAD_R12)
    hit = any(r == "R12 tick" for _, r, _ in f)
    ok = ok and hit
    print(f"  {'caught' if hit else 'MISSED'}  bare ' inside a definition         R12 tick"
          + ("" if hit else f"  (got {sorted({r for _, r, _ in f})})"))
    # R16/R18 are --phase rules: the good phase must be silent. That they stay OFF by default is proven by the
    # corpus, which keeps 05_cells.fs (a CREATE'd cell) and examples/demo_bars.fs (no CHAIN) clean without a flag.
    f = lint_phase(GOOD_PHASE)
    ok = ok and not f
    print(f"  {'clean ' if not f else 'FALSE+'}  good phase: return path, no storage  {f[:1] if f else ''}")
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
    # GUARDRAIL: --phase is OFF by default. R16 refuses storage a plain program may own, and R18 refuses a program
    # that returns to the REPL - both are correct for a phase and false positives everywhere else (docs/26).
    phase = "--phase" in argv
    # GUARDRAIL: `--repl` marks a source a harness TYPES line by line, which is the only path that meets the 63 B ring
    # limit; block uploads (everything the App Store and the corpus use) never see it. Off by default for that reason.
    repl = "--repl" in argv
    argv = [a for a in argv if a not in ("--phase", "--repl")]
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
    # GUARDRAIL: `--repl` skips the block checks as well as R1. `check_blocks` cuts the source into 92 B blocks, and a
    # typed load is never cut - it reported "REFUSING: no interpret-state boundary inside one 92 B block" on a driver that
    # the board accepts line by line, which is a true statement about an upload path nobody uses.
    findings = (lint_definitions(src, base, repl=repl)
                + ([] if repl else check_blocks(src, base))
                + (lint_phase(src) if phase else []))
    for ln, rule, msg in findings:
        print(f"  {argv[0]}:{ln}: {rule}: {msg}")
    print(f"  {len(findings)} finding(s)" if findings else "  clean")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# Ideas backlog — app space

## Next (ordered by measured support)
- **asm dispatcher (A1)**: the only lever with measured support for a big win — P50 measured **278 B** for
  loop + 4 bodies; projection 400–700 B for the full primitive set. Preconditions: extract the C switch into
  `vm_case(cf)` except the 5 bodies that `continue`/`return`, write the loop with a 2-byte offset table,
  keep the C fallback. Board-only verification.
- **cold bucket (A8)**: one call site for rarely-used primitives. Needs per-primitive frequency data first
  (temporary counter in a twin build, run suite + bench). Risk: overfitting to the bench, so choose cold
  words by "never executed by the suite" rather than "rarely by the bench".
- **`vm_task_init`/`vm_task_leave` specialisation** for NTSK==2: the zero-fill and the two-slot retire path
  are the remaining scheduler fat (~20 B at best, judging by how tight they already are).
- **`main` (890 B)**: `drain_cmd` is inlined (7 `pl_emit`, 5 `rd32` inline). A per-byte dispatch table for
  the 5 character classes may beat the if/else chain; measure, do not assume.
- **LIT2 small-literal token** (E4): 26 LIT cells × 4 B = 104 B of inline data in the baked image. A 2-byte
  cell for values ≤ 65535 saves 2 B each (−52 B) for a new case body (+30–40 B) → net maybe +12 B. Alignment
  is safe only because tokens stay 2-byte; a 1-byte cell traps.
- **code field → header bits (E1)**: needs hash12 (proven collision-free) + 2 kind bits + xt10 = 24 bits.
  Only colon words benefit (~21 × 2 B) unless primitive ids also move into the header (64 × 2 B). Larger
  refactor; `find()` must return kind+value, and the dispatcher reads a 3-byte entry instead of a 2-byte cf.

## Structural options only (local C edits no longer pay)
- **token = primitive id**: a token currently points at a 2-byte code field that names the primitive, so every
  dispatch pays a memory read and 128 B of code fields exist. If the token *were* the id, the read disappears
  and the primitive code fields vanish (−128 B code, −~30 B text). Colon words need an id range that resolves
  to a body address; that is the design question to answer first.
- **two-byte dispatch table** (−132 B rodata): needs 63 sweep cases converted from `break` to `goto`; the 5
  bodies using `continue`/`return` must be rewritten first (P50's blocker).
- **asm dispatcher**: 15 B/body vs 30 B across 64 bodies, verified board-only.

## Measured dead ends (do not retry blind)
- Compiler flags: `-fno-inline-small-functions` +76, `-fno-tree-switch-conversion` +32, `-fno-thread-jumps`
  +24, `-fno-reorder-blocks` +34; `-fno-inline-functions`, `-finline-limit=8`, `-fconserve-stack`,
  `-fno-ipa-sra`, `-fno-tree-loop-distribute-patterns` and **every** `-falign-*=1` variant = **0 B**.
- Hoisting `V->DS`: worthless — `V` is `&vm_live`, a static struct, so `ds` is already a link-time constant.
- Aliasing: the shared VM struct does **not** force `sp` reloads — zero reloads of the SP field in
  `vm_enter`, so a register-VM refactor has no aliasing relief to collect.
- Packing the P54 op table 4 B → 2 B: impossible, the entries are function pointers.
- `find()` with an aligned `lhu`: impossible, the 3-byte header stride alternates parity.
- `-msmall-data-limit=2048`: moves `.srodata.p54_binops` to its own section but emits **zero** `gp` references
  on this target; pool sum unchanged (+2 B). No gp/`__global_pointer$` support in this ULP toolchain+script.
- Inlining `rd8`/`wr8` at the 9 provably-in-range PAD sites: **+104 B**. The shared call wins.
- RVC density: already saturated (933 of 1 698 instructions are 2-byte, 2.90 B/instr).

## Instrument notes
- `tools/measure.sh` promoted as the one twin harness; `OUT=` and `SRCDIR=` are its two knobs.
- `.auto/measure.sh` = metric; `.auto/checks.sh` = suite + bench (checksums AND DISP).
- Bake with `-DP54_NAMES` and `tools/tokcensus.py` for per-word token counts — the parser wants
  `NAME <word>` lines and choked on the dump; fix the dump or the parser before relying on it.

## 1-byte primitive tokens (the largest remaining lever, ~+80..120 B, multi-step)
The old measurement ("ceiling 118 B; prototype -44 B for +352 B") was taken when a token pointed at a 2-byte
code field. That design is GONE: tokens are now addresses (even) or primitive ids (`PRIM_TAG - 2*id`, ids 0..70
fit in 7 bits). So a compiled token can be ONE byte:
    byte < 0x80 -> primitive id (0..70)
    byte >= 0x80 -> escape: the next 2 bytes are the 16-bit token (address / xt on the stack)
Compiled code is mostly primitive tokens, so the image's 366 B of code should drop sharply, at +1 B per
address token and ~30 B of escape-path text.
Required work, in order (each is small; the risk is in missing one):
1. split token emission from operand emission: `ctok(xt)` writes 1 or 3 bytes; `cw()` stays the 2-byte cell
   writer. The prelude currently uses `W,` for BOTH (`IF`: token then operand), so the prelude needs two
   words (`WT` token, `WO` operand) and `IF/ELSE/WHILE/REPEAT/UNTIL` must be updated — their `HERE 2 -`
   arithmetic still works because the operand is the last thing written.
2. dispatch loop: `b = rd8_paged(ip++); if (b & 0x80) { w = escape value; cf = tag-decode } else cf = b;`
3. EXEC/TICK keep handing out the 16-bit tagged form (stack xts stay uniform), so `run(xt)` is unchanged.
4. LIT2 becomes 1+2 = 3 B; LIT stays 1+4 = 5 B.
Verification: suite goldens, bench (DISP *will* change - the token stream changes, so this is a deliberate
re-freeze), then the full board list.

### 1-byte tokens — attempt 1 (P68) failed on a -O2-only miscompile
Implemented and got as far as: `ctok()` (1 byte per primitive, 2 bytes for an address as [0x80|hi][lo]),
`rd16u()` for operands at odd addresses, word starts aligned to EVEN in `mkhdr_pad`, cells aligned in `,`,
`WT` primitive for the prelude's token emissions, and the loop restructured to `top:` (decode w) /
`dispatch:` (table jump) / `tail:` (fetch 1 byte or an escape pair).
WHAT WORKED: the prelude bakes, `find` resolves every primitive and colon word, and the *prelude loaded
clean* (exit 0); simple lines (`5`, `: A 5 ;`, `5 0 < .`, `45 EMIT`) are correct.
WHAT FAILED: executing `.` diverges — at **-O2** it takes a ZBRANCH it should not and then reads garbage
into `ip` (EXIT popped 3 from the return stack), while the SAME source at **-O1** is correct. That is a
latent UB in the new fetch path, most likely the `goto dispatch` that jumps past `cf`'s initializer from
inside the fetch block, or the `u8 b` local shadowing the bodies' shared `b`. Fix that before anything else;
until then the change is not shippable and the tree was reverted.
PRICING so far: the ULP link no longer fitted at the old MEMSZ because the new code grew .text BEFORE the
image was re-baked (the image can only shrink after a bake). Expect to drop MEMSZ one step, bake, then raise.

### 1-byte tokens — attempt 2 (P69): the two fixes were not enough; CHANGE THE METHOD
Attempt 2 hoisted `cf` above the loop (no jump past an initializer) and renamed the fetch local to `tb`.
Result: still wrong, now at -O1 *and* -O2 (attempt 1 was correct at -O1), with a new visible symptom:
inside `.` the data stack is EMPTY at the DROP of the zero-printing path (`sp=0` at dispatch, then a POP
wraps sp to 255) and `rsp` is 5, so `EXIT` pops a token byte (3) as a return address.
STOP GUESSING. The next attempt must be a DIFFERENTIAL test, not more staring:
1. build BOTH engines (2-byte tokens and 1-byte tokens) from one source behind `-DTOK1`;
2. add a host-only tracer that, for every dispatch, prints (ip, cf, sp, sp-content) from each build;
3. run the SAME prelude + a tiny file through both and diff the traces — the first differing dispatch names
   the exact primitive whose operand or stack effect diverges, instead of an argument about `goto`s.
Only after the traces agree to the end may the ULP build, bake and board steps run.

### 1-byte tokens — attempt 3 (P70): the dual-engine build found the real problem is BISECTION ORDER
Attempt 3 built both engines from one source behind -DTOK1 (EMIT_TOK/READU macros, prefetch restructured,
WT primitive, alignments that are no-ops for 2-byte tokens). Result: **the SHIPPING engine broke too**
(`5 .` errors with no -DTOK1 at all), while `5`, `: A 5 ;`, `A` still worked. Bisecting by restoring the
original loop did NOT fix it, and the committed prelude vs the new prelude made no difference — so the
defect is in one of the pieces I believed were no-ops (clit/interpret via EMIT_TOK, the LIT/LIT2/BRANCH
readers via READU, the mkhdr_pad/COMMA alignments, or the WT primitive + P_COUNT bump).
NEXT ATTEMPT MUST APPLY THE PIECES ONE AT A TIME and run `5 .` after EACH:
  1. EMIT_TOK/READU macros only (= byte-identical output, must pass)
  2. + alignments in mkhdr_pad and COMMA
  3. + WT primitive, its table slot and the P_COUNT bump
  4. + prelude's 4 token sites
  5. + the loop restructure, still 2-byte
  6. + -DTOK1 encoder and fetch
Anything that breaks `5 .` at its own step is the culprit, and a no-op that is not a no-op is exactly the
class of bug that has now cost three iterations.

### 1-byte tokens — attempt 4 (P71): the ladder works, and it localised the break to WT
Ladder run inside one iteration (build + `5 .` + a BEGIN/WHILE/REPEAT loop after each step):
  S1 EMIT_TOK/READU macros               PASS (byte-identical, as required)
  S2 + alignments (mkhdr_pad, COMMA)     PASS
  S3 + WT primitive, its body and slot   FAIL
DISCRIMINATOR INSIDE S3: replace `X(WT,"WT",0)` by a body-less `X(ZZ,"ZZ",0)` (same id slot, no case body,
no table entry) and everything works — `5 .` = 0x35, the loop prints 0,1,2. So the P_COUNT bump is NOT the
problem; WT's case body label and/or its dispatch slot is.
SYMPTOM with WT present: the prelude still loads with NO error, `.` executes but prints 0x89 instead of 0x35,
and `BEGIN…WHILE…REPEAT` loops never terminate. With the WT slot removed, `.` and the loop become UNKNOWN
WORDS instead — i.e. the failure moves with the table entry, which points at the label-offset table.
NEXT THINGS TO TRY, cheapest first:
1. move `L_P_WT` to the END of the case bodies (just before `L_BAD`) instead of between SEMI and CREATE, and
   move its `[P_WT]` entry OUT of the `#if ... P_HAVE_ZEQ` guard it currently sits inside — a slot inside
   another primitive's guard is exactly the F-74 class of ordering bug;
2. give `P_WT` a slot pointing at an EXISTING simple body (e.g. L_P_DUP) — if the break disappears, the
   problem is the new label's POSITION, not having a new label;
3. only then re-try the real body.
HARNESS LESSON (cost me two iterations of misreading): my ladder test grepped `error` lines out of the
output, which is precisely the diagnostic that matters. Never filter a failure message while bisecting.

### 1-byte tokens — P72: THE ANOMALY IS A LABEL, NOT A WORD
Four discriminating tests, all with the prelude and a 2-line file (`5 .` then a BEGIN/WHILE/REPEAT loop):
1. `X(ZZ,"ZZ",0)` added (id slot only, NO case body, NO table entry)          -> WORKS (0x35, loop 0,1,2)
2. `X(WT,...)` + body + `[P_WT] = DISP_ENT(L_P_WT)`                           -> BROKEN (0x89, endless loop)
3. `[P_WT] = DISP_ENT(L_P_DUP)` (slot to an EXISTING body; new label unused)  -> BROKEN
4. `L_P_WT: goto tail;` (label present, body does NOTHING)                    -> BROKEN
So: the id bump is harmless, the slot target is irrelevant, and the *content* of the new label is irrelevant.
**Adding ONE case-body label anywhere between the existing bodies breaks branch execution.** With the label
removed and the slot left in, `.` and the loop become UNKNOWN words instead — the failure follows the label.
This is a toolchain/table anomaly in the computed-goto dispatch (`&&L_BAD + disp_tbl[cf]`, u16 offsets,
built with the -fno-tree-* flag set), not a mistake in the token-stream design.
NEXT (fresh session, do not guess): dump the raw `disp_tbl` bytes and the real label addresses for both
builds (with and without an extra label) and compare entry by entry — a u16 offset that differs where it
should not is the whole answer. Cheap test: try the same experiment with the -fno-tree-* flags REMOVED, to
see whether the anomaly is flag-induced.

### 1-byte tokens — P73: the table is NOT corrupt; positives are normal
Dumped `disp_tbl` as signed offsets from `L_BAD` in both builds. The failing build showed 63 positive
entries and the CLEAN build 62 — so positive offsets are NORMAL: GCC reorders blocks, so case bodies are not
laid out in source order and many legitimately sit above `L_BAD`. My earlier "a positive offset is
corruption" reading was wrong; that hypothesis is dead.
STILL TRUE and unexplained: adding one case-body label (even `goto tail;`, even unreferenced) breaks `.` and
the loop words, while an id-only dummy primitive works. Since the offset table is legitimate, the next
instrument must be a *target identity* check: make each case body begin with a unique marker (e.g. write its
own id to a global) under a debug flag, then compare, for the same input, the sequence of ids the CLEAN and
the FAILING build actually execute. The first id whose executed-body differs is the answer. That is a
behavioural diff, not a table diff.
RECOMMENDATION for the next session: if this behavioural diff does not explain it inside one iteration, DROP
the 1-byte-token lever for good. It has now cost six iterations and, at ~+100 B, it is the last big prize
but it is not worth an unbounded hunt.

### 1-byte tokens — DROPPED (P74), with the instrument built and the reason recorded
The behavioural recorder was built (host-only `beh_seq[]` filled at every dispatch, dumped at exit) and it
works on the clean build (317 ids for `5 .`). The failing build could not be compared: it reports an error
on line 1 of the input and the driver exits before the dump, so the sequences never met.
PER THE PRE-COMMITTED RULE ("if the behavioural diff does not explain it in one iteration, drop it"), the
1-byte-token lever is CLOSED for this codebase. Six iterations, zero bytes banked, ~+100 B potential.
What a future session would need before reopening it: a working behavioural diff (fix the driver to dump
before exiting on a file error), because that is the only instrument that can name the primitive whose
execution differs. Do NOT reopen it with more source reading.
WHAT THE SIX ITERATIONS DID BUY, and is reusable:
- the encoder (1 byte per primitive, 2 per address), the parity fixes (even word starts, even cells), the
  operand byte-reader and the loop restructure are all written and were individually proven to compile and
  bake the prelude cleanly;
- a precise anomaly: adding ONE case-body label (even `goto tail;`, even unreferenced) breaks `.` and the
  loop words, while an id-only dummy primitive is harmless;
- and the knowledge that positive `disp_tbl` offsets are NORMAL (GCC reorders blocks), which killed the
  table-corruption theory.

### 1-byte tokens — P75: the behavioural diff WORKS and names the divergence
Harness repair first (this is why the earlier attempts saw "no divergence"): the dump was only at exit, and
the driver exits on the first file error, so the failing build always produced an EMPTY sequence - four
iterations of "identical prefix" that were really "no data". Now beh_dump() is called from err(), from
errf_msg() AND at exit, and the failing build records 368 ids against the clean build's 317.
RESULT: at token index 298 the clean build dispatches id 27 (`/MOD`, confirmed by the P54_NAMES boot order -
the 28th name laid down) and the failing build dispatches id 71, which is OUT OF RANGE for P_COUNT=71, so the
bound check catches it and err() fires. The failing build then continues for 51 more dispatches, which is why
the symptom was "prints junk and loops forever" rather than a clean stop.
So `.` reaches `/MOD` through a token that decodes to 71 instead of 27 in the failing build: the token is an
ADDRESS token (a code field), and its target is wrong. 71-27 = 44 = DICT, which is suggestive but unproven.
NEXT (fresh session): print, for that one dispatch, the raw token `w`, `rd16(w)` and the address of `/MOD`'s
body in both builds - three numbers that decide whether the token or the code field is wrong.

### 1-byte tokens — P76: the divergence is a TOKEN VALUE, and /MOD becomes unknown
The hardened recorder now names the exact dispatch. Same position in both builds (ids 19,16,70,X,16,5,14):
  clean   X = 27, token w = 4040
  failing X = 71, token w = 3952
So the COMPILED TOKEN for the word at that source position differs; the streams are otherwise identical.
And in the failing build, `' /MOD .` FAILS ("unknown") while the clean build resolves it — so /MOD is not
findable once the extra primitive exists. That is consistent with its header having been shadowed or never
written, and NOT consistent with the simple "WT collides with /MOD" theory I tried first: defining a COLON
word named WT in the clean build does NOT break /MOD (measured: `10 3 /MOD . .` still prints 31).
NEXT: dump the stored 12-bit key of /MOD's header and of the new primitive's header in the failing build.
Two numbers decide between "collision" (equal keys) and "the header was never written / written elsewhere".
INSTRUMENT NOTE (worth keeping): the recorder dumps from err(), errf_msg() AND exit - without the first two
the driver's exit hides the sequence, which is what made four earlier attempts report "no divergence".

### 1-byte tokens — CLOSED FOR GOOD (P78). Two theories tested, neither explains it.
What P77/P78 established, with data:
1. COLLISION IS REAL BUT NOT THE BLOCKER. The test primitive named "WT" collided at 12 bits with another
   word: the chain dump showed two entries with key 0xba1, and the newer one shadows the older. Renaming to
   a name that passes the bake's check (WT2/TKN2/TC/CT: no FATAL) does NOT fix `.`.
2. THE FAILURE IS NARROW AND STRANGE. With one extra primitive in the vocabulary: `' DUP` and `' IF` both
   resolve, and the prelude loads with no error, but `.` alone becomes unfindable -- `.` is defined late in
   the prelude.
3. TWO OF MY "CLEAN" CHECKS WERE VACUOUS. The collision checker exit(3)s before the chain dump, so
   "duplicates: 0" twice meant the dump never ran; and earlier the behavioural dump was skipped by the
   driver's exit. Rule for the next session: a diagnostic's output must be PROVEN present before its
   silence is read as absence.
FINAL: closed. Ten iterations, no bytes. The lever is ~+100 B and genuinely attractive, but the failure mode
is unexplained and every instrument I have says "one word in the dictionary disappears when the vocabulary
grows by one". Recorded honestly rather than left as a mystery with a misleading trail.

### 1-byte tokens — FINAL CLOSE (P79). What fails is now precise, and it is not what any of my theories said.
Working baseline (measured, this iteration): primitive `X(TKN,"WT2",0)` added, case body `cw((u16)POP())`,
table slot -> its own label, prelude UNCHANGED -> everything works: `5 .` = 5, a BEGIN/WHILE/REPEAT loop
prints 0,1,2, the chain head is `.` at V_LATEST with key 0xba6/token 252, exactly as the clean build.
Failing: the SAME primitive plus the prelude's four `['] 0BRANCH/BRANCH W,` sites rewritten to call it ->
the prelude still defines `(0BR)` (line 34) and `IF` (line 35) WITHOUT error, but at line 70 compiling `.`
reports `IF?` - i.e. `IF` is FINDABLE at line 35 and GONE by line 70. Not exhaustion (MEMSZ 2296 fails the
same as 2100), not a collision (four names tested, none reported FATAL), not the toolchain, not the primitive
itself (proven by the working baseline above).
That is where it stands: an entry that exists and then does not, inside one prelude load. Eleven iterations,
zero bytes. CLOSED. If anyone reopens this, start by dumping the chain head and searching for `IF`'s key after
line 35 and after line 60 - the disappearance is the whole bug.

### P80 — the last C-level shapes, measured and closed
- `-fwhole-program` (+4 B), `-fipa-pta` (0), `-fno-semantic-interposition` (0), `-fno-plt` (0), `-fipa-pta
  -fwhole-program` (0): the interprocedural/whole-program space is closed.
- `PUSH`/`RPUSH` as macros instead of out-of-line functions: the build no longer fits the ULP region at all
  (text grows enough to push .bss past `ram`). Same lesson as the rd8/wr8 inlining experiment, third
  measurement of it: on this machine the shared overflow test beats a test at every call site.
- `__attribute__((noinline))` on interpret/run_line/drain_cmd/find: +42 B (measured earlier this session).
- `__attribute__((cold))` on err/blk_xfer/vm_task_init/vm_task_leave: +2 B.
CONCLUSION: every C-level, flag-level, layout-level and data-level lever this session could reach is now
measured. The one remaining lever with a large payoff is a hand-written asm dispatcher for vm_enter
(~-400..-700 B), which is a written, multi-session project: it must keep `ds`/`sp`/`rsp` in registers, which
is exactly what the C cannot do because PUSH/POP are shared functions — and that sharing is itself worth
bytes, which is why the macros above lost.

### P81 — the asm project, scoped with measured numbers
The search space is closed except for the asm dispatcher. Scope it from the artifact, not from feeling:
  vm_enter                 2 190 B  (nm -S)
  case-body labels           65     (64 in p31_cases.inc + BLKXFER)  => ~33 B per body
  `goto tail;` epilogues     68     => 136-272 B of jump alone (2 B RVC `j` or 4 B `jal`)
A hand-written asm dispatcher that keeps ds/sp/rsp in registers targets ~15 B per body instead of ~33,
i.e. -400..-700 B realistic, and it also deletes the 68 epilogue jumps by falling through.
WHAT IT MUST PRESERVE (all of it is currently enforced by C):
  - POP()/RPOP() wrap: `ds[--sp & (SD-1)]`; sp/rsp are u8 and WRAP to 255 below 0;
  - PUSH/RPUSH refuse at SD and set stack_ovf, which the dispatch boundary reports loudly (ERR_STACK);
  - the tag decode: token >= PRIM_TAG-2*(P_COUNT-1) is an id, else rd16(w) is the code field;
  - the bound check before the table jump (mem[] can hold any halfword);
  - the HOST build must keep the C bodies (#ifdef HOST), so the host suite still validates everything the
    asm is replacing - that is the only cheap oracle for this work.
CLOSED THIS ITERATION (measured): interprocedural/whole-program flags (+4/0); PUSH/RPUSH as macros (region
overflow); per-function optimize("O1"/"O2") on vm_enter (both fail to link = bigger); blkvars[2] both live
(blkn, blkdirty).

### P82 — the C ceiling, measured precisely: register-resident SP cannot be done in C here
Attempted the last structural idea in C: hoist `sp`/`rsp` from VM fields into vm_enter locals (exactly like
`w`/`ip`), extend VM_FLUSH/VM_RELOAD, and flush around the three out-of-line block words.
RESULT: every host test fails, immediately and totally. The reason is structural, not a slip: `PUSH` and
`RPUSH` are file-scope FUNCTIONS that write `V->SP`, while the hoisted bodies read `lsp`. So the hoist
requires PUSH/RPUSH to become macros at the body site - and that was measured two iterations ago: it grows the
image past the ULP region by itself.
THE WALL, now measured from three directions:
  1. rd8/wr8 inlining at the PAD sites: +104 B;
  2. PUSH/RPUSH as macros: does not fit the region;
  3. sp hoisting (this): impossible without 2.
This is the clearest evidence yet for the one remaining lever: an asm dispatcher gets register-resident ds/sp
for FREE in bytes, because asm needs no function call and no macro expansion to keep them in registers - the
very trade that makes the C versions lose. Nothing else in C can reach it.

### P83 — hash-sorted primitive headers: the last sub-100 B design, written up not started
UPPER BOUND: 68 B (68 primitives x 1 B), and it makes primitive lookup a binary search instead of a walk.
WHY IT IS POSSIBLE NOW: a primitive's token is arithmetic in its id (`PRIM_TAG - 2*id`), so its 3-byte header
stores hash12 + token11 + imm1 where only the hash and imm are actually needed. A 2-byte entry
(hash12 + imm1 + 3 spare) would do IF the id could come from the entry's POSITION - and it can, if the
primitive region is stored SORTED BY HASH, laid down in that order at boot, with `id = sorted position`.
WHAT IT NEEDS, in order (each is small, each must be proven before the next):
  1. a GENERATED file listing the primitive ids in hash order (the bake computes hash_pad for each name and
     emits the permutation). The generator must be re-run when a name changes - the same discipline as
     p54_gen.py, and for the same reason: two copies of one ordering is this project's F-74 class.
  2. `boot_init` lays primitive headers down in that order (2-byte entries, from a fixed base), not in enum
     order; `find`'s primitive branch becomes a binary search over the sorted keys.
  3. the dispatch table is PERMUTED so table[sorted position] is the label for that id; the table already
     exists (142 B), so this costs 0 B - it only reorders its initialisers.
  4. `find` must scan the colon chain FIRST (prelude words shadow primitives, as today).
PRICING, from measurements already in this file: the earlier two-region split cost +104 B of find because the
second scan was LINEAR over 2-byte keys. A binary search over 68 sorted keys is ~6 probes, no scan - but the
+104 B measurement is the warning: implementation cost is not obviously below 68 B, so MEASURE IT IN SMALL
STEPS (sorted region + linear scan first) before committing to the binary search.
RISK: the hash-sorted order is a SECOND copy of the vocabulary ordering, exactly the class that produced the
pids.h drift earlier this session. The generated file must be asserted against the enum (static asserts on
count and on each id appearing once) or it will rot silently.

### P84 — tree integrity confirmed at the convergence point
- The bake is DETERMINISTIC: a fresh `tools/bake.sh 2296` reproduces `src/image.h` byte-for-byte (same md5,
  no git diff). That matters because this session changed the dictionary layout, moved PAD 16->12 and DICT
  48->44, replaced the header accounting for two regions and deleted state; a non-deterministic bake would
  mean the shipped image is not the image the source describes.
- The host suite, the bench and the 26-check device regression all pass against this tree.
- `dispatch` costs and the pool are unchanged: app 1 544 B, text 4 592, rodata 164, bss 785, pool 7 853/7 856.
CONVERGENCE: every C-reachable lever has been measured this session. The two remaining projects are written
up with prices and invariants (P81 asm dispatcher, P83 hash-sorted primitive headers). Further loop
iterations should be verification passes like this one, not forced byte hunts - a broken tree is worse than a
plateau, and the project's own rule (fail loud, never fake a green) applies to the search as much as the code.

### P85 — P83 CLOSED BY ARITHMETIC, not by another attempt
The 68 B upper bound is real, but the price is already measured:
- the earlier two-region split (2-byte primitive entries, id from POSITION, LINEAR scan) cost find +104 B of
  text against 71 B of dictionary saved: net -42 B, MEASURED.
- 2-byte entries with `id = position` need NO sorting at all (boot lays primitives down in id order), so the
  68 B saving does not require the generated permutation I proposed in P83 - the earlier split already did
  exactly this and lost on the scan.
- a binary search would replace that scan: it saves perhaps 30-40 B of text but REQUIRES the region sorted by
  hash, i.e. the generated permutation AND a permuted dispatch table. Net estimate: 71 saved - (~15 for the
  search + hash-0 refusal + reshaped mkhdr_prim + tag arithmetic ~55) => about 0, inside the noise.
So P83 is closed: its best variant nets ~0 for a generated ordering that would become a second copy of the
vocabulary order (the pids.h drift class). Not worth it.
CONCLUSION: after this, the ONLY lever left anywhere in the project is the asm dispatcher (P81), and the
reason it is the only one is measured three ways (shared PUSH/POP wins in bytes in C; asm needs no sharing).

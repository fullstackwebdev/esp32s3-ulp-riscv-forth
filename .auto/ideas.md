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

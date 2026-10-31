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

## Measured dead ends (do not retry blind)
- Compiler flags: `-fno-inline-small-functions` +76, `-fno-tree-switch-conversion` +32, `-fno-thread-jumps`
  +24, `-fno-reorder-blocks` +34; `-fno-inline-functions`, `-finline-limit=8`, `-fconserve-stack`,
  `-fno-ipa-sra`, `-fno-tree-loop-distribute-patterns` and **every** `-falign-*=1` variant = **0 B**.
- Hoisting `V->DS`: worthless — `V` is `&vm_live`, a static struct, so `ds` is already a link-time constant.
- Aliasing: the shared VM struct does **not** force `sp` reloads — zero reloads of the SP field in
  `vm_enter`, so a register-VM refactor has no aliasing relief to collect.
- Packing the P54 op table 4 B → 2 B: impossible, the entries are function pointers.
- `find()` with an aligned `lhu`: impossible, the 3-byte header stride alternates parity.
- RVC density: already saturated (933 of 1 698 instructions are 2-byte, 2.90 B/instr).

## Instrument notes
- `tools/measure.sh` promoted as the one twin harness; `OUT=` and `SRCDIR=` are its two knobs.
- `.auto/measure.sh` = metric; `.auto/checks.sh` = suite + bench (checksums AND DISP).
- Bake with `-DP54_NAMES` and `tools/tokcensus.py` for per-word token counts — the parser wants
  `NAME <word>` lines and choked on the dump; fix the dump or the parser before relying on it.

# P12 — What does the engine cost at 32-bit references with paging?

| | |
| --- | --- |
| Runs on | **host only** (needs the RISC-V toolchain, not the board) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P01 (engine size), P02 (32-bit references) |
| Blocks | the 440-byte spare in §4.3; resolution A itself |
| Serves | R1, R5 |

## Question

P01 measured the engine at **3818 B** with 16-bit tokens. The design now uses **32-bit xts** (P02) and
**4 × 256 B frames** (P03e). Nobody has measured the engine *after* those changes. Does the 440-byte
spare survive — or was resolution A computed against an engine that no longer exists?

## Why it matters

§4.3 says the resident dictionary needs ~1096 B and has 1584 − 48 = ~1536 B, leaving ~440 B. If the
32-bit engine grows by 600 B, the spare is gone and the prelude has to be split or paged — a different
design, not a tuning change.

## Given — do not re-derive

* P01: 16-bit engine **3818 B** (`.text` 3556 + `.rodata` 252), `.bin` 3948 at `MEMSZ` 2560, `.data` 0,
  engine `.bss` 222. Build recipe and stub-subtraction technique are in `probe/results/P01-engine-size/`.
* P02: 32-bit references cost 1.49× the dictionary, 39.2 B/word.
* §4.3 budget: total 8176; engine + 150 VM + 1024 frames + 200 table + 400 stacks + 600 rings +
  400 C stack; dictionary gets the rest.
* P05 (for context): 19 MHz, 4 cycles/ALU, 8.1/word load.

## Method

1. Copy `probe/results/P01-engine-size/` into `probe/results/P12-engine-32bit/`. Reuse its IDF project,
   its stub, and its measuring script — do not invent a new build path.
2. Take P02's 32-bit variant of `uforth.c` (in `probe/results/P02-token-width/`) as the source, so the
   width change is the measured one, not a fresh rewrite.
3. Add what the design now requires and P01's build did not have:
   - 4 × 256 B frames + a 4-entry page table (static arrays; they are `.bss`, so they should move
     `.bin` by zero — prove it);
   - the paging call sites in the fetch path (`rd32(ip)` through `resolve()`), stubbed so they compile
     but do not fault.
4. Measure: `.text`, `.rodata`, `.data`, `.bss`, `.bin`; then subtract the stub (P01's `-DP01_STUB_ONLY`
   control link) to get the engine figure.
5. Recompute the §4.3 table with the measured engine; state the dictionary headroom and the spare
   after the 48 B line buffer.
6. Report the delta to P01's 3818 B and, if it is large, the **biggest contributors** from
   `nm --size-sort`.

## Record

| Item | Value |
| --- | --- |
| engine `.text` / `.rodata` / total | bytes |
| `.data` / `.bin` at the design's `MEMSZ` | bytes |
| delta vs P01's 3818 | bytes, % |
| frames + table cost in `.bin` | must be 0 |
| dictionary headroom / spare after the 48 B | bytes |
| top five symbols | name + size |

## Pass criteria

* engine measured with the same recipe as P01 (stub subtracted, build reproducible);
* frames and page table proven not to inflate `.bin`;
* the §4.3 table recomputed, with the spare stated as a number.

## Failure criteria — and what each changes

* **Spare < 150 B** ⇒ resolution A is insufficient. `01-proposal.md` §4.3 must say the prelude itself is
  paged (only the hot core stays resident) and the "first `WORDS` may fault" concession becomes "most
  of the standard vocabulary may fault".
* **Engine > 4.2 KB** ⇒ the §12 stop condition. Report `FAIL` with the number; do not trim features to
  fit.
* **Frames/table inflate `.bin`** ⇒ the arrays are not `.bss`; the boot path must zero them instead.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — the measured engine row, the recomputed headroom, the new spare.
* `probe/EVIDENCE.md` — an entry under E-010.

## Do not

* Do not optimise, inline, or rewrite the interpreter to make the number smaller. Measure what the
  design needs.
* Do not touch the board, `docs/`, or other probes' directories.

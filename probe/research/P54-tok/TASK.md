# TASK — Idea 4: variable-length tokens (1-byte codes for the hottest words)

Read `../SHARED_BRIEF.md` first. This is the highest-risk idea on the list; a measured **NO-GO is a good
outcome** and costs nothing but honesty.

## The idea
Tokens are currently uniform **2 bytes** (16-bit word id), and the code area is **578 B** of the 1 400 B
`mem[]`. Emit **1 byte** for the most-used words and an escape + 2 bytes for the rest. If ~80 % of dynamic
tokens are 1 byte, the *baked* code area could fall by 150–200 B, which is application space.

## Why it is dangerous — enumerate these BEFORE writing code
1. **Branch operands.** `IF`/`THEN`/`BEGIN`/`UNTIL` emit `0BRANCH`/`BRANCH` tokens followed by a **2-byte
   operand cell** (`W,` not `,` — a known bug class in this tree). With 1-byte opcodes, every "skip the
   operand" calculation changes, and the operand is no longer at a fixed stride from the token.
2. **`HERE`/`LATEST`/compiled addresses** are byte offsets into `mem[]`; immediates compute them. Any stride
   change must be recomputed in `W,`, in the immediate words in `src/p39_prelude.fs`, and in the bake.
3. **P46's number-first path and direct `find()`** assume how a token is fetched and decoded.
4. **The checkpoint write** in the dispatch loop stores `(w, ip)`; a variable-length fetch changes what `ip`
   points at mid-instruction.
5. **The baked image** (`src/image.h`) is a byte image of `mem[]`; a new encoding must be re-baked and the
   host and chip must agree byte-for-byte (`tools/bake.sh`).

## Steps
1. **Measure the headroom first**: how many *distinct* tokens does the baked prelude contain, and what is the
   frequency distribution? (You can count tokens statically from the baked image; do not guess.) Report the
   theoretical best case: `Σ(count × (2−1))` bytes.
2. **Prototype the encoding only on paper + a decoder in C**, then implement in the twin. If at any point the
   branch-operand stride cannot be made safe, STOP and report NO-GO with the specific reason.
3. Measure Δ`.text` (fetch/decode) and Δ dictionary/code size separately. The net is what matters.
4. `tests/run.sh` green, `bench/run.sh` results **identical** (checksums, not just "no crash"), re-bake done.
5. State the cycle cost: the fetch is on the hottest path; you cannot measure cycles on the host — say so.

## Deliverable
`FINDINGS.md`: token frequency table, theoretical best case, measured result, the failure modes you closed
or could not close, verdict, diff. If NO-GO, name exactly what would have to change.

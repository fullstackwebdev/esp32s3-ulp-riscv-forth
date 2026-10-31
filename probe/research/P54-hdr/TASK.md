# TASK — Idea 3: 3-byte dictionary header (go/no-go first)

Read `../SHARED_BRIEF.md` first.

## The change
Headers are 4-byte entries growing **down** from `HDRTOP` (= `BLKADR` 1 272), stride 4:
`hash20 | xt11 | imm1`, 85 words = **340 B**. Shrinking to 3 bytes (`hash13 | xt10 | imm1`) moves `V_LATEST`
up by **85 B**, i.e. app space 354 → 439 B, minus the extra `.text` for a 3-byte load.

## Steps — go/no-go comes first
1. **Collision search.** 13 bits over 85 words: expected collisions ≈ `85·84/2 / 8192 ≈ 0.44`. Search hash
   multipliers/functions at bake time and report whether a **collision-free** hash13 exists for the current
   vocabulary. **If none exists, that is the answer** — report the search evidence and stop. Do **not** weaken
   the collision check to make it pass; a silent collision means one word shadows another.
2. If a clean hash exists: `xt` must fit 10 bits. `xt` is a byte offset into `mem[]`, and tokens are 16-bit, so
   all code offsets are even — store `xt/2`. Prove that in code (a `_Static_assert` or bake-time check), never
   in prose.
3. Measure the 3-byte read cost in `find()` (likely two loads + shift/mask) as Δ`.text`, honestly, against the
   +85 B of dictionary area.
4. Re-bake a test image (`src/image.h`) and run `tests/run.sh`. `lookup.fs` (case-insensitivity, newest-wins)
   and `semantics.fs` (storage rules) must both pass.
5. State the net: 85 B gained minus Δ`.text`, and confirm `image_boot_assert`'s expectations
   (`V_LATEST <= MEMSZ`, `V_LATEST & 3 == 0`, `V_HERE <= V_LATEST`) still hold — note that a 3-byte stride
   **breaks the `& 3` alignment assumption**, so that assert and `_Static_assert(HDRTOP % 4)` must be revisited
   deliberately, with a guardrail.

## Deliverable
`FINDINGS.md`: hash search result (with the evidence); measured Δ`.text` table; net byte figure; diff; verdict.
If NO-GO, state exactly what would have to change for it to become possible.

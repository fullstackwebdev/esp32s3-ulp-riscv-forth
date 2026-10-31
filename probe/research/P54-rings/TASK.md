# TASK — Idea 5: merge the output and command rings — ONLY if capacity provably does not drop

Read `../SHARED_BRIEF.md` first.

## The condition the operator set
The change is acceptable **only if the bytes available to input and output in the worst case are at least
today's**. Today: command ring **64 B** (`repl_cmd`), output ring **128 B** (`repl_out`), separate, each able
to be **full at the same time** = **192 B** of buffering. A single 128 B ring saves 64 B of `.bss` and
**halves** the worst case; that is a capacity loss and is therefore **NO-GO by construction**. Do not report it
as a win.

## What to do
1. **Define capacity precisely and write it down**: for each direction, the maximum bytes that can be buffered
   while the other direction is also saturated. Cite the code that reads/writes both rings
   (`src/ulp_repl.c`: `drain_cmd`, `pl_emit`, `CMD_SIZE`/`OUT_SIZE`/masks).
2. **Prove or disprove** that a merged single buffer can meet or beat 64 + 128 simultaneously. Consider and
   measure (statical analysis is fine, there is no host timing model):
   - a single 192 B buffer with a hard split → saves **0 B**, capacity identical. If this is the only safe
     shape, say so plainly: the idea yields nothing.
   - a single 192 B buffer with dynamic sharing → capacity depends on the workload; state the workload for
     which it loses, with the arithmetic. A single lost case is NO-GO.
   - independent 64 + 128 (today) → the reference.
3. If and only if you find a shape that is provably ≥ today's capacity in the worst case, implement it in the
   twin, measure Δ`.bss` and Δ`.text`, and run `tests/run.sh` plus the ring tests (`ring drain`, `ring_test.c`).
4. **The drop-count question**: `pl_emit` drops bytes when the output ring is full. Any merged design must
   state which bytes it drops and prove it drops no more than today in the worst case.

## Deliverable
`FINDINGS.md`: the capacity definition, a table of candidate shapes (`shape → worst-case input B → worst-case
output B → Δ.bss → verdict`), and an explicit GO/NO-GO. A NO-GO with the arithmetic is the expected and
acceptable answer — do not manufacture a win by shrinking capacity.

# 24 — The asm dispatcher: what must not change, and the gate that proves it

## Why this exists

`vm_enter` is **2 302 B of a ~5.9 KB ULP image (39 %)** and inside it are **255 decode-shape instructions**
(`andi`/`slli`/`li`/`addi`) plus **44 branches** ≈ **~860 B of pure dispatch scaffolding** at 2.87 B/instr. There is
**not one `jalr`** in it: the interpreter is a compare cascade, not threaded code. A threaded asm inner loop (one indirect
jump per token, `ds`/`sp`/`rsp` in registers) attacks exactly those bytes. Realistic target **400–700 B**, upper bound ~860.

Freed image bytes become resident app space **1:1**, but only when `MEMSZ` grows by the same amount — and `flash_safe.sh`
is the budget authority, so a refusal there is information.

## The verification problem, stated first

The host suite (24 tests) runs the **C engine**. It cannot execute a ULP asm loop, so **none of the existing green tests
cover this change**. The safety net is therefore:

1. **`tests/golden_battery.py`** — a behavioural battery recorded from the current build
   (`tests/golden/device_battery.json`, 17 entries). Values only: **no addresses, no xts, no timings**, because every
   address moves when the image size changes.
2. The existing device gates: `capabilities.py` 11/11, 15 phases from images, `flash_persist` 3/3, wear counters.
3. The C path stays behind a define until all of the above are green twice.

## Invariants the asm loop must preserve

1. **Token format.** u8 tokens; primitive tags are the top `P_COUNT` values: `PRIM_TAG - 2*(P_COUNT-1)` … `PRIM_TAG`.
2. **u8 wrap.** Token arithmetic wraps mod 256 exactly as the C build does. No widening to 16 bits, no saturation.
3. **Data stack.** `SD` = 16 cells. **Underflow is not free**: `DROP` on an empty stack answers `stack?` (recorded in the
   battery), while some paths wrap silently — the asm loop must reproduce *both*, not unify them.
4. **Overflow reporting** lives in the dispatch tail (`stack_ovf`, which is also a dictionary symbol). If the loop's tail
   moves, the report moves with it or the check dies.
5. **Registers.** `ds` (data stack pointer), `sp` (instruction pointer), `rsp` (return stack pointer) must be spilled
   before any C primitive call and reloaded after — or C must adopt the same convention. Every exit path counts: error,
   `err()`, `msg()`, the `blk_xfer` wait, and the wake/halt boundary.
6. **Task state.** `tskvm` / `vm_live` / `vm_switch` / `vm_task_leave` assume the interpreter's frames are in memory, not
   registers. A register-resident `sp` that is not spilled before `vm_switch` will resume at the wrong token.
7. **The block layer.** `LOAD` arms `V_LOADB` and feeds tokens through `word()`; the refill loop must see the same
   registers it sees today.

## Open questions raised while building the gate (do not lose these)

1. **A dump+adopt after an error hangs the machine.** After `NOPE` (undefined word) or a refused `BLOCK`, running the
   image cycle ends in `W @ EXECUTE` silence for 15 s. A rewind is the only difference from the passing path. The battery
   now runs the image cycle **first** and the error entries **last** so the gate cannot depend on it either way.
2. **`9 LOAD` of `: T 7 . ;` answers `T?`** immediately after an image cycle, while `step4`/`capabilities` load the same
   way and pass. Until the disagreement is explained, the `load` entry is **excluded** from gold rather than guessed.
3. **A 60-char line of `DUP ` repeats arrives as 55 bytes + a 5-byte `DROP` line** ("line too long: 5 bytes"), while a
   64-char line is refused correctly as 64. Mid-line splitting is the class that once corrupted long definitions
   silently — this needs an explanation before any long-line guarantee is claimed.
4. **`BLOCK` always re-fetches**, and the dirty check only refuses a *different* block, so a same-block re-read without
   `SAVE` returns the stored bytes (recorded as `block-refetch`: wrote 200, read 32). Deliberate gold, so a change to it
   is visible.

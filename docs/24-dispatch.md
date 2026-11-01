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

---

## Open questions, resolved (branch `error-path`)

### 1. "An image cycle after an error hangs" — WRONG, and it was my battery
Measured: `' W .` answers **786 before and after** an undefined-word error, so a rewind does **not** remove words defined
since boot, and `NOPE` → image cycle → `EXECUTE` runs correctly (`[8320, 540800]`). Four independent trials (no prelude,
`DROP`, `NOPE`, empty `LOAD`) all pass. The battery hang had a different cause, found in #2.

### 2. `LOAD` then a phase compile — REAL, reproduced 2/2
After a source `LOAD` that compiles a word, then `SEAL`/`2 OVL`, the phase `LOAD`s answer **`7TW?` `TW?` `IDX?`** — `CREATE
tw` never runs — so `HERE` advances 10 B instead of ~516, the dump is a **10 B stub**, the loader adopts it, and `EXECUTE`
hangs with no error anywhere. Clean run for comparison: `HERE` 786 → 1 302 across the same eight blocks.

Two things were done, neither of which hides it:
- **`step4.build_and_adopt` now refuses a stub**: `ce - cs < 200` raises `"phase code is only N B, expected ~500"`.
- The **engine cause is still open**: a prior block-source compile poisons the next one. Tracked here, not fixed.

### 3. "A 60-char line splits mid-line" — WRONG, it was my capture
Measured with real definitions: **59, 60 and 63-char lines all compile** (`PAD59`=111, `PAD60`=222, `PAD63`=333) and a
64-char line is refused whole (`line too long: 64 bytes, the ring holds 63`). The limit is exactly as documented; the
"55 + 5 bytes" split was the sentinel reader, not the machine.

### 4. `BLOCK` always re-fetches — confirmed, kept as gold
Same-block re-read without `SAVE` returns the stored bytes (wrote 200, read 32). The dirty check only refuses a
*different* block. Recorded in the battery as `block-refetch`, which now **seeds its own block** — the original entry
read 255 on a freshly erased store and reported a false regression, i.e. it was testing store history rather than the
engine.

---

## The reclaim ceiling is the STACK REGION, not the pool budget

Growing `MEMSZ` moves the image end **up** towards the fixed stack top `0x1FF0`, so every byte added to the dictionary is
a byte taken from the stack. Measured: `MEMSZ` 2 700 → 2 744 (+44 B) pushed the image end past the canary base `0x1EAC`;
the stack paint then overwrote `.bss`, `#k` reported **316 B of 324 used**, and the battery fell to 15/17. Reverted.

`MEMSZ` 2 700 is therefore the practical maximum with this layout: stack region **332 B**, measured high-water **240 B**
(92 B margin). `flash_safe.sh`'s reserve is now **300 B** (240 measured + 25 %) instead of a pre-measurement 336 B, and it
prints the measured figure so the number cannot drift away from evidence.

---

## The TUI stack overflow: two separate bugs, one found by each tool

**Bug 1, in the app, found by the host probe (`[line] sp=…`).** Every ANSI word emitted only the letter `m`:

```
: M 109 EMIT ;        : INV ESC CSI 55 M ;        (WRONG)
```

`55` is the character `7`, and it was pushed but never emitted, so **each colour change left one cell on the data
stack**. A frame with ~8 colour changes reached `sp=16` and `ERR_STACK` killed the program at the end of the line — which
is why the menu drew perfectly and then ignored every key. Fixed by emitting the digit: `ESC CSI 55 EMIT M`.

Measured before/after on the host engine (same interpreter, no chip):

| word | before | after |
|---|---|---|
| `INV` | sp=1 | sp=0 |
| `HDR` | sp=2 | sp=0 |
| `TITLE` | sp=6 | sp=0 |
| `ITEMS` | sp=13 | sp=0 |
| `FRAME` | overflow | **sp=0 rsp=0** |

**Bug 2, still open, chip-only.** With the leak fixed the chip still reports `ERR_STACK` at the end of `RUN`'s first
frame, while the host reports a clean frame. The only difference on that path is `KEY`: the host's `pl_key` blocks on
stdin, the chip's returns −1 immediately, so `K0` (`BEGIN KEY DUP 0 < 0= UNTIL`) spins thousands of times per second.
That is the next thing to measure: a bounded loop that returns to the engine instead of spinning, or a `KEY` that waits
in the wake path.

### The tool that made this visible

`tests/tui_menu.py` — reproducible end-to-end test of the full-screen menu: fresh-boot assertion, upload, compile,
start, then **every keystroke** (`j`, `k`, arrows, Enter, an unknown key, `q`), asserting the selection's *row* (not just
that a marker exists), that no frame contains `ERR_`, that `q` leaves the alternate screen, and that the REPL answers
afterwards. `--capture` saves every raw frame. It also caught two bugs in itself: a reset that silently did not happen
(now a fresh-boot assertion with an esptool fallback) and `cmd`'s echo parsed as data (now `dev.num`).

---

## The TUI: three real defects found, two fixed, one still open (all measured)

| # | defect | evidence | state |
|---|---|---|---|
| 1 | ANSI words emitted only `m`, so `ESC[7m`'s digit was **pushed and never emitted**: one leaked cell per colour change | host probe: `INV` sp=1, `TITLE` sp=6, `ITEMS` sp=13 → after fix all **0** | **fixed** |
| 2 | the key-wait loop leaked per poll: `BEGIN KEY DUP 0 < 0= UNTIL` leaves the `-1` on the stack when no key is waiting — thousands of polls per second | chip: `j`/`k` moved the menu 2 items then `ERR_STACK`; loop now `BEGIN KEY DUP -1 = WHILE DROP REPEAT` | **fixed** |
| 3 | single-slot keybox dropped the **middle byte** of `ESC [ B`, so arrows did nothing while `j`/`k` worked | test: `j-down` PASS row 5, `arrow-down` FAIL row 5 | host now **queues 8 bytes** and feeds the box as it empties; the arrow path still raises `ERR_STACK` — open |

`tests/tui_menu.py` reports 7/12 today: fresh boot, compile, first frame, `j`–`j`–`k` (rows 4→5→6→5) all PASS; the four
chevron/quit checks FAIL. `q` and `Enter` cannot be judged until the arrow path stops erroring, because the error kills the
program and every later key is delivered to a dead app.

**Next step, precisely:** `27 STEP` with `[` and `B` fed afterwards returns immediately with SEL unchanged, which means
`KEY` handed the arrow handler a byte it did not expect (most likely the CR of the line that started it, or a stale box
byte from before the reset). The arrow reader must ignore anything that is not `[`/`A`/`B`/`C`/`D` instead of trusting the
next byte to be the bracket.

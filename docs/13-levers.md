# 13 — The levers, measured

Goal: **keep all functionality, hold the pool under 7 856 B, and grow app space.** Every number below is measured
on this machine with `probe/lev/ulpmeasure.sh` (compile one candidate source, relink against the prebuilt ULP core
objects, read `size`); commands are in the per-lever directories. Nothing here is an estimate unless labelled.

**App space = `MEMSZ` − `V_HERE` at boot**, and `V_HERE` is **1 136 B** — read straight out of the baked
`image.h`: 1 136 bytes of initialised dictionary, `V_LATEST = 1 000`.

## The correction that changes the goal

The project documents have said app space is **620 B**. It is **144 B**. The 620 figure came from `MEMSZ 2 196`
minus the dictionary and the block layer — but `MEMSZ 2 196` does not fit in the shipping pool at all
(pool would be 8 180 B). **620 B was never achievable in this image**, and the difference between 144 and 620 is not
a rounding error: it is the difference between a machine that holds a two-word program and one that holds a real one.

| | measured |
|---|---|
| `MEMSZ` | 1 280 |
| dictionary at boot (`V_HERE`) | **1 136** |
| **app space** | **144 B** |
| pool used / limit | 7 264 / 7 856 (592 spare) |

## The free lunch: `MEMSZ` was pinned to the baked image size

`image.h` declares `static u8 mem[MEMSZ] = { …1 136 bytes… }`, so `mem` sits in `.data` and **every byte of `MEMSZ`
above 1 136 costs exactly one byte of pool**. Nobody had raised it, so **592 B of the pool was idle while app space
was 144 B.** There is no code change involved: regenerate the image with a larger array.

| `MEMSZ` | pool | spare | app space | verdict |
|---|---|---|---|---|
| 1 280 | 7 264 | 592 | 144 B | today |
| 1 400 | 7 384 | 472 | 264 B | |
| 1 640 | 7 624 | 232 | 504 B | |
| 1 760 | 7 744 | 112 | 624 B | |
| **1 872** | **7 856** | **0** | **736 B** | **free-spare ceiling, zero code change** |
| 1 880 | 7 864 | −8 | — | **OVERFLOW** |

1:1 confirmed at every step (`+120 MEMSZ` → `+120 .data`), and overflow fails **loudly** (negative spare; the link
itself still succeeds, so the guard has to be the size check, not the linker).

## The other levers, each measured on top of the ceiling

| Lever | `.text` | `.data` | `.bss` | pool | spare | app space after |
|---|---|---|---|---|---|---|
| baseline | 4 508 | 1 288 | 1 152 | 7 264 | 592 | 144 B |
| `MEMSZ` → 1 872 | 4 508 | 1 880 | 1 152 | 7 856 | 0 | **736 B** |
| **+ rings shrunk** (cmd 128→64, out 256→128, tib 128→96) | 4 504 | 1 880 | **928** | 7 628 | 228 | **964 B** |
| **+ `NTSK` 3→1** (two task records) | **4 430** | 1 880 | **872** | 7 498 | 358 | **1 094 B** |
| **+ both, `MEMSZ` 2 452** | 4 432 | 2 460 | 648 | **7 856** | **0** | **1 316 B** |

Notes that matter:

* **Rings → −224 B**, exactly as predicted (`repl_cmd` 128→64 = 64, `repl_out` 256→128 = 128, `tib` 128→96 = 32).
* **`NTSK` 3→1 → −280 B of `.bss` *and* −78 B of `.text`** (4 508 → 4 430): the round-robin search and the task
  copy shrink with the count. A lever that saves code as well as data is rare here.
* **Full `tsk` removal** (all 420 B, not just two records) needs the pause path and `vm_task_leave` gone too; the
  measured 280 B is the conservative case, and 420 B is the upper bound from the symbol size.
* **App space went 144 → 1 316 B (9.1×) with 0 B spare and no functionality removed** except two idle task
  records and two thirds of the console rings.

## What each lever costs in behaviour (not bytes)

* **Rings at 64/128:** the ULP drains 32 command bytes per wake, so a 64 B command ring is two wakes of typing
  (~13 ms at the measured period) — fine for a human, and it still bounds a paste. The 128 B output ring holds
  about three short reply lines; `pl_emit` drops and counts beyond that, so the drop counter must stay reachable.
* **`NTSK` 1:** two fewer concurrent tasks. Tasks are not reachable today anyway (creation was GC'd), so this
  costs nothing now and *blocks* nothing later — raising `NTSK` again costs 140 B per task, which is affordable
  once app space is 1 316 B.
* **C-stack reserve (320 B):** untouched. P21 measured 244 B worst case, but trimming it trades a safety margin for
  60 B and cannot be justified while 592 B is idle. **Do not spend it.**

## Consequences for the plan

1. **Raise `MEMSZ` to 1 872 immediately.** It is free, it needs only image regeneration, and it multiplies app space
   5.1×. It should be the next change, before any further optimisation.
2. Then rings, then `NTSK`, then `MEMSZ` again up to the new ceiling — in that order, because each one *raises* the
   ceiling for the next.
3. Blocks still do not fit (456 B of words inside `MEMSZ` + 512 B buffer), but the arithmetic has changed: at
   `MEMSZ` 1 872 the dictionary has 736 B free, which is enough for the **456 B of block words**; the 512 B buffer
   would still need to come out of the pool. That is now a real design option rather than a fantasy.


---

## Applied and verified on the board

| Change | Pool | App space | Verified on the chip |
|---|---|---|---|
| before | 7 264 / 7 856 (592 spare) | **144 B** | — |
| `MEMSZ` 1 280 → 1 872 | 7 856 (0 spare) | **736 B** | `HERE .` → **1 136**; `: SQ DUP * ;` → `HERE .` → 1 150; `2 3 + .` → `5 ok`; `7 SQ .` → `49 ok`; `BOGUS` → `BOGUS?` |
| rings 64/128, `MEMSZ` → 2 048 | **7 840 / 7 856** (16 spare) | **912 B** | `HERE .` → 1 136; `5 ok`; `49 ok`; `CUBE?` for an undefined word; paced input exact line for line |

Measured on the board, not inferred: `HERE .` prints **1 136** at boot, which independently confirms the
`V_HERE` value decoded from `image.h`, and it climbs by 14 B for `: SQ DUP * ;` — so the 912 B of app space is real
space a definition can occupy.

### Two corrections found while applying it

* **The pool ceiling moved when the rings shrank.** Pool = `MEMSZ` + 5 798 with the 64/128 rings (`.data` =
  `MEMSZ`+8, `.text` 4 830, `.bss` 960), so the ceiling is **2 058**, not the 2 064 the earlier table implied —
  the ring edit itself moved `.text` by 6 B. First attempt at 2 064 landed 6 B over. **Recompute this constant
  whenever `.text` or `.bss` changes, because overflow is silent.**
* **A fast burst queues rather than corrupts.** Twenty definitions sent at 0.12 s intervals all landed and were
  echoed, several seconds behind, because the ULP drains 32 command bytes per wake and the console is paced. Paced
  input is exact. The *drop* counter (`repl_out_drop`) is not exposed to the host — worth exposing, because with a
  128 B output ring a truncated reply and a wrong answer are currently indistinguishable from outside.

### Not applied, deliberately

`NTSK` 3→1 would return a further 358 B (280 of `.bss` plus 78 of `.text`) and raise app space to ~1 270 B. It is
left alone because it removes concurrency slots, and the brief is *keep all functionality*. Tasks are unreachable
today, so it costs nothing now — but spending 358 B to delete a capability is a different trade from spending 0 B to
reclaim idle pool, and it should be a deliberate decision rather than a side effect of a size sweep.


---

## R4 was taken (P43), and it cost more than a budget line

| | before R4 | with R4 |
|---|---|---|
| `.text` | 4 518 | **5 014** (+496) |
| dictionary at boot | 1 136 | **1 146** (+10 for the `SPAWN` header) |
| `MEMSZ` | 2 048 | **1 500** |
| **app space** | **912 B** | **354 B** |
| pool | 7 834 | 7 842 / 7 856 |

So the machine traded 558 B of app space for a requirement. That is the honest accounting: R4 is not free, it was
paid for out of the app-space win, and the 420 B of task records were already spent before it existed.

Verified on the chip: `SPAWN TA SPAWN TB` with `PAUSE` bodies prints **1324**; three tasks print **131242**; the
REPL answers before, between and after; a dirty stack is refused **once**, loudly, and the task is retired.


---

## Two levers measured and rejected (parallel lanes, parent-audited)

**`rd32` → single `lw`: rejected.** It **costs 24 B** (text 5 014 → 5 038, pool over budget) because the 34 B
out-of-line reader is inlined 18 times, and it would **trap**: `clit()` writes a cell as two `cw()` halves with no
alignment step, so a literal's value sits at `token+2` and can be `2 mod 4`. `lhu` needs 2 and is safe; `lw` needs 4
and is fatal. The `rd16` win came from deleting a *call*, not from the load — that distinction is the whole lesson.

**Blocks: rejected for now, with the arithmetic.** `blk_place_ok` needs `V_HERE ≤ MEMSZ − 512`; with 456 B of block
words `V_HERE` becomes 1 602, so `MEMSZ` ≥ 2 114 and pool = `MEMSZ + 6 342` = **8 456, i.e. 600 B over**. Adding a
200 B app-space floor needs 800 B; holding today's 354 B needs 1 090 B. The only levers left delete R4 or 320 B of
C-stack margin. **Blocks need a different shape** — a smaller buffer, a paged reader, or storage that does not live
inside `MEMSZ` — not another size sweep.


---

## The interactive-path win (P46), and what it cost

`find()` was called first for every token and failed for every literal, paying a full 81-header scan with two calls
per header (~28 000 cycles). Number-first parsing plus direct header reads: **17.3× on literals, 4.7× on lines**.

| | before | after |
|---|---|---|
| `.text` | 5 014 | 5 156 |
| `MEMSZ` | 1 560 | 1 372 |
| **app space** | **354 B** | **226 B** |
| pool | 7 842 (14 spare) | **7 856 (0 spare)**, C-stack reserve 336 B |

That is the fourth time a win has been paid for out of app space. Worth recording plainly: **the machine now runs
at a good interactive speed and cannot fit another feature without a lever**, and the lever that would free the most
(NTSK 3→1, 358 B) deletes two of the three task slots R4 demonstrates.


---

## VICTORY: memory bar met (P47)

Bar set in advance: **app space >= 512 B, R4 intact, pool <= 7 856.** Result: **558 B**, R4 running two and three
tasks, pool **7 852**.

| lever | bytes | cost |
|---|---|---|
| hand-written VM copy replaces 2 x `memcpy` + `memset` | **−356** | none; found and fixed an 8-byte overrun in it (F-89) |
| spent on `MEMSZ` 1 372 → 1 704 | +332 app space | pool now 4 spare |

Remaining distance to blocks, with today's numbers: **~850 B**, and every remaining lever (NTSK 3→1 = 358 B, C-stack
trim = 76 B, further ring cuts ~96 B) either deletes R4's concurrency or spends the safety margin. Blocks need a
different shape — smaller blocks (256 B), a purpose-built 16 B mailbox, and the words as C primitives — not another
sweep.


---

## The next lever: assembly, priced before committing (P48)

| | measured |
|---|---|
| GCC encoding density | `vm_enter` 848 instructions in **2 392 B = 2.82 B/instr** — at the RVC floor |
| GCC cost per primitive body | **29.5 B** (64 bodies, 1 890 B; median 28) |
| hand-written body, TOS-pointer convention | **15.0 B** (measured on 6 primitives, includes `ret`) |
| projection for the whole dispatch core | **510–930 B** saved |
| blocks gap | **~850 B** |

**Verdict: worth doing, and it is the only proposal on the table that can plausibly close the blocks gap.** It is
not a byte trick — it is a convention change (pointer-to-TOS instead of index), which is exactly what a compiler
cannot express.

**Preconditions, both now met or named:** (1) a regression suite against the shipping engine
(`probe/repl/tests/run.sh`, green), and (2) acceptance that `vm_switch`/`PAUSE` must spill the new register — the
resumability contract from P27 is the real risk, and the host suite cannot test it, so a board run of the 2- and
3-task cases is mandatory after the change.


---

## The asm dispatch core: groundwork landed, projection corrected (P50)

**In the tree:** `src/pids.h` (ids for the assembler) + **13 `_Static_assert`s** in `uforth.c` binding every id and
the two layout facts (`SD == 16`, `sizeof(VM) == 136`). Build clean, text unchanged, suite green. The asserts caught
two of my own errors (guessed macro names; the `DO*` offset) as compile failures rather than as a silently wrong jump
table.

**Corrected projection.** The 15.0 B/primitive measurement assumed a valid TOS pointer and therefore omitted the
16-cell **stack wrap**. With either per-access masking (no win) or one cell of overshoot plus a per-dispatch pointer
re-derivation, the honest figure is **~18–22 B per body** → **≈ 400–700 B** for the 64 bodies, against the ~850 B
blocks gap. The asm path is now *comparable to* the primitive-subset path (2 500 B, but capability lost) rather than
comfortably better.

**Remaining work, and why it is one focused session:** extract the switch into `vm_case(cf)`; write the asm loop with
the inline cases and a fallback call; then validate — which is **board-only**, since the host cannot run RV32 asm.


---

## Standing metric: blocks countdown

**RETIRED.** `probe/repl/countdown.sh` was deleted: after application space moved into the bake, it mixed a
pool model (`-r`, `-s`, `-a` lever savings) with a baked-image measurement and printed two different
headroom figures on one line — e.g. `app space 354 B, 131 B free pool` for a lever that had banked nothing.
Pool is owned by `flash_safe.sh` (refuses to flash when over), app space by `tools/bake.sh` (prints
code/headers/free from the image it baked). The historical numbers below are kept as the record of P47–P52.

```
blocks countdown: 800 B to go  [pool 7852/7856]
  need: dict 40 + buffer 512 + block code 810 = 1362 B
  have: app 558 + pool spare 4 = 562 B
```

Target = block words as C primitives (the cheapest known shape). The ledger's key line: the target `MEMSZ` is
*below* the current one, so **the gap is block-layer code, not dictionary** — text reductions flow straight into
"have".

### The two blockers asm found before writing any

1. `P31_SUBSET`/`P_HAVE_*` gate the dictionary name and the C case body with **one** macro; "keep the name, drop the
   body" is not expressible. Workaround: manual registration in `boot_init`.
2. Five case bodies contain `continue;`/`return;` (EXIT, DO/LOOP), so the switch cannot be extracted into a
   `vm_case(cf)` fallback without editing the verbtim `.inc`. Those primitives stay in C.

Plus `default: err();` in the dispatch, so a case removed for asm can never fall through silently.


---

## P50 status: two integration shapes measured, one rejected

| shape | measurement | verdict |
|---|---|---|
| `p50_try(cf)` called from the C loop | **368 B** for 7 bodies (39 B each) vs GCC's ~84 B | **rejected** — a per-token call pays frame + compare chain + `ret` for a 2-instruction body |
| asm **replacing** the loop (jump table, no call) | **278 B** for loop + 4 bodies | the only shape that can pay; owns fetch, table, `!ip` path, fallback |

Upper bound on the prize is therefore the 719 B in E-068, and the wrap-checked operand sequence (~5 instructions per
two-operand body) is why the realistic figure is lower. Next: implement the loop-replacement form, then validate on
the board (host cannot run RV32 asm).


---

## VERDICT: the asm dispatch core is rejected on measurement

Built it, measured it, and it cannot pay. `p50_loop` (loop + 7 bodies + jump tables) is **490 B** while the seven C
cases it would delete are worth **~84 B** — a 406 B loss, and the image overflowed 8 192 B with both dispatchers
present. The C loop must remain as the fallback, so partial porting buys nothing.

Even a total port is bounded: 1 922 B realistic minus the ~450 B of C-helper bodies, and with the five control-flow
cases necessarily staying in C the figure lands at **−42 B**. Range: **40–470 B** against an 800 B countdown.

**Where blocks can still come from:**

| lever | bytes | note |
|---|---|---|
| `mailbox[54]` → 16 B | **~200** | it is block-layer bss, so it counts directly against the gap |
| 256 B blocks instead of 512 | **256** | halves the buffer; 2× the fetches at 144 µs each, still fine |
| a primitive subset (F-97) | ~220 per 5 words | capability trade, the user's call |

`200 + 256 = 456` of the 800 without giving up a single word; the remainder needs ~8 primitives retired or a smaller
block code. That is now a design conversation with real numbers on both sides.


---

## The countdown with levers combined (all measured)

`countdown.sh` now prices combinations: `-m` mailbox→16 B, `-b` 256 B blocks, `-a N` asm text saved,
`-r N` ring shrink, `-s N` C-stack trim.

| combination | countdown | cost in capability |
|---|---|---|
| today | **800 to go** | — |
| `-m` mailbox 216 → 16 B | **600** | none: 4 words are used of 54 |
| `-m -b` + 256 B blocks | **344** | 2× fetches (144 µs each), 256 B per block instead of 512 |
| `-m -b -a 200` + asm dispatcher | **144** | none in words; asm is board-only verifiable |
| `-m -b -a 200 -r 128` + ring shrink | **16** | line buffer 128 → 96, output 128 → 64, command 64 → 32 |
| `-m -b -a 200 -r 128 -s 60` + stack trim | **FITS, 44 B spare** | stack margin 336 → 276 (measured floor 244) |
| `-m -b -a 290 -r 128 -s 60` (asm at its optimistic end) | **FITS, 134 B spare** | same |

**No word is retired in any row.** The whole gap closes on plumbing, block geometry, ring sizes and the stack
margin — with the asm dispatcher contributing 200–290 B of the 800, i.e. it is helpful but not decisive, and the two
cheapest levers (mailbox, block size) already deliver 456 B on their own.

## NTSK 3 -> 2 — measured −152 B (E-075)

`NTSK` is the task-table size: each slot is a 136 B VM snapshot plus `entry`/`state`, permanent `.bss`
whether or not a task is ever spawned. Measured: `.bss` 964 -> 824 (**−140**), `.text` 4 820 -> 4 808
(**−12**), countdown 800 -> 648 B. The `% NTSK` codegen was projected at ~40 B and measured at 12 B.

Then the named failure `ERR_TASKS` cost **+32 B** back (a full table previously printed the *spawned* name as
if it were an unknown word), so the net for the whole change is **120 B**, countdown 680.

**Capability cost:** at most **two concurrent** tasks. A retired task frees its slot, so this bounds
simultaneity, not lifetime spawns. Proven on hardware (`1324`, then `ERR_TASKS 1324`).

## `-msave-restore` — measured −224 B of `.text` (E-076)

Compiler flag only; injected via `EXTRA_CMAKE_ARGS` because the ULP toolchain file has no extension hook, with the
baseline flags **extracted from IDF's file** at configure time so they cannot drift. Verified on hardware
(`FIB 10` → 55). `-fno-builtin` 0 B, `-fno-stack-protector` 0 B, `-flto` pointless (single TU).

## Hash dictionary (P51) — measured −406 B of dictionary, app space +252 B (E-076)

Headers in their own area, 4-byte entries `hash20 | xt11 | imm1`, stride 4, growing down from `HDRTOP` (= `MEMSZ`,
or the block buffer's base). `find()` = one `lw` per header. Dictionary 730 → **324 B**; countdown 456 → **52 B**.
Text cost +160 B. Guards: bake-time collision scan, `image_boot_assert` (`0x51`), `_Static_assert(HDRTOP % 4 == 0)`.

**Capability cost:** no names in the dictionary, so no `WORDS`/`SEE` (we have neither) and no name in a header. Error
messages still print the *typed* token from PAD, so diagnostics are unchanged.


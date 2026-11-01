# 23 — Reclaiming ULP memory (branch `reclaim-app-space`)

## The budget, as measured

| region | bytes | source |
|---|---|---|
| ULP image + `mem[]` pool | **7 845 / 7 856** | `flash_safe.sh` (11 B free) |
| ULP stack region `[0x1EA9, 0x1FF0)` | **327** (painted from 0x1EAC = 324 B) | `riscv32-esp-elf-nm ulp_main.elf`: `junk` 0x1EA8, `__stack_top` 0x1FF0 |
| resident app space | **690 B** (`LATER HERE -`) | device |

## Stack high-water, device

`#k` reports the painted region's deepest touch. Progressively deeper workloads:

| workload | high-water | free |
|---|---|---|
| after boot | **112 B** | 212 B |
| one `2 3 + .` | **240 B** | 84 B |
| one block READ | 240 B | 84 B |
| `LOAD` of a whole phase (7 blocks) | 240 B | 84 B |
| image adopt + `EXECUTE` | 240 B | 84 B |
| **15 phases** (seed, dump, adopt, execute) | **240 B** | 84 B |

Arithmetic already reaches the maximum, and nothing in the paging path goes deeper: the redesigned `LOAD` really did
remove the extra `interpret/vm_enter` frame it was meant to remove. **Slack = 84 B**, but the paths NOT yet exercised are
the error/refusal chains (`msg`, nack decoding, rewind), so no reserve may be reduced until those are measured too.

## A real bug found on the way

`canary_used()` kept the **last** changed index instead of the **lowest**:

    for (i = 0; i < N; i++) if (p[i] != CANARY_VAL) low = i;      /* ends holding the HIGHEST changed byte */

so it reported `324 - 323 = 1 B` for a machine that uses 240. That is the "impossible 1 byte" in docs 15/16 that sent two
earlier attempts hunting for a wrong base — **the base was always right**. Fixed to keep the minimum.

## What each lever is worth, given these numbers

| lever | gain to app space | note |
|---|---|---|
| pool's 11 free bytes | +11 B | free, no risk |
| stack reserve 324 → 280 B (240 measured + 40) | **+44 B** | needs error paths measured first; overflow is SILENT |
| stack reserve 324 → 264 B (+10 %) | +60 B | thinner margin |
| asm dispatcher | **+400…+700 B** | the real prize; multi-session, needs `ds`/`sp`/`rsp` in registers |
| init-only image regions | unknown (100–300?) | needs a map audit and a proof no call site survives |

Reducing the reserve is not a one-line change: the stack region sits between the image and `__stack_top`, so the bytes
only become app space when `MEMSZ` grows to fill them - and `flash_safe.sh` is the budget authority, so a refusal there is
information, not an obstacle.

---

## Rearranging instead of rewriting: the task machinery is the 400 B

The interpreter rewrite was mispriced (the dispatcher is already threaded: `jr` through a u16 table, ~70 B of decode
prologue + 144 B table). The blocks that are actually *there* are the task machinery, which the source itself says must
stay off ("With P43_TASKS ... the console replays stale command bytes and the REPL is lost - root cause not found; do not
re-enable") while the shipping build had it **on**.

| build | .text | .data | .bss | pool |
|---|---|---|---|---|
| `P43_TASKS` defined (as shipped until now) | 5 108 | 1 952 | 785 | **7 845** |
| `P43_TASKS` **undefined** | 4 844 (**−264**) | 1 952 | 785 | **7 581** (275 free) |

`#define P43_TASKS 0` changed nothing: every guard is `#if defined(...)` — measured, byte-identical image.

### Still inside after the removal (measured symbols)

| symbol | bytes | note |
|---|---|---|
| `tskvm` (.bss) | **272** | 2 × 136 B VM records, now unreferenced but still emitted |
| `vm_switch` | 62 | scheduler |
| `vm_task_leave` | 50 | called from `vm_enter`'s EXIT path |
| `vm_next_ready` | 44 | scheduler |
| `vm_copy` | 38 | 136 B struct copy |
| **total** | **466 B** | guarded removal ⇒ pool ≈ **7 115**, ~740 B free |

So the rearrangement is worth **~730 B in total** (264 already banked by the define, 466 still to guard) without touching
`vm_enter`. `vm_live` (136 B) must stay: with `cur == -1` meaning "outer interpreter", it is a third machine, not a
duplicate — my earlier "+136 B free" was wrong.

The EXIT path needs an `#else`: `if (!ip) { if (!vm_task_leave()) { ... return; } }` becomes the plain return when tasks
are off. That is the only call site outside the scheduler.

---

## DONE: app space 690 → 1 453 B (+763 B, 2.1×) by rearrangement only

No interpreter change. The task machinery was removed (it is documented as broken in `src/ulp_repl.c`: "the console
replays stale command bytes and the REPL is lost — root cause not found; do not re-enable"), and the freed pool was
converted into dictionary space.

| step | pool | app space |
|---|---|---|
| shipped: `#define P43_TASKS 1` | 7 845 | 690 B |
| `P43_TASKS` undefined (`0` does nothing: guards are `defined()`) | 7 581 | 690 B |
| + scheduler/records guarded (`.text` −526, `.bss` −276, `.data` −4) | **7 039** | 690 B |
| + `MEMSZ` 1 936 → 2 700 and a re-bake of `src/image.h` | 7 839 | **1 453 B** |

### What had to change, and why each one

1. **Declarations, not just functions.** Guarding the functions alone saved 264 B of `.text` and left the 272 B
   `tskvm` array allocated — the linker kept it with every reference dead.
2. **`vm_enter`'s EXIT path and `L_P_EXIT`/`L_P_PAUSE`** were the only live references; each needed an `#else`
   (`ip == 0` ⇒ return to C; PAUSE ⇒ no-op resume). `p31_cases.inc` counts: those two bodies are inside the switch.
3. **`VMDBG` disappeared** with the guarded block and the build failed with "implicit declaration of VMDBG" — a macro
   that vanishes is a compile error, not a silent default, so an explicit no-op was added for the no-task build.
4. **The host driver** also stepped tasks (`vm_next_ready`/`vm_run_tasks`), so the bake failed to link until that call
   was guarded. The bake and the ULP build now share one capability set.
5. **`tools/bake.sh`** required the same two changes: no `-DP43_TASKS`, and **MEMSZ is now a required argument** — a
   default is how the shipping image was once baked at one size while the ULP built at another (E-079).
6. **`MEMSZ` 2 700 with 17 B of pool left free.** Banking every byte would leave no slack, and a pool that overflows is a
   link failure that looks like a code bug. `MEMSZ` and `image.h` are one decision: re-bake after any change, or the ULP
   runs a dictionary built for a different memory size (measured: `LATEST HERE - .` answered nothing at all).

### Gates, all device

| gate | result |
|---|---|
| `tests/golden_battery.py check` | **17/17 identical** |
| `tests/capabilities.py` | **11/11** (incl. net-stack-change 0) |
| 15 phases from images | **15/15** |
| host suite | **24 PASS / 0 FAIL** |
| `#k` stack high-water | **240 B of 324** — unchanged by the relayout |

Cost, stated plainly: `SPAWN`/tasks are gone from the shipped engine. It was already unusable per the source's own note,
and the golden battery plus 11 capabilities cannot detect the loss of a capability that never worked.

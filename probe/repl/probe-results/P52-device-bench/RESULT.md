# P52 — the device benchmark, and the two workloads it could not measure

**Result: two of four workloads measured on the chip, with host cross-validation. Two did not run, for a
named reason that is itself the most important finding in this probe.**

## What was built

`P52_LINECYC` (ULP, bench build only): `rdcycle` is read at the **line boundary** in `drain_cmd()`, and the
delta plus the engine's own dispatch counter are printed as a marker on their own line:

```
C <cycles> D <dispatches>
```

The instrument is outside the path it measures — the GUARDRAIL that P42 learned by putting a counter inside
the dispatch loop and invalidating every number it produced.

Bench build flags (all measured, all off in shipping):

| flag | shipping | bench | cost |
| --- | --- | --- | --- |
| `P52_LINECYC` | off | **on** | `.text` +~120 B, +1 number-printer |
| `P42_COUNT` | off | **on** | +12 B `.bss`, ~3 instructions per dispatch |
| `P43_TASKS` | on | **off** | frees ~200 B text (the scheduler is not in the interpreter's path) |

Sections: `.text` 5 186 · `.rodata` 304 · `.data` 1 216 · `.bss` 1 085 = **7 791 / 7 856** (65 B free).
Image `P52-bench-ulp_main.bin` (6 708 B) and `P52-bench-flash_args` kept here.

Driver: `probe/repl/tools/device_bench.py` — lockstep, one line in flight, sends a line and waits for **that
line's** marker, so no count can be attributed to the wrong line.

## Measured on the chip

| workload | line | cycles | dispatches | cycles/dispatch |
| --- | --- | --- | --- | --- |
| `arith` | `ARITH` | **6 059 696** | **15 145** | **400.1** |
| `recursion` | `12 FIB .` | **2 125 198** | **5 188** | **409.6** |
| `arith` | `: ARITH …` (compile) | 330 982 | 13 | — |
| `recursion` | `: FIB …` (compile) | 216 983 | 40 | — |

Cross-validation against the host bench, which counts the same dispatches without timing them:

| workload | host (net of prelude) | device | delta |
| --- | --- | --- | --- |
| `arith` | 15 163 | 15 145 + 13 = **15 158** | **5 dispatches (0.03 %)** |
| `recursion` | 5 230 | 5 188 + 40 = **5 228** | **2 dispatches (0.04 %)** |

The remaining few are the driver line vs the host's `grep`-summed file, which differ by one line ending. The
agreement is good enough to say the two measurement paths agree.

### Wall-clock, from `rdcycle`

19.0 MHz ⇒ arith **319 ms**, recursion **112 ms**. These replace the previously *estimated* "≈909 ms /
≈314 ms" in `CONSTRAINTS.md`, which were dispatch-count × 1 139 cycles and were wrong by ~3×.

### The 1 139-cycle dispatch figure was a workload, not a constant

Measured here: **400 cycles per dispatch** on arithmetic primitives (two independent workloads agree within
2.4 %). The earlier 1 139 cycles came from a literal-heavy line. So dispatch cost is not one number:

| token kind | cycles | |
| --- | --- | --- |
| primitive dispatch in a tight loop | **~400** | measured, two workloads |
| typed literal (number parse + `find`) | 1 623 | measured (P46) |
| a source line's compile overhead | ~17 000–25 000 per definition | measured here |

## What could not be measured, and why

`memory.fs` and `matrix.fs` **failed on the device**, and the failure is a defect, not a budget:

```
memory.fs  1  : RES 16 0 BEGIN DUP , 1+ DUP 16 < 0= UNTIL  -> 185 684 cyc, 13 dsp   ok
memory.fs  2  CREATE BUF                                   ->  18 350 cyc,  1 dsp   ok
memory.fs  3  RES                                          -> 102 522 cyc, 181 dsp  ok
...
            then:  "." is no longer a word   — the marker printed "C .? D .?"
```

`RES` runs 16 `,` writes = **64 B**. The image has **154 B** of application space. `,` does **not** check the
dictionary bound, so the writes ran into the header area and erased headers; the first symptom is that `.`
becomes unknown, i.e. the machine loses the ability to report anything. A later `CREATE`/`BUF` pair then read
as `0 dispatches`, and `MFILL`/`MAT` completed in ~28 700 cycles — one loop iteration instead of 500, because
the definitions had been eaten.

**This is the finding of P52:** the header path is bounds-checked (`ERR_DICT`) but `,` is not, so
"append 64 B" is a silent dictionary overwrite whose symptom is *every word becoming unknown*. It is the same
class as the historical silent pool overflow: the link/image is fine, the damage looks like a wrong-word bug.

Consequence for measurement: these two workloads need **app space**, not cycles. Measuring them requires
either a bigger `MEMSZ` in a bench image (which means re-baking `image.h` — E-079 says a stale bake points
outside `mem[]`), or running each workload in a **fresh boot** so it gets the whole 154 B. The second was
tried and still failed for `memory.fs`: `RES`'s 64 B plus definitions exceed 154 B even alone.

## Bugs found in this probe

1. **`,` has no dictionary bound** (above) — silent header erasure. Not yet filed with a test; needs
   `if (V_HERE + 4 > V_LATEST) err(ERR_DICT)` in the comma path, the same guard the header path already has.
2. **`#define X 0` does not disable `#if defined(X)`.** Turning blocks and tasks "off" by setting them to 0
   changed the section sizes by exactly **0 B** and cost two build cycles. The defines must be commented out.
   (This is why `P43_TASKS` is now commented, not zeroed.)
3. **A line that executes `EXIT` at interpret time wedges the machine.** Preloading the prelude by typing it
   sent `DUP 0= IF 48 EMIT DROP EXIT THEN` — half a definition, intended for compile state — and afterwards
   there was no marker at all until a hard reset. On the device the prelude should **not** be typed: the
   `IMAGE` build already has all 85 words baked.
4. **The driver must not send a markless line as if it were a measurement.** A marker with empty numbers
   (`C .? D .?`) is not a zero; it is excluded from every sum and printed as `?`.

## Probe discipline

**This probe overran the 15-minute budget** — the build/flash/instrument loop took four iterations because
of bugs 2 and 3. Recorded here rather than in the journal's happy voice: the overrun was caused by not
checking `#if defined` before trusting a `#define … 0`, which is a five-second grep.

## Artifacts

- `P52-bench-ulp_main.bin` (6 708 B), `P52-bench-flash_args`, `P52-bench-ulp_main.elf`
- `run.log` — full per-line transcript for arith, recursion, memory (partial), matrix (partial)
- `arith.log` — an earlier attempt, kept because it shows the `EXIT` wedge
- driver: `probe/repl/tools/device_bench.py`

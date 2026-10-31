# P39 — First execution of our engine on the ULP

| | |
| --- | --- |
| Runs on | **board (exclusive)** — flashes; use `/dev/ttyACM1` |
| Time box | **15 min**, one run, hard cap |
| Depends on | P38 (engine + fixed prelude), P22 (build recipe) |
| Blocks | G2 and everything after it |
| Serves | R1 |

## Question

**Has any of this ever run?** No. Every number in this project comes from a host build, static accounting, or an
isolated probe image. This probe answers one thing: **does our interpreter boot on the ULP, compile its prelude,
evaluate an expression, and hand back a correct answer?**

The pass criterion is a **specific value printed on a terminal**, not "it seems to work".

## Why it matters

If the interpreter cannot run on the coprocessor, everything downstream — blocks, tasks, the console — is a design
document. This is the last experiment that can invalidate the whole approach.

## Given — do not re-derive

* P38: engine with 16-bit tokens, fixed `IF`/`ELSE` (2-byte operands), working block words; block layer **456 B**;
  the prelude compiles and its conditionals are verified 17/17.
* P22/P35: the working build recipe (`ulp_embed_binary`, linker script, `nm -S` allocation check), `MEMSZ` that
  links, stub-subtraction for engine size.
* P05: **19 MHz**, RTC tick **122.6 cycles / 6.46 µs**, wake entry **81 cycles**; `rdcycle` resets each wake.
* P06: the timer counts *sleep*; period floor **22 ticks**; wake cause unreadable.
* P16/P23: a 512 B fetch is **144 µs** polling, **176 µs** through the doorbell with the HP blocked.
* Board rules: flash over `/dev/ttyACM1`; **never** GPIO19/20; watchdog first; stage behind a console key; never
  write `COCPU_*` while the ULP may be mid-wake.

## Scope — deliberately minimal

Do **not** bring up blocks, tasks, paging or the REPL. The first run of an interpreter on a new machine should have
the fewest moving parts that still proves it runs:

```
ULP:  start → interpret one line from a constant string → write the result and a wake counter to shared vars → retire
HP:   load_binary → run with a period → print the result and the counter over UART0
```

The line to interpret: **`2 3 + 4 * .`** — expected **20**. Chosen because it exercises literals, two primitives,
and a printing word, and a wrong answer cannot be mistaken for a plausible one.

## Method

1. Board lock; watchdog first; banner; wait for `g` on the console before arming the ULP.
2. Build the ULP image from P38's engine with: 16-bit tokens, no frames (paging removed), no segments, no block
   transfer yet, `pl_emit` writing into a shared out-buffer, and `main` interpreting the constant line once.
3. Confirm allocation with `nm -S` (**frames/segments absent by design; `mem`, `vm_live`, `tsk` present**).
   Report the engine's `.bin` size, and the size **minus** the control stub.
4. HP side: `ulp_riscv_load_binary`, `ulp_riscv_run` with period 1 000 ticks, then print:
   the interpreted output bytes, the value of `wake_count`, and `rdcycle` at wake start.
5. **Run it.** Report exactly what arrives on the serial port.
6. If it does not work, distinguish the three failure modes rather than reporting "nothing":
   - **ULP traps** → the main CPU wake cause will be `ESP_SLEEP_WAKEUP_COCPU_TRAP_TRIG`; say so and which
     `ip`/`status` was published.
   - **ULP never runs** → `wake_count` stays 0; check the timer bit and the loaded image size.
   - **ULP runs but the answer is wrong** → print the raw bytes and the final `sp`/`dsp` so the failure is
     diagnosable.

## Record

| Item | Value |
| --- | --- |
| engine `.bin` (and minus stub) | bytes |
| `nm -S` allocation check | frames/segments absent, `mem`/`vm_live`/`tsk` present |
| output bytes on the wire | |
| interpreted result | **20 expected** |
| `wake_count` | |
| `rdcycle` at wake start | |
| failure mode, if any | trap / never-ran / wrong-answer, with the evidence |

## Pass criteria

* the image loads and runs, `wake_count` advances, and the printed result is **`20`**;
* allocation confirmed by symbol;
* the engine size at 16-bit-without-paging is recorded, because it becomes the new baseline.

## Failure criteria — and what each changes

* **Trap** ⇒ publish the trap evidence and stop; do not "fix" it blind. The next probe gets the trap location.
* **Never runs** ⇒ the loader/timer path is wrong, not the interpreter; report the register writes used.
* **Runs, wrong answer** ⇒ the host/probe divergence is the finding; print the raw token stream bytes and the
  final stack so the difference is visible.
* **Does not fit** ⇒ report the overrun; the engine's 16-bit no-paging size becomes the number everything else is
  measured against.

## Doc deltas to hand back

* `docs/01-proposal.md` — G2 status; and if it runs, the first measured on-chip figure replaces a host figure.
* `docs/JOURNAL.md` — the first on-chip execution, with the exact bytes.
* `probe/EVIDENCE.md` — the engine's real `.bin` size on the chip build.

## Do not

* Do not add features in this probe. One line of Forth, one answer, one counter.
* Do not leave the ULP armed or the timer running; restore a known state and say what is flashed.

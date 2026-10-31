# P09 — Trap postmortem, runtime image swap, RTC-RAM contention

| | |
| --- | --- |
| Runs on | **board (exclusive)** — overwrites the firmware. Get approval first. |
| Time box | **15 min**, one run, hard cap |
| Depends on | P06 (retire semantics) |
| Blocks | R3's overrun evidence, R1's cold-boot item, the "no JTAG" debugging story |
| Serves | R3, R1, `02-harness.md` §5 |

## Timebox — 15 minutes, one run, no slices

* **Hard cap: 15 minutes total**, from the first command to the written `RESULT.md`.
* **At T−2 minutes stop starting new work.** Wrap up, write `RESULT.md`, kill processes, kill the tmux
  session.
* **It all has to fit.** A cold ESP-IDF build is 2–3 minutes and a flash ~20 s, so if the probe needs
  a build, start it in the first five minutes — not at minute ten.
* **Every command carries `timeout`**: builds `timeout 300`, device ops `timeout 30`, host test runs
  `timeout 20`. No bare long-running command, no `&`, no `nohup`, no `/tmp`.
* **Every loop is bounded twice**: by iteration count *and* a wall-clock check inside the loop.
* **A hang is a `FAIL`**, with the exact command and the last output recorded.
* **If the question does not fit in 15 minutes, the question is too big.** Report what was measured;
  the orchestrator will cut a narrower question. Running the same probe again is not the answer, and
  splitting a probe into slices is not the answer either.

## Question

1. When the ULP traps (illegal instruction, unaligned access), what can still be learned — does the
   main CPU wake with a usable cause, and what state survives the trap?
2. Can `ulp_riscv_load_binary()` be called at runtime to replace the running image **without a
   reflash**, so a new engine build can be tested in seconds?
3. Does the ULP reservation collide with the main app's `RTC_DATA_ATTR` variables at 8176 B?

## Why it matters

There is no JTAG on the ULP, so the postmortem path *is* the debugger. `02-harness.md` §5 promises
`ip_shadow` and a sticky status; if a trap wipes them, that promise is false and the harness needs a
different mechanism (for example a shadow PC ring written every N tokens).

Question 2 decides the iteration loop: 90 s per engine change (reflash) vs ~2 s (load over the wire).

Question 3 protects against a silent overlap that would corrupt either the Forth or the main app's
sleep state.

## Method

1. Project under `probe/results/P09-trap-swap/`.
2. **Trap postmortem.** Build an image that writes a known pattern into shared variables (`wake_count`,
   `ip_shadow`, a marker), then executes an illegal instruction (a `.word` that decodes to a reserved
   opcode — verify with the disassembler that it is genuinely illegal, not merely unsupported). Record:
   - the main CPU's wake cause (`esp_sleep_get_wakeup_cause()`) with the ULP armed as a wake source;
   - which shared variables survived the trap;
   - whether the ULP timer keeps running afterwards (does `wake_count` advance again?)
   - whether `ulp_riscv_run()` can restart it without a `load_binary`.
   Repeat for an unaligned 32-bit access (`lw` with a `+1` address) and for an `ecall`.
3. **Runtime image swap.** Two distinct ULP images (A writes `0xA5A5`, B writes `0x5A5A` into the same
   variable). From the main app: load A, run, read; then `ulp_riscv_load_binary(B)` + `ulp_riscv_run()`
   and read again. Confirm the variable flips, the timer still fires, and measure the time for
   load+run. Then verify the documented trap: `load_binary` zero-fills the whole reservation — write a
   sentinel into RTC memory, load an image, and check the sentinel is gone (this is a *documented*
   behaviour to confirm, not a bug).
4. **RTC RAM contention.** In the main app declare `RTC_DATA_ATTR uint32_t sentinel[64]` with a known
   pattern, set `CONFIG_ULP_COPROC_RESERVE_MEM=8176`, load and run the ULP image, check the sentinel.
   Then do the same with the ULP program writing across its whole reservation. Report whether they
   overlap, and what the linker/IDF does about it (error, warning, or silent override).

## Record

| Item | Value |
| --- | --- |
| trap wake cause | string |
| variables surviving trap | list |
| does the timer keep firing after trap | yes/no |
| restart without `load_binary` | yes/no |
| load+run time for a second image | ms |
| `load_binary` zero-fills the reservation | confirmed yes/no |
| `RTC_DATA_ATTR` sentinel survived at 8176 | yes/no, and any warning emitted |

## Pass criteria

* the trap is detected by the main CPU with a distinguishable cause;
* at least `wake_count` and the marker survive, and the report says exactly which variables survive;
* runtime image swap demonstrably works (variable flips, timer keeps running) — or fails loudly;
* the `RTC_DATA_ATTR` question is answered with a yes/no plus the IDF output that says why.

## Failure criteria — and what each changes

* **Nothing survives the trap** ⇒ `02-harness.md` §5's postmortem channel is invalid; replace with a
  shadow-PC ring written every N tokens, and add "trap loses state" to `00-background.md` §2.7.
* **`load_binary` cannot be used at runtime while the timer runs** ⇒ iteration loop L2 in
  `02-harness.md` §6 is dead; delete it rather than leaving a documented-but-impossible workflow.
* **`RTC_DATA_ATTR` overlaps the ULP reservation** ⇒ the 8176 figure is optimistic for real projects;
  `01-proposal.md` §4.3 must reserve a margin and say why.

## Doc deltas to hand back

* `docs/00-background.md` §2.7 — what is actually recoverable after a trap.
* `docs/02-harness.md` §5 — the postmortem table, corrected; §6 — iteration loop L2 confirmed or
  removed.
* `docs/01-proposal.md` §4.3 — the reservation margin if contention is real.
* `docs/01-proposal.md` §10 — R1's cold-boot item and R3's overrun evidence, if this probe supplies it.

## Do not

* Do not use a trap that is actually a legal instruction; disassemble it and paste the encoding.
* Do not claim recovery from a hang; distinguish "hung" from "trapped" by the wake cause and the
  counter.
* Do not leave a trapped or spinning ULP armed on the board; restore, reflash a known image, say what.

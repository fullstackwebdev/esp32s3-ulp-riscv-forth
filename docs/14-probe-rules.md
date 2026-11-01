# 14 — Probe rules

How to run a probe in this project. Every rule below was paid for with a specific failure: a lost board session, a
wrong number believed for weeks, or a rewrite started on a premise that measurement later inverted. The cost is quoted
so the rule reads as experience rather than etiquette.

If a rule here conflicts with convenience, the rule wins. If a rule is wrong, change it here *and* say what it cost.

---

## R1 — Build the decisive artifact before the projection

**Lesson:** a projection assembled from component estimates is a hypothesis. Measurement of the whole can invert it.
**Cost:** twice. `rd32` as a single `lw` was projected as "the same 35 % as `rd16`" and turned out to be **+24 B and a
trap** (E-057); the asm dispatch core was projected at **719 B** and measured at **95–290 B**, then at a **loss** for
partial ports (E-068, E-070).
**Do instead:** spend ≤15 minutes on the cheapest artifact that can *falsify* the idea — a 6-primitive `.S` file, a
per-token prototype, a one-source measurement script — and let it answer first.

## R2 — Never type a test line you have not written down and checked

**Lesson:** half of "the machine is broken" is the operator holding Forth's stack order backwards.
**Cost:** several board round-trips on `BLOCK 0`, where the word is `( n -- addr )`. The resulting empty-name `?` was
chased as a dispatcher bug.
**Do instead:** write the lines into a file, check each word's stack effect against the source, *then* send. Keep the
ordered sequence in `RESULT.md` so it can be replayed.

## R3 — Check the platform's units and constants before using them

**Lesson:** a library that rounds to zero is a hang, not a delay.
**Cost:** `pdMS_TO_TICKS(2)` is **0** at the default 100 Hz tick. `console_task` spun without yielding, `app_main` was
starved, the block server was never created, and the only symptom was a timeout on the *other* core (E-073).
**Do instead:** before using a timing/conversion macro, print or grep its inputs (`CONFIG_FREERTOS_HZ`, tick period,
clock source). One line prevents an hour.

## R4 — When two consumers share memory, publish addresses *and* their address space

**Lesson:** an offset looks exactly like a pointer until you dereference it.
**Cost:** the ULP links at 0, so `&mem` and `&mailbox` are offsets into RTC slow memory. Dereferencing panicked:
`LoadProhibited … EXCVADDR 0x00001e68` — the mailbox offset itself (E-073).
**Do instead:** publish `base + offset` or publish the base alongside, document it in the header comment, and assert
the window size with a `_Static_assert`.

## R5 — Kill silent failures at every creation point

**Lesson:** a thing that fails to be created produces a *symptom elsewhere*, never an error where it happened.
**Cost:** an ignored `xTaskCreate` return ("the server is broken"); symbols deleted by `--gc-sections` and then
missing from the generated header (`'ulp_repl_cmd_bytes' undeclared`); a static initialiser that is constant for one
build and not the other.
**Do instead:** check and print the result of every create/alloc/export; keep one real reference to symbols that must
survive; treat a build error naming a missing symbol as "the linker deleted something", not as a missing include.

## R6 — Never derive an ordering a second time

**Lesson:** any second copy of an ordering will eventually disagree with the first, and the failure appears far from
the copy.
**Cost:** three separate bugs. Ring sizes in two files (host wrote past `repl_cmd[]` into `repl_out[]`, F-74); a
coverage report that named `DUP` as dead because a parsed name list disagreed with the enum by two entries (F-98); and
`P_HAVE_DOCOL` missing because `DOCOL` is declared outside the X-macro list, which gated `case P_DOCOL:` out of the
switch and made every colon word fall to `default: err()` (E-072).
**Do instead:** generate the copy from the single source and assert agreement at compile time
(`_Static_assert(P_DUP == ID_DUP, …)`), or read the value from the artifact itself (names out of the header, not out
of a parsed list).

## R7 — Put the metric in place before the work

**Lesson:** without a standing number, effort drifts to whatever is measurable rather than what matters.
**Cost:** weeks of "620 B of app space" that was never achievable (needs an 8 180 B pool), and a block cost quoting
968 B when the plumbing alone was another ~500 B (F-06, E-059).
**Do instead:** define the metric, write the script that prints it, and print it after *every* change — and
give the metric **one owner**. The current pair: `probe/repl/flash_safe.sh` owns the pool (it *refuses* to
flash when over) and `probe/repl/tools/bake.sh` owns application space (it prints code/headers/free from the
image it just baked).

**And retire the reporter when the metric moves.** `countdown.sh` was that script for P47–P52 and was deleted
in P53: once application space moved into `image.h`, its lever model (`-r`, `-s`, `-a`) still reduced *pool*
while it printed the *baked* app space beside it — one line claiming both `app space 354 B` and `131 B free`.
A metric that is computed twice will eventually disagree with itself, and the version people read will be the
wrong one.

## R8 — Know what the host cannot answer, and say so up front

**Lesson:** the host validates logic and masks hardware; the board validates hardware and hides logic.
**Cost:** RISC-V assembly cannot run on the host at all, so every asm change is a board-only experiment; and the host's
*fake* block server hid the RTC-offset bug for two runs.
**Do instead:** before starting, list the questions that only the board can settle, and design the board run to answer
them in one session.

## R9 — Verify the harness before trusting any number

**Lesson:** a benchmark can measure the wrong program, or the same program twice.
**Cost:** feature-on-coverage. A sweep whose `sed` never matched printed six identical rows; a bench inside the input
path reported `min=567` and left the machine echoing without answering; a two-point model returned a **negative** cost
per dispatch.
**Do instead:** one validation pass *before* timing, echo the effective input back (`MEMSZ=1400 (effective 1400)`),
assert the counters are non-zero and stable, and treat a physically impossible number (negative time, 6 cycles per
token, identical rows) as a harness defect until proven otherwise.

## R10 — Never place the instrumentation or the feature inside the path it depends on

**Lesson:** re-entrancy is the most expensive class of bug here, because the symptom is corruption, not an error.
**Cost:** three times. P42's bench inside `drain_cmd` (broke the console); P43's task step inside `drain_cmd`
(replayed command bytes); P50's dispatcher *called from* the loop (`-188 B`, the wrong shape entirely).
**Do instead:** put it at the same level as the thing it replaces, or one level out — before the drain, after the
drain, in `main`.

## R11 — Boot asserts earn their keep; write them before you need them

**Lesson:** a check that refuses to run converts a silent corruption into a named failure at the only moment the cause
is still visible.
**Cost avoided:** the ring-size boot assert fired on real hardware —
`FATAL: ring size mismatch — ULP cmd=32 out=64, host cmd=64 out=128` — having cost 20 lines when written, and
prevented exactly the class of bug that had cost an hour earlier.
**Do instead:** assert cross-core constants at boot, assert dictionary/pool placement before use, and make each assert
print both values and refuse to continue.

---

## Pre-flight checklist

Before the probe:
1. **Question** — one sentence, falsifiable. If it cannot fail, it is not a probe.
2. **Metric** — what number moves, and by how much would it matter.
3. **Falsifier** — the cheapest artifact that can kill the idea. Build that first.
4. **Platform limits** — what the host cannot answer; what only the board can.
5. **Board lock** — `exec 9>probe/results/.board.lock; flock -n 9 || exit 3`.
6. **Time box** — normally 15 minutes, one run. At T−2 min stop starting work.

During:
7. Validate the harness on one iteration before timing anything.
8. Echo the effective input back; identical rows mean the edit did not apply.
9. Treat impossible numbers as harness defects.
10. If the board is left in an unknown state, restore a known-good image **before** investigating.

After:
11. `RESULT.md` with: the exact commands, the raw numbers, what was proven, what was *not*, and the next question.
12. Record the result in `probe/EVIDENCE.md` and, if it changed a decision, in `docs/JOURNAL.md`.
13. Update the register (`docs/11-findings.md`) if a fact changed, and the countdown if a budget moved.

## R12 — A green suite certifies only what it exercises

**Lesson:** the tests were green for months while `SD 16` corrupted the stack, because the suite's deepest
expression used **6 of 16 cells**. The bug was found by an agent, not by the suite.
**Cost:** a silent wrong answer (`15 FIB .` → 377 instead of 610) and a hard hang, shipped and untested.
**Do instead:** after every bug, add a test that **fails without the fix**, and drive it through the same path
production uses — the message-code tests are piped through the real `msg_expand.h`, and error tests carry an
explicit **abort sentinel** (`888 .`) so "the load stopped" is observable in the diff. One test per hole, and
the hole is named in the test's own header comment.

**Fail loud:** an invalid probe is written down as INVALID with its defects listed (see E-060, E-069, E-070). A
negative result that is recorded is worth more than a positive one that is guessed — twice in this project the
recorded negative stopped a week of work.

## R13 — If the consumer can miss two changes, sample a level, not an edge

**Lesson:** the block server looked for a rising edge of the ULP's request flag while polling once per FreeRTOS tick.
An ULP that cleared and re-raised the flag between two polls was never serviced — 845 ms of `BLKWAIT`, `BK_NOSERVER`,
and a flag left set so that everything afterwards answered `BK_BUSY`. Chased as "the fourth hop" and "the phase body
re-enters at 41 Hz" for hours, and a 20 ms gap in the launcher hid it instead of explaining it. `F-132`.
**Do instead:** publish a **level** that means "nobody has answered this yet" (`flag == 1 && answer_word == 0`), and
publish the data *before* the flag. Then a poll that is arbitrarily late still sees the request. Reset the
age/staleness timer with the answer, not with the sample.

**Corollary — check the domain of a cross-core boolean.** `0xA5A5A5A5` is a perfectly good `if`. The paint canary
had drifted on top of `blk_out`, the flag read `0xA5A5A5A5`, and a *level* test then invented 5 600 requests per second
(`F-131`). Test `== 1`, and print the value by name when it is neither 0 nor 1.

## R14 — A measuring instrument that writes must derive its base from an enforced budget

**Lesson:** `canary_paint()` wrote 0xA5 from the constant `0x1EAC` "taken from nm". The image grows toward it, and two
bytes of code put two live `.bss` words inside the paint. They were the only words there that are zeroed at boot and
never rewritten, so they stayed `0xA5A5A5A5` and every block read after that was corrupted (`F-131`). The two failures
that followed — `ERR_CRC` on the first block op, then a `NAME?` cascade — pointed at the loader, the splitter and the
UART before they pointed at a diagnostic.
**Do instead:** derive the base from the same number the build already enforces (`ULP_POOL_BUDGET == flash_safe.sh
POOL`), so the instrument cannot overlap its subject unless the gate is bypassed. And assert the consequence at boot
(`blk_out > 1` → FATAL by name) so the next occurrence takes one second, not two hours.

**Corollary — off-by-one address arithmetic hides in "obvious" constants.** The first fix computed the base from
`STACK_TOP 0x1FF0` and was 16 B low, because the top is not 0x2000. Write `base == budget` instead of
`base == top - (total - budget)`.

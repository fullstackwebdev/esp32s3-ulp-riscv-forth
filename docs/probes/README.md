# Probe proposals

One file per unknown. Each is self-contained: a subagent with no prior context can take a single
file, run it, and hand back numbers plus exact doc edits. They exist so the unknowns in
[`../01-proposal.md`](../01-proposal.md) become measured limits instead of assumptions.

## The two hard scheduling rules

**1. The board is exclusive.** There is exactly one ESP32-S3. Two agents flashing
`/dev/ttyACM0` at the same time produce garbage and a corrupted board. So:

- **host-only probes** (`P01`–`P04`) may run **in parallel, now**, with no board attached;
- **board probes** (`P05`–`P09`) run **one at a time**, owned by a single agent for the whole
  session; every other agent must be host-only while that session is live.

**1b. Every board probe must be recoverable from, and must say how.**
The P06 run flashed cleanly and then wedged the board: `/dev/ttyACM0` still enumerated but writes timed
out, and no software reset path (esptool stub, `--before usb-reset`, DTR/RTS) recovered it. A human had
to press EN or replug. So, before flashing anything:

* save the exact image you are about to write and the `flash_args` that wrote it, inside your result
  directory, so the previous known-good image can be restored by whoever is holding the board;
* do not rely on `read-flash` of a 32 MB chip as your backup;
* **flash over `/dev/ttyACM1` (UART0), never over the native USB.** The CH343's DTR/RTS drive EN/IO0,
  so UART0 can always force download mode; the native USB wedges when the app crashes (E-017).
* if the board goes silent, recover with `esptool -p /dev/ttyACM1 chip-id` (that resets it via RTS),
  then report. If that fails, ask the operator to press EN, then BOOT+EN, then to unplug for 5 s. Never
  claim a result you did not get.

**2. Board probes overwrite the firmware.** The devkit currently holds the user's own image.
`idf.py flash` destroys it. Do not start a board probe without explicit approval for that specific
probe.

## Rules every probe obeys

* **Never edit `docs/`.** A probe writes only under `probe/results/P<NN>-<slug>/`. The orchestrator
  (the main agent) merges results into the documents. Parallel agents editing the same `.md` file is
  how you lose work.
* **Never edit the baseline** `probe/uforth/uforth.c`. Work on a copy inside your result directory.
* **No `/tmp`.** Everything under the repo root.
* **Long work in `tmux` with `nice`**, never `&`, never a foreground `idf.py build` you then abandon.
  Confirm the session is alive and making progress; clean it up when done.
* **No mocks of the thing under test.** A simulated byte server (`P03`) is the system under
  construction, not a mock of the board; board probes must not simulate hardware at all.
* **Fail loud.** If a prerequisite is missing, print `BLOCKED: <reason>` and stop. Do not invent a
  fallback, do not skip a case, do not narrow the question.
* **Never search outside the repo.** A probe ran `find /` and burned four minutes of its box; the
  project rules forbid it. Paths you need are in `export.sh`, `docs/`, or already on disk.
* **Derive facts from compiler artifacts, not by parsing source.** `nm`, `.su`, `.map` and the linked ELF are
  ground truth; a regex over a C macro with line continuations and nested parentheses is not. P31 lost 30
  turns to exactly that, when diffing two `nm` outputs would have answered the question in two commands.
* **A page or fault claim must come from an access tracer, not from where code sits.** P24 and P26 both
  reported "pages touched" by counting the distinct pages the named definitions *occupy*, then applying a
  thrash rule by hand — no tracer at all. P25 rebuilt one through `resolve()`, and the true figures were
  different (P24: 7 pages / 13 faults per pass, not 6 / 6). Any probe that talks about paging must count
  *accesses*, and should size its own measurement error by also building the naive version.
* **Every result is reproducible**: the result file records the exact commands, the full output, and
  the commit/state of the tree. No `tail`-ed output.

## Deliverable format (all probes)

`probe/results/P<NN>-<slug>/RESULT.md`, containing, in this order:

1. **Answers** — the measured numbers, each with units, in a table.
2. **Evidence** — commands run and their complete output (log files in the same directory).
3. **Verdict** — `PASS` / `FAIL` / `BLOCKED`, against the pass/failure criteria in the brief.
4. **Doc deltas** — literal replacement text for the affected lines of `docs/*.md`, written as
   `file: section → old sentence → new sentence`. The orchestrator applies these verbatim.
5. **Follow-ups** — new unknowns discovered, phrased as a question (they become new probes).

The orchestrator then copies the essential numbers into `probe/EVIDENCE.md` with an ID, and ticks the
relevant boxes in `docs/01-proposal.md` §10.

## Register

| Probe | Area | Runs on | Time box | Depends on | Ticks these acceptance items |
| --- | --- | --- | --- | --- | --- |
| [P01](P01-engine-size.md) | Engine size, resident budget closure | host | 15 min | — | R1 (engine contains no user words), Q3 |
| [P02](P02-token-width.md) | 16-bit vs 32-bit xt: density, page fit | host | 15 min | — | R1, R5 (definition/page rule) |
| [P03](P03-paging-sim.md) | Paging/retry model, thrash detection | host | 15 min | P02 | R5 (all items) |
| [P04](P04-console-and-slicing.md) | Rings, char rate, sliced interpreter | host | 15 min | — | R2, R3 (no blocking) |
| [P05](P05-clock-calibration.md) | Cycles per RTC tick, per instruction | **board** | 15 min | — | Q1 budget constants |
| [P06](P06-wake-semantics.md) | Period overrun, timer+GPIO coexistence | **board** | 15 min | P05 | R3 (retire, one event per edge) — **PASS/PARTIAL/FAIL on the second run (E-019); board recovered** |
| [P07](P07-byte-server.md) | Fault cost: awake vs asleep, throughput | **board** | 15 min | P05 | R6 (all items), R5 (fault cost) |
| [P08](P08-flash-and-retention.md) | Erase/write timings, snapshot, PSRAM loss | **board** | 15 min | P07 | R7 (all items) |
| [P09](P09-trap-and-swap.md) | Trap postmortem, runtime image swap | **board** | 15 min | P06 | R3 (overrun evidence), R1 (cold boot) |
| [P03b](P03b-retry-progress.md) | Does every fault position converge? | host | 15 min | P03 | R5 (fault retry) |
| [P03c](P03c-checkpoint-trace.md) | One position, two traces: why retry re-executes | host | 15 min | P03b | R5 (retry contract) — **PASS** |
| [P03d](P03d-checkpoint-fix.md) | Does moving the checkpoint fix retry? | host | 15 min | P03c | R5 — **PASS, 0/187 mismatches** |
| [P03e](P03e-store-then-fault.md) | Does a store-then-fault word repeat its store? | host | 15 min | P03d | R5 — **BLOCKED**, but found the three-page frame requirement |
| [P12](P12-engine-32bit.md) | Engine at 32-bit refs + paging | host | 15 min | P01 | 3 986 B, spare negative |
| [P13](P13-stack-depth.md) | Real stack depth | host | 15 min | — | **20+7 cells = 108 B** |
| [P14](P14-cycles-per-token.md) | Cycles per dispatch | host | 15 min | P05 | 1 074 cycles, 90.9 % fetch |
| [P16](P16-page-fetch.md) | Page fetch cost, live failures | **board** | 15 min | P20 | **144 µs**; two-in-flight corrupts |
| [P18](P18-edge-coalescing.md) | Pin edges through sleep | **board** | 15 min | P06 | latched, k→1 event, ≤1 period |
| [P19](P19-operand-colocation.md) | Operand co-location | host | 15 min | P03f | FAIL: third page is *data* |
| [P20](P20-native-accessors.md) | Native accessors vs trimmed set | host | 15 min | P14 | trim −824 B; accessors +116 B, 0 cycles |
| [P21](P21-c-stack.md) | C stack bound | host | 15 min | P12 | 176+68 = 244 B → 320 recommended |
| [P22](P22-fits.md) | Build and link the whole machine | host | 15 min | P20 | links, 94 B spare |
| [P23](P23-doorbell.md) | ULP→HP signal path | **board** | 15 min | P16 | **176 µs**, HP blocked |
| [P24](P24-os-layer.md) | OS layer size | host | 15 min | P22 | 3 044 B = 5.9 frames |
| [P25](P25-hot-layout.md) | Hot-set layout + tracer fix | host | 15 min | P24 | page counts were *occupancy*, re-traced |
| [P26](P26-minimal-layer.md) | Smallest layer satisfying R3/R4 | host | 15 min | P24 | **1 024 B**, idle loop 0 faults |
| [P27](P27-resumable-interpreter.md) | Real context switch | host | 15 min | P26 | works inside a colon word; 140 B/task |
| [P28](P28-pay-for-r4.md) | Paying for R4 | host | 15 min | P22 | only 16-bit tokens close (+232 B) |
| [P29](P29-shipping-engine.md) | Shipping engine budget gate | host | 15 min | P28 | FAIL: 4 934 B, 1 836 over |
| [P30](P30-code-structure.md) | Can structure buy 1 496 B? | host | 15 min | P29 | FAIL: out-of-line costs +1 186 |
| [P31](P31-primitive-set.md) | Which primitives are needed | host | 15 min | P30 | 40 derived; 3 412 B; 296 over |
| [P32](P32-audit-budget.md) | Audit the 322 B; price the language | host | 15 min | P31 | 322 named; with language 800 over |
| [P33](P33-visible-blocks.md) | Visible block layer | host | 15 min | P32 | **links**, 7 071/7 856; 456 B of Forth |
| [P34](P34-forth-paging.md) | Transparent paging in Forth | host | 15 min | P33 | 888 B of dictionary — unaffordable |
| [P35](P35-program-size.md) | How big is the program | host | 15 min | P32 | `MEMSZ` 2 196; **1 008 B** app space |
| [P36](P36-overlays.md) | Apps as loaded segments | host | 15 min | P35 | mechanism works, loader 1 400 B: dead |
| [P37](P37-block-wrapper.md) | Why the block wrapper hangs | host | 15 min | P33 | **three Forth bugs**, harness innocent |
| [P38](P38-fix-block-words.md) | Fix and prove | host | 15 min | P37 | **PASS 5/5** |
| [P39](P39-first-chip-run.md) | First execution on the ULP | **board** | 15 min | P38 | **`2 3 + 4 * .` → 20** |
| [P43](P43-r4-tasks.md) | Does R4 run on the chip? | **board** | 15 min | P27 | **PASS: 2 tasks → 1324, 3 tasks → 131242** |
| [P42](P42-lhu-fetch.md) | Does a halfword fetch pay? | **board** | 15 min | P14 | **PASS: −35.2 %/dispatch** (1 757.75 → 1 139.25), +6 B, adopted |
| [P41](P41-ulp-only.md) | Does any Forth run on the main cores? | **board** | 15 min | P39 | **PASS**: static 6/6, stub console `b''` |
| [P10](P10-repl-host.md) | REPL line discipline, escapes, flow control | host | 15 min | P04 | R8 (items 2–4, 8) |
| [P11](P11-repl-board.md) | Real REPL link: attach, pacing, exclusion, dead-man | **board** | 15 min | P06, P10 | R8 (items 1–3, 6, 7) |

Dependency shape: `P01 → P02 → P03` and `P05 → P06 → P07 → P08`, with `P04` and `P09` off to the
side. The two chains are independent of each other, so one host agent and one board agent can make
progress simultaneously — but never two board agents.

## Timeboxes: 15 minutes, one run

Fifteen minutes per probe, from first command to written result, and no splitting a probe into
slices. Long enough that a build (2–3 min), a flash (20 s) and a real measurement fit; short enough
that a stuck agent costs a quarter of an hour rather than an afternoon.

Two rules make it enforceable:

* **T−2 min: stop starting new work.** Write `RESULT.md` with what exists, kill processes and the
  tmux session.
* **If it does not fit in 15 minutes, the question is too big.** The answer is a narrower question,
  not a second run and not slices. That is why each brief asks one thing and names what a partial
  answer is worth.

A `PARTIAL` with numbers is a legitimate outcome and is written up as such. A probe that runs out of
time having written nothing is a failure of the brief, and the brief gets cut down.

**Board contention is enforced mechanically.** Every board probe starts with:

```sh
exec 9>probe/results/.board.lock
flock -n 9 || { echo "BLOCKED: board busy (another probe owns /dev/ttyACM0)"; exit 3; }
```

and keeps fd 9 open for the whole run. Two probes cannot flash the same chip.

## Waves

Strategic order, respecting the two scheduling rules:

| Wave | Probes | Why this order |
| --- | --- | --- |
| **1** | `P01` `P02` `P04` (host, parallel) + `P05` (board, exclusive) | can falsify the resident budget, the token width and the clock model before anything is built on them |
| **2** | `P03` (host, after P02) + `P06` (board, after P05) | the two assumptions most likely to be quietly wrong: fault idempotency, and what an overrunning wake actually does |
| **3** | `P07` (board) | fault cost — the number that decides whether paging is real |
| **4** | `P08` `P09` (board, serial) | storage and postmortem, both of which depend on a working server and a working wake |
| **5** | `P11` (board) | the REPL pipe end to end; needs P06's wake semantics and P10's line discipline |

`P03b` and `P10` are host-only and can run at any time alongside a board probe.

After each wave the orchestrator writes `docs/04-reconciliation.md`: what was learned, which acceptance
items can be ticked, which plan assumptions died, and the exact doc deltas applied. Nothing is marked
done from a probe's own claim — the orchestrator re-reads the evidence file.

## Launching one

Give the subagent the probe file and nothing else:

```
Read docs/probes/P03-paging-sim.md and execute it exactly as written.
You have no other context; the brief is complete. Do not edit docs/.
Write your result to probe/results/P03-paging-sim/RESULT.md and report
the verdict plus the doc deltas in your final message.
If blocked, print BLOCKED: <reason> and stop.
```

That is the whole contract. If a brief cannot be executed from that message alone, the brief is
wrong and gets fixed — not worked around.

# P03 — Paging model: retry, idempotency, frames, thrash detection

**Verdict: PARTIAL — the idempotency question is NOT answered. 0 fault positions were checked
against the baseline. The frame sweep hung at 4 frames and is reported as a hang, not a pass.**

Timebox: 15 min, cut at the cap by the orchestrator (see "What was cut"). Every command ran under
`timeout`; the one long run was redirected to `run.log` (`stdout` unbuffered) — an earlier version of
that run was piped through `head`, which lost its output; that mistake is recorded here so the next
probe does not repeat it.

---

## 1. Question and what is actually established

| Item | Value |
| --- | --- |
| fault positions tested (exhaustive sweep) | **0** — the sweep never reached the measurement loop |
| idempotency mismatches | **not measured** (must be 0; unknown is not 0) |
| faults: prelude @ 2 / 4 / 8 frames | **compile FAILED / 1 / 1** (see §3) |
| faults: 1-page, 3-page, 12-page @ 2 frames | **none — aborted**: 2 frames cannot compile the prelude |
| faults: 1/3/12-page @ 4 and 8 frames | **not measured — the run hung** (see §4) |
| `ERR_HOT_SET` fired where expected | **no data**: never fired in any completed case (peak `faults_per_wake` = 1) |
| resolve() cost: hit / miss | 9.4–9.6 ns / 43.7–58.6 ns per call (host), 2.1–4.1 ns for a PSRAM hit |
| proposed thrash rule and constants | **not justified by data** — do not change §4.2 rule 3 on this result |

Consequence for the design: `01-proposal.md` §4.2 rule 2 stays **unproven**. Nothing here refutes
it; nothing here supports it either. The three mechanisms the model *needs* (below) are the ones the
next, narrower probe must test.

---

## 2. Harness built (reusable — the next probe starts here, not from scratch)

Files in `probe/results/P03-paging-sim/` (a copy of `probe/uforth/`, nothing outside this directory
was modified):

* `uforth.c` — the reference engine plus a `#ifdef PAGING` build. In that build there is **no flat
  `mem[]`**: `rd8/wr8/rd16/wr16/rd32/wr32` are `resolve()` calls, so *every* byte the engine touches
  — token fetch, dictionary walk, `@ ! C@ C! W@ W!` — goes through the page table. `run()` became
  `run_from(w, ip, p)` returning after a fault; `#ifndef PAGING` keeps the original `run()` and the
  53-test suite byte-identical.
* `paging_sim.c` — address space, frame table, LRU, pinning, fake server, fault driver, injector,
  workloads, benchmarks.
* `run.log` — the last, partial run (this file's data). `after-tests.log` — the suite re-run.

Address space: `[0x0000_0000,0x0001_0000)` is the 16-bit dictionary window (tokens are `u16`, P02),
aliased onto flash pages 0..127; `0x1000_0000 +1 MB` is PSRAM (flat, always resident);
`0x2000_0000 +1 MB` is flash, pageable, backed by a private 1 MB server store. Anything else is a
loud `BADADDR`, never a silent alias. Page 512 B, frames 2/4/8, server latency 8 simulated units per
load (and 8 dispatch slots of budget, so a round trip is never free).

Three restart windows per primitive dispatch, which is what "the resume point is a dispatch" costs:

1. **before the token fetch** — a pure read, so retry needs nothing but the cursor;
2. **before the dispatch** — the checkpoint that matters: `(w, ip, p, sp, rsp, ds[], rs[],
   output length)`. Restoring the stacks is what makes `!` restartable at all, because `!` pops the
   address *in order to* resolve it;
3. **before advancing** — again a pure read.

Multi-byte accesses (`W@ W! @ ! LIT` operands, token fetch) call `vm_touch(va, len)` first: **every
page of the cell is resolved before any byte is written.** That is the "no partially-written cell"
rule, and it is a cheap invariant to test.

The outer interpreter needs a *fourth* restart point: `interpret()` itself faults inside
`find()`/`number()`/`,`, with no `run_from` frame above it. A fault there longjmps into a dead frame
("longjmp causes uninitialized stack frame" — observed). The fix in the harness: checkpoint
`(ti, sp, rsp, ds[], rs[], HERE, LATEST, STATE, outlen)` before each word is parsed, and `run()` must
restore the caller's `jmp_buf` on every exit. **This is a design delta, not a test artifact**: any
implementation that only makes primitives restartable will fault the same way.

Pinning: the definition being executed or compiled pins at most `min(2, frames/2)` code pages
(cap so a fault always has a victim); 4 frames ⇒ 2 pinned + 2 free, the case the brief asks for.

Output buffering: `pl_emit` appends to a per-dispatch buffer that is truncated on rollback, so an
`EMIT` before a fault cannot repeat. Without that, `TYPE`/`EMIT` are not idempotent even with a
perfect stack checkpoint. (Model, not measured.)

---

## 3. Prelude and frame counts (the only completed numbers)

`# P03 paging sim: page=512 B, frames up to 8, server latency=8 units, wake=64 dispatches`

```
## prelude
prelude frames=2 COMPILE-FAILED faults=5 hot=0 err=0
prelude frames=4 faults=1 loads=1 writebacks=0 no_victim=0 peak_fpw=1 hot=0 err=0
prelude frames=8 faults=1 loads=1 writebacks=0 no_victim=0 peak_fpw=1 hot=0 err=0
```

* The prelude (`boot_min.fs`, 97 words, dictionary 56 → ~1354 B = 3 pages) compiles at **4 and 8
  frames with exactly one page fault** (the first touch of the page that `HERE` grows into) and
  **no ERR_HOT_SET**: `peak_fpw = 1` against a threshold of `frames`. So the pass criterion "does not
  fire for the prelude" holds at 4 and 8 frames.
* **2 frames: compile FAILS** with `st.err = 1`, `errf = 0`, 5 faults, 1 writeback. That is my
  driver's *"fault arrived with no valid restart checkpoint"* path, **not** a proven capacity limit.
  The honest statement: at 2 frames the model cannot compile the prelude, and I did not isolate
  whether the cause is capacity or incomplete restart coverage. It is *not* evidence for "the
  resident dictionary must be smaller".

---

## 4. The hang — recorded as a FAIL, position not captured

`stdbuf -o0 timeout 100 ./paging_sim > run.log 2>&1` → `exit=124` (killed). The log stops in the
frame sweep:

```
## frame sweep
CASE-ERR: prelude failed at 2 frames
W1  frames=2 ... err=99 disp=0     (aborted: prelude)
CASE-ERR: prelude failed at 2 frames
W3  frames=2 ... err=99 disp=0     (aborted: prelude)
CASE-ERR: prelude failed at 2 frames
W12 frames=2 ... err=99 disp=0     (aborted: prelude)
        <-- nothing more: the first 4-frame case never printed
```

So the stall is in **W1 at 4 frames** — i.e. in the region where the prelude compiles cleanly and a
workload then pages over 4 frames. Two candidate causes, and the data does not separate them:

1. **Retry livelock:** the driver re-enters the same `(w, ip, p)`; if the page it needs is evicted
   again before the retried dispatch resolves it, the sequence repeats forever. My bound is 4×10⁶
   retries *per `run()`*, and every retry copies two 16-cell stacks plus a 512 B page load, so even a
   finite but pathological case looks like a hang inside 100 s. **The position was not captured** —
   the counters (`fault_w, fault_ip, fault_p`) are printed only on an idempotency mismatch, and the
   partial wake counters were not flushed. That is a harness defect: the retry loop must print
   `(w, ip, p, addr)` every N retries.
2. Slow-but-progressing: the sweep runs `run_case` per position with a full prelude recompile each
   time; if `D` is large, the whole section is minutes, not seconds.

**This is a finding about the design, not only about my harness:** a retry state machine with no
"same fault twice" rule has no way to distinguish progress from a livelock, and a 4-frame machine
where the pinned pages plus the demanded page exactly fill the table is precisely where that happens.
The rule to add: **`ERR_PAGE_FAULT_LOOP` when the same `(w, ip, p, fault address)` repeats K = 2
times without an intervening successful dispatch.** The harness has no such rule today — the brief's
"a hang is a FAIL, never a pass" is exactly what happened, and it is why no fault-position number
exists.

---

## 5. One observed retry that did work (anecdote, not a checked position)

From the verbose prelude run at 8 frames (`./paging_sim debug`, per-line dump):

```
45 errf=0 err=0 HERE=1010 LATEST=990  faults=0 retries=0 | : DO     ['] (DO)    W,  HERE ;   IMMEDIATE
46 errf=0 err=0 HERE=1034 LATEST=1010 faults=1 retries=1 | : LOOP   ['] (LOOP)  W,  W, ;    IMMEDIATE
47 errf=0 err=0 HERE=1056 LATEST=1034 faults=1 retries=1 | : +LOOP  ['] (+LOOP) W,  W, ;    IMMEDIATE
```

A page fault landed inside the compilation of `: LOOP …` (the one fault is the page `HERE` grew into),
the retry restored the dispatch checkpoint, re-executed that primitive, and `HERE`/`LATEST` advanced
exactly as they do with no fault. One position, one retry, correct result. **It is not part of the
sweep count and must not be read as "idempotency works".**

---

## 6. Costs (host, `-O1`, x86-64; reported in ns — do not convert to ULP cycles)

```
BENCH resolve-hit-flash   : 9.58 / 9.36 ns/call  (1e6 calls, resident page)
BENCH resolve-hit-psram   : 2.12 / 4.13 ns/call  (1e6 calls)
BENCH resolve-miss+fault  : 58.6 / 43.7 ns/fault (2e5 faults, incl. writeback + load + longjmp)
```

The miss path is ~5–6× the hit path *on the host, where a "server" load is a `memcpy`*. On the chip
the same fault costs a round trip (P07's 50–200 µs, §4.2 rule 3), so the ratio here says nothing
about the budget; only the hit path shape (a page-table lookup and an LRU stamp) ports. Instruction
counts per `resolve()` were **not** taken (no `objdump` pass inside the box) — that is unfinished.

Also: `resolve()` calls `pin_page()` on every dictionary-window hit and stamps the LRU on every hit,
so the measured hit cost already includes the pin-set scan (≤2 entries).

---

## 7. Defect found in the fixture (independent of paging)

`boot_min.fs` defines `: BASE 12 @ ;` — that returns the *contents* of `V_BASE` (10), not the
variable's address (12). So `16 BASE !` (i.e. `HEX`) stores 16 at address 10, which is
`V_LATEST+2`, and destroys the dictionary chain. Verified on the **unmodified** prototype
(`probe/uforth/uforth.c`):

```
before: LATEST=1332 BASE=10
after HEX: LATEST=1049908 BASE=0
```

`DECIMAL` (= `10 BASE !`) does the same with value 32 (`' '`). Any probe that uses `HEX`/`DECIMAL`
(P02, P04 corpora) is measuring a dictionary with a corrupted `LATEST` afterwards; the 53-test suite
passes only because the affected assertions fall through to `number()` or read the stack by luck.
The workloads here therefore use decimal literals only (`537395200` = `0x2008_0000` = flash page
1024). **This is a one-line fix in `boot_min.fs` (`: BASE [ 12 ] LITERAL ;` or `12` as a `CONSTANT`
holding 12) and should be done before any prelude-measuring probe runs again.**

---

## 8. What was cut, and what the next probe should do

Cut by the 15-minute cap: the exhaustive fault-position sweep (0 of `D` positions), the 4/8-frame
cases of the 1-page/3-page/12-page sweep, `ERR_HOT_SET` validation against the 12-page workload, the
instruction count per `resolve()`, and the thrash-rule constants.

To continue from this harness, in this order — all are small edits, no new model:

1. **Add `ERR_PAGE_FAULT_LOOP`** (same `(w, ip, p, addr)` twice without a successful dispatch), and
   print `(w, ip, p, addr)` every 1000 retries. That converts the hang in §4 into a recorded FAIL
   position and tells us whether it is a livelock.
2. **Fix the `BASE` defect** in the fixture, then re-run only the 4-frame `W1` case — the one that
   hung.
3. **Narrow the idempotency question** to what fits: one workload (`WORK`, 4 pages, 8 frames),
   `D` = the baseline dispatch count from the no-fault run, one run per position with
   `inject_at = k` (the injector forces a spurious fault at the *next resolve* of dispatch `k`,
   disarms if that dispatch has no memory access, and counts those as
   `no_access_positions` — never silently skipped). Compare `sp`, `rsp`, `ds[]`, the checksum over
   dictionary pages 0..7 + data pages 1024..1039, and the output hash. Today that loop exists
   (`main`, section "idempotency sweep") but never executed: the baseline digest printed `err=99`
   because the prelude log then still used `HEX`.
4. Only then re-run the frame sweep and pick the thrash constants from real
   `faults_per_wake` numbers (wake = 64 dispatches; rule provisionally
   `faults_per_wake > frames for K = 2 consecutive wakes ⇒ sticky ERR_HOT_SET`, **unvalidated**).

---

## 9. Doc deltas (only what today's data supports)

* `docs/01-proposal.md` **§4.2 rule 2** — add the mechanism, keep the rule unproven. Suggested text:

  > **A fault retires and retries at a primitive dispatch.** The interpreter saves
  > `(w, ip, p, dsp, rsp, stacks)` before every primitive dispatch; a fault restores that checkpoint,
  > the frame is loaded, and the same `(w, ip, p)` is re-entered. Three consequences are structural,
  > not optional: (a) the data/return stacks must be restored, because `!` pops the address in order
  > to resolve it — a fault otherwise loses the operands and every retry computes something else;
  > (b) a multi-byte access resolves *all* pages of the cell before writing any byte, so no fault can
  > leave a half-written cell; (c) the outer interpreter needs its own restart point at the word
  > boundary, because `find`/`number`/`,` touch memory with no `run_from` frame above them. Output
  > must be buffered per dispatch and discarded on rollback. **Exhaustive verification of these
  > claims is still outstanding (P03 partial).**

* `docs/01-proposal.md` **§4.2 rule 3** — no change. Do not write a thrash rule from this result;
  `ERR_HOT_SET` never fired and `faults_per_wake` never exceeded 1 in any completed case.
* `docs/01-proposal.md` **§4.3** — **no change justified**. The prelude compiles at 4 frames with a
  single fault, so the "if the engine exceeds 3.0 KB, drop to 2 frames" branch has no support here,
  and 2 frames did fail — for a reason not yet isolated. Leave 4 frames in the text.
* `docs/02-harness.md` — no mailbox field is justified by this run.
* `probe/uforth/boot_min.fs` (`BASE`) — **fix required**, §7 above. Not edited here (outside this
  probe's write scope).

# P04 — Console, rings, and a sliced interpreter

| | |
| --- | --- |
| Runs on | host only (gcc, no board, no `idf.py`, no `/dev/ttyACM*`) |
| Started | 2026-10-30T12:30:35−07:00 |
| Finished | 2026-10-30T12:36 (well inside the 30 min box; no PARTIAL) |
| Verdict | **PASS with one qualification** — zero drops is achievable *in connected mode*, and is **not** achievable for a bulk paste in autonomous mode at any ring depth that fits ~600 B. The qualification is a flow-control requirement, and it is exactly the case the brief's first failure criterion describes. |

Everything below was produced by the code in this directory. Files:

| File | What it is |
| --- | --- |
| `uforth.c` | copy of `probe/uforth/uforth.c` with (i) `forth_quit()` replaced by `repl_step()`, (ii) non-blocking `KEY`, (iii) an `ERR_LINE_LONG` instead of silent truncation, (iv) two cost counters (`prim_ops`, `mem_ops`) |
| `host_test.c`, `boot_min.fs`, `probe_image.h` | unmodified copies of the baseline; `host_test.c` is byte-identical to the original, which is how the 53-test suite below proves the rewrite |
| `slice_probe.c` | the simulator: paced command ring of depth C, output ring of depth O flushed at wake exit, wake loop of W `repl_step()` calls + a flush + the other task |
| `paste100.fs` | workload (b): exactly 100 lines, 3204 B, mean 31 B/line, max 60 B/line |
| `baseline-tests.log` | the 53 tests on the unmodified copy (before editing) |
| `sliced-tests.log` | the same 53 tests on the sliced copy (after editing) |
| `sweep.log` | the complete 96-row sweep + the `KEY` test + slice-equivalence + dictionary cost |
| `build-baseline.log`, `build-sliced.log`, `build-probe.log` | compiler output, `-Wall -Wextra` clean |

---

## 1. Answers

### 1.1 The parameters the brief asks for

**Recommended triple: `k = 4`, `C = 128`, `O = 256`** — 384 B of the 600 B "mailbox + cmd/out
rings" line in §4.3, leaving 216 B for the mailbox and status.

| Parameter | Value | Why this value, measured |
| --- | --- | --- |
| `k` (tokens per `repl_step`) | **4** | With W = 4 steps/wake a wake retires ≤ 16 tokens. `k = 1` also gives zero drops but needs 3.6× more wakes per line (5 active steps/line at k = 4 vs 18 at k = 1 on the 60-char line). `k = 16/64` buy nothing: the `nchars` ring budget already caps a step at ~9 tokens, so `k ≥ 9` is unobservable for lines shorter than the ring budget. |
| `C` (command ring, bytes) | **128** | Measured peak occupancy in connected mode is **1 byte** at every `k` and every `C` — the ring is essentially never occupied, because 0.115 B/wake arrives and a step drains up to 32. `C` is therefore not sized by the paste; it is sized by the longest *gap between two drains*: `C ≥ 11520 B/s × T_gap`. 128 B covers a **11 ms** stall (an HP-core round trip, a dead-man window, a 200 µs page fault, or a missed wake) with the whole paste in flight. 64 B covers only 5.5 ms. |
| `O` (out ring, bytes) | **256** | Output is flushed at wake exit, so `O` must hold **one wake's** output, not one paste's. Measured peak: **8 B/wake** in connected mode, **123 B/wake** in the worst autonomous wake. The theoretical worst single wake is a 79-char line echo + ` ok\n` + a named error ≈ 103 B, so 128 is 1.2× and 256 is 2.5×. `drops_out` was **0 in all 96 runs**, including at `O = 128`; 256 is chosen for that 2.5× margin, not because 128 failed. |
| `W` (steps per wake) | 4 (assumed scheduler quantum) | A linear multiplier on both throughput and latency. The numbers below are per wake, and `W` is reported with every one of them so a different quantum can be scaled. |

`W` is *not* a parameter the brief asked for, but it multiplies everything, so it is stated
explicitly: every latency and every per-wake output number below is with W = 4 and `nchars` = 32
ring bytes per step.

### 1.2 Measured drop counts and worst-case latency, per workload

Recommended triple `k = 4, C = 128, O = 256`, W = 4, `nchars` = 32:

| Workload | drops_in | drops_out | lines done | tokens | active steps/line (max) | tokens/step (mean) | **tokens/wake max** | **prim. dispatches/wake max** | worst single token | peak cmd-ring | peak out-ring | out B/wake max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| (a) one 60-char line, typed at 10 chars/s | **0** | **0** | 1/1 | 18 | 5 | 3.6 | **16** | **6** | 1 | 1 B | 4 B | 4 |
| (b) 100-line `boot_min.fs`-sized paste, connected (10 µs wakes, 115200 8N1) | **0** | **0** | 100/100 | 320 | 2 | 2.7 | **7** | **8** | 7 | 1 B | 8 B | 8 |
| (b₂) the same paste, **autonomous** (100 ms wakes) — worst case for input | **2933 of 3204 (91.5 %)** | 0 | 10/100 + 1 named error | 37 | 2 | 2.9 | **14** | **12** | 7 | 128 B (full) | 90 B | 90 |
| (c) interactive: short lines alternating with long `: ... ;` definitions (incl. a 100-iteration loop) | **0** | **0** | 6/6 | 30 | 3 | 3.0 | **10** | **505** | **505** | 1 B | 5 B | 5 |

Three things fall out of that table:

1. **`k` does not bound the wake; one token does.** In (c) the wake paid **505 primitive
   dispatches** while retiring only **10 tokens**: the token `BIG` is a colon word containing
   `100 0 DO I 2 * DROP LOOP`, and `run()` executes all 100 iterations inside one `run()` call.
   That is 64× the token budget at k = 4 and 126× at k = 1. **Slicing at token boundaries is
   therefore not sufficient for the 30 µs connected budget.** See §3 and Delta 1.
2. **Output is never the problem; input in autonomous mode is.** `drops_out == 0` in all 96 rows.
3. **A paste is wire-bound, not interpreter-bound.** (b) completes 100 lines / 320 tokens in
   27 813 wakes ≈ **278 ms**, which is 3204 B at 11520 B/s — the ULP spends < 1 % of those wakes
   doing work. A 100-line paste **is not instant** and takes ~3 autonomous periods.

### 1.3 The requirement, derived

With `r_in` = input byte rate, `r_svc` = service rate of the REPL, `T_w` = wake period:

```
C_min  ≥  (r_in − r_svc) · T_w          r_svc = W · nchars / T_w
```

* **Connected (T_w = 10 µs, or 30 µs at the slow end of §8's 1–4 ticks):**
  `r_in = 11520 B/s`, `r_svc = 4·32 B / 10 µs = 12.8 MB/s` (4.3 MB/s at 30 µs). `r_svc ≫ r_in`,
  so `C_min ≈ 1 B + jitter`. Measured peak occupancy: 1 B. **No input drops at any C in the sweep.**
* **Autonomous (T_w = 100 ms):** `r_in = 11 520 B/s`, `r_svc = 128 B / 100 ms = 1280 B/s`, so
  `C_min ≥ (11520 − 1280) · 0.1 = 1024 B` — **1.7× the entire 600 B ring budget**, and enlarging
  the ring cannot fix it (measured: C = 64 → 3061 dropped, C = 128 → 2933, C = 256 → 2758 of 3204;
  the ring size buys 300 bytes and the deficit is 2933). **Flow control is required**: the host
  must send the next line only after the prompt byte (` ok\n`), which caps in-flight input at one
  line ≤ 79 B ≪ 128 B, and/or the status mailbox must assert XOFF.

**Which budget is binding: the 30 µs connected budget.** The autonomous budget is 3000× looser
(505 dispatches in 100 ms is nothing); the connected wake at 30 µs is where a 505-dispatch token
does not fit. Without P05's cycles/tick the conversion cannot be finished, so the binding
constraint is stated in the currency that *is* measured:

| Quantity | Measured | Consequence if P05 measures … |
| --- | --- | --- |
| max tokens/wake at k = 4 | 16 | at 20 MHz (600 cycles / 30 µs) a token must cost ≤ 37 cycles — plausible |
| max primitive dispatches/wake | 505 | at 20 MHz that is 1.2 cycles per dispatch — **impossible**; the 100-iteration token cannot run in a connected wake |
| budget inside `run()` | not bounded today | propose `p = 32` dispatches per step and resume; then 600 cycles / 32 = 18 cycles per dispatch |

### 1.4 `KEY` with an empty ring (pass criterion 2)

```
KEY empty-ring: returns=REPL_ERR sp=0 ring_bytes=0 out="ERR_NO_INPUT?\n"
KEY empty-ring named error, nothing pushed, nothing consumed: PASS
```

`KEY` (`P_KEY`) now reads through `pl_cmd_pop()`, which returns −1 when the ring is empty. Measured:
returns `REPL_ERR` in the same step, pushes **nothing** (`sp` unchanged), pulls **no ring byte**
(`ring_bytes = 0`, the ring is untouched), emits the named error `ERR_NO_INPUT?`, and consumes
exactly **one** primitive dispatch (the `KEY` dispatch itself) — it does not wait, and it does not
consume a wake. `KEY?` also reads the real ring now (`pl_hw(5)` → ring non-empty), which retires
the baseline's *"DEFECT: KEY? is hardwired false on the host"* item on this side.

### 1.5 Bytes per token (for projecting the ULP budget)

Measured dictionary growth on this build (`sweep.log`, tail):

| Source | Tokens | Dictionary growth | B/token |
| --- | --- | --- | --- |
| `: TT 2 * 1 + ;` | 7 | 26 B | **3.71** |
| `: TTT DUP 0> IF 111 ELSE 222 THEN ;` | 11 | 34 B | **3.09** |

I.e. ≈ **10 B fixed header per definition + 2 B per token slot** (a `LIT` costs 6 B / 2 tokens
because of the 4-byte literal). `boot_min.fs` (68 lines, 2680 source bytes) compiles to
**1412 B** of dictionary including the 540 B of primitive headers, 97 words, 21 B per high-level
word — consistent with `docs/03-prototype-review.md`. The prelude therefore costs ~3 B of
dictionary per token of source, which is the number to multiply when projecting how much of the
resident dictionary a prelude page eats.

---

## 2. Evidence

### 2.1 Commands (all with `timeout`; no `&`, no `tmux` needed — every run is < 2 s)

```sh
cd probe/results/P04-console-and-slicing
# baseline, before any edit
timeout 120 gcc -DHOST -std=c99 -Wall -Wextra -O1 -o uforth_test_baseline host_test.c
timeout  60 ./uforth_test_baseline > baseline-tests.log      # 53 passed, 0 failed
# after the rewrite
timeout 120 gcc -DHOST -std=c99 -Wall -Wextra -O1 -o uforth_test host_test.c
timeout  60 ./uforth_test > sliced-tests.log                 # 53 passed, 0 failed
# the probe
timeout 120 gcc -std=c99 -Wall -Wextra -O1 -o slice_probe slice_probe.c
timeout 300 ./slice_probe > sweep.log                        # 96 rows, 0.9 s
```

`-Wall -Wextra` is clean on both builds (one `%lu`/`%u` format warning in the first draft of the
probe was fixed; `build-probe.log` is the clean rebuild). Tests were never weakened: `host_test.c`
is an unmodified copy, and the 53 assertions — including the 10 KNOWN DEFECT ones — are the same
assertions.

### 2.2 The 53-test suite still passes (pass criterion, explicit)

| Run | File | Result |
| --- | --- | --- |
| baseline (unmodified `uforth.c`) | `baseline-tests.log` | `53 passed, 0 failed` |
| after the rewrite (`uforth.c` with `repl_step`, non-blocking `KEY`, `ERR_LINE_LONG`) | `sliced-tests.log` | `53 passed, 0 failed` |

The suite exercises `interpret()`, which is untouched; the sliced path is additionally proven
equivalent by the probe itself:

```
repl_step(k=1, nchars=8) matches interpret() on 13 lines: PASS
```

13 lines (arithmetic, `DO/LOOP`, `BEGIN/UNTIL`, a failing definition with rollback, `CONSTANT`,
`CREATE`/`,`/`@`, a colon word with a loop) driven through `repl_step` with the smallest slice
produce the same stack depth **and the same values** (31-hash of the whole stack) as `interpret()`.

### 2.3 The sweep (condensed; all 96 rows are in `sweep.log`)

Constants: W = 4 steps/wake, `nchars` = 32 ring bytes/step, MEMSZ = 8192 (so the dictionary, not
the rings, is never the limiter — the measured boot image is 1412 B), wire = 115200 8N1 =
11520 B/s, typing = 10 chars/s, connected wake = 10 µs, autonomous wake = 100 ms.

Connected workloads (a), (b), (c) — 72 rows, aggregated by `k` (max over C ∈ {64,128,256} and
O ∈ {128,256}):

| `k` | rows | drops_in max | drops_out max | tokens/wake max | prim. dispatch/wake max | out B/wake max |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 18 | **0** | **0** | 4 | 505 | 8 |
| 4 | 18 | **0** | **0** | 16 | 505 | 8 |
| 16 | 18 | **0** | **0** | 18 | 505 | 8 |
| 64 | 18 | **0** | **0** | 18 | 505 | 8 |

Autonomous paste (b₂) — all 24 rows, the input-side worst case:

| `k` | `C` | `O` | drops_in (of 3204 B) | in_peak | lines done / 100 |
| --- | --- | --- | --- | --- | --- |
| 1 | 64 | 128 / 256 | 3061 (95.5 %) | 64 (full) | 5 |
| 4 | 64 | 128 / 256 | 3061 | 64 | 5 |
| 16 | 64 | 128 / 256 | 3061 | 64 | 5 |
| 64 | 64 | 128 / 256 | 3061 | 64 | 5 |
| 1 | 128 | 128 / 256 | 2994 (93.4 %) | 128 | 8 |
| 4 | 128 | 128 / 256 | 2933 (91.5 %) | 128 | 10 |
| 16 | 128 | 128 / 256 | 2912 | 128 | 10 |
| 64 | 128 | 128 / 256 | 2912 | 128 | 10 |
| 1 | 256 | 128 / 256 | 2866 (89.4 %) | 256 | 11 |
| 4 | 256 | 128 / 256 | 2790 | 256 | 11 |
| 16 | 256 | 128 / 256 | 2758 (86.1 %) | 256 | 14 |
| 64 | 256 | 128 / 256 | 2758 | 256 | 14 |

Every autonomous row also produced at least one **named** error, never a silent wrong answer: the
bytes lost mid-line are concatenated with the next line's start, which hits `ERR_LINE_LONG` or a
bad-word error and aborts that line with the dictionary rolled back. `O` never mattered (0 drops).

Selected single rows (the recommended triple and its neighbours):

```
k,C,O,workload,wakes,lines,errs,tokens,steps,active,tok/active,steps/line,tok/line,
  tok/wake,prim/wake,single-tok,drops_in,drops_out,in_peak,out_peak,outB/wake,outB,memops/prim
4,128,256,a-typed60-connected,610001,1,0,18,610065,5,3.60,5,18,  16,  6,  1,0,0,1, 4, 4, 65,73737
4,128,256,b-paste100-connected,27813,100,0,320,31037,120,2.67,2,7,  7,  8,  7,0,0,1, 8, 8,3607,33973
4,128,256,b2-paste100-autonomous,100005,10,1,37,100018,13,2.85,2,7, 14, 12,  7,2933,0,128,90,90,316,36055
4,128,256,c-interactive-connected,980000,6,0,30,980102,10,3.00,3,10, 10,505,505,0,0,1, 5, 5,122,1863
```

Notes on reading the CSV: `steps` counts every `repl_step()` call including the ones that did no
work (a typed line waits 100 ms per character = 10 000 idle wakes); `active` counts only the calls
that retired ≥ 1 token, so `tok/active` is the real tokens-per-step. `memops/prim` is 8-bit memory
accesses per primitive dispatch over the whole run (parse + `find()` included) — reported for
completeness, not used for the projection.

### 2.4 What the model does and does not simulate

Simulated: paced byte arrival into a depth-C ring (overflow counted, never wrapped), echo of every
received character into a depth-O ring that refuses (and counts) when full
(`drops_out`), a flush at every wake exit, `W` interpreter steps per wake, and the other task
running after them in the same wake. Doubly bounded: `MAXWAKES = 6 000 000` **and** a wall-clock
check inside the loop (600 s); the whole sweep took 0.9 s, no row timed out.

Not simulated (stated so nobody reads more into the numbers than is there): USB-CDC packetisation
(the arrival model is a smooth byte stream at wire rate — the burstier the real host, the more C
matters, which is why C is justified from the stall-gap formula rather than from the measured
1-byte peak), the ULP's real cycles/primitive (P05 has not run — `probe/results/P05-clock/` is
empty), and page faults / HP-core round trips inside a wake (folded into the 11 ms stall budget
that sets C).

---

## 3. Verdict

### 3.1 Pass criteria

| Criterion | Result |
| --- | --- |
| A `(k, C, O)` exists with **zero** drops in all three workloads | **PASS for connected mode** — `drops_in = 0` and `drops_out = 0` in all 72 connected rows, for every `k ∈ {1,4,16,64}`, `C ∈ {64,128,256}`, `O ∈ {128,256}`. **FAIL for autonomous-mode bulk input** — 86–96 % of a 3204 B paste is dropped at every `C ≤ 256`; `C_min = 1024 B` at 100 ms, which does not fit. See §3.2. |
| `KEY` with an empty ring consumes no step and returns a named error | **PASS** — `REPL_ERR` + `ERR_NO_INPUT?`, nothing pushed, no ring byte consumed, 1 primitive dispatch, no wait. |
| Worst-case wake latency for the recommended triple, in token-units and projected µs | **PASS in token-units; µs not available.** Reported: ≤ 16 tokens/wake (measured 16 / 7 / 10 / 10) and ≤ 505 primitive dispatches/wake. **P05 has not run** (`probe/results/P05-clock/` is empty), so the µs projection cannot be made and is stated as a cycles-per-dispatch inequality instead (§1.3). This is the one item the brief allows to be reported in token-units with an explicit note. |

### 3.2 Which failure criteria fired, and what each changes

1. **"No triple gives zero drops within the RAM budget" — fired for autonomous-mode input.**
   The real bound is `C_min ≥ (r_in − r_svc)·T_w`, i.e. **1024 B at 100 ms / 115200 baud**, 1.7×
   the whole ring budget. The fix is **not** a bigger ring: **flow control**. The host sends the
   next line only after the prompt byte (` ok\n`), and the status mailbox asserts XOFF when the
   command ring is over 75 % full. With prompt pacing, in-flight input ≤ one line (≤ 79 B), so
   `C = 128` has 1.6× margin and `drops_in == 0` holds in both modes. Output needs no flow control:
   0 drops in 96/96 runs.
2. **"`k` must be 1 to meet latency" — fired, but not as the brief expected.** `k = 1` does *not*
   rescue the 30 µs budget: the 505-dispatch token (`BIG`) costs the same at `k = 1` as at `k = 64`,
   because `run()` is atomic. So the conclusion is stronger than the brief's: the interpreter must
   be **resumable at every primitive dispatch**, not merely at every token — `run_from(w, ip, budget)`
   must be the *only* execution path, and `repl_step()` becomes a thin loop over it. This changes §5.
3. **"A 100-line paste takes more than one autonomous period" — fired, and it is wire-bound.**
   3204 B at 115200 8N1 = **278 ms** ≈ 3 autonomous periods (or 27 813 connected wakes at 10 µs).
   §7's boot/paste story must state ~0.3 s per 100 lines at 115200 (and scale with baud), instead
   of implying instant.

Not fired: no hang, no retry storm, no silent output loss, no case exceeded the wall clock, and no
run needed a second attempt.

---

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### Delta 1 — `docs/01-proposal.md` §5, replace this bullet

Current:

```
* **The text interpreter is sliced.** `interpret-step` consumes *k* tokens and returns with its
  cursor in memory, so a long `EVALUATE` yields instead of freezing the loop.
```

Replace with:

```
* **The text interpreter is sliced, at two granularities.** `repl-step(k, nchars)` pulls at most
  `nchars` bytes out of the command ring and retires at most *k* = 4 tokens, then returns
  `MORE | LINE_DONE | ERR` with its cursor in memory, so a long `EVALUATE` or a pasted line yields
  instead of freezing the loop. Measured on the host (probe P04): with 4 steps per wake a wake
  retires ≤ 16 tokens and, for ordinary lines, ≤ 8 primitive dispatches. But **one token is not one
  unit of work**: a token that calls a colon word with a 100-iteration loop costs 505 primitive
  dispatches in a single `run()` call — 126× the `k = 1` token budget — so the token budget alone
  does not bound a wake. The interpreter therefore carries a *dispatch* budget too:
  `run_from(w, ip, p)` resumes at any primitive, and it is the only execution path (`k = 1` does not
  save you; resumability at token boundaries is not resumability). Worst case per wake is
  `min(W·k, work available)` tokens **and** `W·p` primitive dispatches, whichever comes first.
```

### Delta 2 — `docs/01-proposal.md` §8, replace the paragraph after the mode table

Current:

```
The host switches mode on attach/detach through the protocol, with a dead-man timer in case it
vanishes mid-session. Output is buffered into the `out` ring and flushed at wake exit; refused bytes
increment `drops_out` and are reported, never silently lost.
```

Replace with:

```
The host switches mode on attach/detach through the protocol, with a dead-man timer in case it
vanishes mid-session. Output is buffered into the `out` ring and flushed at wake exit; refused bytes
increment `drops_out` and are reported, never silently lost.

Ring depths (measured, probe P04): **cmd ring 128 B, out ring 256 B** — 384 B of the 600 B
mailbox+rings line in §4.3, leaving 216 B for the mailbox. They are sized for different reasons.
`out` must hold *one wake's* output, because it is flushed at wake exit: measured peak 8 B/wake
connected, 123 B/wake in the worst autonomous wake, theoretical worst ~103 B (79-char echo + ` ok\n`
+ a named error), so 256 B is a 2.5× margin; `drops_out` was 0 in all 96 probe runs, including at
128 B. `cmd` must hold `r_in · T_gap`, the bytes that arrive during the longest *gap between two
drains*, not during one period: 128 B covers an 11 ms stall (HP-core round trip, page fault,
missed wake) at 115200 8N1, and the measured peak occupancy in connected mode is 1 B.

Bulk input does **not** fit the ring in autonomous mode and is not supposed to: at a 100 ms period
11520 B/s needs `C ≥ 1024 B` to survive a burst, 1.7× the whole ring budget, and the measured loss
is 86–96 % of a 3204 B paste at every C from 64 to 256. Lost bytes are never silent (they produce
`ERR_LINE_LONG` or a bad-word error with the dictionary rolled back), but they are lost. So bulk
input is **flow-controlled, not buffered**: the host sends the next line only after the prompt byte
(` ok\n`), and the status mailbox asserts XOFF when the command ring is over 75 % full. Under that
rule at most one line (≤ 79 B) is ever in flight and `drops_in == 0` holds in connected and
autonomous mode alike.
```

### Delta 3 — `docs/01-proposal.md` §10, R2, replace the second bullet

Current:

```
- [ ] 200 consecutive command lines are interpreted with **zero** dropped output bytes
      (`drops_out == 0`) and zero lost input characters.
```

Replace with:

```
- [ ] 200 consecutive command lines are interpreted with **zero** dropped output bytes
      (`drops_out == 0`) and zero lost input characters, with the host pacing one line per prompt
      byte. Measured bound (probe P04, host simulation, 115200 8N1): output drops are zero for any
      ring ≥ 128 B (peak 123 B in the worst autonomous wake, 8 B/wake connected); input drops are
      zero for any cmd ring ≥ 64 B **only while the wake period keeps `C ≥ r_in · T_gap`** — 128 B
      covers an 11 ms stall. A bulk paste with no pacing loses 86–96 % of its bytes in autonomous
      mode (measured: 2758–3061 of 3204 B) and is therefore excluded from this item: it is a flow
      control requirement, not a ring-size one.
```

---

## 5. Follow-ups

1. **P05 is the blocker for the µs number** (and for R3's "budget for 99.9 % of wakes"). Needed:
   cycles per primitive dispatch and cycles per token (including parse + `find()`). With those, the
   table in §1.3 converts directly; the inequality to satisfy is `W·p·cycles_per_dispatch ≤ 600`
   (30 µs at 20 MHz) in connected mode and `≤ 2·10⁶` (100 ms) in autonomous mode — i.e. the
   connected budget, not the autonomous one, is binding, and it is the `p` budget inside `run()`
   that has to meet it.
2. **Implement `run_from(w, ip, p)` with a dispatch budget and make it the only execution path.**
   P04 measures the need (505 dispatches in one token); the probe's `repl_step()` is a token-level
   slicer and deliberately still calls the atomic `run()`, so the next probe should slice inside it.
   Suggested starting `p`: 32 dispatches/step (needs ≤ 18 cycles per dispatch at 20 MHz).
3. **Measure `find()` cost, which this probe folds into the token cost.** `find()` walks the header
   list with ~3 memory accesses per header; at 97 words that is ~300 accesses per looked-up token,
   far more than executing a primitive. A dictionary index or a hash in the header would change the
   latency model more than `k` does. Worth its own probe before P05's number is used to size `p`.
4. **Flow control belongs in the wire protocol, not in §8's prose.** `docs/02-harness.md` should get
   the prompt-paced rule and the XOFF threshold (cmd ring > 75 % full) as protocol requirements,
   plus the `~0.3 s per 100 lines at 115200` figure for the prelude stream in §7.
5. **The 53-test suite still does not exercise the sliced path** (it drives `interpret()`). The probe
   added a 13-line equivalence check, but that should live in `host_test.c` so a future regression in
   `repl_step()` fails the suite rather than a probe. Suggested: append the same 13 lines as a new
   test group (this probe did not edit `host_test.c` because the brief requires the 53 assertions to
   stay identical).
6. **`ERR_LINE_LONG` changes a documented defect.** The baseline silently truncated lines past
   TIBSZ−1; the sliced REPL now raises a named error and executes nothing. Whenever the suite is
   next updated, the *"interactive line truncation"* note in `REVIEW-RUN.txt` is now stale on this
   side.

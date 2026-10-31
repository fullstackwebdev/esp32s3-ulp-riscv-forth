# P25 — Can a hot-set layout rule make the idle loop fault-free?

| | |
| --- | --- |
| Result | **The re-validation came first and it moved one number by a verdict.** The tracer that P24/P26's idle-loop numbers rest on is *not* the same instrument: P24 and P26 both counted the **distinct pages the named definitions occupy** (analytic), and the first P25 tracer counted **data accesses only** — instruction fetches go through `resolve()`, so the entire dispatch stream was invisible to it. Re-measured on one instrument, the fixed tracer, on the **same workload**: the P24-order idle loop is **4 pages / 0 faults/pass** with the broken tracer and **7 pages / 13 faults/pass** with the fixed one — the bug that missed instruction fetches would have declared R3 **fault-free**; P26's minimal layer is **2 pages / 0 faults/pass steady state** either way, so **P26's "0 faults" survives the fixed tracer** (it was never 3 pages of thrash, and the 3rd page in its table was analytic slack). Then the layout question, unchanged in answer: reordering the layer so the idle path's definitions are contiguous does what it says on the tin — the idle loop's layer footprint drops from **7 pages to 5** — and it does so as *placement only*: the two builds have the same 80 definitions, the same 5540 B of dictionary, the same text per definition, and the same number of page touches per workload (8570 / 5580 / 23895). But **no configuration reaches 0 faults/pass**: at 4 frames the reordered loop faults **14/pass unpinned**, **16 / 18 / 10** with 1 / 2 / 3 pinned frames. The idle block is **2092 B = 4.09 pages — 44 B over the 4-page budget**, so it is 5 pages wherever it starts, and pinning three of those five leaves one LRU frame for the other two. A bound run with 5 frames gives **0 faults/pass steady state**, which locates the remaining gap exactly: the loop is **44 B too big**, not mislaid. Layout cannot close it; P26 has to cut 44 B from the idle path. |
| Runs on | **host only** (`gcc -DHOST`, board untouched, no serial device opened) |
| Time box | one run, 15 min hard cap — **overrun**: ~30 min, 20 of them on tracer bugs that are themselves findings (§2.4) |
| Sources | `uforth.c` = P24's, **plus a page-touch tracer and a workload driver under `#ifdef HOST`** (nothing else changed); `boot_min.fs`, `os_tasks.fs`, `os_events.fs`, `os_repl.fs`, `os_introspect.fs`, `os_device.fs` = P24's, byte-identical; `os_hot.fs` + `os_cold.fs` = the same P24 definitions, re-emitted in a new order by `reorder.py`; `measure2.py` = header walk + page histogram + 4-frame LRU with pinned frames. |

## Record

Faults are steady state = faults in the **last** of ten passes, one continuous LRU across the trace, 512 B
pages, 4 frames, victim = true LRU. "Pinned k" holds frames 0..k−1 to the first k pages of the idle block
(pages 3, 4, 5 of the reordered build).

| Case | pages in idle loop | faults/pass | faults: 3-word line | faults: compile |
| --- | --- | --- | --- | --- |
| P24 baseline (analytic, distinct pages) | 6 | 6 | 8 | 3 |
| P24 baseline **as measured** (P24 order, 0 pinned) | **7** (3–9) | **13** | 5 | 43 |
| P24 order, **buggy tracer** (data only, no instruction fetch) | **4** (3,4,6,7) | **0** | — | — |
| P26 layer, idle, **fixed tracer** | **2** (3,4) + resident 0–2 | **0** | — | — |
| P26 layer, idle, **buggy tracer** | 2 (3,4) | 0 | — | — |
| reordered, 0 pinned | **5** (3–7) | **14** | 12 | 43 |
| reordered, 1 pinned (p3) | 5 | **16** | 10 | 38 |
| reordered, 2 pinned (p3, p4) | 5 | **18** | 8 | 33 |
| reordered, 3 pinned (p3, p4, p5) | 5 | **10** | 7 | 28 |

For reference, the same sweep on the P24 order (pinning pages that are *not* the idle block's pages):

| P24 order | 0 pinned | 1 pinned | 2 pinned | 3 pinned |
| --- | --- | --- | --- | --- |
| faults/pass, idle | 13 | 15 | 23 | 176 |

Byte cost of the layout rule: **0 B.** Both builds end at `HERE = 5540`, 80 layer definitions, 3812 B of
layer code fields + bodies by the `end − cf` measure. The per-definition 4-byte header padding sums to the
same total in both orders.

---

## 1. Answers

**Q: Does the idle path become contiguous, and how many pages does it then touch?**
**Yes, and the count falls 7 → 5 — not to 1–2.** The reordered build's idle block is
`VARIABLE … GPIOXT | EV! T-STATE! NEXT-TASK TICK+ WAKE-1 WAKE-ALL YIELD WAKE-MASK ON-GPIO
EV-GPIO-DO POLL-EVENTS PAUSE SLEEP-TICKS` = 53 definitions occupying **1716–3808 B (2092 B)**.
The idle pass's measured layer-page set is exactly those pages:

| | layer pages touched | histogram (page touches over 10 passes) |
| --- | --- | --- |
| P24 order | 7: 3,4,5,6,7,8,9 | p3:460 p4:450 p5:790 p6:930 p7:900 p8:1610 p9:10 |
| reordered | 5: 3,4,5,6,7 | p3:460 p4:760 p5:2010 p6:1020 p7:900 |

(Pages 0–2 — system variables, primitive headers, the compiled prelude — carry 3420 of the 8570 traced
accesses in both builds and are treated as resident, exactly as P24/P22's resident split does.)

**Q: Does pinning get it to 0 faults?**
**No, and it never can while the block is 5 pages.** k = 1, 2 pin pages the loop *also* needs unpinned, so
they make it worse (16, 18 faults/pass); k = 3 is the best pinned configuration at **10 faults/pass**, and
it spends three of four frames, leaving one for the two pages they do not cover — so the loop evicts on
every pass. The failure criterion "pinning 3 frames is needed" therefore fires *and* the pin does not
work: 1 frame left for data is not viable, and 3 pinned frames still do not hold the working set.

**Q: How far from fitting is it?**
**44 B.** The block is 2092 B against a 2048 B four-page budget. The bound is measured, not argued: the
same trace simulated with **5 frames** gives **first pass 5, last pass 0** faults, i.e. the loop's
working set is exactly one page larger than the frame budget and nothing else about it thrashes. The P24
order needs 7 frames to reach the same state (5 frames: 8 faults/pass, 6 frames: still 7 pages of reach).

**Q: Is the reorder really order-only?**
**Yes, three ways.** (a) `reorder.py` parses each source into whole definitions and asserts the multiset of
definition texts is identical before and after — 80 in, 80 out, `identical text: True`. (b) The two images
are the same size to the byte: 5540 B, 80 layer definitions, 3812 B of code fields + bodies. (c) The
engine's own access counts for each workload are **equal**: idle 8570 = 8570, line 5580 = 5580, compile
23895 = 23895. A layout rule that changed behaviour would show up as a different trace length or a
different dictionary; neither happened, so there is no compiler bug to report here.

**Q: What does the reorder cost the other two workloads?**
The three-OS-word line **loses**: 6 layer pages → 8 (12 faults/pass unpinned vs 5), because in the
reordered dictionary `TASKS`/`.S`/`T` sit after the hot block instead of interleaved with it; pinning the
hot pages claws it back to 7. Compiling a definition is **neutral**: 9 pages and identical fault counts
in both orders (43 / 38 / 33 / 28 for k = 0..3), because the compiler's working set is the boot prelude
plus the page `HERE` points at, and the reorder did not move either.

### 1.1 What the instrument does (`uforth.c`, host-only, `#ifdef HOST`)

* `touch(a)` records `a / 512` into a fixed 200 000-entry buffer. It is called from **`P()`** (every data
  cell access) **and from `rd32_paged()`/`rd8_paged()`** — the instruction stream. That split is the whole
  probe: P24 counted the pages a definition *occupies*; this counts the pages each dispatch *touches*.
* The page-in refill copy is masked out (`tr_hold`): 256 `rd8`s per fault would otherwise dominate the
  trace (109 424 of a 178 276-touch pass was refill, not the loop).
* A driver resolves the layer's xts and calls `run()` directly: `TASK` + `YIELD` to file a task into `CUR`,
  then per pass `EMIT-EVENT ×3` (tick, gpio, key — **untraced**, the ring is filled before the pass
  starts), `POLL-EVENTS`, `10 SLEEP-TICKS`. `-w line` is `10 SLEEP-TICKS TASKS .S`, `-w compile` is
  `: FOO 1 2 + ;` through `interpret()`. No driver word is compiled into the dictionary, so the layer is
  untouched.
* `measure2.py` walks the dumped image (header chain → per-definition page spans) and runs the LRU.

### 1.2 Measured vs P24's analytic numbers

P24 counted distinct pages per working set and applied "> 4 pages ⇒ thrash" analytically, giving
6 / 8 / 3 and 6 / 8 / 3 faults. The trace counts *every dispatch's* page, so the absolute fault counts are
larger (13 instead of 6 for the idle loop) and include the layer's *data* cells on the same terms as its
code. The two agree on the shape — the idle loop is over the frame budget and never warms, compiling is
the cheapest workload per pass — and the before/after comparison in this probe uses one method throughout.

### 1.3 Re-validation of P24's and P26's fault counts (the tracer bug)

The prompt for this retry asserted that P24's 6/6 and P26's 3/0 were taken with the same tracer. They
were not — **neither used a tracer at all.** P24's `measure.py` and P26's `measure.py` both compute the
set of pages the *named definitions occupy* (`cf // 512 … end // 512`) and apply "> 4 pages ⇒ thrash"
by hand. That is the same *class* of error as the broken tracer (it counts placement, not accesses), so
the re-validation is still needed; but the "same buggy tracer" framing is wrong and the numbers below
say what each method actually gives.

One instrument, one workload, three methods — idle loop, 10 passes, 512 B pages, 4 frames, one
continuous LRU:

| Layer | analytic (as published) | buggy tracer (data only) | **fixed tracer** |
| --- | --- | --- | --- |
| P24 order | 6 pages ⇒ 6 faults/pass | **4 pages, 900 touches, 0 faults/pass** | **7 pages, 8570 touches, 13 faults/pass** |
| P26 minimal | 3 pages ⇒ 3 first / 0 pass | 2 pages, 200 touches, 0 faults/pass | **2 pages, 2510 touches, 0 faults/pass** |

**The bug's size: 3 pages and 13 faults/pass on P24, and a verdict flip.** With instruction fetches
untraced the P24-order loop looks like a **4-page, fault-free** working set — it would have passed R3 at
4 frames. The missing fetches are `HERE`/`STATE` and the header chain on page 0 (2400 of 8570 accesses)
plus the whole dispatch stream: `POLL-EVENTS`' own page showed **zero** touches while being executed ten
times. 90 % of the trace (7670 of 8570 accesses) was instruction fetch. P24's *published* number (6
pages / 6 faults) is conservative rather than wrong — it undercounted pages by one and faults by half,
but its verdict ("thrashes, redesign trigger") is what the fixed tracer also says. **No P24 conclusion
changes; the size of the error is 1 page and 7 faults/pass.**

**P26's "0 faults/pass" survives the fixed tracer — plainly.** Its idle loop's layer footprint is
**2 pages (3, 4)**, first pass **2 faults**, steady state **0 faults/pass** at 4 frames, and no pinned
frame. It is the *only* one of the two layers that warms. Two qualifications, both measured:

* **2 pages, not 3.** Its own table said 3 pages because it counted a page the `SLOTS`/`RING`
  data span reaches but the loop does not touch. The published number was one page *pessimistic*.
* **41 % of the loop's accesses land on pages 0–2** (p0: 770, p1: 10, p2: 250 of 2510) — the system
  variables, primitive headers and compiled prelude, treated as resident by P22/P24/P25 alike. P24's
  layer is 40 % resident (3420 of 8570), so the convention is applied equally and the comparison is
  like-for-like: **P26 is 0 faults/pass and P24 is 13 under the same rule.** If pages 0–2 were paged
  too, P26 would be 5 pages and thrash as well; the probe's own position (§2.1's `MINPAGE = 3`) is that
  the resident split is a design claim P22 made, not something P25 can re-open.

| | layer pages | total pages incl. resident | touches/pass | faults/pass |
| --- | --- | --- | --- | --- |
| P24 order | 7 | 10 | 857 | **13** |
| P26 minimal | 2 | 5 | 251 | **0** |

P26 also does **3.4× fewer dictionary accesses per idle pass** (251 vs 857) for the same work — three
events posted, ring drained, switch, sleep check — which is the byte cut showing up as work.

---

## 2. Evidence

### 2.1 Commands (all under `timeout 30`, host only, nothing outside this directory)

```
gcc -DHOST -DMEMSZ=8192 -O1 -std=c99 -Wall -Wextra -o uforth_p25 uforth.c
gcc -DHOST -DMEMSZ=8192 -DP25_BUG_TRACER -O1 -std=c99 -o uforth_p25_bug uforth.c   # rebuilds the broken tracer
python3 reorder.py                                   # os_hot.fs (53 defs) + os_cold.fs (27 defs); text-identical
./uforth_p25 boot_min.fs os_tasks.fs os_events.fs os_repl.fs os_introspect.fs os_device.fs \
             -d img_base.h                           # image: 5540 bytes   ← P24 order
./uforth_p25 boot_min.fs os_hot.fs os_cold.fs -d img_hot.h   # image: 5540 bytes   ← reordered
./uforth_p25 <files> -w idle    -t tr_idle_before.bin -n 10   # 8570 page touches
./uforth_p25 <files> -w line    -t tr_line_before.bin -n 10   # 5580
./uforth_p25 <files> -w compile -t tr_compile_before.bin -n 10 # 23895
./uforth_p25 boot26.fs p26_*.fs -d img_p26.h                 # image: 2940 bytes   ← P26 minimal layer
./uforth_p25     boot26.fs p26_*.fs -w idle26 -t tr_idle_p26_fixed.bin -n 10  # 2510
./uforth_p25_bug boot26.fs p26_*.fs -w idle26 -t tr_idle_p26_buggy.bin -n 10  # 200
./uforth_p25_bug <P24 files>       -w idle   -t tr_idle_p24_buggy.bin -n 10  # 900
./uforth_p25     <P24 files>       -w idle   -t tr_idle_p24_fixed.bin -n 10  # 8570
python3 measure2.py reval                            # §1.3: fixed-vs-buggy, both layers
python3 measure2.py                                  # histograms + LRU + pinned sweep
```

### 2.2 The idle block, page by page (reordered build)

`VARIABLE ALLOT CELLS TASK-SZ T>NEXT … GPIOXT` (data, 41 definitions) occupy 1716–2704 B = pages 3, 4, 5;
the code `EV! … SLEEP-TICKS` occupies 2704–3808 B = pages 5, 6, 7. The pass's touches per page per pass
(10 passes): p3 46, p4 76, p5 201, p6 102, p7 90 — the loop's weight is in the event ring and the
`WAKE-ALL`/`POLL-EVENTS` dispatch, both of which servo the *variables* on pages 4 and 5, so the code and
the data it servos have to be in the same four pages, not just adjacent ones.

### 2.3 Why 2092 B, not 2048 B

The block is 53 definitions: 20 `CONSTANT`s (16 B each), 15 variables/records (16–140 B; `TASK-POOL` 128 B,
`EV-RING` 96 B), and 18 colon words (30–312 B; `POLL-EVENTS` is 312 B, `WAKE-MASK` 156 B). The constants
alone are 320 B of the block. Nothing here is padding the layout rule could recover: the byte cost of the
rule is 0, and the block's size is P24's, not the reorder's.

### 2.4 What was not measured / what went wrong

* No target build (host only, as required).
* Four tracer bugs, each of which produced a plausible wrong answer first — they are the reason the
  run overran, and they are recorded as GUARDRAILs in `uforth.c` and `reorder.py`:
  page-in refill counted as 256 touches (hid the loop's real footprint); the driver's own `find()`
  counted as layer work (page 0, 9, 10 appeared in a loop that never runs on them); `tr_on` cleared
  *after* the lookup instead of before; and `rd32_paged()` not traced at all, so the entire dispatch
  stream was invisible and `POLL-EVENTS`' page showed **zero** touches while being executed 10 times.
* Per-pass fault counts must come from one continuous LRU: simulating each pass from empty frames reports
  compulsory faults only and made "5 faults/pass" look like "needs 5 frames" when the steady state at
  5 frames is 0 and at 4 frames is 14.
* **The fourth bug's size is now measured, not asserted (§1.3):** `-DP25_BUG_TRACER` rebuilds the
  data-only tracer and gives **4 pages / 0 faults/pass** on the P24-order idle loop where the fixed one
  gives **7 / 13** — 90 % of the trace is instruction fetch, and the bug inverts the R3 verdict. Any
  probe that reports "N pages, 0 faults" from a placement count (P24, P26) must be re-run on a trace
  before its 0 is believed.

---

## 3. Verdict

**The layout rule works and is not enough.** **Both layers re-measured on the fixed tracer before the layout question was answered**, because the
prior numbers were placement counts and one of them was taken with an instrument that missed instruction
fetch entirely:

* **P24's verdict holds, its numbers do not.** 6 pages / 6 faults (analytic) is really **7 pages / 13
  faults/pass**; still thrash, still the §12 redesign trigger. The broken tracer would have said **4
  pages / 0 faults** — a *pass* for R3. That is the size of the error: 3 pages and 13 faults/pass, and
  the difference between "R3 fails" and "R3 passes".
* **P26's "0 faults/pass" survives** — **2 pages, first pass 2, steady state 0** at 4 frames, no pinned
  frame, 41 % of its accesses on the same resident pages 0–2 that P24's loop also assumes (40 %). It is
  the only layer of the two that warms. Its published "3 pages / 3 first-pass faults" was one page
  pessimistic.

Against the probe's criteria:

* *Reordering measured, histogram before and after* — **met** (§1, 7 → 5 pages).
* *At least one configuration reaching 0 faults/pass on the idle loop* — **not met.** Best is 10 faults/pass
  at 3 pinned frames; unpinned is 14.
* *The other two workloads measured in the same configuration* — **met** (table above; the line loses
  6 → 8 pages, compiling is unchanged).
* *Byte cost stated* — **met: 0 B**, `HERE = 5540` in both orders.
* Failure criterion **"idle loop still ≥ 3 pages after reordering"** — **fires** (5 pages). The probe's
  reading is that layout cannot fix the loop and R3 depends on P26's minimal layer. The measurement adds
  the size of that dependency: **44 B**, and it is 44 B of *idle-path* bytes, because with one more frame
  the reordered loop is 0 faults/pass while the P24 order still faults (8/pass at 5 frames, 4/pass at 6,
0 only at 7 — it has 7 pages of reach).
* Failure criterion **"pinning 3 frames is needed"** — **fires and does not help**: it is 10 faults/pass,
  not 0, and it leaves one frame for data. Pinning is not a design option at 5 pages.
* Failure criterion **"reordering breaks a test"** — **does not fire.** Same 80 definitions, same bytes,
  same touch counts on all three workloads. No compiler bug.

The shape of the answer: **contiguity is necessary and pinning is a red herring.** A hot-block rule that
merely *groups* the idle path buys 2 of the 2–3 pages it was hoped to buy, but the group is 4.09 pages
wide, so it still lands on 5. The rule that matters is a *budget*: the idle path must be ≤ 2048 B including
the variables it servos, and then it needs no pinned frames at all — LRU warms to 0 within one pass.

---

## 4. Doc deltas (verbatim, `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §6.1 — the layout rule and the measured faults/pass

> **Measured (P25).** Placing the idle path's definitions contiguously — data first (`TASK-SZ`, the record
> offsets, the states, `TASK-POOL`, the run-queue, the tick, the event ring and its six variables), then
> `EV!`, `T-STATE!`, `NEXT-TASK`, `TICK+`, `WAKE-1`, `WAKE-ALL`, `YIELD`, `WAKE-MASK`, `EV-GPIO-DO`,
> `POLL-EVENTS`, `PAUSE`, `SLEEP-TICKS` — is **53 definitions in 2092 B**, i.e. **4.09 pages of 512 B**,
> and it costs **0 B**: both the P24 order and the reordered dictionary end at `HERE = 5540` with the same
> 80 definitions and the same per-definition text. Measured on the engine's own page-touch trace, the
> idle loop's layer footprint falls from **7 pages to 5** (histogram before `p3:460 p4:450 p5:790 p6:930
> p7:900 p8:1610 p9:10`, after `p3:460 p4:760 p5:2010 p6:1020 p7:900`) but its faults/pass at 4 frames do
> not improve: **13 → 14**. Pinning 1, 2, 3 frames gives **16, 18, 10** faults/pass, so no pinned
> configuration reaches 0. The rule is only useful with a **budget**: the block must be ≤ 2048 B, and at
> **5 frames the reordered loop is 0 faults/pass steady state** while the P24 order still faults (8/pass
> at 5 frames, 4/pass at 6, 0 only at 7).

### 4.2 `docs/01-proposal.md` §4.2 — a rule if pinning becomes part of the design

> **Do not pin the hot block (P25).** Pinning is measured to be *worse* than leaving the frames to LRU
> until the pinned set covers the whole working set: with the idle block at 5 pages, pinning 1 / 2 / 3
> frames gives 16 / 18 / 10 faults/pass against 14 unpinned (idle loop, 4 × 512 B frames, 512 B pages).
> A pinned frame is a frame the rest of the loop cannot use, so a partial pin converts one thrashing
> loop into a thrashing loop with fewer frames. The rule that survives is **fit, then do not pin**: when
> the idle path is ≤ 4 pages it needs no frames at all (LRU warms in one pass), and when it is > 4 pages
> pinning cannot rescue it. If a permanent pinned block is ever adopted, its cost is exactly this: k
> frames removed from every other workload — measured on the same traces, pinning 3 frames also moves
> compiling a definition from 43 to 28 faults/pass (it happens to help there) and the three-OS-word line
> from 12 to 7 — and the *other* pages of the pinned block, or any task that calls the pinned words, are
> outside the pin and still fault.

### 4.3 `docs/01-proposal.md` §10 — R3 restated with measured faults

> **R3 — event loop.** Measured (P24 analytically, P25 on the engine's page-touch trace with a 4-frame
> LRU): the idle event loop's working set is **7 pages of 512 B in the P24 order and 5 pages after
> reordering the layer so the idle path is contiguous**. Steady state is **13 faults/pass before, 14
> after** — the loop does not warm at 4 frames in either order. Pinning 1–3 frames does not reach 0
> (16 / 18 / 10 faults/pass). The idle block is **2092 B = 4.09 pages, 44 B over the four-page budget**;
> at 5 frames the reordered loop is **0 faults/pass**, so the remaining gap is 44 B of idle-path bytes and
> not a placement problem. **R3 therefore depends on P26 cutting ≥ 44 B from the idle path** (or on a
> per-task record and ring that live in the same four pages as the words that servo them); layout alone
> is measured insufficient. **Redesign trigger (§12) still stands.**

### 4.4 `docs/01-proposal.md` §10 — a correction to P24's and P26's fault counts (amend 4.3)

> **Correction (P25, re-validation).** The idle-loop page counts in P24 (6 pages, 6 faults/pass) and
> P26 (3 pages, 3 first-pass faults, 0 steady state) were both **analytic**: they count the distinct
> pages the named definitions *occupy* and apply "> 4 pages ⇒ thrash". Re-run on the engine's own
> page-touch trace — every instruction fetch through `resolve()` and every data cell through `P()`, one
> continuous 4-frame LRU — P24's layer is **7 pages, first pass 14, 13 faults/pass**, and P26's is **2
> pages, first pass 2, 0 faults/pass**. So: **P26's 0 faults/pass holds and P24's thrash holds**; the
> published page counts are off by 1 in each case (P24 low, P26 high) and the published P24 fault count
> is off by 2× (6 → 13). This matters because the first version of that tracer hooked only `P()` — a hit
> reads the frame copy through `resolve()`, so instruction fetch was invisible and P24's loop measured
> **4 pages / 0 faults**, i.e. a *pass*. Any page count in these reports that is not from an LRU run
> over a trace covering both fetch and data is a placement count, not a working set.

### 4.5 `probe/EVIDENCE.md` — new entry
> ### E-0xx — contiguity wins 2 pages, pinning wins nothing (P25)
>
> **Instrument first.** P24 (6 pages / 6 faults) and P26 (3 pages / 0 faults) were analytic placement
> counts; re-run on one page-touch trace (all instruction fetch through `resolve()`, all data through
> `P()`, one continuous 4-frame LRU): **P24 = 7 pages / 13 faults/pass** and **P26 = 2 pages / 0
> faults/pass**. The data-only tracer that missed instruction fetch (90 % of the trace) gave **4 pages /
> 0 faults/pass** on P24's loop — a false pass for R3.
>
> The P24 OS layer re-emitted with the idle path contiguous (event poll → dispatch → task switch → sleep
> check) — **53 definitions, 2092 B, 0 B of layout cost**, 80 definitions and `HERE = 5540` before and
> after, per-definition text identical, and identical page-touch counts per workload (idle 8570, line
> 5580, compile 23895), so the change is placement only. The idle loop's layer footprint falls **7 → 5
> pages** (histogram `p3:460 p4:450 p5:790 p6:930 p7:900 p8:1610 p9:10` → `p3:460 p4:760 p5:2010 p6:1020
> p7:900`), faults/pass at 4 × 512 B **13 → 14 unpinned**, **16 / 18 / 10 with 1 / 2 / 3 frames pinned**:
> **no configuration reaches 0**. The block is **4.09 pages (44 B over budget)**; with 5 frames the
> reordered loop is **0 faults/pass** while the P24 order still faults (8/pass at 5 frames, 4 at 6, 0
> only at 7). The three-OS-word line gets *worse* with the reorder (6 → 8 pages, 5 → 12 faults/pass,
> 7 when the hot pages are pinned); compiling a definition is unchanged (9 pages, 43 faults/pass).

---

## 5. Follow-ups

1. **Give the idle path a byte budget, not a block.** P26's target is now exact: **≤ 2048 B including the
   variables it servos** (currently 2092 B; `POLL-EVENTS` alone is 312 B and `WAKE-MASK` 156 B). Cutting
   44 B closes R3 at 4 frames — verify by re-running `-w idle` on the P25 driver, where 5 frames already
   gives 0 faults/pass.
2. **Move the event ring and the run-queue *into* the block deliberately.** The reorder sorted
   definitions; the trace says the loop's heaviest pages are the rings and the task pool (p5: 201
   touches/pass). A block whose *data* is at its end and whose code is at its start splits across pages
   5–7 for no reason; put the two rings and the 4-task pool last, the words first, and re-measure.
3. **Do not adopt pinning** unless a block is already ≤ 3 pages; the measurement says a partial pin is a
   net loss (§4.2).
4. **Re-run the line workload after the P26 cut.** It is the workload the reorder *hurt* (6 → 8 pages),
   and it is the one a user actually types.
5. **Fold the tracer into the harness.** `uforth.c`'s `-w/-t` driver is 60 lines and gives page-touch
   traces for every future layout question; P03f's simulator can consume the same trace and would add
   dirty write-back and a cost model (144 µs/fetch) instead of a bare fault count.
6. **P26's layer is the one that already answers this probe's question.** On the same trace and workload
   it is **2 pages / 0 faults/pass at 4 frames, no pinned frames** — so the 44 B is not a hypothesis: the
   P26 idle path (1224 B headerless for the whole layer) already warms. Adopt P26's idle-path shape rather
   than cutting 44 B out of P24's, and re-run `-w idle` on P24's driver as the acceptance test.

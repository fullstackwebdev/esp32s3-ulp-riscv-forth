# P03f — 4 × 256 B does not kill the three-page livelock: it kills the prelude first

**Verdict: FAIL.** The two-constant change (512 → 256, and the frame count to 4) does **not** stop the
livelock. It makes it *earlier and worse*: at **4 × 256 B the harness cannot compile `boot_min.fs`**.
The fault-free baseline of the measured workload never starts —
`ERR_RETRY_CAP in feed ti=20 addr=764`, **390 faults**, `CASE-ERR: prelude failed at 4 frames`,
`positions=0, tested=0, mismatches=not-measured`. The three-address cycle is still there and still
needs **three distinct pages** (`508` → page 1, `764` → page 2, `1024` → page 4 at 256 B); halving the
page size did not shrink the working set, it *moved the prelude into a page-straddling regime* where
the same dispatch needs three pages instead of two.

The RMW workload (P03e's `+!`) is therefore **unreachable** at 4 × 256 — it dies in the same prelude,
12 tokens into the file. The one measurement this probe was built to make is not available, and the
answer is structural, not noisy: same fault stream shape, same one-page-per-retry ratio, one level
higher in the boot sequence.

Host-only, gcc, one source tree, four configurations (4 × 256, 2 × 512, 4 × 512 control, plus the RMW
build of each). Nothing outside `probe/results/P03f-frames-4x256/` was written; `docs/`, `probe/uforth/`,
the P03b/P03c/P03d/P03e directories and the board were never touched. Every command ran under
`timeout 30`; every run redirected to a log, never piped through `head`.

---

## 1. Question, verdict, and what is established

| Item | Value |
| --- | --- |
| question | does a 4 × 256 B frame budget (1024 B) break the three-page livelock that 4 × 512 B hits? |
| **verdict** | **FAIL** — 4 × 256 B cannot run the prelude, so it cannot run the sweep or the RMW step |
| fault-free baseline (4 × 256) | **invalid**: `ERR_RETRY_CAP` inside `feed()`, `ti=20`, `addr=764`, 390 faults, `chk=00000000` |
| RMW workload (4 × 256) | **does not complete, and is not reached**: same `ERR_RETRY_CAP`, `ti=12`, `addr=1024`, 202 faults |
| mismatches over the sweep (4 × 256) | **not measured** — 0 positions entered (`tested=0`) |
| distinct pages in the worst cycle | **3** — `{508, 764, 1024}` = pages 1, 2, 4 (256 B pages) |
| constant drift found in the harness | `flash_page()` hardcoded `>> 9`; at 256 B that makes two page numbers per address (§4.1). Fixed before any run was scored |
| frame RAM actually compared | P03d/P03e ran **4 × 512 = 2048 B**, not "2 × 512". The equal-RAM control (1024 B) is therefore **2 × 512**, built and run here as the P03f counterpart (§2) |

What is established, and it is enough to settle §4.3: **the constraint is the number of pages a
dispatch touches, and smaller pages increase it.** 4 × 256 B is not a smaller version of 4 × 512 B in
page-count terms — the dictionary now spans twice as many pages, so a token fetch, its inline operand,
and a dictionary cell that used to share two pages now need three, against an evictable set of
`frames − pin_cap(2) = 2`. The cycle is reproduced before the workload ever runs.

## 2. The measurement (verbatim)

### 2.1 4 × 256 B — the configuration the brief asked for (`run.log`, `faults-4x256.log`)

```
# P03b retry progress: page=256 B, frames=4, workload=WORK, wake=64 dispatches

## baseline
ERR_RETRY_CAP in feed ti=20 addr=764 perm=0
CASE-ERR: prelude failed at 4 frames err=ERR_RETRY_CAP
baseline frames=4 disp=0 faults=390 loads=390 writebacks=2 sp=0 rsp=0 ds0=0 chk=00000000 out=00000000 err=ERR_UNKNOWN
BLOCKED: baseline broken err=ERR_UNKNOWN chk=00000000 (no sweep attempted)

SUMMARY baseline_valid=no positions=0 tested=0 mismatches=not-measured loop_bound=not-measured
```

`faults-4x256.log`, 390 faults, three addresses and nothing else:

```
     68 addr=764      page 2, offset 252
     67 addr=508      page 1, offset 252
     67 addr=1024     page 4, offset 0
      1 addr=768 / 65280 / 65024 …   (the prelude's earlier, converging faults)
```

`loads=390` for `faults=390` — one page load per retry, zero forward progress, the exact signature
P03e recorded at 512 B.

### 2.2 The equal-RAM control, 2 × 512 B, same source (`run-2x512.log`, `faults-2x512.log`)

```
ERR_RETRY_CAP in feed ti=19 addr=1010 perm=0
CASE-ERR: prelude failed at 2 frames err=ERR_RETRY_CAP
SUMMARY baseline_valid=no positions=0 tested=0 mismatches=not-measured loop_bound=not-measured
```

```
    100 addr=1024     page 2, offset 0
    100 addr=1010     page 1, offset 498
```

So the equal-RAM layout does not boot either, with a **2-page** cycle — 2 frames minus the single pin
(`pin_cap = frames >= 4 ? 2 : 1`) leaves one evictable frame for two alternating pages. This is the
number the brief's "2 × 512" column wanted: it is not a working layout to regress from.

### 2.3 The 4 × 512 B control — the harness still reproduces P03d bit-for-bit (`run-4x512-check.log`)

```
baseline frames=4 disp=187 faults=15 loads=15 writebacks=12 sp=1 rsp=0 ds0=4 chk=4f99db40 out=811c9dc5 err=OK
loop_bound=resolved err=ERR_PAGE_FAULT_LOOP at pos=1
sweep: positions=187 tested=187 injected_fired=83 no_access=104 skipped=0 mismatches=0 faults=2793 retries=2876 forced_evicts=20 resume_mismatch=1768
SUMMARY baseline_valid=yes frames=4 workload=WORK positions=187 tested=187 mismatches=0 hangs=0 loop_bound=ERR_PAGE_FAULT_LOOP elapsed=0.2s
```

`chk=4f99db40`, `disp=187`, `positions=187`, `mismatches=0` — identical to P03d's `run.log`. That
is what licenses the §4.1 `PAGE_SHIFT` edit: at 512 B it is a pure no-op, proven by digest, not argued.

### 2.4 The RMW workload (P03e's `+!`) at both layouts (`rmw/run-rmw-4x256.log`, `rmw/run-rmw-4x512.log`)

```
4 x 256:  ERR_RETRY_CAP in feed ti=12 addr=1024 perm=0
          CASE-ERR: prelude failed at 4 frames err=ERR_RETRY_CAP
          baseline frames=4 faults=202 loads=202 writebacks=2 err=ERR_UNKNOWN  (prelude, not WORK)
          cycle: 1024 x68, 748 x67, 508 x66  -> pages 4, 2, 1

4 x 512:  ERR_RETRY_CAP w=602 ip=1500 p=2 addr=1500 retries=302
          baseline frames=4 disp=1788 faults=302 loads=301 writebacks=75 sp=2 rsp=2 ds0=1 chk=bfbd1e73
          cycle: 602 x67, 537397248 x67, 1500 x67  -> pages 2, 1028, 1
```

The 4 × 512 RMW line reproduces P03e's `run.log` exactly (`chk=bfbd1e73`, `retries=302`,
`loads=301`), so the RMW build is the same specimen and the 4 × 256 RMW result is attributable to the
page size alone.

### 2.5 Faults per workload, both layouts

| workload | 4 × 512 B (2048 B RAM) | 4 × 256 B (1024 B RAM) | 2 × 512 B (1024 B RAM) |
| --- | --- | --- | --- |
| P03d `WORK` (no RMW), fault-free | **15** faults / 15 loads / 12 writebacks, `disp=187` | not reached — prelude `ERR_RETRY_CAP` after **390** faults | not reached — prelude `ERR_RETRY_CAP` after **200** faults |
| P03d `WORK`, whole sweep | **2793** faults / 2876 retries over 187 positions, 0 mismatches | not measured (0 positions) | not measured (0 positions) |
| P03e RMW workload | **302** faults / 301 loads → `ERR_RETRY_CAP`, 0 progress | not reached — prelude `ERR_RETRY_CAP` after **202** faults | not reached |
| distinct pages in the cycle | **3** (`1, 2, 1028` for RMW; `1, 2` for `WORK`) | **3** (`1, 2, 4`) | **2** (`1, 2`) |

The trade the brief wanted quantified — "more faults, each moving half the data" — is **not what
happens**. Faults do not rise gently; the layout stops booting. The cost of 256 B pages is not
double faults, it is a page-capacity failure in the prelude, because the *page count* a dispatch spans
grows while the frame count stays at 4.

## 3. Why, precisely

`service_fault()` picks the LRU victim with pinned dictionary pages excluded, and `pin_cap` is 2 at
four frames. A faulting dispatch restarts from its **entry checkpoint**, so the pages it needs must be
co-resident *at the moment it runs*, not merely sequentially reachable:

* at 256 B, `boot_min.fs`'s definitions sit at offsets near page ends. The token fetch at `508`
  (page 1, offset 252) and the inline operand at `764` (page 2, offset 252) are code pages and both
  get pinned; the dictionary cell at `1024` (page 4) is the third page and has no frame left that can
  hold it while a retry is in flight.
* 4 frames − 2 pins = 2 evictable frames < 3 pages in the working set ⇒ each retry loads exactly the
  page the previous load evicted. `faults == loads`, 390 times.
* `ERR_PAGE_FAULT_LOOP` cannot fire: its key is `(w, ip, p)` and the cycle alternates between
  `ip=20` windows with different `p`. The run ends on `RETRY_CAP`, named and bounded — as designed.
* 2 × 512 B fails for the same reason with a smaller set: 2 frames − 1 pin = 1 evictable frame for
  two pages (`1010`, `1024`).

The P03e conclusion therefore stands and is now stronger: **N + 1 frames where N is the number of
pages one dispatch touches**, and at 256 B the prelude already needs N = 3. 1024 B of frame RAM in
four 256 B slots cannot hold a machine that boots.

## 4. Harness: what was reused, and the edits

Copied **verbatim** from `probe/results/P03d-checkpoint-fix/` (`paging_sim.c`, `uforth.c`,
`boot_min.fs`); nothing in the retry driver (`run()`, `service_fault()`, `ckpt_save`, window ids) was
touched. The RMW variant is P03e's `paging_sim.c` + `uforth.c` (the `+!` primitive and the `RMW` word),
also otherwise untouched, copied into `rmw/` because `paging_sim.c` `#include`s `uforth.c` from its own
directory.

Build (unchanged): `gcc -DHOST -DPAGING -std=c99 -O1 -Wall -Wextra -o paging_sim paging_sim.c` — the
same three pre-existing warnings (`load` unused, two `-Wclobbered`), none new (`build.log`).

### 4.1 `paging_sim.c` — three edits, one of them forced

| edit | why it is not optional |
| --- | --- |
| `PAGE_SIZE 512 → 256` | the probe |
| `PAGE_SHIFT` added, `flash_page()` `>> 9` → `>> PAGE_SHIFT` | **`PAGE_SIZE` was not the only place the page geometry appeared.** With the shift left at 9, `2046` and `2048` both mapped to page 4 while their frame offsets were 254 and 0 — two different page numbers for one address. The first attempt at 4 × 256 livelocked on `2046/2048/12342` for 217 retries because of *that*, not because of capacity, and would have been reported as a false FAIL. `PAGE_SHIFT = 9` reproduces P03d bit-for-bit (§2.3), so the edit changes nothing at 512 B |
| `TEST_FRAMES` left at 4 | the brief's "frames 2 → 4" does not apply: P03d and P03e both ran `TEST_FRAMES=4` (their `run.log` headers say `frames=4`). The frame count was already 4; there was nothing to raise |

The two-constant framing in the brief was therefore **two-thirds right**: one constant had to change,
one was already 4, and a third site (`>> 9`) had to be parameterised for the change to mean anything.

### 4.2 Variants built from that one source (no second edit of the working tree)

```
paging_sim-4x512-check.c   PAGE_SIZE 512, PAGE_SHIFT 9, TEST_FRAMES 4   -> control (§2.3)
paging_sim-2x512.c         PAGE_SIZE 512, PAGE_SHIFT 9, TEST_FRAMES 2   -> equal-RAM control (§2.2)
rmw/paging_sim-rmw-4x256.c PAGE_SIZE 256, PAGE_SHIFT 8, TEST_FRAMES 4   -> RMW at the probe layout
rmw/paging_sim-rmw-4x512.c PAGE_SIZE 512, PAGE_SHIFT 9, TEST_FRAMES 4   -> P03e reproduction
```

Generated by `sed` from the edited source, recorded here because the constants are the experiment.

## 5. Doc deltas (not applied) and the next step

### `docs/01-proposal.md` §4.3 — the frame layout

The 4 × 256 B row of the layout table is **dead**: it cannot compile the prelude. Replace the
candidate description with a confirmed one:

> **Frame layout: 4 frames × 512 B = 2048 B, page size 512 B.** Confirmed by P03d (sweep clean, 187
> positions, 15 baseline faults) and bounded by P03f: the layout is the *minimum* that boots —
> 2 frames × 512 B livelocks inside `boot_min.fs` (`ERR_RETRY_CAP`, cycle `1010/1024`, 200 faults)
> and 4 × 256 B livelocks there too (`ERR_RETRY_CAP`, cycle `508/764/1024`, 390 faults). Halving the
> page to keep 1024 B of frames does not preserve the working set: the dictionary spans twice as many
> pages, so the three pages a dispatch touches at 512 B become three *differently placed* pages that
> the 2 evictable frames cannot hold.

### `docs/01-proposal.md` §4.2 rule 2 — the frame-capacity sentence, with the measured N

> A primitive that touches more than one page inside one dispatch must be able to hold them all in
> the frame budget: the resume point is the **dispatch entry**, so a page evicted by one retry's load
> is re-faulted by the next step of the same dispatch and the retry can thrash indefinitely
> (`ERR_RETRY_CAP`, never a hang). Measured N at 512 B pages: **3** — a token page, an inline-operand
> page and a data page (P03e, `602` / `1500` / `537397248`, 302 retries, one load per retry), and
> 3 already during the prelude at 256 B (P03f, `508` / `764` / `1024`). The requirement is therefore
> **N + 1 frames, N = 3 measured, and N grows when the page size shrinks** — the frame budget cannot
> be reduced by shrinking pages. Pinning (`pin_cap = min(2, frames/2)`) eats two of the frames, so the
> evictable set is `frames − 2`; at 4 frames that is 2, which is why N = 3 does not fit.

### `probe/EVIDENCE.md` — extend E-020

> **E-020 (extended, P03f).** The three-page dispatch cycle is a page-capacity limit, not a page-size
> limit. 4 × 256 B (1024 B of frame RAM) does not boot: the prelude's own definitions need three pages
> co-resident (token `508` / inline operand `764` / dictionary cell `1024`) against `4 − pin_cap(2) = 2`
> evictable frames, and the run dies `ERR_RETRY_CAP` after 390 one-load-per-retry faults
> (`run.log`, `faults-4x256.log`). 2 × 512 B (the same 1024 B in two frames) dies the same way with a
> 2-page cycle (`1010`/`1024`, 200 faults). 4 × 512 B is the smallest layout that runs at all:
> 0 mismatches over 187 positions, 15 baseline faults, and the P03e RMW livelock reproduces bit-for-bit
> (`chk=bfbd1e73`, 302 retries). Conclusion for §4.3: budget 2048 B of frames at 512 B pages, or raise
> the frame **count** — do not shrink the page.

**Next step (one paragraph, for the queue):** the two structural unknowns are now one. Do not spend
another probe on page size; 512 B × 4 is the floor and it is already at the floor. The open question is
whether N = 3 is the maximum a dispatch can touch — P03e's `+!` and P03f's prelude both hit 3, and the
P03e audit says no primitive in the measured set needs more, plus `vm_touch` gives multi-byte accesses
a single-page-at-a-time fault granularity. The cheap probe that would close §4.3 is therefore a
*static* one: enumerate, per primitive, the maximum number of distinct pages a single dispatch can
have live at once, and require `frames ≥ N + pin_cap + 1`. If that comes out at 3, 4 × 512 B closes
resolution A with no dictionary give-back. The second-order finding worth one line in §4.2 is the
`ERR_PAGE_FAULT_LOOP` blind spot P03e reported: a two-window cycle inside one dispatch is
indistinguishable from progress, and `RETRY_CAP` is the only backstop.

Artifacts: `run.log` + `faults-4x256.log` (the probe layout, 4 × 256 — prelude livelock),
`run-2x512.log` + `faults-2x512.log` (equal-RAM control), `run-4x512-check.log` (P03d reproduced,
`chk=4f99db40`), `rmw/run-rmw-4x256.log` + `rmw/faults-rmw-4x256.log` (RMW unreachable at 256 B),
`rmw/run-rmw-4x512.log` + `rmw/faults-rmw-4x512.log` (P03e reproduced, `chk=bfbd1e73`, 302 retries),
`build.log` + `rmw/build-*.log` (three pre-existing warnings, none new), `paging_sim.c` + `uforth.c` +
`boot_min.fs` (the harness as built), `paging_sim` / `paging_sim-2x512` / `paging_sim-4x512-check`
(binaries), `paging_sim-4x512-check.c` / `paging_sim-2x512.c` (control sources), `rmw/` (the RMW
variant and its two builds), this file.

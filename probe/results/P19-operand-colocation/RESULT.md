# P19 — Padding so a token and its operand share a page does **not** make N = 2

**Verdict: FAIL.** The co-location rule is implemented, costs almost nothing (**6 B in the prelude,
1 pad, 0.46 % of the dictionary**), and buys **nothing**: N is still **3** in every layout that
reaches the measurement, and the three-page set is still fatal at 1536 B. With the rule in place
**4 × 512 B = 2048 B remains the floor**: `3 × 512` compiles the prelude (N = 3, clean) and then dies
in the workload source (`ERR_RETRY_CAP w=4 addr=1530`, cycle `1530 / 1536 / 1010` = pages 1, 2, 3),
`2 × 512` cannot compile `boot_min.fs`, and `4 × 256` dies in the prelude exactly as it did in P03f
(`ERR_RETRY_CAP ti=12 addr=764`, cycle `508 / 764 / 1026` = pages 1, 2, 4). The RMW workload the
probe was built to rescue is **unchanged bit-for-bit**: at 4 × 512 B with the rule it still ends
`ERR_RETRY_CAP w=602 ip=1500 p=2 addr=1500 retries=302` — P03e's / P03f's exact cycle.

The reason is the failure mode the brief named worst: **the third page is not the operand.**
For `+!` it is the **data** page (`537397248` = page 1028); for the compiling dispatches it is the
page the cell is written to; for the threaded fetch it is the next token's page. No compiler padding
rule can merge a code page with a data page. **Frames stay at 4 × 512 B = 2048 B; §4.3's 512 B has to
come from somewhere else.**

Host-only, gcc, one source tree, eight binaries (four layouts × the WORK harness and the RMW
variant). Nothing outside `probe/results/P19-operand-colocation/` was written; `docs/`, other probe
directories and the board were never touched. Every build and run under `timeout 30`, every run
redirected to its own log, never piped through `head`.

---

## 1. Question, verdict, and what is established

| Item | Value |
| --- | --- |
| question | if the compiler pads so a token and its inline operand never straddle a page, does N drop to **2**, and does 3 × 512 B (1536 B) then sweep clean? |
| **verdict** | **FAIL** — N stays 3; the third page is a data/cell page, not the operand |
| N with the rule, 4 × 512 B | **3** — prelude `{0,1,2}`, workload `{0,3,1}` (pages, 512 B) |
| smallest layout that boots + completes + sweeps clean | **4 × 512 B = 2048 B** (0 mismatches over 187 positions) |
| 3 × 512 B (1536 B) | prelude compiles, **workload source dies** `ERR_RETRY_CAP ti=4 addr=1530`, 201 loads / 203 faults |
| 2 × 512 B (1024 B) | **prelude does not compile** (5 faults, `1010`/`1024`) |
| 4 × 256 B (1024 B) | **prelude does not compile** — same `ERR_RETRY_CAP ti=12 addr=764` as P03f, 393 faults |
| RMW workload, 4 × 512 B, rule on | **still livelocks**: `ERR_RETRY_CAP w=602 ip=1500 p=2 addr=1500 retries=302` (= P03f §2.4) |
| padding cost | **1 pad / 6 B** in the prelude; 6 B by the end of the WORK workload; 12 B for the RMW build — **0.37 – 0.80 % of the dictionary** |

What is established: the P03f conclusion survives the cheapest available fix. A straddle is rare
(P02's 39 B average definition means one pad per ~85 tokens) and the rule removes it for 6 bytes —
but the page count per dispatch was never explained by straddles alone. A dispatch needs its token
page, its operand page **and** the page it reads or stores, and the third one is data.

## 2. The measurement (verbatim)

### 2.1 4 × 512 B with the rule — boots, completes, sweeps clean (`run-4x512.log`)

```
NMAX prelude max=3 at_disp=211 cf=53 pages=0,1,2 hist(1..32):1:76,2:209,3:7 pad_n=1 pad_bytes=6 dict_here=1354
NMAX work max=3 at_disp=323 cf=46 pages=0,3,1 hist(1..32):1:39,2:71,3:22 pad_n=1 pad_bytes=6 dict_here=1662
baseline frames=4 disp=187 faults=15 loads=15 writebacks=12 sp=1 rsp=0 ds0=4 chk=45c502cb out=811c9dc5 err=OK
loop_bound=resolved err=ERR_PAGE_FAULT_LOOP at pos=1
sweep: positions=187 tested=187 injected_fired=83 no_access=104 skipped=0 mismatches=0 faults=2793 retries=2876 forced_evicts=20 resume_mismatch=1768
SUMMARY baseline_valid=yes frames=4 workload=WORK positions=187 tested=187 mismatches=0 hangs=0 loop_bound=ERR_PAGE_FAULT_LOOP elapsed=0.2s
```

`faults=15 / loads=15 / disp=187` are P03d's numbers exactly; the digest moved
(`chk=4f99db40` → `45c502cb`) because the dictionary is 6 B larger — that is the padding, not a
behaviour change. The sweep is clean (0/187) *and* N is still 3.

### 2.2 3 × 512 B — the layout §4.3 wanted (`run-3x512.log`)

```
NMAX prelude max=3 at_disp=211 cf=53 pages=0,1,2 hist(1..32):1:76,2:209,3:7 pad_n=1 pad_bytes=6 dict_here=1354
ERR_RETRY_CAP in feed ti=4 addr=1530 perm=0
CASE-ERR: workload source failed at 3 frames err=ERR_RETRY_CAP
SUMMARY baseline_valid=no positions=0 tested=0 mismatches=not-measured loop_bound=not-measured
```

`faults-3x512.log`, 203 faults, three addresses and nothing else:

```
     67 addr=1536     page 3, offset 0
     67 addr=1530     page 2, offset 506
     66 addr=1010     page 1, offset 498
```

Three code/data pages (`1010`, `1530`, `1536`) against `3 − pin_cap(1) = 2` evictable frames. The
prelude is identical to 4 × 512 B's (same N, same histogram) — the failure moved *later*, into
compiling the workload source, and it is still a three-page cycle.

### 2.3 2 × 512 B and 4 × 256 B — neither boots (`run-2x512.log`, `run-4x256.log`)

```
2 x 512:  CASE-ERR: prelude failed at 2 frames err=OK
          baseline frames=2 disp=0 faults=5 loads=5 writebacks=1 chk=00000000
          cycle: 1024 x3, 1010 x2          -> pages 2, 1

4 x 256:  ERR_RETRY_CAP in feed ti=12 addr=764 perm=0
          CASE-ERR: prelude failed at 4 frames err=ERR_RETRY_CAP
          baseline frames=4 disp=0 faults=393 loads=393 writebacks=3 chk=00000000
          cycle: 764 x68, 508 x67, 1026 x67  -> pages 2, 1, 4
```

4 × 256 B is P03f's prelude failure reproduced under the rule (`ti=12`, `764`), with the third
address moving `1024` → `1026` — the 2 B shift the padding caused. The rule does not change the
shape of the failure at all.

### 2.4 The RMW workload (`rmw/run-rmw-4x512.log`) — the dispatch the rule was supposed to save

```
NMAX prelude max=3 at_disp=25031 cf=23 pages=0,2,1 hist(1..32):1:84,2:79,3:5 pad_n=0 pad_bytes=0 dict_here=1348
ERR_RETRY_CAP w=602 ip=1500 p=2 addr=1500 retries=302
baseline frames=4 disp=1788 faults=302 loads=301 writebacks=75 sp=2 rsp=2 ds0=1 chk=7dfada69
NMAX work max=3 at_disp=25119 cf=46 pages=0,3,1 hist(1..32):1:18,2:33,3:7 pad_n=2 pad_bytes=12 dict_here=1560
```

`retries=302`, `loads=301`, cycle `602` / `1500` / `537397248` — identical to P03e's and P03f's
reproduction except for the digest (12 B of padding). `+!` carries **no inline operand**, so the rule
has nothing to merge for it: the three pages are two code pages and the data page `1028`. RMW at
3 × 512 B dies even earlier (`ERR_RETRY_CAP in feed ti=45 addr=1018` in the workload source).

### 2.5 Per-layout table (the probe's Record section, filled)

| Layout | prelude compiles | RMW completes | sweep mismatches | max N | padding cost |
| --- | --- | --- | --- | --- | --- |
| 3 × 512 | **yes** | no (dies in the workload source, `addr=1530`) | not measured (0 positions) | **3** (`{0,1,2}` prelude) | 6 B / 0.46 % |
| 2 × 512 | **no** (`1010`/`1024`) | no | not measured | not reached | n/a (prelude dies) |
| 4 × 256 | **no** (`508`/`764`/`1026`) | no | not measured | not reached | n/a (prelude dies) |
| 4 × 512 (control) | yes | **no** (`w=602 ip=1500`, 302 retries) | **0 / 187** | **3** (`{0,3,1}` workload) | 6 B / 0.37 % |

Padding cost is `pad_bytes / (here − DICT)`, `DICT = 56`: prelude `6 / (1354−56) = 0.46 %`, end of
the WORK workload `6 / 1606 = 0.37 %`, RMW build `12 / 1504 = 0.80 %`. One pad in the prelude, one
more in the RMW build's workload, **none** in the WORK workload's source.

## 3. Why, precisely

The rule is in the right place and it works: `cw()` is the only place a token is emitted, and one
pad of 6 B kept every `LIT`-style token together with its 4-byte operand for 1354 B of dictionary.
N did not move, so the second page of a dispatch was never the operand:

* **Compile-time dispatches.** `,` / `CONSTANT` / `:` fetch their token from the dictionary (page
  `p`), write `V_HERE` / `V_LATEST` / `V_STATE` (page 0 at 512 B — the variables live at offsets
  0..24, `DICT = 56`), and write the cell they are building (page `p` or `p+1`). Three pages; the
  third is the *cell*, which the compiler chooses and no padding can avoid (the dictionary has to
  grow across pages).
* **Runtime dispatches.** `@`, `!`, `+!` fetch a token (page `p`), read or write a data cell
  (page 1028), and — in the threaded engine as built — fetch the next token inside the same dispatch
  (page `q`). `+!`'s cycle `602` / `1500` / `537397248` is exactly this: two code pages and the data
  page.
* **The capacity arithmetic does not change.** `pin_cap = frames ≥ 4 ? 2 : 1`, so the evictable set
  is `frames − pin_cap`: 2 at four frames, 2 at three, 1 at two. N = 3 needs 3 evictable frames if
  none of the three is pinned; at 3 frames the pin set leaves exactly 2. That is why 3 × 512 B dies
  in the first three-page dispatch of the workload source and 4 × 512 B does not.
* `ERR_PAGE_FAULT_LOOP` cannot fire on the prelude cycles (their key is `(w, ip, p)` and the cycle
  alternates windows), so `RETRY_CAP` is again the only backstop — P03e's blind spot reproduces.

The co-location rule is therefore **correct but insufficient**: it removes the only page-fault
source the compiler controls, and N is set by the page-fault sources it does not control.

## 4. Harness: what was reused, and the edits

Copied **verbatim** from `probe/results/P03f-frames-4x256/` (`paging_sim.c`, `uforth.c`,
`boot_min.fs`, and the `rmw/` variant of each). The retry driver (`run()`, `service_fault()`,
`ckpt_save`), the pinning and the accessors are untouched.

Build: `gcc -DHOST -DPAGING -std=c99 -O1 -Wall -Wextra` — the same three pre-existing warnings
(`load` unused, two `-Wclobbered`), none new (`build-paging_sim-*.log`).

| edit | file | why |
| --- | --- | --- |
| `PAGE_SIZE`/`PAGE_SHIFT` moved **above** `#include "uforth.c"`, `COLO_PAGE = PAGE_SIZE` | `paging_sim.c` | the rule lives in `uforth.c`'s compiler and needs the page geometry; defined after the include it would compile out silently |
| **the rule**: before `wr16(h, v)`, if `PAGE_SIZE − (h & (PAGE_SIZE−1)) < 8`, pad `HERE` up to the page boundary; count pads and bytes | `uforth.c` `cw()` | the probe. Threshold 8, not 2: a 2 B token plus a 4 B literal written as two 2 B cells |
| `n_seen[]`/`n_hist[]` per-dispatch page set: opened at `VM_CKPT_DISPATCH` seeded with the token's page, closed at the next `VM_CKPT_FETCH` **and** at `VM_CKPT_RUNEND` | `paging_sim.c`, `uforth.c` | the N measurement |
| `raise_fault()` discards the open set | `paging_sim.c` | a fault truncates the body and the retry driver's own `write_cell(V_HERE/V_LATEST/V_STATE)` reads would otherwise be charged to the dispatch that faulted |
| `page = PAGE_SHIFT` in the RMW copy's `flash_page()` | `rmw/paging_sim.c` | the `>> 9` P03f fixed in the main copy was still hardcoded in `rmw/` |
| layout variants generated by `sed` from the one source (`run-sweep.sh`) | `paging_sim-<layout>.c`, `rmw/paging_sim-<layout>.c` | the constants are the experiment; the C is never re-edited per layout |

Two instrumentation bugs were found and fixed **before** any result was scored, and both would have
produced a false verdict:

* closing the N set at the next token fetch charged the **outer interpreter's** `find()`/`PAD` reads
  to the dispatch that had just ended → N = 4 (`{0,1,2,3}`) at 4 × 512 B, for a workload that sweeps
  clean in 4 frames. A metric artifact, not a page-capacity limit.
* a fault's retry path runs `write_cell()` on three variables in page 0 → a phantom 3-page set
  `{0,1,3}` for a dispatch whose real pages were `{1,3}`.

Both are documented as GUARDRAILs at the code site. The N numbers in §1/§2 are post-fix.

## 5. Doc deltas (not applied) and the next step

### `docs/01-proposal.md` §4.3 — the frame line

> **Frame layout: 4 frames × 512 B = 2048 B, page size 512 B.** The number is a **page-count** floor,
> not a page-size one, and it is confirmed twice: P03d (sweep clean, 187 positions, 15 baseline
> faults) and P19, which implemented the only compiler-side remedy — a rule that pads so a token and
> its inline operand never straddle a page (6 B, 0.46 % of the dictionary) — and measured N = **3
> again** (prelude `{0,1,2}`, workload `{0,3,1}`, 512 B pages). With the rule in place 3 × 512 B
> still dies (`ERR_RETRY_CAP ti=4 addr=1530`, cycle `1530/1536/1010`), 2 × 512 B cannot compile the
> prelude, and 4 × 256 B dies in the same prelude as before (`508/764/1026`). The third page a
> dispatch needs is the **data/cell** page, which no compiler rule can merge with the code page: the
> RMW `+!` dispatch is bit-for-bit unchanged (`w=602 ip=1500`, 302 retries). **Frames are 2048 B**;
> the 512 B that §4.3 is short must come from another line, not from frames.

### `docs/01-proposal.md` §4.2 rules 1/2 — the co-location rule as a *lower bound*, not a fix

> **Rule 1 (compiler).** Before emitting a token, if fewer than 8 bytes remain in the current page,
> pad to the next page boundary, so a token and its 4-byte inline operand are always in one page.
> Measured cost (P19): **1 pad per 1354 B of dictionary in the prelude**, 0.37 – 0.80 % of the
> dictionary overall — cheap enough to keep as a fault-rate rule, but it does **not** reduce N.
> **Rule 2 (frame capacity).** `frames ≥ N + 1` with **N = 3 measured**, and the three pages are
> token, cell/data and (for the threaded fetch and for `,`) the page the next cell is written to. N
> is not a function of the page size or of code layout: shrinking pages raises N (P03f), padding
> cannot lower it (P19). Pinning (`pin_cap = min(2, frames/2)`) subtracts from the evictable set, so
> 4 frames is the minimum that holds 3 pages; 3 frames does not.

### `probe/EVIDENCE.md` — extend E-024

> **E-024 (extended, P19).** The three-page dispatch cycle is not a straddle artifact. A compiler
> rule that pads so a token and its inline operand share a page was implemented and measured: it
> costs 6 B in the prelude (0.46 %) and leaves N at 3 in every layout that reaches the measurement
> (4 × 512 B: prelude `{0,1,2}`, workload `{0,3,1}`). 4 × 512 B still sweeps clean (0/187,
> `faults=15`); 3 × 512 B compiles the prelude and then dies `ERR_RETRY_CAP` (`1530/1536/1010`,
> pages 1–3, 203 faults); 2 × 512 B and 4 × 256 B do not compile the prelude. The P03e RMW livelock
> survives unchanged (`w=602 ip=1500`, 302 retries, cycle `602/1500/537397248` — two code pages plus
> the **data** page 1028), so the third page is data, not the operand. Conclusion: **frames =
> 4 × 512 B = 2048 B**, and the co-location rule is adopted only for fault rate, never for budget.

**Next step (one paragraph, for the queue):** stop trying to buy frame bytes back from the compiler.
Two of the three pages a dispatch needs are chosen by the *program*, and P19 shows the third is a
data page that no layout rule reaches. The remaining framing question is therefore the honest one
§4.3 has to answer: whether the machine can be given a **pinned data page** (a small "current cell"
window, or `+!` as a primitive with a pre-touched cell) so that a dispatch that reads and writes one
cell needs two pages, not three, against 4 frames. That is a primitive/ABI decision, not a
measurement, and it is the only path left that turns 2048 B into 1536 B. If it is refused, §4.3
finds its 512 B elsewhere and P03d's 4 × 512 B layout is final.

Artifacts: `run-4x512.log` + `faults-4x512.log` (control: clean 0/187, N = 3),
`run-3x512.log` + `faults-3x512.log` (prelude yes, workload source `ERR_RETRY_CAP`),
`run-2x512.log` + `faults-2x512.log`, `run-4x256.log` + `faults-4x256.log`,
`rmw/run-rmw-*.log` + `rmw/faults-rmw-*.log` (RMW unchanged at 4 × 512, early at 3 × 512, unreached
elsewhere), `build-paging_sim-*.log` / `rmw/build-paging_sim-*.log` (three pre-existing warnings,
none new), `paging_sim.c` + `uforth.c` + `boot_min.fs` + `rmw/` (the harness as built),
`paging_sim-<layout>.c` / `rmw/paging_sim-<layout>.c` (the layout constants), `run-sweep.sh` /
`run-all.sh` (build and run drivers), this file.

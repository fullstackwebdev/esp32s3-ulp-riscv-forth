# P03e — A store-then-fault primitive at 4 frames: the sweep cannot run, the added step livelocks

**Verdict: BLOCKED.** Not "baseline unstable" in the nondeterminism sense — the baseline is
bit-identical on every repeat (`chk=bfbd1e73`, two runs, `run.log`/`run2.log`) — but the *added*
read-modify-write step makes the **fault-free** case livelock, so there is no baseline to sweep
against: `ERR_RETRY_CAP w=602 ip=1500 p=2 addr=1500 retries=302`, with exactly **one page load per
retry and zero forward progress** for 302 retries. Positions tested: **0** (`tested=0`, sweep never
entered). Mismatches: **not measured**. The probe's question — *does the retry repeat the store?* —
is **not answered by measurement**, and store repetition was **not observed**; it was also **not
reached**. What the run does prove, from the per-fault log, is a different and previously unrecorded
limit: **a primitive whose dispatch needs three pages co-resident (two code pages for token + inline
operand, one data page) never gets them at 4 frames**, and the per-dispatch resume point turns that
into an eviction cycle rather than a fault storm that converges.

Host-only, gcc, one build, three workload variants. Nothing outside
`probe/results/P03e-store-then-fault/` was written; `docs/`, `probe/uforth/`, the P03b/P03c/P03d
directories and the board were never touched. Every command ran under `timeout 30`; every run was
redirected to a log and never piped through `head`/`tail`.

---

## 1. Question, verdict, and what is established

| Item | Value |
| --- | --- |
| question | if one dispatch stores and *then* faults on a second access, does the per-dispatch retry repeat the store? |
| **verdict** | **BLOCKED** — the RMW workload does not converge even with faults disabled, so the sweep cannot produce a mismatch count |
| harness | copied verbatim from `probe/results/P03d-checkpoint-fix/` (`paging_sim.c`, `uforth.c`, `boot_min.fs`); retry mechanism untouched |
| harness re-verification | with the P03d workload and the enlarged primitive table: `chk=2aadbb71 disp=179 positions=179 tested=179 mismatches=0 hangs=0 loop_bound=ERR_PAGE_FAULT_LOOP elapsed=0.6s` (`run-harness-ref.log`) — the copy still reproduces P03d's clean sweep |
| new baseline (two runs) | **not valid**: `ERR_RETRY_CAP … retries=302` in both runs, identical `chk=bfbd1e73 sp=2 rsp=2` — reproducible, but the workload itself does not terminate |
| positions tested / `no_access` | **0 / n-a** — `SUMMARY … positions=1788 tested=0 mismatches=not-measured`; 1788 is not a dispatch count (each page load adds `SERVER_LATENCY=8` to `st.dispatches`, so a thrashing run inflates it: 302 loads ≈ 2400 of those units) |
| mismatches | **not measured** (`grep -c MISMATCH run.log` → `0`, but no position was compared) |
| first mismatch | **none** — no position was run, so there is no `(w, ip, p, addr)` mismatch to report |
| cause | **neither store-repetition nor a retry bug**: proven page-capacity livelock (trace in §3) |
| store repetition | **not observed, not exercised** — the fault always lands on the *read*, before the store |

Why the added step fails is not a mystery and not noise — it is legible in the fault stream (§3) and
it reproduced identically across three variants of the same idea (§2). The one thing it is *not* is
a repeated store: at every fault in the cycle the stack has been restored to `sp=2 rsp=2
ds=1,537397248` and the faulting address is either a code address (`602`, `1500`) or the operand
cell itself (`537397248`) — the increments never get applied twice because they never get applied
once.

## 2. The measurement (verbatim)

Reference run — P03d's workload, same binary, only the primitive table enlarged (§4.1):

```
baseline frames=4 disp=179 faults=109 loads=109 writebacks=12 sp=1 rsp=0 ds0=4 chk=2aadbb71 out=811c9dc5 err=OK
loop_bound=resolved err=ERR_PAGE_FAULT_LOOP at pos=1
sweep: positions=179 tested=179 injected_fired=83 no_access=96 skipped=0 mismatches=0 faults=19499 retries=19582 forced_evicts=16 resume_mismatch=18522
SUMMARY baseline_valid=yes frames=4 workload=WORK positions=179 tested=179 mismatches=0 hangs=0 loop_bound=ERR_PAGE_FAULT_LOOP elapsed=0.6s
```

(`run-harness-ref.log`; `paging_sim-ref` built from `paging_sim-ref-src.c.keep`. P03d's `disp=187` is
`179` here and its `chk=4f99db40` is `2aadbb71` — the primitive table grew by one 8-byte entry, so
every dictionary address moved; that is a layout change, not a behaviour change, and the mismatch
count is unchanged at 0.)

The three RMW variants, each a full baseline attempt:

```
variant a  PX=537397246 (cell straddles pages 1026/1027), RMW last in WORK
           baseline frames=4 disp=1833 faults=302 loads=301 writebacks=12 sp=2 rsp=2 ds0=1 chk=0b088139 out=811c9dc5 err=ERR_RETRY_CAP
           ERR_RETRY_CAP w=602 ip=1500 p=2 addr=537397246 retries=302         (run-straddle.log)

variant b  PX=537397248 (single cold page 1028), RMW last in WORK
           baseline frames=4 disp=1833 faults=302 loads=301 writebacks=77 sp=2 rsp=2 ds0=1 chk=5938bad1 out=811c9dc5 err=ERR_RETRY_CAP
           ERR_RETRY_CAP w=602 ip=1500 p=2 addr=537397248 retries=302         (run-rmwlast.log, run2-rmwlast.log)

variant c  PX=537397248 (single cold page 1028), RMW *first* in WORK   <-- the deliverable source
           baseline frames=4 disp=1788 faults=302 loads=301 writebacks=75 sp=2 rsp=2 ds0=1 chk=bfbd1e73 out=811c9dc5 err=ERR_RETRY_CAP
           ERR_RETRY_CAP w=602 ip=1500 p=2 addr=1500 retries=302              (run.log, run2.log — identical)
```

Movement of the step within `WORK` (variant c) moves the *last* faulting address from the data cell
to the inline operand but changes nothing structural: `faults=302`, `loads=301` in all three. 302
retries buy exactly 302 page loads — a one-for-one trade, which is the signature of a cycle, not of
progress.

## 3. The livelock, traced — six checkpoints, and why it is page capacity

`./paging_sim trace` runs the same `run_case` path as the sweep (P03c's rule: same build, only the
injection differs). Both cases die the same way, so the trace below is the fault-free case;
`trace-base.log:593-601`, with the two windows either side of the fault line:

```
593 FAULT-FAULT d=1762 w=602 ip=1500 p=2 addr=1500      retry=299 sp=0 rsp=2
594 CK         d=1770 w=602 ip=1500 p=1 cf=64 sp=2 rsp=2 ds=1,537397248, rs=0,1514, olen=0
595 FAULT-FAULT d=1770 w=602 ip=1500 p=1 addr=602       retry=300 sp=2 rsp=2
596 CK         d=1778 w=602 ip=1500 p=1 cf=64 sp=2 rsp=2 ds=1,537397248, rs=0,1514, olen=0
597 CK         d=1778 w=602 ip=1500 p=2 cf=64 sp=2 rsp=2 ds=1,537397248, rs=0,1514, olen=0
598 FAULT-FAULT d=1779 w=602 ip=1500 p=2 addr=537397248 retry=301 sp=0 rsp=2
599 CK         d=1787 w=602 ip=1500 p=1 cf=64 sp=2 rsp=2 ds=1,537397248, rs=0,1514, olen=0
600 CK         d=1787 w=602 ip=1500 p=2 cf=64 sp=2 rsp=2 ds=1,537397248, rs=0,1514, olen=0
601 FAULT-FAULT d=1788 w=602 ip=1500 p=2 addr=1500      retry=302 sp=0 rsp=2
```

`faults.log` (written by the `trace` run, the last process to open it) classifies all 302 events
into three addresses, round and round:

```
67 FAULT w=602 ip=1500 p=2 addr=537397248      (data cell, flash page 1028)
67 FAULT w=602 ip=1500 p=2 addr=1500           (LIT inline operand, dictionary page 2)
67 FAULT w=602 ip=1500 p=1 addr=602            (token fetch, dictionary page 1)
```

Read against the checkpoints:

* **The dispatch is the right one and the resume state is correct.** Every `CK` in the cycle is
  `w=602 ip=1500 p=1|2` with `sp=2 rsp=2 ds=1,537397248 rs=0,1514` — the `+!` operands `( 1 PX )` and
  the return address of `RMW` are restored identically, 302 times. `sp=0` on the fault line is the
  live stack after `+!` popped both operands to call `rd32(addr)`; the restore puts them back. No
  stack damage, no phantom return address, no doubled `P_DOCOL`.
* **The three pages are never co-resident.** The fault cycle is `(page 1: token) → (page 1028:
  operand cell) → (page 2: inline operand at 1500) → (page 1) …`. Each retry loads exactly one page
  and, because `service_fault()` picks the LRU victim, the page it loads evicts the page the next
  step of the *same dispatch* needs. `retries=302`, `loads=301`: one load per retry, and the
  dispatch re-runs from its entry checkpoint both times it is entered.
* **The fault is on the READ, never after the store.** `+!` is `rd32(a)` then `wr32(a, old+b)`; the
  cycle's own addresses show the read side failing (`537397248` and the two code addresses). The
  store is only reached once the read and both code pages are resident — and that state is never
  reached. So this run says nothing at all about store repetition.
* **The progress bound cannot see it.** `ERR_PAGE_FAULT_LOOP` requires the *same* `(w, ip, p)` twice
  in a row; here the triple alternates `p=1 ↔ p=2`, so the harness counts every retry as a new
  window and only `guard > RETRY_CAP` (200) / `RETRY_CAP` ends the run — reported loud and bounded as
  `ERR_RETRY_CAP`, not as a hang, which is the behaviour P03/RETRY_CAP was designed for.

The code pages are pinned when hit (`resolve()` → `pin_page(pg)` for `va < DICT_WINDOW`), so the
frames that hold pages 0/1/2 are largely unavailable as victims; with `frames=4` the evictable set is
too small to hold `{page 1, page 2, page 1028}` at once while a retry is in flight. That is a
capacity property of the configuration, not of the checkpoint order — P03d's `BUMP` never trips it
because each of its dispatches touches exactly one code page and one data page.

## 4. Harness: what was reused, and the two edits

Reused **verbatim**: `paging_sim.c`, `uforth.c`, `boot_min.fs` copied from
`probe/results/P03d-checkpoint-fix/`. Nothing in the retry driver (`run()`, `service_fault()`,
`ckpt_save`, the window ids) was touched; `diff` against P03d shows only the two edits below.

Build (unchanged): `gcc -DHOST -DPAGING -std=c99 -O1 -Wall -Wextra -o paging_sim paging_sim.c` — the
same three pre-existing warnings (`load` unused, two `-Wclobbered`), none new.

### 4.1 `uforth.c` — one new primitive, `+!`, appended at the **end** of `PRIMS`

```diff
- X(GPIOG,"GPIO@",0) X(GPIOS,"GPIO!",0) X(ADCG,"ADC@",0) X(MS,"MS",0) X(WAKE,"WAKE",0)
+ X(GPIOG,"GPIO@",0) X(GPIOS,"GPIO!",0) X(ADCG,"ADC@",0) X(MS,"MS",0) X(WAKE,"WAKE",0) \
+ X(ADDSTORE,"+!",0)
...
+        case P_ADDSTORE: a = POP(); b = POP(); wr32(a, rd32(a) + b); break;
```

`+!` is `( n addr -- )`: one read and one write of the same cell inside one dispatch, and the value
stored depends on what was read, so a repeated store would be visible in the digest (a constant store
would not be). Read-then-write order is deliberate and carries a GUARDRAIL: writing first (or
splitting the store into per-byte `vm_wr8` calls) is exactly what would create the store-then-fault
shape under test.

**Appending at the end is not cosmetic.** Inserting `+!` next to `W!` renumbers every later primitive
id, and the fixture dies: `boot_min.fs:53` (`: +LOOP …`) ends with `err=1 sp=223 faults=86` and
`run_case` reports `CASE-ERR: prelude failed at 4 frames`. Measured with the `debug` driver, then
fixed by appending (`P_ADDSTORE` keeps every existing id). Both lessons are GUARDRAILs in `uforth.c`.

### 4.2 `paging_sim.c` — the one added workload step

```diff
+    "537397248 CONSTANT PX",
+    ": RMW  1 PX +! ;",
-    ": WORK   P1 BUMP P2 BUMP P3 BUMP P4 BUMP P1 @ P2 @ + P3 @ + P4 @ + ;",
+    ": WORK RMW P1 BUMP P2 BUMP P3 BUMP P4 BUMP P1 @ P2 @ + P3 @ + P4 @ + ;",
```

`PX = 537397248` is a 4-byte cell at the start of flash page 1028, a page this workload otherwise
never touches, so `+!` must fault there. The first choice, `537397246`, straddled pages 1026/1027 and
failed the same way (variant a) — recorded in `run-straddle.log` and in a GUARDRAIL, because
"two cold pages in one dispatch" is the harder version of the same capacity problem. `WORK`'s line
also had to stay under `TIBSZ=80` (`feed()` turns a longer line into `TEST BUG` + `st.err=1`, which
surfaces as a misleading `CASE-ERR: prelude failed`); hence the separate one-line word `RMW`.

### 4.3 What this run can and cannot say

Can say: the P03d harness, with one appended primitive and P03d's own workload, still sweeps clean
(0 of 179); and a single `+!` dispatch on a cold data page at 4 frames does **not** converge, for a
proven, traced reason (three-page working set + LRU eviction + dispatch-entry resume), reproducibly,
in three workload variants.

Cannot say: anything about store repetition. The store is never reached in the failing dispatch, so
the question is untouched by this workload. Statically, the audit of the primitive set (below)
predicts no store repetition is possible for *single-address* stores at all.

### 4.4 Audit of the primitive set (63 primitives) for multi-access words

The write path is the reason the risk is narrow: `vm_wr8`, `vm_wr16`, `vm_wr32` all call
`vm_touch(va, len)` over the **whole** byte range before writing any byte, and after that only
`located()` can fault — with `VM_FAULT_BAD` (no such page), which surfaces as `err != OK`, never as a
repeated store. So a store of one address cannot fault "after the store". The words holding two
*independent* addresses:

| word | accesses per dispatch | second address pageable & different? |
| --- | --- | --- |
| `,` `W,` `C,` | `wr16/wr32` at `HERE`, then `wr32` at `V_HERE` (4) | both in the dictionary page — no |
| `CREATE` `CONSTANT` (`mkhdr_pad`) | several stores at `HERE`, `V_LATEST`, `V_HERE` | same page — no; compile-time only |
| `+!` (new) | `rd32(a)` then `wr32(a, …)` | same address — no |
| `@ ! W@ W! C@ C!` | 1–4 byte touches, one address | no |
| `TYPE` / `(.\")` | read-many | read-only |
| `MOVE` `FILL` `CMOVE`-family | — | **not in this primitive set** |

**Count: 0 of 63 primitives can store and then fault on a second, different page inside one
dispatch.** The three comma words are the only multi-address writers and both of their addresses live
in the dictionary page (and they run at compile time, outside the measured window). If a
read-modify-write word is ever added with operands on independent pages, the capacity limit in §3
applies *before* the store-repetition question does.

## 5. Doc deltas (not applied) and the next step

The pass branch's "delete the unobserved-risk paragraph" is **not** justified by this run: no sweep
was executed, so store-then-fault remains unobserved. The RMW finding is a new, separate constraint
and needs a line of its own.

### `docs/01-proposal.md` §4.2 rule 2 — keep the residual-limit sentence, add the capacity constraint

Leave the existing sentence (`The residual limit, not measured: a primitive that writes a cell and
then faults on another page still duplicates that write — the sweep's workload contains no such
primitive.`) and replace its tail after `still duplicates that write` with:

> — no such primitive exists in the measured set: all 63 primitives reach memory through
> `vm_wr8/16/32`, which resolve their whole byte range *before* writing, so a single-address store
> cannot fault after it writes, and the only two-address writers (`,` `W,` `C,`) keep both addresses
> in the dictionary page. P03e tried to reach the case with an added `+!` read-modify-write primitive
> and could not measure it: at 4 frames the primitive's dispatch needs three pages co-resident (token
> page, inline-operand page, data page) and never gets them — one page load per retry, `ERR_RETRY_CAP`
> after 302 retries, traced as a cycle `(602, p=1) → (537397248, p=2) → (1500, p=2) → …`. So §4.2
> rule 2 also implies a **co-residency requirement**: a primitive that touches more than one page
> inside one dispatch must be able to hold them all in the frame budget (or the resume point must be
> finer than the dispatch), because the per-dispatch resume point re-enters from the top and can
> thrash indefinitely — bounded and named (`ERR_RETRY_CAP`), never a hang. `ERR_PAGE_FAULT_LOOP` does
> not catch this: its key is `(w, ip, p)` and the cycle alternates `p=1 ↔ p=2`.

Also update the parenthetical progress-bound note in the same rule with: `and the bound does not fire
when the cycle alternates windows inside one dispatch (P03e) — retry cap is the backstop there`.

### `docs/01-proposal.md` §10 R5 — the store-then-fault item, restated

Replace the bullet's last sentence (`Not covered by that measurement: a primitive that stores and
then faults on another page inside the same dispatch.`) with:

>       - [ ] Still open, and now harder than it looked: **store-then-fault is not measurable at 4
>             frames** (P03e, BLOCKED). Adding a `+!` read-modify-write step makes the fault-free
>             workload itself livelock — `ERR_RETRY_CAP`, 302 retries / 301 page loads, identical
>             digest on repeat — because the dispatch needs three pages co-resident. Measure it with a
>             frame budget that can hold them (≥ 5 frames at 512 B pages, or the RMW operand in an
>             already-resident page) before drawing any conclusion about retry idempotency for
>             multi-access primitives.

### `docs/01-proposal.md` §10 R5 — new sub-item for the capacity finding

>       - [ ] A primitive that touches *n* pages in one dispatch needs *n* + (code pages it spans)
>             frames, or the retry from the dispatch-entry checkpoint will thrash to `ERR_RETRY_CAP`.
>             Measured (P03e, 4 frames, 512 B pages): `+!` on a cold data page, code spanning two
>             dictionary pages — 302 retries, 0 progress, three addresses cycling.

(A fourth, optional delta if the parent wants it: append the P03e sentence under E-014 in
`probe/EVIDENCE.md` — harness re-verified at 0 of 179 with the enlarged primitive table; the RMW
workload blocked with a traced three-page cycle. Not written, per "write only inside this directory".)

**Next step (one paragraph, for the queue):** do not re-run P03e as designed; the workload step is
infeasible at 4 frames for a reason that is now traced. Two cheap continuations: (a) the
*measurement* P03e wanted — keep the same harness and `+!`, but place `PX` in a page the workload
already touches and make the failing access its second one (inject at the `+!` position so the read
hits and the write's page is the cold one), or raise `TEST_FRAMES` to 6 and re-sweep, which answers
the idempotency question directly; (b) the *design* question this run opened — decide whether
`ERR_PAGE_FAULT_LOOP`'s progress key should include the faulting address, since a two-window cycle
inside one dispatch is currently indistinguishable from progress. Neither is a change to the retry
mechanism, which this probe left untouched.

Artifacts: `run.log` + `run2.log` (the deliverable variant c, twice — identical digests),
`run-rmwlast.log` + `run2-rmwlast.log` (variant b), `run-straddle.log` (variant a, straddling cell),
`run-harness-ref.log` (P03d's workload, enlarged table — 0 of 179), `run-dup-rmwfirst.log` (a repeat
of variant c before the source comment was corrected), `trace-run.log`, `trace-base.log`,
`trace-f61.log` (one line per checkpoint and fault; the livelock cycle in full), `faults.log`
(per-fault, with windows — written by the last process, i.e. the `trace` run), `build.log` (three
pre-existing warnings, none new), `paging_sim.c` + `uforth.c` + `boot_min.fs` (the harness as built),
`paging_sim` (binary), `paging_sim-rmwlast.c` (variant b source), `paging_sim-ref` +
`paging_sim-ref-src.c.keep` (the harness-re-verification build), this file.

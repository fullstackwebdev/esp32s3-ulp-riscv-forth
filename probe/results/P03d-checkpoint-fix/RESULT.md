# P03d — Checkpoint after the fetch: the sweep is clean, primitive-granular retry works

**Verdict: PASS.** Moving the resume checkpoint to *after* the token fetch (`w = rd16(ip); ip += 2`)
and *before* execution is the whole fix. Baseline unchanged (`chk=4f99db40 sp=1 rsp=0`), all **187**
dispatch positions swept, **0 mismatches**, 0 hangs, `ERR_PAGE_FAULT_LOOP` still resolves — and all
**32** of P03b's mismatching positions now reproduce the baseline digest exactly. One edit, two lines
reordered in `uforth.c`; nothing else changed.

Host-only, gcc, one build. Nothing outside `probe/results/P03d-checkpoint-fix/` was written; `docs/`,
`probe/uforth/` and the P03b/P03c directories were not touched; the board was never touched. Every
command ran under `timeout 30`; every run was redirected to a log (`run.log`, `trace-run.log`) and
never piped through `head`/`tail`.

---

## 1. Question, verdict, and what is established

| Item | Value |
| --- | --- |
| question | with the checkpoint taken after the token fetch and before execution, is the exhaustive sweep clean over every faultable dispatch position? |
| **verdict** | **PASS** — 0 mismatches / 187 positions, 83 faultable |
| baseline (faults disabled) | `disp=187 faults=15 sp=1 rsp=0 ds0=4 chk=4f99db40 out=811c9dc5 err=OK` — **equals the required `4f99db40` / `sp=1` / `rsp=0`**, so the edit changed checkpoint placement, not semantics |
| positions tested / `no_access` | **187 / 104** (`injected_fired=83`, `skipped=0`) — identical to P03b, so the sweep is the same measurement |
| mismatches | **0** (`grep -c MISMATCH run.log` → `0`) |
| hangs | **0** (`SUMMARY … hangs=0`) |
| progress bound | still resolves: `ERR_PAGE_FAULT_LOOP w=1430 ip=0 p=1 addr=1430 retries=6`, `loop_bound=resolved at pos=1` |
| the 32 formerly-broken positions | **all 32 now report `chk=4f99db40 sp=1`** — checked one by one against P03b's `MISMATCH` list (59 61 62 73 75 76 77 79 81 82 93 95 96 97 99 101 102 113 115 116 117 119 121 122 133 135 136 137 139 162 174 186) |
| run | one sweep run (`run.log`, `elapsed=0.3s`) plus one reuse of the same binary's `trace` mode for position 61 (`trace-run.log`) |

What this establishes: cause (a) as P03c named it was the *only* cause visible to this sweep. Primitive
(dispatch-)granular retry with the checkpoint after the fetch is idempotent over every position this
workload can fault at, 4 frames. Cause (b) — an early store inside a primitive that faults later — is
**not** exercised by this workload, so it is unobserved here, not refuted (§4).

---

## 2. The measurement (verbatim from `run.log`)

```
## baseline
baseline frames=4 disp=187 faults=15 loads=15 writebacks=12 sp=1 rsp=0 ds0=4 chk=4f99db40 out=811c9dc5 err=OK

## permanent fault (progress bound)
ERR_PAGE_FAULT_LOOP w=1430 ip=0 p=1 addr=1430 retries=6
perm pos=1 err=ERR_PAGE_FAULT_LOOP retries=7 perm_faults=5 dispatches=1
loop_bound=resolved err=ERR_PAGE_FAULT_LOOP at pos=1

## idempotency sweep (frames=4)
…
pos=187 fired=1 spurious=1 evict=1 faults=15 retries=16 err=OK disp=195 chk=4f99db40 out=811c9dc5 sp=1 rsp=0 first=(w=240,ip=1442,p=2)

sweep: positions=187 tested=187 injected_fired=83 no_access=104 skipped=0 mismatches=0 faults=2793 retries=2876 forced_evicts=20 resume_mismatch=1768
SUMMARY baseline_valid=yes frames=4 workload=WORK positions=187 tested=187 mismatches=0 hangs=0 loop_bound=ERR_PAGE_FAULT_LOOP elapsed=0.3s
```

Side-by-side with P03b's sweep line, same harness, same workload, same frames, the only difference
being the checkpoint order:

```
P03b: sweep: positions=187 tested=187 injected_fired=83 no_access=104 skipped=0 mismatches=32 faults=2783 retries=2866 forced_evicts=20 resume_mismatch=1760
P03d: sweep: positions=187 tested=187 injected_fired=83 no_access=104 skipped=0 mismatches=0  faults=2793 retries=2876 forced_evicts=20 resume_mismatch=1768
```

The *fixture* counters are identical (`probability of coverage`: same 83 positions fire, same 104 do
not, same 20 forced evictions), so the mismatch count is comparable across the two runs. The
aggregate `faults`/`retries` differ by 10 because the 32 formerly-broken cases no longer take their
detour through the double-executed word body.

Two bookkeeping differences worth recording so nobody reads them as regressions:

* `resume_mismatch` 1760 → 1768. This counter compares the restored checkpoint's `(w, ip)` with the
  *live cursor* `(r_w, r_ip)`, and that cursor is itself set from the last restored checkpoint — so
  its value is a function of the checkpoint placement, not a correctness signal. The pass criterion is
  the digest comparison, and that is 0 mismatches. Position 61's own case (`trace-run.log`) shows a
  fault now restoring window **B** of the dispatch it belongs to, which is a deliberate, one-window
  earlier resume than the old window C.
* `ERR_PAGE_FAULT_LOOP` now reports `w=1430 ip=0 p=1` instead of P03b's `w=1430 ip=1432` (P03b
  printed `p=0` for every window; P03c's literal window ids make it `p=1` = `VM_CKPT_FETCH`). The
  named error still fires, still carries `(w, ip, p)` and the address, and still costs one retry more
  (`retries=6` vs `5`) — the same expected consequence of resuming one window earlier. No hang.

---

## 3. The specimen position (61), re-traced: the re-executed `P_DOCOL` is gone

Not required by the brief (it only asks for a trace if mismatches remain), but position 61 is the
position P03c proved and the same binary's `trace` mode is free to reuse — so it is the direct check
that the named mechanism is what disappeared, rather than the mismatch count merely moving.

```
$ ./paging_sim trace
TRACE base  inject=0  disp=187 faults=15 retries=15 resume_mismatch=9  sp=1 rsp=0 ds0=4 chk=4f99db40 out=811c9dc5 err=OK file=trace-base.log
TRACE fault inject=61 disp=188 faults=15 retries=16 resume_mismatch=10 sp=1 rsp=0 ds0=4 chk=4f99db40 out=811c9dc5 err=OK file=trace-f61.log
```

Position 61 was `disp=197 sp=0 ds0=1 chk=e39b261d` in P03b/P03c. It is now `disp=188 sp=1 rsp=0
chk=4f99db40` — one extra dispatch (the retried dispatch itself), identical page image, identical
stacks.

`trace-base.log:63-66` (fault-free) and `trace-f61.log:62-67` (one fault injected at position 61),
the windows around the fault:

```
base 63 CK d=61 w=174 ip=1412 p=3 cf=0 sp=1 rsp=2 ds=537395200, rs=0,1488, olen=0
base 64 CK d=61 w=174 ip=1412 p=1 cf=0 sp=1 rsp=2 ds=537395200, rs=0,1488, olen=0
base 65 CK d=61 w=174 ip=1412 p=2 cf=14 sp=1 rsp=2 ds=537395200, rs=0,1488, olen=0
base 66 CK d=62 w=234 ip=1414 p=3 cf=14 sp=2 rsp=2 ds=537395200,537395200, rs=0,1488, olen=0

f61  63 FAULT-FAULT d=61 w=1408 ip=1488 p=2 addr=1410 retry=8 sp=1 rsp=2
f61  64 CK d=61 w=1408 ip=1488 p=1 cf=0 sp=1 rsp=1 ds=537395200, rs=0, olen=0
f61  65 CK d=61 w=1408 ip=1488 p=2 cf=0 sp=1 rsp=1 ds=537395200, rs=0, olen=0
f61  66 CK d=62 w=174 ip=1412 p=3 cf=0 sp=1 rsp=2 ds=537395200, rs=0,1488, olen=0
f61  67 CK d=62 w=174 ip=1412 p=1 cf=0 sp=1 rsp=2 ds=537395200, rs=0,1488, olen=0
```

Read against P03c's two traces:

* The injected fault is now attributed to window **B** (`p=2`) with the *correct* pair
  `w=1408 ip=1488` — P03c's was `w=1408 ip=1410 p=3`, i.e. window C with the unadvanced `ip`. The
  faulting read is the same read (`addr=1410`), it is simply no longer *guarded* by a checkpoint that
  predates the dispatch.
* The restored checkpoint — `trace-f61.log:62`, window B of `d=60`: `CK d=60 w=1408 ip=1488 p=2
  cf=0 sp=1 rsp=1 rs=0` (the line immediately above the fault, and the triple the fault line
  prints) — is exactly the one P03c predicted. The re-executed `P_DOCOL` therefore pushes
  `RPUSH(1488)`, and `trace-f61.log:66` reaches `rs=0,1488 rsp=2` where P03c's broken run had
  `rs=0,1488,1410 rsp=3`.
* Window C now records the *fetched* token and the advanced `ip`: `trace-base.log:63` is `w=174
  ip=1412 p=3`, byte for byte the state of the next window A (`trace-base.log:64`) — the
  confirmation that C is now "token fetched, not yet executed".

The whole-run check is `trace-diff-normalised.txt`: both logs with the dispatch counter stripped
(`sed -E 's/ d=[0-9]+//'`), then `diff`. Base 248 lines, f61 251 lines, and the normalised diff is
**36 lines total**, of which everything is either the injected fault block or a `retry=` ordinal:

```
62a63,65
> FAULT-FAULT w=1408 ip=1488 p=2 addr=1410 retry=8 sp=1 rsp=2
> CK w=1408 ip=1488 p=1 cf=0 sp=1 rsp=1 ds=537395200, rs=0, olen=0
> CK w=1408 ip=1488 p=2 cf=0 sp=1 rsp=1 ds=537395200, rs=0, olen=0
69c72
< FAULT-FAULT w=234 ip=1414 p=2 addr=537395200 retry=8 sp=2 rsp=2
---
> FAULT-FAULT w=234 ip=1414 p=2 addr=537395200 retry=9 sp=2 rsp=2
… (the remaining 5 hunks are the same +1 on `retry=`)
```

That is the strongest form of the result available from this harness: the retried run reaches
**every** checkpoint of the fault-free run with identical `(w, ip, p, cf, sp, rsp, ds, rs, olen)` —
the only extra work is one re-executed dispatch and one extra retry ordinal. No phantom return
address, no double-executed body, no stack or page-image divergence.

---

## 4. Harness: reused, changed, and the limits of this result

Reused, verbatim, **no rewrite**: `paging_sim.c`, `uforth.c`, `boot_min.fs` were copied from
`probe/results/P03c-checkpoint-trace/` — which is P03b's harness *plus* P03c's distinct-window-id fix
(`VM_WIN_FETCH=1`, `VM_WIN_DISPATCH=2`, `VM_WIN_NEXT=3`, `p` demoted to trace metadata) *plus* the
checkpoint trace hooks; `diff` against P03b's copies shows exactly those P03c changes and nothing
else, and `boot_min.fs` is identical. Copying P03c's copies rather than re-deriving the fix by hand
is what makes "one edit" true: the only delta between P03c's harness and this one is the two lines in
§4.1.

Build (unchanged from P03's): `gcc -DHOST -DPAGING -std=c99 -O1 -Wall -Wextra -o paging_sim
paging_sim.c`. Three pre-existing warnings (`load` unused, two `-Wclobbered`), none new.

### 4.1 The single edit (`uforth.c`, `run_from` tail)

```diff
         if (!ip) return VM_DONE;
-        VM_CKPT_NEXT(w, ip, p);       /* C: advancing is a pure read — retry alone */
-        w = rd16(ip); ip += 2;
+        w = rd16(ip); ip += 2;        /* the read that can fault: resume point stays B */
+        VM_CKPT_NEXT(w, ip, p);       /* C: state == window A of the next dispatch */
```

Nothing else was edited — not the primitives, not the window ids, not the driver, not the workload.
The GUARDRAIL comment above the new order records the lesson (P03c position 61: a checkpoint ahead of
`rd16(ip)` re-executes a completed dispatch and leaks a return address).

Why this is correct and not merely different: a fault on `rd16(ip)` now rolls back to window B, whose
checkpoint carries the `(w, ip)` the dispatch was *entered* with and a snapshot of both stacks taken
before the switch — so the dispatch is re-run once, from its own entry state, and every
`ip`-dependent primitive (`P_DOCOL`, `P_BRANCH`, `P_EXIT`, `P_LIT`, `P_ZBRANCH`, `P_LOOP`) computes
the same effect it computed the first time. Window C is no longer a resume point at all; it is a
redundant duplicate of the next window A, kept because removing it would be a second change.

### 4.2 What this can and cannot prove

Can prove: at 4 frames, over one 187-dispatch workload and every one of the 83 positions where a fault
can actually be raised, one injected fault leaves the live stacks, the output and the page image
identical to the fault-free run. And that the specific mechanism P03c named (re-executed `P_DOCOL`,
phantom return address `1410`) is absent at exactly that position.

Cannot prove, and not claimed:

* **Cause (b) is still unobserved.** No primitive in this workload stores and then faults later in
  the same dispatch, so "a store repeated inside a retried primitive" is untouched by this sweep. A
  workload with a read-modify-write primitive that faults between the store and the dispatch end
  would be the test; it was not run.
* **One workload, one frame count, one page size** (4 frames, 512 B pages, 187 dispatches). P03's
  frame/workload matrix belongs to P03 and is not repeated. 0 mismatches at 4 frames does not
  establish 2 frames.
* **A code-page fault inside a primitive's own control flow is only as safe as the primitive is
  pure.** Both stacks and the output length are restored, but dictionary/`HERE`/page-table writes are
  not rolled back — a primitive that writes a cell and then faults on a *different* page still
  duplicates that write. Window B does not fix that; nothing in this change does.
* **`spurious`/`no_access` are injection-property counters, not coverage of every memory access.**
  104 positions raise no fault because the injected dispatch touched nothing pageable.

Artifacts: `run.log` (the sweep, including baseline and the permanent-fault probe), `trace-run.log`
(the two-case trace run), `trace-base.log`, `trace-f61.log` (one line per checkpoint, measured window
only), `trace-diff-normalised.txt` (the same two logs with `d=` stripped, diffed — the whole-run
verification in §3), `faults.log` (per-fault, with windows — note this file is rewritten by whichever
process runs
last, so its content is the *trace* run's faults; the sweep's per-position attribution is carried by
every `pos=` line in `run.log` as `first=(w,ip,p)`), `uforth.c`, `paging_sim.c`, `boot_min.fs`,
`paging_sim` (the binary as built and run), this file.

---

## 5. Doc deltas (not applied) and the next step

Per the brief's pass branch: **adopt fine-grained retry; word-boundary pinning is dropped.** The frame
pressure argument that motivated the experiment now holds: frames stay transient, so a definition that
straddles two pages does not hold both frames for its whole duration.

### `docs/01-proposal.md` §4.2 rule 2 — replace the rule's cause/decision sentences

Replace, from `Cause: a checkpoint taken before the token fetch re-executes an already-completed
dispatch, and a store performed early in a primitive that faults later in the same dispatch happens
twice.` through the end of the `**So the one-line fix is … P03d.**` paragraph, with:

> Cause, traced at position 61 (P03c) and then fixed and re-measured (P03d): the fault landed in the
> *token-advance* window, whose checkpoint was saved **before** `w = rd16(ip); ip += 2`, so the retry
> re-entered one dispatch too late and re-executed a `P_DOCOL` that had already completed, pushing
> `1410` instead of `1488` (a store repeated early in a faulting primitive was **not** observed).
> Moving that checkpoint to **after the fetch and before execution** removes it: the exhaustive sweep
> at 4 frames — one fault at each of the 187 dispatch positions, 83 of them faultable — goes from
> **32 mismatches to 0**, with the baseline unchanged (`chk=4f99db40 sp=1 rsp=0`) and no hang (P03d).
> So the resume point is **per primitive dispatch**, checkpointed after the token fetch, with both
> stacks and the output length as part of the resume state; a fault on the fetch itself rolls back to
> the dispatch's own entry checkpoint and re-runs that one dispatch, which is idempotent. Word-boundary
> pinning is **dropped**: it is unnecessary at this granularity, and with only 2 frames (P01) pinning
> a straddling definition would hold both frames for its whole duration and make nested calls thrash.
> The residual limit, not measured: a primitive that writes a cell and then faults on another page
> still duplicates that write — the sweep's workload contains no such primitive.

Also update the parenthetical in the same rule: `(verified: fires after 5 retries at `w=1430 ip=1432
addr=1430`)` → `(verified: fires after 6 retries at `w=1430 ip=0 addr=1430`, P03d; 5 retries under the
superseded checkpoint order, P03b)`.

### `docs/01-proposal.md` §10 R5 — replace the fault-retry item

Replace the bullet beginning `A fault retries correctly at **word boundaries**` (through
`… this box stays open until the word-boundary retry exists.`) with:

> - [ ] A fault retries correctly at **primitive-dispatch boundaries**, with the resume checkpoint taken
>       after the token fetch: in a 187-dispatch, 4-frame workload, one fault injected at each dispatch
>       position leaves the final stacks, the output and every touched page identical to the fault-free
>       run (baseline `chk=4f99db40`, `sp=1`, `rsp=0`), with **0 mismatches over all faultable
>       positions**. Measured: **0 of 83** mismatched (P03d, PASS), down from 32 of 83 with the
>       checkpoint ahead of the fetch (P03b, FAIL). Not covered by that measurement: a primitive that
>       stores and then faults on another page inside the same dispatch.

(A third, optional delta if the parent wants it: append the P03d sentence under E-014 in
`probe/EVIDENCE.md` — 0 of 83 mismatches, position 61 clean, window C now equals the next window A.
Not written, per "write only inside this directory.")

**Next step (one paragraph, for the queue):** §4.2 rule 2 becomes the checkpoint-after-fetch rule and
word-boundary pinning is dropped, so the compiler does **not** need per-definition page lists for
resume purposes and §4.3 does not need the straddle-thrash caveat. What remains open is the residual
limit this sweep cannot see: cause (b), a primitive whose store is followed by a fault in the same
dispatch. That is one cheap follow-up probe, not a design change — add a read-modify-write primitive
to the workload whose operand sits on a different page than its code, run the same 187-position sweep,
and count mismatches. If it is clean too, the retry mechanism is done and §4.2 rule 2 can be stated
without caveats; if it is not, the fix is per-primitive ordering (resolve before store) rather than
pinning.

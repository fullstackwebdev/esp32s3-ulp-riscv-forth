# P03c — One position, two traces: the retry re-executes a completed `P_DOCOL` (cause a)

**Verdict: cause (a) — CONFIRMED, measured at window level.** The injected fault at position 61 is
raised in **window C** (`VM_CKPT_NEXT`, `p=3`), on the token read `w = rd16(ip)`, *after* the dispatch
at `w=1408` has already completed. The checkpoint restored is the one saved **before** that read, so
the retry re-enters `run_from(1408, 1410)` and re-executes the already-completed `P_DOCOL`: the trace
shows the re-fetch (`p=2 cf=0`) and its effect `rsp 2 → 3`, `rs=0,1488,1410` where the fault-free run
has `rs=0,1488`. The phantom return address `1410` then survives to the next `P_EXIT`, which returns
to `1410` instead of `1488` and re-runs the whole word body a second time (**10 extra dispatches**,
105 vs 95) — that is the changed page image. Cause (b) (an early store repeated inside a primitive)
does **not** appear anywhere in this trace: every other fault in both runs is `p=2` (window B) and
retries idempotently.

Host-only, gcc, one build, two runs of the same binary differing only in `inject_at`. Nothing outside
`probe/results/P03c-checkpoint-trace/` was written; `docs/`, `probe/uforth/` and P03b's directory were
not touched; the board was never touched. Every command ran under `timeout 30`, the run was redirected
to `trace-run.log` and never piped through `head`/`tail`.

---

## 1. Question, verdict, and what is established

| Item | Value |
| --- | --- |
| question | at position 61, what does the retried run do differently from the fault-free run — and is it (a) a checkpoint taken before the token fetch, or (b) an early store repeated inside a primitive that faults later? |
| **cause** | **(a)** — window C is checkpointed before `w = rd16(ip); ip += 2`, so a fault in that read resumes at `(w_old, ip_old)` and re-executes the dispatch that just completed |
| window numbers assigned | `p=1` = `VM_CKPT_FETCH` (A), `p=2` = `VM_CKPT_DISPATCH` (B), `p=3` = `VM_CKPT_NEXT` (C) — literal, not threaded from `run_from` |
| window of the specimen's fault | **C (`p=3`)** — `FAULT-FAULT d=61 w=1408 ip=1410 p=3 addr=1410 retry=8` (`trace-f61.log:64`) |
| re-executed dispatch | `(w=1408, ip=1410, p=3, token=0)` — token `0` = `P_DOCOL` |
| state differing after retry | `rsp` +1 (2 → 3, permanent to the end of the run); return stack `rs=0,1488,1410` vs `rs=0,1488`; one extra `P_EXIT` target (`1410` vs `1488`) ⇒ the word body re-executes; dispatches 105 vs 95; final `sp=0` vs `1`, `ds0=1` vs `4`, `chk=e39b261d` vs `4f99db40` |
| verification | the same binary reproduces P03b exactly: baseline `disp=187 faults=15 sp=1 rsp=0 chk=4f99db40`, specimen `disp=197 retries=16 sp=0 rsp=0 chk=e39b261d` — so the two traces are the P03b specimen, not a new fixture |
| run | one run of one binary (`trace-run.log`), both cases `err=OK`, no hang, no `ERR_PAGE_FAULT_LOOP` (not under test) |

Correction to P03b's bookkeeping, worth recording because the brief inherits it: P03b's specimen triple
"`w=234 ip=1520`" is *not* the injected fault. It is the **last** fault of the case (the ordinary
`P4` boundary miss, `retry=15` in both runs); P03b's `MISMATCH` line printed `fault_w/fault_ip` of the
final fault, and its `first=(w=240,ip=1442,p=0)` was the first *legitimate* page miss of the measured
window. With window numbers and a per-checkpoint log, the injected fault is unambiguous:
`w=1408 ip=1410 p=3 addr=1410`.

---

## 2. The two traces (verbatim, same build, only `inject_at` differs)

`trace-base.log` — fault-free, lines 63–69 (`p=1` A, `p=2` B, `p=3` C):

```
63 CK d=61 w=1408 ip=1410 p=3 cf=0 sp=1 rsp=2 ds=537395200, rs=0,1488, olen=0
64 CK d=61 w=174 ip=1412 p=1 cf=0 sp=1 rsp=2 ds=537395200, rs=0,1488, olen=0
65 CK d=61 w=174 ip=1412 p=2 cf=14 sp=1 rsp=2 ds=537395200, rs=0,1488, olen=0
66 CK d=62 w=174 ip=1412 p=3 cf=14 sp=2 rsp=2 ds=537395200,537395200, rs=0,1488, olen=0
67 CK d=62 w=234 ip=1414 p=1 cf=14 sp=2 rsp=2 ds=537395200,537395200, rs=0,1488, olen=0
68 CK d=62 w=234 ip=1414 p=2 cf=21 sp=2 rsp=2 ds=537395200,537395200, rs=0,1488, olen=0
69 FAULT-FAULT d=63 w=234 ip=1414 p=2 addr=537395200 retry=8 sp=2 rsp=2
```

`trace-f61.log` — one fault injected at position 61, lines 63–70:

```
63 CK d=61 w=1408 ip=1410 p=3 cf=0 sp=1 rsp=2 ds=537395200, rs=0,1488, olen=0
64 FAULT-FAULT d=61 w=1408 ip=1410 p=3 addr=1410 retry=8 sp=1 rsp=2
65 CK d=61 w=1408 ip=1410 p=1 cf=0 sp=1 rsp=2 ds=537395200, rs=0,1488, olen=0
66 CK d=61 w=1408 ip=1410 p=2 cf=0 sp=1 rsp=2 ds=537395200, rs=0,1488, olen=0
67 CK d=62 w=1408 ip=1410 p=3 cf=0 sp=1 rsp=3 ds=537395200, rs=0,1488,1410, olen=0
68 CK d=62 w=174 ip=1412 p=1 cf=0 sp=1 rsp=3 ds=537395200, rs=0,1488,1410, olen=0
69 CK d=62 w=174 ip=1412 p=2 cf=14 sp=1 rsp=3 ds=537395200, rs=0,1488,1410, olen=0
70 CK d=63 w=174 ip=1412 p=3 cf=14 sp=2 rsp=3 ds=537395200,537395200, rs=0,1488,1410, olen=0
```

The two files agree **line for line up to line 63** (`CK d=61 w=1408 ip=1410 p=3 …`). The divergence is
exactly the retry:

* `trace-base.log:64` — the run advances: `w=rd16(1410)=174`, `ip=1412`, dispatch continues with the
  return stack at `rsp=2`, `rs=0,1488`.
* `trace-f61.log:64` — the injected fault fires on **that same read** (`addr=1410`), and line 63's
  checkpoint is the resume state.
* `trace-f61.log:65,66` — the retry re-enters `run_from(1408, 1410)`: window A, then window B **re-fetch
  the token at `w=1408`** (`cf=0`), i.e. the dispatch that had already completed.
* `trace-f61.log:67` — it re-executes it: `rsp 2 → 3`, `rs` gains `1410`. The dispatch is `P_DOCOL`
  (`cf=0`): `RPUSH(ip); ip = w + 2`. The fault-free run pushed `1488` (the caller's continuation); the
  retry pushes its own resume `ip=1410`.

The consequence, farther down the same two traces (`trace-base.log:93` vs `trace-f61.log:97`):

```
base   93 CK d=79 w=64 ip=1488 p=3 cf=3 sp=0 rsp=1 ds= rs=0, olen=0
f61    97 CK d=80 w=64 ip=1410 p=3 cf=3 sp=0 rsp=2 ds= rs=0,1488, olen=0
```

`cf=3` is `P_EXIT`. The fault-free run returns to `1488`; the retried run returns to the phantom
`1410` — which is `w+2` of the `P_DOCOL` above, i.e. the body it just left — so the body starting at
`w=174` is executed a **second** time (`trace-f61.log:98` is `CK d=80 w=174 ip=1412 p=1`, the same
dispatch the fault-free run had at `trace-base.log:64`). Counted over the run: **105 window-B
checkpoints vs 95**, i.e. exactly the 10 dispatches of that body. The page image and `sp` then differ
for the rest of the run.

---

## 3. Cause, and the one-line fix

**Cause (a), with the line numbers.**

* The checkpoint restored is `trace-f61.log:63`, window **C**, and C is taken in `run_from`'s tail
  **before** the read it guards:

  ```
          if (!ip) return VM_DONE;
          VM_CKPT_NEXT(w, ip, p);       /* C: saves the *old* w and the *unadvanced* ip */
          w = rd16(ip); ip += 2;        /* the read that can fault */
  ```

  The saved pair means "`w` is the word I just finished, `ip` points at the next token", but
  `run_from`'s entry semantics are "fetch the token at `w` and dispatch it". Resuming therefore
  re-fetches `rd16(w_old)` (`trace-f61.log:66`) and re-dispatches (`trace-f61.log:67`) a dispatch that
  had already completed.
* **Cause (b) is not present.** In both runs every other fault is `p=2` (`trace-f61.log:73` etc.:
  `w=234 ip=1414 p=2`), i.e. inside a window-B dispatch, and each of those 14 retries resumes at the
  same `(w, ip)` and continues identically — `trace-f61.log:74,75,76` match `trace-base.log:70,71,72`
  in every field but the window-C `rsp`/`rs` this probe has already corrupted. No primitive in this
  trace stores and then faults: the faulting access `rd16(1410)` is not inside a primitive at all, it
  is the loop's own advance.
* The observable defect is *not* "the instruction pointer went wrong" — it re-enters at the right
  place — it is that `P_DOCOL`'s side effect is `RPUSH(ip)` of `ip`, and re-executing it with the
  resume `ip` writes a **different return address** than the first execution did. Every window-C
  resume of a control-flow-touching dispatch therefore leaks one return-stack cell. That is why the
  page image changes only in 24 of P03b's 32 positions (the ones where the re-executed token has a
  side effect) and why `sp` ends one lower in the specimen.

**One-line fix (a):** move the C checkpoint *after* the read it guards, so the saved `(w, ip)` means
"token already fetched, not yet executed" — which is then byte-identical to window A of the next
iteration, and resumable with the existing entry semantics:

```c
        if (!ip) return VM_DONE;
        w = rd16(ip); ip += 2;        /* the read that can fault: residual resume point is B */
        VM_CKPT_NEXT(w, ip, p);       /* C: state == window A of the next dispatch */
```

With that order, a fault on `rd16(1410)` rolls back to the **B** checkpoint of that dispatch —
`trace-f61.log:62`, `CK d=60 w=1408 ip=1488 p=2 cf=0 sp=1 rsp=1 ds=537395200, rs=0,1488` — the stacks
are restored, and `P_DOCOL` is re-executed with the *correct* `ip=1488`: `RPUSH(1488)`, i.e. exactly
the fault-free effect. This does not remove cause (b)
in general (a primitive that stores and then faults still repeats its store); §4.2 rule 2's
word-boundary pinning remains the safer rule, and it covers both.

Per the brief this probe does **not** touch the interpreter: the fix above is stated, not applied.

---

## 4. Harness: reused, changed, and what it can and cannot prove

Reused: P03b's `paging_sim.c`, its `uforth.c` (`PAGING` build), `boot_min.fs`, the frame table,
`resolve()`, LRU + pinning, the fake server, `run_case()`, the injection point, the progress bound.

Changes (all inside this directory; `probe/results/P03b-retry-progress/` untouched):

1. **The named harness defect, fixed.** `VM_CKPT_FETCH`, `VM_CKPT_DISPATCH`, `VM_CKPT_NEXT` now pass
   literal window ids `1`, `2`, `3`; `run_from`'s `p` is `(void)p`, it no longer names a window.
   Every fault line in both logs therefore carries a window.
2. **Every checkpoint is logged** (`trace-base.log`, `trace-f61.log`), one line each:
   `CK d=<dispatch counter> w ip p cf=<token> sp rsp ds=<top 4> rs=<top 4> olen`. The token is what
   makes the re-executed dispatch nameable; without it the retry looks like a duplicate green line.
   Only the measured workload is traced (`trace_meas` is set after the counter reset) — the prelude
   also dispatches (it compiles `boot_min.fs`) and would have buried the window.
3. **`trace` mode in `main`**: one binary, two `run_case()` calls — `inject=0` → `trace-base.log`,
   `inject=61` → `trace-f61.log`. Same `run_case()` path as the sweep, same hooks; only `inject_at`
   differs between the two logs, and the traced pair *is* the P03b pair (verified: baseline and
   specimen digests match P03b to the digit).

Can prove: the window of a fault, the checkpoint that was restored, the token that re-executed, and
the per-checkpoint stack state on both sides — i.e. the whole (a)/(b) question for this position.

Cannot prove, and not claimed:

* **Nothing about the other 31 mismatches.** The brief is one position; this is one position. The
  window-C mechanism now has a name; how many of the 32 are window C is a re-sweep, not run here.
* **Cannot exclude (b) globally:** this trace contains no store-then-fault primitive, so (b) is
  unobserved, not refuted.
* **Cannot separate the phantom-return damage from ordinary double execution** in the final digest:
  both come from the same re-execution, and the digest is the aggregate. The per-line trace is the
  evidence; the digest only confirms it is P03b's specimen.
* Trace line numbers refer to the files as delivered; `diff trace-base.log trace-f61.log` is the
  complete record of the divergence (identical to line 63, then 10 extra dispatches).

Evidence files: `trace-run.log` (the run), `trace-base.log`, `trace-f61.log` (the two traces),
`faults.log` (per-fault, both cases, with windows), `paging_sim.c`, `uforth.c`, `boot_min.fs`,
`paging_sim` (binary as built; rebuilt once after the single run to fold in two comment-only
GUARDRAIL edits — no code change, the traces here are that one run, not a re-run); this file.

---

## 5. Doc deltas (not applied) and the next step

### `docs/01-proposal.md` §4.2 rule 2 — replace the sentence that currently reads

> Cause: a checkpoint taken before the token fetch re-executes an already-completed dispatch, and a
> store performed early in a primitive that faults later in the same dispatch happens twice.

with:

> Cause, traced at position 61 (P03c): the fault landed in the *token-advance* window — checkpointed
> before the read `w = rd16(ip); ip += 2` — so the retry re-entered at `(w=1408, ip=1410)` and
> re-executed the `P_DOCOL` that had already completed, pushing a second, wrong return address
> (`1410` instead of `1488`) that made the word body run twice; a store repeated early in a faulting
> primitive was not observed.

### `probe/EVIDENCE.md` — append under E-014 (P03b's hypothesis is now measured):

> **P03c confirms cause (a) at window granularity (the probe the P03b report asked for).** Same
> harness, three literal window ids (`1` FETCH, `2` DISPATCH, `3` NEXT), every checkpoint logged.
> Position 61's injected fault is window **3**: `FAULT d=61 w=1408 ip=1410 p=3 addr=1410 retry=8`.
> The restored checkpoint (taken before `w = rd16(ip)`) makes the retry re-fetch the token at
> `w=1408` (`CK … p=2 cf=0`) and re-execute it (`rsp 2 → 3`, `rs=0,1488,1410` where the fault-free run
> has `rs=0,1488`); the phantom return address makes the next `P_EXIT` return to `1410` instead of
> `1488` and re-run the body (+10 dispatches, 105 vs 95). Cause (b) not observed. One-line fix:
> move `VM_CKPT_NEXT` after `w = rd16(ip); ip += 2;`. Result dir:
> `probe/results/P03c-checkpoint-trace/`.

Next step (one paragraph, for the queue): the design fix does not change — §4.2 rule 2 keeps
**word-boundary pinning** as the resume granularity, and it is now justified by a mechanism rather
than a mismatch count: a dispatch-granular retry cannot be idempotent at control-flow tokens, because
`P_DOCOL`/`P_BRANCH`/`P_EXIT` compute their effect from the `ip` they are re-entered with. Two
optional follow-ups, both cheap and both extensions of this run rather than new probes: (i) re-run
P03b's sweep with the window ids now in place, to attribute all 32 mismatches to windows and confirm
they are all window C; (ii) apply the one-line C-after-fetch reorder and re-run the same sweep, to
measure how far the mismatch count drops before word-boundary pinning is implemented. Neither is
needed for the §4.2 decision.

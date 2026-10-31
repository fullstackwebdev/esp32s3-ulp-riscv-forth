# P03b — Retry progress: does every fault position converge?

**Verdict: FAIL — the retry at the primitive-dispatch resume point is not idempotent. 32 of the 83
faultable dispatch positions in a 187-position, 4-frame workload finish with a different machine
state than the fault-free run. The baseline is clean, so this is a result about the mechanism, not
about the fixture. The progress bound does its job: a permanent fault becomes
`ERR_PAGE_FAULT_LOOP`, and there are zero hangs.**

Host-only, gcc, P03's harness reused (`paging_sim.c` copied from `probe/results/P03-paging-sim/`
and fixed, not rewritten). Nothing outside `probe/results/P03b-retry-progress/` was written; the
board was never touched. Every command ran under `timeout 30`; the run was redirected to `run.log`,
never piped through `head`.

---

## 1. Question and what is established

| Item | Value |
| --- | --- |
| baseline digest valid | **yes** — `err=OK`, `disp=187`, `faults=15`, `sp=1`, `rsp=0`, `chk=4f99db40`, `out=811c9dc5` |
| dispatch positions in the workload | **187** (`INIT` + `WORK` region at 4 frames) |
| of which a fault can be injected | **83** — at the other **104** positions the armed fault was cleared at the next dispatch before any faultable flash access occurred, so those cases are byte-identical to the baseline by construction and are reported as `no_access`, never as passes |
| positions tested | **187** (skipped 0 — every position was run) |
| positions where the injection actually fired | **83** |
| mismatches | **32** (must be 0) — positions listed in §2 |
| mismatches among faultable positions | **32 / 83 = 39 %** |
| `ERR_PAGE_FAULT_LOOP` fires on a permanent fault | **yes** — at sweep position 1, `(w=1430, ip=1432, p=0)`, `addr=1430`, after 5 retries |
| hangs | **0** — every one of the 187 cases finished with `err=OK`; whole run 0.2 s |
| resume window recorded in the checkpoint | **uninformative** — `p` is an *argument* to `run_from(w, ip, p)`, never updated as the interpreter advances, so `ck.p` is 0 in every fault. The window identity is a harness limitation, not a finding; see §3. |
| `resolve()` timing | **not measured** — this probe is about correctness (per the brief) |

So: one fixed 200-dispatch-order workload at 4 frames, every dispatch position swept once with one
fault injected exactly there. The fault-free run is reproducible; the retry is not a faithful
replay of it.

---

## 2. The mismatches (the finding)

All 32, with the faulting checkpoint that was re-entered:

```
pos=59  w=234 ip=1520 p=0  sp=2/1  chk=ee186b40/4f99db40
pos=61  w=234 ip=1520 p=0  sp=0/1  chk=e39b261d/4f99db40
pos=62  w=234 ip=1520 p=0  sp=2/1  chk=4f99db40/4f99db40  (live stack differs, pages equal)
pos=73  w=234 ip=1520 p=0  sp=1/1  chk=2df19b43/4f99db40
pos=75  w=234 ip=1520 p=0  sp=0/1  chk=ddaf1a0a/4f99db40
pos=76  w=234 ip=1520 p=0  sp=3/1  chk=710e5b41/4f99db40
pos=77  w=234 ip=1520 p=0  sp=1/1  chk=9e5e0039/4f99db40
pos=79  w=64  ip=1488 p=0  sp=0/1  chk=0f8ceb41/4f99db40
pos=81  w=234 ip=1520 p=0  sp=0/1  chk=981eda17/4f99db40
pos=82  w=234 ip=1520 p=0  sp=2/1  chk=4f99db40/4f99db40  (live stack differs)
pos=93  w=234 ip=1520 p=0  sp=1/1  chk=da725343/4f99db40
pos=95  w=234 ip=1520 p=0  sp=0/1  chk=5f1994e8/4f99db40
pos=96  w=234 ip=1520 p=0  sp=3/1  chk=c48da341/4f99db40
pos=97  w=234 ip=1520 p=0  sp=1/1  chk=1e14a827/4f99db40
pos=99  w=64  ip=1492 p=0  sp=0/1  chk=049a9340/4f99db40
pos=101 w=234 ip=1520 p=0  sp=0/1  chk=981eda17/4f99db40
pos=102 w=234 ip=1520 p=0  sp=2/1  chk=4f99db40/4f99db40  (live stack differs)
pos=113 w=234 ip=1520 p=0  sp=1/1  chk=6cb47b43/4f99db40
pos=115 w=234 ip=1520 p=0  sp=0/1  chk=27892536/4f99db40
pos=116 w=234 ip=1520 p=0  sp=3/1  chk=f54e5b41/4f99db40
pos=117 w=234 ip=1520 p=0  sp=1/1  chk=9e7ba6a5/4f99db40
pos=119 w=64  ip=1496 p=0  sp=0/1  chk=404da341/4f99db40
pos=121 w=234 ip=1520 p=0  sp=0/1  chk=981eda17/4f99db40
pos=122 w=234 ip=1520 p=0  sp=2/1  chk=4f99db40/4f99db40  (live stack differs)
pos=133 w=234 ip=1520 p=0  sp=1/1  chk=21b53343/4f99db40
pos=135 w=234 ip=1520 p=0  sp=0/1  chk=b1d93c24/4f99db40
pos=136 w=234 ip=1520 p=0  sp=3/1  chk=404da341/4f99db40
pos=137 w=234 ip=1520 p=0  sp=1/1  chk=09fe6a83/4f99db40
pos=139 w=64  ip=1500 p=0  sp=0/1  chk=4f99db40/4f99db40  (live stack differs)
pos=162 w=234 ip=1520 p=0  sp=0/1  chk=4f99db40/4f99db40  (live stack differs)
pos=174 w=234 ip=1520 p=0  sp=0/1  chk=4f99db40/4f99db40  (live stack differs)
pos=186 w=278 ip=1522 p=0  sp=0/1  chk=4f99db40/4f99db40  (live stack differs)
```

Distinct positions, for the record:

```
59 61 62 73 75 76 77 79 81 82 93 95 96 97 99 101 102 113 115 116 117 119 121 122
133 135 136 137 139 162 174 186
```

Shape of the error:

* **24 of 32 change the final page image** (`chk` differs): the workload's data pages end with a
  *different number of increments* — the classic double-execution signature (`ds0 = 5` where the
  baseline has `4`, `ds0 = 537395200` = a `P1` address left un-consumed on the stack).
* **8 of 32 keep identical pages but a different live data stack** — a value is lost or left
  behind without changing memory.
* `sp` ends at 0 in 15 cases (the baseline leaves the `WORK` result, 1 cell), at 2 or 3 in 9 cases,
  and at 1 with a *different* value in 8 cases. The final value is never a subset of the correct
  one — it is a different interleaving.
* The window index in every line above is `p=0` — **for all 187 positions and every fault, in both the passing and the failing cases**, because `p` is passed into `run_from(w, ip, p)` and never updated within a call: `VM_CKPT_FETCH/DISPATCH/NEXT` all store the same argument. The three windows are therefore *not distinguishable* in this harness's recorded triple; only `(w, ip)` is real. The `p=0` column must not be read as "the fault was in window A".
* One clean case is enough on its own: **position 61 faults once, retries once (`faults=15`,
  identical to the baseline, no cascade), and ends at `sp=0` with a changed page image.** A single
  fault plus a single retry is already enough to lose the result.

The failure is not positional noise: the mismatch positions repeat with a period of 20 (59, 61, 62 /
73, 75, 76, 77 / 93, 95, 96, 97, …), i.e. they sit at the same relative dispatch inside each `BUMP`
call of `WORK`. Whatever is wrong is inside a specific primitive sequence, executed once more or
once less.

**Mechanism, not fixed here (the brief says report the position, do not attempt a fix).** Two
defects are visible by reading the paging build, and the second one reproduces the observed
signature exactly; neither has been *traced* yet, so treat this as the hypothesis to test, not as the
measured cause.

1. The checkpoint restores `(w, ip, sp, rsp, ds[], rs[], outlen)` — *registers* — and re-enters
   `run_from(w, ip, p)`. It does not restore *memory*, and it holds exactly one `(w, ip)` pair while
   the engine can be nested several `run_from` frames deep. A primitive that has already performed
   one store and then faults on the next `resolve()` is re-run from its entry checkpoint with its
   memory effects still in place, so the store happens twice.
2. **Window C is checkpointed before the instruction it guards.** In `run_from`'s tail:

   ```
           if (!ip) return VM_DONE;
           VM_CKPT_NEXT(w, ip, p);       /* C: saves the *old* w and the *unadvanced* ip */
           w = rd16(ip); ip += 2;        /* the read that can fault */
   ```

   The state saved at C is "`w` is the word I just finished, `ip` points at the next token". A fault
   in that `rd16(ip)` therefore resumes at `(w_old, ip_old)`, whose first action is `cf = rd16(w_old)`
   — it **re-executes the dispatch that had already completed**, then advances again. That is exactly
   the observed signature: data pages with one increment too many (`ds0=5` where the baseline has
   `4`), an address left unconsumed on the stack, and a final `sp` that is smaller by one when the
   repeat swallowed the result. A window-C read is reached only by the dispatches whose token stream
   leaves `ip` pointing into a not-yet-touched page, which fits 32 of 83 rather than all of them.

`st.resume_mismatch` came out at 1760 over the sweep: the `(w, ip)` at which a fault was retried was
frequently not the one that had just faulted, which is the "fault re-raised on a different position
than the one that retired" family the brief named. That counter is not proof of a specific
double-execution; tracing position 61 (below) is.

---

## 3. Harness: what was reused, what was changed, what the injections can and cannot prove

Reused verbatim as a starting point (P03's model, not a new simulator): `paging_sim.c` +
`uforth.c` (the `#ifdef PAGING` build) from `probe/results/P03-paging-sim/`, and the frame table,
`resolve()`, LRU + pinning, the fake server, `run_from(w, ip, p)`, 3 windows per dispatch, the
interpreter-level restart point, and the per-dispatch output buffer.

Changes, all inside `paging_sim.c`:

1. **Fixture**: `boot_min.fs` copied from `probe/uforth/` (the fixed `: BASE 12 ;`). No comment line
   is ≥ 80 bytes. **The baseline is clean at 4 frames** — the exact failure P03 hit (`err=99`) is
   gone, and the prelude compiles with one fault.
2. **Injection armed before the hit path in `resolve()`.** P03 armed it *after* the resident-page
   shortcut, so an injection at a resident page silently did nothing and counted as a pass. Now the
   fault always fires, and an unpinned resident frame is written back and evicted first so the retry
   really pays a fetch.
3. **Per-fault log** (`faults.log`): one line per fault with `(w, ip, p, addr, retry)` plus a
   `FAULT-INTERP` variant for the outer interpreter. P03 printed the position only on a mismatch,
   which is why its hang had no position.
4. **Progress bound** `ERR_PAGE_FAULT_LOOP`: the same `(w, ip, p)` faulting `K = 2` times with no
   other window started in between (progress = a checkpoint at a different `(w, ip, p)`). Backstopped
   by a 200-retry cap per `run()`/`feed()`/`write_cell()` that is a *named* `ERR_RETRY_CAP`, so no
   fault can ever look like a hang again.
5. **Digest comparison on live cells only** (`ds[0..sp)`, `rs[0..rsp)`): comparing all 16 cells
   reported 105 phantom mismatches whose dead cells above `sp` merely differed.
6. **Two harness bugs fixed that would have faked a result**: `errf` (the sticky outer-interpreter
   error flag) was never reset by `vm_init`, so the first failing case made *every following case*
   "fail in its prelude"; and `inject_at`/`perm_at` were assigned only *after* the prelude, so a
   case's prelude ran with the previous case's injection still armed (the prelude then lost a page
   permanently — the first run of this probe died on exactly that).

What the sweep can and cannot prove:

* **Can**: every dispatch position was run and compared; the 83 faultable positions each took a real
  fault + retry and produced a comparable digest.
* **Cannot** account for the 104 positions where the injection never fired. The arm is set inside
  `vm_on_dispatch()` and cleared at the next dispatch, so a dispatch whose remaining accesses are
  all PSRAM or absent retires without a fault; I did not isolate *why* 104 do, within the timebox.
  Those 104 cases are not evidence of anything — they reproduce the baseline because nothing was
  injected into them.
* **Cannot**: say *which* of the three restart windows faulted. `p` is threaded into
  `VM_CKPT_FETCH/DISPATCH/NEXT` unchanged, so the recorded triple always reads `p=0`; the harness
  cannot attribute a mismatch to a window. Window identity has to be inferred from `(w, ip)` plus the
  code path, which is why §2 states a hypothesis and not a cause. The next harness change is one
  line — give each of the three `VM_CKPT_*` macros its own literal window number — and then this
  sweep can state the window per mismatch.
* **Also cannot** isolate a *single* window with a single fault: `vm_on_dispatch()` runs after the
  token read, so the injection always lands on a memory access *inside* the switch or at the tail
  read, never on the dispatch's first read.

Run hygiene: two earlier program runs were aborted by harness defects 2 and 6 above; the run
reported here is the third, single, complete run of `./paging_sim` (`run.log`, 0.2 s). A *control*
run with the forced eviction disabled (`NOEVICT=1`, `run-noevict.log`) gives the identical 32
mismatches and identical fault/retry totals, so the mismatches are not caused by the eviction the
injector performs.

Evidence files in this directory: `run.log` (the run), `faults.log` (per-fault `(w, ip, p, addr,
retry)`), `run-noevict.log` (control), `paging_sim.c`, `uforth.c`, `boot_min.fs`, `paging_sim`
(binary, as built), plus this file.

---

## 4. The progress bound (§ Method step 4)

Permanent fault injected at sweep position 1 — the page touched by that dispatch never becomes
usable, the server "loads" it and the next `resolve()` faults on it again:

```
ERR_PAGE_FAULT_LOOP w=1430 ip=1432 p=0 addr=1430 retries=5
perm pos=1 err=ERR_PAGE_FAULT_LOOP retries=6 perm_faults=4 dispatches=1
loop_bound=resolved err=ERR_PAGE_FAULT_LOOP at pos=1
```

* It fires after **5 retries / 4 repeated faults**, in milliseconds, at a *named* position
  `(w=1430, ip=1432, p=0)` with the faulting address `1430` in the log.
* It is the same-key rule, not the 200-retry cap: `retries=6` is far below `RETRY_CAP`.
* Conclusion: the bound works and is needed. **This is the one requirement of P03b that passes.**
  A retry state machine without it has no way to tell progress from a livelock — which is exactly
  what P03 recorded as an unnamed hang at 4 frames.

---

## 5. Doc deltas (not applied — this probe may not write `docs/`)

Verdict `FAIL` ⇒ per the brief the resume point moves to word boundaries. Both deltas below are
verbatim text for the orchestrator to apply; nothing in `docs/` was edited.

### `docs/01-proposal.md` §4.2 rule 2 — replace the whole rule with:

> 2. **A fault retries, and the retry must be idempotent — measured at dispatch positions, and it
>    does not close yet (P03b, FAIL).** The interpreter checkpoints `(w, ip, p, sp, rsp, ds[], rs[],
>    output length)` at each primitive dispatch and re-enters the same `(w, ip, p)` after the page
>    fetch. Exhaustive measurement — one 187-dispatch workload at 4 frames, one fault at every
>    dispatch position — gives **32 mismatches out of the 83 positions where a fault can occur
>    (39 %)**: the retried run ends with a different page image in 24 cases and a different live
>    stack in 8, including a position that took exactly one fault and one retry. The resume point
>    therefore moves to **word boundaries**: residency is checked once at the top of each word and a
>    fault is only raised there, so no retry can ever re-enter a partially executed primitive. The
>    retry state machine carries a **progress bound**: a retry that returns to the same
>    `(w, ip, p)` twice without an intervening successful dispatch aborts with
>    `ERR_PAGE_FAULT_LOOP` (verified: a permanently unfetchable page at sweep position 1 aborts
>    after 5 retries with `w=1430 ip=1432 p=0 addr=1430`), with a hard retry cap (`ERR_RETRY_CAP`)
>    as the backstop so no fault can present as a hang. Output stays buffered per dispatch and is
>    discarded on rollback. Two structural consequences remain as before: `!` pops its address in
>    order to resolve it, so the stacks must be part of the resume state; and the outer interpreter
>    needs its own restart point, because `find`/`number`/`,` touch memory with no `run_from` frame
>    above them.

### `docs/01-proposal.md` §10 R5 — replace the fault-retry item with:

> - [ ] A fault retries correctly at **word boundaries**: in a 187-dispatch, 4-frame workload, one
>       fault injected at each of the dispatch positions leaves the final stacks, the output and
>       every touched page identical to the fault-free run (baseline `chk=4f99db40`, `sp=1`,
>       `rsp=0`), with **0 mismatches over all faultable positions**. Measured today at
>       primitive-dispatch granularity: **32 of 83 mismatched** (P03b, `FAIL`), so this box stays
>       open until the word-boundary retry is implemented.
> - [ ] A permanently unfetchable page produces `ERR_PAGE_FAULT_LOOP` with the faulting
>       `(w, ip, p)` and address in the error, never a hang (verified: fires after 5 retries).

`docs/01-proposal.md` §4.2 rule 3 (thrash rule) and §4.3 (frame count) get **no delta** from this
probe: frame count was fixed at 4 by the brief and no workload was swept for `faults_per_wake`.

---

## 6. What the next probe must do (one paragraph, for the queue)

Take position 61 as the specimen: `BUMP` at `w=234`, one fault at `ip=1520`, one retry
(`faults=15`, identical to the baseline — no cascade), and the run ends at `sp=0` instead of `1` with
a changed page image. Two one-line harness changes first: give each of `VM_CKPT_FETCH`,
`VM_CKPT_DISPATCH`, `VM_CKPT_NEXT` its own literal window number so `p` stops being always 0, and
log every checkpoint, not just every fault. Then dump the 8 dispatches around position 61 in the
fault-free and the retried run and diff them. Test in this order: (a) window C's checkpoint is taken
before `w = rd16(ip); ip += 2`, so a fault in that read re-executes a completed dispatch; (b) a store
performed earlier in a primitive that faults later in the same dispatch is repeated. Do not re-sweep
the matrix; one position, two traces.

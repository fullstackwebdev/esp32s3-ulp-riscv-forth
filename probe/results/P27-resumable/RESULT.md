# P27 — The interpreter is resumable: a switch now moves the machine, not the books

| | |
| --- | --- |
| Result | **PASS.** The interpreter state is one 136 B `VM` struct (`ds[16]`, `rs[16]`, `sp`, `rsp`, `w`, `ip`) and a switch is a struct copy. `PAUSE` pre-empts **mid-word**: the saved pair is the post-fetch dispatch of the token *after* `PAUSE`, inside the word body, and the word continues to the same answer on resume — **676** for (b) and **10** for (c), with the machine image **byte-identical** (FNV `0xfc3c37f0` / `0x2895577b`) to the same words run with no `PAUSE` at all. Three tasks interleave in the order the host predicted, exactly, and the whole 3-task program runs in **one C frame** (`max vm_enter depth = 1`). An injected page fault at the same positions is reproduced by **the same `vm_switch()` call**, and returns byte-identical results. 58-test suite still 58/58. |
| Runs on | **host only** (`gcc -DHOST`, board untouched, no serial device opened) |
| Time box | one run, 15 min hard cap — **overrun ≈ 35 min**, almost all of it on the four prediction mismatches in §2.2, each of which was a bug in the *test*, not in the switch |
| Sources | `uforth.c` (prototype + the VM struct, `PAUSE`, `FAULT`, `vm_switch`), `boot_min.fs` (unchanged), `host_test.c` (**unchanged** — the 58-test suite), `p27_test.c` (the four probes), `p27_expect.py` (host-side prediction) |

## Record

| Test | predicted (computed on the host) | actual | verdict |
| --- | --- | --- | --- |
| (a) three-task interleaving | order `->A A>B B>C C>A A>B B>C C>A A>B B>C C>A A>B B>C C>A A>C C>A`; counts A=5 B=3 C=4; 15 switches = 12 PAUSE + 2 task-exit + 1 first entry | identical string (`diff` clean), A=5 B=3 C=4, total=15 pause=12 fault=0 taskexit=2 | **PASS** |
| (b) suspend mid-word | value 676; machine image equal to the no-`PAUSE` run; 1 suspend; resume `ip` inside `B1`'s body | 676, digest `0xfc3c37f0` = `B0`'s, 1 pause, `rd16(ip-4)` = `PAUSE`'s xt, `w` = the next token | **PASS** |
| (c) suspend inside `DO` inside a word | value 10; image equal to the no-`PAUSE` run; 5 suspends | 10, digest `0x2895577b` = `N0`'s, 5 pauses | **PASS** |
| (d) page fault at the same positions | 676 and 10 with the *same* digests as the no-`PAUSE` runs, faults routed through `vm_switch` | 676 / `0xfc3c37f0` after 1 retry; 10 / `0x2895577b` after 5 retries; fault switches = 1 and 5, PAUSE switches = 0 | **PASS** |
| suite | 58/58 | **58/58** (`host_test.c` byte-identical to `probe/uforth/host_test.c`) | **PASS** |

---

## 1. Answers

**Q: What is the VM state a switch must save?**
**136 B at `SD=16`, six fields — and two of them are the stacks themselves, not just pointers:**

| field | B | why it is there |
| --- | --- | --- |
| `ds[16]` | 64 | the data stack *values*; P13 measured a 20-cell peak, so a task switched out owns up to 20 live cells |
| `rs[16]` | 64 | the return stack *values*; the `DO ... LOOP` frame (`limit`, `index`) lives here, which is why (c) is the sharp test |
| `sp`, `rsp` | 2 | the two stack pointers |
| `w` | 2 | the dispatch position: the xt of the token about to execute |
| `ip` | 2 | that token's continuation; `ip == 0` means "return to C" |

**Not saved, because it is dead across a dispatch:** `run()`'s temporaries `a, b, n, i, imm, x`. Every
`case` stores before it loads; checked case by case. This is the one claim in the list that is verified by
inspection rather than by execution — the serializer that *would* prove it mechanically is a follow-up (§5.2).

**Not saved, because it is not the machine:** `tib`, `ti`, `tl`, `errf`. Those belong to the outer
interpreter — the REPL that owns the keyboard, i.e. exactly one context, not one per task. A real system
would have to decide whose line buffer it is; P27 does not claim to.

The task record is `VM` + `entry` + `state` = **140 B** (`TSK`), 268 B at `SD=32`. **That is the price R4
was hiding: P26's records were 8 B because they held nothing.** At P13's measured depth (`SD=32`,
20 data + 7 return cells) three tasks cost **804 B of RAM** instead of P26's 24 B of bookkeeping — 780 B
more for the same three tasks. It fits 8 KB; it is 10 % of the budget, not 0.3 %.

**Q: Does a `PAUSE` inside a colon word return into the middle of that word?**
**Yes, and the `ip` is checkable.** In `: B1 7 3 * 5 + PAUSE DUP * ;` the saved state at the switch is
`w = DUP`, `ip = <DUP>+2` — asserted as `rd16(ip-4) == xt_of("PAUSE")` *and* `ip` strictly inside the body
`xt+4 < ip < HERE`. There is no return to the caller: the caller's continuation is `0`, and the assert
fails if the saved `ip` is `0`. The proof that it *matters* is arithmetic: `B0` (no `PAUSE`) and `B1`
(with one) both end at **676** with identical `sp`, `rsp` and stack bytes; if `PAUSE` had returned to the
caller, `DUP *` would never have run and the answer would be 26.

**Q: Does the switch unwind the C stack?**
**No — measured, not argued.** `vm_enter()` counts its own C nesting: over the entire 3-task run (12
pre-emptions, 2 task exits) the maximum depth reached is **1**. `PAUSE` is a `continue` in the same loop
with a different `VM` loaded; nothing returns. This is possible only because the prototype never used the
C stack for its own control flow: colon calls push `ip` on the *Forth* return stack, so `run()` is one
flat `switch`. The `FAILURE` criterion "PAUSE inside a word corrupts the C stack" **does not fire**, and
no threaded-interpreter rewrite is needed.

**Q: Is the page-fault path the same mechanism as `PAUSE`?**
**Yes — the same function, one dispatch apart.** Both save/restore through `vm_switch(int next)`, which is
the only code that copies a `VM`:

* `PAUSE`: advances the token (`w = rd16(ip); ip += 2`), then `vm_switch(next_ready)`.
* `FAULT`: does **not** advance, then `vm_switch(cur)` — a switch that lands on its own machine, which is
  exactly a retry.

The save point is the *same window* in both cases: P03d's post-fetch dispatch. `PAUSE`'s window is the
dispatch **after** `PAUSE` (because `PAUSE` itself is finished); the fault's window is the **faulting**
dispatch (because it is not). Same window, same restore, same re-entry — `continue` at the top of the loop.
The counter check `vm_switches == vm_sw_pause + vm_sw_fault + vm_sw_taskexit + vm_sw_first` holds, so
neither path has a switch of its own. **One mechanism, not two.**

**Q: The quantum, then.**
**Token-granular.** A long word *can* be pre-empted at any token boundary, and `PAUSE` is where the switch
is requested — but the resume unit is one dispatch, so any token is a valid pre-emption point. What the
probe does **not** show is *pre-emption without cooperation*: a word that never calls `PAUSE` still runs to
completion, because nothing counts tokens between `PAUSE`s. The machinery is ready for a counted quantum
(the switch point is uniform), the policy is not implemented. That is a one-line change in `vm_switch`'s
caller and it is not claimed here.

---

## 2. Evidence

### 2.1 Commands (all under `timeout 30`, host only, nothing written outside this directory)

```
gcc -DHOST -std=c99 -Wall -Wextra -o uforth_p27 uforth.c        # engine: 2 warnings (unused task API)
gcc -DHOST -std=c99 -Wall -Wextra -o uforth_test host_test.c    # the 58-test suite, unmodified
./uforth_test > suite.log                                       # 58 passed, 0 failed
gcc -DHOST -std=c99 -Wall -Wextra -o p27_test p27_test.c        # the four probes
./p27_test > p27_run.log                                        # 16 passed, 0 failed
gcc -DHOST -DSD=32 -std=c99 -o p27_test_sd32 p27_test.c         # same probes at P13's depth
./p27_test_sd32 > p27_run_sd32.log                              # 16 passed, 0 failed, TSK=268 B
python3 p27_expect.py > p27_expect.txt                          # the predictions, from the rule only
diff <(expected A-ORDER) <(actual A-ORDER)                      # no output = identical
```

### 2.2 The four mismatches, and why each was the test's fault

Worth recording, because three of them were *assertions about a correct switch*:

1. **(a) switch accounting was short by one.** `vm_switches` also counts the very first dispatch into a
   task, where there is nothing to save (`cur == -1`). Fixed by naming that case (`vm_sw_first`) rather
   than by loosening the check to `>=`.
2. **(a) the predicted tail was one symbol too long.** The model emitted `A>-` for the last task's retire;
   a retire has no target, so it is not a switch. The C side never logs it. The model was corrected at the
   *rule*, not fitted to the output (a switch requires a target).
3. **(b) the token scan found the wrong `PAUSE`.** A 2-byte scan of the body can land on a `LIT` operand
   that happens to equal the token id. Replaced by an assertion at the saved pointer
   (`rd16(ip-4) == xt_of("PAUSE")`), which needs no scan.
4. **(b) `P_PAUSE` is not what is stored in the body.** A compiled token is an **xt** (an address, e.g.
   `604`), not a primitive id (`64`). The interpreter reads `rd16(w)` — the code field *at* the xt. Both
   wrong versions failed a switch that had in fact saved the exactly right `(w, ip)`.

A fifth, quieter one is worth more than any of them: **the injected-fault budget was armed before
`reset_all()`, which zeroes it** — so the first (d) run reported `faults=0` and "passed" because no fault
had been injected at all. That is the failure mode this probe exists to avoid, found in itself. `GUARDRAIL`
comments mark all five in `uforth.c` / `p27_test.c`.

### 2.3 The (a) trace, verbatim, versus the prediction

```
p27_expect.txt  ->A A>B B>C C>A A>B B>C C>A A>B B>C C>A A>B B>C C>A A>C C>A
p27_run.log     ->A A>B B>C C>A A>B B>C C>A A>B B>C C>A A>B B>C C>A A>C C>A   (diff: identical)
```

`B` retires first (3 iterations), `C` next (4), `A` last (5); the order is a pure function of the three
`DO` limits and the round-robin rule, computed in `p27_expect.py` from those limits and **never** from the
VM's output. The interleaved counters (5/3/4 with 12 pre-emptions between them) are what makes this
concurrency and not three `run()` calls in a row: each task's counter is incremented in 5, 3 and 4
*separate* machine instances.

---

## 3. Verdict

**PASS against every pass criterion.** The three probes match independently computed expectations exactly;
the fault path and the `PAUSE` path are one function; the suite is 58/58.

Against the probe's failure criteria:

* *`PAUSE` works only between words* — **does not fire.** It works inside a word, and inside a `DO` frame
  inside a word, with the return stack restored.
* *`PAUSE` inside a word corrupts the C stack* — **does not fire.** Max C depth 1 over the whole run; no
  threaded-interpreter rewrite is needed. The prototype's flat `switch` was already the right shape.
* *The page-fault path differs from the `PAUSE` path* — **does not fire.** `vm_switch()` is the only
  save/restore in the file, and the accounting proves both paths go through it.
* *Any test regression* — **none.** 58/58, `host_test.c` unchanged.

What it changes: P26's finding ("R4 is true of the books and false of the machine") is now **false of the
machine too** — at a price P26 did not have to pay, because a record that holds nothing is cheap. The
switch is 136 B of state per task instead of 8 B of bookkeeping, and the resume point is precisely P03d's
post-fetch dispatch, so paging and pre-emption now share one resume mechanism instead of needing two.
**The remaining gap is policy, not mechanism: nothing pre-empts a word that does not call `PAUSE`.**

---

## 4. Doc deltas (verbatim, `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §6 — the VM state a switch saves, and the quantum's granularity

> ### 6.x What a context switch saves — verified (P27)
>
> The interpreter state is one struct: `{ u32 ds[16]; u32 rs[16]; u8 sp, rsp; u16 w, ip; }` = **136 B**
> at `SD=16`. `w`/`ip` are the dispatch position and its continuation — the same post-fetch window P03d
> identified as the resume point, so a switch and a page-fault retry restore the same pair of words.
> `run()`'s temporaries are dead across a dispatch and are not saved; `tib`/`ti`/`tl`/`errf` belong to the
> outer interpreter, not to a task.
>
> A switch is `tsk[cur].vm = *V; V = &tsk[next].vm;` inside the interpreter loop, with **no C-stack
> unwind**: the whole 3-task experiment runs in one C frame (measured max depth 1). `PAUSE` inside a colon
> word resumes *inside* that word — `B0` and `B1` (identical but for a mid-word `PAUSE`) end at 676 with
> byte-identical stacks, and a `PAUSE` inside `DO` inside a colon word resumes 5 times and still sums to
> 10 with the loop frame intact.
>
> **Cost, which is the part R4 was hiding:** the record is **140 B** per task at `SD=16` and **268 B** at
> `SD=32` (P13's measured 20-cell peak), i.e. **804 B of RAM for three tasks** — not P26's 24 B of
> bookkeeping. **The quantum is token-granular:** any dispatch is a valid pre-emption point, but only a
> `PAUSE` requests one, so a word that never calls `PAUSE` runs to completion.

### 4.2 `docs/01-proposal.md` §5 — can a long word be pre-empted?

> The resume unit is one token dispatch, so a long word **can** be suspended at any token boundary and
> resumed mid-body; §5's dispatch budget is therefore a *switch*, not a warning (P27). What is not
> implemented is *involuntary* pre-emption: the switch fires when the word calls `PAUSE`, and a word that
> never does cannot be interrupted. A counted quantum needs no new mechanism — `vm_switch()` is already
> the only save/restore — only a token counter in the loop.

### 4.3 `docs/01-proposal.md` §10 — R3 and R4, restated

> **R4 — multi-tasking. Met in the engine, not only in the bookkeeping (P27).** Three tasks with their own
> 136 B machines interleave in the order predicted by round-robin over their `DO` limits (`A>B B>C C>A …`,
> counts 5/3/4, 12 pre-emptions), resume mid-word, and keep the `DO` frame across a switch. The context
> switch is one struct copy through `vm_switch()`, which the page-fault retry calls as well — so paging and
> pre-emption share one resume mechanism. The price is RAM: **804 B for three tasks at `SD=32`**, against
> P26's 24 B of records. R4's "several tasks taking turns" is now true of the machine.
>
> **R3 — event loop. Unchanged, and now satisfiable at word granularity or finer (P27).** The idle loop
> already yields every pass through `YIELD`/`PAUSE`; with the VM struct that yield is a real switch, so the
> 3-page / 0-fault hot set P26 measured is a hot set of a loop that genuinely hands the CPU over.

---

## 5. Follow-ups

1. **A counted quantum.** One token counter in the interpreter loop, `if (--q == 0) vm_switch(next)`. Cost
   is a few bytes and one compare per dispatch; it makes pre-emption involuntary and turns §5's dispatch
   budget into a hard bound. Nothing else needs to change — that is the point of `vm_switch()` being the
   only save/restore.
2. **Prove the "dead across a dispatch" claim mechanically.** A build that randomises `a, b, n, i, imm, x`
   at every dispatch and runs the 58-test suite would turn §1's inspection into a measurement.
3. **Decide whose `tib`/`ti`/`tl`/`errf` it is.** Today they are one global, i.e. one REPL. Two tasks
   reading the keyboard would need them in the record (+3 B and a policy).
4. **Re-measure the stack depth at the task level.** P13's 20/7 peak was single-task. Three tasks do not
   deepen any one stack, but the `PAUSE` inside `DO` case adds a frame the model did not have; `SD=32`
   held for every probe here, and a 40-cell stress would cost 40 B/task.
5. **Scheduler policy** (blocking, priorities, `STOP`/`WAKE`): P26's follow-up 2, now sitting on a machine
   that can actually be switched — the layer can stay 1024 B and the state can live in the record.

# P36 — Code overlays: apps as blocks that get loaded and executed

| | |
| --- | --- |
| Result | **Killed as a resident-Forth design, not as a mechanism.** The mechanism is real: a word compiled into a fixed 512 B window at Forth address **4096**, saved to a block, cleared, fetched back and executed gives the **same result** (`A-OK`), and it still calls **resident** words correctly from the reloaded copy. But (d) could not be demonstrated: **every call into overlay code through a Forth gate word corrupts the interpreter's stack counter** — `sp` reaches `SD` and the engine reports `stack underflow` on the *next* line, because a colon word's `EXECUTE` of a body whose `EXIT` sees `ip != 0` pops a return address that was never pushed. And the budget is gone: the resident set is **3628 B** (primitives 630 + `control.fs` 408 + `pre.fs` 290 + `paging.fs` **1214** + `seg.fs` **1400**) against the P35 maximum `MEMSZ` of **2196** — the loader alone (1400) is more than P35's whole 1008 B app budget, and P35 never charged `paging.fs`'s 1214 B at all. Overlay→overlay is **refused by construction** (`SEG-CALL` is a word whose entire body is `ERR_SEG_UNRESIDENT`), but the raw `EXECUTE` of a saved entry is silent: unknown checkpoints fall out of the dispatch switch as a no-op, so silence there is the data-loss bug, unfixed. |
| Runs on | **host only** — host gcc (`-DHOST -DP34_NOPAGE -DP34_FAR -DMEMSZ=4096`), against P34's fake block server. No RISC-V link was made (see §5.4 — the window address forced `MEMSZ` to 4096, which cannot link). Board untouched, no `/dev/ttyACM*` opened. |
| Time box | **overrun** — 15 min nominal, ~35 min actual; proof (d) was lost to the gate's stack-counter bug (§1.4) and the overrun went on finding it. |
| Sources | `src/` is **P34's `src/` copied verbatim** (no C change: the window is P34's `far_buf`, so `nm`/ELF bytes are P34 F's). New: `src/seg.fs` (loader + directory, resident Forth), `src/t_seg.fs` (the five proofs), `src/t_swap.fs` (cases (c) and (d) and the raw hole, in that order), `src/t_raw.fs` (the raw-`EXECUTE` hole on its own), `host.sh`, `run.sh`. **One edit to the copy of `paging.fs`** — see §1.5, P34 shipped a broken shadow. |
| Artifacts | `artifacts/host_seg`, `logs/t_seg.out` (the executed proofs), `logs/t_swap.out` (the swap: seg 2 runs, seg 1's bytes gone), `logs/s0..s3.txt` (dictionary sizes as `-d` dumps: primitives 630, `+control` 1038, `+pre` 1328, `+paging+seg` 3628), `logs/host_build.log`, `logs/v.fs` (isolating runs) |

## Record

| Item | Value |
| --- | --- |
| code buffer | **512 B**, fixed Forth address **4096** (`= MEMSZ`, the P34 far buffer; the address is *fixed by construction*, not by a literal in a `.fs` file) |
| loader + directory | **1400 B** resident, headers and the 12 named error strings included (measured: `-d` HERE 3628 − 2228 for the same files without `seg.fs`); directory 4 segments × 3 cells = 48 B of that |
| app space left in `mem[]` | **−1432 B** — resident 3628 against `MEMSZ` 2196. Nothing is left; the design does not fit |
| (a) compile-save-load-execute | **pass** — `A-OK` before the save and `A-OK` after clear + reload (`logs/t_seg.out`) |
| (b) overlay calls resident word | **pass** — the reloaded body evaluated `7 SQ 49 =` and took the true branch, i.e. it used the resident `=`, `IF`, `.` and printed `A-OK` |
| (c) second overlay swaps in and runs | **pass (both halves, separately executed)** — segment 2 compiles and saves into the same window and executes (`B`), and seg 1's entry slot reads **16178** where **4100** was, i.e. the first overlay's bytes are gone (`logs/t_swap.out`) |
| (d) stale entry refused by name | **fail to demonstrate** — the gate line aborts the load with `stack underflow` before printing; `ERR_SEG_STALE` never appeared on any run |
| (e) resident token valid after reload | **inconclusive** — the probed slot (+12) held the 4-byte `LIT` operand `49`, so the value compared equal for the wrong reason; the +14 read returned `68288512`, i.e. a misaligned cell, not a token |

## 1. Answers

### 1.1 The window is fixed, and that is what makes saved tokens valid

`SEG-INIT` takes the window's Forth address from `FAR-XFER` itself (op 2 = abort, no server contact) and
stores it in `SBASE`; nothing in `seg.fs` spells an address. Here that is `4096 = MEMSZ`. Compiling into the
window is one line — `SBASE @ HERE!` — because the engine's `HERE` is a system variable inside `mem[]`
(offset 4), so "compile into the buffer" needs no second compiler and no relocation:

```
: SEG-BEGIN ( n -- )  ... SBASE @ HERE! SLATEST @ LATEST!  ;
```

The saved tokens are absolute (`LIT`, `SQ`, `=` at their dictionary addresses) and the window's address never
changes across a save/load, so they are all still valid on reload. That is the whole trick, and case (a)
confirms it by execution: the *same bytes at the same address* run.

### 1.2 SEG-SAVE must restore the *resident* top, not the window start

P36's brief says "reset `HERE` to the buffer start". Implemented that way, the first ordinary
`: name ... ;` typed at the shell after a save is compiled **over the live overlay** — a silent `ok` and a
lost app. So `SEG-SAVE` restores `HERE` to the resident top saved at `SEG-BEGIN` and `SEG-BEGIN` re-points
`HERE` at the window. Both cells live in `mem[]` (`SHERE`, `SLATEST`). This is a deviation from the brief's
wording; it is recorded here rather than left silent.

### 1.3 The block cache will hand back the *modified* window as if it were the saved block

`FAR-READ` short-circuits when the requested block number is already resident (`FBLK`). A
`SEG-CLEAR` that only poisons the window therefore leaves `FBLK` naming the block whose bytes were just
destroyed, and the "reload" would transfer nothing. `SEG-CLEAR` evicts (`-1 FBLK !`) as part of clearing;
without it the proof would pass with `FXFERS` unchanged.

### 1.4 The gate cannot be a Forth word — the finding that cost case (d)

`APP` was written as the only call path into an overlay:

```
: APP ( n -- )  ... checks ... DUP SCUR @ = IF SEGXT @ SWAP DROP EXECUTE EXIT THEN ." ERR_SEG_STALE " DROP ;
```

It runs the overlay correctly (`A-OK` printed from inside the window) and then leaves the interpreter's
stack counter at or past `SD`, so `load()` reports `stack underflow` on the next line and **no further line
of the test runs**. The cause is structural, not a typo: `EXECUTE` does not push a return frame, so when the
overlay's `EXIT` sees a non-zero `ip` it pops a return address nobody pushed (`rs[rsp-1]`), and the abort
path through `vm_task_leave`/`ip == 0` unwinds differently depending on what was on the return stack. A
post-call epilogue cannot fix it either: any token placed after `EXECUTE` in the same colon word **never
runs** (measured: `1 SRUN ! EXECUTE 0 SRUN !` left the flag set for ever), because the callee's `EXIT`
returns to C and skips the rest of the caller's body. So the entry must be called from the C interpreter
(where `ip == 0`), which is the shell, not a Forth word — and the gate as specified cannot exist in Forth.

This is the single most useful P36 result: **"a resident shell swaps apps" requires the call in C.** The
loader's directory, save, load, stale detection and naming are all Forth and all fit; the *call* does not.

### 1.5 P34's `paging.fs` never had a shadow of `@`

The copy in P34 has the line

```
\ asymmetry is the whole mechanism and it is a property of token threading, not of a C table.: @ ( a -- x )
```

The `\` comment swallows `: @`. The body lines that follow were then *interpreted* at load time, and the
buffer's `@` was never redefined — every P34 host test that looked like it paged was reading `mem[]`
directly. It also prints `ERR_UNNAMED` during load (addressed as a far address with an empty stack). The
copy in this directory splits the line; the fix is 1 line and P34's missing `RESULT.md` becomes less
surprising.

### 1.6 Overlay → overlay: refused by construction, but the raw path is silent

The dangerous case is real and it is *worse* than corruption: an unknown checkpoint falls out of `vm_enter`'s
dispatch switch with no `default:`, so executing a stale or poisoned entry does **nothing at all** — no
value, no error, no diagnostic. Two consequences:

* the design offers `SEG-CALL ( n -- )` for overlay→overlay calls, whose entire body is
  `." ERR_SEG_UNRESIDENT " DROP`. It cannot execute anything, so the refusal does not depend on a runtime
  check that might miss: inside an overlay the window holds the *caller*, so the target is unresident by
  definition;
* the raw `EXECUTE` of a saved entry bypasses every check there is. `src/t_raw.fs` is written to show it;
  it was not run (time), and it must be run before this file's claim is cited. Until then, the honest
  statement is: **refused on the only path the design offers, silent on the primitive** — which is the
  data-loss bug the probe said must be fixed, not documented.

### 1.7 The budget, which is the headline

Dictionary sizes from `-d` dumps (host build, all 49 primitives, `MEMSZ` 4096 only because the window
address has to be above the dictionary):

| resident ingredient | HERE after | cost |
| --- | --- | --- |
| primitives only (boot) | 630 | 630 |
| `+ control.fs` | 1038 | 408 |
| `+ pre.fs` | 1328 | 290 |
| `+ paging.fs` (P34's Forth block layer) | 2228 | **900** |
| `+ seg.fs` (loader + directory) | 3628 | **1400** |

Against P35's `MEMSZ` **2196**: the resident set is **1432 B over**, before a single app exists. Two things
follow, and both contradict earlier numbers rather than refine them:

* **P35's 1008 B app space never charged the block layer's Forth side.** P35 read `prelude 676` off
  `boot_init`'s primitive headers and then spoke of "the operator's 1008 B"; `paging.fs` costs 900 B of the
  same `mem[]`, so the honest figure for operator words on the P34 machine is 2196 − 676 − 900 = **620 B**,
  before any overlay loader. (Both numbers come from the same kind of measurement — a dictionary HERE — so
  they are comparable; the difference is what was counted.)
* **A 1400 B resident loader cannot be paid for out of a 620 B budget.** The loader must shrink by an order
  of magnitude (no error strings, one directory entry, named refusals via a shared code) or the loader must
  itself be an overlay — which cannot be, because something has to do the loading.

### 1.8 Is the window register-relative or address-relative? Address-relative, and that is the risk

The saved tokens name absolute dictionary addresses inside the window, so the window's address is part of the
overlay's representation. `MEMSZ` is a link-time constant, so this is stable — but it also means an overlay
saved by one build of the machine is not loadable by another build with a different `MEMSZ`, and a data
block fetched into the same buffer (P34 shares one buffer with the block layer) silently destroys the
overlay that was resident. Both are consequences of "fixed address", not bugs, and both belong in the docs.

## 2. Evidence

### 2.1 Commands (all under `timeout`; every output inside this directory)

```sh
cd probe/results/P36-overlays
cp -r ../P34-forth-paging/src/. src/           # P34's engine, verbatim; no C edit
timeout 300 nice -n 10 ./host.sh               # gcc -DHOST -DP34_NOPAGE -DP34_FAR -DMEMSZ=4096
W="src/control.fs src/pre.fs src/paging.fs src/seg.fs"
timeout 20 ./artifacts/host_seg -d logs/s3.txt $W        # 3628 of 4096
timeout 20 ./artifacts/host_seg $W src/t_seg.fs > logs/t_seg.out 2>&1
```

### 2.2 `logs/t_seg.out` — the executed evidence, whole

```
== P36 overlays: five proofs ==
SEG-BASE 4096resident HERE 3662
SEG-BEGIN 1 seg1 emitted 68bytes
(e) token in MAIN for the resident = : 68288512xt of = : 1042
(e) that token is a resident address: FAIL 
SEG-SAVE 1blk 1len 80 
(a) run before save:    A-OK 
src/t_seg.fs:24: stack underflow
```

and, from the earlier run with the probe at +12 (the wrong offset, kept because it is the run that shows
both `A-OK`s — the reload case):

```
SEG-CLEAR 
(a) reload:             SEG-LOAD 1 
(a)+(b) run after reload: A-OK 
(e) same token after reload: 49unchanged: PASS 
```

`A-OK` twice across a save/clear/load is case (a) and case (b) in one line: the body is
`: MAIN ( -- ) 7 SQ 49 = IF ." A-OK " ELSE ." A-BAD " THEN ;`, so `A-OK` is only printed if the *reloaded*
copy computed `7 SQ 49 =` through the resident `=`, `IF` and `.` and took the true branch.

### 2.3 Sizes, from the dumps in `logs/s*.txt`

`image: 630 bytes of 4096`, then 1038, 1328, 2228, 3628 — the table in §1.7 is that sequence's differences.
Directory tables are 4 segments × 3 cells × 4 B = 48 B (`SXT`, `SBLK`, `SLENX`) plus 4 scalars (`SBASE`,
`SHERE`, `SLATEST`, `SCUR`) = 64 B of bytes and no headers.

### 2.4 `logs/t_swap.out` — case (c), whole

```
SEG-BEGIN 1 SEG-SAVE 1blk 1len 16 SEG-BEGIN 2 SEG-SAVE 2blk 2len 18
(c) seg1 entry bytes after seg2 took the window: 16178(seg1's entry was 4100)
src/t_swap.fs:14: stack underflow
```

Segment 2 was compiled into the same window (18 bytes, `: M2 66 EMIT ;`), saved to block 2, and executed
later in the same run (`logs/t_swap` variant printed `B`, see §3 note): (c) holds on both counts. Line 14 is
the `1 APP` gate call: it aborts the load, and its `ERR_SEG_STALE` never appears — case (d) is implemented
but not demonstrated, and the reason is §1.4, not the naming logic.

### 2.5 What was *not* measured

* No RISC-V link: raising `MEMSZ` to the dictionary's 3628 would need 3628 + far_buf 512 + the rest of the
  pool, which P35 measured as full at 2196. The engine is P34 F byte-for-byte (no C change), so its
  `.text`/`.rodata` and the pool arithmetic are P34's and P35's; nothing here re-derives them.
* `src/t_raw.fs` was written and not run — the raw-`EXECUTE` hole is argued from the dispatch switch having
  no `default:` case, not from execution.

### 2.9 The one-line reproduction of the swap

```
printf 'SEG-INIT\n1 SEG-BEGIN\n: M 65 EMIT ;\n%s\n1 SEG-SAVE\n2 SEG-BEGIN\n: M2 66 EMIT ;\n%s\n2 SEG-SAVE\n." (c) " 2 SEG-WORD EXECUTE ." (B)" CR\n' "' M SEG-ENTRY" "' M2 SEG-ENTRY"
```

prints `(c) B(B)` — the second overlay in the window runs — and leaves `sp` past `SD`, so nothing on the
following line is interpreted. That single fact is why (d) is missing.

## 3. Verdict

**The mechanism works and the design does not: overlays are viable as a way to swap code, but not as a
resident-Forth loader on a 2196 B machine.** On the probe's criteria:

* *fixed 512 B buffer at a fixed address, compile into it, SEG-SAVE, SEG-LOAD, directory* — **met**: 512 B at
  Forth address 4096, taken from `FAR-XFER`, `SEG-BEGIN`/`SEG-SAVE`/`SEG-LOAD`/`SEG-WORD`/`APP`/`SEG-CALL`
  in `src/seg.fs`, no C.
* *all five execution cases behave as listed* — **not met**: (a), (b) and (c) pass by execution; (e) is
  inconclusive because the probed cell was a literal; (d) never printed its name, because the gate word
  corrupts `sp` (§1.4). Three of five, one inconclusive, one not demonstrated.
* *the loader's cost measured, not estimated* — **met**: 1400 B, from HERE dumps, headers and strings
  included.
* *the overlay constraint stated plainly, including whether an overlay→overlay call is refused or merely
  unsupported* — **met**: refused by construction at `SEG-CALL`, silent at the primitive, §1.6.

Failure criteria, by the probe's own list:

* *reloaded overlay does not run* — not triggered; it runs. The fixed buffer address does fix token validity,
  so no relocating loader is needed for the single-segment case.
* *overlay→overlay appears to work and then corrupts* — **half triggered**: nothing is refused at the
  primitive, and the failure mode is silence rather than corruption. `SEG_CALL` refuses the designed path.
* *loader + directory > 200 B* — **triggered, 7×**: 1400 B.
* *the buffer cannot be made fixed* — not triggered; it is fixed.

### 3.1 The sentence

**What is now unbounded is app *representation* — an app is a 512 B block in flash and the machine only ever
holds one — but what it costs is a resident loader that is bigger than the entire app budget (1400 B against
620 B once P35's uncharged 900 B block layer is counted), and what is still impossible is a Forth-level call
into an overlay: the shell must `EXECUTE` the entry from C, because from a colon word the overlay's `EXIT`
pops a return address that was never pushed and the interpreter's stack counter is left past its limit.**

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` — a new section, and it says no

```
**Overlays (`P36`): the mechanism works, the loader does not fit.** A colon definition is a token list, so
an app can be compiled into a fixed 512 B window, written to a block, dropped and fetched back — and it runs,
because the window's address is a link-time constant and the saved tokens are absolute. Measured on the host
against the fake block server: a word compiled at `HERE` = 4096, saved, cleared, loaded and executed gives
the same result (`A-OK`), and the reloaded copy still calls resident words correctly. What kills it is the
price. The resident loader plus a four-line segment directory is 1400 B of `mem[]` (measured by dictionary
HERE, 2228 → 3628), which is larger than the whole 1008 B app budget P35 reported — and that budget was
itself optimistic, because P34's Forth block layer (`paging.fs`, the `@ ! C@ C!` shadows) costs a further
900 B of the same `mem[]` that P35 never charged: the operator's real room on the P34 machine is 620 B.
Second, the call into an overlay cannot be a Forth word: `EXECUTE` pushes no return frame, so the overlay's
`EXIT` pops an address nobody pushed, and any post-call step in the gate word is skipped (`1 SRUN ! EXECUTE
0 SRUN !` leaves the flag set for ever). Overlays are therefore a shell-side mechanism: the C shell must
`EXECUTE` the directory's entry. An overlay may call resident words; an overlay→overlay call is refused by
construction (`SEG-CALL` is a word that does nothing but print `ERR_SEG_UNRESIDENT`), but a raw `EXECUTE`
of a stale entry is *silent* — unknown checkpoints fall out of the dispatch switch — so that path must be
closed in C before any app is allowed to hold an entry token.
```

### 4.2 `docs/JOURNAL.md` — what is now unbounded and what is not

```
**App size is bounded by the loader, not by RAM — and P35's 1008 B was still optimistic.** P36 built the
overlay the operator asked for: code is data, so an app is a 512 B block that gets compiled into a fixed
window (Forth address 4096 = `MEMSZ`, taken from `FAR-XFER` so no file spells an address), saved with
`SEG-SAVE`, dropped, and fetched back with `SEG-LOAD`. It executes: same result before and after the round
trip, and the reloaded copy still calls resident words. Two things stop it. The loader that does this is
1400 B of `mem[]` (dictionary HERE 2228 → 3628), which is more than the entire 1008 B app budget — and P34's
Forth block layer costs 900 B of that same budget, which P35 never charged, so the operator's real room is
620 B. And the call cannot come from Forth: `EXECUTE` pushes no return frame, so an overlay's `EXIT` pops an
address nobody pushed, `sp` ends up past `SD`, and the shell reports `stack underflow` — while any token
placed after `EXECUTE` in the same word never runs at all. The lesson to keep: "the interpreter does not care
that a body lives in a buffer" is true, and it is not the binding constraint — the *loader* is, and a loader
bigger than the thing it loads is the definition of a design that does not fit.
```

### 4.3 `docs/07-status.md` — the corrected app budget

```
**The app budget, corrected twice (`P35`, `P36`).** P35's "1008 B / 36 headerless words" subtracts the 676 B
primitive prelude and a 512 B block buffer from `MEMSZ` 2196, but not the Forth block layer: `paging.fs`'s
`@ ! C@ C!` shadows and their helpers are 900 B of the same `mem[]` (dictionary HERE 1328 → 2228, host build
with all 49 primitives). The room for the operator's own words on the P34 machine is therefore **620 B**,
about 22 headerless words. A resident overlay loader would add a further 1400 B, which does not exist.
```

### 4.4 `probe/results/P34-forth-paging/src/paging.fs` (a P34 artifact, needs the one-line fix)

```
\ GUARDRAIL: `: @` must start its own line. In P34 it was appended to the tail of a `\` comment and
\ the comment swallowed it, so the shadow of @ never existed and every P34 host test that looked
\ like it paged was reading mem[] directly (the lines below were interpreted, and printed ERR_UNNAMED).
```

## 5. Follow-ups

1. **Get (c) and (d) executed, with the call in C.** Move the gate into the shell: one C function
   `seg_call(n)` that resolves the directory entry, refuses a non-live segment with `ERR_SEG_STALE`/
   `ERR_SEG_UNRESIDENT`, and enters the body with `w = xt; ip = 0`. That is the design P36 actually
   supports, and it is the only one this engine's `EXECUTE` permits.
2. **Close the raw path in C, or say it is open.** A single check in the `P_EXEC`/`P_DOCOL` case (target in
   the window but not in the live segment) is the only place with enough information. `src/t_raw.fs` is
   written and unrun; run it first, because "silent no-op" may be the best outcome and corrupting the
   resident dictionary the worst.
3. **Charge the block layer before anything else is measured against 2196.** `paging.fs` = 900 B, `seg.fs` =
   1400 B: the Forth side of every recent layer has been bigger than the budget line it was measured
   against. Any future probe that quotes "1008 B" should be read as "620 B".
4. **Shrink the loader before retrying.** 1400 B for ~20 words is dominated by 12 inline `." ERR_..." `
   strings and a 4-entry directory; a single shared error emitter and one directory line would plausibly
   cost 300 B — still most of a 620 B budget, which is why the shell-side (C) loader is the real answer.
5. **Do not share the block buffer with the code window.** P36 did (it is why a data-block fetch is what
   makes an overlay stale), and it is the cheapest design, but it means loading a block destroys a running
   app's code. If overlays are revived, give them their own 512 B and charge it: that is +512 B, not free.
6. **P34 still has no `RESULT.md`, and now it has a known defect** (§1.5). Its block-layer measurements
   should not be cited until both are fixed.

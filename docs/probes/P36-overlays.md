# P36 — Code overlays: apps as blocks that get loaded and executed

| | |
| --- | --- |
| Runs on | **host only** (build + link + host execution) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P34 (Forth paging), P35 (`MEMSZ` 2196, 1008 B of app space) |
| Blocks | the productivity-suite question: whether total app size is bounded by RAM |
| Serves | R1, R5 |

## Question

The operator's observation is the right one: **code is data.** A colon definition is a token list, so it can be
saved to a block, cleared, and loaded back — and the interpreter will execute it as long as it sits in RTC RAM.
That makes *total app size* independent of RAM: resident core in `mem[]`, apps as **overlays** swapped through a
fixed code buffer.

Does that work, what does the loader cost, and what exactly refuses to work?

## Why it matters

If overlays work, the machine is a 1980s handheld: a resident shell plus a screen of code per app, with apps and
their data living in flash. If they do not, the program is 36 words and a productivity suite is out of reach.

## Given — do not re-derive

* P35: non-paged `MEMSZ` **2196**, prelude 676, block buffer 512 ⇒ **1008 B / 36 words** for the app.
* P32: 16-bit tokens, 64 KB dictionary address space (not the binding limit — RAM is).
* P16: 512 B block fetch **144 µs**; one outstanding request only.
* P27: the interpreter resumes at a dispatch; `PAUSE` and the fault path share `vm_switch`.
* The interpreter walks `ip` through RTC RAM and does not care that a body lives in a buffer.

## Method

1. Copy P34's tree into `probe/results/P36-overlays/`. Add a **fixed 512 B code buffer** in the pool, at a fixed
   address, and a way to compile into it (`HERE` pointing at the buffer) — the buffer address must be stable, or
   every saved token is wrong.
2. Implement, in Forth where possible:
   - `SEG-SAVE ( block -- )` — write the compiled region to a block and reset `HERE` to the buffer start;
   - `SEG-LOAD ( block -- )` — fetch the block into the buffer, leaving the region executable;
   - a **segment directory** (`SEG#` → entry xt) so code can call "app 2's main word" without hardcoding.
3. **Prove, by execution on the host** against a fake server:
   (a) compile a word into the buffer, save it, clear it, load it back, and **execute it** — same result;
   (b) the reloaded overlay **calls a resident word** (the shell or a prelude word) and gets the right answer;
   (c) a **second overlay** loads into the same buffer and runs, and the first one's bytes are gone;
   (d) after the swap, calling the first overlay's entry is **refused with a named error**
       (`ERR_SEG_STALE`), not silently executed;
   (e) a token inside a saved overlay that pointed at a *resident* word is still valid after reload
       (show the token value unchanged).
4. Report: loader + directory size in headerless bytes, the buffer cost, and the resulting app space in `mem[]`.
5. State the honest limit in one sentence: **what is now unbounded** (apps in flash, swapped through 512 B) and
   **the constraint on overlays** (they may call resident words; a call from one overlay to another cannot work,
   because the target is not resident — say whether the design refuses it or documents it).

## Record

| Item | Value |
| --- | --- |
| code buffer | bytes, fixed address |
| loader + directory | headerless bytes |
| app space left in `mem[]` | bytes |
| (a) compile-save-load-execute | pass/fail, same result |
| (b) overlay calls resident word | pass/fail |
| (c) second overlay swaps in and runs | pass/fail |
| (d) stale entry refused by name | pass/fail, error name |
| (e) resident token valid after reload | pass/fail, token value |

## Pass criteria

* all five execution cases behave as listed;
* the loader's cost measured, not estimated;
* the overlay constraint stated plainly, including whether an overlay→overlay call is refused or merely
  documented as unsupported.

## Failure criteria — and what each changes

* **A reloaded overlay does not run** ⇒ token addresses depend on where the code was compiled; report the delta
  and whether a fixed buffer address fixes it. If it does not, overlays need a relocating loader and the design
  must say so with a cost.
* **Overlay→overlay calls appear to work and then corrupt** ⇒ that is the dangerous case. Report it loudly and
  make the design **refuse** it (`ERR_SEG_UNRESIDENT`), because silence there is a data-loss bug.
* **Loader + directory > 200 B** ⇒ say so; apps then cost 200 B of the 1008 before any app exists.
* **The buffer cannot be made fixed** ⇒ overlays are not viable on this machine and the suite must fit in 1008 B
  resident.

## Doc deltas to hand back

* `docs/01-proposal.md` — a new section on the overlay model, or the statement that it does not work.
* `docs/JOURNAL.md` — what is now unbounded and what is not.

## Do not

* Do not let a stale overlay execute. A refused call with a name is the only acceptable outcome.
* Do not touch the board, `docs/`, or other probes' directories.

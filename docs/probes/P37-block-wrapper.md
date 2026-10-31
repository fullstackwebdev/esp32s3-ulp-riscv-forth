# P37 — Why does the Forth `BLOCK` wrapper hang?

| | |
| --- | --- |
| Runs on | **host only** |
| Time box | **15 min**, one run, hard cap |
| Depends on | P33 (protocol passes 4/4, wrapper hangs) |
| Blocks | the block store, and therefore documents, `SAVE`, `LIST` — and the port |
| Serves | R5 |

## Question

P33's protocol path works: `BLOCK` returns the right bytes, `UPDATE`/`SAVE` write back, the named failures fire.
But the **Forth wrappers** — the words a program calls — **hang**. Two candidate causes, and they point in
opposite directions:

* **(H) Harness:** the fake server only runs *between* interpreter steps, so a synchronous spin waiting for
  `rsp_seq` can never be serviced. On the chip this same spin is fine: a fetch is 144 µs inside a multi-millisecond
  wake, and the main core answers.
* **(L) Language:** words compiled at that `HERE` have a real branch/operand bug, so the spin never terminates
  even when the answer arrives.

Until this is answered, "the block layer works" is a protocol claim, not a language claim.

## Given — do not re-derive

* P33: region need 7071 of 7856; block words **456 B**; buffer 512 B inside `mem[]`; protocol 4/4 on the fake
  server; wrappers `BLOCK`/`SAVE` hang.
* P16: 512 B fetch **144 µs**, deterministic, **one outstanding request only**.
* P34: the Forth layer can call resident words and branch correctly in *other* words (its reloaded overlays ran
  and evaluated `7 SQ 49 =`), so compiled branches are not broken in general.
* P20: a dispatch is 726 cycles.

## Method

Three experiments, cheapest first. Each must run with a hard `timeout` — a hang is the expected failure mode.

1. **Isolate the language from the mailbox.** Compile a Forth word that spins on a plain dictionary variable:
   ```forth
   VARIABLE FLAG
   : SPIN  BEGIN FLAG @ UNTIL ;
   ```
   Set `FLAG` from the host between interpreter steps, then call `SPIN`. If this hangs, the language is fine and
   the *harness* cannot run any spin (cause H, confirmed early). If it terminates, compiled loops work and the
   fault is in the mailbox wait.
2. **Service the mailbox during the spin.** Extend the harness so the fake server runs whenever the interpreter
   polls the response word — i.e. model "the main core answers while the ULP is still inside the word". Then run
   the real wrapper `BLOCK`. If it now completes with the right bytes, cause **H** is confirmed: the wrapper is
   correct and the harness was the lie.
3. **Bound the wait and see what it says.** Add a retry counter to the wrapper (in Forth, not C) that aborts with
   `ERR_NO_SERVER` after N polls. Then: does it reach the error, or does it hang before? Reaching the error means
   the loop runs and the mailbox never answers (H). Hanging means the loop itself is broken (L).

## Record

| Experiment | Result | Implication |
| --- | --- | --- |
| 1. plain variable spin | terminates / hangs | language vs harness |
| 2. mailbox serviced during the spin | completes / hangs | H confirmed or refuted |
| 3. bounded wait | reaches `ERR_NO_SERVER` / hangs | H or L |
| wrapper cycles per poll | | sanity against 726 |

## Pass criteria

* the two causes are separated by experiment 1 alone if possible;
* if cause H, the harness model is corrected so that the *same* wrapper word is exercised end to end;
* if cause L, the failing token position is named.

## Failure criteria — and what each changes

* **Cause L (a real branch bug)** ⇒ block words are not trustworthy until fixed; the port must not assume them.
  Report the token and the compiled body.
* **Cause H** ⇒ nothing is wrong with the machine, and the **design consequence is real**: a synchronous wait is
  only safe if the main core is guaranteed to answer inside the wake. Then the wrapper needs a published bound
  (`ERR_NO_SERVER` after N polls) and `06-repl.md`/`08-psion.md` must state that a block fetch can stall a wake.
* **Both** ⇒ say so; H explains the hang, L may explain the wrong bytes.
* **Neither (the spin terminates but returns wrong data)** ⇒ the protocol is being read out of order; report the
  sequence numbers.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.5 — the wrapper's status, and the bound if cause H.
* `docs/02-harness.md` §2 — if the harness must model a concurrently-running server, say how.
* `docs/JOURNAL.md` — the answer, because it decides whether the block store is trusted.

## Do not

* Do not add a C-level timeout to hide a Forth spin bug; the bound must be Forth, where a program can see it.
* Do not let a hang consume the box — every run gets `timeout`.
* Do not touch the board, `docs/`, or other probes' directories.

# P34 — Transparent memory, written in Forth

| | |
| --- | --- |
| Runs on | **host only** (build + link + host execution against a fake server) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P32 (variant D), P16 (144 µs per fetch), P33 (buffer cost) |
| Blocks | R5 in its original form — "any memory addressable, and the program does not know" |
| Serves | R5 |

## Question

The operator's question: **can the *language* provide the transparency, so the C side only moves bytes?**

The insight to test: in a token-threaded Forth, a colon word's body holds the **xt of the `@` that existed when
it was compiled**. So the prelude can be compiled against the raw primitive, and *afterwards* `@` and `!` can be
**shadowed** by colon words that page. Existing words keep the fast primitive; everything the user writes gets
transparency — for free, with no new C.

Does that work, what does it cost, and is the semantic hole (a far access that cannot be satisfied) closed with a
named abort rather than a wrong value?

## Why it matters

This is the difference between "we dropped R5" and "R5 works, and the program cannot tell". It also removes the
2466 bytes of frames/table/fetch-path entirely, because the paging decision moves from the interpreter's fetch
into a handful of Forth words.

## Given — do not re-derive

* P32: variant D engine 3916 B (language intact), region need 8656 of 7856; dropping frames+table+paged-fetch
  frees **2466 B** ⇒ **1666 B spare** (1346 with the C stack reserved).
* P16: 512 B fetch **144 µs** (2 740 cycles), deterministic, 3.55 MB/s; **one outstanding request only** — two in
  flight corrupt with a valid CRC.
* P23: doorbell wake 176 µs with the main core blocked.
* P26/P28: dictionary (`mem`) 908 B, resident need 676 B ⇒ **232 B of dictionary spare**.
* P20: a colon-word dispatch costs **726 cycles**; a primitive call inside it is another dispatch.

## Method

1. Copy P32's variant D into `probe/results/P34-forth-paging/`.
2. Remove frames, page table and the paged fetch path (as P33 does). Add **one** primitive that the C side must
   keep: `FAR-XFER ( op block -- status )` — write the request, bounded wait, copy 512 B to/from the buffer in
   the pool. Nothing else in C. State its size.
3. **The address convention**, in one line: bit 31 set ⇒ far address; `far = 0x8000_0000 + block×512 + offset`.
   The buffer sits in the pool as its own array, **not** inside `mem` (which is already 232 B from full).
4. **The shadowing**, in Forth, after the prelude is compiled:
   ```forth
   : @ ( a -- x )  DUP FAR? IF FAR@ ELSE RAW@ THEN ;
   : ! ( x a -- )  DUP FAR? IF FAR! ELSE RAW! THEN ;
   : C@ ... : C! ...        \ same shape
   ```
   plus the residency logic (`FAR@` compares the block number, calls `FAR-XFER` on a miss) and `FAR-ALLOT`
   which hands out far addresses. Written as Forth words, headerless bytes measured.
5. **Prove the shadowing does what it claims**: compile a word that uses `@` *before* the redefinition and one
   *after*, then show the first still calls the raw primitive (disassemble the two bodies or compare their
   tokens) while the second pages.
6. **Execute on the host** against a fake server, and report each:
   - a far read returns the server's bytes;
   - a far write followed by a far read of the same cell round-trips;
   - reading two different far blocks alternately works (and costs two transfers — count them);
   - the no-answer case **aborts the line with `ERR_NO_SERVER`** and does **not** return a value;
   - a second request while one is outstanding is refused (`ERR_BUSY`), never silently coalesced;
   - a resident `@` in a loop is *not* slowed by the wrapper (measure the token count of both bodies).
7. Report: engine delta vs D, the buffer's cost, the Forth wrappers' headerless bytes, the spare against the
   pool (both ways), and the cost of a *warm* far access in dispatches and cycles.

## Record

| Item | Value |
| --- | --- |
| engine delta vs D (after removing frames/table/fetch) | |
| `FAR-XFER` primitive | bytes |
| buffer | bytes, placement |
| Forth wrappers + residency + `FAR-ALLOT` | headerless bytes |
| dictionary spare after the wrappers (232 B available) | |
| pool spare (and with the C stack reserved) | |
| warm far access | dispatches, cycles |
| prelude word still uses the raw primitive | yes/no, evidence |

## Pass criteria

* the machine links with the language, three tasks, the console and the Forth paging words;
* **the shadowing demonstrably leaves pre-existing words on the raw primitive**;
* every execution case behaves as listed, with the two named failures;
* the cost of a warm far access stated in dispatches and cycles.

## Failure criteria — and what each changes

* **Wrappers exceed the 232 B dictionary spare** ⇒ say by how much; the options are a smaller residency logic, a
  bigger `mem` (paid from the pool spare), or accepting `F@`/`F!` as explicit names instead of shadows.
* **Shadowing does not isolate pre-existing words** ⇒ the token-threading assumption is wrong; report it, because
  it means the interpreter must distinguish "user" and "system" accessors some other way.
* **A warm far access exceeds ~30 dispatches** ⇒ scattering far accesses is impractical; the machine is
  block-oriented (copy in, work, copy out) and the documentation must say so rather than pretending.
* **`FAR-XFER` cannot be bounded** ⇒ the abort case must become a two-phase request, and the wrapper API changes.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.4 and §7 — R5's wording: transparency provided by the language, with the cost.
* `docs/JOURNAL.md` — the mechanism and what it costs.

## Do not

* Do not let a failed far access return a stale or zero value; the line must abort with a name.
* Do not hide a transfer count — a program that thrashes must be measurable.
* Do not touch the board, `docs/`, or other probes' directories.

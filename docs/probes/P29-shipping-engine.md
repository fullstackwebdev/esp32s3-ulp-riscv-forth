# P29 — The shipping engine: does it still fit with the switch in it?

| | |
| --- | --- |
| Runs on | **host only** (build + link) |
| Time box | **15 min**, one run, hard cap |
| Depends on | P22 (engine 3190), P27 (`vm_switch`), P28 (16-bit tokens, 232 B spare) |
| Blocks | the port to the chip — this is the last budget gate |
| Serves | R1–R5 |

## Question

P22 measured an engine of **3190 B** with **no context switch** and **no OS-layer C glue**. P27 then added
`vm_switch` (save/restore of 136 B of state, plus the fault path sharing it), and P28 bought three tasks with
16-bit tokens, leaving **232 B**. Does the engine that will actually ship still fit — with 16-bit tokens, the
resumable switch, the paging fault path, and the layer's four hooks (`pl_key`, `pl_emit`, `pl_hw`, `pl_halt`)?

## Why it matters

This is the gate. Every previous budget estimate in this project has been wrong in the same direction — round
estimates of code that had not been written. The 232 B is the smallest margin yet measured, and the two things
about to be added are exactly the things no estimate has covered.

## Given — do not re-derive

* P22: engine 3190 (`.text` 3010 + `.rodata` 180), `MEMSZ` 1188 at 1 task, 94 B spare, and the warning that
  four budget arrays were dead-store-eliminated in a first "successful" link — **confirm allocation with
  `nm -S`**.
* P27: `vm_switch` saves `ds[SD]`, `rs[SD]`, `sp`, `rsp`, `w`, `ip` = 136 B per task; record 140 B; `PAUSE`
  and the fault path are one mechanism.
* P28: 16-bit code tokens, 32-bit data cells; 3 tasks × 140 B out of the same pool; `MEMSZ` 908; resident
  need 676; **gap +232**.
* P26: the layer is Forth, so its *definitions* cost dictionary, but its hooks are C.

## Method

1. Build the shipping engine:
   - 16-bit code tokens (P02's `a16` variant), 32-bit data cells;
   - `vm_switch` and the fault path as P27 built them;
   - paging through `resolve()`/frames as P12/P22 did;
   - the four layer hooks, real (no stubs), driving a ring and a halt;
   - 4 × 512 B frames, `SD=16`, 320 B C stack, 128 B line buffer.
2. Link at `MEMSZ` 908 with the minimal layer (P26's 1024 B) compiled in **and** with the prelude only, so the
   engine's true cost is separated from the dictionary's.
3. Report `.text`, `.rodata`, `.bin`, and the **delta against P22's 3190**, broken down by what was added
   (`nm --size-sort` for `vm_switch`, the hooks, the 16-bit fetch path).
4. **Confirm allocation with `nm -S`** for every budget array — frames, page table, stacks, rings. A missing
   array means the compiler removed it and the link is a lie.
5. State the final gap: `MEMSZ` available vs resident need for 3 tasks.

## Record

| Item | Value |
| --- | --- |
| engine `.text` / `.rodata` / total | |
| delta vs P22's 3190 | |
| `vm_switch` + hooks + 16-bit fetch, bytes | |
| allocation confirmed by `nm -S` | yes / no, per array |
| `MEMSZ` at 3 tasks | |
| resident need | |
| **final gap** | |

## Pass criteria

* the engine links with the switch, the hooks and 16-bit tokens at `MEMSZ` 908;
* allocation confirmed by symbol, not by "it linked";
* the delta against P22 attributed to named symbols.

## Failure criteria — and what each changes

* **Engine > 3162 (i.e. the 232 B gone)** ⇒ name the overrun and the symbol that caused it. The candidates in
  order of plausibility: `vm_switch` inlining both stack copies, the fault path duplicating the switch, the
  16-bit fetch path adding a sign/mask step, or the hooks pulling in ring machinery. §4.3 changes, and the
  answer is likely "two tasks" or "paging the cold prelude" — with the measured cost.
* **Link fails outright** ⇒ report the exact message and the overrun. Do not trim the layer to fit; the layer's
  size is P26's measured result.
* **An array is missing from `nm -S`** ⇒ the link is invalid; report `FAIL` and fix the allocation before any
  size claim.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.3 — the shipping engine's measured size, the final gap, and the 3-task verdict.
* `docs/JOURNAL.md` — an entry naming the delta and where it went.
* `probe/EVIDENCE.md` — an entry with the symbol breakdown.

## Do not

* Do not stub the hooks, inline away the switch, or drop 16-bit tokens to make it fit. Report the overrun.
* Do not touch the board, `docs/`, or other probes' directories.

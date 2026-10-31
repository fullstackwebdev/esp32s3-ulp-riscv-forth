# 07 — Status report

**Date:** 2026-10-30 · **Scope:** snapshot at the end of the *first* probing wave (P01–P09) · **Board:**
ESP32-S3 rev v0.2, alive, running a probe image

> **This document is a snapshot, not the current state.** Everything after P09 — including the entire budget
> settlement, the OS layer, the task switch, event coalescing, the doorbell and the block-store decision — is in
> [`JOURNAL.md`](JOURNAL.md) (J-10 onward) and in `01-proposal.md` §4.3/§4.4. The numbers below that are marked
> *superseded* were correct when written and are kept only so the history reads straight.
>
> **Headlines that changed:**
>
> | Was (this doc) | Now | Source |
> | --- | --- | --- |
> | spare 94 B | **operator's program: 1008 B / 36 words** (paging dropped) | P35 |
> | `MEMSZ` 1188 | **2196** (or 1880 with the C stack reserved) | P35 |
> | paging transparent | **block store, visible or Forth-shadowed**; resident code is the bound | P32–P35 |
> | 3 tasks implied free | **140 B per task**, 3 tasks = 420 B | P27 |
> | page ~1 ms | **144 µs** per 512 B fetch | P16 |
> | "one definition per page" | 4 × 512 B frames were the minimum that boots — and paging is now deferred | P03f, P19 |

---

## 1. What we are building, in the operator's words

> An interpreter, not compiled Forth. An event loop. Multi-threaded — an 8 KB operating system.
> Connect from here to the REPL. Any memory usable, paged through the other processors. They do
> communication and memory only; all compute stays on the ULP. No Wi-Fi, no Bluetooth, no NVS.

The **ULP** is a separate, tiny processor inside the ESP32-S3 that keeps running when the two big
cores sleep. It has **8176 bytes** of its own memory and, while the big cores sleep, no access to
flash or PSRAM. Everything — typed text, definitions, stacks, tasks — lives in those 8176 bytes unless
a page is fetched from a filing cabinet that only the big cores can open.

Target: **a Forth machine that would fit in the RAM of a 1980s micro, running on the part of an
ESP32 that stays awake, with its filing cabinet borrowed from the big cores while they sleep.**

---

## 2. Requirements and where each stands

| # | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| R1 | Interpreter, not compiled Forth: text in, interpreted on the chip | **met for user programs** — typed at the REPL, compiled and run by the on-target compiler. Caveat: the *standard vocabulary* is baked (on-chip prelude compilation needs 14 874 B vs 7 856) | E-046, E-047, F-12 |
| R2 | Live connection: type, see output, `ok`, define words immediately | **met on the board**: prompt emitted by the ULP, echo, `ok`, runtime definitions executed; verified again today with 10 correctness cases | E-047, E-061 |
| R3 | Event loop: wake → drain console → step tasks → sleep; nothing blocks | **met in the operating path**: `main()` is the loop, the timer re-arms on halt, tasks are stepped once per wake, and the only blocking call (the block handshake) is not in this image | E-011, E-019, E-055 |
| R4 | Multi-tasking: cooperative tasks with their own stacks and a saved IP | **met on the chip**: `SPAWN TA SPAWN TB` with `PAUSE` bodies prints `1324`; three tasks print `131242`; the REPL answers before, between and after | E-055, E-062 |
| R5 | Memory beyond 8 176 B through explicit block words | **met in `probe/blocks`, not in shipping**: 8 × 256 B blocks work end to end on the chip (`BLOCK`/`UPDATE`/`SAVE`, `ERR_DIRTY`, CRC-verified fetches) at 8 047 of 8 176 B, by spending **R4** (tasks cost ~496 B of text, and the pool holds one or the other). Shipping stays as costed below:: 456–530 B of words + 512 B buffer + ~500 B plumbing ≈ **1 300–1 500 B** against **558 B of app space** and 4 B of pool spare — ~850 B short. Transparency stays rejected (888 B of dictionary, P34) | E-059, E-062, F-49 |
| R6 | The main cores are only a byte server | **met and asserted**: the console bridge moves bytes only; no Forth executes on the main cores, proven by a static checker (6/6) and by a counterfactual where the console returns `b''` | E-048, E-049, P41 |
| R7 | Storage without NVS (dedicated flash partition, no NVS) | **not built** — no partition work attempted; blocks were to be its first user | — |
| R8 | Command-line REPL over USB | **met** — `probe/repl/repl` or plain `picocom -b 115200 /dev/ttyACM1`; prompt, echo, `ok`, named errors. Framed control frames (`06-repl.md` §3) and `ulpctrl` are still design | E-047, J-59 |

---

## 3. What exists

**Documents** — `00-background` (platform facts + corrections to the original notes), `01-proposal`
(the design, requirements, acceptance checklist), `02-harness` (how the board is driven), `03-prototype-review`
(the starting code, by execution), `06-repl` (the console), `07-status` (this), `probes/` (15 briefs).

**Code** — `probe/uforth/`: the reference prototype plus a 36-word boot layer, and a host suite of
**58 tests, all passing**. That is the whole of the working software.

**Evidence** — `probe/EVIDENCE.md`, entries E-001 … E-020, each with the command that produced it.

---

## 4. What we measured

| Probe | Question | Verdict | The number that matters |
| --- | --- | --- | --- |
| P01 | how big is the interpreter? | **PASS** | **3818 B** of the 8176 — I had estimated 2600, so 1.2 KB of dictionary disappeared |
| P02 | 16- vs 32-bit references | **PASS** | **39.2 B per word** (was 21); 6.5–8.7 % of definitions straddle a page |
| P03 | does paging retry work? | PARTIAL | 0 positions measured — my own fixture corrupted the dictionary |
| P03b | same, exhaustively | **FAIL** | **32 of 83** fault positions gave a different result |
| P03c | why? | PASS | traced to a checkpoint taken one instruction too early (`P_DOCOL` pushed `1410` instead of `1488`) |
| P03d | fixed? | **PASS** | **0 mismatches over 187 positions**, same baseline digest |
| P03e | do write-then-fail words repeat the write? | **BLOCKED** | 0 positions — workload froze with faults **off**; revealed the three-page problem instead |
| P04 | console rings, slicing | PASS | rings 128/256 B, `k=4`; **one token can cost 505 primitive steps**, so resume must be per-step |
| P05 | clock | **PASS** | **19.0 MHz**, **122.6 cycles/tick**, **6.46 µs/tick**, **81 cycles** just to wake up |
| P06 | overrun, two wake sources | PASS + PARTIAL + FAIL | period is **sleep**, not period; wake cause **unreadable**; GPIO latency not obtained |
| P10 | REPL line discipline | **PASS** | reserved byte appears **0 times in 86 KB**; 6/6 escapes, 7/7 line cases, 0 bytes lost |
| P07 P08 P09 P11 | server cost, flash, crash, real link | **not run** | — |

---

## 5. What failed, plainly

* **P03e answered nothing.** Its own question — does a word that stores then faults repeat the store —
  got no data at all: the workload froze with faults disabled, zero positions swept. As the probe it
  was asked to be, it is a blank, and it is written up as `BLOCKED`, not as a pass.
* **The board wedged for hours** and needed a physical reset. Root cause: our code writing
  processor-control registers while the ULP was also using them. That first attempt produced zero data.
* **The firmware that was on the board before we started is gone.** Overwritten by P05 without a
  backup. My process failure; unrecoverable.
* **A test fixture of mine was broken** (`BASE` returned a value where an address was needed), so
  `HEX` corrupted the dictionary and destroyed P03's entire baseline. One probe wasted.
* **P05's first run** failed on a latched hardware counter and came back half-done.
* **Three things could not be obtained:** wake-cause attribution (impossible on this silicon),
  GPIO edge latency (needs a narrower experiment), and retire-after-abort (it reproduced the wedge).

---

## 6. What the measurements changed

| # | Assumption | What the silicon says | Consequence |
| --- | --- | --- | --- |
| 1 | 8 KB is enough for a Forth | 397 bytes short | word **names move to paged storage**, only code stays resident (~440 B spare) |
| 2 | stop anywhere, fetch, resume | 39 % of positions resumed wrongly | checkpoint **after** the fetch, before execution |
| 3 | two 512 B page slots | a step can need **three pages at once** | **4 × 256 B**, same RAM |
| 4 | period = timer interval | timer counts **sleep** | a slow wake delays the next; nothing is lost, rate slips |
| 5 | GPIO events are timestamped | wake-cause register reads **0 always** | poll RTC-IO status, coalesce one event per pin per wake |
| 6 | console and flashing on the chip's USB | USB wedges when a program hangs | **flash and console on the UART port**, which is the recovery port |

Two more, smaller: the prototype's 32-bit reads cost **8× a native load** (69 vs 8.1 cycles) and must
be fixed before any speed figure is quoted; and the working language is **39 bytes per word**, so 8 KB
is roughly 200 words of your own.

---

## 7. Where we are right now

* **On the chip:** a live Forth REPL. `probe/repl` boots, prints its own prompt from the coprocessor, and
  evaluates what you type: `2 3 + .` → `5 ok`, `: SQ DUP * ;` then `7 SQ .` → `49 ok`, `BOGUS` → `BOGUS?`.
  **Current, measured:** image **6 888 B** on the wire; pool **7 852 / 7 856** (`.text`+`.rodata` 5 168, `.data` 1 720,
  `.bss` 964); `MEMSZ` 1 704 with `V_HERE` 1 146 at boot → **558 B of app space**; C-stack reserve 340 B.
  **Multi-tasking (R4) is live**: `SPAWN TA SPAWN TB` with `PAUSE` bodies prints `1324`, three tasks `131242`.
  Dispatch is **1 139 cycles**/token (was 1 758), a typed literal **1 623** (was ~28 000). Blocks are **not** in this
  image: 456 B of words + a 512 B buffer + ~500 B of plumbing against 558 B of app space (E-062).
* **On the PC:** the prototype and its 58 tests, the paging/block harnesses, and fourteen probes' worth of
  measurements.
* **In the design:** every budget line measured, four requirement-level corrections applied (blocks not
  transparent paging; overlays dead; 620 B of app space; prelude baked rather than compiled at boot).

The shortest honest summary: **the machine exists and you can type at it.** Resident code is 620 B of the
Forth memory; documents live in blocks only after they are added to this image, which has 598 B of pool
left — enough for the block words (456 B) but not for their 512 B buffer.

---

## 8. Next, in order

1. **P03f** — re-run the paging sweep with **4 × 256 B** frames to confirm the three-page livelock is
   gone. Same harness, one constant changed, 15 minutes.
2. **P07** — what one page fetch actually costs with the big cores awake, and with them woken from
   sleep. This decides whether paging is usable at all in the real loop.
3. **P11** — the real REPL link: attach, 200 paced lines, unpaced paste, port exclusion, dead-man.
4. **The bridge** — main-core firmware that moves bytes between USB and the ULP's rings, watchdogged.
   This is what makes the machine reachable and stops every later step needing a reflash.
5. **P08 / P09** — flash write/erase and snapshot restore; what survives a crash; whether a new
   interpreter image can be loaded without reflashing.

Nothing in that list is optional, and none of it is Forth-level work: the interpreter is the last thing
to arrive, because everything above it changes what the interpreter has to be.

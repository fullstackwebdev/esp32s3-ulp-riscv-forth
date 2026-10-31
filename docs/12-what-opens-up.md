# 12 — What the unverified wins would actually unlock

The question: do the open items — 16-bit halfword loads, hand-written RVC assembly, verified divider latency, the
592 B of slack — open anything we had ruled **impossible**, specifically transparent load/store and multi-tasking?

Short answer: **one of them, and not the one I expected.** Multi-tasking was never impossible; its state is already
bought and paid for in the shipping image. Transparent load/store stays dead, and the reason is not size — it is that
its cost is *dictionary*, and every win available is *code*.

---

## 1. Multi-tasking: already 80 % paid for, and nobody noticed

`probe/repl/build`'s own symbols, from the shipping 6 120 B image:

| Symbol | Size | Status in the image |
|---|---|---|
| `tsk` (3 task records) | **420 B** | **allocated in `.bss`, part of the 7 258 B already counted** |
| `vm_switch` | 102 B | **linked and called** — from `vm_task_leave` and from `main`'s pause path |
| `vm_task_leave` | 120 B | **linked** — the retire path is live |
| `vm_task_init` (spawn) | 72 B | **absent — eliminated by `--gc-sections`: nothing calls it** |
| `vm_next_ready` (round-robin) | 54 B | **absent — same reason** |
| `vm_run_tasks` (stepping loop) | 80 B | **absent — same reason** |

So the record array, the context switch, and the retire path are *in the machine right now*. What was removed is the
three functions that would **create and schedule** a task: **206 B**.

Enabling multi-tasking therefore costs about **250 B** (206 B + a spawn primitive and one Forth word) against
**598 B spare**. It fits, with ~348 B left. **Multi-tasking is one probe away, not one redesign away.**

*Correction to the register.* F-08 says "3 tasks = 420 B" as though that were a cost to budget for. The shipping
image has already spent it. The honest statement is: *the state is bought, the entry points were garbage-collected.*
A budget that counts something twice is the same class of error as F-56.

## 2. Transparent load/store: dead, and now doubly dead

R5 originally promised that `@` and `!` would work at any address, paging invisibly to flash and PSRAM. Two
independent numbers, from two different directions, both say no:

* **Forth side (P34):** the `@`/`!` shadows and their machinery are **888 B of dictionary** against **202 B** for
  explicit block words. App space is 620 B; this would consume 143 % of it.
* **C side (measured now):** the paged interpreter — `vm_enter`, the retry/fault state machine — is **2 520 B of C**
  when forced out of line, and it is *entirely absent* from the shipping image. We are not paying for it and do not
  want to.

The decisive point for this memo: **888 B is a dictionary cost, and no win on the table is a dictionary win.**
`lhu` saves code (measured: **−12 B** of `.text`), RVC saves code, `-fkeep-static-functions` reveals code. None of
them adds a byte to `MEMSZ`, which is where the 888 B would have to live.

## 3. Blocks in the shipping image: still no — and the reason is arithmetic, not pessimism

| Component | Cost | Where it must live |
|---|---|---|
| block words (`BLOCK`/`UPDATE`/`SAVE`) | 456 B | **inside `MEMSZ`** (they are Forth definitions) |
| block buffer | 512 B | pool, outside `MEMSZ` |
| **total** | **968 B** | vs **598 B spare** (+12 B from `lhu`) |

`MEMSZ` is 1 280 B with **144 B free**, so the 456 B of words cannot be squeezed in either. Blocks need a
re-balanced `MEMSZ`, a smaller buffer, or the words moved out of the dictionary — a design decision (open question 3),
not something a 12-byte code win touches.

## 4. What the ISA work *did* change: algorithms, not capacities

* **`MUL` is 34 cycles, `MULH` 66** (TRM Table 2.6-1). Any index scaling, hash, or reciprocal must be a shift or an
  add. This is a *cost model*, and it changes what you write — it does not give you room to write more.
* **RVC is live** (`ret` → 2-byte `c.jr`): hand-written assembly for the fetch loop can buy density. Unmeasured, and
  the fetch loop is one function.
* **The real fetch cost is a call chain, not two loads.** Measured: `rd16` is a **42 B out-of-line function with 11
  call sites**; `rd32` 34 B / 18 sites; `rd8` 30 B / 12 sites. So a token fetch is `jal rd16` + bounds check + two
  `lbu` + shift + or + `ret` — call overhead *and* two loads, at 480 cycles per `NEXT`. Replacing `lbu,lbu,shift,or`
  with one `lhu` removes one load (and the 12 B of code), which is a **load-latency question**, not an
  instruction-count question: 480 cycles for ~20 instructions says RTC RAM latency dominates. **That is why P42 has
  to be measured rather than argued.**

  **P42 then measured it, and the answer inverted that paragraph's original claim.** Removing one `rd8()` call took
  the dispatch from **1 757.75 to 1 139.25 cycles — −35.2 %** — for **+6 B** of pool (E-053). The lever was real
  and large; what was wrong was judging it by its 12-byte code delta. The generalisation survives the correction
  and is stronger than it: **a call on this core costs ~24 cycles per instruction, so removing a call is worth far
  more than removing an instruction.**

## 5. The one genuinely new capability the numbers reveal

`-fkeep-static-functions` is a **measurement technique** we did not have: it shows what the linker deleted. On this
image it recovers 492 B of net text and, more usefully, a per-function price list of everything currently inlined
or absent — `vm_enter` 2 520 B, `drain_cmd` 302 B, `interpret` 252 B, `mkhdr_pad` 204 B, `number` 176 B,
`run_line` 154 B, `vm_run_tasks` 80 B, `vm_task_init` 72 B, `vm_next_ready` 54 B, `run` 24 B.

That gives every future "can we afford X?" question a first-pass answer in one flag, instead of a probe.

## Verdict table

| Capability | Was it blocked? | What it actually needs | Blocked by | Verdict |
|---|---|---|---|---|
| Multi-tasking (R4) | **never blocked** — mis-accounted | 206 B of spawn/schedule code + ~40 B primitive | nothing | **buildable now**, ~348 B spare after |
| Transparent `@`/`!` (R5 as written) | yes | 888 B *dictionary* (+2 520 B C) | `MEMSZ`, not the image | **still dead** |
| Explicit blocks (`BLOCK`/`SAVE`) | yes | 456 B in `MEMSZ` + 512 B pool | 968 B vs 598 B | **still dead**, needs re-balanced `MEMSZ` |
| Blocks **and** tasks together | yes | 968 + 250 B | 1 218 B vs 598 B | **dead**; tasks win, blocks wait |
| Faster fetch (`lhu`/inline) | no | 1 load instead of 2 | unknown — latency, not instructions | **measure (P42)** |
| 16-bit token width (R4's enabler) | no | already paid (−232 B vs 32-bit) | — | done (F-40) |

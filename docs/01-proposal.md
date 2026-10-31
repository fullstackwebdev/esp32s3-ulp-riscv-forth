# 01 — Proposal: an interpretive Forth OS on the ESP32-S3 ULP

Status: **current**. Supersedes the earlier draft of this file. Platform facts are in
[`00-background.md`](00-background.md); the link to the board is in
[`02-harness.md`](02-harness.md); the starting code is reviewed in
[`03-prototype-review.md`](03-prototype-review.md).

---

## 1. What we are building

A live, text-interpreted Forth system that runs on the ULP RISC-V coprocessor of an ESP32-S3, inside
its 8176 bytes of RTC RAM, with cooperative tasks driven by an event loop, connected to a terminal
over USB, whose data space extends transparently into PSRAM and flash through the main cores acting
purely as a byte server.

### Hard requirements (these define the project; nothing below may violate them)

| # | Requirement |
| --- | --- |
| **R1** | **An interpreter, not compiled Forth.** Source text enters the chip and is interpreted there. No PC-side compilation of Forth programs, no prebuilt dictionary of user words, no rebuild to change a program. **Status: met for user programs** — typed at the REPL, compiled on the chip (E-047). **Caveat:** the *standard vocabulary* is baked into the image, because compiling it on-chip needs 14 874 B against 7 856 (P39/E-046, and 4 336 of that is a duplicated dispatch switch from inlining). Streaming the prelude from flash is the open follow-up. |
| **R2** | **A live connection.** A terminal attaches, types text, sees output and `ok`, and defines words that exist immediately. |
| **R3** | **An event loop.** Everything the system does happens inside a wake-triggered loop; nothing blocks; each wake retires so the timer re-arms. |
| **R4** | **Multi-tasking.** Several Forth tasks run in the loop, each with its own stacks and a saved instruction pointer. |
| **R5** | **Memory beyond 8176 B, through explicit block words.** `BLOCK ( n -- addr )` loads a 512 B block into one buffer, `UPDATE` marks it, `SAVE` writes it back over the main cores; the program addresses bytes inside the buffer. **Transparency was measured and rejected:** 888 B of dictionary for `@`/`!` shadows plus their machinery — 88 % of the app space (P34). Data and *source* scale without limit; resident *definitions* do not, because the interpreter fetches tokens from RTC RAM (P35/P36). |
| **R6** | **The main cores are only a byte server.** They copy bytes, read/write flash, erase sectors, and carry the console. They never interpret, compile, schedule, or compute. |
| **R7** | **No NVS.** Storage is a dedicated flash partition and PSRAM. NVS is not used. |
| **R8** | **A command-line REPL over USB.** A plain serial terminal gets a prompt and runs Forth; the repository's own tool (`ulpctl`) adds history, pacing and control frames on the same port. No Wi-Fi, no Bluetooth, no second cable. Design in [`06-repl.md`](06-repl.md). |

Everything else — scheduler policy, page size, block layout — is engineering detail, decided below.

---

## 2. Scope

**In scope:** R1–R8, on the ESP32-S3 with 8176 bytes of ULP RAM, 16 MB octal PSRAM and 32 MB flash.
R8 makes the bridge firmware and the host tool part of the deliverable — a REPL nobody can attach to is
not a REPL.

**Out of scope** (and the acceptance checklist contains nothing about these): floating point, ANSI
compliance, a screen editor, a filesystem with names and directories, preemptive scheduling, memory
protection, networking, power optimisation, multiple ULP images, a second language.

Nothing in this document is a promise about any of those.

---

## 3. Why this is possible at all

Two facts make the design work, and both are specific to this platform:

1. **In a token-threaded Forth, code is data.** A colon definition is an array of tokens walked by
   our C interpreter — not machine instructions fetched by the CPU. The CPU's fetch unit can only
   reach RTC RAM, but *our* loop can read a definition from anywhere. Therefore definitions can be
   paged, and R5 is achievable.
2. **The ULP wakes, runs and retires, keeping its globals.** Measured: the IDF runtime floor is 128
   B, `.bss` is not re-zeroed per wake, `__stack_top` is re-seeded every wake, and returning from
   `main` sets `DONE` without stopping the timer. So a persistent VM is a state machine over
   globals, and a page fault is just a wake boundary.

Corollary: **the stacks and VM registers must stay resident**, because a fault in the middle of a
push has no resume point. Paging is for code and data, never for the machinery.

---

## 4. Architecture

```
┌────────────────────────── ULP, 8176 B resident ──────────────────────────┐
│  engine:  token interpreter + ~31 primitives + parser/find/number        │
│  VM state: ip, dsp, rsp, current task, status, fault counters            │
│  page frames + page table (LRU)                                          │
│  data stack, return stack (resident, small)                              │
│  mailbox: command ring, output ring, storage request/response            │
└───────────────┬──────────────────────────────────────────────────────────┘
                │  faults on 0x1… / 0x2… addresses
                ▼
   ┌──────────────────────────────────────────────────────────┐
   │ main cores — byte server only                             │
   │   · copy bytes to/from PSRAM                             │
   │   · read/write/erase the storage partition                │
   │   · carry the console to USB                              │
   └──────────────────────────────────────────────────────────┘
                ▲
                │ framed protocol (docs/02-harness.md)
        workstation terminal
```

### 4.1 Forth address space

Tagged in the top nibble, so `@`/`!` are uniform:

| Range | Backing | Resident | Survives power loss |
| --- | --- | --- | --- |
| `0x0000_0000 … 0x0000_1FFF` | RTC RAM | always | no |
| `0x1000_0000 … 0x10FF_FFFF` | PSRAM (16 MB) | on demand | no |
| `0x2000_0000 … 0x21FF_FFFF` | flash partition (32 MB) | on demand | yes |

These are Forth addresses, deliberately different from hardware addresses. Hardware registers stay
reachable only through primitives (`GPIO@`, `GPIO!`, `ADC@`, …), so a stray pointer cannot poke a
peripheral or a flash controller.

### 4.2 The four paging rules

1. **A definition spans at most two pages.** The compiler pins every page the definition being
   compiled touches (two frames at most) and refuses only a definition larger than a page
   (`ERR_WORD_TOO_BIG`). Measured (P02): with 32-bit tokens **6.5–8.7 %** of definitions straddle a
   512 B boundary — roughly mean definition size ÷ page size — so "refuse a straddle" would reject
   one definition in fourteen. At 256 B pages the rate is 10.9–15.2 %, which is why the page stays
   512 B.
2. **A fault retries at primitive granularity, with the checkpoint taken *after* the token fetch —
   measured, 0 mismatches (P03d).** The interpreter saves `(w, ip, p, sp, rsp, ds[], rs[], output
   length)` *after* fetching the next token and *before* executing it, and re-enters the same
   `(w, ip, p)` after the page fetch. Exhaustive measurement — one 187-dispatch workload at 4 frames,
   one fault injected at every dispatch position (83 can actually fault; 104 report `no_access`) —
   gives **0 mismatches, 0 hangs**, with the baseline `chk=4f99db40 sp=1 rsp=0` reproduced exactly.

   The two failed attempts are why this is stated so precisely. Checkpointing *before* the fetch gave
   **32 mismatches of 83** (P03b): a fault during the fetch re-ran a completed dispatch, traced at
   P03c to `P_DOCOL` pushing return address `1410` instead of `1488`, so the matching `EXIT` returned
   into the wrong place and the body ran twice. Moving the checkpoint fixed all 32, including every
   previously failing position.

   Word-boundary pinning is **dropped** — unnecessary at this granularity, and it collides with the
   budget: pinning would hold every page of a definition for its whole duration and nested calls would
   thrash. Fine-grained retry keeps frames transient, which is what this machine needs.

   **Frame capacity is the binding constraint, and it is measured (P03e).** A single dispatch can touch
   **three pages at once** — token page, inline-operand page, data page — and with two 512 B frames the
   LRU evicts the page the retry is about to need, so the retry makes **zero forward progress**: the
   fault-free baseline livelocked at `ERR_RETRY_CAP` after 302 loads and 302 retries over a
   three-address cycle. Hence **4 × 256 B** (§4.3): same RAM, four slots, the cycle fits. Any future
   change that raises the number of pages a dispatch touches (wider inline operands, a string literal
   crossing a page) must be checked against this, not assumed.

   The retry state machine carries a **progress bound** — a retry returning to the same `(w, ip, p)`
   twice without an intervening successful dispatch aborts with `ERR_PAGE_FAULT_LOOP` (verified firing
   after 5 retries at `w=1430 ip=1432 addr=1430`) — plus `ERR_RETRY_CAP` as a hard backstop, so no
   fault can present as a hang. Output is buffered per dispatch and discarded on rollback. `!` pops its
   address in order to resolve it, so **the stacks are part of the resume state**, and the outer
   interpreter needs its own restart point because `find`/`number`/`,` touch memory with no `run_from`
   frame above them.

   **One unobserved risk remains:** a primitive that stores and *then* faults on a second access in the
   same dispatch would repeat the store on retry. P03c found no case and P03d's workload has no
   read-modify-write word, so it is untested rather than cleared. P03e tests it; if it fails, the fix
   is a residency check before a primitive's first store — a per-primitive audit, not an architecture
   change.

3. **Paging is cold storage, not extra RAM.** A fault costs one round trip: ~50–200 µs with the main
   cores awake, milliseconds if they must boot. The hot set must fit the resident frames. Thrashing
   is reported as a number (`faults_per_wake`, sticky `ERR_HOT_SET`), never as a hang.
4. **Flash is written in sectors.** 4 KB erase granularity and finite cycles: dirty pages go to PSRAM
   immediately, to flash only on `FLUSH`/`SAVE`, with sector rotation and a shadow copy.

Page size **512 B, 4 frames (2 KB)**. Flash storage is addressed in 1 KB blocks (two pages), which
also gives us Forth-style source blocks.

### 4.3 Resident budget — **built and linked** (P22), with 94 bytes to spare

The machine as specified was built and linked. It fits — at a smaller Forth memory than the arithmetic
predicted, and with the overrun fully named.

| Item | Value | Source |
| --- | --- | --- |
| Engine (40 primitives, 32-bit refs, paging) | **3190** (`.text` 3010 + `.rodata` 180) | P20 C, P22 |
| Page frames 4 × 512 | 2048 | P03f, P19 |
| VM state + counters | 150 | — |
| Page table + LRU (4 slots) | 250 | — |
| Forth stacks | 128 | P13 (peak 108 B) |
| Mailbox + rings | 600 | P04 |
| Line buffer | 128 | P10 |
| **ULP hooks / REPL glue** | **142** | P22 — *a line this budget did not have* |
| C stack (carved at the top of the pool) | 320 | P21 (worst case 244 B) |
| **Forth memory (`MEMSZ`) that links** | **1188** | P22 |
| **Left over** | **94 B total** (10 B of pool + 84 B inside `MEMSZ`) | P22 |
| Task state for R4 (3 tasks × 140 B at `SD=16`) | **−420** | P27 |

**R4 closes in exactly one way: 16-bit code tokens (P28).** Each extra task costs 140 B out of the same pool,
so `MEMSZ` falls as tasks are added. Measured, with the 16-bit build compiled rather than extrapolated:

| # | tasks | `MEMSZ` | resident need | gap |
| --- | --- | --- | --- | --- |
| A | 1, 32-bit | 1188 | 1104 | **+84** |
| B | 2, 32-bit | 1048 | 1144 | **−96 fails** |
| C | 3, 32-bit | 908 | 1144 | **−236 fails** |
| **D** | **3, 16-bit** | **908** | **676** | **+232** |
| E | 3, 16-bit, cold prelude paged | 908 | 448 | +460, and the page claim is untraced — not needed |
| F | 3, 16-bit, `SD=12` | 976 | 676 | rejected: `SD` must be a power of two for the `& (SD-1)` masks, and 12 is below P13's 20-cell peak |

**Decision: adopt 16-bit code tokens.** The 16-bit dictionary is **636 B resident** (56 header + 496 prelude
+ 84 primitive headers), bodies 728 → 424 (1.72×, matching P02's 1.74×), code fields 312 → 156; the name
directory is a wash (812 → 818). It buys R4 while spending **no** measured margin: frames stay 4 × 512, stacks
stay `SD=16`, the C stack and rings are untouched, and all 78 words stay resident.

The price is **address width, not RAM**: code references become 16-bit, so the *code* space is 64 KB — about
1 600 words, against a prelude of 78 — and **R5 is unaffected because data addresses were always 32-bit cells**.
Paging still gives terabytes of data; only the number of *definitions* has a ceiling.

**Does the shipping engine fit? No — and the reason is code structure, not arithmetic (P29).** Built as
specified (16-bit tokens, `vm_switch`, paging, all four hooks, 3 task records), the engine is **4934 B**
against P22's 3190, so the region needs **9692 of 7856 — 1836 B over**. With `MEMSZ` set to **0** it is still
918 B over, which means the **pool**, not the dictionary, is now binding.

Attribution from `nm --size-sort`:

| Symbol | Bytes | Why |
| --- | --- | --- |
| **`vm_enter`** | **2380 (51 %)** | the 61 primitive bodies **plus** `resolve`/`pg_load` inlined at every token-stream read |
| libgcc `memcpy` + `memset` | **400** | pulled in by `tsk[from].vm = *V` and `vm_task_init`'s zero loop |
| `vm_switch` | 102 | |
| `pg_load` / `rd16_paged` | 168 | |
| `word` / `find` / `mkhdr` / `err` / `clit` | 598 | |
| hooks (all four) | 196 | |

Three suspects were cleared: there is **no double stack copy**, the fault path genuinely calls `vm_switch`,
and the hooks are only 196 B. Allocation was confirmed by `nm -S` for every array (frames 2048, table,
rings, mailbox, `mem` 908, task array 420, `vm_live` 136) — nothing was eliminated this time.

**The engine budget for a 4-frame, 3-task machine is 3438 B**, so 1496 B had to come out. It does not come
out of **code structure** (P30, FAIL): making the paging helpers `noinline` saved **0 B**; making all 62
primitive bodies out-of-line *cost* **+1186 B**, because `vm_enter` collapsed 2380 → 668 while the bodies
themselves cost **2872** — **3540 out of line against 2380 inlined**. The only structural saving found was
dying libgcc: a hand-written 30 B VM copy replaces a 232 B `memcpy`, and unrolling the zero loop by four words
removes `memset` — **−400 B** in total.

So the cost is **per primitive body, not per code shape**: roughly 57 B each, wherever they live. The lever is
the **number of primitives**, and P31 settled it: tracing every name lookup while the prelude and all five
layer files load through the real interpreter resolves **35 primitives**, plus 5 the compiler emits directly
and never looks up (`EXIT`, `LIT`, `DOCOL`, `DOYAR`, `DOCON`) = **40, exactly P20's set**. Built with that set
plus the libgcc fixes, the engine is **3412 B**.

**It still does not link: 296 B short.** Region need 8152 vs 7856. And the target itself was optimistic — the
fixed lines measure **4740 B**, not 4418, so the true engine ceiling is **3116 B**, and 322 B of that
difference is not explained by any line in this table. P32 audits that before the design gives anything up,
because a 296 B gap inside a 322 B accounting discrepancy is not yet a wall.

**Two functional costs of the derived set, which matter more than the bytes.** Deriving a primitive set from
what today's code *calls* is circular: it produces a machine that can only run the program it was measured on.
The 40-set drops `I`, `J` and `UNLOOP` — so **a user program cannot write `DO … LOOP`** even though the prelude
defines it — and drops `GPIO!`, so **nothing can drive an output pin**. It also drops `'`, `(`, `."` and
`CONSTANT`.

### 4.4 The audit, and the only option that closes (P32)

The 322 B is **not slack, it is a bill the table had no convention for**: `nm -S` accounts for every byte —
**+420** task records (omitted from the sum but listed in a footnote), **+196** startup/entry plus the `main`
skeleton (no row at all), **+128** line buffer (dropped from the sum), **+34** engine-TU statics, **+6** VM
counters, **−142** hooks (a *code* line counted among allocation lines; already inside the engine), **−320**
C stack (a line that is **not in the image at all**, because `__stack_top = ORIGIN + LENGTH` grows *down into*
the last 320 B of the region). Corrected engine ceiling: **3116 B**; stricter **2796 B** once that stack is
honoured inside the pool.

With the language restored — `I J UNLOOP GPIO! ' CONSTANT ( ." (.")` — the engine is **3916 B** and the real
link needs **8656 of 7856: 800 B over** (1120 if the stack is reserved). The nine restored primitives cost
504 B, so the gap is a language gap, not a tuning gap.

Priced options against that 800 B, none sufficient alone:

| Option | Frees | Residual | Cost |
| --- | --- | --- | --- |
| **(a) drop paging from v1** | **−2466** (frames 2048 + table 250 + `pg_load`/`rd16_paged` 168) | **fits, 1666 B spare** | no page frames, no paged fetch, no fault retry; the 908 B of dictionary is all the Forth there is. **The language does not change** — paging is invisible to Forth words, so it can be re-added later without touching a primitive |
| (b) two tasks | −140 | 660 short | R4 drops to two tasks; every "three tasks" measurement becomes an extrapolation |
| (c) `mem` 908 → 676 | −232 | 568 short | zero dictionary slack — no room for anyone's own words. (b)+(c) = −372, still 428 short |

**The choice is the operator's and is not yet made.** The technical recommendation is (a) — but with ×g a
correction to what (a) means, which the operator's question produced:

**Most of the 2 466 B buys *transparency*, not storage.** Frames in the address space, a page table, an LRU, a
resolved fetch path and a fault/retry state machine all exist so that `@` and `!` can reach an arbitrary address
without the program knowing. A **visible** block interface needs none of it:

* one **512 B buffer** in the pool,
* `BLOCK ( n -- addr )` — write a request to the mailbox, wait for the reply, copy 512 B, return the buffer
  address — **synchronous and bounded**, so there is no fault, no resume point and no page table;
* `UPDATE` / `SAVE` to write the buffer back;
* the existing mailbox, already in the budget at 216 B.

Measured inputs make this practical: a 512 B fetch is **144 µs** (P16) with the main core polling and **176 µs**
through the doorbell with it blocked (P23), so a single wake of a few milliseconds can absorb dozens of block
loads. Estimated cost of the whole visible layer: **512 B of buffer + ~200 B of code ≈ 700 B**, against 2 466 B
for transparency — leaving a non-paged machine with roughly **950 B spare** (600 with the C stack reserved).

What it gives up is stated plainly: **code cannot live off-chip** (definitions stay resident), and an arbitrary
address is reached by copying a block into the buffer first. That is the 1980s Forth block file, which is
exactly the idiom the operator asked for.

**And the re-spent budget, measured by construction (P35).** Raising `MEMSZ` until the link fails:

| Case | `MEMSZ` that links | operator's budget after prelude and 512 B block buffer | words @28 B | words @39 B | vs paged |
| --- | --- | --- | --- | --- | --- |
| paged machine (P28) | 908 | 232 B | ~8 | ~6 | — |
| **non-paged, C stack not reserved** | **2196** | **1008 B** | **36** | **25** | **4.3×** |
| non-paged, C stack reserved inside the pool | **1880** | **692 B** | **24** | **17** | 3.0× |

`sections = 5651 + MEMSZ` against `7748 + MEMSZ` for the paged build: **2091 of the 2466 B came back**, and
**352 B** was spent on the block layer (348 engine + 4 `blk_out`) — no byte is missing, and `nm -S` confirms
`frm`/`ptab`/`ptab_lru_reserve` are **gone** while `mem` equals the new `MEMSZ`.

So the honest headline changes: **the operator's program is 1008 B / 36 words, not 232 B / 8 words.** "908 B"
was a paging artefact — the pool had already paid for frames no Forth word can address. And the distinction that
matters for what scales: **data (blocks) and source (screens in flash) are effectively unbounded; resident
*definitions* are not**, because the interpreter fetches tokens from RTC RAM.

### 4.5 Transparent vs explicit block access — priced (P34)

The Forth-shadowing idea works mechanically but costs more than the machine can pay:

| Shape | Dictionary cost | Fits the 1008 B app space? |
| --- | --- | --- |
| **Transparent**: `@` `!` `C@` `C!` shadowed to page | **888 B** (636 headerless): shadows 202 + machinery 434 (read/save/fail/allot) | **no** — leaves ~120 B for the program |
| **Explicit**: `F@` / `F!` only, no shadows | **202 B** | yes — leaves ~806 B |
| **Block words**: `BLOCK` / `UPDATE` / `SAVE` over one buffer | cheapest (P33) | yes, and it is the 1980s idiom |

Engine cost of the transparent variant: **+244 B** over P35's non-paged build (4174 vs 3930 sections; `far_xfer`
+144, `far_sum` +50, `pl_hw` de-inlined +126), and the real 7856 B link **succeeds** using **3369 B**. The
buffer is a 512 B `.bss` array of its own — `mem` stays 908.

**Decision: explicit block access for v1.** Spending 888 of 1008 bytes to hide a page fault is a bad trade when
the program itself is only 36 words; the same transparency costs 686 B more than naming the two words
`F@`/`F!`. Transparency stays an *option* for a machine with more RAM, not for this one.

One caveat recorded honestly: P34 proved **half** of the shadowing claim. Pre-existing words do keep the raw
primitive (a token is an xt: `@`'s header 230 → xt 234, and a word compiled later installs at xt 2220), but the
shadow itself **failed to install** (`ERR_UNNAMED`, `' @` still 234), so "user code pages without knowing" was
never demonstrated end to end. If transparency is ever revisited, that experiment comes first.

**The visible block layer is the cheap one (P33), and it links with room.** `BLOCK` / `UPDATE` / `SAVE` over one
buffer: engine **+200 B** like-for-like against the non-paged build, the buffer 512 B inside `mem[]`, region need
**7071 of 7856 ⇒ 785 B spare** (465 B with the C stack honoured). Its Forth is **456 B** — against 888 B for the
transparent wrappers, **432 B cheaper**, which is the difference between an app that fits and one that does not.

So the app-space arithmetic for the suite, with everything maximised (`MEMSZ` 2196, buffer inside it):

| | bytes |
| --- | --- |
| `MEMSZ` (non-paged, links) | 2196 |
| − block buffer (at `MEMSZ−512`) | 512 |
| − prelude | 676 |
| **= app space before the block words** | **1008** |
| − block words (`BLOCK`/`UPDATE`/`SAVE`) | 456 |
| **= code left for the application** | **552** (236 if the C stack is reserved) |

### 4.6 Overlays: mechanism works, budget kills it (P36)

The "apps as blocks loaded into a buffer" model was tested end to end. **The mechanism works** — compile into
the buffer, save, clear, reload, execute gives the same answer, and the reloaded copy calls resident words
correctly (`7 SQ 49 =` evaluated through the resident `=`/`IF`/`.`). **The budget does not:**

| Item | Bytes |
| --- | --- |
| resident set with the segment loader, directory and 12 inline `ERR_*` strings | **3 628** |
| maximum `MEMSZ` that links | **2 196** |
| **shortfall** | **−1 432** |

The dictionary ladder is measured and unambiguous: primitives 630 → `+control` 1 038 → `+pre` 1 328 → `+paging`
2 228 → **`+seg` 3 628**. A loader that costs 1 400 B cannot live in a machine with 620 B of app space.

Two things this also corrects:

* **App space is 620 B, not 1 008.** P35's figure never charged the block layer, which is **900 B** in this
  variant (P33's 456 B was a different, smaller `blocks.fs`). The operator's real room is 620 B before any app.
* **A gate call into an overlay cannot be a plain Forth `EXECUTE`.** If a segment's entry is a bare token list,
  its final `EXIT` pops a return frame nobody pushed, leaving `sp` past the stack — which is why the stale-segment
  test aborted with a stack underflow instead of printing its named error. It is fixable (compile each segment as
  a real colon definition so it carries `DOCOL`), but it is moot while the loader does not fit.

**Consequence for the sprint: no overlays in v1.** The device runs **one resident application** at a time, and
the shell either does not exist or is part of that application.

**Open bug: the wrapper's Forth does not execute yet.** P33's protocol path passed 4/4 on the host fake server —
`BLOCK` returns the right bytes, `SAVE` writes back, the named failures fire — but the Forth `BLOCK` and `SAVE`
wrappers **hang**. Two candidate causes, and they point in opposite directions: (a) the host harness has no
concurrent server, so a synchronous spin cannot be serviced between interpreter steps and would work on the chip,
or (b) a real branch/operand bug in words compiled at that `HERE`. P37 must distinguish them before the suite
depends on this.

Two corrections to the arithmetic that preceded this build:

* **The budget was 190 B short, not 0 B.** At the predicted `MEMSZ` of 1380 the link fails with
  `address 0x1f6e … not within region 'ram'` (8046 vs 7856). The 202 B gap is named: **142 B of hook
  and REPL code with no budget line**, 28 B of engine growth caused by the `MEMSZ` constant folding into
  ~20 access paths, 22 B of alignment, 10 B of residue.
* **A first link "passed" with 880 B spare and was wrong**: four budget arrays had been
  dead-store-eliminated out of `.bss` (728 B). Every future budget build must confirm allocation from
  `nm -S`, not from "it linked".

**Consequence: there is no room to grow.** The 8 KB machine exists, the prelude fits headerless at
1104 B of the 1188, and every subsequent Forth word — tasks, the event loop, the REPL's own words —
must live in **paged** storage. That is the resolution-A design, now with a measured reason rather than a
preference: a paged definition costs one page fetch on first use (**144 µs, P16**) and then runs from a
frame.

**The old estimate is kept below for the record.**

**The 32-bit prelude needs ~1956 B of dictionary (P02) and only 1584 B exists — a 372 B gap.**

**Decided (operator, 2026-10-30): resolution A — headerless resident words plus a paged name
directory.** Headers (link, flags, name) are **44 %** of the dictionary, measured (~860 B of 1956), and
they are needed only for `WORDS`, `SEE` and interactive `FIND` — never to execute a word. After the
prelude has been interpreted:

* the resident dictionary keeps **code fields and bodies only** (~1096 B of the 1956 B), which fits in
  1584 B with **~488 B spare**;
* names and links move to a **read-only, flash-backed name directory**, paged like everything else;
* `FIND` becomes two-level: a resident code-field table first (the fast path, no fault, one 32-bit
  compare per candidate), then the paged directory walk (the slow path, may fault);
* `WORDS`, `SEE` and `'`-on-an-unknown-word take the slow path, so **the first `WORDS` of a session may
  fault once per directory page** — accepted by the operator as the price of keeping execution fast;
* a dictionary snapshot must record the directory generation; a mismatch is
  `ERR_SNAPSHOT_MISMATCH` and is refused, never merged.

The line buffer grows from 80 B to **128 B** to match the command ring (P10 F3: an 80-byte buffer
behind a 128-byte ring produced errors that looked like ULP faults). That is **48 B** off the
dictionary, so the spare after resolution A is **~440 B**, not 488.

Rejected: resolution B (dictionary entirely paged) — it fits by construction but every call from the
REPL into a prelude word may fault, which is precisely what the wake budget cannot afford.

This decision also caps the engine: if a build ever pushes the engine past ~4.2 KB, the 440 B of
spare is gone and there is nothing left to cut except the prelude.

**Frames are 4 × 256 B, not 2 × 512 B** — same 1024 B, four slots instead of two. Reason, measured
(P03e): a single dispatch can touch **three distinct pages at once** — the page holding the token, the
page holding its inline operand, and the page holding the data being read — and with only two frames the
LRU evicts the very page the retry needs, so the retry loop makes *zero* forward progress and dies on
`ERR_RETRY_CAP` after 302 page loads. That livelock happened in the **fault-free** baseline, which is
the strongest possible signal. Four slots with half the page size keeps the same RAM, makes the
three-page cycle resolvable, and costs more faults (a page covers half the bytes) but each fault moves
half the data. Fine-grained retry is unaffected by pages being small — definitions may straddle freely,
which is also why word-boundary pinning stays dropped.

---

## 5. Execution model

Every wake is a full reset of the core; `ip`, `dsp`, `rsp`, `task`, `status` are globals. So:

```
wake:
  wake_count++; t0 = rdcycle
  cause = wake_cause()                     # timer | RTC-IO | mailbox poke
  queue events (one per pending RTC-IO pin)
  drain cmd ring → characters into the input buffer
  for each runnable task, in round-robin order:
      slice = min(quantum, remaining budget)
      run interpreter/task for that slice     # the interpreter is itself sliced
  flush out ring; publish heartbeat{seq, wake_count, cycles_used, faults}
  return 0                                  # DONE | SHUT_RESET_EN; timer keeps running
```

* **The timer counts *sleep*, not period — measured (P06).** `gap_between_wake_starts =
  span_of_previous_wake + period`, with the additive term fixed at **22 ticks** while the span was
  swept from 3 to 47 ticks. Three rival models were tested and refuted: a lost tick predicts
  `22 − (span mod 22)` = 19 at the two overrun points, a latched tick predicts ≈ 0, re-entry is ruled
  out by `cyc_top = 81` on all 11 000+ measured wakes. Consequences:
  * **No tick is ever lost; an overrun is drift, not damage.** A wake that takes longer than the period
    delays the next one by exactly its own duration, and the delay accumulates. `overrun++` is a *rate*
    signal, not an error, and work can never make the loop miss an event.
  * **For a fixed rate, subtract the span yourself:** sleep `period − last_span`, clamped at the floor.
    `ulp_set_wakeup_period()` **cannot go below 22 ticks (142 µs)** — asking for 8 µs still yields 22 —
    so a 1-tick period does not exist on this part.
* **Per-wake arithmetic** (measured, P05): **122.6 cycles per tick**, **81 cycles of wake entry**,
  dependent ALU op **4 cycles**, RTC-RAM word load **8.1**, byte load **8.6**; core **19.0 MHz ± 1.5 %**;
  RTC slow clock **154.9 kHz** (not the documented 136 kHz), so **1 tick = 6.46 µs**, and every tick↔µs
  conversion uses the *calibrated* frequency at runtime, never a constant. The 22-tick floor is 2 697
  cycles of which 81 are entry — still only ~650 ALU ops, which is why a wake must retire many ticks of
  work rather than a few.
* **The text interpreter is sliced, at two granularities.** `repl-step(k, nchars)` pulls at most
  `nchars` bytes out of the command ring and retires at most *k* = 4 tokens, then returns
  `MORE | LINE_DONE | ERR` with its cursor in memory. Measured on the host (P04): with 4 steps per
  wake a wake retires ≤ 16 tokens and, for ordinary lines, ≤ 8 primitive dispatches. But **one token
  is not one unit of work**: a token that calls a colon word with a 100-iteration loop costs 505
  primitive dispatches in a single `run()` call — 126× the `k = 1` token budget. The token budget
  alone therefore does not bound a wake, so the interpreter carries a *dispatch* budget too:
  `run_from(w, ip, p)` resumes at any primitive dispatch, and it is the only execution path. Worst
  case per wake is `min(W·k, work available)` tokens **and** `W·p` primitive dispatches, whichever
  comes first.
* **Nothing blocks.** `KEY` returns `ERR_NO_INPUT` when the ring is empty. There is no busy-wait
  primitive in the language.
* **Retirement** is `return` from `main` → `ulp_riscv_halt()` → `DONE`; the timer re-arms *from wake
  exit*, which is why the period is a sleep time and not a period.
* **Pin events: latched, coalesced to one per pin per wake, latency bounded by one period (P18).** Measured
  on the chip: an edge during sleep leaves a latch that is still set at the next wake (13/13 trials); **k
  edges during one sleep produce exactly one event for k up to 5 000**; the latch reads zero after the ULP
  clears it; single pulses as short as **30 ns** still latch. The ceiling is therefore **one event per pin
  per period** — 151 edges/s at a 1 s period, 151 000/s at a 1 ms period — and events faster than that are
  **merged, not queued**. Latency is uniform over one period (min 990 µs, median 4 188 µs, max 6 592 µs at a
  1 s period), never more than one period. So the event ring needs **one bit per pin per wake**, and any
  design that assumes a queue depth per pin is wrong.
* **Wake cause is not readable.** Both wake sources can be armed at once — measured (P06),
  `RTC_CNTL_ULP_CP_TIMER_REG` reads back `0xA0000000` = `SLP_TIMER_EN|GPIO_WAKEUP_ENA`, so IDF's
  "one source only" is an API limit, not silicon — but `RTC_CNTL_SLP_WAKEUP_CAUSE` read **0 on every
  wake**, including timer-only wakes. So the loop **polls RTC-IO interrupt status at the start of each
  wake** and coalesces: one event per pin per wake, counted, no timestamps. That is weaker than
  "timestamped edges" and it is what the hardware offers.
* **Never touch `COCPU_*` registers from the main core while the ULP may be mid-wake.** P06 reproduced
  the wedge inside the retire path that writes `COCPU_CTRL` while the HP was also disarming the ULP,
  and it is the only stage that has ever hung this board. To stop the ULP: clear `SLP_TIMER_EN`, wait
  for `wake_count` to stop advancing, then read or flash.

---

## 6. Tasks

Cooperative only. No preemption: there are no atomics, no timer interrupt into Forth, and a reset
every wake, so a preemptive switch would be a bug factory.

Task record, 32 bytes:

| Off | Field |
| --- | --- |
| +0 | `next` (run-queue link) |
| +4 | `dsp` |
| +8 | `rsp` |
| +12 | `ip` |
| +16 | `state` (free / ready / sleeping / blocked / dead) |
| +20 | `wake_at` (wake counter target) |
| +24 | `wait_mask` (event kinds) |
| +28 | `user` (body xt or a cell for the program) |

Words: `TASK`, `YIELD`, `PAUSE`, `SLEEP-TICKS`, `STOP` (block on mask), `TASKS`.

Stacks are allocated per task out of the dictionary at `TASK` time; the recommended size is 32 cells
data + 16 return (192 B), which makes **three tasks** the realistic ceiling. `ERR_TASK_NO_ROOM` is a
named failure, not a clamp.

### 6.1 The OS layer: what fits, and what had to be given up (P24 → P26)

The layer written to the *spirit* of the request was 80 definitions and **3044 B headerless — 5.9 frames**,
and its idle loop touched 6 pages and faulted **every pass**. Written instead to the *literal* content of
R3 and R4, it is **22 definitions, 1024 B headerless — exactly 2 frames**, and the idle loop settles to
**0 faults per pass** after one cold pass.

| Group | budget | P26 actual | note |
| --- | --- | --- | --- |
| tasks | ≤ 300 | **292** | `PAUSE` folded into `YIELD`; three 32 B records |
| events | ≤ 250 | **304** | +54 kept deliberately: the full-ring guard and `DIAG` are the only path to a REPL error report, and clamping is a lie |
| REPL | ≤ 200 | **188** | |
| introspection | ≤ 120 | **240** | the ceiling was optimistic: `WORDS` 136 + `U.` 80 + `.S` 24 is the floor, because the 40 primitives have no decimal printer |
| device | ≤ 100 | **0** | `GPIO@`/`GPIO!` are already primitives — recorded as a finding, not wrapped |
| **total** | ≤ 1024 | **1024** | 3044 → 1024, **66 % removed** |

Workloads at 4 × 512 B frames, **measured with a real access tracer** (P25 — the earlier figures were
computed from where definitions sit, not from what the loop touches): the idle loop touches **2 layer pages,
2 faults on the first pass, then 0 per pass**, across 2 510 accesses per pass. A line calling three OS words
also settles to 0. By contrast P24's layer, re-traced, touches **7 pages and faults 13 times per pass**.
The same trace shows **90 % of accesses are instruction fetch**, and 41 % of P26's land in the resident
region — so the working set is genuinely "two code pages plus the resident core".

**What was given up, with the measured cost of keeping it** (from P24's own image): task states and
`WAKE-1`/`WAKE-ALL`/`STOP` (296 B), the free-slot scan (236 B), `TASKS` (128 B), the task pool (132 B →
28 B), `TICK+` (28 B), three of four record fields (24 B/slot), `PAUSE` (12 B), `EMIT-EVENT` and
`WAKE-MASK` and event kinds (~520 B), `POLL-EVENTS` (304 → 120 B), the REPL's prompt/error words (192 B),
`?` and `.` (84 B), and `MS`/`PIN?`/`PIN!`/`PIN-WAIT` (108 B). Those are the features the 8 KB machine does
not have.

**The switch is real now, and it costs 140 bytes per task (P27).** A context switch saves six fields —
`ds[SD]` **by value** (64 B at `SD=16`), `rs[SD]` (64 B, because a `DO` frame lives there), `sp`, `rsp`, `w`
(the dispatch xt) and `ip` (the continuation, with `0` meaning "return to C"). 136 B of state plus a 4 B
record = **140 B per task**, or **268 B at `SD=32`**. Three tasks are therefore **420 B** (or 804 B with
larger stacks) — *not* the 24 B of record fields that P26's layer implied. **This is the price R4 was hiding,
and §4.3 does not have it.**

Proven, not asserted: `PAUSE` works **inside a colon word** — the saved point is the post-fetch dispatch of
the token *after* `PAUSE`, inside the body — and four independent predictions (interleaving order and
per-task counts, a mid-word suspend, a `PAUSE` inside `DO` inside a word, and the same positions on a page
fault) all matched exactly, with digests identical to the unimpeded runs. **`PAUSE` and the page-fault path
are one mechanism** (`vm_switch`), which is the property that keeps the two bug surfaces from diverging.

Not saved, deliberately: `run()`'s temporaries (dead across a dispatch, verified by inspection) and the outer
interpreter's `tib/ti/tl/errf` — so the *outer* interpreter is not resumable yet, and `EVALUATE` across a
wake boundary remains open.

---

## 7. The interpreter and the dictionary

**R1 in concrete terms.** The chip starts with an empty dictionary (`HERE = DICT`) and interprets
text through its own outer interpreter:

```
interpret: word → find → (found: execute | compile) | number? → push/compile LIT | error
```

* `:` creates a header and sets `STATE`; non-immediate words are appended as tokens; `;` appends
  `EXIT`. A compiled word is an array of tokens — the same representation the interpreter executes.
* Immediate words (`IF`, `THEN`, `DO`, `LOOP`, …) execute during compilation and patch 2-byte branch
  holes. They are written in Forth using `[']`-literals, because the primitive set has no
  `POSTPONE`.
* **The prelude is text.** It is stored in the flash partition and streamed to the ULP at first boot
  by the byte server, then interpreted. It is never compiled off-target. After interpretation the
  dictionary may be snapshotted back to flash (`SAVE`) so a later boot restores in one copy instead
  of re-interpreting. A snapshot is a cache of interpreted work, not a compiled program — and a
  mismatched snapshot is refused (`ERR_SNAPSHOT_MISMATCH`), never run.
* **Code references are 16-bit** (tokens), while **data addresses are 32-bit cells** — the two widths are
  independent, and conflating them cost this project a design round. P02 measured the 32-bit variant at
  **39.2 B/word against 25.1** (1.49× the dictionary); P12 showed the engine barely notices the width (+168 B
  was paging, not tokens). P28 then built both and found that **only 16-bit closes the budget with three
  tasks**: 676 B resident instead of 1144, leaving 232 B spare. The ceiling this imposes is 64 KB of *code*
  (~1 600 words against a 78-word prelude); R5 is unaffected because data was always 32-bit.
* Dictionary overflow is `ERR_DICT_FULL` with rollback to the line-start snapshot. A failed line
  leaves no partial definition behind.

---

## 8. Console and mode

| Mode | Period | Work per wake | Behaviour |
| --- | --- | --- | --- |
| **Connected** | 32–64 ticks (207–414 µs) | 3.8–7.8 k cycles | terminal attached; echo ≈ 0.2–0.4 ms, feels immediate |
| **Autonomous** | 100 ms (≈ 15 500 ticks) | 1.9 M cycles | terminal gone; tasks and events keep running |
| **Idle** | 1 s | 19 M cycles | waiting on a GPIO event or a mailbox poke |

The connected period is **not** 1–4 ticks, and the cost is now measured rather than estimated (P14):
**one primitive dispatch costs 1 074 cycles typical** (1 006 best, 1 506 worst), of which **976.5
cycles — 90.9 % — is `NEXT` plus the dispatch head**, because `NEXT` performs **two byte-wise `rd32`
fetches** (token → xt → code field) at **452 cycles each**. The primitive itself is 9 % of the cost.
Consequences: a 4-token typing slice is **35 ticks ≈ 226 µs**; compiling one prelude line (2
dispatches) is 113 µs; P04's 505-dispatch token is **542 370 cycles ≈ 4 424 ticks ≈ 28.6 ms**.

**Correction (P20): D7 is not a dispatch win.** The shipped engine fetches tokens through
`rd32_paged()`, which resolves a page once and then does four `lbu` on the frame — it never enters the
byte-wise `rd32` chain. Measured: native accessors save **0 cycles** on dispatch and cost **+116 B** of
engine. Their real value is `@`/`!`/`find`/`mkhdr` at **8.0×/5.5×**, i.e. the parse and compile path,
which is where the REPL spends its time. P14's 452-cycle `rd32` was the *data* path, not `NEXT`.

With the trimmed 40-primitive set (P20 variant C) a dispatch is **726 cycles** (658 best, 994 worst) and
a 4-token typing slice is **23.7 ticks ≈ 153 µs**. **Waking the main core works, and it does not need a spinning core (P23).** The correct mechanism is
`ulp_riscv_wakeup_main_processor()` → `RTC_CNTL_SW_CPU_INT` → `RTC_CNTL_COCPU_INT_ST`, handled by
`ulp_riscv_isr_register(fn, arg, ULP_RISCV_SW_INT)`: **27.32 ticks / 176 µs median, 200/200, with the
main-core task blocked on a semaphore**. Polling costs 157 µs and no CPU idle; light-sleep wake 474 µs;
deep-sleep wake reboots the chip and cannot be measured as a round trip. P16's "doorbell never fired" was
a wrong signal source — it drove an RTCIO pad and hung a *digital* GPIO interrupt off it, 0 ISRs in 200
edges. **R6 is therefore satisfied without a busy-waiting core.**

**A page miss costs 2 740 cycles = 22.35 ticks = 144 µs** — measured on the chip (P16), **6.8× cheaper
than the host model predicted** (18 700 cycles was an upper bound; the page was served from internal
RAM with PSRAM not enabled, so treat 144 µs as a *lower* bound for PSRAM-backed pages). Transport is
deterministic, spread max/min 1.07×, **3.55 MB/s** sustained.

That makes paging affordable in the live loop: one fault plus one dispatch is ≈ 30 ticks, a 4-token
typing slice plus a fault ≈ 53 ticks, so §8's 32–64 tick connected period holds **provided faults batch
to at most one per wake**. Resident code types at 153 µs/frame; a cold definition costs 144 µs once and
then runs from a frame.

The host switches mode on attach/detach through the protocol, with a dead-man timer in case it
vanishes mid-session. Output is buffered into the `out` ring and flushed at wake exit; refused bytes
increment `drops_out` and are reported, never silently lost.

Ring depths (measured, P04): **cmd 128 B, out 256 B** — 384 B of the 600 B mailbox+rings line in
§4.3. They are sized for different reasons. `out` must hold *one wake's* output because it is flushed
at wake exit: measured peak 123 B in the worst autonomous wake, theoretical worst ~103 B, so 256 B is
a 2.5× margin and `drops_out` was 0 in all 96 runs. `cmd` must hold `r_in · T_gap`, the bytes arriving
during the longest *gap between drains* — 128 B covers an 11 ms stall (HP round trip, page fault,
missed wake) at 115200 8N1, and measured peak occupancy in connected mode is 1 B.

Bulk input does **not** fit the ring in autonomous mode and is not supposed to: 11520 B/s needs
`C ≥ 1024 B` to survive a burst, 1.7× the whole ring budget, and the measured loss is 86–96 % of a
3204 B paste at every C from 64 to 256. So bulk input is **flow-controlled, not buffered**: the host
sends the next line only after the prompt byte, and the status mailbox asserts XOFF above 75 % ring
occupancy. Under that rule at most one line is in flight and `drops_in == 0` in both modes.

### 8.1 The command-line REPL (R8)

Full design in [`06-repl.md`](06-repl.md). The load-bearing decisions:

* **Console on UART0 (`/dev/ttyACM1`), flashing on the native USB (`/dev/ttyACM0`).** Separate ports
  mean no contention, and a plain serial line means `picocom` works with no tool at all — the
  property that makes it feel like a 1980s machine.
* **Passthrough is the default.** Bytes are bytes; no framing, no buffering, no added latency. Framing
  (COBS + CRC-16) is used only for control frames and only when the tool asks.
* **One reserved byte, `0x1D`,** for escapes: `0x1D 0x1D` for a literal, `0x1D f` to enter framed
  mode, `0x1D s` for bridge state. An unknown sequence is emitted verbatim, so a bad escape cannot eat
  text.
* **The ULP echoes, not the host.** What you see on screen is proof the characters arrived.
* **The host paces: one line per prompt byte.** Measured in P04 — unpaced pasting loses 86–96 % of
  bytes. Bulk input is flow-controlled, not buffered.
* **The bridge owns the port exclusively** (`TIOCEXCL` + a lock), and drops the ULP to autonomous
  after 30 s of silence so the fast wake period is not burned for an empty terminal.

---

## 9. Definition of done

> **Done** means a person with nothing but this repo and the board can, in one sitting: flash it
> once, attach a terminal, type a Forth program and watch it become live words, run those words
> inside the event loop alongside at least two other tasks, write a page and the dictionary to
> flash, power-cycle the board, and find the same program still there and still running — all
> without rebuilding anything and without a single silent failure. Every way it can go wrong
> answers with a named error on the terminal and a status bit in the mailbox.

Note what "done" does **not** include: no editor, no filesystem, no floating point, no power
budget, no ANSI conformance. See §2.

---

## 10. Acceptance criteria

Unchecked on purpose: none of these is verified yet. Each is executable and each has a named failure
mode; an item is only ticked when the evidence is recorded in `probe/EVIDENCE.md`.

### R1 — interpreter, not compiled Forth
- [ ] The engine image contains **no** user words and **no** prebuilt dictionary (`nm` on the ULP
      ELF shows no Forth word symbols; the dictionary area is uninitialised at load).
- [ ] On a cold boot the ULP has an empty dictionary (`HERE == DICT`) and the prelude text is
      received as bytes over the byte server, then interpreted on the chip.
- [ ] Typing `: SQ DUP * ;` then `5 SQ .` prints `25`, with no rebuild and no host-side compile step.
- [ ] Changing one prelude line requires only a terminal session (no `idf.py build`), and the change
      is observable in `WORDS`.
- [ ] A deliberately bad line prints a named error and leaves the dictionary byte-identical to
      before the line (HERE and LATEST unchanged).
- [ ] With resident headers moved to the paged name directory (§4.3 resolution A), a resident word is
      still found and executed (`' DUP EXECUTE` works), `WORDS` lists it, and the fault count for the
      first `WORDS` of a session equals the number of directory pages touched — not one fault per
      word.

### R2 — live connection
- [ ] `ulpctl forth` attaches, shows a prompt, echoes each character, and prints `ok` per line.
- [ ] 200 consecutive command lines are interpreted with **zero** dropped output bytes
      (`drops_out == 0`) and zero lost input characters, with the host pacing one line per prompt
      byte. Measured bound (P04, host simulation, 115200 8N1): output drops are zero for any ring
      ≥ 128 B; input drops are zero for any cmd ring ≥ 64 B **only while the period keeps
      `C ≥ r_in · T_gap`** (128 B covers an 11 ms stall). An unpaced bulk paste loses 86–96 % of its
      bytes in autonomous mode and is therefore excluded — that is a flow-control requirement, not a
      ring-size one.
- [ ] A 10-minute interactive session with continuous typing, page faults and task switching loses
      nothing and never stalls (heartbeat monotonic throughout).
- [ ] Detaching the terminal drops the system to autonomous mode within one dead-man period, and
      re-attaching resumes the session with the dictionary intact.

### R3 — event loop
- [ ] `wake_count` increases monotonically and matches elapsed/period within 1 % over 10 minutes.
- [ ] An overrunning wake delays the next wake by exactly its own duration and **no tick is skipped**:
      `gap = span + period` with a stable additive constant (measured 22 ticks, P06).
- [ ] Requesting a period below the floor yields 22 ticks (142 µs), never less, and the tool reports
      the floor rather than pretending it got 1 tick.
- [ ] A task that spins past its quantum is recorded (`overrun++` with its `ip`) and the loop
      continues; the ULP does not hang.
- [ ] No primitive blocks: `KEY` with an empty ring returns `ERR_NO_INPUT` and consumes no tick.
- [ ] A GPIO edge produces exactly one coalesced event per pin per wake, handled in the same wake or
      the next — never lost, never duplicated. **No timestamps:** the wake-cause register reads 0 on
      every wake (P06), so cause comes from polling RTC-IO status.

**Measured (P26): with the minimal 1024 B layer the idle loop touches 3 pages and settles at 0 faults per
pass after one cold pass (432 µs).** With P24's 3044 B layer it touched 6 pages and faulted every pass — so
the layer size, not the layout, was the problem. Caveat being re-checked by P25: both measurements used a
tracer that may not have counted instruction fetches (P24/P26 shared it).

### R4 — multi-tasking
- [ ] Three tasks each increment their own counter; after 1000 wakes the three counters differ by
      at most 1 and the sum equals the expected total for the quantum in use.
- [ ] `PAUSE`/`YIELD` switch tasks with correct stacks: a task that recurses and yields produces the
      same result as running the same word without yielding.
- [ ] A task blocked on an event mask stays out of the run queue until that event arrives.
- [ ] A fourth `TASK` request fails with `ERR_TASK_NO_ROOM` and changes nothing.

### R5 — memory beyond 8176 B (block store)
- [x] `BLOCK` returns exactly one buffer address; a bad block number leaves the stack unchanged and aborts with a
      named `ERR_RANGE`, sending no request (P38, measured: `sp` delta 0 on every path).
- [x] `SAVE` reports through one status cell: `0` on success, a named failure otherwise, with the dirty flag
      preserved on failure (P38: `ERR_BUSY`, server's own copy verified).
- [x] A fetch that would overlap the dictionary aborts with `ERR_BUFOVER` naming both addresses
      (`dict_here=3634 > block_buffer=3584`), instead of overwriting definitions (P38).
- [x] Compiled conditionals and loops are correct after the branch-operand fix: 17/17 across four nesting levels,
      operand proven **2 bytes at `token+2`** by reading back the compiled body (P38).
- [ ] The block words are present in the **shipping image** and a document survives a power cycle. Measured
      cost is **not** 456 + 512: the Forth layer is **530 B** (146 B of it constants and variables), the buffer
      512 B, and the plumbing `blk_xfer` + `blk_sum` + `mailbox[54]` ≈ **500 B** — about **1 300–1 500 B** in
      total. The shipping image has **558 B of app space** and 4 B of pool spare, so this is ~850 B out of reach,
      and the remaining levers delete R4's concurrency or the C-stack margin (E-059, E-062).
- [ ] An unpaced 4 KB paste into the block buffer loses bytes **and the loss is reported** — P04 measured 86–96 %
      loss unpaced, so the console must pace.
- [ ] A block fetch that gets no answer aborts with `ERR_NO_SERVER` within a bounded number of polls (Forth-level
      bound, not a C timeout) — proven on the host in P38; not yet on the chip.

*Superseded:* the transparent-paging items this group used to hold (frame layouts, fault retry, `ERR_HOT_SET`,
`ERR_PAGE_FAULT_LOOP`) are kept in the journal and in P03b–P03f/P19/P26. They were real work and they produced the
numbers that justified dropping the feature; they are no longer requirements.

### R6 — main cores are only a byte server
- [ ] The ULP's Forth code never receives an HP-computed value: every reply is raw bytes plus a
      status word, and the server-side code contains no Forth parser, compiler or scheduler
      (`grep`-verifiable, and stated in the server's own header comment).
- [ ] Stopping the server task (deliberately) makes the next paged access fail with
      `ERR_NO_SERVER` within a bounded retry count — not a hang and not a zero-filled page.
- [ ] A CRC mismatch on a page reply is reported as `ERR_CRC` and the page is discarded, not used.
- [ ] **Exactly one request is outstanding at a time.** Measured (P16): with two in flight, the reply to
      `seq=1` carried the *other* page's bytes with a **valid checksum** — the corruption is
      undetectable by CRC and was only caught by a page marker. The protocol must enforce it, and the
      ULP must refuse to issue a second request while `REQ_PENDING` is set.
- [ ] With the server alive, a 4 KB read from PSRAM through `@` costs no more than one fault per
      page (measured count, printed by the test).

### R7 — storage, no NVS
- [ ] Flash storage uses a dedicated partition; NVS is not initialised or linked into the server
      path (verifiable in the build map).
- [ ] `SAVE` writes the dictionary to flash and `RESTORE` after a power cycle yields an identical
      dictionary checksum and identical `WORDS` output.
- [ ] A corrupted or version-mismatched snapshot is refused with `ERR_SNAPSHOT_MISMATCH` and the
      system boots empty instead of running it.
- [ ] Flash writes are sector-batched: a 200-iteration write workload produces at most one erase per
      sector touched, and the erase counter is published.

### R8 — command-line REPL over USB
- [x] A plain terminal session gets the ULP's prompt and runs `: SQ DUP * ;` then `5 SQ .` → `25 ok`, with no
      repo tool involved. **Met, measured on the board** (E-047) — via `probe/repl/repl`, which is the same
      byte-pump path `picocom` would use; the prompt is emitted by the ULP itself. `7 SQ .` → `49 ok`.
- [ ] `ulpctl forth` sends 200 paced lines with `drops_out == 0` and zero lost input characters.
- [ ] An unpaced 4 KB paste loses bytes **and the loss is reported** with a count; the tool refuses to
      unpace without an explicit flag.
- [ ] An unknown `0x1D` sequence is passed through verbatim (both bytes reach the ring, nothing is
      eaten), and the console never accepts a control byte into a line — binary payloads go through
      framed mode. Measured on the host (P10): `0x1D` occurs **0 times in 86.1 KB** of Forth source,
      6/6 escape cases and 7/7 line-discipline cases correct, XOFF loses 0 bytes, no double echo.
- [ ] A second opener on the port is refused with a named error and does not disturb the first
      session.
- [ ] Detaching drops the ULP to autonomous mode within one dead-man window; re-attaching resumes
      with the dictionary intact and unchanged (checksum equal).
- [ ] `ulpctl monitor` interleaved with `ulpctl forth` on the same port does not corrupt console
      output, **including while console input is flowing** — the escape is parsed before the XOFF
      gate (P10 finding F2).
- [ ] A 129-byte line yields `ERR_LINE_TOO_LONG`, the line is dropped, and the dictionary is
      byte-identical afterwards.

### Cross-cutting (the repo's non-negotiables)
- [ ] Every failure path named above has been *executed* at least once and produced its named error.
- [ ] No silent defaults: no zero-filled page, no clamped counter, no wrapped stack, no dropped byte
      without a counter.
- [ ] `probe/EVIDENCE.md` holds the command and the output for every ticked item.

---

## 11. Risks and open questions

Each question below has an executable probe brief in [`probes/`](probes/README.md); the register there
shows what can run on the host (in parallel) and what needs the board (one at a time).

| # | Question | Why it matters | Answered by |
| --- | --- | --- | --- |
| Q1 | cycles per RTC tick, per token, per wake | every budget above; core clock is not documented | calibration experiment |
| Q2 | behaviour when a wake overruns its period (tick lost / latched / re-entry) | the deadline model must match reality | deliberate overrun test |
| Q3 | real engine size | decides 4 frames vs 2, and whether the prelude fits resident | first ULP build |
| Q4 | fault cost with the main cores asleep vs awake | whether paging is usable unattended | measured round trip |
| Q5 | does an interpreted prelude boot fast enough to be tolerable | decides "always interpret" vs "snapshot by default" | measure boot time both ways |
| Q6 | PSRAM retention in deep sleep | decides whether PSRAM can hold the system of record (assumed: no) | datasheet + test |

---

## 11a. What runs today

A live Forth REPL on the coprocessor, with the main core as a byte pump (E-047):

```
ulp forth
 ok
2 3 + .        →  5 ok
: SQ DUP * ;   →   ok
7 SQ .         →  49 ok
BOGUS          →  BOGUS?
```

**Current, measured:** image **6 888 B** on the wire; pool **7 852 / 7 856** (`.text`+`.rodata` 5 168, `.data` 1 720,
`.bss` 964); `MEMSZ` 1 704 with `V_HERE` 1 146 at boot → **558 B of app space**; C-stack reserve 340 B.
**Multi-tasking (R4) is live**: `SPAWN TA SPAWN TB` with `PAUSE` bodies prints `1324`, three tasks `131242`.
Dispatch is **1 139 cycles**/token (was 1 758), a typed literal **1 623** (was ~28 000). Blocks are **not** in this
image: 456 B of words + a 512 B buffer + ~500 B of plumbing against 558 B of app space (E-062).

Also live, and verified on the board: **multi-tasking (R4)**. `SPAWN` takes a name, resolves its xt and runs it as a
task; `PAUSE` yields. Tasks are stepped once per wake from `main()`, after the console drain, and refuse loudly
(once) if the prompt stack is not empty. Cost: **+496 B of `.text`** (E-055).

## 11b. The next sprint

The platform work is measured and the budget is settled. The product built on it is specified in
[`08-psion.md`](08-psion.md): a character-display, block-backed, overlay-app pocket machine — requirements
D1–D16, hardware specification with pin assignments, the app model, and gates G0–G8. It inherits every number in
§4.3–§4.5 and adds none of its own.

Two bugs gate it: **P36** (do overlays load and execute?) and **P37** (why does the Forth `BLOCK` wrapper hang?).
Both are host-only and both are running or queued.

---

## 12. What would make us stop and redesign

Named in advance, so a failure is a decision rather than a surprise:

* the headerless scheme (§4.3, resolution A) fails to recover ≥ 400 B of headers in a real build, so
  the resident dictionary still cannot hold the prelude;
* a primitive that stores and then faults within one dispatch repeats its store and cannot be made
  restartable — P03d cleared token-fetch granularity (0 mismatches over 187 positions), so this is the
  last open path to abandoning paging;
* fault cost so high that any non-resident definition makes the loop miss its period.

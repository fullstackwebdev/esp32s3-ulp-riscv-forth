# 11 — Findings register

Every fact this project holds, itemised, with **what it means** — the decision it drove, the thing it forbids, or
the question it closes. This is the index to the evidence, not a replacement for it: each row names its pedigree.

**Pedigree rule.** A row is admitted only if it is *measured* on this board (probe number), *read* in a named
section of a cached source (`10-references.md`), or *derived* from a compiler artifact (`nm`, `.su`, `.map`, ELF).
Anything else is a rumour. There are three corrections on the books that started as rumours which happened to be
true, and one that was simply wrong (F-56).

---

## A. The envelope — how big the machine can be

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-01 | The pool is not 8 176 B; the C stack must come out of it | **7 856 B** (8 176 − 320) | every budget starts here, not at the datasheet figure | P21 |
| F-02 | The shipping image, measured end to end | **6 888 B** on the wire · pool **7 852 / 7 856** · `MEMSZ` 1 704 · `V_HERE` 1 146 → **app space 558 B** · C-stack reserve 340 B | every later budget row refers to this build (R4 live, lhu + number-first + hand VM copy) | E-062 |
| F-03 | Engine code is not spread over many functions | **4 818 B** text+rodata, of which `main` is **2 956 B** | GCC inlined the whole dispatch loop; the cost is hidden from `nm` and visible only in `objdump` | E-048 |
| F-04 | The dictionary is a resident 1 280 B block | `MEMSZ` **1 280 B** | the baked prelude sets the floor; it is data, not code | E-048 |
| F-05 | Non-paged `MEMSZ` ceiling | **2 196 B** (**1 880 B** with the C stack charged to the pool) | an upper bound on the dictionary, set by the *engine*, not by RAM | P35 |
| F-06 | Application space in the **shipping** image | **144 B**, not 620 B: `MEMSZ` 1 280 − `V_HERE` 1 136, read from the baked `image.h` | the long-quoted 620 B assumed `MEMSZ` 2 196, which needs an **8 180 B** pool — it was never achievable in this image. The most misleading number the docs contained | E-054, `docs/13-levers.md` |
| F-07 | The block layer itself | **456 B** of Forth + **512 B** buffer | fits in the spare 598 B only without the buffer — which is why it is not in the image | P33, P38 |
| F-08 | Task state | **140 B** per task; 3 tasks = **420 B** — **already allocated in the shipping `.bss`**, inside the 7 258 B (see `12-what-opens-up.md`) | multi-tasking's state is already bought; what `--gc-sections` removed is the 206 B that would create and schedule a task (F-61). Counting this 420 B again as a cost would be an F-56-class error | P27, E-052 |
| F-09 | C stack worst case | **244 B** (176 + 68) → reserve **320 B** | the 8 176 B figure is a fiction without this | P21 |
| F-10 | Forth stack depth actually used | **108 B** (20 data + 7 return cells) | the 16-cell `SD` is ample; a larger `SD` buys nothing | P13 |
| F-11 | Rings, mailbox and `tib` | ≈**600 B** | console plumbing is a sixth of the pool; it must be justified, and it is (F-41) | P04 |
| F-12 | Compiling the prelude **on the chip** | **14 874 B** needed vs 7 856 available; **4 336 B** is a second copy of the 62-body dispatch switch, **4 350 B** the source in `.rodata` | R1 holds for user programs only because the standard vocabulary is **baked**; streaming it from flash is the named follow-up | P39, E-046 |

## B. Time — what a wake costs and what fits in one

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-13 | RTC slow clock is not the documented 136 kHz | **154.9 kHz ± 0.5** | every derived timing figure in the vendored docs is ~12 % wrong for this chip; use the measurement | P05, E-011 |
| F-14 | Core clock and tick | **19.0 MHz ± 1.5 %**, **122.6 cycles/tick** | `rdcycle` and ticks are both usable; there is no need to guess a clock tree | P05, E-011 |
| F-15 | A wake is cheap | **6.46 µs/tick**, **81 cycles** entry | waking on every keystroke is affordable; no need to batch | P05, E-011 |
| F-16 | The timer counts **through** sleep | **+22 ticks** constant across sleeps | autonomous execution is a timer problem, not an accounting problem | P06, E-019 |
| F-17 | The wake cause is unreadable | **0 of 6** reads | a ULP cannot know why it woke; any design that branches on wake source is dead | P06, E-019 |
| F-18 | Dispatch cost | **1 006 / 1 074 / 1 506** cycles (best/typical/worst); `NEXT` = **480.2**; `NEXT` + head = **90.9 %** | the interpreter's fetch loop, not the primitives, is the optimisation target | P14, E-023 |
| F-19 | Doorbell to the main core | **176 µs**, 200/200, task genuinely blocked | the HP can be asleep and still serve; polling is not needed | P23, E-030 |
| F-20 | Block fetch | **144 µs** polling, **176 µs** by doorbell, **3.55 MB/s** | a 512 B block is ~9 % of a wake budget; blocks are usable per-command, not per-token | P16, E-029 |
| F-21 | Pin edges survive sleep but **coalesce** | ≤**1 event per wake**; ceiling **151 edges/s** at a 1 s period (P18 brief; the figure is in the probe result, not in EVIDENCE as its own entry) | an input device must either poll fast or accept lost edges — it cannot queue them | P18 |
| F-22 | A typing slice | **23.7 ticks ≈ 153 µs**; period floor **22 ticks / 142 µs** | interactive latency is dominated by the period, not by work | P04 |

## C. Arithmetic and the instruction set

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-23 | The ISA contract | `-march=rv32imc_zicsr_zifencei -mdiv`, `-Os`, ABI **ILP32 soft-float** | this line, not a PDF, is the boundary; anything outside it does not assemble | ULP sub-build `compile_commands.json` |
| F-24 | Multiply and divide are **slow** | `MUL` **34**, `MULH` **66**, `DIV`/`REM` **34** cycles | one `*` = **28 % of a wake**; a double-width multiply (66) can never appear in an inner loop | TRM §2.6.2 Table 2.6-1 |
| F-25 | But they are **instructions**, not library calls | `mul`/`div`/`rem` each one instruction, no stack frame | the 34 cycles is the opcode; there is no hidden `jal __mulsi3` to remove | `probe/isa/codegen.c` |
| F-26 | Compressed encodings are live | `ret` assembles to 2-byte `c.jr` | hand-written assembly can buy **code density** as well as cycles | `probe/isa/codegen.c` |
| F-27 | The dispatch loop contains **no multiply** | 0 `mul` in the dispatch path; all 59 index scalings are `slli` | no 34-cycle trap sits in the hot path — checked, not assumed | `probe/isa/ulp_main.dis` |
| F-28 | The image's only divides are in number I/O | 3 `mul`, 1 `div`, 1 `divu`, 2 `rem`, 1 `remu`, all in `.`/number reader | 68 cycles per decimal digit is irrelevant next to a human typing | same |
| F-29 | **`rd16` was two `rd8()` calls** | each a `jal` + prologue + bounds check + load + `ret`, on the path that is 90.9 % of a dispatch | tokens are 16-bit and always even, so one `lhu` is legal — and it turned out to be worth **35.2 %** of the dispatch, not the ~1 % the instruction count implied (F-66) | `src/uforth.c:67`, F-18, E-053 |
| F-30 | No hardware stack | every `call` is a `sw`/`lw` pair through software `sp` | a context switch is a register save, not a stack swap — which is why 140 B/task is possible | psABI §2.1 |
| F-31 | ULP interrupts are **not** the privileged spec | custom instructions, 4 usable sources of 32 | `ulp_riscv_isr_register(ULP_RISCV_SW_INT)` is the whole story; there is no `mstatus`/`mcause` to poke | TRM §2.6.3 |

## D. Structure and correctness

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-32 | A branch operand is **2 bytes at `token+2`** | `W,` (2 B) not `,` (4 B) | using `,` compiles an `IF` whose filler `0x0000` executes as `DOCOL` at address 0 and `rsp` climbs 2,3,4… The single most expensive bug class in this repo | P37, P38 |
| F-33 | After that fix, conditionals are correct | **17/17** across four nesting levels | the Forth layer can now be trusted to compile control flow | P38, E-045 |
| F-34 | Block words have strict stack discipline | `sp` delta **0** on every path, including every error | a word that silently changes stack depth poisons the next call; named failures (`ERR_RANGE`, `ERR_BUSY`, `ERR_BUFOVER`) instead | P38, E-045 |
| F-35 | A context switch works **inside a colon word** | shares `vm_switch` with the fault path; **140 B**/task | tasking and paging recovery are one mechanism, not two | P27 |
| F-36 | Exactly one block request may be outstanding | two in flight **corrupt silently, with a valid CRC** | a CRC is not a correctness check when the protocol allows interleaving; the guard must be structural | P16, E-029 |
| F-37 | `.bss` is absent from the ULP `.bin` | `load_binary` zero-fills the reservation first | first-run detection still uses a magic word (`0x52455000`), because a warm restart is not a load | E-047 |
| F-38 | One writer per ring index, u32-aligned | no lock needed, none present | the only place a deadlock could live was removed by construction, not by care | E-047 |
| F-39 | `--gc-sections` deletes symbols, not just code | an unused global vanishes → no `ulp_*` in the header → HP fails to link | a stub that does nothing still has to *look like* it uses what it defines | P41 |
| F-40 | 16-bit code tokens + 32-bit data cells is the **only** affordable width | **−232 B** vs 32-bit references | it pays for 3 tasks; the price is a 64 KB *code* ceiling (~1 600 words), which R5 does not touch | P28 |

## E. Interaction — the console

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-41 | There is a working REPL on the coprocessor | `2 3 + .` → **`5 ok`**; `: SQ DUP * ;` then `7 SQ .` → **`49 ok`**; `BOGUS` → `BOGUS?` | R8 is real, not designed; the prompt is emitted by the ULP | E-047 |
| F-42 | The ULP sends a bare `\n` | client must keep `OPOST\|ONLCR` (`tty.setraw` clears it) | clearing it produces the **staircase** — every reply indented one more space | J-59 |
| F-43 | `\r` and `\n` are both end-of-line | CRLF input runs the line **and** an empty line | a client must strip CRLF or every line answers twice | J-59 |
| F-44 | Unpaced input loses bytes | **86–96 %** lost at every ring depth; connected mode **72/72** intact | the console must pace; "it mostly works" was 4 % of a paste | P04, E-008 |

## F. The boundary between the cores

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-45 | No Forth executes on the main cores — **asserted** | static 6/6, plus a counterfactual where the console returns **`b''`** | R6 is enforced by a checker, not by source intent; re-run it in 0.4 s after any change | E-048, E-049, P41 |
| F-46 | The HP image carries the dictionary only as inert bytes | 1 occurrence of the 1 280 B payload, inside the embedded 6 108 B blob | the blob is legitimate; anything outside it would mean a copy the ULP never sees | E-048 |
| F-47 | The HP must not touch `COCPU_*` while the ULP may be waking | wedge, reproduced on purpose | cost hours and a physical recovery; the doorbell (F-19) is the supported path | P06, P23 |
| F-48 | UART0 is both console and flash port | `/dev/ttyACM1` (CH343) works; `/dev/ttyACM0` (native USB-JTAG) wedges when the app crashes | one port for talking, one for rescue; never flash the other | E-017 |

## G. Dead ends — each killed by a number, not an opinion

| # | Idea | The number that killed it | **Means** |
|---|---|---|---|
| F-49 | Transparent paging (`@`/`!` work anywhere) | shadows alone **888 B** vs **202 B** explicit | 88 % of the app space for an ergonomic benefit; rejected on cost, and the fault machinery on top of it |
| F-50 | Programs as loaded overlays | loader **1 400 B** against **620 B** of app space | the mechanism worked; the accounting did not |
| F-51 | Out-of-line dispatch to save bytes | **+1 186 B** | the compiler was already doing the right thing; "structure" was a size loss |
| F-52 | 4 × 256 B frames | could not **boot** | frame size is pinned by the token + operand + data working set, not by preference |
| F-53 | Compile the prelude at boot | **14 874 B** vs 7 856 | see F-12: the vocabulary is baked, and R1 carries a caveat because of it |
| F-54 | A display and a keyboard | **cancelled by the operator** | headless, console-only machine; `08-psion.md` keeps the cancellation on its face |

## H. Method — lessons about how we got things wrong

| # | Lesson | What happened | **Rule now** |
|---|---|---|---|
| F-55 | **Occupancy is not access** | P25's "hot pages" were counted, not traced; re-tracing with an access tracer changed the answer | a claim about access requires a tracer; counting what is resident proves nothing |
| F-56 | **A convention can masquerade as a measurement** | the +322 B "over budget" was a calling-convention mistake in the harness, not a real cost | re-derive the suspicious number from a second artifact before designing around it |
| F-57 | **Substring checkers lie** | the HP image "contained" `SWAP`, `OVER`, and `DUP` — inside the embedded blob, and inside `…DUPLICATE` / `…HALF_DUPLEX` | match payloads byte for byte; a checker you have learned to ignore is worse than none |
| F-58 | **A checker can flag its own explanation** | the source check failed on the word "interpreter" inside the comment explaining that the interpreter is on the ULP | strip comments, match identifiers; never delete the explanation to silence the checker |
| F-59 | **The tool is part of the measurement** | `pdftotext` is jailed and cannot see this repo; the "missing" manual was a sandbox, not a download | verify the extractor produced bytes before concluding anything about the source |
| F-60 | **A requirement can be measured out of existence** | R5 still demanded transparent paging long after P34/P36 priced it | rewrite the requirement, keep the dead end in the journal as the reason |

## J. What the wins unlocked (measured after the ISA work)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-61 | The task machinery is 80 % present | `tsk` **420 B** allocated; `vm_switch` **102 B** and `vm_task_leave` **120 B** linked and called; `vm_task_init` **72 B** + `vm_next_ready` **54 B** + `vm_run_tasks` **80 B** **eliminated as unreferenced** | enabling R4 costs **~250 B** against **598 B spare**: no redesign, no new state, just entry points | E-052 |
| F-62 | The paged interpreter is 2 520 B of C, entirely absent | `vm_enter` forced out of line = **2 520 B**; `--gc-sections` removed it | a second, independent price tag on the paging feature that F-49 killed from the Forth side | E-052 |
| F-63 | The `lhu` change saves **6 B of pool** and **35 % of the dispatch** | object `.text` 4 948 → 4 936 B (−12 B); linked pool **7 258 → 7 264 B** (+6 B, the bounds branch) | bytes and cycles decouple completely: a change that costs 6 bytes bought 618 cycles per token. Judging it by its size was the mistake | E-052, E-053 |
| F-64 | The fetch cost is a **call chain**, not two loads | `rd16` = 42 B / **11 call sites**, `rd32` 34 B / 18, `rd8` 30 B / 12; `NEXT` = 480 cycles for ~20 instructions | ~24 cycles per instruction means **RTC RAM latency dominates**; cutting an instruction (or a load) may buy little, so P42 must be measured, not argued | E-052, probe/isa/ulp_main.dis |
| F-65 | `-fkeep-static-functions` is a price list | forces the linker's deletions to materialise: **+492 B** net, and a per-function size for everything inlined or dead | every future "can we afford X?" has a first-pass answer in one flag instead of a probe | E-052 |

## K. Adopted from P42

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-66 | One halfword load beats two byte loads through a call | **1 757.75 → 1 139.25 cycles/dispatch (−35.2 %)**, bit-identical across boots; intercept 51 550 → 30 525 | the fetch path is ~24 cycles per instruction, so **call overhead and dependent loads dominate everything**. Adopted; the remaining risk is alignment at call sites that are not token reads | E-053, `src/uforth.c` |
| F-67 | A bench inside the input path measures nothing | three separate harness defects (compile-only `BEGIN`/`UNTIL`; primitives fetch no tokens; `interpret()` re-entered from `drain_cmd`) produced `min=567 err=4` and a machine that echoed without answering | **instrumentation must live outside the path it measures**, and the harness must validate `errf/sp/rsp/ti==tl` before it times anything | P42 attempt 1 |

## L. Levers, measured (`docs/13-levers.md`)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-68 | `MEMSZ` was pinned to the baked image size, leaving pool idle | +120 `MEMSZ` → +120 `.data` exactly; ceiling **1 872** → pool 7 856, app space **736 B** | 592 B of pool was idle while app space was 144 B. **Free 5.1× app space, no code change** | E-054 |
| F-69 | Rings give back 224 B | cmd 128→64, out 256→128, tib 128→96: `.bss` 1 152 → 928 | app space 736 → 964 B; a 64 B command ring is still two wakes of typing | E-054 |
| F-70 | Task records give back 280 B **and** 78 B of code | `NTSK` 3→1: `.bss` −280, `.text` 4 508 → 4 430 | the round-robin search and task copy shrink with the count; re-raising `NTSK` later costs 140 B/task | E-054 |
| F-71 | Combined: app space 144 → **1 316 B** | rings + `NTSK` 1 + `MEMSZ` 2 452 → pool exactly 7 856, spare 0 | a 9.1× increase with no requirement removed | E-054 |
| F-72 | Pool overflow is not caught by the linker | `MEMSZ` 1 880 → pool 7 864, link succeeds, spare −8 | the guard must be the size check, not the link | E-054 |

## M. R4 and the console (P43)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-73 | **Multi-tasking runs on the chip** | `SPAWN TA SPAWN TB` with `PAUSE` bodies → **1324**; three tasks → **131242**; REPL healthy after | R4 is met: cooperative switching inside colon words, driven from the prompt. Cost **+496 B of text** (the 420 B of records were already paid) | E-055 |
| F-74 | **A constant duplicated across two cores is a coincidence, not a constant** | ULP rings 64/128, host still 128/256 → host wrote past `repl_cmd[]` into `repl_out[]`; 3/9 checks failed. Matched + boot assert → **9/9** | symptoms were replayed characters (`3 CUBE .H`, `.HERE?`), which read as Forth corruption. The ULP now exports its sizes and the host refuses to start on mismatch | E-056 |
| F-75 | `pl_halt(0)` on last-task retire kills the console | tasks ran, then the ULP stopped and the port went silent | code written when tasks were the only driver is wrong once something sits above them; the retire path returns to C with `cur = -1` | E-055 |
| F-76 | Stepping tasks mid-drain replays commands | same re-entrancy class as P42's bench: the third time a feature was put inside the path it depends on | step once per wake from `main()`, after `drain_cmd` has published its tail | E-055 |
| F-77 | `idf.py build` does not report pool usage | a **7 902 B** image (46 over) built, flashed and ran; only `ulpmeasure.sh` objected | the pool guard must be a size check in the measurement path, never the linker | E-056 |

## N. Two negatives that close the loop (parallel lanes, audited)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-78 | `rd32` as one `lw` **costs** bytes | text 5 014 → 5 038 (**+24**, +38 pre-R4); pool 7 842 → 7 866 (over) | the 34 B out-of-line body is paid 18 times instead of once. Same lever as `rd16`, opposite sign: there the win was deleting a *call* | E-057 |
| F-79 | …and it would **trap**, because literals are only 2-aligned | `clit()` writes a cell as two `cw()` halves, `P_LIT` reads `rd32(ip)`; value sits at `token+2` → **2 mod 4** | `lhu` needs 2 (safe, E-053); `lw` needs 4 (fatal). Header links are `wr16`/`rd16` — a 2-alignment contract; only 37 of 81 headers are 4-aligned | E-057 |
| F-80 | Blocks are **600–1 090 B** out of reach, with the arithmetic shown | `blk_place_ok` → `MEMSZ` ≥ 2 114 → pool 8 456 (**600 over**); with 200 B app space → 800 over; holding 354 B → 1 090 over | every remaining lever either is already spent or deletes R4. Blocks need a different **shape** (smaller buffer, paged reader, storage outside `MEMSZ`), not a bigger sweep | E-058 |

## O. Blocks, priced properly (P44)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-81 | The Forth block layer is **530 B**, and 146 B of that is not code | `CONSTANT`s + `CREATE`s = 146; code + error strings = 384 | most of the "456 B" is eight dictionary entries that exist only so Forth can say `BLKERR @` | E-059 |
| F-82 | As C primitives, blocks save **490 B of dictionary and cost 350 B of code** | net **≈ 150 B** | a real win, but blocks land at **8 288 B — 432 over** instead of 922 over. The lever works; it does not close the gap | E-059 |
| F-83 | Every block budget on record omitted the plumbing | `blk_xfer` 186 + `blk_sum` 56 + `mailbox` **216** ≈ **500 B** | "blocks cost 968 B" was dictionary + buffer only; the honest range is **1 300–1 500 B** | E-059 |
| F-84 | The mailbox is 6× oversized for the protocol | `mailbox[54]` = 216 B for a 4-word handshake | a 16 B mailbox returns ~200 B, which with the C port leaves blocks ~230 B short instead of 432 | E-059 |

## P. The interactive path (P46)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-85 | Typing cost was **name lookup**, not dispatch | parsed literal **28 155** cycles vs dispatch **1 139** | `find()` ran first and failed for every literal, and each of 81 headers cost two calls (~240 cycles each). The dispatcher, which the asm plan targeted, was never the bottleneck | E-061 |
| F-86 | Two small C changes buy **17.3×** on literals, **4.7×** on lines | literal 28 155 → **1 623**; group 48 344 → **10 305**; `.text` +142 | number-first in `interpret()`, direct byte reads in `find()`. Cost: app space 354 → **226 B** | E-061 |
| F-87 | An over-budget image corrupts the interpreter, not the build | 7 984 B image ran; ULP C stack overflowed into `.bss`; symptom was a bare `?` and vanished definitions | the pool guard must be a **pre-flash measurement** (`flash_safe.sh`), because the link is happy far past the budget | E-061 |

## Q. Memory victory (P47)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-88 | Killing the libgcc calls is the biggest byte win that deletes nothing | text **5 156 → 4 800 (−356 B)**; `.text.memcpy` + `.text.memset` were 127 instructions | `vm_switch`'s two struct copies and a `memset` were library calls; the hand-written word copy costs far less than the 136 B copies it replaces | E-062 |
| F-89 | A 4-word unrolled copy of a 34-word struct overruns by 8 bytes | `sizeof(VM)` = 136 B = 34 words; loop bound `n -= 4` copied 36 | two tasks worked, **three hung the machine dead**; the overrun lands in the adjacent task record. Copy whole words, then the tail — the 20 B it costs is cheaper than a bug that only shows at three tasks | E-062 |

## R. Assembly, priced (P48)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-90 | GCC's RISC-V code is already at the RVC floor | `vm_enter` = 848 instructions in **2 392 B = 2.82 B/instruction** | assembly cannot win on *encoding*; only on executing fewer instructions | E-063 |
| F-91 | A TOS-pointer stack convention halves a primitive body | GCC **29.5 B**/body (64 bodies, 1 890 B) vs hand-written **15.0 B** (measured, incl. `ret`) | the C engine pays `andi+addi+slli+add+lw` per operand because it indexes `ds[(sp-1)&(SD-1)]`; a pointer makes it one `lw`. Projection: **510–930 B** for 64 bodies against an ~850 B blocks gap | E-063 |
| F-92 | The rewrite's risk is the resumability contract, not the primitives | a switch is a 136 B struct copy of a memory-resident VM (P27) | a register TOS pointer must join the save set, so `vm_switch` and `PAUSE` change too. The host suite cannot cover that (R4 is board-side) — the rewrite needs both tests | E-063, E-055 |

## S. The compiler is not the problem (P48b)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-93 | Removing GCC buys **zero** bytes | no libgcc helpers left; `-Os` = `-Oz` = **5 550 B**, `-O2` = 7 900 | nothing to reclaim from the toolchain; the flags are spent | E-064 |
| F-94 | Encoding is already at the floor; half the text is one function | **2.82 B/instruction**; `vm_enter` **2 392 B = 50 %**, other 26 functions 2 424 B | assembly wins only inside `vm_enter`, and only by *convention* (F-91). The other 50 % is logic where C is both clearer and nearly as small | E-064 |
| F-95 | The image generator is C, and it is not optional | `image.h` is produced by compiling `uforth.c` for the host and dumping `mem` | an all-assembly engine loses the thing that bakes the vocabulary. The generator must stay C regardless of what the ULP runs | E-064 |

## T. Dead code (P49)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-96 | The linker leaves nothing behind; the *runtime* does | `gc-sections` is on and no libgcc helpers remain, yet **34 of 65 primitives** are never dispatched by prelude-compilation + the 26-assertion suite | "dead code" here is not unreachable code, it is *unexercised capability* — the linker cannot see it | E-065 |
| F-97 | The optional primitive set is worth **~2 500 B** | `P31_SUBSET` build: text 4 820 → **2 314**, rodata 348 → 80 | this is the largest byte pool in the image, and it is a **capability trade**, not a free lever: every byte of it is a word a program may need. It also reframes blocks: an ~850 B gap is comfortably inside this pool if a subset were acceptable | E-065 |
| F-98 | A coverage report must read names from the artefact | pairing a bit index with a name list parsed from the macro files reported `DUP` as dead (the lists disagreed by two entries) | read the name out of the header the bit refers to; any second copy of an ordering is a bug waiting (cf F-74, the ring sizes) | E-065 |

## U. The asm loop, measured (P50)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-99 | The dispatch **loop** is the cheaper half to rewrite | C loop ~**502 B** (bounds check, checkpoint, table, `!ip`) vs asm ~**185 B**; 4 inline bodies measured together at **278 B** | I had been counting only per-body wins; the fixed overhead C carries per loop is worth more than the cases | E-068 |
| F-100 | Wrap handling costs ~4 B/body and does not kill the win | asm **23.2 B**/body *with* boundary re-derivation vs GCC 29.5 B | the 15 B prototype omitted the wrap; including it still leaves asm ahead because C pays the mask per *access*, asm per *body* | E-068 |
| F-101 | Projected saving **719 B** vs an 800 B countdown | loop 185 + 64 × 23.2 = ~1 673 B against 2 392 B | 90 % of the blocks gap — but bodies that call C helpers will need store/call/reload (~30 B), so expect **400–700 B** in practice | E-068 |

## V. Asm integration shapes (P50)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-102 | Calling asm per token is a **loss**, not a win | `p50_try` = 368 B (7 bodies ≈ 39 B each) against GCC's ~84 B for the same seven | a per-token call pays a frame, a compare chain and a `ret` for a 2-instruction body. **Asm must replace the loop, not be called from it** | E-069 |
| F-103 | The wrap-checked NOS access costs ~5 instructions | `addi, andi, li, bne, addi` for every two-operand body | this is what moves a body from the prototype's 15 B to ~23 B, so 719 B is an upper bound, not an expectation | E-069 |
| F-104 | The loop itself is where the fixed cost sits | C loop ~502 B vs asm loop ~185 B (E-068) | half the available saving is in code C generates *once*, not per case — which is why the all-or-nothing shape is the only one that pays | E-068, E-069 |

## W. Asm verdict: cannot pay (P50)

| # | Finding | Number | **Means** | Where |
|---|---|---|---|---|
| F-105 | A partial asm port **pays for two dispatchers** | 7 bodies: asm 490 B vs the ~84 B of C cases it removes = **−406 B**; the image overflowed 8 192 B with both loops present | the C loop must stay as the fallback, so asm only pays when nearly every body moves | E-070 |
| F-106 | Even a *total* port saves only **40–470 B** | all 64: 1 922 B realistic; but the 5 control-flow cases must stay C (`continue`/`return`) → **−42 B** | against an 800 B countdown, the asm dispatch core **cannot** close the blocks gap. E-068's 719 B assumed the C loop would vanish, which it cannot | E-070 |

## I. Open — the questions this register cannot answer yet

1. ~~**Does `lhu` pay?**~~ **Answered: 35.2 % of the dispatch, adopted** (F-66, E-053). Open sub-question: is every
   `rd16` call site even-aligned? Asserted by construction and unobserved over ~10 000 dispatches, but a
   `-DALIGN_TRAP` build settles it in one run.
2. **Is `DIV` really 34 cycles on this silicon?** That is a documentation figure (F-24), never confirmed with
   `rdcycle`.
3. **Blocks, with tasks kept.** Tasks are *in* now (R4 live). Blocks measure at 456–530 B of words + 512 B buffer +
   ~500 B plumbing ≈ **1 300–1 500 B**, against **558 B of app space and 4 B of pool spare** — ~850 B short, and every
   remaining lever deletes R4's concurrency or the C-stack margin (E-059, E-062). A redesign question: smaller
   blocks, a 16 B mailbox, words as C primitives.
4. **Wake cause.** F-17 says unreadable. If a future IDF or a register we have not found exposes it, designs that
   branch on wake source come back on the table.
5. **Streaming the prelude** (P40): the only path that removes the R1 caveat in F-12.
6. **Ctrl-] / control frames.** `06-repl.md` §3 is designed and not built; `0x1D` currently reaches the line
   buffer and is ignored.

## F-107 · A baked image and a ULP build that disagree about ONE flag dispatch the wrong primitive
The dictionary in `image.h` stores each primitive's id. `P43_TASKS` inserts `X(SPAWN)` **before** the block
entries, so it shifts every id after it. The bake ran without it, the ULP build ran with it (`#define P43_TASKS 1`,
under a comment that said the feature was OFF). Result: the image's `BLOCK` (id 59) executed the ULP's **SPAWN**
(id 59). Every symptom followed from that: `0 BLOCK` printed a bare `?` because `SPAWN` called `word()`, hit
end-of-line, and `err()` printed an empty PAD; `0 BLOCK 1 BLOCK` printed `1?` because `SPAWN` parsed `1` as a task
name and failed to find it. **Not a block bug at all.** Three flags were duplicated across four places
(`subset.h`, `ulp_repl.c`, the bake command line, `pids.h`); the fix is one owning header plus
`_Static_assert(P_COUNT == ID_COUNT)`.

## F-108 · The checksum needed `volatile` for exactly the reason the status already did
`blk_xfer` writes `mailbox[3] = 0` for a READ and later compares it to the buffer sum. Only `&mailbox[2]` was
volatile, so GCC folded the load to the constant 0. Consequence: **every zero block verified** (0 == 0) and the
first block with real data failed `ERR_CRC` — while the server's own log showed `file=65 buf=65 sum=65`, i.e. the
two cores agreed and the ULP still complained. A guardrail warning about the status poll sat one line above the
bug. Any word another core writes must be read through a `volatile` lvalue, once, everywhere.

## F-109 · One buffer + many blocks loses data silently unless the fetch is refused
`65 0 BLOCK C! UPDATE` then `66 1 BLOCK C!` then `SAVE` then `0 BLOCK C@ .` printed **0**: fetching block 1
overwrote the buffer holding block 0's unsaved edit, with no error. Measured on the board. Now a fetch of a
different block while dirty is refused with `ERR_DIRTY` and pushes `-7`; the program cannot believe it wrote.

## F-110 · R4 and R5 do not both fit, and the experimental tree spends R4
With blocks linked the ULP totals **7 934 B** of the 8 176 B pool; plus the 260 B C-stack reserve that is **18 B
over**, and `P43_TASKS` alone is ~496 B of `.text` plus the `tsk[]` table. The blocks tree therefore runs with R4
off (matching its own note that tasks make the console replay stale bytes) and lands at **7 787 + 260 = 8 047 of
8 176, 129 B spare**, `MEMSZ` 1 528, `BLKADR` 1 272, 256 B blocks, **168 B of app space**. `probe/repl` keeps R4 on.

## F-111 · A failed bake leaves the previous `image.h` and looks like success
`./hb -d src/image.h prelude.fs` with `TIBSZ` too small printed `line too long (93 >= 80)` and exited non-zero,
but the tree kept the old image — so the next build silently used a dictionary from a different flag set. The bake
step must check its own exit status, and the header must record the flags it was baked with. `TIBSZ` also sizes
the loader's line buffer, so a 102-character *comment* in the prelude can silently block the bake.

## F-112 · `-msave-restore` is worth 224 B of text on this image, free
Measured in the real build (not a projection): `.text` 4 828 -> **4 604**, one compiler flag, no source change.
The ULP sub-build takes its flags from IDF's `toolchain-ulp-riscv.cmake`, which has no "extra flags" hook, so the
flag is injected through `EXTRA_CMAKE_ARGS` with `-DCMAKE_C_FLAGS` — and the baseline string is **read out of
IDF's toolchain file at configure time** rather than retyped, because a second copy of
`-Os -march=rv32imc_zicsr_zifencei -mdiv …` would diverge silently and a missing `-mdiv` is a different machine.
The other candidates measured **zero**: `-fno-builtin` 0, `-fno-stack-protector` 0, `-flto` pointless in a
single translation unit (BFI).

## F-113 · A hash dictionary saves 406 B, but only if the link AND the code field both go
First measurement of the idea — hash replacing name+length, links kept — gave **82 B**: 81 words at an average of
**3.5 characters** (`+`, `DUP`, `.`), 283 B of names, so there is simply not much name to delete. The saving is
in the *structure*: a header of `link + hash + code` is 8 B whatever the name length. Dropping the link (fixed
4-byte stride in a separate area) and folding the xt and the immediate flag into the same 4-byte word gives
`hash20 | xt11 | imm1` = **324 B for 81 words vs 730 B** — a 406 B dictionary and an `lw`-per-header lookup
instead of a link chase with byte compares.

Alignment decided the design: a 32-bit key at a 2-mod-4 address **traps** (F-78), so entries must be 4-aligned,
which is why the header area starts at a multiple of 4 and steps down by 4.

## F-114 · The baked image and the ULP build must agree about `MEMSZ`, and now they are forced to
With headers anchored to `HDRTOP = MEMSZ`, `image.h` carries an **absolute** address. The shipping image had been
baked at `MEMSZ 1900` while the ULP built at **1704** — harmless while headers were link-chained from the bottom,
fatal afterwards: the ULP would look for headers above its own `mem[]`. Now `image_boot_assert()` checks
`V_LATEST <= MEMSZ`, `V_LATEST % 4 == 0`, `V_HERE <= V_LATEST` at boot and halts with code `0x51`.

The same change broke `IMMEDIATE`, which is **Forth in the prelude** (`LATEST 2 + DUP C@ 128 OR SWAP C!`) and
wrote into the middle of the new hash. The symptom was `IF?` three lines further down, not an error at
`IMMEDIATE`. One header shape, one owner of the flag bit.

## F-115 · The stack index wrapped silently, and the suite could not have caught it
`PUSH` used `ds[sp & (SD-1)]`, so at `SD=16` the 17th value overwrote slot 0. `15 FIB .` measures **610 at
SD 256** and **377 at SD 16**; a three-line file **hangs** the machine at SD 16. The suite peaks at **6**
data cells, which is why months of green told us nothing — a test suite only certifies the depths it
reaches. Now a push past `SD` sets `stack_ovf`, reported once at the dispatch boundary as `ERR_STACK`
(`0x89`) with the stacks reset, so the line is lost and the session survives. Cost +22 B text, **0 pool**;
`SD 32` would have been +394 B.

## F-116 · Comparing `a + width` instead of `a` is a wraparound bug, not a bounds check
`rd16` tested `a + 1u < MEMSZ`, which is **true** for `a = 0xFFFFFFFF` because the sum wraps to 0. `-1 @`
therefore passed the check and read `mem - 1`. `P(a)` was always correct because it compares the address
itself. Any "is there room for N bytes" test must compare the address, never the address plus its width.

## F-117 · Message text cost 104 B of the ULP's `.rodata`; it belongs on the host
One `MSG_LIST` X-macro expands to enumerators on the ULP and to the string table on the HP, so the two
sides cannot drift, and `.rodata` fell 372 → **268** — which is now *only* the 67-entry dispatch jump table.
`strings` over the ULP image returns **0**. The transcript stays byte-identical because `tests/run.sh` pipes
the engine through `tools/expand.c`, which includes the same header: the test proves the operator's view,
not a filter's own copy.

## F-118 · Coverage tracked the code, not the failures
Five real defects were found in one afternoon (stack wrap, `rd16` wrap, `IMMEDIATE`/header flag, image `MEMSZ`
drift, hash-vs-name economics). The suite caught **none** of them: it exercises six stack cells, no wild
address, no case variation, no deep recursion, and no error path. A suite that grows with the *features*
certifies the features; coverage has to grow with the **failures**. Every one of those five now has a test that
fails if the fix is reverted, and the error tests carry an `888 .` sentinel so an abort is visible in the diff.

## F-119 (RETRACTED) · The "engine defect" was an idiom mistake
**This finding was wrong and is kept as a correction.** It claimed that calling a `CONSTANT` from inside a
colon definition underflows the stack. Narrowed with four experiments, the engine is fine: a DOCON works
once, works in a loop, and a DOCVAR works in a loop. What actually failed was
`HERE CONSTANT VB 0 ,` — `HERE` is read **before** the header is created, so `VB`'s value is the address of
`VB`'s own **header** (measured: `VB` = 590, `VB @` = 38 666 242 = header bytes, `HERE` after = 600). `@`
there reads a link field and `!` there corrupts the dictionary, which presented as exactly the symptoms I
filed.

The real finding, now tested in `tests/semantics.fs`:

**`HERE CONSTANT X` names a header; `CREATE X ,` names a body.** A buffer must be reserved by a word that
already exists, and named with `CREATE` *after* it, or the buffer and that word's own code are the same
bytes. Both mistakes were mine, and the benchmark caught them — which is the argument for having one.

## F-120 · `,` appends past the header area without a bound check
The header path checks before it writes (`ERR_DICT`), and `image_boot_assert` checks the baked layout at
boot. The comma path does not. Measured on the device (P52): with 154 B of application space, `RES`
(`16 0 BEGIN DUP , 1+ DUP 16 < 0= UNTIL DROP`) writes 64 B, runs into the header area, and erases headers.

The symptom is not "dictionary full". It is **`.` becomes an unknown word** — the machine loses the ability
to report anything, and the marker printed `C .? D .?`. A later `CREATE` then executed in **0 dispatches**,
and two loop workloads completed in ~28 700 cycles, i.e. one iteration instead of 500, because their
definitions were gone.

**Fix:** guard the comma path exactly as the header path is guarded —
`if (V_HERE + 4 > V_LATEST) { err(ERR_DICT); break; }` — and let it be loud, because the alternative is a
wrong-word bug that reads as "the engine is broken".

## F-121 · 200 B of `.bss` were allocated for a protocol that indexes four words
`static u32 mailbox[54]` — 216 B — while `BLK_MB` is 4 and only `mb_get`/`mb_set` at indices 0..3 are ever
used. It was P04's status mailbox, kept after the block protocol was reduced to four words.

Because application space is `V_LATEST − V_HERE` and both live in `mem[]`, every byte of `.bss` freed is a
byte available to `MEMSZ`: `mailbox[BLK_MB]` plus `MEMSZ` 1 200 → 1 400 moved **200 B** into the dictionary
gap. Measured: application space **154 → 354 B**, pool unchanged at 7 853 / 7 856, nothing removed.

The general rule, now in `countdown.sh` and `CONSTRAINTS.md`: **`.bss` and `.text` are not "overhead", they
are the app space.** Audit them by symbol before concluding that a machine this size cannot grow.

## F-122 · `PAUSE` does not hand the machine to the other task (OPEN)
Two tasks that both `PAUSE` do not interleave. With `: PC 1 . PAUSE 2 . ;` and `: PD 3 . PAUSE 4 . ;`,
`SPAWN PC SPAWN PD` must print **1324** (each digit once, alternating). It prints **122** — variably
**1212** before the flush change below — so the second task resumes inside the first task's body.

**Confirmed on the device, not just the host**: `SPAWN PC SPAWN PD` → `1212` on the chip at `MEMSZ` 2 024.

Why it survived 15 iterations of optimisation: the host build **never stepped tasks** (`vm_run_tasks` was
called only from the ULP's `main`), so no host test could execute two tasks at all; and every device probe
used PAUSE-free tasks (`: TA 10 20 + . ;`), which do work (`3070`). The defect is therefore older than this
session's changes.

What is known:
- `vm_copy(VM *d, const VM *s)` and both call sites in `vm_switch` have the right direction.
- Adding `VM_FLUSH()`/`VM_RELOAD()` around PAUSE's `vm_switch` — which is *required* since P56 hoisted `w`/`ip`
  into locals — changed the symptom (1212 → 122) without fixing it, so it is a necessary but not sufficient
  part of the fix. Reverted rather than shipped, because a partial fix that changes one wrong output into
  another is not progress.
- The remaining suspect is the paused task's saved `W`/`IP`: the resumed body starts at the first task's
  continuation, which is what a save into the wrong record (or a load from the wrong record) looks like.

**Guarded by** `tests/known_defects/tasks_pause.fs` + `tools/known_defects.sh`, which asserts the CORRECT
string (`1324`) and prints `FIXED` when it starts passing. It lives outside `tests/*.fs` on purpose: that
directory requires a golden per file, and recording `122` would be recording a gap.


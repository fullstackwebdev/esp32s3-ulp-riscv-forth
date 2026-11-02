# JOURNAL — everything tried, learned and rejected

Append-only lab notebook for this repo. Every entry says what we tried, why, what actually happened, and
what changed as a result. Newest entries go at the **bottom** of §2; corrections and dead ends are kept
permanently in §3 and §4 so we do not re-learn them.

Evidence lives in [`../probe/EVIDENCE.md`](../probe/EVIDENCE.md) (E-001 … E-029) and in
`probe/results/P*/RESULT.md`. This journal is the narrative; those files are the receipts.

---

## 0. How we work — rules bought with failures

| Rule | Bought by |
| --- | --- |
| **15 minutes per probe, one run, no slices.** T−2 min: stop starting work, write up, kill processes. If it doesn't fit, the question is too big — cut the question, never extend the clock. | The first wave ran 40-minute boxes and one agent burned 4 minutes on `find /`. |
| **Board is exclusive; lock it with `flock` before touching `/dev/ttyACM0/1`.** | Two board probes would otherwise flash the same chip. |
| **Flash over `/dev/ttyACM1` (UART0), never the native USB.** The CH343's DTR/RTS drive EN/IO0, so UART0 can always force download mode. | The board wedged for hours after a probe crashed the app; only UART0 recovered it (J-16). |
| **Never run `find` outside the repo.** | An agent ran `find /` and lost 4 of its 15 minutes. |
| **Keep the image you flash plus its `flash_args` in the result dir.** | The firmware that was on the board before this session is gone forever (J-16). |
| **Check the baseline digest before sweeping.** | P03e swept nothing because its fault-free baseline livelocked; the run was a blank. |
| **Validate the fixture before trusting it.** | My own `boot_min.fs` had `BASE 12 @` instead of `12`, so `HEX` corrupted the dictionary and destroyed P03's baseline (J-13). |
| **Confirm allocation from `nm -S`, not from "it linked".** | The first P22 link "passed" with 880 B spare because 728 B of arrays had been dead-store-eliminated (J-28). |
| **Never pipe a long run through `head`; log to a file.** | P03's hang lost its own evidence that way. |
| **A probe's verdict is a claim; re-read its evidence file.** | Every reconciliation in this journal did that. |
| **Never write `COCPU_*` from the main core while the ULP may be mid-wake.** | That is what wedged the board (J-16, J-18). |

---

## 1. Starting point

The operator's request, in their words: **an interpreter, not compiled Forth; an event loop; multi-threaded;
an 8 KB operating system; reachable from a command line; any memory usable via paging through the other
cores, which do communication and memory only; no Wi-Fi, no Bluetooth, no NVS.**

We had a prototype (`probe/uforth/uforth.c`): a token-threaded Forth in C, no libc, no malloc, one `mem[]`
array, ~64 primitives, and a text interpreter. It ran on the PC and passed 53 tests. Nothing had run on
the chip.

Docs written first, from ESP-IDF v5.4 sources and the v5.5 page: `00-background` (platform facts),
`01-proposal` (design + R1–R8 + acceptance), `02-harness` (how to drive the board), `03-prototype-review`
(the prototype, by execution). Nine probe briefs followed.

---

## 2. Timeline

**J-01 · The envelope, before any probe.**
8176 bytes usable (not 8192 — the loader will not use the last 16). IDF's runtime floor is 128 B. A
30-line Forth boot layer plus primitives was already 1352 B in the prototype. RTC slow clock documented at
136 kHz, RTC tick = one wake trigger.

**J-02 · P01 — how big is the interpreter?**
Built for real through `ulp_embed_binary`, stub subtracted by a control link. **3818 B** (`.text` 3556 +
`.rodata` 252). I had estimated 2600. The error is 1.2 KB — the size of the dictionary we no longer had.
Also measured: `.bin` 3948 at `MEMSZ` 2560; `mem[]` is `.bss` so it never inflates the blob;
**`MEMSZ` 4096 cannot link** against 8176 (3948 + 4096 + 290 = 8334). At 4 frames the dictionary would
have 560 B; at 2 frames 1584 B.
*Changed:* the frame count went to 2, and the dictionary was declared short.

**J-03 · P02 — 16-bit vs 32-bit references.**
Both builds passed the unchanged 53-test suite. **25.09 → 39.22 B/word** (1.49× the dictionary),
max 60 → 96 B; **6.5–8.7 %** of definitions straddle a 512 B page (10.9–15.2 % at 256 B). Literals are
26.5 % of body bytes; headers 44 % of the dictionary. Straddle rate ≈ mean size ÷ page size, so it is a
property of definition size, not of the compiler.
*Changed:* "one definition per page" became "at most two, both pinned" — and the 44 % header figure later
became the lever that saved the budget.

**J-04 · P04 — console rings and slicing.**
Recommended `k = 4` tokens per step, **128 B command ring, 256 B output ring**, 4 steps per wake. Zero
drops interactively and in connected mode; an unpaced paste in autonomous mode loses **86–96 %** of its
bytes at every ring that fits the budget, so bulk input must be **flow-controlled, not buffered**.
The headline: **`k` does not bound a wake — one token can cost 505 primitive dispatches** (a colon word
with a 100-iteration loop). Resumability at token boundaries is not resumability.
*Changed:* the resume point must be a primitive dispatch.

**J-05 · P05 (first attempt) — the clock, half done.**
Instruction costs measured: dependent ALU **4.0 cycles**, RTC-RAM word load **8.1**, byte load **8.6**.
`cycles per tick` failed because `RTC_CNTL_TIME_LOW0` is a latched snapshot — it needs
`RTC_CNTL_TIME_UPDATE` set and allowed to self-clear first. Reported `PARTIAL` rather than guessing.
*Changed:* nothing yet; the number was owed.

**J-06 · P05 (second attempt) — the clock, closed.**
**122.6 cycles per tick**, core **19.0 MHz ± 1.5 %**, **RTC slow clock 154.9 kHz** — *not* the documented
136 kHz (+14 %). **1 tick = 6.46 µs.** Wake entry costs **81 cycles**, so a 1-tick wake has 41 cycles of
usable work: ten ALU ops. Also: IDF's `ULP_RISCV_CYCLES_PER_US 17.5` is 8 % low, so
`ulp_riscv_delay_cycles()` under-delays.
*Changed:* every tick→µs conversion now uses the calibrated frequency; "wake every tick" is impossible.

**J-07 · P03 — paging retry, destroyed by my own fixture.**
Built the harness (frame table, `resolve()`, fault injection). Its baseline came back `err=99` and the
sweep never ran: `boot_min.fs` had `: BASE 12 @ ;`, which returns the *contents* of `V_BASE`, so `HEX`
stored 16 into `V_LATEST+2` and broke the dictionary link chain (`LATEST 1332 → 1049908`). Five regression
tests and a guardrail later, that is fixed — and a second bug appeared while writing the comment: the
guardrail line was 90 bytes and the Forth loader rejects lines ≥ 80.
*Changed:* fixture fixed; a rule added that a probe validates its own fixture before sweeping.

**J-08 · P03b — exhaustive sweep: the retry design was wrong.**
187 dispatch positions, one fault at each, 4 frames. Baseline clean. **32 of the 83 faultable positions
gave a different result (39 %)** — 24 changed the page image, 8 changed the live stack, including one
position with exactly one fault and one retry and no cascade (measured `sp=0` instead of `1`).
`ERR_PAGE_FAULT_LOOP` worked (fires after 5 retries). No hangs.
*Changed:* `01-proposal` §4.2 rule 2 rewritten to move the resume point to **word boundaries** — which was
the wrong conclusion, corrected one probe later.

**J-09 · P03c — one position, two traces: why it broke.**
The specimen: `P_DOCOL` at `w=1408, ip=1410`. Fault-free, it pushes return address `1488`. Retried, it
pushes **`1410`** — because the checkpoint was saved **before** `w = rd16(ip); ip += 2`, so the retry
re-executed a dispatch that had already completed. The phantom return address then made `EXIT` return into
the wrong place and the body ran twice (105 dispatch checkpoints vs 95). The other candidate cause — a
store inside a primitive that faults later — appears nowhere in the trace.
*Changed:* the fix is one line: checkpoint **after** the fetch.

**J-10 · P03d — the one-line fix, verified.**
Same sweep, checkpoint moved. Baseline digest identical (`chk=4f99db40 sp=1 rsp=0`) — proof the edit moved
the checkpoint rather than changing semantics. **187 positions, 0 mismatches, 0 hangs.** All 32 previously
failing positions now reproduce the fault-free digest.
*Changed:* **fine-grained retry adopted; word-boundary pinning dropped.** That mattered because with 2
frames and 2-page definitions, pinning would have held every frame and thrashed. Frames stay transient.

**J-11 · P03e — BLOCKED, and accidentally the most useful result of the day.**
The probe asked "does a store-then-fault primitive repeat its store?" It answered nothing: its workload
**livelocked with faults disabled**, so zero positions were swept. That is a blank as a probe, and it is
recorded as `BLOCKED`, not as a pass.
But the livelock was the finding: a single dispatch can touch **three pages at once** — token, inline
operand, data — and with 2 × 512 B frames the LRU evicts the page the retry is about to need, so it makes
**zero progress**, 302 retries, `ERR_RETRY_CAP`. The static audit also answered the original question:
**0 of 63 primitives** can store-then-fault; every store path pre-touches its whole byte range.
*Changed:* frames went to 4 × 256 B (same RAM, more slots) — which was **also** wrong, one probe later.

**J-12 · P03f — 4 × 256 B does not work; 4 × 512 B is the minimum that boots.**
4 × 256 B cannot even compile the prelude (`ERR_RETRY_CAP` at `ti=12 addr=764`). 3 × 512 B compiles but
dies on the workload. The rule is **frames ≥ N + 1** where N is the pages a dispatch touches, and
**shrinking pages raises N**. 4 × 512 B reproduces the clean sweep.
*Changed:* frames = **4 × 512 = 2048 B**, and the 512 B that the budget was short had to come from another
line, not from frames.

**J-13 · P19 — can the compiler keep token and operand on one page?**
Yes, and it is cheap: pad to the boundary before a token, cost **6 B (0.46 %)** in the prelude. But **N
stays 3** — the third page is the **data** page (cycle `602 / 1500 / 537397248`), and no compiler rule can
merge data with code. 3 × 512 still dies; 2 × 512 cannot compile.
*Changed:* frames are confirmed at 2048 B; the shortfall must come from somewhere else.

**J-14 · P10 — console line discipline and escapes.**
Reserved byte `0x1D` appears **0 times in 86.1 KB** of real and synthetic Forth source. Escape table
**6/6**, line discipline **7/7**, XOFF lost **0 bytes** of 198, no double echo, suite 58/58.
Two findings changed the design: **F2** the escape must be parsed *before* the XOFF gate (otherwise
`monitor` goes deaf exactly when you type fast); **F3** the line buffer must equal the ring size — 80 B
behind a 128 B ring produced errors that looked like ULP faults. Also removed a contradiction in my own
requirement: R8 said a literal `0x1D` round-trips, which is impossible because the console ignores control
bytes. Binary data goes through framed payloads.
*Changed:* line buffer 128 B (cost 48 B), escape table simplified, R8 restated.

**J-15 · The REPL became requirement R8**, with a design (`06-repl.md`): console on UART0 for
tool-free `picocom` use, passthrough by default, framed only for control frames, ULP echoes so what you
see is proof of arrival, one line per prompt byte.

**J-16 · P06 (first attempt) — the board wedged, and the firmware was lost.**
Flashed cleanly, hash-verified, then silence: zero bytes on `/dev/ttyACM1`, `Write timeout` on
`/dev/ttyACM0`. Every software reset path failed — stub flasher, `--before usb-reset`, `--before
no-reset`, DTR/RTS, `--no-stub`. The USB device kept enumerating, so it was the chip, not the cable.
The operator had to press EN. Even then it re-wedged, because the crashing app came straight back.
**Recovery: `esptool -p /dev/ttyACM1 chip-id`** — the CH343's DTR/RTS drive EN/IO0, so UART0 can force
download mode. That is how the board was recovered, its P05 image reflashed, and its console verified
(4319 bytes, `mcyc1024=122541`, `hz_milli=154058`).
**The firmware that was on the board before this session is gone.** P05 overwrote it with no backup. My
process failure; unrecoverable.
*Changed:* UART0 is the flashing and recovery port; every board probe keeps the image it flashes plus
`flash_args`; the bridge task must be watchdogged; the console lives on UART0 precisely so a dead USB
still leaves a voice.

**J-17 · P06 (second attempt) — wake timing, and the wedge explained.**
Overrun is **not** lost/latched/re-entry: `gap = span_of_previous_wake + 22 ticks`, with the 22 constant
while span swept 3 → 47 ticks. Three rival models refuted by that. So **the timer counts sleep, not
period**: a slow wake delays the next by its own duration, nothing is skipped, the rate slips.
`ulp_set_wakeup_period(8 µs)` floors at **22 ticks (142 µs)**. Timer and GPIO **can** be armed together
(`RTC_CNTL_ULP_CP_TIMER_REG = 0xA0000000`), but **`RTC_CNTL_SLP_WAKEUP_CAUSE` reads 0 on every wake** —
attribution is impossible, so pin events must be polled and coalesced. GPIO latency not obtained.
The wedge reproduced and was **stage-attributed**: it dies inside the ULP retire path that writes
`COCPU_CTRL` while the HP is disarming the ULP. Watchdog armed, no panic — a hardware-level stall.
*Changed:* §5's timing model, R3's acceptance items, and the hard rule about `COCPU_*`.

**J-18 · P12 — the engine at 32-bit references with paging.**
**3986 B** (+168, almost all of it paging helpers). Frames and page table cost **0 B** of blob
(1040 B of `.bss`, proved three ways). But the spare went **negative** (−266 B), and image + `.bss` is
8006 of 8176 — so 32-bit references and ≥ 4 KB of Forth memory cannot both be paid for.
*Changed:* the budget was declared broken and the levers enumerated.

**J-19 · P13 — the stacks are tiny.**
Instrumented at depth 256 so nothing was capped: peak **20 data + 7 return cells = 108 B** across prelude
compilation, 5-deep nesting, 3-level loops, 60-character strings, worst-case `find`, and a 100-iteration
loop. Compile depth scales with source nesting, not program size, and is *below* runtime — so the compiler
needs no stack of its own.
*Changed:* stacks 400 → **128 B**, and 272 B went to the dictionary.

**J-20 · P14 — what a dispatch costs.**
Static accounting on the rv32 build, weighted by P05's measured classes: **1 074 cycles typical**
(1 006 best, 1 506 worst), of which **90.9 % is `NEXT` plus dispatch head** — because `NEXT` did two
byte-wise `rd32` fetches at **452 cycles each**. A 4-token typing slice = **35 ticks ≈ 226 µs**; one
prelude line 113 µs; P04's 505-dispatch token **28.6 ms**.
*Changed:* §8's latency claims, and I named D7 the highest-value change — which was wrong (J-21).

**J-21 · P20 — the lever is the primitive set, not the accessor.**
Four builds. **A** reproduced 3986 B exactly. **B** (native `lw`/`sw`): **+116 B** and **0 dispatch cycles
saved** — because the shipped engine fetches tokens through `rd32_paged()` (resolve once, four `lbu` on the
frame), never the byte-wise chain; D7's 8.0×/5.5× applies to `@`/`!`/`find`/`mkhdr`, i.e. parse and
compile. **C** (40 primitives instead of 64): **engine 3162 (−824)**, prelude dictionary **1716 (−240)**,
dispatch **726 cycles**. **D** (prelude resident) was 348 B short.
Also: **a page miss estimated at ≈ 18 700 cycles ≈ 0.99 ms, 26× a dispatch** — which P16 then corrected
downward by 6.8× (J-23).
*Changed:* the primitive set trimmed to 40; D7 demoted to a compile-speed fix in every document; typing
slice 153 µs; paging policy named as the dominant cost.

**J-22 · P21 — the C stack is 244 B worst case.**
The engine is not recursive, so the deepest static chain from the compiler's own `.su` output is a hard
bound: `main` 96 → `clit` 16 → `cw` 32 → `rd32` 16 → `rd16` 16 → `rd8` 0 = **176 B**, tied by
`main → find → rd32 → rd16 → rd8`. Plus the interrupt `SAVE_REGS` **68 B** on the same stack = **244 B**.
Host verification: observed 368 B against a 464 B static bound, so the method never understates.
*Changed:* C stack 400 → **320 B** (76 B margin).

**J-23 · P16 — a page fetch is 144 µs, and two in flight corrupt silently.**
**A** (HP awake, polling): **22.35 ticks / 144 µs**, 200/200, spread 1.07×, **3.55 MB/s**. My 0.99 ms
estimate was **6.8× too high** (lower bound: internal RAM, PSRAM not enabled). Break-even **23 ticks**;
fault + dispatch ≈ 30 ticks; typing slice + fault ≈ 53 ticks — so 32–64 tick connected mode holds *if
faults batch to one per wake*.
**B** (HP blocked, woken by the ULP): **not measured** — the doorbell produced **0 ISR events in 200
attempts**, both muxes. **C** (deep-sleep wake): path not in that image.
Failure modes all detectable: `TIMEOUT_NO_ANSWER` after ~158 ms, `CHECKSUM_REJECTED`, `RANGE_REJECTED`
with nothing copied. And the nasty one: **two requests in flight → the reply to `seq=1` carried the other
page's bytes with a valid checksum.** CRC cannot catch that; only a page marker did.
*Changed:* paging is affordable in the loop; §8 restated; **single outstanding request is now a hard
requirement in R6**.

**J-24 · P22 — the machine links, with 94 bytes to spare.**
Built the full §4.3 machine: 40 primitives, 32-bit refs, 4 × 512 frames, 128 B Forth stacks, 320 B C
stack, 128 B line buffer, headerless resident dictionary, names in a paged directory.
Resident dictionary **1104 B** (612 B of headers removed from 1716); directory **812 B** for 78
definitions; **`MEMSZ` 1188 B** is the largest that links. At the predicted 1380 the link **fails** —
8046 vs 7856, **190 B over**. The 202 B gap is fully named: **142 B of hook/REPL glue with no budget
line**, 28 B of engine growth from the `MEMSZ` constant folding into access paths, 22 B alignment, 10 B
residue. **94 B left in total.**
And a method trap: the first link "passed" with 880 B spare because **728 B of arrays were dead-store-
eliminated out of `.bss`**; `nm -S` caught it.
*Changed:* the budget table is now the linked one; the design has **no room to grow**, so tasks, the event
loop and the REPL words must all be paged.

**J-25 · Decision taken by the operator: resolution A** — headerless resident words plus a paged name
directory, accepting that the first `WORDS` of a session may fault once per directory page.

**J-26 · Requirement R8 added**: a command-line REPL over USB, no Wi-Fi, no Bluetooth. Design in
`06-repl.md`, eight acceptance items, probes P10 (host, PASS) and P11 (board, not yet run).

**J-27 · Booking keeping: 15-minute boxes.** The cap started at 40 minutes, went through a 5-minute
slice experiment (too short to contain a build), and settled at **15 minutes, one run, no slices**. The
rule that makes it work: *if it does not fit, the question is too big.*

---

## 3. Corrections log — things I asserted that the measurements killed

| # | I said | Reality | Fixed by |
| --- | --- | --- | --- |
| 1 | "8 KB of RAM" | **8176 B** usable | Kconfig range; measured `__stack_top = 0x1ff0` |
| 2 | "136 kHz RTC slow clock" (from the docs) | **154.9 kHz** measured on this board | P05 |
| 3 | "a 1-tick period is possible" | floor **22 ticks / 142 µs** | P06 |
| 4 | "an overrunning wake loses ticks" | **drift**: interval = sleep + work, nothing lost | P06 |
| 5 | "GPIO events are timestamped" | wake cause register reads **0 always**; poll and coalesce | P06 |
| 6 | "2 × 512 B frames" | **4 × 512 B**; 4 × 256 cannot even boot | P03f, P19 |
| 7 | "word-boundary pinning is the fix" | fine-grained retry is correct; pinning dropped | P03d |
| 8 | "the resume point can be any primitive" | not until the checkpoint moved **after** the fetch | P03b → P03d |
| 9 | "D7 (native accessors) is the highest-value change" | **0 dispatch cycles saved, +116 B**; it is a parse/compile fix | P20 |
| 10 | "a page miss costs ~0.99 ms" | **144 µs**, 6.8× cheaper | P16 |
| 11 | "the budget has ~440 B spare" | **94 B**, and only after trimming to 40 primitives | P12, P20, P22 |
| 12 | "a literal `0x1D` can round-trip through the console" | impossible — control bytes are ignored by design | P10 |
| 13 | "flash on the native USB" | UART0 is the flashing **and recovery** port | J-16 |
| 14 | "16-bit tokens can't index > 64 KB, so we need 32-bit" | conflated **code** references with **data** addresses; data was always 32-bit, and 64 KB of code is ~1600 words | P02, §4.3 |
| 15 | "the doorbell doesn't work on this chip" | it works: 176 µs, HP task blocked. P16 tested the wrong signal source | P23 |
| 16 | "the OS layer will fit in a frame or two" | **3044 B headerless = 5.9 frames**; the idle loop thrashes | P24 |
| 17 | "the OS layer cannot fit this machine" | written to the **literal** requirement it is 1024 B (2 frames) and runs fault-free | P26 |
| 18 | "the scheduler gives us multitasking" | `dsp`/`rsp`/`ip` are still C statics — records switch, machine does not | P26 |
| 19 | P24 "6 pages / 6 faults per pass", P26 "3 pages / 0 faults" | **Both were occupancy counts, not traces.** Re-traced: P24 is **7 pages / 13 faults per pass**, P26 is **2 pages / 0 faults**. P26's claim survives; P24's method did not | P25 |
| 20 | "three tasks cost 24 B of task records" | **140 B per task** — the switch saves both stacks by value. Three tasks are **420 B**, and the budget has 94 | P27 |
| 21 | "pin edges are never lost" | **merged**: k edges → 1 event, ceiling one per pin per period | P18 |
| 22 | "32-bit references are the safe choice" (adopted after P02) | **16-bit code tokens are the only thing that pays for R4**; data addresses were never the constraint | P28 |
| 23 | "the budget is closed" | it closes **with 232 B**, but the engine measured in P22 had no `vm_switch` and no OS glue — those come out of the 232 | P22, P27, P28 |
| 24 | "one giant inlined dispatch function is the bloat; make it out of line" | **out of line costs +1186 B.** The bodies are ~57 B each wherever they live; only libgcc's 400 B was recoverable | P30 |
| 25 | "the shipping engine has 40 primitives" | it was built with **61**; P20's 40-set and P29's 61-set are different machines, and the difference is ~1 200 B | P29, P30, P31 |
| 26 | "the engine ceiling is 3438 B" | fixed lines measure **4740**, so the ceiling is **3116** — 322 B never appeared in the table | P31 |
| 27 | "trimming primitives to what the code uses gives the right machine" | **circular**: it removes `I`/`J`/`UNLOOP` (no user `DO … LOOP`) and `GPIO!` (no output pin) | P31 |
| 28 | "the budget is off by 322 B of arithmetic" | **convention error**: code counted as allocation, a non-image line counted, three real allocations omitted. Ceiling is 3116, or 2796 with the stack | P32 |
| 29 | "paging and a programmable language both fit in 8 KB" | **no.** With the language in, the machine is 800 B over; only dropping paging closes it | P32 |
| 30 | "your program is 232 B" | **1008 B / 36 words** without paging — the 232 was what paging cost, not what the chip has | P35 |
| 31 | "paging unlocks program size" | it unlocks **data and source**; resident *definitions* stay bounded because the token fetch is in C | P35 |
| 32 | "transparency in Forth is cheap because it's just words" | **888 B of dictionary** — 88 % of the 1008 B app space. Explicit `F@`/`F!` costs 202 | P34 |
| 33 | "the block layer will be the expensive one" | **456 B**, versus 888 for transparency — 432 B cheaper, and it links with 785 B spare | P33 |
| 34 | "overlays give unlimited app size" | mechanism works, **loader costs 1 400 B** against 620 B of app space. Overlays out of v1 | P36 |
| 35 | "app space is 1 008 B" | **620 B** — P35 never charged the 900 B block layer | P36 |
| 36 | "the block wrapper hangs because the harness can't service a spin" | **three Forth bugs**: `,` where `W,` belongs (16-bit branch operands), and two stack-order slips. The harness was innocent | P37 |
| 37 | "the branch target is 8a+4b+2c+d" | **8d+4c+2b+a** — the branch consumes TOS, the last argument. The test was right, the model was wrong | P38 |
| 38 | "nothing of ours runs on the chip" | **it runs**: `2 3 + 4 * .` → 20, wake_count 0→60, no trap. Engine 4 314 B | P39 |
| 39 | "the prelude can be compiled at boot" | needs **14 874 B** — 4 336 of it a duplicate dispatch switch from inlining, the rest the source in `.rodata` | P39 |
| 40 | "we have an interpreter, so we have a REPL" | we had a **one-shot evaluator**; the REPL needed a ring pump, an echo and a prompt — now built and typed at on the chip | J-60 |
| 41 | "the resident checksum covers the dictionary" (and docs/25's guess that an adopt rewrites its own headers above the seal) | the range included the launcher's **live** cells; `SEL` moved it by one byte and refused a good image. The tail had never moved | `tests/adopt_sum.py`, §J-102 |
| 42 | "the program library's image checksum is the finished work" (my own claim, hours old) | the operator found `ERR_ULPCODE` from the second frame on: `.N` built digits with `48 +` into the raw `EMIT` path, `0x80`+ being the console's message codes | `tests/adopt_sum.py`, `tests/tui_cli.py`, lint R7 |
| 43 | "MS sleeps for its argument" | it returns the wake count: twenty `200 MS` in 0.05 s (F-125) | lint R9 |
| 44 | "a DTR/RTS pulse resets the board in ~50 ms" | on USB-Serial-JTAG it does nothing: HERE 794 stayed 794. Only esptool's hard reset worked (F-126) | `devio.Dev.pulse_reset` verifies |
| 45 | "the linter knows the machine's vocabulary" | it listed 8 words the machine does not have, incl. `MOD`; the chip answered `MOD?` for code the linter called clean | `tests/lint_vocab.py` |
| 46 | "`MS` cannot sleep — that needs the wake timer" (my claim this morning) | it needed `rdcycle` and 38 B, not the wake machinery: `100 MS` = +100 ms, slope x1.00 | `src/ulp_repl.c`, `tests/ms_clock.py` |
| 19 | P24 "6 pages / 6 faults per pass", P26 "3 pages / 0 faults" | **These were occupancy counts, not traces.** Re-traced: P24 is **7 pages / 13 faults per pass**, P26 is **2 pages / 0 faults**. P26's claim survives; P24's method did not | P25 |

---

## 4. Dead ends — do not repeat these

| Attempt | Why it failed | What to do instead |
| --- | --- | --- |
| `find /` to locate the toolchain | scanned the root filesystem, burned 4 minutes | paths are in `export.sh`; the toolchain is under `~/.espressif` |
| Flashing over `/dev/ttyACM0` when the app may crash | USB enumerates but never drains writes; no software reset helps | flash over `/dev/ttyACM1`; recover with `esptool -p /dev/ttyACM1 chip-id` |
| Writing `COCPU_CTRL` from the HP while the ULP may be running | hardware-level stall; needed a physical reset | stop the ULP by clearing `SLP_TIMER_EN`, wait for `wake_count` to stop |
| Resuming a page fault at any primitive | 32/83 positions produced wrong answers | checkpoint **after** the token fetch |
| Making pages smaller to save frame RAM | raises the page count a dispatch touches; 4 × 256 cannot boot | 4 × 512 = 2048 B is the floor |
| Compiler padding to merge token and operand pages | N stayed 3 — the third page is **data** | frames stay 2048 B; find the space elsewhere |
| Trusting "it linked" as proof of allocation | 728 B of arrays were dead-store-eliminated | check `nm -S` for every budget array |
| Sweeping before validating the baseline | P03e swept 0 positions on a broken fixture | assert the baseline digest first |
| Extending a probe's timebox to finish | produced 40-minute runs and one runaway | cut the question, not the clock |
| Buffering bulk console input | 86–96 % loss at any ring that fits | pace one line per prompt byte |

---

## 5. Where the numbers stand

| Quantity | Value | Source |
| --- | --- | --- |
| ULP RAM | 8176 B (7856 pool + 320 C stack) | P01, P22 |
| Engine (40 primitives, 32-bit refs, paging) | 3190 B | P20, P22 |
| Forth memory that links (`MEMSZ`) | 1188 B | P22 |
| Resident dictionary after headers move | 1104 B | P22 |
| Spare | **94 B** | P22 |
| Cost per word | 39.2 B with headers, ~28 B headerless | P02 |
| Core clock | 19.0 MHz ± 1.5 % | P05 |
| RTC slow clock | 154.9 kHz (1 tick = 6.46 µs) | P05 |
| Cycles per tick / wake entry | 122.6 / 81 | P05 |
| Period floor | 22 ticks (142 µs) | P06 |
| Wake interval | sleep + previous wake duration | P06 |
| Dispatch cost | 726 cycles (40 primitives, paged fetch) | P20 |
| Typing slice (k = 4) | 23.7 ticks / 153 µs | P20 |
| Page fetch | 22.35 ticks / 144 µs, 3.55 MB/s | P16 |
| Stack peak (both stacks) | 108 B | P13 |
| C stack worst case | 244 B (static 176 + 68 interrupt) | P21 |
| Console escape collisions | 0 in 86.1 KB | P10 |

---

## 6. Open questions

1. ~~**Does the doorbell work at all?**~~ **Answered (P23): yes** — 176 µs median, 200/200, with the main-core
   task blocked. P16 had driven an RTCIO pad and hung a digital GPIO interrupt off it.
2. ~~**How big is the OS layer, and does the hot set fit four frames?**~~ **Answered (P26): yes — 1024 B,
   22 definitions, 2 frames.** And ~~the page counts~~ **re-measured properly (P25): 2 pages, 0 faults per
   pass with a real access tracer.** P24's layer, re-traced, is 7 pages / 13 faults per pass. Page claims
   now require a tracer (rule added to `docs/probes/README.md`).
2b. ~~**Does the scheduler actually switch the machine?**~~ **Answered (P27): yes**, inside a colon word,
   sharing one mechanism with the fault path. **New problem:** it costs 420 B for three tasks and the budget
   has 94. *P28 recomputes the budget with R4 included.*
2c. **Is the *outer* interpreter resumable?** `tib/ti/tl/errf` are not saved, so `EVALUATE` across a wake
   boundary is still open. That is the REPL's own state, and R2 depends on it.
3. **Does the shipping engine fit?** P22 measured 3190 B *before* `vm_switch` (P27) and before the OS layer's
   C glue existed. The 232 B spare is all that is left for both. *P29 builds it.*
3b. **How long does the prelude take to interpret on the chip?** If it is tens of seconds, snapshots become
   mandatory for the "interpreter at boot" story.
4. **What does flash cost** — erase, program, sector rotation, snapshot restore, and does PSRAM survive deep
   sleep?
5. **What survives a crash**, and can a new image be loaded without reflashing?
6. **Does the real console link work** — P11: attach, 200 paced lines, unpaced paste, exclusion, dead-man.
7. ~~**Does the machine run at all?**~~ **Answered:** it runs and you can type at it (`2 3 + .` → `5 ok`,
   `: SQ DUP * ;` then `7 SQ .` → `49 ok`). E-046, E-047.

---

## 7. Evidence index

| Entry | Probe | Result dir |
| --- | --- | --- |
| E-001 … E-006 | board identity, IDF, memory ceiling, image sizes, address spaces, v5.5 cross-check | `probe/` |
| E-007 | P02 token width | `P02-token-width/` |
| E-008 | P04 console and slicing | `P04-console-and-slicing/` |
| E-009 | P05 instruction costs (partial) | `P05-clock/` |
| E-010 | P01 engine size | `P01-engine-size/` |
| E-011 | P05 clock closed | `P05-clock/` |
| E-012 | P03 fixture bug, 0 positions | `P03-paging-sim/` |
| E-013 | P10 REPL line discipline | `P10-repl-host/` |
| E-014 | P03b retry not idempotent | `P03b-retry-progress/` |
| E-015 | P06 wedge and recovery | `P06-wake/` |
| E-016 | P03c cause isolated | `P03c-checkpoint-trace/` |
| E-017 | recovery over UART0 | — |
| E-018 | P03d checkpoint fix verified | `P03d-checkpoint-fix/` |
| E-019 | P06 wake timing and cause | `P06-wake/` |
| E-020 | P03e three pages, livelock | `P03e-store-then-fault/` |
| E-021 | P12 engine at 32-bit | `P12-engine-32bit/` |
| E-022 | P13 stack depth | `P13-stack-depth/` |
| E-023 | P14 cycles per dispatch | `P14-cycles-per-token/` |
| E-024 | P03f frame layouts | `P03f-frames-4x256/` |
| E-025 | P19 operand co-location fails | `P19-operand-colocation/` |
| E-026 | P20 trim/native accessors | `P20-native-accessors/` |
| E-027 | P21 C stack bound | `P21-c-stack/` |
| E-028 | P22 machine links, 94 B spare | `P22-fits/` |
| E-029 | P16 page fetch 144 µs, two-in-flight corruption | `P16-page-fetch/` |
| E-030 | P23 doorbell: 176 µs, HP blocked | `P23-doorbell/` |
| E-031 | P24 OS layer 3044 B, idle loop thrashes | `P24-os-layer/` |

**J-28 · P23 — the doorbell works; P16 had been asking the wrong question.**
P16 could not get the doorbell to fire at all (0 ISR events in 200 attempts, both muxes). The cause was
mechanical, not timing: it drove an RTCIO GPIO pad and hung a **digital** GPIO interrupt off it. The
intended mechanism is `ulp_riscv_wakeup_main_processor()` → `RTC_CNTL_SW_CPU_INT` →
`RTC_CNTL_COCPU_INT_ST`, handled by `ulp_riscv_isr_register(fn, arg, ULP_RISCV_SW_INT)`.

| Path | fired | median | HP task |
| --- | --- | --- | --- |
| ISR → blocked task (semaphore) | **200/200** | **27.32 ticks / 176 µs** | blocked |
| light-sleep wake | 200/200 | 73.43 ticks / 474 µs | asleep |
| deep-sleep wake | 1/2 staged | not measurable (chip reboots) | asleep |
| polling (control) | 200/200 | 24.25 ticks / 157 µs | spinning |

Register evidence: `ena=0x00002200` (COCPU bit 13 + ULP_CP bit 9), and after every pass
`INT_ST=0x00000000 … swcpu_pending=0` — latches cleared, no leak, `hp_isr=200` for 200 requests.
*Changed:* R6 is satisfied **without a busy-waiting core**; the doorbell costs 20 µs over polling. The
documented `deep-sleep` promise stays unverified because the chip reboots.

**J-29 · P24 — the OS layer does not fit the working set.**
The layer was written for real in Forth against the shipped 40-primitive set and compiled: **80
definitions, 3824 B with headers, 3044 B headerless — 5.9 frames.** Per group: tasks 1380, events 908,
REPL 300, introspection 348, device 108. 10 definitions per 512 B frame, unevenly (3–15); the largest word
`POLL-EVENTS` is **320 B, 62 % of a frame**.

| Workload | pages | faults |
| --- | --- | --- |
| idle event loop | **6** | **6 every pass (864 µs) → thrash** |
| line calling three OS words | 8 | 8 (1152 µs) → thrash |
| compiling one definition | 3 | 3 once, then stable |

94 B of resident room holds no executable word; three 32 B task records are already 96 B.
*Changed:* R3 and R4 as written are **not met** by this layer. This is the §12 trigger the P24 brief named
in advance. Two candidate answers, both to be measured: a **minimal** layer sized to two frames, and a
**hot-set layout rule** that makes the idle path contiguous so one or two frames can be pinned.

**J-30 · Reflection after 29 probes: what the machine actually is.**
Nine measurements have now moved the design. The pattern is worth naming, because it will keep holding:
**every estimate I have made has been wrong in the direction of "there is more room than there is"** —
engine 2600 → 3818 → 3190, frames 1024 → 2048, spare 1750 → 440 → 94, page miss 0.99 ms → 144 µs (the one
place I was wrong pessimistically), OS layer "fits in a frame" → 5.9 frames. The single most valuable
probe was the one that was *supposed* to answer something else (P03e), and the single most valuable change
was the one I had ranked last (trimming the primitive set: −824 B engine).

Where that leaves the stated goal: **the machine fits and cannot grow.** 94 bytes of resident room, an
engine of 3190 B, 1188 B of Forth memory, and an OS layer that is three times the working set. The
interpreter exists as a design, not as firmware. What has to happen next is not more probing of the
envelope — it is choosing what the machine *is*: a minimal 8 KB Forth with three tasks that fits, or a
larger machine that gives up one of the requirements.

**J-31 · P26 — the OS layer fits after all, when written to the requirement instead of the spirit.**
P24's layer was 3044 B / 80 definitions and thrashed. Written instead to exactly what R3 and R4 say — three
tasks taking turns, one event ring, a REPL, `WORDS` and `.S` — it is **22 definitions, 1024 B headerless
(exactly 2 frames)**, and the idle loop settles at **0 faults per pass** after one cold pass (432 µs).
66 % of P24's layer was removed, and the drop table names every feature with what it cost to keep: task
states and wake-all (296 B), the free-slot scan (236 B), `TASKS` (128 B), the task pool (132 → 28),
`EMIT-EVENT`/`WAKE-MASK`/event kinds (~520 B), `POLL-EVENTS` (304 → 120), REPL prompt/error words (192),
`?` and `.` (84), device helpers (108).

Two things it also found. A bug in its own draft: `YIELD` returned the new slot, so `SLEEP-TICKS` leaked a
stack cell per iteration — compiled clean, corrupted the stack after 16 passes; now a guardrail. And a gap
that has been there all along: **`dsp`/`rsp`/`ip` are C statics, so the scheduler switches records but not
the machine.** R4 is bookkeeping until the resumable interpreter exists. That is §4.2's work, and it is
now the top of the list.

**J-32 · P25 died on the provider, not the probe — and left a real finding behind.**
The run ended with `model temporarily unavailable`, and the last thing it said before dying was that
**instruction fetches go through `resolve()`/frames, not `P()`, so they were not being traced**. That
matters: P24's 6-pages and P26's 3-pages were both measured with the same tracer. A page count that misses
instruction fetches is exactly the kind of number that flatters a design. Relaunched with that lead as step
one, and told to re-measure both layers before doing anything else — a wrong measurement is worse than a
missing one.

**J-33 · P25 — "pages touched" was never measured. It was computed, and it was wrong.**
The retry began with the lead its predecessor died on (instruction fetch goes through `resolve()`, not
`P()`), and found something larger: **neither P24 nor P26 used a tracer at all.** Both `measure.py`s counted
the distinct pages the named definitions *occupy* — `cf//512 … end//512` — and applied "more than 4 pages
means thrash" by hand. That is an occupancy estimate, and calling it a measurement was wrong.

P25 then did the thing worth copying: it built a **deliberately broken** tracer (hooking only `P()`) to size
the error on an identical workload, then the real one through `resolve()`/frames.

| Layer, idle loop | analytic (published) | broken tracer | real tracer |
| --- | --- | --- | --- |
| P24 order | 6 pages / 6 faults | 4 pages, 900 touches, 0/pass | **7 pages, 8 570 touches, 13 faults/pass** |
| P26 minimal | 3 pages / 0 faults | 2 pages, 200 touches, 0/pass | **2 pages, 2 510 touches, 0 faults/pass** |

The error is **3 pages and 13 faults per pass** — and it flips a verdict in the wrong direction for P24
(its number was conservative) while *improving* P26's (fewer pages than published). Two conclusions that
matter:

* **P26's "0 faults per pass" survives the real tracer.** The minimal layer genuinely warms up: 2 faults on
  the first pass, nothing after. That is the first performance claim in this project that has held up under
  a proper instrument.
* **90 % of the accesses are instruction fetch** (7 670 of 8 570), and 41 % of P26's land in the resident
  region — so the working set is "two code pages plus the resident core", exactly what four frames buys.

P25's own layout experiment failed its pass criteria (no configuration reached 0 faults on P24's reordered
idle loop) and that is now moot: P26's layer gets there without any layout rule or pinned frame.

**J-34 · P27 — the machine switches now, and R4 costs 420 bytes nobody budgeted.**
`PAUSE` works **inside a colon word**: the saved point is the post-fetch dispatch of the token *after*
`PAUSE`, inside the body, so the word finishes to the same answer on resume. Four predictions computed on the
host — never from VM output — all matched exactly: the three-task interleave (`A>B>C>A…`, counts 5/3/4, 15
switches), a mid-word suspend (676, image byte-identical), a `PAUSE` inside `DO` inside a word (10, 5
resumes), and a page fault injected at the same positions. **`PAUSE` and the fault path are one mechanism**
(`vm_switch`), which is the property that stops two sets of resume bugs from existing.

And the bill: a switch must save `ds[SD]` **by value** (64 B), `rs[SD]` (64 B — the `DO` frame lives there),
`sp`, `rsp`, `w`, `ip` = **136 B**, plus a record = **140 B per task**, **268 B at `SD=32`**. Three tasks are
**420 B**, not the 24 B of record fields P26's layer implied. With 94 B spare, **the machine as linked runs
one task.** R4 was free in the budget only because it had never been implemented.

**J-35 · P18 — pin events are level-ish, not queued, and that changes the event loop's contract.**
An edge during sleep leaves a latch that is still set at the next wake (13/13), a 30 ns pulse latches, and
**k edges during one sleep produce exactly one event for k up to 5 000**. The ceiling is one event per pin
per wake — 151 edges/s at a 1 s period, 151 000/s at 1 ms — and faster edges are **merged, not queued**.
Latency is uniform over one period (990 µs … 6 592 µs at 1 s), never more than one period. The latch reads
`0x00000000` after the ULP clears it.

So the ring needs **one bit per pin per wake**, and the honest requirement wording is "state changes are
detected at wake granularity; edges faster than one per period are merged", not "never lost".

**J-36 · P28 — R4 is payable, but only by giving up the token width we had just chosen.**
Each task takes 140 B out of the same pool, so `MEMSZ` shrinks as tasks are added. Built both images and
walked the same 78 definitions:

| tasks | `MEMSZ` | resident need | gap |
| --- | --- | --- | --- |
| 1, 32-bit | 1188 | 1104 | +84 |
| 2, 32-bit | 1048 | 1144 | **−96 fails** |
| 3, 32-bit | 908 | 1144 | **−236 fails** |
| **3, 16-bit** | **908** | **676** | **+232** |

So 32-bit tokens cannot buy multitasking at *any* task count, and 16-bit tokens pay for three tasks with
232 B left over. The 16-bit dictionary is 636 B resident (56 header + 496 prelude + 84 primitive headers);
bodies 728 → 424 B, code fields 312 → 156 B, directory unchanged.

**Decision: 16-bit code tokens, 32-bit data cells.** The two widths were only ever conflated by me. The price
is a 64 KB *code* ceiling — about 1 600 words against a 78-word prelude — and R5 is untouched because data was
always addressed in 32-bit cells. Nothing measured is spent: frames, stacks, C stack and rings all stay.

**J-37 · Reflection: the budget is now closed by measurement, and the largest risk moved.**
Nine levers were measured; only two of them did more than their estimate promised (trimming the primitive
set, −824 B of engine; 16-bit tokens, −468 B of dictionary), and the rest came in worse than hoped (engine,
frames, task state, glue). Every line of §4.3 now has a receipt, and the sum has 232 B of headroom.

The risk is no longer arithmetic. It is that **P22 measured an engine without `vm_switch` and without the OS
layer's C glue** — new code that must come out of those 232 B — and that **nothing of ours has yet run on the
ULP**. The next probe is therefore not another budget estimate; it is the shipping engine, built.

**J-38 · P30 — the code shape was not the problem, and the negative result is worth more than a win.**
Five builds of the same source. `noinline` on the paging helpers saved **0 bytes**. Putting all 62 primitive
bodies out of line made `vm_enter` collapse from **2380 to 668** — and made the engine **1186 bytes bigger**,
because the bodies themselves cost 2872: **3540 out of line against 2380 inlined**. The only structural win in
the whole exercise was dying libgcc — a 30 B hand copy replacing a 232 B `memcpy`, and a 4-word-unrolled zero
loop removing `memset`, together **−400 B**.

So the cost is **~57 bytes per primitive body, wherever it lives**. The lever is the *number* of primitives,
not their placement. And that exposed a discrepancy I should have caught when P29 reported it: **P20 measured a
40-primitive engine at 3162 B, and the shipping builds used 61.** That gap is ~1 200 B — most of what is
missing.

**J-39 · P31 stalled on the wrong tool, then was told to stop parsing and diff.**
The agent spent 30 turns writing regexes against the `PRIMS` macro — line continuations, escaped quotes, nested
parentheses — and failed repeatedly on its own parser. The fix was not a better regex: **both primitive sets
already exist as built artifacts**, so `nm` on P20's ELF and on P29's ELF, diffed, gives the added bodies
exactly, from the compiler rather than from source text. Steered to do that, with the instruction to write up
what it had rather than start another script.

The general lesson, now a rule in `docs/probes/README.md`: **derive facts from what the compiler emitted
(`nm`, `.su`, `.map`), not from parsing source text.** Every hard number in this project that has survived
scrutiny came from an artifact; most of the ones that did not were estimates dressed up as measurements.

**J-40 · P31 — 40 primitives confirmed; the machine is 296 B short, and the derived set is the wrong 40.**
The set was derived properly this time: a traced run recorded the header address of every name lookup while
the prelude and all five layer files loaded → 35 primitives, plus 5 the compiler emits as tokens and never
looks up (`EXIT`, `LIT`, `DOCOL`, `DOVAR`, `DOCON`) = **40**, exactly P20's number. With the libgcc fixes the
engine is **3412 B**, and the real link is **296 B short** (8152 vs 7856). The 3438 target was itself 322 B
optimistic: fixed lines measure 4740, so the true ceiling is 3116 — and 322 B of that is not explained by any
line in the budget.

Then the finding that matters more than the bytes: **deriving a primitive set from what the code currently
calls is circular.** It keeps only what today's programs use, so the result can run today's programs and
nothing else. The 40-set drops `I`, `J` and `UNLOOP` — a user cannot write `DO … LOOP`, though the prelude
defines it — and drops `GPIO!`, so nothing can drive a pin. It also drops `'`, `(`, `."` and `CONSTANT`.
Restoring those puts bytes back, so 3412 is the floor for a demo, not for a Forth.

That is the honest state: **the machine is 296 B short of the smallest version that isn't crippled, and 322 B
of the accounting is unexplained.** Before anything is given up, the discrepancy gets audited.

**J-41 · P32 — the 322 bytes were a bill, not slack; and with the language in, only dropping paging closes.**
`nm -S` accounts for every byte: **+420** task records (in a footnote, not the sum), **+196** startup and the
`main` skeleton (no row at all), **+128** line buffer (dropped from the sum), **+34** statics, **+6** counters,
against **−142** hooks (a *code* line counted among allocation lines) and **−320** C stack (a line that is not
in the image — `__stack_top` grows down *into* the last 320 B of the region). So §4.3's arithmetic was fine and
its conventions were wrong, which is a subtler and worse kind of wrong: it looked audited.

Corrected ceiling 3116 B (2796 with the stack honoured). Restoring the nine primitives a programmer needs costs
**504 B**, putting variant D at **3916** and the link **800 B over** (1120 with the stack). The gap is a
*language* gap.

Options priced: two tasks frees 140 (660 short), `mem` → 676 frees 232 (568 short), together still 428 short.
**Only dropping paging closes it**, and it closes it with 1666 B to spare — because the paging infrastructure is
2466 B of frames, table and fetch path for a feature that is invisible to every Forth word.

**J-42 · The state of the machine, honestly.**
An 8 KB Forth with three tasks, the console, the full language and 1 666 B spare fits today, if paging is
deferred. A paged machine does not fit at any task count with a language someone can program. That is the whole
of the budget phase, and it is a scope decision rather than an engineering one: paging can come back later
without changing a single primitive, because `@` and `!` do not know whether they are paging.

**J-43 · P35 — "908 B" was a paging artefact. The program is 1008 B, or 36 words.**
Raised `MEMSZ` until the link failed, rather than doing arithmetic. Non-paged, C stack not reserved: **2196
links, 2197 fails**. With the C stack honestly carved inside the pool: **1880**. After the 676 B prelude and the
512 B block buffer, that leaves the operator **1008 B / 36 headerless words** (692 B / 24 words in the
conservative case) — against the paged machine's 232 B. **4.3×**, and the missing byte is found:
`sections = 5651 + MEMSZ` versus `7748 + MEMSZ` for the paged build, so 2091 of the 2466 came back and 352 went
on the block layer.

`nm -S` confirms `frm`, `ptab` and `ptab_lru_reserve` are **gone** and `mem` equals the new `MEMSZ`. The probe
also declined to repeat P32's convention error: since the block buffer sits *inside* `mem[]`, it quoted
`MEMSZ − 676 − 512` rather than the flattering figure.

**J-44 · What paging actually unlocked, stated once.**
It never unlocked *program size* — the paged machine's 232 B was the worst number in the project precisely because
2 466 B of pool had been spent on frames no Forth word can address. What it unlocks, and what the block layer
keeps, is **data and source**: blocks in flash addressed as far addresses, screens of source `INCLUDE`d a page at
a time. **Resident definitions remain bounded**, because the interpreter fetches tokens from RTC RAM and no Forth
word can intercept that fetch. So the machine has a fixed amount of *code* and effectively unlimited *data and
source* — which is exactly the shape of a 1980s Forth, arrived at from measurement rather than nostalgia.

**J-45 · P34 — transparency is affordable in bytes and unaffordable in *share*.**
The shadowing idea works mechanically — a token is an xt, so a colon word compiled before the redefinition
keeps the primitive — but the price is **888 B of dictionary (636 headerless)**: 202 for the four shadows, 434
for the machinery behind them (`FAR-READ`, `FAR-SAVE`, `FAR-FAIL`, `FAR-ALLOT`). Against **1008 B of app
space**, that leaves 120 B for the program itself. Naming the two words `F@`/`F!` costs **202 B** and leaves 806.

The engine cost is modest and the link succeeds: **+244 B**, 3369 of 7856 used, buffer as its own 512 B array so
`mem` is untouched. So the machinery is fine; the *share* is not.

And the probe was honest about a half-result: the shadow **failed to install** (`ERR_UNNAMED`), so "user code
pages without knowing" was never demonstrated end to end. What *was* shown is the property the design depends
on: pre-existing words keep the raw primitive.

**J-46 · Decision: explicit block access, and what that means for the suite.**
With 1008 B of app space, transparency eats 88 % of the program to hide a page fault that costs 144 µs. The
machine gets `BLOCK`/`UPDATE`/`SAVE` (or `F@`/`F!`), which is the 1980s idiom and leaves ~800 B of code.

That puts the productivity suite in focus, and the number that governs it is **not** code — it is the display:
a 40×8 character screen is 320 B of screen memory and ~32 ms to refresh from the ULP over bit-banged GPIO, while
a 240×320 pixel framebuffer is 9 600 B and does not fit in the machine at all. The suite is a Psion-class device:
character display, block-backed documents, apps swapped through a 512 B code buffer.

**J-47 · P33 — the cheap shape links: 7071 of 7856, and the layer's Forth is 456 bytes.**
The visible block layer **links for real** where transparent paging was 800 B over: region need **7071 of 7856**,
**785 B spare** (465 with the C stack honoured). Engine cost is **+200 B** like-for-like, buffer 512 B inside
`mem[]` (a separate array would be unreachable by `C@`/`!`), and the Forth surface is **456 B** — **432 B
cheaper** than P34's transparent wrappers. Half the price for the same storage.

**J-48 · The app-space arithmetic, finally in one place.**
`MEMSZ` 2196 − block buffer 512 − prelude 676 = **1008 B**, minus the block words 456 = **552 B of application
code**, or **236 B** if the C stack is honestly reserved inside the pool. That is the number the productivity
suite has to be built against, and it is why overlays (P36) matter: 552 B holds one app, not three.

**J-49 · An open bug, stated as one.**
The block layer's *protocol* passes 4/4 on the host — right bytes out, writes back, named failures — but the
Forth wrappers `BLOCK` and `SAVE` **hang**. Two causes point opposite ways: the host harness has no concurrent
server, so a synchronous spin cannot progress between interpreter steps (and would be fine on the chip, where a
fetch is 144 µs inside a multi-millisecond wake); or the words compiled at that `HERE` have a branch/operand
bug. Until P37 separates them, "the block layer works" is a protocol claim, not a language claim — and the probe
said so itself rather than rounding it up.

**J-50 · Sprint defined: the Psion-class device (`08-psion.md`).**
The measurements have converged on a product, so it is now specified rather than implied: a 40 × 4 character LCD
on six GPIO, six keys, a resident shell and editor core, apps as overlays, documents as flash blocks, and a serial
console. Requirements are numbered **D1–D16** so they do not collide with the platform's R1–R8, and every one is
anchored to a measured figure: 4 096 B engine, 2 196 B Forth memory, **552 B of application code**, 144 µs per
block, 726-cycle dispatch, 142 µs minimum wake.

Two things about the spec are deliberate. First, the display choice is **forced by arithmetic, not taste** — a
240 × 320 framebuffer is 9 600 B against an 8 176 B RAM, and even a 128 × 64 mono buffer is half the pool, so the
character display is the only option that fits and the ancestors had one for the same reason. Second, the sprint
**does not promise three apps.** With 552 B, one app plus a shared editor core is the honest target, and overlays
are what would buy the rest — which is exactly why G0 (P36) gates the whole thing.

The gates are listed as G0–G8 with G0/G1 host-only and G2 the first chip work. Nothing in the sprint starts until
the two open bugs report, because both of them can delete an app from the plan and it is cheaper to know that
before building the shell.

**J-51 · Bring-up plan for the real panel: a 1602A is 16 × 2, not 40 × 4.**
The operator has a breadboard, a 1602A and the ESP32-S3, so the spec's display line gets a bring-up path it did
not have: `09-display-wiring.md`. Three things in it are worth repeating because each has cost someone a day: the
**contrast pot (V0) must be adjusted before any code** or the module looks dead; **RW goes to GND**, because with
RW high the 5 V HD44780 drives D4–D7 into 3.3 V ESP32 pins; and **line 2 starts at DDRAM 0x40**, so a naive
`row × 16 + col` address puts the second line in the middle of the first.

Power is fine from the devkit's 5 V pin — 2 mA of logic plus ~20 mA of backlight through a 220 Ω resistor, well
inside USB. The panel's VIH is 2.2 V, so 3.3 V logic drives a 5 V module safely, but only in the direction we need
it.

And a process point that contradicts the project's own "everything on the ULP" instinct: **prove the wiring with
the main core first.** A wiring fault and a driver bug are indistinguishable otherwise, and the ULP path has two
extra unknowns (GPIO primitives, the coprocessor memory map) that have nothing to do with whether the panel is
wired right.

**J-52 · P36 — overlays work, and the loader for them does not fit.**
The mechanism is proven: compile into the buffer, save to a block, clear, reload, execute — same answer — and the
reloaded copy calls resident words correctly. But the **loader, directory and its twelve inline error strings cost
1 400 B resident**, against a maximum `MEMSZ` of 2 196 and an app space of **620 B**. The dictionary ladder is
measured: 630 → 1 038 → 1 328 → 2 228 → **3 628**. A loader that does not fit cannot manage apps that do not fit.

Two corrections fell out. **App space is 620 B, not 1 008** — P35's number never charged the block layer, which is
**900 B** here (P33's 456 B was a different, smaller file). And **a gate call into an overlay cannot be a plain
`EXECUTE`**: if the segment's entry is a bare token list, its final `EXIT` pops a frame nobody pushed and `sp`
runs past the stack — which is why the stale-segment test aborted with a stack underflow instead of printing its
named error. Compiling each segment as a real colon definition fixes it; the budget does not.

**J-53 · The sprint de-scoped itself, honestly.**
The Psion device is now **one application at a time**: engine, prelude, one app, block words, display and keys.
No shell, no overlays. That is still a real product — a notes device that holds a note across a power cut with the
main cores asleep — but it is not a suite, and the journal should say so rather than carrying "three apps" in a
plan nobody checked.

The levers to buy a second app, with measured values: three tasks → one task **+280 B**; block layer from 900 B
toward 456 B **+444 B**; the `ERR_*` strings into a block **~100 B**. Together that is ~824 B, enough for a second
small app and still not a suite.

**J-54 · Display legs cancelled — both of them, by the operator.**
The breadboard 1602A leg and the follow-on "built-in display" leg are dropped. What they cost and what they
taught:

* The 1602A bring-up consumed a long stretch of the session and **never showed a character**. The driver was
  proven good — the console showed all six GPIOs configured as outputs, the init sequence sent, `hello world`
  written — so the fault was in the wiring on the bench, and without a multimeter every step was a guess. Two
  concrete errors were found and fixed along the way (a **470 µF capacitor in series with the backlight**, which
  blocks DC and is not a resistor; and a 4 kΩ contrast resistor, too weak). Contrast as a *resistor divider* and
  `RW` tied to `GND` are now written down in `09-display-wiring.md` for whoever tries next.
* The pivot to a board with a built-in panel would not have been easier: every such panel is a **240×240 or
  170×320 pixel controller over SPI**, needing a 115 KB framebuffer, an SPI master the ULP does not have, and
  ~1 s per bit-banged frame. It would have forced the main core to own the pixels — a real departure from R6 —
  and it was cancelled before it cost anything.
* **The lesson worth keeping:** the display was never the hard part of this project. The interpreter, the budget,
  the paging decision and its measurement were. Hardware bring-up without a meter burned the session; the software
  work is where the remaining risk actually is, and it is host-only and cheap.

**J-55 · What is live again.**
The machine, headless: engine, prelude, tasks, block store, console on UART0. **620 B of app space** (P36's
corrected figure), 4 096 B engine, 2 196 B Forth memory, blocks at 144 µs per 512 B, 726-cycle dispatch. Two
gates stand between that and a running Forth: **P37** (why the `BLOCK`/`SAVE` wrapper hangs — harness or a real
branch bug) and **G2** (port the engine to the ULP and boot to a prompt, which nothing has done yet).

**J-56 · P37 — the block layer's hang was three bugs in the Forth, and the harness was innocent.**
Cause H — "the fake server has no chance to run during a synchronous spin" — is **refuted**: `blk_xfer` calls
`pl_hw(6,…)`, which *is* the host's server, **before** its poll loop. The server was always serviced.

The real cause is a class of bug worth naming: **a 16-bit engine takes a 2-byte branch operand, and `,` is not
`W,`.** `boot16.fs`'s `IF`/`ELSE` emitted the branch token with `,` — which is `a4()` + a 4-byte write — so every
compiled `IF` read its target from a `0x0000` filler, and when the operand landed at 2 mod 4 the processor
executed that hole as `DOCOL` at address 0 and `rsp` climbed 2, 3, 4, … A stack trace that looks like runaway
recursion, from a comma in the wrong width.

Two more, smaller: `BLOCK`'s `0= IF DROP 0 BLKDRT ! EXIT THEN` dropped the **buffer address** instead of the
status (because `0=` works on TOS only), so `BLOCK` returned nothing and the caller's `!` popped an empty stack to
`sp = 255`; and `SAVE` lost its status the same way. Plus a placement bug that is now a rule: P33's host put the
512 B buffer at 1792 while the dictionary had reached 1842, so the fetch **overwrote definitions**.

What survives: the engine, the harness model, and the block *protocol* — the real wrapper completes 8/8 once the
Forth is right, and a Forth-level bounded wait reaches `ERR_NO_SERVER` instead of hanging.

**J-57 · P38 — the block layer passes five proofs, and one of them caught my own model.**
Fixed the four P37 bugs and proved them by execution against host-computed predictions. The instructive failure:
**(a) first run passed 12 of 16**, and the *model* was wrong — I had the leaf index as `8a+4b+2c+d` when Forth's
branch consumes TOS, i.e. the **last** argument, so it is `8d+4c+2b+a`. The test shape never changed and no
expected value was copied from a run; the model was corrected and then matched 16/16, and the flag order was
independently confirmed by the disassembly in (b). That is the difference between a test and a mirror.

(b) is the one I trust most: the branch operand is **2 bytes at `token+2`**, read back from the compiled body, with
every target landing on a token boundary. It also produced two reader guardrails — a body token *is* an xt
(`cf = rd16(xt)`), and a colon word's first token is `xt+2` — which is exactly the kind of thing that silently
produces wrong conclusions if you assume otherwise.

(c)–(e) close the block layer: `sp` delta zero on every path, named failures that send no request, a `SAVE` that
reports through the server's own copy, and an overlap assertion that fires by name when the dictionary grows into
the buffer (`ERR_BUFOVER: dict_here=3634 > block_buffer=3584`).

**J-58 · The machine is now ready for the only step that can still invalidate it.**
Everything measured so far comes from host builds, static accounting, or isolated probe images. **Not one line of
the Forth interpreter has executed on the ULP.** That is G2, and it is the next probe.

**J-59 · P39 — the machine exists. It printed 20.**
For the first time in this project, our own interpreter executed on the coprocessor: `2 3 + 4 * .` → **`20`** as
two bytes on UART0, `errf=0`, empty stack, no trap. `wake_count` went 0 → 60 in 400 ms at a 1 000-tick period,
so the timer path is real, and the allocation check shows `mem`/`tsk`/`vm_live`/`tib` present with **no** `frm`,
`ptab` or `blk` symbols — the paging machinery is genuinely gone.

The flashed image is **5 876 B of 7 856**, of which 1 280 is the baked prelude dictionary, leaving a **4 314 B
engine** — the new baseline, and 900 B larger than P33's estimate because the estimate never had the prelude's
dictionary in `.data`.

**And the first honest failure on silicon: compiling the prelude at boot needs 14 874 B.** 4 336 B of that is a
*second copy of the 62-body dispatch switch*, because `interpret()` is `static` and GCC inlined `run()`/`vm_enter()`
into `main()` while keeping the original in `interpret()`. That is a compiler accident, not a design limit — and
it is exactly the kind of thing that only shows up when you actually build the thing. The rest is the prelude's
source sitting in `.rodata` next to the dictionary it compiles into.

So the next question writes itself: **can the prelude be streamed from flash over the mailbox at boot**, so the
source is never resident? That is P40, and it is the difference between "R1 holds in spirit" and "R1 holds on the
chip".

**J-60 · A REPL you can type at, on the chip.**
P39 proved the interpreter *evaluates*; this proves it is **interactive**. The HP core became what R6 says it
should be — a dumb byte pump between UART0 and two RTC-memory rings — and everything else lives on the
coprocessor: the character intake, the echo, the prompt, the interpreter, the compiler.

```
ulp forth
 ok
2 3 + .        →  5 ok
: SQ DUP * ;   →   ok
7 SQ .         →  49 ok      ← defined at runtime, on the chip
BOGUS          →  BOGUS?
```

Image 6 120 B of 7 856. The prompt is emitted **by the ULP**, not by the host, so "the HP printed the banner"
can never be mistaken for "Forth ran" — that separation is the whole reason this transcript is evidence.

One thing surfaced and was fixed in the same pass: the first version printed both the engine's `BOGUS?` and the
REPL's own ` ?`, two reports for one error. A machine that says a thing twice teaches you to distrust both.

Not in this image yet: blocks (`BLOCK`/`SAVE`), and tasks. The REPL is the doorway; those are rooms.

**J-61 · Documentation audit — the docs caught up with the machine, and one requirement needed a caveat.**
Swept every document for claims that the last twenty probes falsified, and found four:

* **`06-repl.md` said "the code does not exist yet".** It does now: `probe/repl/` is a byte pump on the main core
  plus a REPL on the coprocessor, and it has been typed at. The document now carries the measured transcript, the
  fact that only passthrough + line discipline are implemented (no framed control frames, no `ulpctl`), and the
  two terminal rules that cost an hour: **do not clear `OPOST|ONLCR`** (the staircase) and **strip CRLF** (two
  prompts per line).
* **`07-status.md` said "nothing on the chip yet"**, in two places including its one-line summary. Replaced with
  the real state: a live REPL, 6 120 B image, 7 258 of 7 856 B of pool, 598 B spare.
* **`02-harness.md` presented `ulpctl` and the framed protocol as the plan** with no indication that half of it is
  built. Now the passthrough implementation is named, and the two terminal facts are attached to it, because they
  are constraints on any client — including the one that was designed before the machine ran.
* **`01-proposal.md` R1 was quietly overstated.** It says "no prebuilt dictionary". The shipping image *has* a
  baked prelude, because compiling it on-chip needs 14 874 B against 7 856. So the honest wording is: **R1 is met
  for user programs**, which are typed, compiled and executed on the chip; the *standard vocabulary* is baked, and
  streaming it from flash is the named follow-up. Ticking that box without the caveat would have been the kind of
  rounding this journal exists to prevent.

Also done: the probe register now lists P12–P39 with verdicts (it had stopped at P11), the README leads with a
working transcript instead of a plan, and `08-psion.md` keeps its cancellation banner while `09-display-wiring.md`
stays as hardware reference for whoever tries a panel later.

Nothing stale was found in `00-background.md` (platform facts, all measured), `03-prototype-review.md` (a review of
a specific prototype, with its own D7 correction already recorded) or `09-display-wiring.md`.

**J-62 · R5 was still describing a feature we had already rejected.**
The last drift the audit found was in the requirements themselves, not the prose: **R5 still said "any address is
readable and writable, pages back onto PSRAM and flash without the program knowing"**, and its acceptance group
was eight boxes about frames, fault retry, `ERR_HOT_SET` and `ERR_PAGE_FAULT_LOOP`. All of that was measured,
priced at **888 B of dictionary for the shadows alone plus machinery** (P34) and **1 400 B for an overlay loader**
(P36) — and dropped. The document was still asking for it.

Rewritten to what is actually built: `BLOCK`/`UPDATE`/`SAVE` over one 512 B buffer, with the requirement stating
plainly what scales (data and source) and what does not (resident definitions, because the token fetch is in C).
Five of its boxes are now ticked **with measured evidence** from P38 — stack discipline, status reporting, the
overlap assertion, the branch-operand proof — and the remaining three name exactly what is missing from the
shipping image (the block words are not in it yet; it has 598 B spare and needs 968).

The transparent-paging items are not deleted from history: they stay in the journal and in P03b–P03f/P19/P26, with
a note in the acceptance section saying they were real work whose numbers are the reason the feature is gone. That
is the rule this project keeps re-learning — **a requirement that has been measured out of existence must be
rewritten, not left standing as an aspiration.**

**J-63 · "We are not using the ESP32 cores" was true, unasserted, and therefore unprotected.**
The claim was correct — the interpreter, the echo and the prompt are all on the coprocessor — but the only
evidence was that `repl_main.c` does not `#include "uforth.c"`. That is a statement about intent, and this project
has already been burned twice by evidence of that shape: P32's budget was a **convention error**, P25's hot pages
were **occupancy**. Both looked fine.

So it is now an assertion (`probe/repl/tools/assert_ulp_only.py`, 6 checks) plus a counterfactual (P41). The
counterfactual is the one that convinces: flash a ULP that wakes and does nothing, keep the bridge byte-for-byte,
and the console answers **`b''`** — not an error, not an empty prompt, *nothing* — while `ulp woke 76 times` keeps
advancing. Restore the image and the same keystrokes produce `5 ok`.

Two lessons from building the checker, both about checkers:

* **The substring version was a liar.** The HP image contains `SWAP` and `OVER` legitimately (inside the embedded
  ULP blob it must carry) and `DUP` twice as a fragment of `ESP_ERR_MESH_DISCARD_DUPLICATE` and
  `MODE_RS485_HALF_DUPLEX`. Three hits on a correct image. The check now matches the 1280-byte dictionary payload
  byte for byte and requires every hit to be inside the blob.
* **It flagged its own comment.** The source check failed on the word "interpreter" inside a GUARDRAIL comment
  whose entire purpose was to say the interpreter is on the ULP. A checker that fires on the sentence explaining
  the invariant teaches you to delete the explanation; it now strips comments and matches identifiers.

And one build lesson worth keeping: the stub would not link because `--gc-sections` had dropped the unused ring
arrays, so the IDF map generator exported no `ulp_*` symbols. **A stub that does nothing still has to look like it
uses what it defines.**

**J-64 · We did not have the manual. Now we do, and it does not contain the number we need.**
Two answers, in the order they matter.

*Did we have the manual?* No. The cache held exactly one document: the ULP RISC-V **API guide** (118 KB HTML). Every
chip-level fact in this repo came from measurement or from IDF's register headers. That is now fixed: the TRM v1.8
is fetched through `tools/fetch.py` — 15 215 232 B, sha256 recorded, journaled — and its text extracted to
`cache/derived/`. 1 531 pages. `docs/10-references.md` records what each source is authoritative for, so the
question never needs asking again.

*Does it help us optimise?* Not where the cost actually is. §1.7 "Instruction Performance" is about the **Xtensa**
cores; §2.5.2.1 is about the **ULP-FSM**, a different machine. There is **no per-instruction timing for the ULP
RISC-V anywhere in 1 531 pages** — and our dispatch loop's 1 074 cycles per token, 90.9 % of it token fetch, stays
a `rdcycle` measurement (P05, P14). The manual also does not name a readable wake-cause register, so P06's
"reads 0 on every wake" remains a measured fact rather than something a document could have told us.

Which puts the optimisation question where it belongs: not in the manual, but in the **compiler and the
disassembly** — `.su`, `nm -S`, and `objdump` of a 4 818-byte image whose `main` is a single 2 956-byte function
because GCC inlined the entire dispatch loop. That last fact is now a documented invariant (E-048 check 4), and it
is also the biggest unexplored lever: inlining helps the compiler and hides the cost from us.

**J-65 · The ABI and ISA documents arrived, and the first thing they did was price our arithmetic.**
Three documents now cached with hashes and journal entries: the ESP32-S3 TRM (1 531 pages), the RISC-V unprivileged
ISA manual (238 pages, ratified 20191213) and the RISC-V ELF psABI 1.0 (56 pages). Plus the boundary that actually
binds us, taken from the ULP sub-build's `compile_commands.json` rather than from prose:
`-Os -march=rv32imc_zicsr_zifencei -mdiv`, ABI **ILP32 soft-float**.

The prize was not in the ISA manual. It was TRM **Table 2.6-1**, which we had never read:

| | cycles |
|---|---|
| `MUL` | **34** |
| `MULH`/`MULHU`/`MULHSU` | **66** |
| `DIV`/`DIVU`/`REM`/`REMU` | **34** |

Against P05's 122.6 cycles per wake, **one multiply is 28 % of a wake**. Against P14's 1 074 cycles per dispatch,
3.2 %. And a double-width multiply is 66 cycles — over half a wake — so it can never appear in an inner loop. This
is the first hard cost we have ever had for an arithmetic opcode on this core; until now every timing number in
this repo came from `rdcycle` or from counting instructions.

Two things were then checked rather than assumed, and both came out in our favour:

* `mul`, `div` and `rem` each compile to **one instruction, no stack frame** (`probe/isa/codegen.c`, built with the
  ULP's exact flags). The 34 cycles is the instruction, not a libgcc call hiding behind a `jal`.
* `ret` assembles to a 2-byte `c.jr`, so **RVC compressed encodings are live**. Hand-written assembly for the
  dispatch loop can buy code density as well as cycles — the ISA manual's chapter 16 is not academic here.

And one thing was checked that did *not* hold up: the dispatch loop has **no multiply at all**. All 59 index
scalings in `main` are `slli`, so there is no 34-cycle trap sitting in the hot path. The only multiplies and
divisions in the whole 6 120-byte image are 3 `mul`, 1 `div`, 1 `divu`, 2 `rem`, 1 `remu`, and they live in number
printing and parsing — the `.` and number reader — where a 68-cycle decimal digit extraction is irrelevant next to a
human typing.

Which leaves the real target, and it is not arithmetic at all: **`rd16(a)` is implemented as
`rd8(a) | rd8(a+1) << 8`.** Two byte loads, a shift and an or, for *every token fetched*, when token fetch is
already 90.9 % of the dispatch cycle. Since tokens are 16-bit and written through `wr16` at an address that only
ever advances by 2 from an even base, those addresses are **always even**, and RV32IMC has `lhu`. That is one
instruction where we currently spend four, on the single hottest path in the machine. It is the obvious next probe
— measure it with `rdcycle` before believing it, because "fewer instructions" and "fewer cycles" have disagreed
before (P14: fetch dominated by *nothing* we had guessed).

**J-66 · The findings register: sixty facts, each with its meaning attached.**
Wrote `docs/11-findings.md` because the knowledge had become findable only by remembering which probe to grep. It
itemises **60 findings** in eight groups — the envelope, time, arithmetic and the ISA, the machine's structure, the
console, the boundary between the cores, the dead ends, and the method lessons — and for each one states **what it
means**: the decision it drove, the thing it forbids, or the question it closes.

Two rules went into it, and both made it better than a summary would have been:

* **Every row names its pedigree** — measured on this board (probe), read in a named section of a cached source, or
  derived from a compiler artifact. Writing the register is what exposed that F-51's "+824 B for 32-bit references"
  was a number I could not source; it is gone. The unverified claim died in the writing, which is the point of
  writing things down.
* **Placeholders are not allowed**, even temporarily. The first draft carried `E-0xx` in four rows; the project's
  own fail-loud rule caught them on review, and resolving each one turned up two more corrections — the doorbell is
  E-030, not E-031, and P18's 151 edges/s is recorded in the probe result rather than in `EVIDENCE.md`, which the
  register now says out loud instead of quietly implying.

The register also records the three meta-findings that cost the most and generalise the furthest: **occupancy is not
access** (F-55), **a convention can masquerade as a measurement** (F-56), and **a checker you have learned to ignore
is worse than none** (F-57). Those are the ones worth re-reading before the next optimisation.

And it closes with six open questions, so the next session starts from a list rather than from memory — led by the
one this week's ISA work produced: `rd16` spends four instructions where `lhu` spends one, on the 90.9 % of the
dispatch cycle that is token fetch.

**J-67 · Asked what the unverified wins unlock, the answer was "multi-tasking, and it was never blocked".**
The question was whether the open items — halfword loads, RVC, verified divider latency — open anything we had ruled
out, specifically transparent load/store and multi-tasking. So I went and looked at the shipping image's symbols
instead of reasoning about the register.

`tsk` is **420 B of `.bss` that is already allocated**, inside the 7 258 B of pool we are already using. `vm_switch`
(102 B) and `vm_task_leave` (120 B) are **linked and called**. What `--gc-sections` deleted is `vm_task_init`
(72 B), `vm_next_ready` (54 B) and `vm_run_tasks` (80 B) — **206 B that would create and schedule a task**, removed
because nothing called them. Against 598 B spare, multi-tasking costs about **250 B** including a spawn primitive.
It fits.

So F-08 in the register was subtly wrong in the way this project keeps having to correct: it listed "3 tasks =
420 B" as a cost to budget for, when that money left the account some time ago. Counting it again is the same class
of mistake as P32's convention error and the F-56 rule — **a budget that double-counts is not a budget**.

The rest of the question answered itself in the negative, and cleanly:

* **Transparent load/store stays dead**, and the reason is not size but *kind*. Its cost is **888 B of dictionary**
  (P34). The wins on the table are **code**: the `lhu` variant measured **−12 B** of `.text`, not the large win I
  had been gesturing at. You cannot pay a dictionary debt with code savings.
* **Blocks stay dead** for the same arithmetic: 456 B of words must live in `MEMSZ` (144 B free), plus a 512 B
  buffer; 968 B against 598 B spare, and 12 B does not change the ratio.
* **And the paging path has a second price tag I had never measured:** `vm_enter` — the retry/fault state machine
  behind transparent access — is **2 520 B of C**, entirely absent from the image. P34 killed the feature from the
  Forth side; this prices it from the C side. Two independent numbers, same verdict.

Two things I had to correct about my own last session, both worth keeping:

* **"`lhu` is the single biggest lever" was overstated by exactly the measurement that tested it.** `rd16` is not
  inlined; it is a 42 B function with 11 call sites, and `NEXT` spends 480 cycles on ~20 instructions — **~24 cycles
  per instruction**, which says RTC RAM latency dominates, not instruction count. Removing one load might buy a few
  percent or almost nothing. P42 measures it; the prose no longer promises.
* **A new tool came out of it.** `-fkeep-static-functions` makes the linker's deletions materialise and hands back a
  per-function price list — `vm_enter` 2 520, `drain_cmd` 302, `interpret` 252, `mkhdr_pad` 204, `number` 176,
  `run_line` 154. Every future "can we afford X?" now has a first-pass answer in one flag instead of a probe.

**J-68 · P42 failed, and the failure was the benchmark, not the machine.**
The question was clean: token fetch is 90.9 % of a dispatch, `rd16` does two byte loads where one `lhu` would do, so
does the fetch get faster? The size half I already had: **−12 B**. The cycle half produced nothing usable, because
I built the benchmark inside the thing being benchmarked.

Three separate defects, each caught by the previous one failing:

* **`BEGIN…UNTIL` typed at the interpreter do nothing.** They are compile-only. `3 BEGIN 1- DUP 0 = UNTIL DROP .`
  printed `3`, so the "1 000-iteration" workload ran once and reported 141 684 cycles as if it had run a thousand
  times. A benchmark that silently measures a single pass is worse than no benchmark: it produces a number.
* **A 0/1 flag read as 4.** `errf` is a `u8` set only to 1; the bench reported `err=4` and `min=567 cycles` for 100
  repetitions of a 54-token line — six cycles per repetition, which no plausible interpreter does.
* **The machine stopped answering.** Afterwards, typed lines echoed and produced no `ok`; replies arrived late and
  batched. The bench called `interpret()` from *inside* `drain_cmd()`, 100 times per line, and `interpret()` owns
  `tib`/`ti`/`tl`/`errf` and does `ti = tl` on error — so the diagnostic re-entered the parser in the middle of a
  drain and left the ring and the parser disagreeing.

So the probe is **INVALID**, not negative: no cycle comparison between the two images exists, and `lhu` remains
unmeasured. What it did produce is worth keeping — the exact method that must be used next time (time from `main()`
before the first drain; assert `ti == tl` and `errf == 0` after one iteration *before* looping; count tokens with a
bench-only counter; two line lengths so the per-call overhead cancels and the slope is cycles per token), written
into `docs/probes/P42-lhu-fetch.md` so the next attempt cannot repeat it.

The one rule this adds to the method list: **never place the instrumentation inside the path being measured.** The
first version's own GUARDRAIL said "keep the bench outside the dispatch loop" — and then I put it inside the input
path, which is the same mistake one level up. The bench is now gated behind `-DP42_BENCH` and the shipping image is
restored and verified (`2 3 + .` → `5 ok`, `7 SQ .` → `49 ok`, `BENCH` → `BENCH?`), 6 108 B, pool 7 258 B unchanged.

**J-69 · P42 on the second attempt: 35 % of the dispatch, for six bytes, and three harness bugs on the way.**
Attempt 1 measured nothing. Attempt 2 measured something large and adopted it.

| `rd16` variant | 81 dispatches | 161 dispatches | cycles/dispatch |
|---|---|---|---|
| `rd8(a)` + `rd8(a+1)` | 193 928 | 334 548 | **1 757.75** |
| one `lhu` | 122 804 | 213 944 | **1 139.25** |

**−618.5 cycles per token, −35.2 %**, bit-identical across reboots, `err = 0` in both, identical dispatch counts.
Cost: **+6 B** of pool (7 258 -> 7 264), 592 B still spare. Verified on the board after adoption: `2 3 + .` -> `5 ok`,
`: SQ DUP * ;` then `7 SQ .` -> `49 ok`, `: CUBE DUP DUP * * ;` then `3 CUBE .` -> `27 ok`, `BOGUS` -> `BOGUS?`,
`21 D2 .` -> `42 ok`.

**Why it was worth so much.** 1 758 cycles for a two-byte token is ~24 cycles per instruction (F-64), and the old
`rd16` made **two `rd8()` calls** — each a `jal`, prologue, bounds check, load and `ret`, with no cache to hide any
of it. Deleting one call deleted ~600 cycles. The generalisation is the useful part: **on this core, removing a call
beats removing an instruction by an order of magnitude.**

Which demolishes my own paragraph from a day earlier. In `12-what-opens-up.md` I had just written that `lhu` was
"overstated by exactly the measurement that tested it" and worth maybe a few percent — an inference from the
12-byte code delta. It was wrong in the opposite direction: bytes and cycles decoupled completely. The correction
is in the document, credited to the measurement that produced it.

**Three harness defects, each caught by the previous one failing.** `BEGIN`/`UNTIL` are compile-only, so the first
workload ran once and "measured" 141 684 cycles for a thousand iterations. The second used primitives
(`1 DUP + DROP`), which `interpret()` calls straight through C — **no token is ever fetched**, so it timed
dictionary lookup. The third called `interpret()` from inside `drain_cmd()` and left the machine echoing without
answering. Behind all three: printing numbers through the engine's own `.` pulled a **second 2 586-byte copy of the
interpreter** into the image, taking it to 8 010 B against a 7 856 B pool — the bench was trampling its own C stack,
which is where `min=567 err=4` came from.

What made attempt 2 work was not cleverness, it was the rules written down after attempt 1: run once from `main()`
before the drain exists; use colon words so tokens are actually fetched; count dispatches in `vm_enter()`; validate
`errf/sp/rsp/ti == tl` before timing; two line lengths so overhead cancels; print in hex, never through the engine.

**Still open, named:** alignment is asserted by construction, not proven for every `rd16` call site (dictionary link
fields also use it). `-DALIGN_TRAP` exists to settle that in one run.

**J-70 · The fan-out failed completely, and five minutes of doing it myself found a 9x error in the docs.**
Six `delegate` researchers were launched in parallel, one per lever. **All six died with `Request timed out` on
their first exploratory step** — 66 to 90 bytes of output each, no `RESULT.md`, no measurements. Nothing was
learned from them, and the honest accounting is that the run cost time and produced zero.

Rather than retry the same shape, I built the measurement they were all blocked on: **`probe/lev/ulpmeasure.sh`**,
which compiles one candidate source and relinks it against the *prebuilt* IDF ULP core objects, then reports
text/rodata/data/bss/pool/spare. Three seconds per candidate, no CMake tree per candidate, no full `idf.py build`.
That single script is what the six agents each needed and none of them got to.

With it, the first real findings:

**App space is 144 B, not 620 B.** `V_HERE` at boot is **1 136 B**, decoded straight out of the baked `image.h`.
`MEMSZ` is 1 280. The 620 figure the docs have quoted for weeks assumed `MEMSZ` 2 196 — which needs an **8 180 B**
pool. It was never achievable. Every plan that said "620 B of app space" was planning against a machine that does
not exist.

**And 592 B of the pool was idle while app space was 144 B.** `image.h` declares `mem[MEMSZ]`, so `MEMSZ` sits in
`.data` and every byte above 1 136 costs exactly one pool byte — but nobody had raised it. Measured ladder: `MEMSZ`
1 872 puts the pool at **exactly 7 856** and app space at **736 B**, with no code change at all. 1 880 overflows by
8 B, and **the link still succeeds** — the guard has to be the size check, not the linker.

Then the rest, each measured on top: rings 224 B (`.bss` 1 152 → 928), `NTSK` 3→1 another 280 B **plus 78 B of
text** (4 508 → 4 430, because the round-robin search shrinks too). Combined at `MEMSZ` 2 452: **app space
144 → 1 316 B, pool exactly 7 856, spare 0.** A 9.1× increase with no requirement removed — only two idle task
records nobody could reach and two thirds of the console rings.

**The measurement lesson to keep.** My first `MEMSZ` sweep printed six identical rows, because the `sed` pattern
had six spaces where the source had five. A sweep whose rows never move is not evidence; it is a broken edit. The
loop now echoes the effective value it measured, and that rule belongs with the others: **verify the input changed
before believing the output.**

Also worth recording about delegation: the tasks were well-scoped, isolated and forbid the board, and that was not
the problem — the platform timed out. What recovered the work was giving *one* primitive (a 3-second measurement
path) to *me*, rather than six agents the same under-specified instruction to go rebuild CMake trees.

**J-71 · Applied: app space 144 -> 912 B, verified on the chip, and two more corrections found by doing it.**
`MEMSZ` 1 280 -> 1 872 first (free, no code change): pool exactly 7 856, app space 736 B. On the board `HERE .`
printed **1 136**, which independently confirms the `V_HERE` value decoded from `image.h`, and it climbed to 1 150
after `: SQ DUP * ;` — so the space is real. Then the rings 128/256 -> 64/128 for another 176 B of pool, and `MEMSZ`
up to 2 048: **pool 7 840 of 7 856, app space 912 B.** `2 3 + .` -> `5 ok`, `7 SQ .` -> `49 ok`, `BOGUS` ->
`BOGUS?`, `HERE .` -> 1 136, all re-verified after the second change.

Two corrections that only appeared because the change was actually made:

* **The pool ceiling moved when the rings shrank.** Pool = `MEMSZ` + 5 798 with the new rings, so the ceiling is
  2 058 and not the 2 064 the table implied — my first attempt at 2 064 landed **6 B over** and I flashed it before
  noticing. That is the same class of error as the `sed` that didn't match: a number carried forward from a
  measurement of a *different* build. The constant now carries its own derivation in a GUARDRAIL comment, because
  overflow is silent.
* **A fast burst queues; it does not corrupt.** Twenty definitions at 0.12 s intervals all landed and were echoed
  seconds later — the console drains 32 bytes per wake, so a burst is paced by design. My first read of that was
  "the machine is falling behind / interleaving output", which was my *reader* overlapping windows, not the machine.
  Paced input is exact, line for line. Still worth exposing `repl_out_drop` to the host: with a 128 B output ring, a
  truncated reply and a wrong answer look identical from outside.

Deliberately left on the table: `NTSK` 3->1 (another 358 B, app space ~1 270). It deletes concurrency slots, and the
brief is to keep all functionality. Reclaiming idle pool costs nothing; deleting a capability is a decision.

**J-72 · R4 is alive on the chip — and the bug that had been eating the console was a size constant in two files.**
Goal for this session was a victory, not another number. The victory is cooperative multi-tasking: `SPAWN TA SPAWN
TB` with `PAUSE` bodies prints **1324**, three tasks print **131242**, and the REPL answers normally before, between
and after. Pool 7 842 of 7 856, app space 354 B.

Getting there took five wrong turns, and four of them were the *same* wrong turn:

1. `SPAWN?` — the dictionary is **baked**, so a new primitive needs `image.h` regenerated on the host. Obvious in
   hindsight, invisible when the primitive is right there in the source and the machine says it does not exist.
2. `pl_halt(0)` on last task retire — written when tasks were the only driver. With a REPL above them it stops the
   ULP and the console goes silent. Now it returns to C with `cur = -1`.
3. Stepping tasks **inside `drain_cmd`** — the third time this project has put instrument/feature code inside the
   path it depends on (P42's bench, P43's task step). Re-entrancy produced replayed command bytes.
4. A 136 B `VM outer` local for saving the live machine — that is C stack on top of a 244 B worst case against a
   320 B reserve. Replaced with a loud precondition: refuse to run tasks when the prompt stack is not empty.
5. The refusal printed **once per wake**, hundreds of times, filling the log. Now it retires the pending task and
   says so once.

And then, after all of that, the console was *still* broken with R4 disabled — which is what forced the real
diagnosis: **the ring sizes live in two files**. When the ULP rings shrank to 64/128, `repl_main.c` kept 128/256, so
the host masked with 127 and wrote past `repl_cmd[]` straight into `repl_out[]`. Every symptom followed: `3 CUBE .H`,
`.HERE?`, replies several lines late. Matching the constants and adding a boot-time assert took 9 of 9 checks from
3 of 9 to green — and R4 then worked on the first try, because its corruption had been this all along.

**The lesson worth keeping:** a constant duplicated across two cores is not a constant, it is a coincidence waiting
to expire. It now has one owner (the ULP exports its sizes) and one check (the host refuses to start if they
disagree).

Two smaller ones: `--gc-sections` deleted the exported size symbols because nothing on the ULP read them, which broke
the *host* build with `'ulp_repl_cmd_bytes' undeclared` — same shape as P41's stub; and **`idf.py build` does not
report pool usage**, so a 7 902 B image built, flashed and ran fine. `ulpmeasure.sh` caught it; the build did not.

**J-73 · Parallel probes work at width 3. The two things they found were both refusals, and both saved a board run.**
The first fan-out (six children) died on its first step; that was **width, not capability** — six concurrent children
on 4 cores all hit the request timeout before running a command. Three-wide, with literal commands instead of "go
explore", completed cleanly and delivered all three deliverables.

What they delivered, and my audit of each:

* **`rd32` as a single `lw` costs bytes and would trap.** I re-measured it myself: text 5 014 → **5 038 (+24)**, pool
  7 842 → 7 866, i.e. **over budget**. And the trap is structural: `clit()` writes a literal as two `cw()` halves with
  no alignment step, so the value sits at `token+2` and can be **2 mod 4**; `lw` needs 4. The lane had walked the
  shipped `mem[]` and named eight real sites at `≡2`, including `HERE` — the first word you would type. It also
  established that header links are `wr16`/`rd16`, a **2**-alignment contract, with only 37 of 81 headers 4-aligned.
* **Blocks are 600–1 090 B out of reach.** `blk_place_ok` forces `MEMSZ` ≥ 2 114 once the 456 B of block words exist;
  pool is `MEMSZ + 6 342`, so that is **8 456 — 600 B over**. With a 200 B app-space floor, 800 B over; holding
  today's 354 B, 1 090 B over. The levers that remain either are already spent or delete R4.

The lesson I keep re-learning, now with a second instance: **the `rd16` win was deleting a call, not removing a
load.** I generalised it to `rd32` as "the same 35 % class of win", and it is the opposite sign — bigger, slower to
fetch, and fatally misaligned. Measuring a lever that *looks* identical to one that worked is not optional.

And the smaller one, about delegation: what made three-wide work was **removing the reasoning burden**. Every child
got literal commands, the exact replacement line, and a 3-second measurement script that already existed. The six
that failed were told to explore, in a repo with fourteen documents and a CMake tree.

Also worth recording for honesty: I asked one lane to check a premise of my own ("so how many bytes must be freed at
MEMSZ 2604") and it came back with **"2604 is not the value the arithmetic requires"** — the minimum for the stated
requirement is 2 314. A lane that corrects the question is worth more than one that answers it.

**J-74 · The C-primitive lever for blocks: 490 B of dictionary bought for 350 B of code, and blocks are still 432 short.**
Ran the probe properly instead of arguing. Three numbers, all measured.

The Forth layer is **530 B**, not the 456 B on record, and the split matters: **146 B of it is eight dictionary
entries** — five `CONSTANT`s and three `CREATE`d cells — that exist only so Forth can write `BLKERR @`. The other
384 B is code plus the error strings the layer prints.

Porting `BLOCK`/`UPDATE`/`SAVE` to C primitives removes exactly the thing that was expensive: dictionary entries.
Measured on object sections, the C build adds 350 B of text and 12 B of `.bss` where the Forth build adds 530 B of
dictionary. **Net ≈ 150 B saved.** Blocks would then land at **8 288 B — 432 over** the pool, against 922 over for
the Forth layer.

So the lever is real and it is not enough. And in measuring it I found the thing that had been missing from every
previous block estimate: **the plumbing**. `blk_xfer` (186 B), `blk_sum` (56 B) and the **mailbox, 216 B** — a
`u32[54]` sized for P04's full status block, of which the block protocol uses four words. That is ~500 B that the
"blocks cost 968 B" figure never included; the honest range is **1 300–1 500 B**.

The next lever is therefore not the words at all: **shrink the mailbox**. 216 B → 16 B returns ~200 B, which
together with the C port leaves blocks ~230 B short instead of 432 — and 230 B is a number that rings/`NTSK` could
plausibly reach without deleting R4.

Two process notes. First, the C port hit two build errors that both looked like linkage and were ordering: `say()`
declared below my helper, and `P33_BLOCK` pulling the host-only fake server (`srv[16][512]`) into the image — the
latter is properly `#ifdef HOST`-gated, so the .bss blow-up was the mailbox plus alignment, not 2 KB of lie.
Second: `ulpmeasure.sh` links, and a link fails when the image is over the *hardware* region — so for over-budget
candidates the measurement has to come from object sections instead. That distinction (my 7 856 convention vs the
8 192 region) is worth remembering before "it won't build" is read as "it won't fit".

**J-75 · P45 failed. The bench was wrong four times, and the one number it produced is not a measurement.**
Asked whether hand-written RISC-V assembly is a lever, I started from the disassembly: `vm_enter` opens with
`addi sp,sp,-64` and ten `sw` of s0–s10, and closes with ten `lw` and a `ret`. That is **24 of ~47 instructions per
dispatch** — roughly half the 1 139-cycle dispatch, spent spilling ten callee-saved registers so a ten-instruction
case body can run. On paper, a leaf dispatch loop with a private register convention is the biggest remaining cycle
lever.

So the hypothesis was worth testing, and the test failed four ways:

1. a workload line longer than `TIBSZ`, which overwrote the ring indices and reported a million cycles for 21 tokens;
2. a line that underflowed the stack (`1 +`), which the validity check correctly refused;
3. the dispatch counter silently compiled out of the derived tree, so every "dispatches" field was 0 and the slope
   guard fired `err=4`;
4. a half-wired four-point design where the 8-group points returned 0 — and the two surviving points produced a
   *negative* per-dispatch cost, which is the arithmetic telling you the model is wrong.

P45 is therefore **INVALID**, not negative, and it stays that way in the record.

What it did surface is worth keeping, clearly labelled: **113 194 cycles for 5 parsed words** — over 20 000 cycles per
word *typed*, against 1 139 cycles for a body token. If that survives a correct measurement, the cost of interacting
with this machine is parse and `find()` (a linear scan of 81 headers), not dispatch — and hand-written assembly for
the dispatch loop would optimise the path that is already the fast one. That would be a genuinely useful answer,
which is why it is parked as a *preliminary observation* and not a finding.

The board is restored and healthy: R4 still prints `1324`, `2 3 + .` still gives `5 ok`, `HERE .` gives 1 202 after two
definitions, pool 7 842 of 7 856.

**The lesson, which is not about assembly:** four harness defects in one probe is not bad luck, it is a bench built
without a single passing end-to-end case first. P42 succeeded only after the harness validated one iteration
(`errf`, `sp`, `rsp`, `ti == tl`) *before* timing anything — and P45 inherited pieces of it without the discipline.
The next attempt must reuse the *validated* path and change exactly one thing: the workload string.

**J-76 · The disassembly answered the asm question by pointing somewhere else: the name lookup, 17x.**
The plan was: measure where a dispatch's cycles go, then hand-write the hot loop in assembly. The measurement said
the hot loop was never the problem.

P46 finally landed (the P45 harness was wrong four ways; this one reused P42's *validated* pattern and printed
`err = 0`). Its two-point model came back with a **negative** cost per dispatch — which is the arithmetic telling
you the model is wrong, because per-word cost is not uniform. The reason is the finding: **`find()` is called first
and fails for every literal**, and each of the 81 headers cost *two calls* (`rd16`, `rd8`) at ~240 cycles apiece.

| | before | after |
|---|---|---|
| parsed literal | **28 155** cycles | **1 623** (−17.3×) |
| line of `1 1 + 1 + …` | **48 344** per group | **10 305** (−4.7×) |

Two changes, both C, both a few lines: try `number()` first when the token starts with a digit, and read the header
link and length **directly** instead of through two function calls. That is the same lesson as `lhu` and as F-66 —
**the cost on this core is calls and dependent memory access, not instructions** — applied for the third time.

So the answer to "can we disassemble it all and hand-write the assembly" is: we can (census in
`probe/isa/ulp_main_shipping.dis`; `vm_enter` is 47 % of text), and it would buy ~1.8× on *compiled loop*
throughput — while the interactive path was 28 000 cycles per typed word, 25× the dispatch it feeds. **The
disassembly was worth doing; it just pointed at the parser, not the dispatcher.**

Cost of the win: `.text` +142, so `MEMSZ` 1 560 → 1 372. **App space 354 → 226 B**, pool exactly 7 856.

And the failure that nearly hid it: I flashed a **7 984 B** image (128 B over) because `idf.py build` does not report
pool usage (F-77). The ULP C stack overflowed into `.bss` and the machine presented *corrupted interpreter state* —
a bare `?`, definitions that vanished — which looks exactly like a logic bug in the change I had just made. I spent
a host rebuild proving the logic was fine before spotting the size. `probe/repl/flash_safe.sh` now measures and
refuses; its own first version double-counted the `dec` column and refused a legal image, which at least proved the
gate fires.

**J-77 · Memory victory declared: app space 144 B -> 558 B, with R4 intact and the pool at 7 852/7 856.**
The bar was set before starting: **app space >= 512 B, R4 intact, pool under 7 856.** Met.

The lever was the one that deletes nothing: `vm_switch` made **two libgcc `memcpy` calls** for its 136 B VM struct
copies and `vm_enter` a `memset` — 127 instructions, 7 % of text. The hand-written word copy was already in the
source behind a flag; enabling it cost **−356 B**, which `MEMSZ` turned straight into **+332 B of app space**.

And it exposed a latent bug that had been sitting in that code since P30. `vm_copy` unrolls four words per
iteration and counts down by four from `sizeof(VM)/4` — but `sizeof(VM)` is **136 bytes = 34 words**, so the final
iteration copies 4 words with only 2 left. **Eight bytes past the struct, into the adjacent task record.** Two tasks
worked fine (`1324`). Three tasks **hung the machine dead** — no output, and every subsequent line returned nothing,
which reads like the ULP dying. The fix is three lines and 20 bytes: whole words, then the tail. Verified: three
tasks print `131242` and the machine answers normally afterwards.

That is the second time this session that a size-driven change was broken in a way only a *third* participant could
reveal (the first was the ring-size mismatch, which only showed once more than one line was in flight). Worth
generalising: **when a change copies or shares state, test with N+1, not N+1's happy path.** Two tasks exercised the
copy; three exposed the overrun.

Session scoreboard, all measured and all on the board:

| | start | now |
|---|---|---|
| app space | 144 B | **558 B** (3.9×) |
| pool | 7 264 | 7 852 of 7 856 |
| cycle per dispatch | 1 757.75 | **1 139.25** (−35 %) |
| cycle per typed literal | ~28 000 | **1 623** (−17.3×) |
| requirements | REPL | REPL **+ R4** |

**What blocks would still cost, now:** app space 558 B + 4 B spare = 562 B available; the block layer needs 456 B of
dictionary + a 512 B buffer + ~500 B of plumbing (or ~40 B of dictionary as C primitives plus the same plumbing) —
roughly **850 B short**, and the only levers left delete R4 or the C-stack margin.

**J-78 · Documentation consolidation after the victory, and the one place a stale number was doing damage.**
The numbers moved four times today (app space 144 → 912 → 354 → 226 → 558), so I swept every doc that claims to
describe the *current* state: `README.md`, `docs/07-status.md`, `docs/01-proposal.md` §11a and the register's F-02 now
all state the measured build — image 6 888 B, pool 7 852/7 856, `MEMSZ` 1 704, `V_HERE` 1 146, **558 B of app
space**, C-stack reserve 340 B, R4 live, dispatch 1 139 cycles, typed literal 1 623.

The journals and `EVIDENCE.md` were **not** rewritten. They record what was true when it was measured, and a record
that tracks the present is not a record — it is a summary with a date on it.

One stale claim mattered more than the rest: R5's acceptance box still said blocks cost "456 B and the buffer 512 B,
and the current image has 598 B spare". Both halves were wrong — the Forth layer is **530 B**, the plumbing is
**~500 B** on top (E-059), and the spare is **4 B**. A reader would have concluded blocks were "nearly there" by
roughly 850 B. It now carries the real range, 1 300–1 500 B, and says plainly which levers remain and what they cost.

That is the same failure mode as the never-achievable "620 B of app space" (F-06): a cost figure copied forward
through several revisions without being re-derived. **The fix is cheap — measure the number again when the
surrounding budget changes — and the cost of not doing it is a plan built on sand.**

**J-79 · Merged the victories under a regression suite, then priced the assembly rewrite instead of starting it blind.**
Two jobs, in the right order.

**Merge.** The victories had no protection: the 58-test host suite targets `probe/uforth`, the *prototype*, so `lhu`,
number-first parsing, the inlined `find` reads, the hand VM copy and R4 were all unverified by anything that runs on a
keyboard. Added `probe/repl/tests/suite.fs` (26 assertions) plus a runner that builds the host binary **from
`src/uforth.c`** — the same source the ULP runs — and diffs against a golden file whose 22 values I checked by hand
(`5 4 42 6 15 -5 -2 123456 49 10 10 49 27 42 1 -1 0 0 7 0 1276 -1`). Green. Also caught that `src/line.fs` is P39's
demo line, which *prints 20*, so loading it would have poisoned the golden output for a reason unrelated to any
change.

**Price.** The instinct is "hand-write the hot loop". Two measurements say what that can and cannot buy. GCC is already
at the RVC floor — **2.82 bytes per instruction** across `vm_enter`'s 848 instructions — so assembly cannot win on
encoding. It can only win by *executing fewer instructions*, and the way is a **TOS pointer** instead of an index:
the C engine computes `ds[(sp-1)&(SD-1)]` with five instructions per operand access, where a register pointing at
the top cell makes it one `lw`. Prototyped and measured: **15.0 B per body by hand versus 29.5 B per body from GCC**
(64 bodies, 1 890 B). Projection **510–930 B** against a blocks gap of **~850 B** — so this is the first proposal
since transparent paging that could plausibly close it.

**And the risk is not the primitives.** The engine's switching design (P27) rests on the VM being *memory*: a switch
is a 136 B struct copy. A register-resident TOS pointer must be spilled into that record on every switch, so
`vm_switch`, `PAUSE` and the fault path all change — and the host suite cannot see any of it, because R4 only runs on
the board. That is the precise reason the suite had to come first, and why the rewrite needs a board run of the 2-
and 3-task cases before it can be trusted.

**J-80 · "Can we drop GCC and gain space?" — measured: no, and the reason sharpens what to do instead.**
Three checks, all cheap, all decisive. There is **no libgcc left** to remove (P47 took the last `memcpy`/`memset`).
Compiler flags are exhausted — `-Os` and `-Oz` both produce **5 550 B**, `-O2` produces **7 900**. And encoding is at
the floor: **2.82 bytes per instruction**, because GCC is already emitting compressed forms almost everywhere.

So the compiler's *presence* costs nothing. What costs bytes is a convention it cannot express — **a register holding
a pointer to TOS** instead of an index into `ds[]` — worth 29.5 → 15.0 B per primitive body. And that, usefully,
is confined: `vm_enter` is **2 392 B, exactly 50 % of the text**; the other 26 functions are the other 2 424 B and
they are logic — parsing, `find`, `number`, headers, errors, the REPL — where assembly would save ~10 % at best.

The sharper reason not to go all-assembly: **`image.h` is produced by compiling `uforth.c` on the PC and running it.**
The vocabulary is baked by the C engine. An all-assembly ULP would either lose its generator or need a second
implementation of the same dictionary layout — the exact class of duplication that produced the ring-size bug (F-74).

**Conclusion, recorded:** keep GCC for the 26 cold functions and for the generator; hand-write the **dispatch core
only**. That is the ~510–930 B lever, and it is the blocks gap.

**J-81 · Asked about dead code, built a coverage tracer — and found a menu, not a lever.**
The linker already does its job: `gc-sections` is on, and P47 removed the last libgcc helper, so nothing *unreferenced*
survives. The open question is what is **referenced but never executed**, which no linker can see.

`-DP49_COVER` records every primitive id the dispatch loop executes and every header `find()` matches, and prints the
names **read out of the headers themselves**. Result, for the prelude plus the 26-assertion suite: **34 of 65
primitives never dispatched** — `WAKE`, `MS`, the ADC and GPIO words, `TYPE`, `KEY`, `I`/`J`, `(DO)`/`(LOOP)`, `ROT`,
`OVER`, `AND`, `XOR`, the shifts, `!`, `'`, `CONSTANT`, `CREATE`, `,`.

Then priced them: a `P31_SUBSET` build is **text 2 314 B against 4 820** — so the non-essential primitives are worth
**~2 500 B**, which is the largest byte pool in the image and several times the 850 B blocks needs.

But it is **not a lever under the current brief**. Every one of those bytes is a word a program might call; deleting
them is deleting capability, and the goal says keep it. What it does is change the blocks conversation from "needs a
redesign" to "needs a decision": an 850 B gap sits comfortably inside a 2 500 B pool if a subset of primitives is
acceptable.

Two method lessons, both familiar shapes. The first version of the report was **wrong** — it paired a bit index with
a name list parsed from the `X()` macro files, and the list and the enum disagreed by two entries, so it announced
`DUP` as dead. Reading the name from the header makes that class of error impossible, and it is the same lesson as the
ring sizes (F-74): **one owner for every ordering, or the second copy will lie.** The second: a local variable named
`w` in my dump collided with the engine's `#define w (V->W)`, and GCC reported the error at the macro's definition
rather than at my line.

**J-82 · Started the asm dispatch core: groundwork done, and the estimate corrected before a line of asm was written.**
Two pieces of real work landed. `src/pids.h` now carries the primitive ids for the assembler, and `uforth.c` holds
**13 `_Static_assert`s** binding every id the asm will use to the real enum, plus the two layout facts it hard-codes
(`SD == 16`, `sizeof(VM) == 136`). Build clean, text unchanged, suite green.

Those asserts immediately earned their keep by catching **two mistakes of mine before any assembly existed**: I had
guessed the macro names (`P_PLUS` for what is actually `P_ADD`), and I had forgotten that the enum declares
`DOCOL/DOVAR/DOCON` *before* the X-macro list, so every id was off by three. Both became compile errors instead of a
jump table dispatching the wrong case — which is exactly the failure F-98 describes, made mechanical rather than
hopeful.

I also read the loop contract out of the source instead of assuming it, and it is worth writing down because the asm
must reproduce it exactly: `cf = rd16(mem + w)`; cases may push/pop or set `ip` (DOCOL does `RPUSH(ip); ip = w + 2`);
`if (!ip)` returns to C; otherwise `w = rd16(mem + ip); ip += 2`.

**And the projection moved, for an honest reason.** The 15.0 B/primitive prototype was measured with a pointer to TOS
that was *valid by fiat* — it omitted the 16-cell stack wrap. The real dispatcher must either mask per access (which
is what C already does, for no win) or tolerate one cell of overshoot and re-derive the pointer once per dispatch.
Realistic figure: **~18–22 B per body**, so the asm prize is **≈ 400–700 B**, not 510–930. Still the blocks lever,
but the low end of it — and I would rather correct the number now than after building 64 case bodies on it.

What is not done: the asm loop and the inline cases. Two reasons for stopping there in this session. The integration
needs the C switch extracted into a `vm_case(cf)` fallback. And **RISC-V assembly cannot be tested on the host** — the
only validation is a flash plus the typed suite plus the 2- and 3-task runs. Leaving half-integrated asm in the tree
at the end of a session is a worse outcome than leaving the groundwork.

**J-83 · Countdown metric created, and asm hit two structural blockers in its first five minutes.**
The metric first, because it changes how everything after it reads. `probe/repl/countdown.sh` prints one ledger, and
`tests/run.sh` runs it on every green suite, so victories are measured in bytes-toward-blocks rather than in
adjectives:

```
blocks countdown: 800 B to go  [pool 7852/7856]
  need: dict 40 + buffer 512 + block code 810 = 1362 B
  have: app 558 + pool spare 4 = 562 B
```

Its most useful output is not the 800 — it is the shape: the target `MEMSZ` (1 698) is *lower* than the current 1 704,
so **the entire gap is the block layer's code, not its dictionary.** Every text byte saved goes straight into "have".

Then the asm work, which produced two findings before any assembly was written:

1. **P31's subset gates bind the name to the body.** The same `P_HAVE_DUP` macro controls the dictionary entry in
   `p31_prims.inc` and the C case in `p31_cases.inc`. An asm body needs the first without the second, and the gate
   cannot express that. Workaround designed: register asm-handled primitives manually in `boot_init` (ids already
   assert-guarded) and let the subset gates drop their C bodies.
2. **Five case bodies assume the loop.** `p31_cases.inc` has 5 `continue;`/`return;` statements — EXIT and the
   DO/LOOP family — so the switch cannot be lifted into a `vm_case(cf)` fallback without editing a file the project
   deliberately keeps verbatim (P30/P31: hand-edited cases make variant diffs meaningless). So those primitives stay
   in C and asm takes only the bodies with clean control flow.

And one safety measure that only matters once bodies move out of the switch: `default: err();` in the dispatch. A
removed case with no default would fall through and keep executing with unchanged stacks — every symptom of that looks
like a Forth bug rather than a missing dispatcher entry. It is now loud.

**J-84 · First assembly for the dispatch core: 278 B for the loop plus four bodies, and a 719 B projection.**
Wrote `dispatch.S` with the one convention that matters — **a persistent pointer to TOS in `s2`** — and four inline
bodies (`DUP`, `DROP`, `+`, `0=`), falling back to the C switch for everything else. It compiles: **278 B**.

The interesting part is *where* the saving comes from, which I had wrong. I had been thinking of per-body wins
(29.5 → 23.2 B), but the bigger half is the **loop**: GCC's carries the bounds check, the checkpoint read, the jump
table and the `!ip` path in ~502 B, and the asm version does it in ~185 B. Adding the wrap check I had omitted from
the prototype (~4 B per push/pop) still leaves asm ahead, because C pays the mask *per operand access* while asm pays
it *per body*.

Projection: **719 B saved**, which covers **90 %** of the 800 B countdown. That is the upper end of the corrected
400–700 estimate, and it is the first number in this project that plausibly closes the blocks gap with the
requirements intact.

Two honest caveats before anyone celebrates. First, `1324`-class validation is impossible on the host — assembly runs
only on the chip — so the port has to be followed by a board session with the typed suite *and* the 2- and 3-task
runs. Second, 60 bodies remain, and the ones that call C helpers (`mkhdr`, `number`, `find`, `blk_xfer`) need a
store-state/call/reload sequence around them (~30 B each); the 23.2 B average will rise there. A realistic finish is
1 700–2 000 B, i.e. **400–700 B** saved rather than a flat 719 — which, with the mailbox shrink (~200 B), still
crosses zero.

**J-85 · Built the per-token asm dispatcher, measured it, and it loses — which is worth more than the code.**
Extended `dispatch.S` to seven bodies and gave it a callable entry so it could be integrated *without* touching the
loop: `p50_try(cf, &V, &mem)`, called before the C switch, returning 1 if it handled the token. The shape was chosen
deliberately — it is the low-risk integration, and it keeps the shipping source's semantics untouched apart from one
`if`.

Measured: **368 B** total, of which ~56 is prologue/epilogue and ~40 is the seven `li`+`beq` id comparisons. The seven
bodies are **272 B, 39 B each**. GCC's cost for the same seven primitives is **~84 B** — they are the simplest bodies
in the engine, 8–12 B apiece in the inline switch.

So the call-based shape is a **loss of ~188 B** before a single C case is removed. Not because the bodies are bad but
because a per-token call pays a frame, a compare chain and a `ret` for a two-instruction body.

This is the third time in this project that the *shape* of an integration, not the code in it, decided the outcome —
P42's bench inside the drain loop, P43's task step inside `drain_cmd`, and now this. The rule generalises: **the
instrument or the optimisation must live at the same level as the thing it replaces.**

Which settles the design: the asm must **replace `vm_enter`'s loop** — owning the fetch, the jump table, the
`!ip`/task-leave path and the fallback for the primitives it does not implement (including the five with
`continue`/`return`). That is the shape measured at 278 B for loop + 4 bodies, and the only one that can pay.

Second measurement worth keeping: the wrap-checked NOS sequence costs ~5 instructions per two-operand body, which is
what moves a body from the prototype's 15 B to ~23 B. The 719 B projection is therefore an upper bound.

**J-86 · The asm dispatch core is dead on measurement, and I had the economics wrong twice.**
Built the loop-replacement form exactly as designed — `p50_loop` owns the fetch, the id-range dispatch, the per-body
wrap re-derivation and the `w/ip` advance, while C keeps the switch for everything it does not handle. It works, it
compiles, and it is **490 B** for the loop plus seven bodies.

Then the arithmetic that matters, which I had been getting wrong: **the C loop cannot be removed**, because it is the
fallback. So a partial port pays for *two* dispatchers — 490 B of asm against the ~84 B of C cases it deletes, a
**406 B loss** — and the image overflowed 8 192 B outright with both present. That overflow was the measurement
announcing the problem before I computed it.

Corrected economics of `vm_enter` (2 392 B = C loop 502 + 64 bodies × 29.5):

* port 7 bodies → **+258 B loss**
* port all 64 → −920 B *if* the C side vanishes completely
* …but ~15 bodies call C helpers and need store/call/reload (~30 B each) → **−470 B**
* …and the 5 control-flow cases (`continue`/`return`) must stay in C → **−42 B**

**So the prize is 40–470 B, likely at the bottom, against a countdown of 800.** The asm path cannot deliver blocks.

This is the second downward correction this session — `rd32` promised the same 35 % as `rd16` and delivered a byte
*loss* plus a trap; asm promised 719 B and delivers tens. Both were caught by measuring the assembled whole instead of
summing optimistic parts. **A projection built from component estimates has to be validated against a real build
before anyone writes 60 bodies on it** — which is exactly what the per-token prototype and this loop bought us, for
about an hour instead of a week.

What remains credible for blocks: the plumbing is the cost, so attack the plumbing. `mailbox[54]` → 16 B saves ~200 B
of block-layer bss; 256 B blocks halve the buffer (256 B); together that is ~456 B of the 800. The rest has to come
from a small primitive subset (~220 B buys about five primitives by F-97) — which is a capability decision, not an
engineering one.

**J-87 · The countdown closes when the levers are combined — and asm turns out to be a supporting player.**
Made `countdown.sh` price combinations (`-m` mailbox, `-b` 256 B blocks, `-a` asm, `-r` rings, `-s` stack) and ran the
ladder:

| | countdown |
|---|---|
| today | 800 to go |
| mailbox 216 → 16 B | 600 |
| + 256 B blocks | 344 |
| + asm dispatcher (200 B) | 144 |
| + ring shrink (128 B) | 16 |
| + stack trim (60 B) | **FITS, 44 B spare** |

Two things worth saying plainly. First, **the gap closes with no word retired** — the cheapest two levers already
deliver 456 B of the 800, and neither costs a primitive. Second, **asm is not the decisive move it looked like**: 200
of 800 bytes, behind a rewrite that can only be validated on the board. Its earlier 719 B projection was wrong twice
over — once for the double dispatcher, once for assuming the C loop would vanish.

The capability price of the full ladder is: block size 256 B instead of 512 (2× the fetches at 144 µs each, still
per-command not per-token), line buffer 128 → 96 characters, output ring 128 → 64 bytes, and stack margin 336 → 276
against a measured floor of 244.

**J-88 · Built the experimental blocks tree with every lever behind a flag — it is 43 B over, and the lever that would close it is blocked.**
`probe/blocks/` exists with `EXP_BLK`, `EXP_RINGS`, `EXP_STACK`, `EXP_SUBSET` and `EXP_ASM` (off, per E-070), plus a
real HP byte server in `main/repl_main.c`. The shipping tree is untouched.

Two findings that only appear when you actually build it:

**The block buffer is unreachable from the host by symbol.** `mem` and `mailbox` are `static`, so the IDF map generator
never exports them — the ULP now publishes their *addresses* at first run and the host writes through a pointer. And
`(u32)&mem[0]` cannot be a static initialiser in the host build, which matters because the host build **is** the image
generator: a generator that does not compile means the vocabulary is never baked.

**`EXP_SUBSET` breaks the bake**: `p39_prelude.fs:25: error / IMMEDIATE?`. Without the flag the same tree bakes
cleanly at 1 180 bytes. Isolated to the prelude's line 25, and demonstrably *not* the eight retired names — none
appears in the prelude. Cause unknown.

Which leaves the arithmetic: the image is **43 B over** (7 943 against 7 900), and the −223 B subset is the lever that
would close it. `MEMSZ` cannot shrink: `V_HERE` 1 180 + the 256 B buffer puts the floor at 1 436 and the tree is at
1 442.

The positive: **blocks work on the host.** The fake server reports `SRV blk0[0]=00 blk0[9]=09 blk3[9]=1e`, so the
handshake, the checksum and the buffer copy are intact; only the board path is pending.

**J-89 · Blocks: two blockers cleared, one honest unknown left.**
Cleared the bake failure: **`DOCOL` is declared outside the X-macro list**, so my subset generator never emitted
`P_HAVE_DOCOL`, the `case P_DOCOL:` body was gated out, and every *call* of a colon word fell to `default: err()` —
presenting as `IMMEDIATE?` at prelude line 25, the first call rather than the definition. Third instance of the same
lesson (F-74, F-98, now this): **any second derivation of an ordering will eventually disagree with the first.**

Also cleared: the experimental build now **fits** — pool 7 903 of 7 916 with the 260 B stack reserve, `MEMSZ` 1 360,
`V_HERE` 1 104, 256 B of app space, 256 B blocks — and it boots on the board: `5 ok`, `HERE .` → 1 104, and R4's
"tasks need an empty stack" still speaks.

And the ring-size boot assert fired for real on hardware: `ULP cmd=32 out=64, host cmd=64 out=128`. It **refused to
run** rather than corrupting the console. That assert cost 20 lines and ten minutes when I wrote it; it just paid for
itself by preventing exactly the bug that cost me an hour earlier.

**The remaining unknown, stated plainly:** `BLOCK 0` errors as `0?` and `BLOCK 1` as `1?` — the error names the
*number* after `BLOCK`, while `UPDATE` and `SAVE` dispatch fine. `BLOCK` demonstrably runs (it emits `ERR_NO_SERVER` a
line later), so the token is mapped correctly; something about the token *after* it fails. I tried the obvious
suspect — the wait bound — and raising `BLKWAIT` from 2 ms to 100 ms changed nothing, which rules it out and is worth
recording as a ruled-out hypothesis rather than a hunch.

Next session: `: T 0 BLOCK . ; T` to separate interpret-mode parsing from the primitive itself.

**J-90 · Blocks on the chip: three board-only bugs fixed, one error path still unexplained.**
The experimental tree now fits and runs, and the byte server demonstrably answers a request. Getting there cost three
bugs that only exist on hardware:

* **`pdMS_TO_TICKS(2)` is zero at 100 Hz.** The console pump spun at priority 10 without yielding and starved
  `app_main`, so the server task was never created — and the only evidence was a timeout on the other core. One tick
  (10 ms) fixes it, and the server is now created *before* the pump, because ordering is part of correctness when a
  higher-priority task may never yield.
* **An ignored `xTaskCreate` return** turned "the task never started" into "the protocol is broken". It now reports
  success and free heap.
* **The ULP links at address 0**, so `&mem` and `&mailbox` are offsets into RTC slow memory, not pointers. Reading one
  directly produced `Guru Meditation … LoadProhibited … EXCVADDR 0x1e68` — the mailbox offset itself. Adding
  `SOC_RTC_DATA_LOW` fixed it.

With those, `blksrv: req #1 blk=0 op=0 sum=0` appears, so the handshake is live.

**What is left:** `0 BLOCK` prints `?` — an error with an *empty* name, i.e. `err()` ran with a zero-length PAD. The
same binary on the host prints `1104`, so the primitive and the server logic are right; the difference is on-chip and
it is **not** the wait bound (2 ms, 100 ms and 400 ms all behave identically, which rules that hypothesis out rather
than leaving it as a suspicion).

Two honest notes. I spent several round-trips on malformed test lines (`BLOCK 0` instead of `0 BLOCK`) — the Forth
stack order is `( n -- addr )`, and typing it backwards produces symptoms that look like dispatcher bugs. And the
empty-name `?` remains a real, unreduced anomaly; the next probe should print `rd8(PAD)` and `errf` at the moment of
failure rather than guessing from the transcript.

**J-91 · The probe rules now exist as a file, because the same lessons kept being paid for twice.**
Wrote `docs/14-probe-rules.md` — eleven rules, each quoting the failure that produced it and what it cost, plus a
pre-flight/during/after checklist. Linked from a new repo-root `AGENTS.md` in one line, so an agent starting cold hits
it before the first probe rather than after the fourth.

The rules are not advice, they are the session's bills:

* **R1** build the decisive artifact before the projection — `rd32` and the asm core each inverted under measurement.
* **R2** write the test line down and check the stack effect — `BLOCK 0` cost several board round-trips.
* **R3** check units — `pdMS_TO_TICKS(2)` is zero at 100 Hz and starved a task into non-existence.
* **R4** publish address *space* with addresses — the ULP links at 0, and dereferencing an offset panicked.
* **R5** kill silent failures at creation — an ignored `xTaskCreate` return, gc-deleted symbols, a non-constant
  initialiser.
* **R6** never derive an ordering twice — three bugs, all from a second copy.
* **R7** put the metric in place first — "620 B of app space" survived weeks because nothing measured it.
* **R8** say what the host cannot answer — asm is board-only, and the fake server hid a real fault.
* **R9** verify the harness — identical sweep rows, `min=567`, a negative cost per dispatch.
* **R10** never put the instrument inside the path it depends on — three times in one session.
* **R11** boot asserts earn their keep — the ring-size check fired on hardware exactly when it mattered.

The last paragraph is the one I most want the next session to read: **an invalid probe written down as INVALID with its
defects is worth more than a positive one that is guessed.** Twice here, a recorded negative stopped a week of work.

**J-92 · Blocks work on the chip. The bug was one integer, not the block layer.**
Four board-only defects, in the order they were found:

* **A flag in four places.** `P43_TASKS` inserts a primitive before the block entries, so it shifts every id.
  The bake ran without it, the ULP build with it, and the image's `BLOCK` (59) executed the ULP's `SPAWN` (59).
  `SPAWN` parses a name, found end-of-line, and printed an empty PAD — the bare `?` I had been treating as a
  block-layer mystery. `0 BLOCK 1 BLOCK` printed `1?` for the same reason: SPAWN parsed `1` and could not find a
  task. One owning header (`src/subset.h`) plus `_Static_assert(P_COUNT == ID_COUNT)` makes the drift a compile
  error; it immediately caught my own first guess at the ids.
* **The checksum needed `volatile` for exactly the reason the status did** — and the warning about the status was
  the line above the bug. GCC folded `mailbox[3]` to the `0` written for a READ, so zero blocks verified and real
  blocks failed CRC while the server's log showed both cores agreeing.
* **One buffer, many blocks, no error.** Write block 0, fetch block 1, save, read block 0 → 0. Silent data loss is
  the worst failure here because the program believes it wrote. Now `ERR_DIRTY` / `-7`.
* **A failed bake leaves the old `image.h`.** `line too long` for a 102-character *comment* stopped the bake, and
  the tree kept a dictionary from a different flag set. Check the bake's exit status.

Verified on the hardware, clean console: `0 BLOCK .` → 1272, write 65, `UPDATE`, `SAVE` → 0, read back 65,
`ERR_DIRTY -7`, read back 70, `: SQ DUP * ;` `7 SQ .` → 49, `2 3 + .` → 5. Pool **8 047 of 8 176**, 168 B of app
space, 8 × 256 B blocks.

The honest ledger: **this tree pays R4 to get R5.** Tasks cost ~496 B of text and the pool holds one or the other,
not both. `probe/repl` keeps R4 and its green suite; nothing from here has been copied back. And the lesson I keep
re-learning, now three times over: *a second copy of an ordering is a bug with a delivery date.*

**J-93 · NTSK 3→2: the dial cost less than projected and the failure message cost more.**
`tsk[]` holds one full VM snapshot per task (136 B) plus entry/state, so 3→2 returned **140 B of .bss** and,
contrary to my projection, only **12 B of .text** — I had argued the `% 3` → `% 2` change would be worth ~40 B
because `% 3` is a divide-by-constant. It is not, in this loop. Countdown 800 → 648.

The interesting part was the failure path. A full task table called `err()`, which prints the word in PAD —
the *name being spawned* — so a third `SPAWN` printed `TA?` and read exactly like an unknown word. That is the
same shape as the block bug (F-107), where a missing id presented as a bare `?`: **an error that borrows the
parser's buffer cannot say what actually failed.** It now prints `ERR_TASKS`, which cost 32 B back
(countdown 648 → 680, net 120 B for the change).

Two things the hardware taught me that the host could not:
* **A retired task frees its slot.** `SPAWN TC` after TA and TB finished succeeded — correct, but it means
  `NTSK` bounds *concurrent* tasks, not lifetime spawns, and the first board test I wrote could not prove the
  bound for that reason.
* A test harness that resets the board each run starts with an **empty dictionary**, so `TA?` was "unknown
  word", not a task-table failure. I burned a run learning that; the fix is to define the tasks in the same
  session as the spawns.

Coverage: `tests/ntsk.fs` asserts the abort and the exact message, run separately from `suite.fs` because a
deliberate error aborts a load and would swallow the rest of the assertions.

**J-94 · Two levers, and one of them was right for a different reason than the proposal.**
`-msave-restore` measured exactly what was predicted: **−224 B of `.text`** for a compiler flag, verified on the
board through `FIB` (deep recursion exercises every new libcall prologue) and through the task interleaving.
The other flags measured **zero**, which is worth knowing as much as the win.

The hash dictionary measured **82 B** the way I first tried it, and the proposal's 1 000–1 300 B looked wrong. It
wasn't wrong — *my version* was: I kept the 2-byte link and the 2-byte code field, so all I had removed was 3.5
characters of name per word. Taking the idea seriously means removing the link (fixed 4-byte stride) and folding
the xt and immediate flag into the same word: `hash20 | xt11 | imm1`. That is **324 B for 81 headers against
730 B**, and app space went **558 → 810 B**. Countdown **456 → 52 B**.

Alignment chose the design: a 4-byte key at a 2-mod-4 address traps on rv32 (F-78), so the header area starts on a
multiple of 4 and steps down by 4. The `xt` inside the entry points at the code field in the code area, which
means the dispatcher, the body offset and every `xt+2` in the tree are untouched — the change is all in `find`,
`mkhdr_pad` and the area's bookkeeping.

Two things this touched that I did not expect:

* **`IMMEDIATE` is Forth in the prelude** (`LATEST 2 + DUP C@ 128 OR SWAP C!`). It wrote into the middle of the
  new hash, and the failure appeared as `IF?` three lines later. A header shape has exactly one owner; the prelude
  is part of that owner.
* **The image had been baked at `MEMSZ 1900` while the ULP built at 1704.** Harmless for months because headers
  were chained from the bottom; fatal the moment `V_LATEST` became absolute. There is now a boot assert that
  halts with code `0x51` instead of presenting as "every word is unknown".

Also added, because a 20-bit hash has to be *checked* rather than trusted: a **bake-time collision scan** that
aborts the bake. A collision returns the wrong word silently, which is the one failure this machine cannot report.

**J-95 · The suite was green because it never went deep, and the bytes came from where the text was.**
Three agents ran in parallel copies. Two of their findings were bugs, and both were verified before I
believed them:

* **`SD 16` wrapped.** `15 FIB .` answers 610 at SD 256 and **377 at SD 16**, and a three-line file hangs the
  machine. The suite peaks at six cells, so it certified nothing about the stack — a test only vouches for the
  depths it reaches. Fixed by checking the push index and reporting `ERR_STACK` at the dispatch boundary:
  +22 B of text, no pool. `SD 32` (+394 B) is deferred; the *correct* behaviour is now loud rather than deep.
* **`rd16`'s bound test wrapped** (`a + 1u < MEMSZ` is true at `a = 0xFFFFFFFF`), so `-1 @` read `mem - 1`.

The third change was the one that paid: messages are now **one byte on the wire**, expanded by the host from
a table both cores share. `.rodata` 372 → 268, `strings` on the ULP image returns **0**, and the countdown
went from **52 B short to FITS with 29 B spare** — blocks and R4 in one image.

The validation I care about most: `tests/run.sh` pipes the engine through `tools/expand.c` and compares
against the *unchanged* `expected.txt`, so "the operator sees the same transcript" is a test, not a claim.

Agents' other numbers, for the record: computed goto −6 B (the table is conserved — `&&label` is also 4 B),
un-checking the accessors as proposed **+40 B** (only 13 body lines are safe, and GCC then outlines `PUSH`),
`UC_FOLD` −14 B (−22 B with cgoto, deferred by decision), `-Oz` identical to `-Os`, `-mrelax` 0,
`-fno-jump-tables` +88 net. Repo is now under git with a checkpoint commit.

**J-96 · Five bugs, zero caught by the suite, and 22 bytes of known-safe lever left unspent.**
The honest answers to "did we use everything safe" and "did we cover the holes" were *almost* and *no*.

Coverage: the suite exercised six stack cells out of sixteen, no wild address, no case variation, no deep
recursion and no error path — so it certified the features and none of the failures. There are now seven
checks, each named after the defect it would have caught, and each one fails if the fix is reverted. The
runner loops over `tests/*.fs`, so a new case cannot be forgotten, and error tests carry an `888 .` sentinel so
"the load aborted" is visible in a diff instead of being known to the script.

Levers: everything measured is either adopted or rejected with a number. The only safe bytes still on the
table are computed goto (−6) and the folded accessors (−22) — 22 B, skipped by decision, against 29 B of
spare pool. `-Oz` is byte-identical to `-Os`, `-mrelax` is a no-op here, and the rest of the flag surface
costs bytes rather than saving them.

What is still unproven is written down rather than implied: `ERR_DICT`, the `0x51` image assert, a
deliberately constructed hash collision, and the block layer's dirty/CRC paths.

**J-97 · Blocks and tasks in one image — four bugs, all of them "the other half" or "the other copy".**
The countdown said the two capabilities would fit, and they do: pool **7 853 of 7 856**, `MEMSZ` 1 200,
128 B blocks, `BLKADR` 1 072, and on the hardware a full round trip (`1072`, write, `SAVE 0`, read back 65,
`ERR_DIRTY -7`) *and* `1324`/`ERR_TASKS` from the task layer in the same session.

Getting there cost four defects and none of them was subtle in hindsight:

* the primitives were only half present — X entries without case bodies, which dispatches to `default: err()`
  and prints the word in PAD, indistinguishable from "unknown word";
* `BLKSZ` had a second owner on the host (256 vs the ULP's 128), so SAVE nacked with a plausible code and
  the overrun wrote into the ULP's `.bss` — the giveaway was a second boot banner mid-session;
* publishing the block addresses only in the first-run block is wrong because **RTC RAM survives a reset**:
  after a reflash the magic says "already ran", the size stays 0, and SAVE nacks over zero bytes;
* F-108 came back — this tree still read `mailbox[3]` non-volatile, so a READ's checksum was CSE'd to the
  zero we had written ourselves.

Two smaller ones worth keeping: `BLKWAIT 4096` is shorter than the host's 10 ms poll (the first request times
out and then everything is `ERR_BUSY`, by design), and a size initialisation inside `#if defined(BLK_DEBUG)`
means zero in the shipping build.

Limits, stated plainly: 128 B blocks, 154 B of app space, RAM-backed storage on the HP, **no flash and no
PSRAM**. The countdown script now recognises a block-enabled build instead of adding the layer twice.

**J-98 · The block tests are in the suite — and the mutation check showed one of them cannot fail.**
Nine checks now run, two of them block-specific, against a second host binary built with the shipping block
flags. Adding them was routine; verifying that they *bite* was not.

Reverting the volatile fix makes `blocks.fs` pass. GCC folds that load on rv32 at `-Os` and not on x86, so
the bug that cost a board session is invisible to every host test we can write. Rather than pretend
otherwise, the code was changed so the mistake cannot be made: `mb_get`/`mb_set` hold the `volatile` in one
place instead of at each of the six call sites. `deep.fs`, checked the same way, does catch its bug
(`55377888` instead of `55ERR_STACK `), so not all of the coverage is decorative — but one is, and the
record says which.

This is R12 with teeth: a test that cannot fail is decoration, and the only way to know the difference is to
reintroduce the bug and watch.

**J-99 · The benchmark exists, and the first thing it did was find a bug.**
Four workloads with exact, portable units: a checksum, the engine's own dispatch count, and the depth
ladder. No wall-clock, because the host is a different machine — cycles belong to the board.

Writing them in Forth taught me the dialect the hard way, and all of it is now written down: `BEGIN…UNTIL`
and `IF…THEN` are **compile-only**, so a loop typed at the prompt runs its body once and prints a *plausible
wrong number* (324901 instead of 832501 — the worst kind of failure, and one I only caught because I had
computed the answer by hand); there is no `R@`, no `ALLOT`, no `DO…LOOP`; `CONSTANT` takes its value from
the stack; and a buffer must be reserved by the word that pushes its base, because `HERE CONSTANT BUF`
points at the bytes the next definition will occupy — I "reserved" 64 B and then overwrote the loop that was
using it.

Then the suite found a real defect on its first outing: **a `CONSTANT` called from inside a colon definition
underflows the stack.** A colon word in the same position is fine. That is why the memory-bandwidth number
is not in the baseline — I marked the workload pending with its reproduction rather than measure a number
from a failing run. Six months of green tests never called a constant inside a loop.

**J-100 · I filed a defect that was my own mistake, and narrowing it down is what caught me.**
For an hour the record said "a CONSTANT called from inside a colon definition underflows the stack" — an
engine defect. Four experiments said otherwise: a DOCON works once, works in a loop, a DOCVAR works in a
loop, and `CREATE V 0 , 42 V ! V @` answers 42.

The bug was `HERE CONSTANT VB 0 ,`. `HERE` is read before the header exists, so the constant's value is the
address of **its own header** (590); `@` there returns header bytes (38 666 242) and `!` there corrupts the
dictionary. That produced exactly the symptoms I had attributed to the engine.

Three things worth keeping from this:

* **The benchmark did its job.** It found a real trap — just not the one I first named.
* **"Pending because of a bug" was too convenient.** The bug blocked one *formulation*, not the measurement,
  and the honest move was to narrow it instead of filing it and moving on.
* **A retraction is a first-class entry.** F-119 stays in the register with RETRACTED on it, because a
  findings file that only accumulates confirmed items is a file that lies about its own history.

`tests/semantics.fs` now pins the four storage rules and the trap, and the memory workload is in the
baseline at 862 dispatches.

**J-101 · The biggest gain was 200 B of array nobody indexed.**
Application space had been 154 B for the whole project. The audit took one command (`nm -S --size-sort`) and
found `static u32 mailbox[54]` — 216 B of `.bss` for a protocol that indexes four words, left over from
P04's status mailbox. `countdown.sh` had even modelled the fix as an optional `-m` scenario for weeks.

Sizing it from `BLK_MB` instead of a legacy 54, and moving the 200 B into `MEMSZ` (1 200 → 1 400) with a
re-bake, gives **354 B of application space — 2.3× — with no word, primitive or feature removed.**

Three things this taught:

* **Audit by symbol, not by belief.** I had been reasoning about `.bss` as "tasks 280, rings 96+64, vm_live
  136, mailbox 216..." for sessions without noticing that one of those numbers was pure waste.
* **The lever was already written down.** `countdown.sh -m`. A modelled lever that is not adopted is a
  decision that has quietly been made by forgetting.
* **Adopting a lever must retire its flag.** `-m` would now double-count 200 B, so it exits 2 with a named
  message instead of quietly reporting a bigger number — the same rule as the block layer being counted
  twice (P43).

Next candidate, feature-neutral and unbuilt: the 4-byte header (`hash20|xt11|imm1`) could become 3 B
(`hash13|xt10/2|imm1`) for **+85 B**, at the cost of two loads per lookup and a bake-time collision search.


**J-102 · The guard refused a dictionary that had not changed — and the doc's own hypothesis was wrong.**
The program library worked except for its last step: after one image had been adopted and returned, adopting a
second was refused with `img: REFUSED resident dictionary changed`. `docs/25` recorded it as open, with a
hypothesis — the checksum's tail `[sealed LATEST, top)` must be rewritten by the adopt itself — and a next step:
"have `#d` print both partial sums".

The next step was cheaper than that. `#m` already reads `mem[]` from the main core at zero ULP bytes, so a script
could snapshot the whole resident region, diff it, and compute every candidate sum off-line: no firmware change for
the diagnosis at all. What it said:

* the tail `[2032,2476)` was **byte-identical** through three adopts — the hypothesis was dead on arrival;
* `[52,1666)` — the resident code region — **also holds the launcher's live cells**, and pressing `k` writes `SEL`
  at 1180. Sum 36 585 → 36 586, one byte. That is the refusal, verbatim: `(sum 36586, built on 36585)`.

So the guard was firing on ordinary use, and it had been doing so since the menu gained a second entry. A guard that
fires on normal use is worse than no guard: it teaches the operator to click past the one time it is right.

The identity is now the **resident header table** only, `[V_SEAL, blk_off)`. Header entries are
`imm1 | xt11 | hash12`, so that region pins every resident name *and* the xt an image will call — which is the only
mismatch that makes an adopt execute garbage — and it does not move while the machine runs. One function, three
callers (`#d`, op 3, and the retired `#l`), because the old range had been spelled out at each site (R6).

What this session also caught, in the same sweep: the shipped `./cli.py --library` still used `2 OVL` to rewind (that
is `( blk -- )`; it *arms a block*), `--term`'s default word `RUN` does not exist in the launcher (`RUNP` does, so the
tool printed `RUN?` into an invisible screen), and `#c` compared an image's headers at `cs + cl` when they live at
`hs` — reporting "12 byte(s) differ" on a perfect image.

Verification is symmetric, because a guard nobody can trip is not a guard: three adopts in a row succeed (including a
different image), a `SEL` write changes nothing, and a descriptor field forged with `#p` is still refused by name
(`sum 55781, built on 55782`, nack 4 = `BK_CRC`).

Device tests are now one command — `probe/repl/tests/device.sh`, 47 checks under the board lock — because the reason
`2 OVL` survived in the shipped path was that each test carried its own copy of the build steps and the copy was
never the one that shipped. `tests/programs.py` now calls `cli.library()` itself.

**J-103 · `ERR_ULPCODE` was a digit, not a bug in the program library.**
The operator clicked the spinner and got flooded. Reproduced under a pty in one run, and the stream names the cause:
`\x1b[5;2H\x7f3 … \x7f9`, then `ERR_ULPCODE 0x80`, then `ERR_BUSY` at 0x8A, `ERR_UNNAMED` at 0x90, then `ERR_ULPCODE`
for every frame from 0x91 up. The frame counter had walked past 790 in four seconds and `.N` builds its digits as
`48 + EMIT` — and `EMIT` is the raw byte path, while `src/msg_codes.h` owns everything at or above `0x80`.

Three defects stacked, none of them the program library:

* **`.N` was a two-digit printer at best** (`DUP 10 < IF DIGIT ELSE 10 /MOD DIGIT DIGIT THEN` — 100 printed `:0`) and it
  fed `48 + quot` straight into `EMIT`, so from 897 the digits *were* message codes.
* **`KEY` returns `-1` for "no key"** and both demos compared it only with `113`, so "nothing" was a keystroke and the
  draw loop ran at ~267 frames/s instead of once per press.
* **`MS` does not sleep**: twenty `200 MS` measured at 0.05 s, because `L_P_MS` is `pl_hw(3, POP(), 0)` and `pl_hw` op 3
  returns the wake count. The pacing did nothing.

Fixed in `.fs`, as asked: `DIGIT` clamps (`15 AND 48 + EMIT`), `.N` proves its range (`100 /MOD DROP DUP 9 <`), both
demos wait with the resident `K0`, and the spinner is key-paced — one frame per press, silent when idle. **The engine
was not touched**: `MS` should sleep, but that is the wake timer and needs permission; F-125 records it as open.

The tests had certified this twice over. `read_until(b"SPIN")` returns the moment the title arrives, so it never saw the
second frame; and the linter had nothing to say about `EMIT`, `KEY` or `MS`.

So the linter grew three rules, each quoting its measurement: **R7 byte range** (an interval analysis that trusts only
literals and `AND`/`/MOD`, so `ESC 27` and `SENT 0` stay clean while `48 +` does not), **R8 key -1**, **R9 ms stub**.
The selftest now names the rule each fixture must trip instead of just "something fired" — it was quietly passing on
unrelated leaks before, which is how three demo bugs sat behind a green selftest.

And the linter's own vocabulary was wrong: it listed `MOD`, `/`, `>`, `@!`, `ALLOT`, `CR`, `SD`, `SPACE`, none of which
the machine has. It linted a launcher containing `100 MOD` as CLEAN while the chip answered `MOD?` at block 79. The table
is now checked **against the device** — `tests/lint_vocab.py`, 60/60 — and the duplicate dict keys that made it lie to
itself are gone.

One more, found while timing the operator's first complaint ("cli --library is really slow"): `pulse_reset` never reset
this board. HERE 794 → pulse → 794; only esptool's hard reset returned 786. USB-Serial-JTAG emulates DTR/RTS, so the
modem bits are not wired to EN. Two no-ops per connect, and a message that blamed the hardware. Now verified and fell
back: **21.7 s → 2.9 s**. While measuring it I also found a stale `cli.py` from my own crashed harness holding
`/dev/ttyACM1`, which `cli.connect` can now name instead of retrying for 36 s.

Device: 51/51 across five files (`tests/device.sh`). Host suite: exit 0.

**J-104 · `MS` sleeps now, for 38 bytes, and the first thing it exposed was my own off-by-one.**
Permission given, so the engine got a clock. `L_P_MS` popped its argument and returned the wake count; `pl_hw(3)` in
`src/ulp_repl.c` now busy-waits:

```c
#define CYC_PER_MS 19000u              /* P05 measured 19.0 MHz +/- 1.5 % on this board */
while (ms--) { t0 = cyc_now(); while ((cyc_now() - t0) < CYC_PER_MS) { } }
```

`rdcycle`, not the RTC timer: one instruction against a latch-and-read dance that would have eaten most of the 53 B of
pool headroom left. And a per-millisecond loop rather than `a * 19000`, which overflows u32 above 226 050 and would turn
a bad argument into a *quiet* short wait — the fail-safe this project bans.

Measured (`tests/ms_clock.py`, baseline subtracted): `0 MS` = 0 ms, `100 MS` = +100 ms, `300 MS` = +301 ms, slope
**x1.00**. Pool: 7 839 → **7 877** of 7 892 (gate refuses over).

So the spinner can spin again — `FRAME STEP 250 MS KEY …`, 3.7 frames/s, 158 B/s — and it is allowed to because the
bounded counter and the clamped `DIGIT` mean the worst case is a *fast* spinner, not message codes. That is defence in
the right place: the display cannot emit a code byte even if every layer above it misbehaves.

Two rules moved rather than being left alone:

* **R9 retired.** "MS does not sleep" was true and measured, and is now false. A rule that outlives its fact is
  folklore, so the check is gone, the fixture became an R8 case, and the reason is written in the docstring.
* **R8 narrowed.** "`KEY` never tested against -1" now also requires *no pacing*. The measured runaway needed both
  faults; a loop that waits 250 ms per pass and ignores -1 is ordinary terminal code, and firing on it would teach the
  operator to ignore R8.

Then the new digit assertions caught a bug I had just written: `.N` printed **`09` for 9**, because the single-digit test
was `DUP 9 <` — false at 9. Every device test had passed with it: they asserted that *a number* appeared, never *which*
number. `adopt_sum.py` now pins `0, 9, 42, 99, 100 → 0`. First run of that assertion produced five FALSE failures
because the transcript is `"9 ok"` and I compared against `"9 "` — which is its own lesson, applied in the same commit.

Device: 61 checks across six files. Host suite: exit 0. Linter: 7 rules, 8/8 selftest catches, all four examples clean.

**J-105 · "It just says Bar", "it counts to 10", "it stays red" — three .fs bugs and a test suite that read titles.**
The operator ran it and reported exactly what a test cannot: nothing was drawn. All three were in `.fs`:

* **Bars drew nothing.** `BAR` put every bar at `5 2 AT` and filled with **spaces** — eight invisible overwrites of one
  cell. Now each bar is its own row with `#` blocks, `(i+1)*4` wide, in colour `i+1`, 144 `#` in the frame.
* **The spinner was a progress bar.** It printed a counter and `P` stars, which counts to 10 and resets. Now it rotates
  `| / - \` via `4 /MOD` and two tiny glyph words, with the phase number beside it.
* **The red row stayed red.** `MARK` painted the selected row and never reset the colour, so every row ever selected
  stayed red for the rest of the session. `OFF` now starts every row, and `FOOT0`/`BARS` restore the default too.

Why the suite was green: **it asserted titles.** `read_until(b"SPIN")` stops at the title, and the bar test looked for
the word `BARS`. So the tests now read whole frames by their sentinel and count pixels — one red run per redraw (before
and after moving), 144 `#` and 8 colours for the bars, at least two glyphs for the spinner. Fixing that surfaced two
test bugs of my own: `dwell(0)` inspected zero bytes and "failed" on working code, and reading until a *title* leaves
the rest of the frame in the pipe, which showed as "0 red" then "2 red" for one red per frame. A frame terminator
belongs at the END of a frame; both demos had `SENT` right after the title.

**Then the slowness.** `./cli.py --library` was 11.3 s, and 9 of it was not the build:

* the "is the port held?" check sat *after* `pulse_reset`, so a stale `cli.py` from an earlier run cost ~9 s of resets
  before the message that named it — moved to the first line of `connect()`;
* `connect()` pulsed RTS (a no-op on USB-Serial-JTAG, F-126) and then fell back to esptool on every run — now it goes
  straight to the reset that works;
* `Dev.reset` slept a guessed `settle + 1.0 + 0.5` = 2.7 s after esptool. It now asks `HERE .` until the machine
  answers: the board decides, not a number. **connect 6.9 s → 2.3 s.**
* and `--library` fell into the REPL when the app exited, so a *live process* kept holding `/dev/ttyACM1` and the next
  run had to be refused. It now exits (`--repl` stays), and the test proves it by starting a second instance and getting
  `2 3 + .` → `5 ok`.

Plus `dev.cmd(settle=…)` so a `LOAD` - which answers with exactly one line - does not pay the 20 ms second-line window:
**build 4.8 s → 4.1 s, total 11.3 s → 6.6 s**, with per-block progress so the wait is visible. The remaining ~4 s is 34
blocks on a 19 MHz chip at one USB round trip each; that is the design's floor, not a bug.

**J-106 · The traceback after a good build: a cleanup step listening for a message nobody sends.**
The operator pasted a crash that happened *after* "library ready", on a working machine:

```
devio.Timeout: no reply to '!LINE' within 8.0s; got ''
```

`!LINE` is how the host takes the line discipline back, and it prints nothing - it just clears raw mode. What `dev.cmd`
had been matching all along was the ` ok` printed for the line that started the program, i.e. **unsolicited output that
survives only if the buffer was not already drained.** In a terminal, with the frame consumed and the ` ok` already
read, nothing was left to match, and the cleanup raised through `main` and printed a traceback over a half-restored
terminal.

Two fixes, both about the same rule - *wait only for what must arrive*:

* the cleanup writes `!LINE` without waiting, then proves the machine is back with `HERE .` (which must answer). It
  cannot raise: terminal restored first, then a named message and exit 3 if the board really is gone. No `return` in
  `finally` either - that would discard the exception that brought us there, which is the silent-failure shape this
  project bans.
* **Ctrl-C now actually ends the program.** It only ever stopped the proxy: the machine stayed inside the app's `KEY`
  loop, keystrokes stopped reaching the keybox, and the REPL became unreachable while the board looked dead. `term()`
  now sends the app's own quit key and requires the interpreter's ` ok` - up to three times, because a launcher nests
  (one `q` leaves the demo and the *menu* still waits - measured as "no ok" with one key). Stopping at the first ` ok`
  also avoids a stale `q` in the keybox quitting the next program on its first poll.

The test now *creates* the failing condition instead of being saved by a race: it drains the console to silence before
the final `q` ("the console goes quiet before exit: 0 B"), and it starts a second run, interrupts it mid-animation with
Ctrl-C, and requires a usable machine afterwards. Device: 69 checks across six files.

**J-107 · Chaining images as phases: 400 B of program in a 290 B window, and the fourth hop that stalls.**
The operator asked for the Forth way to break the app-space ceiling by chaining images, not for a scheduler. It is a
**tail call by variable**: a resident cell `NXT`, a one-token `CHAIN` (`NXT !`) as a phase's last act, and

    : SWITCH ( desc -- ) NXT ! BEGIN NXT @ WHILE NXT @ ADOPT 0 NXT ! EXECUTE REPEAT ;

`ADOPT` is `RW 3 BLKXFER DROP @` — the old one-shot SWITCH body, unchanged. The launcher hands SWITCH the first
descriptor; each phase names the next or says nothing (the dispatcher clears `NXT` before every `EXECUTE`, so forgetting
to chain *ends* the program instead of looping it). Shared state lives **below the seal** — the window is replaced on
every adopt, so a phase that leaves anything there loses it.

Measured on the device: the gauge is three images (100 + 112 + 188 = **400 B**) in a **290 B** window — **1.38×** — and
the chain adopts 60 → 62 → 64, draws all three panels and returns to the menu in **152 ms**. The price is exactly the
old lesson in new clothes: **the launcher and the phases compete for the same RAM**. Adding the chain machinery, a third
menu row and a shared counter took the launcher from 25 to 28 blocks and the window from 346 B to 237 B, which is why
the single-phase spinner no longer fit; it is now the gauge's third phase, and the menu is two entries.

Two bugs paid for on the way:
* **`fsplit` split `... ; 40` | `CONSTANT IMGP ...`.** A block is a *line*, and every line starts with an empty stack
  (`run_line()` does `sp = 0`), so a value can never cross a block boundary. The device said `block 87: ERR_STACK`
  and then five `NAME?` lines naming words that were fine. The splitter now keeps the token before `CONSTANT` with it,
  with a selftest case, and the general rule is written down: *a block must be stack-self-contained.*
* my own harness twice: `dev.cmd` returns on the `img:` marker (so "the chain returned" was really "the line printed
  one line"), and an isolation run reused a dirty dictionary, turning every case into `ERR_BUSY`.

**Still open, named:** a *fourth* hop stalls. With a 4th image chained after the 3rd, the machine adopted 60, 62, 64 and
then re-entered phase 3's body at ~41 Hz with `blk_out 1 req 0` latched, `V_LOADB 0` and 64 B of unread commands in the
ring. Three phases are solid, the shipped library is three phases, and the next question is in docs/25: is the third
adopt refused silently, or does the block layer latch on the third rewind?

**J-108 · The linter learned two rules and a check from the chaining work.**
R10 (`block start`) and R11 (`fit`) came out of two failures in the same hour: a split that put `40` on the far side of
a block boundary (`block 87: ERR_STACK`, then five `NAME?` lines naming words that were fine), and definitions written
at 94/96 B that only failed once the chip was already flashing. R11 is the cheaper of the two — it runs the splitter
that would have refused the upload, so the finding arrives with no board attached.

The third is not a lint rule at all: `cli.check_chains()`. A phase names its successor as a *literal* (`62 CHAIN`)
while the descriptor map lives in `cli.py`, so the same number exists twice and a stale one is silent — the phase jumps
to whatever image is in that block. The map moved twice today and both times the phases had to be re-pointed by hand.
The check runs before the machine is touched (source only), treats an absent `CHAIN` as `0` on the last phase, and
refuses the build by name.

Two of the three needed the selftest to be honest: R10's fixture is a *hand-made bad split*, because the splitter now
refuses to produce one — the rule is the belt to that braces (a regression in `fsplit`, or a hand-written multi-block
upload). And R10 was blind at first because `CONSTANT`/`,` were not in its vocabulary: a rule that cannot see the word
it is named after is a rule that reports nothing.

**J-109 · The throwaway probes became a corpus: `tools/sink.py` + `tests/sink/`.**
Every ad-hoc probe this session was a `.tmp_*.py` that got deleted after use, which is how a lesson gets re-learned. The
ones worth keeping are now twelve small Forth programs in `probe/repl/tests/sink/`, ordered by what they establish, and
one runner that checks each against **the verdict it must get**:

| # | file | establishes | must lint as | on the chip |
|---|---|---|---|---|
| 1 | 01_arith.fs | arithmetic and the stack | clean | `6620` |
| 2 | 02_loops.fs | BEGIN/WHILE/REPEAT over a `CREATE`d cell | clean | `1543` |
| 3 | 03_digits.fs | two-digit printing with a **bounded** EMIT | clean | `0 1 … 12` |
| 4 | 04_escape.fs | the ANSI byte path and the frame sentinel | clean | ESC[2J ESC[31m ok NUL |
| 5 | 05_cells.fs | `CREATE` / `!` / `@` below the seal | clean | `38` |
| 6-11 | bad_r01/02/03/04/07/08 | a `\` comment, an undefined word, underflow, leak, unbounded EMIT, `KEY` never tested | **the named rule** | r07 must print `ERR_ULPCODE` |
| 12 | bad_r11.fs | a definition too long for one block | R11 fit | — |

That is the point the operator asked for: the corpus is *the linter's* regression suite too. `--selftest` proves a rule
fires on the fixture it was born with; the corpus proves it does not fire on good code and still fires on bad code
written earlier. It runs in `tests/device.sh` and costs ~50 ms without a board.

Two facts fell out of building it, both now pinned:
* **`.` prints no trailing space** — `2 3 + .` answers `5 ok`, so three of them concatenate to `6620`. The sink
  expectations are the record.
* **the first block op after a hard reset can answer `ERR_BUSY`** — the store is still booting and the layer is latched
  (measured: HERE stayed 786, block 64 refused). One `0 2 BLKXFER` abort plus one retry is the documented escape; the
  runner does both, or the corpus fails for a reason unrelated to what it tests.

**J-110 · Branch `dispatcher`: 1 193 B of window, 2.1 ms per hop, and the two bugs that hid behind a 10 ms tick.**
Both halves of the operator's request are now numbers instead of arguments.

**Window.** `examples/boot.fs` (dispatcher only: `CHAIN`/`PICKX`/`SWITCH`/`GO` + two cells = 134 B of code, 24 B of
headers) leaves **1 193 B** where the full menu launcher leaves 254 B — 4.7×.

**Unlimited.** `tests/dispatcher.py` builds 24 generated phases and requires each to run in order and the line to return:
**24 hops, 50 ms, 2.1 ms/hop, counter 24, no refusals.** The ceiling is the store (128 blocks), not the design.

**Then the operator said "make it faster than 20 ms" — and that request exposed two real bugs.**

*F-132, the handshake.* The HP serviced a block request only on a 0→1 **edge it sampled** once per tick; a raw `BLKXFER`
does not raise `blk_req`, so an ULP that re-raised the flag between two polls was never answered: 845 ms of BLKWAIT,
`BK_NOSERVER`, flag left set, everything after that `BK_BUSY`. That is the "fourth hop" and the 41 Hz re-entry. Fixed by
testing the **pending level** (`blk_out == 1 && mailbox[2] == 0`) — zero ULP bytes — plus publishing `blk_out` *after*
the mailbox, because at boot mailbox[2] is 0 and a half-posted request got answered with power-on garbage (`ERR_CRC` on
the first LOAD).

*F-131, the canary.* `canary_paint()` wrote 0xA5 from a hardcoded `0x1EAC`, and **two bytes** of new code pushed
`blk_out`/`blk_req` past it. Those are the only ULP globals zeroed at boot and never rewritten, so they read
`0xA5A5A5A5` for ever — and the new level test believed it: **12 028 phantom requests in 2 s**, trampling the transfer
window under a real `LOAD`. Symptom: `ERR_CRC` on the first block read after reset in 2–3 of 12 trials, then NAME?
cascades, with a re-`LOAD` clean. Fixed by deriving the paint base from the pool budget the flash gate enforces, by
testing `blk_out == 1` rather than "nonzero", and by a boot assertion that names the fault. 18/18 trials clean after.

*F-133, the log line.* One `printf` per adopt is 4.8 ms of UART at 115200 and the block task cannot poll while it
writes: it was 4.5 of the 5.1 ms a hop cost. Now behind `#v 1`, quiet by default (failures stay loud). With the
hot-path spin (8 × 150 µs after a service, instead of a whole tick) the hop is **2.1 ms**.

Also on this branch: the window is **declared** (`MIN_WINDOW = 200` in `cli.library()`, refused if violated — it had
drifted 346 → 290 → 237 B silently); `connect()` proves the block server answers before handing over the port; the
linter learned that `'` pushes an xt and skips its operand; and phase names must avoid resident hash collisions
(`: P1` refused, `: PHASE1` compiled).

**Rejected:** `CONFIG_FREERTOS_HZ=1000` reached 2.2 ms but exposed an unrelated intermittent garbage path (5 failures in
11 trials at 1 kHz vs 0 in 6 at 100 Hz). One subsystem's latency is not worth the whole system's tick rate.

**J-111 · "Do we have coverage of any of this?" — two holes, one of them a false guarantee.**
The question found what the numbers had hidden.

*The refusal arm was a lie.* The guarantee added with the window work — "a failed adopt STOPS the chain instead of
executing stale bytes" — rested on `PICKX` returning a `NOOP` xt, and that arm read `UNLATCH ' NOOP`. Bare `'`
(`P_TICK`) calls `word()` at **run** time; `[']` (`BTICK`, immediate) compiles a literal. So the arm compiled a *parse*
that ran with no input and printed `?`. It never showed because the 24-hop test only ever adopted valid descriptors.
Fixed in both launchers, and `tests/dispatcher.py` now **forces** the refusal: a phase chains to a block nobody described
and the test requires the line to return, the counter to stop at 1, and `REFUSED` to be printed. Proof: revert the fix and
`a chain into an UNDESCRIBED block returns` fails with no ` ok`.

*The linter could not see it.* It modelled `'` as "push an xt, skip the operand" — right for the stack, wrong for the
code, and it never checked that a ticked word exists. It now has **R12** (bare `'` inside a definition, message carries
the fix), knows `[']`, and reports `['] NOXX` as R2. The corpus grew to 15 entries (`06_tick.fs` runs `[']` on the chip;
`bad_r12.fs` and `bad_tick.fs` are the two refusals) and `tests/run.sh` now lints `boot.fs`/`menu.fs` — a shippable file
that no host check reads is a file whose next regression waits for a board.

Also added, both from the same "was that ever tested?" pass: `dispatcher.py` asserts the block server is **quiet at rest**
(one idle second, stable `#u` total — the exact signature of the canary storm that cost two hours) and that the
per-adopt line is off by default and follows `#v` both ways (the 8 ms/hop threshold could NOT have caught that one: 24
hops x 4.8 ms is still 115 ms). `dispatcher.py` is 14 checks; the suite is 7 device files + a 15-entry corpus + the host
suite, all green.

**J-112 · The "HP off" behaviour is documented, because it was only in my head.** The operator asked what happens with
the main core disabled, and the answer existed as three separate facts in three code paths. It is now a named section in
`docs/25` ("What works with the HP switched off"), two rows plus a short paragraph in the user manual, and a pointer from
`docs/22`: (1) block server absent but HP alive - everything resident keeps working (dictionary 786 to headers ~2 476),
one `ERR_NO_SERVER` after `BLKWAIT` ~845 ms, then `ERR_BUSY` for every later block call until `0 2 BLKXFER`, which is a
deliberate latch, not a second fault; (2) HP not running at all - no console, since the HP owns the UART and both rings,
so a single baked program of 1 366 B; (3) the build switches that remove the HP from the picture on purpose
(`BISECT_NO_FLASH_WRITE`, `P33_NOPAGE`, and `CANARY`, which is a keep).

Every number in the table is quoted from the artefact that asserts it (`tests/blocks_noserver.fs` and its `.expected`,
decoded byte for byte: `ERR_NO_SERVER -3`, then `5` from `2 3 + .`, then `ERR_BUSY -2`), so the document cannot drift from
the machine without the host suite going red first.

**J-113 · Wave 1 of the App Store: the contract, two harness/code lanes merged, and the finding that stops the slice.**
Three lanes ran in parallel worktrees; two delivered, the third measured something that mattered more than the app.

*Lane C (contract code).* `cli.py` now refuses an over-window image and a phase set past 128 blocks, prints a per-phase
budget table from real descriptor sizes, and `--geometry` prints the compiler-side constants (memory 2 604, header top
2 476 = transfer offset, block 128, rings, pool budget) so they can be diffed against the board's own `#u`/`#i`. The linter
gained R16 (a phase may not own state) and R18 (a phase must name a return path), with fixtures and two corpus entries.

*Lane H (harness).* `tools/screen.py` turns a run into a 70x24 cell grid and diffs a golden; `tests/parity.py` runs one
program on the host binary and on the board and diffs every cell (a skip is never success); `tests/build_host_app.sh`
derives every constant from the sources and refuses by name if one cannot be read.

*Three things I had to correct, all mine.* (1) The screen width was invented as 80x24; the launcher's own `FILL` is
**70 columns**, so cards are 22x7 in two bands. (2) The harness was a second terminal driver beside the one in
`tests/tui_cli.py`; the reader now lives once in `tools/frames.py` and screen.py adds only the grid. (3) The contract put
the display vocabulary in the resident launcher; measured, that is 831 B of a 1 366 B budget and the window fell to
535 B. Resident is now the dispatcher plus the registry (measured **335 B**), every phase carries its own drawing words,
and the window is **1 031 B** (`F-135`).

*The finding.* A phase's own display vocabulary costs ~175 B, strings ~90 B, leaving ~760 B of logic. The calculator as
written (digits, four operators, equals, tape with j/k, always-on through registry cells) needs ~1 184 B and does not fit;
it was refused mid-compile with `KX?` and **no error on the failing line** - when the header area meets the code area the
name is simply not recorded, and the next use reports `NAME?` (`HERE` 1984 vs `LATEST` 2011). The file is parked as
`calc1.wip.fs`, not in `LIBRARY`, not tested: nothing claims it works. Wave 2 splits it into two phases, which is the case
the 16 KB store was sized for.

*Also fixed on the way:* `DO`/`LOOP` were in the linter's CONTROL set while `src/p31_prims.inc` has no such prim, so the
linter certified a calculator loop the engine refused at line 11 - removed, and `bad_loop.fs` is now a corpus entry. And
the App Store window floor (1 000 B) was being applied to the *shipping menu launcher* (254 B, correct for its own
design), which turned `programs.py` and `tui_cli.py` red; there are two floors now, `MIN_WINDOW` for any launcher and
`APP_WINDOW` for the App Store build.

State: host suite 25 PASS / 0 FAIL, device 7 files + a 16-entry corpus green, linter selftest PASS.

**J-114 · The App Store runs on the chip: five phases, 16/16 end to end.**
`./cli.py --appstore` builds the resident (dispatcher + registry, 344 B), SEALs the window at **1 037 B**, stages and
describes five phases (calc 995, tape 641, mail 910, reader 981, shelf 1 032), seeds content and enters through `56 GO` so
the dispatcher owns the switching. `tests/appstore.py` drives it through a pty - the operator's own path - and asserts what
is DRAWN: five cards with exactly one inverse title, `Enter` opening the calculator, `12+34=` drawing 46 on the chip, `q`
returning to the shelf, `Enter` opening the inbox, a card with no app refusing, and a clean exit with no `ERR_` anywhere.

Four defects fell out of that last stretch, each of them a lesson now written down: the shelf's `NL` was LF without CR (a
terminal keeps the COLUMN on LF, so every row wrapped - that was the operator's mangled screen, not the output ring); a
card whose app was never built adopted whatever an older build left in that block (`BK_RANGE = -5`); `cli.library()` staged
the menu launcher at block 70, which is reader CONTENT now, so the reader drew its own source; and `RMAX` clamped half way
through page 2 while the page base still said 64 after content moved to 72.

Also closed: `BLOCK` no longer hands a status back where an address belongs (three paths, all push 0 now, with the status
still named), and the drop counter is back and READ - which then disproved my own explanation. Every scenario reports zero
drops, so the reader's unpaced loss is downstream of `pl_emit`; the pacing stays as a labelled workaround, not a rule.

Not in this version, and the cards refuse rather than pretend: **sheet** (1 371 B against a 1 037 B window - needs a
two-phase split) and **gopher** (never written). Both are wave 3.

**J-115 · Branch `spi-lora`: the low-power / external-memory research is written down, labelled as unmeasured.**
The ESP32-S3 went back in its box with an 8 MB flash backup (sha256-verified, `backup/README.md`), and the next era opens
with a different question: could an ultra-low-power SPI memory let the ULP alone keep this machine alive for months, with
more RAM than the 8 KB it has? The research conversation is now `docs/27-spi-lora.md`, and its most important property is
that it says which numbers are guesses: the ULP's bit-banged SPI figure (235 kHz first try, 350 kHz with direct register
writes, ~417 kHz estimated ceiling, 1.1 MHz measured for clock-only toggling) is forum-reported, the FRAM/MRAM clock maxima
are datasheet-recalled, and the deep-sleep µA floor is recalled too. Not one of them was measured here.

The hard constraint that did come out of it, and it is ours: the ULP image is **7 891 of 7 892 B**. A LoRa driver and an
external-memory path both have to buy their bytes from the interpreter, so the first real question is the byte budget, not
the driver.

**J-116 · The SX126x reference driver is written down, and the Forth answer is arithmetic, not opinion.**
`docs/28-sx126x-ulp.md` holds the supplied C (six files, reassembled - the paste had its blocks interleaved, and
`sx126x_ulp_hal.h` was never supplied, so its contents are inferred and marked), eight "check this before copying it" notes,
and the answer to the real question.

The answer: **yes, in Forth - and the reason is the opposite of the obvious one.** Not that Forth is fast enough, but that the
SPI is too small a share of the cost to care about. A 20-byte packet at SF9/125 kHz is ~90 ms of air time; the warm-start TX
path is ~35 bytes of SPI, which is 1 ms in C and 4-9 ms in Forth - 5-10 %. Warm start makes the interpreter's 4-10x penalty
disappear into the noise. Cold-initialising every packet would make it visible (~30 %), which is why the C's
LORA_FORCE_COLD_INIT stays a debug flag.

What Forth actually costs is BYTES, and that is the honest blocker: the ULP pool is 7891 of 7892 B. So the driver belongs in a
PHASE - the mechanism we already built - with 3-4 primitives (pin write/read, microsecond delay, the bit loop) in the token
table. Calibration from our own history: one counter plus its increment cost 12 B, so 3-4 primitives are ~120-230 B that we
do not currently have; something moves first, or the radio lives on the main core and the ULP just counts wakes.

Also recorded so it is not rediscovered: DIO1 is a LEVEL, so the IRQ clear must happen BEFORE SET_TX or the wait exits on the
previous packet and looks like a radio fault; BUSY timeouts must be derived from a measured loop, not a guessed iteration
count; a freq computed from a variable drags a 64-bit divide into the ULP image; and the cfg in a block must use 4-byte
offsets, because F-136 already proved what an unaligned load does on rv32.

**J-117 · The backup was of the wrong board, and the identity check that "passed" was a substring count.**
With the LoRa board now on `/dev/ttyUSB0`, the flash backup was taken and recorded as the App Store machine. It is not: the
app region says `esp-idf: v4.4.7 38eeba213a / arduino-lib-builder`, the strings say `SX126xInterface<T>` and
`meshtastic_MeshPacket`, and it is a **Heltec V3 running Meshtastic**. The four "our firmware" hits that satisfied the check
were all the word **`repl`** inside stock IDF strings. The App Store board had already gone (its `/dev/ttyACM1` console was
absent - that is also why the new board's console looked silent at 115200: Meshtastic talks over USB-CDC). The 8 MB image
is re-filed as `heltec-v3-meshtastic-...bin`, which is genuinely useful - it is the LoRa board's factory firmware - but the
App Store flash was **not** captured, and `backup/README.md` now says so in its first paragraph plus the exact 3-minute
procedure for when that board is back.

Rule R16 was written for it: an identity check must produce something only that entity could produce - a full-region hash
against a known build, the project-description string, a recorded MAC - never a substring count, a banner, or "it answered".
Corollary: a device on the same path after a replug is a different device until proven otherwise.

The measurement itself could not run (no board with our interpreter attached), so the tool that will run it is committed
instead: `probe/repl/tools/token_rate.py` measures per-token cost from the differences between three same-loop definitions
(so loop overhead cancels), refuses to report if the REPL is not ours, and derives the whole LoRa table from it - including
the honest modelling of the C primitive at its own 350 kHz rather than as "1 token per byte". Two unit bugs were found in
it before committing: SCK kHz printed as 1000/(8*us_byte) understated the bus 1000x, which would have made a 40 kHz bus look
like 0.65 kHz and "Forth is hopeless" for arithmetic reasons.

**J-118 · The ULP-RISC-V transmits LoRa. First try: 4/4 packets, no main core involved.**
`probe/lora` is a bare-metal ESP32-S3 project where the ULP bit-bangs SPI to an SX1262 on a Heltec V3: **975 cycles/byte
(143 kHz SCK)**, driver **2 584 B**, `TxDone` on every 5 s wake, chip status `0x2c` read by the ULP agreeing with the
hardware-SPI probe's `0x2a` on the same pins. The question docs/28 was written around - "can the ULP own the radio" - is
answered yes, and the answer came with the numbers the docs had only guessed at.

What the bring-up cost, and taught: **F-141**, `RTC_GPIO_OUT_DATA_W1TS_S` is 10, so `REG_WRITE(..., BIT(pin))` writes ten
bits below the field and is silently discarded - the ULP ran, the loop executed, MISO read 0, GetStatus read 0x00, and
every command "succeeded" while no pad moved. Four flash cycles went into pin maps and GPIO handover before a pad
read-back inside the ULP settled it. **F-142**, that read-back instrument was itself blind: `RTC_GPIO_IN` only reports a
pad with its input buffer enabled, so an output pin reads 0 and the test said "everything is dead" for a working bus.

Green on the way: the two-configuration cold init (no TCXO, then TCXO) turned a jumper guess into a fact - **this board
needs the DIO3 TCXO at 1.8 V** - and warm start retention (`SET_SLEEP 0x04`) is proven across ULP wakes, which was §6.4's
open question.

Standing: decode a packet on a receiver (TxDone proves the radio transmitted, not that the bytes are right), then deep
sleep, then the Forth question with real sizes - 2 584 B of C against a 7 892 B pool holding everything and 1 B free.

**J-119 · Air side verified without a receiver: 195.8 ms against a derived 185.3 ms.**
The packet's payload was read back out of the radio's own TX buffer (`ReadBuffer 0x1E`) and matches byte for byte, so the
SPI data path is proven rather than merely error-free. The ULP's awake window per warm transmit, timed by the main core at
200 us resolution, is **195.8 ms** against **185.3 ms** predicted for SF9/125 kHz/20 B/CR 4-5 - 105.6 %, i.e. the modem
really is configured the way the driver claims.

Two instruments were caught lying on the way. **F-143**: `ULP_RISCV_GET_CCOUNT()` calibrated to 0.3 % over 10 ms and then
read 3.4e9 cycles (195 s) across SET_TX -> DIO1, even after switching to signed arithmetic; it was replaced with the main
core's clock rather than "fixed". **F-144**: the replacement number then looked impossible because the expected air time
had been computed as ~108 ms without the (CR+4) factor - 14 payload symbols instead of 33. A correct measurement was
rejected because a bad derivation sat next to it.

Also now proven with a counter instead of an assumption: **warm start**. `cold 2` against `wakes 6`/`tx_ok 6` - exactly two
cold inits ever, every later wake going straight to SET_TX. docs/28 §6 and probe/lora/README.md carry the measured table.

**J-120 · Deep sleep: the CPU off, the ULP still transmitting, 31 packets and no failures.**
Five 30 s deep-sleep cycles on the Heltec V3: the ULP's RTC-domain timer keeps firing every 5 s with `esp_deep_sleep` in
force, `tx_ok` climbs 6, 13, 19, 25, 31 with `tx_fail` at zero, and `cold` stays at 2 - so the warm radio configuration
survives the CPU being powered down, and the mechanism docs/27 described as plausible is now demonstrated.

`ESP_PD_DOMAIN_RTC_SLOW_MEM` does not exist on the S3: RTC slow memory cannot be powered down, which is exactly where the
ULP's variables live. `RTC_PERIPH` is held on explicitly, since that is where the ULP lives.

The energy answer, from `probe/lora/power_budget.py` (measured timings, labelled datasheet currents): **95 % of the ULP's
awake window is the packet on air**. 195.8 ms per transmit, 185.3 of them on air; at a 5 s period a 2000 mAh cell is ~49
days, at 30 s ~287 days, at 60 s ~1.5 years. The levers that buy months are the period and the air time, not the SPI
clock and not the interpreter - which is the useful thing to know before porting anything to Forth.

F-145 records the fourth unit slip of this project, and the fix that finally holds: derive one named rate, convert with
the factors written out, print both.

**J-121 · Every LoRa number is now in one file, and a script checks it.**
`docs/29-lora-measurements.md` consolidates the whole session: hardware facts established by measurement (pin map, `GetStatus`
0x2a, the TCXO on DIO3 at 1.8 V proven by trying both), the ULP's size and speed (2 804 B, 17.550 MHz, 971 cycles/byte =
144.6 kHz SCK), air time (33 payload symbols, 185.34 ms derived against 195.8 ms measured, 105.6 %), sleep behaviour (five
deep-sleep cycles, 31/31 packets, `cold` frozen at 2), and the power table (~49 days at a 5 s period, ~287 days at 30 s,
~1.5 years at 60 s, on labelled datasheet currents).

The part that matters as much as the numbers: `probe/lora/verify_numbers.py` re-derives them from the datasheet formula and
compares both against `probe/lora/results/console-2026-11-01.txt`, the verbatim capture. It caught two things while being
written - that the capture I had saved did not actually contain `wakes 31` (a shorter run had produced it), and that my own
"tx_ok == wakes" assertion was wrong on the warm-up sample, which is now left in the table and explained instead of
smoothed away. A document with a wrong number is worse than no document; F-143 and F-144 both cost a session's worth of
confusion in the same week.

**J-122 · The SX1262 driver, in Forth, verified byte-for-byte without a radio.**
`examples/apps/lora/lora1.fs` bit-bangs SPI on GPIO!/GPIO@ alone - **zero new primitives** - and compiles to **958 B**
(HERE 786 -> 1744), which fits the 1 037 B phase window with 79 B to spare. Against the C driver's 2 804 B that is a third
of the size, and the wire is identical: `probe/repl/tests/lora_spi.py` reconstructs the SPI byte stream from the host
engine's own pin trace and compares **transaction by transaction** against the 14-command cold-init sequence the C driver
runs on real hardware (55 bytes), plus the transmit path through SetTx (WriteBuffer with the 20 payload bytes,
ClearIrqStatus, SetTx). Wired into run.sh: the host suite is 30 PASS.

Three bugs fell out before any hardware was touched, and two are general lessons. **F-146**: this dialect's >R / R> leave
TWO extra cells per call when used inside a word that calls other words (`7 9 LORA_SPIX . . .` printed three numbers), so
every second command byte arrived as 0x00 - fixed by unrolling the bit loop into eight stack-neutral shifts, which is
faster as well. **F-147**: SetPacketParams starts with a 16-bit preamble and the driver sent only its low byte, shifting
every following field by one; only the golden byte stream could see that. Plus R15 in person: a pin constant named
LORA_RESET collided with a word of the same name, so `1 LORA_RESET LORA!` called the reset word recursively and the machine
said only "error".

Not done, and named in docs/30 §5: the file is not yet packaged as a device phase (block source has no line boundaries, so
its `\` comments are refused by R1 and LORA_INIT does not fit one 92 B block - R11), it has never run on a radio, and the
~30-40 kHz bus estimate is still an estimate because measuring it needs our interpreter on this board.


# 03 — Review of the reference prototype (`uforth.c`)

The prototype is reproduced verbatim in [`probe/uforth/uforth.c`](../probe/uforth/uforth.c). This
review is based on **executing** it, not reading it: it is built for the host, a 36-word boot layer
is compiled into it, and 53 behavioural tests are run against it
([`probe/uforth/REVIEW-RUN.txt`](../probe/uforth/REVIEW-RUN.txt)). Everything below is either a test
that passes, a test that fails on purpose to pin a defect, or a measured number.

```sh
cd probe/uforth
gcc -DHOST -std=c99 -Wall -Wextra -o uforth_test host_test.c && timeout 30 ./uforth_test   # 53 passed, 0 failed
gcc -DHOST -std=c99 -o uforth_boot uforth.c && ./uforth_boot boot_min.fs -d probe_image.h
```

---

## 1. Verdict

The core idea is right and the code is a real, working base: token threading, a C inner
interpreter, headers with links, `CREATE`/`CONSTANT`, immediacy, a text interpreter, and a
dictionary that fits with room to spare (1352 of 2560 bytes, **1208 free**, after 64 primitives and
36 high-level words).

It is **not yet a ULP program**, for four structural reasons (§4, D3–D6), and it has a family of
silent-failure habits (§4, D1–D2, D10) that are the opposite of what this project needs. None of
them are hard to fix; all of them are easy to inherit by accident.

---

## 2. Measured facts about the prototype

| Metric | Value | How |
| --- | --- | --- |
| Primitives in the table | **64** (`P_COUNT`) | `dbg` count of headers |
| Bytes for primitives (headers + code + system vars) | **540 B**, `HERE = 596` | after `boot_init()` |
| Boot layer added | **36 words, 756 B** → 1352 B total | `boot_min.fs` |
| Average high-level word | **21 B** (header + ~4 tokens) | 756 / 36 |
| Free dictionary at 2560 B image | **1208 B** | 2560 − 1352 |
| Test suite | 53 assertions, all passing | `REVIEW-RUN.txt` |

The 21 B/word figure is the one to plan with: at 2560 B of Forth memory a typical word costs 21 B,
so ~55 words per KB of dictionary. A 4 KB image (MEMSZ 4096) holds ~150–190 words plus primitives,
which matches the earlier hand-estimate for an application-sized Forth.

---

## 3. What is verified to work

| Behaviour | Test |
| --- | --- |
| `+ - * /MOD U/MOD`, truncating signed division | `-7 2 /MOD` → rem −1, quot −3 |
| `INT_MIN / -1` does not overflow-trap (special-cased) | → rem 0, quot `0x80000000` |
| Stack ops `DUP SWAP OVER ROT >R R>`, `U<`, `<`, `0=` | several |
| `DO … LOOP` with correct `I`, nested `J` | 3 and 6 values, in order |
| `+LOOP` descending, limit crossing | 5 4 3 2 1 0 (6 iterations, standard semantics) |
| `IF/ELSE/THEN`, `BEGIN/UNTIL`, `WHILE/REPEAT` | taken/not-taken, termination |
| `: ; LIT BRANCH 0BRANCH EXECUTE` | `: B A A + ;`, `' Z EXECUTE`, `['] + EXECUTE` |
| `CREATE`/`,`/`@`, `CONSTANT`, `C,`/`C@` | four tests |
| Number base (`BASE` via `12 !`) | hex `FF`, decimal `255` |
| Compiler rollback on error inside `:` | `HERE`/`LATEST`/state restored, earlier words still work |
| `."` compile-time string | `(.")` + inline length |

The boot layer proves the harder claim: **control structures can be written in Forth on this
engine** — with `[']`-literals standing in for a `POSTPONE`/`COMPILE` mechanism that the primitive
set does not have. That is a real design constraint, recorded as D9 below, not an oversight to paper
over.

---

## 4. Defects, ranked

Severity: **B** = blocks the ULP port, **S** = silent wrong behaviour, **C** = cosmetic/documentation
debt. Each row names the test that pins it.

### D1 (S) — out-of-range addresses are silently redirected
`P(a)` returns `&junk` for every address ≥ `MEMSZ`, so all wild addresses alias **one shared byte**.
A bug becomes a wrong answer instead of an error, and on the ULP this is also why Forth cannot see
peripheral registers at `0x8000…`.

Evidence: `7 12288 C!` succeeds; `12288 C@` → 7; `16384 C@` → **7** (same byte).

Fix: an explicit `bad_address()` that sets a sticky `ERR_ADDR` status, aborts the current line, and
(on the ULP) retires the core with the status published. A debug build can additionally record the
faulting address and the IP.

### D2 (S) — stack depth is unguarded in both directions
`sp` is `u8` and the index is masked with `SD-1`, so a 17th push overwrites cell 0, and `POP()` on an
empty stack wraps `--sp` to 255 and reads stale data.

Evidence: 20 pushes into a 16-deep stack raise nothing and destroy cell 0; `+` on an empty stack is
silent.

Fix: check depth **before** the store in a debug build (two instructions), keep guard cells under
both stacks and verify them at every `PAUSE` and at wake exit in release builds, and make an
overflow/underflow a named fault.

### D3 (B) — the REPL blocks
`forth_quit()` loops forever on `pl_key()`. On the ULP a wake must *retire*: blocking on input means
the core either never sets `DONE` (and misses every subsequent tick) or depends on the main CPU
being awake, which defeats the point.

Fix: no blocking primitive. The REPL becomes a state machine driven by the command ring:
`wake → drain ring → feed characters → on newline interpret one line → publish output → retire`.
`KEY` stays for a *buffered* read that fails with `ERR_NO_INPUT` when the ring is empty.

### D4 (B) — `run()` is not resumable
`ip`, `w`, `a`, `b`, `n` are locals of `run()`. Task switching at `PAUSE` works (a primitive can save
`ip`), but **resuming across a wake boundary does not**, and that is precisely what a persistent VM
needs: the C stack is discarded, and `start.S` re-seeds `sp` on every wake.

Fix: `u16 run_from(u16 w, u16 ip)` returning either `VM_RETURNED` or `VM_RESUME(ip)`; store
`(w, ip)` in the task record / VM state. Also removes the `ip == 0` sentinel, which is a second
latent trap.

### D5 (B) — no shared mailbox, no defined absolute window
The main CPU can only reach `mem[]` if it knows its RTC address. With `static u8 mem[MEMSZ]` inside
`.data`, that address is whatever the linker chooses, and `MEMSZ` is a compile-time guess shared
between the PC build and the ULP build with **no guard**: if `image.h` was generated with
`MEMSZ=2560` and the ULP build uses another value, the array size silently wins and offsets shift.

Fix: one named block at a fixed offset inside `mem[]` (`struct uforth_mailbox` at `MAILBOX_OFF`),
exported as a symbol so the generated `ulp_*.h` gives the main CPU `ulp_<name>` = `0x50000000 + off`;
and a `#define` emitted into `image.h` that the ULP build `#if`-checks against `MEMSZ`.

### D6 (B) — hardware is only reachable through `pl_hw`
Forth sees `mem[]` and nothing else. That is a defensible, testable design (no wild pointers, host
tests run unchanged), but it means every peripheral needs a new primitive and an opcode, and it
collides with D1's "registers at 0x8000" reality. Decide it explicitly rather than by accident:

* **Option A (recommended for v1):** keep the array-bounded model and grow `pl_hw` into a documented
  op table (GPIO get/set, ADC, RTC-IO interrupt ack, wake-CPU, I2C read/write, cycle counter).
* **Option B:** let Forth address real ULP-space memory (`0 … 0xFFFF`), keep a guard band for the
  dictionary, and accept that host tests need a mapped region.

### D7 (R) — 32-bit access is byte-at-a-time — **REQUIRED, but not for the reason assumed**
`rd32`/`wr32` are built from two `rd16`, each built from two `rd8`: **8 byte accesses per cell read**,
costing **452 cycles** in the shipped build (P14) against **8.1** for a native `lw`.

**But it does not cost what it looked like it cost (P20).** The interpreter's token fetch goes through
`rd32_paged()`, which resolves the page once and then does four `lbu` on the frame — so `NEXT` never
enters this chain, and native accessors save **0 cycles** on dispatch while costing **+116 B** of
engine. What they actually buy is `@`/`!`/`find`/`mkhdr` at **8.0× / 5.5×** — the parse-and-compile
path, which is exactly where a REPL spends its time. So D7 is still required, but it is a
*compile-speed* fix, not an interpreter-loop fix, and it should be adopted together with the agnostic
rule that paged fetches go through one resolved pointer rather than an address. Also note P02: the address-space work makes this cheaper, because 32-bit
references make cell alignment an invariant a build can assert rather than a hope.

### D8 (C) — error rollback covers `:` only
`savehere`/`savelatest` are set in `P_COLON` and used when `errf` is set. A failed `CREATE`,
`CONSTANT`, `."` or `,` leaves the dictionary advanced. `savehere` is also zero-initialised and only
safe because rollback is gated on `V_STATE`.

Fix: snapshot at the start of every *line* (`interpret`), roll back on any error to that snapshot,
and make the snapshot explicit rather than incidental.

### D9 (C) — no `[ ]`, `COMPILE`, `POSTPONE`
Control words must be written with `[']`-literals (see `boot_min.fs`). That works, but it is not
obvious, and any user defining an immediate word will hit it. Either document it as *the* idiom or
add `[`/`]` (two trivial primitives) so `[ ' 0BRANCH ] W,` style is available.

### D10 (S) — input truncation is silent, and the limit is small
`forth_quit` drops characters past `TIBSZ-1` with no diagnostic. Verified: a 100-character line is
echoed back as 79 characters and compiled as if nothing happened. The file loader *is* loud
(`line too long (83 >= 80)`), and `boot_min.fs` tripped that limit on its own first line — so the
limit is not theoretical.

Fix: 128-byte buffer, and an explicit `ERR_LINE_TOO_LONG` that aborts the line.

### D11 (C) — `'` is not immediate
`: Q ' ;` compiles happily and explodes at runtime when `'` tries to parse from an empty input
buffer. Use `[']` inside definitions; consider making `'` immediate or refusing it in compile state.

### D12 (C) — `KEY?` is untestable
It calls `pl_hw(5, …)` and the host backend has no case 5, so the non-blocking input path looks
implemented but is hardwired false.

### D13 (C) — no hex literals
`0x3000` is a parse error (`number()` is base-relative, `X` is 33 ≥ 10). The boot layer now provides
`HEX`/`DECIMAL`; a `$` prefix in `number()` would be friendlier for addresses.

### D14 (C) — `pl_emit` "may drop"
For a REPL fed by a ring buffer this must not be silent. Add a dropped-byte counter to the status
block so the harness can report it.

---

## 5. What this changes in the proposal

| Proposal section | Was | Now |
| --- | --- | --- |
| §4.1 threading | recommended indirect threading with 32-bit cells | **token threading retained** (a tested implementation exists, 21 B/word measured); cell/token width becomes **32-bit xts** once paging lands, because 16-bit tokens cannot index past 64 KB — that is the price of R5, ~30 B/word |
| §4.4 bootstrapping | stream the prelude from the HP, compile on target | **prelude stays text** and is interpreted on the chip (requirement R1). The `image.h` bake is dead: it was a proof that the model closes, not the shipping path. Streaming from flash at boot is the mechanism; a dictionary snapshot is a cache of interpreted work, never a compiled program |
| §4.2 registers | pinned TOS/`dsp`/`rsp`/`ip` in RISC-V registers | unchanged as a goal, but only after E1 says the C interpreter is too slow; the prototype has **no** pinned registers and works |
| §5 event loop | state machine across wakes | now a hard requirement, not a preference: D3 + D4 are port blockers |
| new | — | §4.6 "compile-time stack discipline": `DO`/`IF` leave patch addresses on the data stack, so a `PAUSE` or an error during compilation corrupts the compiler state; the compiler needs its own stack or careful bracketing |

Two smaller consequences worth carrying into the design:

* **Word density is the budget unit.** 21 B/word measured; plan the app in words, not bytes.
* **The inner interpreter is a `switch` over 64 cases** running from RTC memory with no I-cache.
  Cycles per token is the number that decides whether this whole approach fits inside one wake
  budget. It must be measured on the ULP before any optimisation work (E1), and the host benchmark
  is not evidence for it.

---

## 6. Port plan

| Step | Change | Acceptance |
| --- | --- | --- |
| P0 | Watchdog on the test runner (`timeout`) — a bad branch operand hangs the VM, as it did here | suite still 53/53 |
| P1 | `bad_address()` + depth guards + `ERR_*` status block (D1, D2) | each "KNOWN DEFECT" test flips to expecting a named error |
| P2 | `run_from(w, ip)` returning a resume token; remove the `ip==0` sentinel (D4) | a test that suspends mid-word and resumes produces identical results to an uninterrupted run |
| P3 | Non-blocking REPL state machine + ring buffers (D3) | the same suite runs with input fed from a ring, one line per "wake" |
| P4 | resident-layout guard (was `image.h` MEMSZ) + fixed mailbox block + symbol export (D5) | host tool reads/writes the mailbox through `0x50000000 + off` |
| P5 | `ulp_main.c`: `pl_*` over `pl_hw`, wake loop, `rdcycle` budget, `return 0` to retire | `ulpctl info` + heartbeat from the real chip |
| P6 | Profile with `rdcycle` (E1); only then consider `lw`/`sw` accessors (D7), pinned registers, superinstructions | cycles/token and cycles/wake published in `probe/EVIDENCE.md` |

P0–P4 are host work and can be done with no board attached; P5 is the first step that needs the
S3, and it depends on the harness in [`02-harness.md`](02-harness.md).

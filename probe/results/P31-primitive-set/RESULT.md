# P31 — Does the layer need 61 primitives, or 40?

| | |
| --- | --- |
| Result | **The layer needs exactly 40 — and that is still not enough to link.** The requirement was derived from the engine's own name lookups, not from a guess: a host build of the shipping engine instrumented in `find()` loaded `boot_min.fs` + the whole P26 layer and resolved **35 primitive names**; adding the four the compiler emits without a lookup (`EXIT` from `;`, `LIT` from numbers/`[']`, and the pseudo tokens `(DOCOL)`/`(DOVAR)`/`(DOCON)`) gives **40 required entries**, i.e. **26 of the 63 table entries are dead: 1158 B** (A 4934 → **B 3776**). P30's hand VM copy and unrolled zeroing on top gives **C = 3412 B** (`.bin − control` 3424) — **26 B *under* the 3438 target** — yet the **real 7856 B link still fails: 8152 needed, 296 B over**. The reason is arithmetic that the target never checked: the fixed budget lines are **4740 B** (8152 − 3412), so the engine's true ceiling is **7856 − 4740 = 3116 B**, not 3438. Cutting the primitive set bought 1158 B, the largest single lever in the project, and it lands the engine 296 B short of a machine that links. Nothing is chosen here; the three options are priced in §3. |
| Runs on | **host only** (compile + link + `nm`) — `esp32s3` ULP-RISC-V, `riscv32-esp-elf-gcc 14.2.0 (esp-14.2.0_20241119)`, IDF v5.4, `-Os -march=rv32imc_zicsr_zifencei -mdiv -fdata-sections -ffunction-sections`, P22/P29's linker script (`LENGTH = 7856`). Board untouched, no `/dev/ttyACM*` opened. |
| Time box | **overrun: ~15 min of work in ~45 min.** Cost of the overrun: the per-primitive byte cost inside the switch was not measured one at a time (only the 26-entry aggregate, 44.5 B/entry), and the `-Oz` follow-up P30 suggested was not tried on C. Nothing in the verdict depends on either. |
| Sources | `src/uforth.c` = **P30's `uforth.c`** (itself P29 verbatim + `-D` knobs) with **one mechanical change**: the `PRIMS` X-macro and the `vm_enter` dispatch switch were cut into `src/p31_prims.inc` and `src/p31_cases.inc` by `p31_gen.py`, each entry and each case group behind `#if !defined(P31_SUBSET) \|\| defined(P_HAVE_<ID>)`. The text is **moved verbatim, never retyped**, and with no `-DP31_SUBSET` the token stream is unchanged — **A reproduces P29/P30 to the byte**. `src/p31_host*.c` does not exist: the derivation build is `src/uforth.c` itself with `-DP31_TRACE -DHOST` (the `P31_TRACE` hook is inert in the ULP build). `derive.py` turns the trace into `src/p31_required.defs`, which `p31_build.py` compiles into B and C. |
| Time box | one run, three variants, each **really linked** at `MEMSZ` 908 with 3 tasks (`-DNTSK=3 -DSD=16 -DTIBSZ=128`) |

## Record

Engine = `.text + .rodata` minus the 196 B control image (P29/P30's convention); `.bin − control` is the
second, 12–14 B higher column. Every variant was linked for real against `LENGTH = 7856` **and** placed in a
12000 B diagnostic region so `nm -S` can be read at all.

| Variant | primitive entries | engine, sections | engine, `.bin − control` | gap to 3438 | pool: needed of 7856 | real 7856 B link |
| --- | --- | --- | --- | --- | --- | --- |
| **A** P29 baseline | 63 table (+3 pseudo) | **4934** (4670+264) | 4948 | **+1496** | 9692 | **FAIL** — `address 0x25dc`, 1836 over |
| **B** exactly the required set | **37 table (+3 pseudo) = 40** | **3776** (3616+160) | 3788 | **+338** | 8516 | **FAIL** — `address 0x2144`, 660 over |
| **C** B + hand VM copy + 4-word zeroing | 37 (+3) | **3412** (3252+160) | 3424 | **−26 (fits 3438)** | 8152 | **FAIL** — `address 0x1fd8`, **296 over** |

A reproduces P29/P30 exactly on every figure that was recorded there: `.text` 4670, `.rodata` 264, engine
4934/4948, `vm_enter` 2380, `memcpy` 232, `memset` 168, and the same link address `0x25dc`. So the
refactor into guarded includes changed nothing, and B/C are measured against the same machine.

Per-symbol, where the 1522 B between A and C actually are:

| symbol | A | B | C | what it means |
| --- | --- | --- | --- | --- |
| `vm_enter` | **2380** | **1354** | **1354** | **−1026 B from dropping 26 bodies**; the switch still holds 40 cases, the fetch, `EXIT`/`EXEC`/`PAUSE`/`FAULT`-less tail |
| 26 removed bodies | in `vm_enter` | gone | gone | 1158 B total (A−B), **44.5 B per entry** — P30's ~57 B/figure was for out-of-line functions with their own prologues |
| libgcc `memcpy` | 232 | 232 | **0** | `tsk[from].vm = *V` replaces with `vm_copy` (30 B) |
| libgcc `memset` | 168 | 168 | **0** | `vm_task_init`'s zero loop becomes a 4-word unrolled store loop |
| `vm_switch` | 102 | 102 | **92** | smaller once it calls `vm_copy` |
| `mkhdr` | 148 | 194 | 194 | +46 B: the outer interpreter's inlining balance shifts once the switch is smaller (in the totals, not hidden) |
| `word` / `find` / `clit` | 202 / 148 / 34 | 172 / 0 / 0 | 172 / 0 / 0 | `find` and `clit` are absorbed into their callers at this size; the trio's total falls 384 → 172 |
| `pg_load` / `rd16_paged` / `resolve` | 108 / 60 / inlined | same | same | untouched in every variant — paging is not in this lever |
| `err` / `vm_task_leave` / `vm_next_ready` | 66 / 76 / 52 | same | same | |

`nm -S` allocation check, **all three variants, not just the best one** (from `artifacts/p31_<V>_nm.txt`):

```
frm=2048 ptab=16 ptab_lru_reserve=234 cmd_ring=128 out_ring=256 mailbox=216 tib=128 mem=908
vm_live=136 tsk=420   A: all-present   B: all-present   C: all-present
```

## 1. Answers

**Q: Which primitives does the P26 layer and `boot_min.fs` actually name?**
Not from a reading of the sources — from the engine. A host build of the shipping `uforth.c`
(`-DP31_TRACE -DHOST`) had `find()` record the **header address** of every successful lookup while
`boot_min.fs`, `os_tasks.fs`, `os_events.fs`, `os_repl.fs`, `os_introspect.fs`, `os_device.fs` loaded. A header
below the address `V_HERE` had after `boot_init()` is a primitive, so the name printed is the primitive's own
name out of its own header. It resolved **35 distinct names, in one clean run, no errors**
(`artifacts/p31_host_trace.txt`):

```
!  ( +LOOP) (DO) (LOOP) * + , - /MOD 0= 0BRANCH : ; < >R @ AND BRANCH
C!  C@  CREATE  DROP  DUP  EMIT  EXECUTE  GPIO@  KEY  OR  OVER  R>  ROT  SWAP  TYPE  [']  \
```

Five more are required and **can never appear in a name trace**, because the compiler emits their tokens
directly:

| added | why it is required though nothing looks it up |
| --- | --- |
| `EXIT` | `;` compiles `rd16(V_XEXIT)`; `boot_init` sets `V_XEXIT` only if the `EXIT` entry exists. Without it every colon word ends in token 0 = `(DOCOL)` — infinite recursion, not an error message. |
| `LIT` | `clit()` (numbers and `[']`) compiles `rd16(V_XLIT)`; same mechanism, same silent garbage. |
| `(DOCOL)` `(DOVAR)` `(DOCON)` | `:`, `CREATE` and `CONSTANT` write these three pseudo tokens directly. They are not in the `PRIMS` table at all, but they are three case bodies. |

**35 + 2 + 3 = 40 required entries.** P20's 40-primitive set was therefore **exactly right, not optimistic**
— the probe's own failure criterion ("the layer needs > 50") does not fire.

**Q: So the 61-vs-40 discrepancy was the primitive set — 824 B, was it?**
It is bigger. Measured here: **A − B = 4934 − 3776 = 1158 B for 26 removed entries, 44.5 B each.** P20's
824 B estimate came from a different build (unpaged, 32-bit tokens, different code shape); the number on
*this* engine is 1158 B, and it is the largest single lever the project has found.

**Q: Does C fit?** **The engine does; the machine does not.** C is **3412 B by `.text + .rodata` (3424 by
`.bin − control`) — 26 B *under* 3438** — and the **real 7856 B link still fails**:
`address 0x1fd8` = **8152 needed, 296 B over**. Both facts are true and they are not in conflict: the engine
is not the only thing in the pool.

**Q: Why does the real link still fail with the engine under target?**
Because **3438 B was never the engine's ceiling.** From C's own link: 8152 needed − 3412 engine = **4740 B of
fixed lines** (frames 2048, page table + LRU 250, rings + mailbox 600, task records 420, VM state 136, line
buffer 128, `mem` 908, startup/peripherals/seed ~250). `7856 − 4740 = 3116 B`. The 3438 figure implies fixed
lines of `7856 − 3438 = 4418 B`, i.e. **322 B less than they actually are**. So:

| engine ceiling | value |
| --- | --- |
| implied by the 3438 target | 3438 B |
| implied by C's measured link (8152 − 3412) | **3116 B** |
| C's engine | 3412 B → **296 B over the real ceiling** |

The remaining 296 B is not code shape and not the primitive set any more. It is 26 dead primitive bodies'
worth of margin that is not there.

**Q: Is 40 the floor?** Not proven, but it is close: of the 40, the layer's text drives 35 and 5 are
compiler-emitted. Nothing left is droppable without deleting a Forth word the layer defines
(`'`, `.\"`, `CONSTANT`, `I`, `J`, `KEY?`, `W@`, `W,`, `W!`, `C,`, `LITERAL`, `U<`, `U/MOD`, `XOR`,
`INVERT`, `LSHIFT`, `RSHIFT`, `UNLOOP`, `(` — all already gone in B; see the table in §2.2) or the `;`/number
mechanism itself.

## 2. Evidence

### 2.1 Commands (all under `timeout`; builds in tmux with `nice -n 10`; every output inside this directory)

```sh
cp ../../P30-code-structure/src/{uforth.c,ulp_stubs.c,ulp_p30*.ld} src/       # then ulp_p31*.ld
cp ../../../P26-minimal-layer/{boot_min.fs,img_last.h} ../../P26-minimal-layer/os_*.fs src/
timeout 20 python3 p31_gen.py                       # PRIMS + switch -> p31_prims.inc, p31_cases.inc
timeout 20 gcc -DP31_TRACE -DHOST -DMEMSZ=8192 -DSD=16 -DTIBSZ=128 -O1 -std=c99 \
      -o artifacts/p31_host src/uforth.c
timeout 20 artifacts/p31_host src/boot_min.fs src/os_tasks.fs src/os_events.fs src/os_repl.fs \
      src/os_introspect.fs src/os_device.fs 2> artifacts/p31_host_trace.txt
timeout 20 python3 derive.py                        # trace -> src/p31_required.defs (+ dropped list)
for V in A B C; do timeout 300 nice -n 10 python3 p31_build.py $V 908; done    # logs/p31_<V>.log
timeout 20 riscv32-esp-elf-size -A artifacts/p31_<V>_diag.elf                  # section columns
timeout 20 riscv32-esp-elf-nm --size-sort -S artifacts/p31_<V>_diag.elf        # artifacts/p31_<V>_nm.txt
```

`run.sh` sources IDF's `export.sh`; `p31_build.py` takes compile and link flags from P20's own generated
`ulp_main` build (`compile_commands.json` + `build.ninja`) exactly as P29/P30 do. Each variant attempt links
the **real 7856 B script first** and then the 12000 B diagnostic script, so "fits" is a link result.

### 2.2 What B removes, and what dies with each — one line each

Derived by `derive.py` from the trace: the 26 `PRIMS` entries the layer never resolves. Checked by hand
against the prelude and layer text for the "what breaks" column.

| removed | cost≈ | what breaks |
| --- | --- | --- |
| `'` `TICK` | 44 B | nothing in the layer — every compile-time xt is `[']`, which survives. The interactive `' X` idiom and the `(' GOTKEY)` posting in `os_repl.fs` (a comment, not code) have no primitive. |
| `(` `PAREN` | 20 B | nothing: every prelude/layer comment is `\`, which survives. No block comments. |
| `.\"` `DOTQ` | 30 B | nothing: no layer word prints a string (prompt is `62 EMIT`, errors are `?ERR` + `EMIT`). No compile-time or runtime string printing. |
| `(.\")` `PDOTQ` | 20 B | `DOTQ`'s compiled body, removed with it — and then `V_XSTR` is never set, so nothing can dispatch to it either. |
| `ADC@` | 20 B | nothing: `os_device.fs` says "`ADC@` ... not in R1–R8 and not re-defined here". No analog read at any level. |
| `C,` | 16 B | nothing: no layer word compiles a byte (`boot_min.fs` uses `,`); byte data can no longer be compiled into the dictionary. |
| `CONSTANT` | 30 B | nothing: `os_tasks.fs` builds every variable from `CREATE` + `0 ,` ("the 40 has no VARIABLE"). `n CONSTANT X` is gone. |
| `FAULT` | 20 B | nothing in the layer; the *injected* fault path P27/P29 used to prove page-fault resume is gone. The page-in retry inside the fetch loop (the thing being tested) stays. |
| `GPIO!` | 30 B | no prelude word writes a pin — `POLL-EVENTS` only reads one (`PIN @ GPIO@`). **R1's actuator write has no primitive left**; it comes back at ~30 B when a word actually toggles a pin. |
| `I` | 10 B | nothing: `POLL-EVENTS` and `SLEEP-TICKS` read their counters from layer variables (`RN @`, `TICK @`). No loop index is available to any Forth word. |
| `INVERT` | 6 B | nothing: `boot_min.fs` derives `NEGATE` as `0 SWAP -` and `NOT` as `0=`; `INVERT` is named nowhere. |
| `J` | 10 B | nothing: the layer has no nested `DO .. LOOP`. Outer-loop index unavailable. |
| `KEY?` | 16 B | nothing: `os_repl.fs` says "the 40-word set dropped `KEY?`" and guards with its own `KIN` flag before ever calling `KEY`. `QUIT` is unaffected. |
| `LITERAL` | 16 B | nothing: `boot_min.fs` compiles xts with `['] x ,`. The `[ ... ] LITERAL` idiom is gone. |
| `LSHIFT` | 10 B | nothing: no layer word shifts. |
| `MS` | 16 B | nothing: `os_device.fs` excludes it by name; `SLEEP-TICKS` waits by yielding until `TICK` has advanced, not by `MS`. |
| `PAUSE` | 30 B | `os_tasks.fs` **defines** `PAUSE` as `YIELD`, shadowing the primitive, so the token is never compiled. With the native `PAUSE` gone, a task cannot yield *through the engine switch* — P26's `YIELD` rotates bookkeeping only, which `os_tasks.fs` already warns about. |
| `RSHIFT` | 10 B | nothing: no layer word shifts right. |
| `U/MOD` | 40 B | nothing: `/MOD` (signed) is what `/`, `MOD` and `2/` use; unsigned division is named nowhere. |
| `U<` | 16 B | nothing: `boot_min.fs` builds `<` (signed) and `>` as `SWAP <`. No unsigned compare. |
| `UNLOOP` | 6 B | nothing: no `EXIT` out of the middle of a `DO .. LOOP`. |
| `W!` | 16 B | nothing: `boot_min.fs` carries the GUARDRAIL that `W!` was trimmed and patches 4-byte operands with `!`; no 2-byte store anywhere. |
| `W,` | 8 B | nothing: same — no 2-byte compile step. |
| `W@` | 12 B | nothing: `os_introspect.fs` rebuilds the 2-byte header link from **two `C@`** precisely because `W@` is absent; `WORDS` keeps working. |
| `WAKE` | 16 B | nothing: the layer polls a pin (`POLL-EVENTS`) instead of waiting on a wake source. No word dies. |
| `XOR` | 16 B | nothing: no layer word xors. |

Two removals are *not* "nothing breaks" and are flagged rather than smoothed over: **`GPIO!`** (R1's actuator
write has no primitive) and **`PAUSE`** (no yield through the engine switch). Both are the layer's own
choice — it never writes a pin and it re-defines `PAUSE` — but they are scope facts, not byte savings.

### 2.3 The derivation is from the interpreter, and the symbol diff says why it had to be

The stack's alternative, diffing the two existing ELFs, was run and does not answer the question:

```sh
riscv32-esp-elf-nm --defined-only --print-size --size-sort P20/artifacts/ulp_main_A.elf | awk '{print $NF}' | sort > p20_syms.txt
riscv32-esp-elf-nm --defined-only --print-size --size-sort P29/artifacts/ulp_main_p29_diag.elf | awk '{print $NF}' | sort > p29_syms.txt
comm -13 p20_syms.txt p29_syms.txt
-> cmd_ring cur halt_status mailbox memcpy memset out_ring pl_halt ptab_lru_reserve rd16_paged tsk
   vm_depth vm_enter vm_faults vm_faults_left vm_live vm_max_depth vm_next_ready vm_sw_fault
   vm_sw_first vm_switch vm_switches vm_sw_pause vm_sw_taskexit vm_task_leave
```

Both images keep every primitive body **inside one function** (`run()` in P20, `vm_enter` in P29), so the
added and removed primitives have **no symbols to diff** — the diff names only the added *machinery* (paging,
the `VM`, task records, libgcc). The primitive set can only come from the dictionary, which is why the
requirement was taken from `find()` and not from `nm`.

### 2.4 The instrumented hook is inert in the shipping build

`P31_TRACE` guards the whole trace: three globals, one `#ifdef` inside `find()`, and two statements in the
host-only `main`. Variant A compiles with no defines and reproduces 4934/4948, `vm_enter` 2380, `memcpy` 232,
`memset` 168 **and the same link address `0x25dc` as P29/P30** — so the mechanism did not perturb the
baseline it is calibrated against.

## 3. Verdict

**C fits the engine target and does not fit the machine. The 296 B gap requires a scope decision, and the
three options are priced below, not chosen.**

On the probe's own criteria:

* *the required primitive set derived from what the layer and prelude actually name* — **met**: 35 names
  resolved by the engine's own `find()`, + `EXIT`, `LIT`, `(DOCOL)`, `(DOVAR)`, `(DOCON)` for stated
  mechanical reasons, **= 40**.
* *A reproduces 4934* — **met exactly**, including the link address.
* *C's engine at or under 3438 **with a successful real link**, or the exact remaining gap* — the first half
  holds (**3412 B, −26 B**), the link does **not**: **8152 needed of 7856, gap 296 B.**
* *no array vanished* — **met for A, B and C**.

Measured cost of the three options, from C's own image (`artifacts/p31_C_nm.txt`, `.bss` and `.text`):

| option | measured cost it removes | residual against 296 B |
| --- | --- | --- |
| **(i) drop paging from the first machine** | `pg_load` 108 + `rd16_paged` 60 + `resolve` (inlined, 0 B of symbol) = **168 B of engine**, plus **2298 B back to the pool** (`frm` 2048, `ptab` 16, `ptab_lru_reserve` 234) → region need 8152 → **5854** | **fits with ~2170 B spare**; gives up the 4×512 B frames, the 16-bit paged fetch, and `MEMSZ` becomes directly addressed |
| **(ii) two tasks** | `tsk` 420 → 280 = **140 B** (`NTSK=2`) | **156 B still short** |
| **(iii) smaller prelude** | `mem` 908 → **620** B is the floor that still holds the measured 676 B resident need, so at most **232 B** (`MEMSZ` 908 → 676) | **64 B still short** |

Combinations are priced for the operator, not decided: **(ii) + (iii) = 372 B > 296 B**, so two tasks plus a
prelude that fits `MEMSZ` 676 would close the gap with 76 B spare and keep paging. **(i) alone** also closes
it, with room, and loses the thing this project spent P03/P16/P19 proving.

**The plain statement the probe asked for:** *C's engine is 3412 B, under 3438 — and the 7856 B machine still
does not link, by 296 B, because the fixed budget lines are 4740 B and the engine's real ceiling is 3116 B.
The 3438 target was 322 B optimistic.* The budget phase does not end here; it ends when one of the three
options above is chosen.

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.3 — the required primitive set, the engine size, and whether it fits

```
**How many primitives does the layer need, and does the machine fit? (`P31`)** Exactly **40** — derived
from the engine's own name lookups, not from a guess: a host build of the shipping interpreter with `find()`
instrumented loaded `boot_min.fs` + all five P26 layer files and resolved **35** primitive names; `EXIT` (from
`;` via `V_XEXIT`), `LIT` (from numbers/`[']` via `V_XLIT`) and the three pseudo tokens `(DOCOL)`/`(DOVAR)`/
`(DOCON)` are emitted by the compiler without a lookup, so 35 + 5 = 40. The other **26 of the 63 table
entries are dead** and cost **1158 B** (44.5 B per entry inside the switch): baseline **4934** → required set
**3776** → plus P30's hand VM copy and 4-word zeroing **3412** (`.bin − control` 3424, i.e. **26 B under the
3438 target**). **The real 7856 B link still fails: 8152 needed, 296 B over.** The reason is that the target
was optimistic: C's own image shows **4740 B of fixed lines** (frames 2048, page table + LRU 250, rings and
mailbox 600, task records 420, VM state 136, line buffer 128, `mem` 908, startup ~250), so the engine's real
ceiling is **3116 B**, not 3438. The primitive set is settled at 40 and worth 1158 B; the last 296 B is a
scope decision, priced in `probes/P31-primitive-set.md`: drop paging (−168 B engine, −2298 B pool, fits with
~2170 spare), two tasks (−140 B, still 156 short), or a prelude that fits `MEMSZ` 676 (−232 B, still 64
short) — or two tasks *and* the smaller prelude (−372 B, fits by 76 B, paging kept).
```

### 4.2 `docs/JOURNAL.md` — the resolution of the 61-vs-40 discrepancy

```
**The layer needs 40 primitives, and 40 primitives is still 296 B short.** The 61-vs-40 discrepancy that
P29/P30 left open is closed, and it was not a guess: P31 built the shipping interpreter for the host with
`find()` instrumented, loaded `boot_min.fs` and the whole P26 layer through it, and let the engine record
every primitive it resolved — 35 names in one clean run. Five more are required without a lookup because the
compiler emits their tokens directly (`;` writes `EXIT`, numbers and `[']` write `LIT`, `:`/`CREATE`/
`CONSTANT` write `(DOCOL)`/`(DOVAR)`/`(DOCON)`); that is 40, exactly P20's set, so P20 was right and the
shipping build had been carrying 26 dead bodies. Dropping them is worth **1158 B** (4934 → 3776), 44.5 B
apiece, the largest single lever in the project. P30's hand VM copy and unrolled zeroing add their usual
**−364 B** on top (both libgcc symbols absent), landing at **3412 B — 26 B under the 3438 target** — and the
machine **still does not link**: 8152 B needed of 7856, **296 B over**. The target itself was the error: the
fixed budget lines are 4740 B, so the engine's real ceiling is 3116 B, i.e. the 3438 figure assumed 322 B of
budget that does not exist. Every remaining lever is a scope decision and none is taken here: drop paging
from the first machine (−168 B of engine, −2298 B of pool, fits with ~2170 B spare), two tasks (−140 B, 156
short), a prelude that fits `MEMSZ` 676 (−232 B, 64 short), or two tasks plus that prelude (−372 B, fits by
76 B). The primitive set is no longer a lever; the pool arithmetic is.
```

### 4.3 `probe/EVIDENCE.md` — the three-variant table and the required set (for the record)

```
P31 — primitive set derived from the engine's own lookups (host build, find() trace):
REQUIRED 40: !  ( +LOOP) (DO) (LOOP) * + , - /MOD 0= 0BRANCH : ; < >R @ AND BRANCH C! C@ CREATE
             DROP DUP EMIT EXECUTE GPIO@ KEY OR OVER R> ROT SWAP TYPE [']
             + EXIT, LIT (compiler-emitted tokens) + (DOCOL), (DOVAR), (DOCON) (pseudo tokens)
DEAD 26:     ' ( ." (.") ADC@ C, CONSTANT FAULT GPIO! I INVERT J KEY? LITERAL LSHIFT MS PAUSE
             RSHIFT U/MOD U< UNLOOP W! W, W@ WAKE XOR

variant  entries  engine (sections)   .bin − control   needed of 7856   real link
A        63+3     4934 (4670+264)     4948             9692             FAIL, 0x25dc, 1836 over
B        37+3     3776 (3616+160)     3788             8516             FAIL, 0x2144, 660 over
C        37+3     3412 (3252+160)     3424             8152             FAIL, 0x1fd8, 296 over
```

## 5. Follow-ups

1. **Stop treating the primitive set as the lever.** It is settled at 40 and it is worth 1158 B, and it has
   now been taken. The engine is 3412 B and the shortfall is 296 B of *pool*, not of code. Any further
   primitive-cutting reaches into words the layer actually defines (`>`, `=`, `2/`, `NEGATE`), i.e. into the
   prelude's own bytes, which move from `mem[]` to `.text` — a wash at best.
2. **Re-derive the budget with the real fixed lines.** `3438 = 7856 − 4418` used a 4418 B non-engine figure;
   the linked image says **4740 B**. Whatever line is wrong (frames, LRU reserve, mailbox, startup), §4.3's
   budget table should be recomputed from `8152 − 3412` rather than from the target. This probe did not
   attempt to find which line is off.
3. **Do not re-run the out-of-line experiment with 40 primitives.** P30 showed out-of-lining is +1160 B at 62
   bodies because each function pays a prologue; at 40 bodies `vm_enter` is already 1354 B, so the crossing
   point is even further away.
4. **`-Oz` was not tried on C.** P30's follow-up 4 asked for it on A; C is now the build worth trying it on
   (`riscv32-esp-elf-gcc` supports it, and the switch is exactly the shape `-Oz` optimises). One build.
5. **`GPIO!` and `PAUSE` are load-bearing for R1, not for the layer as written.** Both are absent from the
   required 40 because no prelude word uses them. When a layer word actually writes a pin or yields through
   the engine, they come back at ~30 B each — remember that in the budget, and do not record the 40 as
   permanently free of them.

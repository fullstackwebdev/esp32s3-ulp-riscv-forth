# P24 — Does the OS layer fit, and what does the paged hot set really look like?

| | |
| --- | --- |
| Result | **PASS on the measurement, FAIL on the design as specified.** The OS layer **compiles** against P20 variant C's 40 primitives — 80 definitions, **3824 B with headers / 3044 B headerless**, **47.8 B/definition with headers, 38.0 B headerless** — which is **40.7× the 94 B of resident room P22 left** and **7.5 frames** of paged storage. A 512 B frame holds **10.0 of these definitions** (measured: 80 definitions over 8 pages, min 3 / max 15 per page). The hot set does **not** fit 4 frames: the **idle event loop touches 6 pages** and **thrashes on every pass** (≥ 864 µs/pass of page fetch alone); a line calling three OS words touches **8 pages**. Compiling one definition is the only 3-page working set that stays put. Two of the words the brief requires (**`KEY?`, `MS`**) and three the layer needs (**`DEPTH`, `W@`, a context-switch primitive**) were trimmed out of the 40-primitive set and **cannot be reconstructed in Forth** — the layer compiles by owning their state and is honest about the reach it lost. |
| Runs on | **host only** (`gcc -DHOST`, board untouched, no serial device opened) |
| Time box | one run, 15 min hard cap — **overrun**: ~19 min, spent on three compile errors that are themselves findings (§1.2) |
| Sources | `uforth.c` = **P20 variant C verbatim** (copied, byte-identical), `ulp_stubs.c` = P20 C's, `boot_min.fs` = **P22's 32-bit prelude** (73 lines, 78 definitions, 1716 B — reproduces P22's measured prelude exactly). Layer: `os_tasks.fs`, `os_events.fs`, `os_repl.fs`, `os_introspect.fs`, `os_device.fs`. `measure.py` = header walk + working-set pages. |

## Record

| Group | definitions | bytes with headers | headerless bytes |
| --- | --- | --- | --- |
| tasks | 39 | 1772 | 1380 |
| events | 20 | 1124 | 908 |
| REPL | 9 | 376 | 300 |
| introspection | 8 | 408 | 348 |
| device words | 4 | 144 | 108 |
| **total** | **80** | **3824** | **3044** |

Boot prelude for reference: 78 definitions, 1716 B (with headers), measured — identical to P22.
"Headerless" = code field + body only (P22 resolution A's resident split); the paged name directory
adds `8 + name` bytes per definition on top (780 B of headers in this layer ⇒ 859 B of directory).

---

## 1. Answers

**Q: Does the layer compile against the shipped 40 primitives?**
**Yes — and it cost three fix-up rounds that say something about the set.** `gcc -DHOST -DMEMSZ=8192`
builds the engine clean (one pre-existing unused-function warning), and the five group files interpret
in order. Staged `HERE` after each file: 1716 → 3488 → 4612 → 4988 → 5396 → **5540 B**. No definition
is empty: every word has a body that a future context switch or the REPL actually calls.

**Q: How big is the layer, per group?**

| Group | defs | with hdrs | headerless | B/def (hdrs) | B/def (headerless) |
| --- | --- | --- | --- | --- | --- |
| tasks | 39 | **1772** | 1380 | 45.4 | 35.4 |
| events | 20 | **1124** | 908 | 56.2 | 45.4 |
| REPL | 9 | **376** | 300 | 41.8 | 33.3 |
| introspection | 8 | **408** | 348 | 51.0 | 43.5 |
| device | 4 | **144** | 108 | 36.0 | 27.0 |
| **total** | **80** | **3824** | **3044** | **47.8** | **38.0** |

**Q: What fits in one 512 B frame?**
Measured by walking which page each definition's code field lands in: **10.0 definitions/frame on
average** (80 defs / 8 pages), per page 3–15 definitions, 324–624 B of live bytes. From the ratios:
**10.7 defs/frame with headers, 13.5 headerless**. But this is the wrong comfort: `POLL-EVENTS` alone
is **320 B** and `EMIT-EVENT` 156 B, so "10 definitions" is *ten small constants*, not *ten words you
would call*. An average-sized word is ~48 B and the largest are ~6× that.

**Q: The three working sets, with fault counts (4 frames, 512 B each, LRU):**

| Working set | distinct pages | first pass | steady state |
| --- | --- | --- | --- |
| (a) idle event loop (`POLL-EVENTS` → `WAKE-MASK`/`WAKE-1`/`TICK+` → `YIELD` → `NEXT-TASK`, + ring and pool data) | **6** (pages 4–9) | **6 faults = 864 µs** | **thrash**: 6 pages, 4 frames ⇒ ≥ 2 evictions per pass, so **6 faults every pass** |
| (b) one line calling three OS words (`10 SLEEP-TICKS TASKS .S`) | **8** (pages 0, 4–10) | **8 faults = 1152 µs** | **thrash** — and it drags in page 0 (the system variables `HERE`/`STATE`) |
| (c) compiling one definition | **3** (pages 0, 1, 10) | **3 faults = 432 µs** | **stable, 0 faults/frame** — page 10 is `HERE`, 0 and 1 are the system variables and primitives |

The most-used path is (a), the idle loop: **6 page fetches before it does anything, and again on every
iteration**. At P16's 144 µs lower bound that is **≥ 864 µs of pure fetch per loop pass**, before
`POLL-EVENTS` reads a single event.

**Q: Can the 94 B resident room hold any of it?**
**No.** The layer is 3824 B = **40.7× the spare**; the smallest definition in it is
`#DEAD`/`#FREE`/`#SLEEP` at **16 B each**, so 94 B holds **5 of the 20 16-byte constants/variables and
not one executable word**. Even the smallest *group* (device words, 144 B) is 1.5× the whole spare, and
one 32-byte task record × 3 tasks is 96 B — more than the spare by itself. There is no version of this
layer that is resident. §12's "OS layer < 512 B ⇒ permanently resident in frame 0" branch is **not**
taken by a factor of 7.5.

**Q: What is the first-call fault cost for the most-used path?**
Idle event dispatch: **6 faults × 144 µs = 864 µs** to enter, and because the working set is 6 pages
against 4 frames it never warms: **the loop pays it every pass**. On a 1 ms tick that is 86 % of the
budget spent paging.

**1.1 What the layer actually contains (`os_*.fs`, no stubs)**

* tasks — `TASK` (record + 192 B stack from `ALLOT`, queued), `YIELD` (round robin + `TICK+` + wake
  scan), `PAUSE`, `SLEEP-TICKS`, `STOP` (block on mask), `TASKS`, plus the 32 B record
  (`T>NEXT DSP RSP IP STATE WAKE WAIT USER`), 5 states, `#MAXTASK`, `#STK`, a 128 B `TASK-POOL`,
  `NEXT-FREE`, `NEXT-TASK`, `WAKE-1`, `WAKE-ALL`, `TICK+`, `T-STATE!`.
* events — 8-slot ring of 12 B records (`EV-RING`), `EMIT-EVENT`, `POLL-EVENTS` (a full drain pass,
  returns the count), `ON-GPIO` (mask + xt), `WAKE-MASK` (releases blocked tasks), `EV-GPIO-DO`,
  three event kinds, `KIN` (key-pending).
* REPL — `QUIT` as a task body (`PROMPT → POLL-EVENTS → KEY → OK? → YIELD`, forever), `KEY?`,
  `PROMPT`, `CR`, `SPACE`, `.CODE`, `.ERR`, `OK?`, `ECHO`. `TYPE` is the primitive and is not
  redefined.
* introspection — `WORDS` (walks the header chain through `LINK@`), `.NAME`, `.`, `U.`, `.DIGIT`,
  `?`, `.S`.
* device — `MS`, `PIN?`, `PIN!`, `PIN-WAIT`.

**1.2 The three compile failures are the finding** (each is a GUARDRAIL in the source):

1. `(` is **not** in the 40-primitive set, so every `( -- t )` stack-effect comment was looked up as a
   word and aborted the line: `os_tasks.fs:44: error`. A Forth with no `(` has no stack-effect
   comments — the layer carries its comments in `\` only.
2. `W@` was trimmed, so the 2-byte header link must be rebuilt from two `C@` (`LINK@`). Any `WORDS`
   that reads one byte walks into the name.
3. **No `ALLOT`, no `VARIABLE`, no `DOES>`**: cells are claimed by moving `V_HERE` (`HERE + 4 !`) and a
   variable is `CREATE 0 ,`. Every task stack and both rings in this layer are allocated that way.

**1.3 The primitives that are genuinely missing** (the layer compiles around them, but they bound R3/R4)

| Missing primitive | trimmed in | what the layer had to do instead | cost to re-add |
| --- | --- | --- | --- |
| `KEY?` (pl_hw op 5) | P20 C | layer owns `KIN`; the key event sets it, `KEY?` reads it — **no way to ask the platform** | **12 B dictionary** (measured: 4-char primitive = 8 B header + 4 B cf) + hook call in `.text` |
| `MS` (pl_hw op 3) | P20 C | `MS` advances the layer's own `TICK` and yields — **not a hardware delay** | 12 B + `.text` |
| `WAKE` (pl_hw op 4) | P20 C | sleep is a compare against `TICK`; nothing can put the ULP to sleep | 12 B + `.text` |
| `DEPTH` | never in the set | `.S` prints TOS non-destructively; **it cannot print the stack** | 12 B + `.text` |
| `W@` | P20 C | `LINK@` = two `C@` and a `256 *` (4 B of body per call site) | 12 B + `.text` |
| context switch (`DSP@`/`RSP!`/`IP!` or `SAVE`/`RESUME`) | never in the set | `TASK` fills `dsp`/`rsp`/`ip` fields, but sp/rsp are C statics — **Forth cannot save or restore them** | engine work, not a table entry |

The finding: **the layer is 3824 B and it still cannot switch tasks or ask for a key.** The 40-primitive
trim bought 824 B of engine (P20) and cost R3/R4 their three cheapest primitives; re-adding `KEY?`,
`MS` and `WAKE` is **36 B of dictionary** — the trim was not worth those 36 B.

---

## 2. Evidence

### 2.1 Commands (all under `timeout 30`, host only, nothing outside this directory)

```
gcc -DHOST -DMEMSZ=8192 -O1 -std=c99 -Wall -Wextra -o uforth_p24 uforth.c
./uforth_p24 boot_min.fs                                  -d img_last.h   # image: 1716
./uforth_p24 boot_min.fs os_tasks.fs                      -d img_last.h   # image: 3488
./uforth_p24 boot_min.fs os_tasks.fs os_events.fs         -d img_last.h   # image: 4612
./uforth_p24 boot_min.fs ... os_repl.fs                   -d img_last.h   # image: 4988
./uforth_p24 boot_min.fs ... os_introspect.fs             -d img_last.h   # image: 5396
./uforth_p24 boot_min.fs ... os_device.fs                 -d img_last.h   # image: 5540  ← all five
python3 measure.py                                                        # the tables above
```

`MEMSZ` is 8192 only because the host 40-word engine has no paging pressure; `dictionary bytes` is what
is compared, and the host build reproduces P22's prelude number (1716) exactly, which calibrates the
technique before it is used on the layer. **The layer does not fit a real machine's `MEMSZ = 1188`** —
5540 total needs 5540 B of Forth memory; that is the headline, not a detail.

### 2.2 Where the bytes go

* 780 of 3824 B (20 %) are headers — lower than the 44 % the prelude shows, because this layer is
  constants- and variable-heavy (`#FREE`, `T>NEXT`, `EV-H`, …) whose names are short.
* Runtime allocation is *not* in the 3824 B: the 128 B `TASK-POOL` is compiled in, but each `TASK`
  call claims 192 B of stack at run time. Three tasks ⇒ 704 B of dictionary *more* at run time. The
  design's "three tasks is the realistic ceiling" is a 704 B allocation against a 94 B spare.
* `POLL-EVENTS` is the single largest word at **320 B** — 62 % of a frame by itself, and it is in the
  idle path.

### 2.3 What was not measured

No target build: `probe/uforth`'s engine was **not** re-linked for esp32s3 (P22 already gives the
`.text` cost of the primitive set, and the probe is host-only by its own rules). The `+12 B of
dictionary per re-added primitive` is measured from the header walk of the primitives already in the
image; their `.text` cost is bounded by P20's per-primitive measurements, not measured here.

---

## 3. Verdict

**The OS layer compiles and it does not fit.** 3824 B with headers, 3044 B headerless, 80 definitions,
10.0 definitions per 512 B frame, 7.5 frames of storage — against **94 B of resident room**. The three
working sets come out **6 / 8 / 3 pages**: the idle event loop and any line of REPL interaction
**thrash** on 4 frames, compiling does not.

Against the brief's failure criteria:

* **A working set needs more than 4 frames** — *fires, twice* (idle loop 6, typed line 8). The hot set
  does not fit; every interaction faults. This is the **§12 redesign trigger for R3/R4**.
* **The layer does not compile against 40 primitives** — *narrowly does not fire*: it compiles, but
  three of its required words (`KEY?`, `MS`, and any hardware wake) were **replaced by layer-owned
  state** because their primitives were trimmed. `DEPTH` was never there, so `.S` cannot print the
  stack, and no primitive can save/restore sp — the task *books* switch, the task *context* cannot.
* **Total layer < 512 B** — does not fire, by 7.5×.
* **Idle loop faults on every pass** — **fires.** The event loop's own code is 6 pages against 4
  frames; it faults every pass. "Fatal for R3" per the brief, and it is what the numbers say.

What that leaves: the layer is **~4× too big** and its *dispatch* path is **~2 pages too wide**. The
first is a design choice (fewer words, shorter constants, a 32 B task record that costs 8 constants to
address); the second is structural (a cooperative scheduler's round robin inherently walks
queue → task → wake → tick across the dictionary). No amount of header stripping closes a 7.5× gap:
headerless the layer is still **5.9 frames**.

---

## 4. Doc deltas (verbatim, `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §6 (Tasks) — append after the words list

> **Measured (P24).** The Forth side of §6 — record accessors, states, pool, `TASK`, `NEXT-FREE`,
> `NEXT-TASK`, `WAKE-1`, `WAKE-ALL`, `TICK+`, `YIELD`, `PAUSE`, `SLEEP-TICKS`, `STOP`, `TASKS` — is
> **39 definitions, 1772 B with headers / 1380 B headerless** (45.4 / 35.4 B per definition). Add the
> events group the same task loop needs (ring, `EMIT-EVENT`, `POLL-EVENTS`, `ON-GPIO`, `WAKE-MASK`):
> **20 definitions, 1124 B / 908 B**. The whole OS layer measured so far is **80 definitions,
> 3824 B / 3044 B** — 40.7× the 94 B left after §4.3, i.e. **7.5 frames of 512 B**. Three `TASK` calls
> additionally claim **192 B of dictionary each at run time**, so the "three tasks" ceiling is a
> **704 B** allocation, not free. And the words in the table above cannot actually switch context:
> `dsp`/`rsp`/`ip` are C statics, so `TASK` fills the record but no primitive can save or restore the
> engine's pointers. A context-switch primitive is required before §6 means anything.

### 4.2 `docs/01-proposal.md` §7 (The interpreter and the dictionary) — append

> **What the layer costs what it asks of §7 (P24).** The trimmed 40-primitive set (P20 C) has no `(`,
> no `W@`, no `ALLOT`, no `VARIABLE`, no `DOES>`: stack-effect comments in parentheses abort the line
> (`os_tasks.fs:44: error`), the 2-byte header link must be built from two `C@`, and every ring and
> task stack has to be claimed by moving `V_HERE` by hand. `WORDS`/`.S` are also partly out of reach:
> no `DEPTH` means `.S` cannot print the stack, and `.S` in this layer prints the top cell only.
> Re-adding `KEY?`, `MS`, `WAKE`, `DEPTH`, `W@` costs **12 B of dictionary each** (measured: 4-char
> primitive = 8 B header + 4 B code field) — 60 B for the lot, i.e. **less than 1.6 % of the layer**,
> and P20's 824 B engine win was not worth losing them.

### 4.3 `docs/01-proposal.md` §10 — R3 and R4, restated

> **R3 — event loop.** Measured (P24): the idle event loop's Forth working set is **6 pages of 512 B**
> against **4 frames**. First pass **6 faults**, steady state **6 faults every pass** — LRU cannot hold
> 6 pages in 4 frames, so the loop pays **≥ 864 µs of page fetch per pass** (P16's 144 µs/fetch lower
> bound). The event loop as specified does not fit and does not warm. **Redesign trigger (§12).**
>
> **R4 — multi-tasking.** Measured (P24): the task group alone is **1772 B** (1380 B headerless), the
> events group **1124 B**, the REPL **376 B**, introspection **408 B**, device words **144 B** — total
> **3824 B** against **94 B** of resident room. A line calling three OS words touches **8 pages**
> (thrash); compiling one definition touches **3** (432 µs, stable). `TASK` cannot switch context
> without a primitive for the engine's sp/rsp/ip. **R4 is not met by this composition and cannot be
> met by trimming headers: headerless the layer is still 5.9 frames.**

### 4.4 `probe/EVIDENCE.md` — new entry

> ### E-0xx — the OS layer compiles, and it is 7.5 frames (P24)
>
> Forth OS layer (tasks, events, REPL, introspection, device words) compiled on the host against P20
> variant C's 40 primitives, over P22's 32-bit prelude (reproduced exactly: 78 definitions, 1716 B).
> **80 definitions, 3824 B with headers, 3044 B headerless, 47.8 / 38.0 B per definition.** Per group:
> tasks 39 defs 1772/1380, events 20 defs 1124/908, REPL 9 defs 376/300, introspection 8 defs
> 408/348, device 4 defs 144/108. **10.0 definitions per 512 B frame** (measured, 80 defs over 8
> pages). Working sets, 4 frames: idle event loop **6 pages ⇒ 6 faults every pass (864 µs, thrash)**;
> a line calling three OS words **8 pages (thrash)**; compiling one definition **3 pages, 432 µs,
> stable**. The layer is **40.7× the 94 B of resident room**; the smallest definition in it is 16 B, so
> 94 B holds five of its twenty 16-byte entries and no executable word. `KEY?`, `MS`, `WAKE` were trimmed
> from the 40-primitive set and are replaced by layer-owned state; `DEPTH`, `W@`, `(`, `ALLOT`,
> `VARIABLE` are absent and had to be worked around; no primitive exists to save/restore the engine's
> stack pointers, so the tasks book-switch but cannot context-switch. Re-adding the five missing words
> costs **60 B of dictionary**.

---

## 5. Follow-ups

1. **Shrink the layer before growing the frames.** 3824 B has ~800 B of obvious fat: 20 entries are exactly 16 B
   (`T>DSP`, `#FREE`, `RUNQ`, `CUR`, `KIN`, …) and together cost **320 B**; collapsing the record
   offsets and state codes into 3 indexed words saves ~250 B; `.CODE`
   /`.ERR`/`OK?`/`ECHO` are REPL convenience. Target < 2048 B before re-measuring the hot set.
2. **Split `POLL-EVENTS` (320 B).** It is 62 % of a frame and on the idle path; a dispatch table in a
   paged frame would move the per-kind branches out of the hot page.
3. **Re-run the working-set count with a real LRU simulation** (this probe counted distinct pages and
   applied the 4-frame rule analytically — `P03f`/`P03`'s simulator is the right tool and would give
   fault counts per 100 passes rather than per design-trace).
4. **Decide the context switch.** Either add `DSP@ !`/`RSP@ !`/`IP@ !` (3 primitives, ~36 B of
   dictionary) or accept that tasks are coroutines driven by the engine's `run()` and restate §6.
5. **Reconsider P20's trim on this evidence**: `KEY?`, `MS`, `WAKE`, `DEPTH`, `W@` = 60 B of
   dictionary against 40.7× overflow. The trim saved bytes in the wrong place.

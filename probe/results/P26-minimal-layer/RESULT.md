# P26 — What is the smallest OS layer that still satisfies R3 and R4?

| | |
| --- | --- |
| Result | **PASS.** The minimal layer that satisfies R3 and R4 as literally written is **22 definitions, 1224 B with headers, 1024 B headerless — exactly the budget, 2.0 frames**, and its **idle event loop touches 3 pages, so with 4 frames it faults 3 times on the first pass (432 µs) and 0 times in steady state.** P24's layer was 3044 B headerless and 6 pages of idle hot set; the requirement's literal content needs **a third of the bytes and one page less than the frame count**. Three groups met their ceilings (tasks 292/300, REPL 188/200, device 0/100); two did not (events 304/250, introspection 240/120) and the reasons are measured, not asserted — introspection cannot be 120 B because `WORDS` must rebuild the 2-byte link without `W@` (36 B) and `.S` cannot print a cell without a decimal printer the 40 primitives do not have (80 B). The layer is still **1024 B exactly** because the device group costs 0 B: `GPIO@`/`GPIO!` are primitives. |
| Runs on | **host only** (`gcc -DHOST`, board untouched, no serial device opened) |
| Time box | one run, 15 min hard cap — **overrun: ~40 min**, 30 of them on the size fight (four rewrites, each one a measurement) and 5 on a stack leak this probe found in its own first draft |
| Sources | `uforth.c`, `ulp_stubs.c`, `boot_min.fs` = **P24's files, copied byte-identical** (the prelude reproduces P22 exactly: 78 definitions, 1716 B). Layer: `os_tasks.fs`, `os_events.fs`, `os_repl.fs`, `os_introspect.fs`, `os_device.fs`. `measure.py` = P24's header walk, extended with per-word bytes, the three workloads, and a `-i`-free group table. `os_tasks_pause.fs` + `img_with_pause.h` = the same layer with `: PAUSE YIELD ;` spelled out, for the 12 B delta. |

## Record

| Group | budget | actual | dropped from P24 |
| --- | --- | --- | --- |
| tasks | ≤ 300 | **292** | task states + `WAKE-1`/`WAKE-ALL`/`STOP` (296 B), free-slot scan `NEXT-FREE`+`NEXT-TASK` (236 B), `TASKS` printer (128 B), 3 of the 4 record fields (24 B/slot), `TICK+` (28 B), `PAUSE` as a word (12 B, shared with `YIELD` per the brief) |
| events | ≤ 250 | **304** (+54) | 12 B event records with payloads + kind dispatch (`EMIT-EVENT` 172 B, `WAKE-MASK` 144 B, `EV-GPIO-DO` 36 B), edge detection, FIFO order. **Kept:** the overflow guard + `DIAG` (44 B) — a clamp would be a lie, and the guard is the only reachable path to the REPL's error report |
| REPL | ≤ 200 | **188** | `PROMPT`/`CR`/`.CODE`/`.ERR`/`OK?`/`ECHO` (192 B) folded into `QUIT` + `?ERR`; `KEY?` (16 B primitive, replaced by the layer-owned `KIN` + one hook word, 32 B) |
| introspection | ≤ 120 | **240** (+120) | `?` (16 B), `.` (44 B), `.DIGIT` (24 B). **Kept and it is the overrun:** `WORDS` 136 B (includes the `W@`-less link walk, 36 B) + `U.` 80 B (no printer in the 40) + `.S` 24 B |
| device | ≤ 100 | **0** | `MS` (36), `PIN?` (20), `PIN!` (12), `PIN-WAIT` (40). `GPIO@`/`GPIO!` are primitives, so R1–R8's two device words cost **0 B of Forth** |
| **total** | ≤ 1024 | **1024** | 3044 B → 1024 B: **2020 B removed, 66 %** |

Per-word, measured from `img_last.h` (headerless; `ALLOT`-reserved data is inside the word that
reserved it):

| tasks (292) | events (304) | REPL (188) | introspection (240) | device (0) |
| --- | --- | --- | --- | --- |
| `ALLOT` 28, `SLOTS` 28 (3×8 B records), `CUR` 8, `TICK` 8, `DIAG` 8, `TASK` 88, `YIELD` 68, `SLEEP-TICKS` 56 | `RING` 20 (4 cells), `RN` 8, `PIN` 8, `PXT` 8, `ON-EVENT` 24, `POST` 116, `POLL-EVENTS` 120 | `KIN` 8, `GOTKEY` 24, `?ERR` 60, `QUIT` 96 | `WORDS` 136, `U.` 80, `.S` 24 | — |

Plus, **outside** the headerless number: 200 B of headers (16 %; P24: 20 %) and, at run time, 64 B of
dictionary per `TASK` call (3 tasks ⇒ **192 B**), the same allocation P24 flagged.

---

## 1. Answers

**Q: How much machine does R3 + R4 literally need?**
**1024 B headerless, 22 definitions**, against P24's 3044 B / 80 definitions. The whole requirement is:
one loop that never blocks and always retires, several tasks taking turns with their own stacks, and
events that get dispatched. That is **three words** (`YIELD`, `POLL-EVENTS`, `QUIT`), a 24 B slot pool,
a 16 B event ring, and the plumbing to get in and out of them. Everything else P24 compiled — five task
states, a free-slot scan, a linked run queue, a 12 B event record with a kind field and a payload, a
task printer, a number-formatting REPL — is *policy the requirement does not state*.

**Q: Does it fit two frames?**
**Exactly: 1024 B headerless = 2.0 frames; 1224 B with headers = 2.4 frames.** The 94 B of resident room still holds almost none of it —
`ALLOT` 28 + `SLOTS` 28 + `CUR` 8 + `TICK` 8 + `DIAG` 8 = 80 B fits, which is **one executable word and
four cells** — so the layer is paged, not resident, but it is paged *thin*.

**Q: Does the idle loop still fault?**
**No.** The idle path (`QUIT` → `POLL-EVENTS` → `POST`/`EXECUTE` → `YIELD` → `SLEEP-TICKS`) plus its
data (`TICK`, `CUR`, `SLOTS`, `RING`, `RN`, `PIN`, `PXT`, `KIN`, `DIAG`) is **3 pages — 3, 4 and 5** —
against 4 frames. First pass **3 faults (432 µs)**, then **0 faults per pass**. P24 measured 6 pages and
6 faults every pass.

**Q: The three workloads (4 frames, 512 B each, LRU):**

| Workload | pages | first pass | steady state |
| --- | --- | --- | --- |
| (a) idle event loop | **3** (3–5) | 3 faults = 432 µs | **0 faults/pass** |
| (b) a line calling three OS words (`10 SLEEP-TICKS YIELD .S`) | **4** (0, 3–5) | 4 faults = 576 µs | **0** |
| (c) compiling one definition | **3** (0, 3, 5) | 3 faults = 432 µs | 0 |

Page 0 is the system variables (`V_STATE`=0, `V_HERE`=4, `V_LATEST`=8); page 5 is `HERE`. (b) is exactly
one page over the idle set and fits **because** the idle set is 3 and not 4: the REPL's number printer is
the only extra and it lands on a page the loop already holds. At P24's size the same line was 8 pages.

**Q: What is *not* in this layer, and is the shortcut honest?**
Every cut is a *removed word*, not an empty one. The load order is unchanged, no `:` body is empty or a
stub, and no word is defined that nothing calls. Four places deserve naming:

* **`PAUSE` is `YIELD`.** The brief says "`PAUSE` (shared with `YIELD` if possible)", so the layer does
  not define it; a `: PAUSE YIELD ;` alias is **12 B** and is kept in `os_tasks_pause.fs` as the measured
  evidence. With the alias the layer is **1036 B headerless / 1244 B with headers** (`img_with_pause.h`,
  measured: tasks 304 instead of 292), i.e. 12 B over the headerless budget and 2.02 frames. That is the only 12 B between this layer and the number.
* **No task states.** A sleeping task is scheduled every round and re-yields; `SLEEP-TICKS` compares the
  tick. There is no `blocked` and no `dead`. This is a real semantic loss (a sleeping task burns a slot,
  and `STOP`/`WAKE-MASK` are gone) and it is the largest single saving: 296 B of P24 state machinery.
* **Nothing can actually switch context.** `TASK` fills `[xt][sp]` and `YIELD` rotates `CUR`; `dsp`,
  `rsp` and `ip` are C statics and no primitive in the 40 can save or restore them. P24 found this and it
  is unchanged: **R4's "several tasks taking turns" is true of the books and false of the machine.** The
  24 B slot pool and the 192 B of run-time stacks are what a future primitive would switch *between*.
  This is the one claim in this probe that a byte count cannot make true.
* **The ring holds handler xts, not events with payloads.** 4 cells, LIFO drain, no kind byte: dispatch
  is `@ EXECUTE`. A full ring drops the event and sets `DIAG = 1` — the only path that reaches the REPL's
  error report, so the error path is reachable instead of decorative.

**1.1 The one bug this probe found in itself** (worth more than the byte count)
The first draft's `YIELD` left the new slot number on the stack, and `SLEEP-TICKS` used `OVER` to reach
its wake time: **one extra cell per iteration until the data stack wrapped.** It compiles, it passes the
"no error" test, and it only misbehaves at run time — `SLEEP-TICKS` would corrupt the stack after 16
passes. Fixed by making `YIELD` stack-neutral (`GUARDRAIL` in `os_tasks.fs`). Every word in the final
layer was then traced by hand for stack neutrality: `ALLOT`, `TASK`, `YIELD`, `PAUSE`, `SLEEP-TICKS`,
`ON-EVENT`, `POST`, `POLL-EVENTS`, `GOTKEY`, `?ERR`, `QUIT`, `WORDS`, `U.`, `.S`.

**1.2 What was not measured**
Nothing was executed: `QUIT` is an infinite loop and the host build has no way to run a bounded instance
of it without adding a hook that would not exist on the chip. So **"never blocks and always retires" is
verified by inspection, not by execution**: the only blocking primitive in the loop is `KEY`, and it is
reached only under `KIN @ IF` — i.e. only when the layer already owns a pending key (`POST` from the
platform's key hook). Fault counts are the P24/P16 analytic model (distinct pages + the 4-frame rule),
not an LRU simulation; P24's follow-up 3 is still open.

---

## 2. Evidence

### 2.1 Commands (all under `timeout 30`, host only, nothing outside this directory)

```
gcc -DHOST -DMEMSZ=8192 -O1 -std=c99 -Wall -Wextra -o uforth_p26 uforth.c   # 1 pre-existing warning
./uforth_p26 boot_min.fs os_tasks.fs os_events.fs os_repl.fs \
             os_introspect.fs os_device.fs -d img_last.h    # image: 2940 of 8192 (prelude 1716)
./uforth_p26 boot_min.fs os_tasks_pause.fs os_events.fs ... -d img_with_pause.h   # 2960
python3 measure.py                 # the tables above, from img_last.h
python3 measure.py img_with_pause.h   # tasks 304 / total 1036: the 12 B PAUSE delta
```

`MEMSZ=8192` only because the host engine has no paging pressure; the number compared is dictionary
bytes, and the prelude reproduces P22's 1716 B exactly, which calibrates the technique before it is used
on the layer.

### 2.2 Every size fight is in the table above

Four rewrites, each driven by a measurement, in this order: 1112 → 1056 → 1028 → 1024 headerless.

* **1112 → 1056:** inline `LINK@`/`.NAME` into `WORDS` (−24; each is one caller and each costs 4 B of
  code field plus 4 B of call token), inline `SLOT`, make `?ERR` report without a leading `SPACE`.
* **1056 → 1028:** `3 MOD` instead of `3 AND` for the pool index (AND yields 0..3 and slot 3 runs off a
  3-slot pool), and the `WORDS` name print restructured to `2 + DUP C@ 31 AND SWAP 1 + SWAP TYPE` (−8).
* **1028 → 1024:** `YIELD` made stack-neutral, which removed `SLOT` from `YIELD`, `DROP` from `QUIT`,
  and let `SLOT` be inlined — but the mask/`MOD` arithmetic paid most of it back.
* The last 12 B (`PAUSE` as a word) were **not** taken; they are in `os_tasks_pause.fs`.

### 2.3 Where the bytes go

* **5 words are 54 % of the layer:** `WORDS` 136, `POLL-EVENTS` 120, `POST` 116, `QUIT` 96, `U.` 80 =
  548 B. Nothing else is over 88 B. P24's fat was 20 constants at 16 B each plus a 32 B record: that is
  gone, and what is left is *code*, which is why further cuts now cost semantics rather than fat.
* **46.5 B headerless per definition** (P24: 38.0). The average went **up**, because the layer is no
  longer 80 small words: it is 22 words of which 5 are real programs. "Definitions per frame" has stopped
  being a useful unit at this size — bytes per *word you would actually call* is the honest one.
* **40 B of the 1024 is data** (`SLOTS` 24 + `RING` 16). The rest is code field + tokens.

---

## 3. Verdict

**The machine can afford R3 and R4 as written, and this layer is what they cost: 1024 B headerless,
2.0 frames, 3 pages of idle hot set, 0 faults per pass.** Against the brief's failure criteria:

* *Total > 1024 B with no defensible cut* — **does not fire.** 1024 B exactly, with `PAUSE` shared as the
  brief permits; 1036 B if `PAUSE` is a spelled-out word, which is a 12 B design choice and is measured.
* *Idle loop still faults every pass at this size* — **does not fire.** 3 pages, first pass 3 faults, then
  steady. The stop condition ("R3 is not achievable on 4 frames") is **not** reached: R3 is achievable
  with one frame to spare.
* *The event ring needs more than one frame* — **does not fire.** The ring is 16 B of dictionary data plus
  236 B of code (`POST` + `POLL-EVENTS`) that sits inside the idle loop's 3 pages. It never needs a frame
  of its own.
* *Stub/empty/fake words* — none. `os_device.fs` is 0 B because both its words are primitives, and that
  is stated as a finding in the file, not hidden behind a wrapper.

What that changes in the plan: **P24's conclusion was right about its own layer and wrong as a conclusion
about the machine.** A layer written to the spirit of §6 (states, blocked tasks, run queue, task printer,
8-slot payload ring) is 5.9 frames; a layer written to R3/R4's literal text is 2.0 frames and does not
fault. The cost is paid in *scheduling policy*, not in the requirements: no blocking, no priorities, no
task introspection, no event payloads, and — unchanged from P24 — **no context switch**, which still
needs a primitive and is now the only thing standing between this layer and R4's letter.

---

## 4. Doc deltas (verbatim, `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §6.1 — replace P24's numbers with the minimal layer's

> ### 6.1 The minimal layer **fits** — measured (P26)
>
> The same requirement, written to R3/R4's literal text instead of to the spirit of §6, is **22
> definitions, 1224 B with headers / 1024 B headerless = 2.0 frames** — a third of P24's 3044 B and
> **exactly the two-frame budget**. A group table, with the ceilings the requirement was given:
>
> | Group | ceiling | actual | what was given up |
> | --- | --- | --- | --- |
> | tasks | 300 | **292** | five task states, `WAKE-1`/`WAKE-ALL`/`STOP`, the free-slot scan, the run-queue link, `TASKS`, and 3 of the 4 record fields: the record is now `[xt][sp]`, 8 B |
> | events | 250 | **304** | event payloads and kinds (the ring holds handler xts, dispatched with `@ EXECUTE`), FIFO order, edge detection. Kept: the full-ring check and `DIAG`, because a clamp would be a lie |
> | REPL | 200 | **188** | `PROMPT`, `CR`, `.CODE`, `.ERR`, `OK?`, `ECHO` folded into `QUIT`/`?ERR` |
> | introspection | 120 | **240** | `?`, `.`, `.DIGIT`. `WORDS` must rebuild the 2-byte link without `W@` (36 B) and `U.` is 80 B because the 40 primitives have no decimal printer — this group cannot meet 120 B and the 120 B was optimistic |
> | device | 100 | **0** | `MS`, `PIN?`, `PIN!`, `PIN-WAIT`; `GPIO@`/`GPIO!` are primitives |
> | **total** | **1024** | **1024** | `PAUSE` is `YIELD` (the brief's own option); spelling it out costs 12 B |
>
> With 4 frames the idle loop touches **3 pages**, faults **3 times on the first pass (432 µs)** and then
> **0 times per pass**. A line calling three OS words touches 4 pages and does not thrash; compiling
> touches 3. The 40 B of dictionary data (3 slots of 8 B, a 4-cell ring) and 192 B of run-time stacks are
> what a context-switch primitive would switch between — and **still no primitive can**: `dsp`/`rsp`/`ip`
> are C statics, so R4's "tasks taking turns" is true of the scheduler's books and false of the machine.

### 4.2 `docs/01-proposal.md` §10 — R3 and R4, restated

> **R3 — event loop.** Measured (P26): the idle loop's Forth working set is **3 pages of 512 B** against
> **4 frames** — first pass **3 faults (432 µs)**, steady state **0 faults per pass**. The loop is
> `QUIT` → `POLL-EVENTS` → dispatch → `YIELD` → `SLEEP-TICKS`; its only blocking primitive is `KEY`, and
> it is reached only when the layer already holds a pending key, so **every pass retires**. The loop is
> now one page *inside* the frame count instead of two pages outside it (P24: 6 pages, 6 faults/pass).
>
> **R4 — multi-tasking.** Measured (P26): three tasks with their own stacks cost **292 B** of layer
> (`TASK` 88, `YIELD` 68, `SLEEP-TICKS` 56, a 24 B slot pool, `ALLOT`, three 8 B cells), plus 192 B of
> dictionary claimed at run time. Tasks take turns by rotating `CUR` over three slots, one tick per turn,
> and there is **no blocking state**: a sleeping task is scheduled and re-yields. **The context switch
> itself still does not exist** — no primitive in the 40 saves or restores `dsp`/`rsp`/`ip` — so R4 is met
> in the scheduler's bookkeeping and not in the engine. That is unchanged from P24 and is the one item a
> layer rewrite cannot fix.

### 4.3 `docs/JOURNAL.md` — new entry

> **J-xx — R3 and R4 were never a 3044 B requirement (P26).** P24 compiled 80 definitions to the *spirit*
> of §6 — five task states, a free-slot scan, a linked run queue, a 12 B event record with a kind and a
> payload, a task printer, a formatting REPL — got 3044 B headerless, 5.9 frames, 6 idle pages, and
> concluded R3/R4 do not fit. P26 asked what the requirement's literal text needs and got **22
> definitions, 1024 B headerless, 2.0 frames, 3 idle pages, 0 faults per pass.** So the machine can afford
> a multitasking Forth; what it cannot afford is *this* scheduler's policy. Given up to get there: task
> states and blocking (`STOP`/`WAKE-MASK`), the free-slot scan, event payloads and kinds, FIFO ordering,
> task introspection, and `PAUSE` as a separate word. Paid for by the device group being free — `GPIO@` and
> `GPIO!` are primitives, so the 100 B ceiling those words were given paid for the introspection overrun.
> Two lessons: **budget the requirement, not the design** (P24 was 3× the literal ask), and **a byte
> budget hides run-time bugs** — P26's first `YIELD` left a cell on the stack and `SLEEP-TICKS` leaked one
> per iteration; it compiled clean and would only have corrupted the stack after 16 passes.

---

## 5. Follow-ups

1. **Decide the context switch, now with the price known.** The layer is 1024 B; `DSP@ !` / `RSP@ !` /
   `IP@ !` are three primitives (~36 B of dictionary, P24 §1.3) plus engine work. That is 3.5 % of the
   layer to make R4 literally true. Nothing else in this probe is worth as much per byte.
2. **Re-add blocking, in one word at a time, and re-measure the hot set.** `STOP` (48 B) + `WAKE-MASK`
   (144 B) + a state field is ~200 B and would put the layer at 1224 B — over the headerless budget, under
   2.4 frames. It is the first thing to buy back if R3's "wakes" grow teeth.
3. **Run the three workloads on a real LRU simulator** (P03f's), not the 4-frame rule. The margin is now
   one page (3 of 4), which is exactly where the analytic model is least trustworthy.
4. **Introspection is the group that cannot meet its ceiling; treat 240 B as its floor**, or drop `WORDS`
   and keep `.S`. The `W@`-less link walk and the missing decimal printer are 116 B of *primitive-set*
   debt, not layer fat — P24's follow-up 5 (reconsider the trim) is still the right call.
5. **Bound `QUIT` in a test.** It is the one word no host test can run today. A `#LOOPS` cell the tick
   decrements would make "always retires" executable instead of inspected.

# P28 — Paying for R4: the budget closes, and only at 16-bit tokens

| | |
| --- | --- |
| Result | **CLOSES — one row, D: 3 tasks + 16-bit code tokens, gap +232 B.** The headline is *not* "no combination closes", but it is nearly worse: **rows B and C fail**, so 32-bit tokens cannot buy R4 at *any* task count — two tasks are already **96 B** short, three are **236 B** short. The 16-bit build measured on the same 78 definitions drops the resident need from **1104 → 636 B** (code field 4 → 2 B, bodies 728 → 424 B) and turns −236 into **+232 B**, keeping `SD=16`, all 4 × 512 B frames, and every word resident. It costs the **64 KB code ceiling** (P02's measured 1.49×), and R5 is unaffected because data addresses were always 32-bit. `SD=12` (row F) is **rejected twice over** — the stack indexes wrap with `& (SD-1)` so a non-power-of-two silently aliases live cells, and 12 cells is below P13's 20-cell data peak. Paging the cold prelude (row E, **228 B** of 14 named words) closes by +460 but is **not needed** and buys headroom at a fault cost nobody has traced. |
| Runs on | **host only** — `gcc -DHOST` dictionaries of both token widths, `-d` image dump + header walk. No `riscv32-esp-elf` link was run (§2.4 says exactly which number that leaves open). Board untouched, no serial device opened. |
| Time box | 15 min, one run — finished inside it; ~6 min of it on discovering that the only 16-bit engine available (P02 `a16`) carries **61 primitives** against P22's **40**, so its dictionary is 97 definitions, not 78 (§2.2) |
| Sources | `src/uforth32.c` + `src/boot_min32.fs` = **P22's linked engine and prelude, verbatim** (`cp`, no edits); `src/uforth16.c` + `src/boot_min16.fs` = **P02's `a16` build, verbatim**; `split_widths.py` = P22's `split_dict.py` parameterised by code-field width |

## Record

`MEMSZ` **available** = 1188 minus the bytes each extra task record steals from the pool (P22: `mem[]` is
exactly what is left after every other line). **Resident need** = the measured dictionary walk plus the
P26 layer's 40 B of `SLOTS`+`RING` data, which only the multitasking rows need.

| # | tasks | `MEMSZ` available | resident need | gap | gives up |
| --- | --- | --- | --- | --- | --- |
| A | 1 | **1188** | **1104** (+10 B pool = 94 B total spare) | **+84** | R4 entirely. Keeps 32-bit xts, so no code ceiling. 94 B is the whole headroom — one more prelude word is ~14 B |
| B | 2 | **1048** (1188 − 140) | **1144** (1104 + 40) | **−96 FAILS** | nothing — and it still does not fit. Two tasks at 32-bit tokens is not a reduced R4, it is not an R4 |
| C | 3 | **908** (1188 − 280) | **1144** | **−236 FAILS** | nothing. This is the row P27's 420 B implied, and it is 236 B underwater |
| D | 3 + 16-bit | **908** | **676** (636 + 40) | **+232** | the **16-bit code-token ceiling of 64 KB** (P02: 1.49× whole-dictionary density). Keeps `SD=16`, 4 × 512 B frames, all 78 definitions resident, 232 B headroom |
| E | 3 + 16-bit + paged prelude | **908** | **448** (636 − 228 + 40) | **+460** | same as D **plus** a fault on first use of 14 named words, write-back on the compile-time patch of 6 of them, and a page claim no tracer has seen (P25). Not needed: D already closes |
| F | 3 + 16-bit + `SD=12` | **976** (1188 − 212) | **676** | **+300 — REJECTED, not viable** | *illegal*: `SD=12` is not a power of two and `PUSH`/`POP` index with `& (SD-1)`, so 12 aliases live cells instead of overflowing; and 12 cells < P13's **20-cell** data-stack peak |

The six gaps in one line: `+84, −96, −236, +232, +460, (+300, illegal)`.

---

## 1. Answers

**Q: Does any combination close?**
**Yes — D, by 232 B, and only D.** Rows B and C do not close by 96 and 236 B. That is the finding the
plan needs: the gap is **not** a three-task problem, it is a **token-width problem**. Two tasks at 32-bit
tokens leave the machine 96 B over with 4 × 512 B frames already taken out of the budget.

**Q: Where do the numbers come from?**
Both dictionaries were **built and walked**, not extrapolated:

```
32-bit (P22 engine + P22 prelude, verbatim)  dictionary 1716 B, 78 definitions
  resident 1104 B   directory 812 B   -> reproduces P22 exactly  ✅
16-bit (P02 a16 engine + a16 prelude)        dictionary 1352 B, 97 definitions
  restricted to the same 78 definitions: resident 636 B (sysvars 56 + 580), bodies 424 B
```

The 16-bit body total **424 B** against the 32-bit **728 B** is a ratio of **1.72**, consistent with P02's
measured per-body ratio of **1.74** — so this is the same effect P02 measured, applied to the *resident
split*, which is why it needed a build: the ratio is a density number, and the resident set is
`sysvars + code fields + bodies`, three parts that scale differently.

| line | 32-bit | 16-bit | why |
| --- | --- | --- | --- |
| system variables + `PAD` | 64 | **56** | `V_XLIT`/`V_XEXIT`/`V_XSTR` are xts, so they halve too (`PAD` 28 → 24, `DICT` 64 → 56) |
| code fields, 78 definitions | 312 | **156** | 4 B → 2 B each |
| bodies, 78 definitions | 728 | **424** | P02's 1.74× body density |
| **resident need (P22's dictionary)** | **1104** | **636** | −468 B, 42 % |
| name directory (paged, not in the pool) | 812 | **818** | links and names do not narrow, and the xt is 2 B smaller — a wash |

**Q: Is 16-bit tokens' engine cost zero?**
**Not measured here, and it does not need to be for the verdict to hold.** P12 measured the width itself as
~free (+168 B there was paging, not width), and P22 measured the *pool constant's* coupling at **±30 B** of
`.text` (`2982 @ MEMSZ 2560 → 3010 @ 1188`). Row D's **+232 B** absorbs a full 30 B swing and still shows
+202. What is *not* measured is the 16-bit engine's `.text` at `MEMSZ = 908` on the ULP target (§2.4).

**Q: Row E — which words, and what do they cost?**
The 14 words that no REPL interaction needs: `ELSE`, `WHILE`, `REPEAT`, `AGAIN`, `UNTIL`, `?DUP`,
`NEGATE`, `DECIMAL`, `HEX`, `*/`, `0>`, `2*`, `2/`, `NOT` — **228 B** resident at 16-bit:

| word | 16-bit (cf+body) | word | 16-bit |
| --- | --- | --- | --- |
| `ELSE` | 36 | `DECIMAL` | 14 |
| `WHILE` | 30 | `HEX` | 14 |
| `REPEAT` | 22 | `*/` | 14 |
| `AGAIN` | 14 | `0>` | 14 |
| `UNTIL` | 14 | `2*` | 12 |
| `?DUP` | 12 | `2/` | 12 |
| `NEGATE` | 14 | `NOT` | 6 |

Five of them (`ELSE`, `WHILE`, `REPEAT`, `AGAIN`, `UNTIL`) are **self-patching** — `THEN`/`ELSE` write into
the branch operand with `HERE SWAP !` — so paging them buys a dirty page and a write-back on the first
compile that uses one. **The fault count must be measured, not reasoned**: P25's finding is that page
claims need a tracer, P26's hot set already claims 3 of the 4 frames, and P03f/P19 showed 4 × 512 B
livelocks on `ERR_RETRY_CAP` when working set exceeds frames. E's +460 B is therefore **headroom bought
with an untraced risk**, against D's +232 B bought with nothing but address width.

**Q: Row F — is 12 cells defensible?**
**No, twice.** (1) P13's measured peak is **20 data cells + 7 return cells**; a 12-cell data stack
overflows by 8 cells on the measured single-task workload, before multitasking adds anything. (2) The
engine's stacks are **fixed-size ring buffers with silent wrap** — `PUSH` is `ds[sp & (SD-1)]` — so
`SD=12` does not overflow, it **aliases live cells**, which is the failure mode P22's `GUARDRAIL` records.
Any "12 cells with a depth check" variant means changing the stack discipline, which is a different design,
not a budget line. F closes **only if it were legal**, and it is not; it would have bought 68 B over D.

**Q: What does three tasks cost the machine that the table does not show?**
`task 0`'s 136 B `VM` is already inside P22's 150 B `vm_state_reserve` line, so the table charges **140 B
per *additional* task** (B +140, C +280, F +212 at 106 B/task). Two lines are deliberately **out** of the
table and named here: P26's layer **code** (1024 B headerless − 40 B data) is not in P22's link at all, and
P27 measured the switch as *policy-free* (`PAUSE` only). If the layer's code has to be resident, **no row
closes** — it is 984 B against a best gap of +460. That is a scope decision, not arithmetic, and the probe
does not make it.

**Q: Does R4 survive at three tasks?**
**Yes, at 16-bit tokens (D: +232), and it scales one more task: 4 tasks = 768 − 676 = +92; 5 tasks = 628 −
676 = −48.** So the machine supports **four** tasks at 16-bit, not three, and the number to write into §10
is the one the operator wants — this probe's mandate is three.

---

## 2. Evidence

### 2.1 Commands (all under `timeout`, all outputs inside this directory)

```sh
cp ../P02-token-width/a16/uforth.c        src/uforth16.c      # verbatim, P02 a16
cp ../P02-token-width/a16/boot_min.fs     src/boot_min16.fs   # verbatim, the 16-bit prelude
cp ../P22-fits/src/uforth.c               src/uforth32.c      # verbatim, the linked engine
cp ../P22-fits/src/boot_min.fs            src/boot_min32.fs   # verbatim, the 32-bit prelude

timeout 120 gcc -DHOST -O2 -o artifacts/uforth_host32 src/uforth32.c
timeout 60 ./artifacts/uforth_host32 -d artifacts/image32.h src/boot_min32.fs
  -> image: 1716 bytes of 2560 (844 free)        # identical to P22's image_p22.h
timeout 120 gcc -DHOST -O2 -DMEMSZ=4096 -o artifacts/uforth_host16 src/uforth16.c
timeout 60 ./artifacts/uforth_host16 -d artifacts/image16.h src/boot_min16.fs
  -> image: 1352 bytes of 4096 (2744 free)       # identical to P02's a16 boot dictionary

timeout 20 python3 split_widths.py 4 artifacts/image32.h > artifacts/split32.txt
timeout 20 python3 split_widths.py 2 artifacts/image16.h > artifacts/split16.txt
```

`-DMEMSZ=4096` on the 16-bit build only widens `P()`'s bound; P02 found the same 2560 default too small for
a wider build, and an overflowing `P()` maps every address past `MEMSZ` onto one junk byte instead of
erroring.

### 2.2 The 16-bit engine available is not width-only — and that is handled, not hidden

The only 16-bit engine in the repo is P02's `a16`, which is the **original prototype**: **61 primitives**
against P22's **40**. Its dictionary therefore holds **97 definitions**, and its whole-image resident is
**674 B**, which is *not* the number for row D. The walk was restricted to the **78 definitions P22 actually
links**, all of which exist in the 16-bit image (32-bit-only definitions: **0**); the 19 extras
(`J`, `UNLOOP`, `W@`, `W!`, `U/MOD`, `XOR`, `INVERT`, `LSHIFT`, `RSHIFT`, `U<`, `KEY?`, `W,`, `C,`,
`LITERAL`, `."`, `(.")`, `(`, `MS`, `WAKE`) are P20's *deletions*, not a width effect, and cost 38 B of
code fields that a 16-bit P22 engine would not have. **636 B is the composition, not the image total** —
stated because reporting `674` would be a 38 B error in the closing row's favour.

### 2.3 The prelude, per word, both widths (cf+body)

```
word         16    32        word         16    32
ELSE         36    60        0>           14    24
WHILE        30    48        DO           14    24
IMMEDIATE    30    52        LOOP         14    24
IF           30    48        +LOOP        14    24
REPEAT       22    40        UNTIL        14    24
*/           14    28        HERE         12    20
HEX          14    24        LATEST       12    20
DECIMAL      14    24        BASE         12    20
NEGATE       14    24        ?DUP         12    24
AGAIN        14    24        STATE        12    20
THEN         10    20        1+           12    20
/            10    20        1-           12    20
2DUP          8    16        0<           12    20
NIP           8    16        2*           12    20
TUCK          8    16        2/           12    20
=             8    16        NOT           6    12
<>            8    16        BEGIN         6    12
>             8    16
```

The 36 words are **496 B at 16-bit / 872 B at 32-bit** (1.76×); the other 42 definitions are primitives
(2 B / 4 B each of code field, no body) at **84 / 168 B**. Those two sums are the whole table:
`56 + 496 + 84 = 636` and `64 + 872 + 168 = 1104`.

### 2.4 What was *not* built, and the exact size of that hole

**No `riscv32-esp-elf` link of a 16-bit engine.** P22's engine source carries the hooks, the 4 × 512 B
frames, the page table, the rings and the `MEMSZ` constant; `a16` has none of them. A 16-bit link is
therefore a **port** of P22's source to 16-bit tokens (the reverse of P02's `a16-to-b32.diff`), not a build,
and it does not fit in this box. Consequences, stated as consequences:

* the **resident need** in rows D/E/F is measured (§2.1–2.3), and the pool arithmetic above it is P22's;
* the **engine line** (3190) is P22's 32-bit figure. P12 measured width as ~free and P22 measured the
  `MEMSZ` coupling at **±30 B**, so row D's +232 carries a **±30 B** uncertainty — and that is the number a
  port must confirm before §4.3 is rewritten with `MEMSZ = 908`;
* rows B and C need **no** such port: they are the 32-bit machine with records added, and both fail by more
  than the coupling could ever give back.

---

## 3. Verdict

**PASS, and the verdict is a scope recommendation, not a fit.** Against the probe's pass criteria:

* **every combination computed from the measured numbers, with the arithmetic shown** — two dictionaries
  built and walked (§2.1), the four-part split in §1, the six gaps in the Record;
* **at least one row stating a positive gap** — **D: +232**, and E: +460 as a variant of it;
* **the functional cost of each closing row named** — D gives up the 64 KB code ceiling (P02's 1.49×);
  E gives up that *and* first-use faults on 14 named words worth 228 B, five of them self-patching, on a
  page claim P25 says cannot be reasoned about.

Failure criteria, checked:

1. *No combination closes ⇒ R4 dropped or reduced to two tasks.* **Does not fire** — but **two tasks at
   32-bit tokens does not close either (−96)**, so "reduced to two tasks" is only available *with* 16-bit
   tokens (+372). The reduced-R4 option is therefore not cheaper than the full one.
2. *Only 16-bit closes ⇒ adopt 16-bit code tokens and note R5 is unaffected (data addresses were always
   32-bit).* **This is exactly what happened.** Adopt 16-bit tokens; R5 unaffected.
3. *Only paged prelude closes ⇒ state the expected fault count.* **Does not fire** — E is not needed, and
   its fault count is untraced (§1, P25).
4. *`SD=12` looks necessary ⇒ check against P13's 27-cell peak.* **Checked and rejected**: 12 < the
   20-cell data peak, and `SD` must be a power of two or the wrap aliases live cells. F is not a row, it is
   a bug with a budget attached.

**What changes in the plan:** §4.3's closing table has a positive entry the first time — and it is bought
with address width, not with frames, stacks, rings or words. Nothing in the pool is spent: `SD=16`,
4 × 512 B frames, the 320 B C stack, the 600 B rings and all 78 definitions stay exactly as P22 measured
them. The 94 B "no room to grow" of P22 becomes **232 B of headroom** — the first slack the design has had.

---

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.3 — append this closing table after the §4.3 budget table (P22's §4.1 delta stays)

```
**Does it close with task state in it? (`P28`)** R4 needs 140 B per task of saved machine (`P27`), which
comes out of the pool 1:1 because `mem[]` is what is left. At 32-bit code tokens it does not close at any
task count; at 16-bit it closes at three tasks and still fits a fourth:

| # | tasks | `MEMSZ` available | resident need | gap |
| --- | --- | --- | --- | --- |
| A | 1 (as linked) | 1188 | 1104 | **+84** (94 B with the pool residue) |
| B | 2, 32-bit | 1048 | 1144 | **−96** — fails |
| C | 3, 32-bit | 908 | 1144 | **−236** — fails |
| D | 3, **16-bit** | 908 | 676 | **+232** — closes |
| E | D + cold prelude paged | 908 | 448 | +460, not needed |
| F | D + `SD=12` | 976 | 676 | rejected: `SD` must be a power of two, and 12 < `P13`'s 20-cell peak |

Density, measured on both builds of the same 78 definitions (`P28`): code fields 312 → 156, bodies 728 →
424 (1.72×, matching `P02`'s 1.74× body ratio), system variables 64 → 56, so resident **1104 → 636 B** and
the paged directory is unchanged (**812 → 818 B**, a wash). `MEMSZ` 908 with 3 × 140 B of records leaves
**232 B**, enough for one more task (+92) and not two. The 16-bit engine's `.text` at `MEMSZ` 908 has not
been linked (`P28` §2.4); `P22`'s pool-constant coupling is ±30 B, which +232 absorbs.
```

### 4.2 `docs/01-proposal.md` §10 — R4, restated with the task count the machine can support

```
- [ ] **R4 — several tasks take turns, and the machine pays for them (`P27`, `P28`).** The context switch
      is one 140 B struct copy at `SD=16`, resumable mid-word, and it fits: **three tasks close by 232 B**
      and a fourth by 92 B, at **16-bit code tokens** (`P28`, measured on both builds of the same 78
      definitions). At 32-bit tokens R4 does not close at all — two tasks are already 96 B over — so
      **R4 is the reason the token width is 16 bits**, and `§7`'s 32-bit xts are withdrawn: code addresses
      are 16-bit (`64 KB` code ceiling), data addresses stay 32-bit, so **R5 is unaffected**.
```

### 4.3 `docs/JOURNAL.md` — new entry

```
**R4 paid for, in address width.** P28 costed the 140 B/task that P27 measured against P22's 94 B of
slack. At 32-bit code tokens nothing closes — two tasks are 96 B over, three 236 B — so "reduce R4 to two
tasks" was not a cheaper option than the full requirement. Building the 16-bit dictionary for the same 78
definitions (P02's engine + prelude) put the resident need at 636 B instead of 1104 (code fields 312→156,
bodies 728→424), which turns three tasks from −236 into **+232**, with frames, stacks, rings and every
word untouched. The price is the 64 KB code ceiling; data addresses were always 32-bit, so R5 does not
move. SD=12 was rejected twice: not a power of two (the stacks wrap with `& (SD-1)`), and below P13's
20-cell peak. Decision: **16-bit code tokens, three tasks, 232 B headroom.** One number is still open —
the 16-bit engine's `.text` at MEMSZ 908 — and P22's ±30 B pool coupling is smaller than the margin.
```

---

## 5. Follow-ups

1. **Link the 16-bit engine.** Port P22's source to 16-bit tokens (the reverse of P02's `a16-to-b32.diff`)
   and link at `MEMSZ = 908` with three 140 B records. Until that runs, §4.3's `MEMSZ` is a computed value
   with a ±30 B measured coupling, not a linked one. The port is mechanical and the diff is the
   specification.
2. **Decide the OS layer's residency.** P26's 1024 B headerless layer is 40 B of data (charged above) and
   ~984 B of code (not charged, not in P22's link). If that code must be resident, **no row closes**. It is
   a scope decision; the probe deliberately does not make it.
3. **Re-derive the directory's xt duplication at 16-bit.** The directory is 818 B with 2 B xts; P22's
   follow-up 3 (a 1-byte resident index instead of an xt) is worth ~156 B at 16-bit, not 312 — the lever
   halves with the width, so it should be re-costed before anyone counts it as a spare 300 B.
4. **Four tasks is one row away.** 4 tasks at 16-bit leave +92 B; 5 leave −48. If the operator wants four,
   §4.3 should say four, because the arithmetic already supports it and the record is the only line that
   moves.
5. **`SD`'s power-of-two requirement should be a static assert**, not a `GUARDRAIL` comment: `SD=12` is a
   natural attempt at this budget and it fails silently by aliasing live cells.

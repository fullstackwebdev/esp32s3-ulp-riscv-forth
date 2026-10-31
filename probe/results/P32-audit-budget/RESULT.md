# P32 — Audit the 322 bytes, then price what the machine keeps

| | |
| --- | --- |
| Result | **The 322 B is fully named — and it is not slack, it is a bill.** `nm -S` on P31 variant C's image accounts for every byte between §4.3's 4418 B and the linked 4740 B: **+420 `tsk`, +196 startup/entry + main skeleton, +128 `tib`, +34 engine-TU statics, +6 VM counters**, against **−142 hooks** (tabled as a fixed line, actually paid inside the engine's `.text`) and **−320 C stack** (tabled as a fixed line, actually *not in the image at all*). `+420+196+128+34+6−142−320 = 322`. So the table's arithmetic is not the error — **the table mixes two conventions** (some lines are symbols, one line is code, one line is outside the image) — and the corrected engine ceiling is confirmed at **3116 B**, with a second, stricter ceiling of **2796 B** that appears the moment the C stack is honoured inside the pool (§1.2 — `__stack_top` is `ORIGIN+LENGTH`, so the stack grows *down into* the last 320 B of the linked image; 296 B is the optimistic version of the gap). **Variant D — C plus `I J UNLOOP GPIO! ' CONSTANT ( ."` (and `(.")`, without which a compiled `."` is a token with no case) — is 3916 B engine (3928 `.bin − control`) and the real 7856 B link fails at `address 0x21d0`, 8656 needed, 800 B over.** The nine restored entries cost **504 B** (440 in `vm_enter`, 48.9 B/entry; 36 B of `.rodata` name strings; the rest is the outer interpreter reshuffling). Against the corrected ceiling: **+800 B** (or +1120 if the stack is reserved). The three options are priced in §1.4 and **none is chosen**: only (a) closes the gap alone. |
| Runs on | **host only** — `riscv32-esp-elf-gcc 14.2.0 (esp-14.2.0_20241119)`, IDF v5.4, P29/P31's linker script (`LENGTH = 7856`). Board untouched, no `/dev/ttyACM*` opened. |
| Time box | **overrun.** Build D was launched at ~T+11 min, not T+3: the first launch died on a `cp -r` that nested `src/` one level deep (`probe/results/P32-audit-budget/src/src/…`), and the fix plus relaunch cost the budget. One build of D, one run, no retries after that. The audit was read off P31's existing `nm`/ELF artifacts (no rebuild), as the brief allows ("derive from nm/ELF artifacts"). |
| Sources | `src/` is **P31's `src/` copied verbatim** (uforth.c, ulp_stubs.c, `p31_prims.inc`, `p31_cases.inc`, `p31_required.defs`, the `os_*.fs` layer, both `.ld` scripts) — no engine source was edited. `p32_build.py` is P31's `p31_build.py` with **one added variant** (`D` = C + nine `-DP_HAVE_*`) and output paths renamed `p31_*`→`p32_*`. `run.sh` is P31's driver with the script/log names changed. |
| Artifacts | `artifacts/audit_nm.txt` (every non-engine symbol in C, plus the control image), `artifacts/p32_D_diff.txt` (D vs C per symbol), `artifacts/p32_D_nm.txt`, `artifacts/p32_D_{diag,real}.{elf,map}`, `artifacts/p32_control.elf`, `logs/p32_D.log` |

## Record

| Part | Result |
| --- | --- |
| audit: 322 B named | **every byte**: +420 `tsk`, +196 startup/main, +128 `tib`, +34 statics, +6 VM counters, −142 hooks, −320 C stack = **322** |
| corrected engine ceiling | **3116 B** (`7856 − 4740`), confirmed; **2796 B** if the 320 B C stack is reserved inside the pool as `__stack_top` requires |
| D: engine | **3916 B** (`.bin − control` **3928**), 49 primitive entries, real link **FAIL 0x21d0, 8656 needed of 7856 = 800 over** |
| D gap vs corrected ceiling | **+800 B** vs 3116 (**+1120 B** vs 2796) |
| (a) drop paging | **−2466 B** (−2298 pool, −168 engine) → 6190 needed, **fits, 1666 spare**; loses the frames, the paged fetch and the fault/resume path |
| (b) two tasks | **−140 B** → 8516 needed, **660 short**; one fewer concurrent task |
| (c) `mem` → 676 | **−232 B** → 8424 needed, **568 short**; the dictionary has 0 B of slack over the measured resident need |

## 1. Answers

### 1.1 The 322 B, line by line

`8152` (C's need) `− 4740` (non-engine) `= 3412` (C's engine). The 4740 breaks down to `196` control
`.text` + `8` `.srodata.seed.0` + `4` `.data` + `4532` `.bss`. Mapped to §4.3 (`artifacts/audit_nm.txt`):

| §4.3 line | tabled | `nm -S` symbol(s) in C's image | measured | Δ |
| --- | --- | --- | --- | --- |
| Page frames 4 × 512 | 2048 | `frm` 2048 | 2048 | 0 |
| VM state + counters | 150 | `vm_live` 136 + `vm_depth` 4 + `vm_max_depth` 4 + `vm_sw_first` 4 + `vm_switches` 4 + `vm_sw_taskexit` 4 | 156 | **+6** |
| Forth stacks | 128 | no symbol: DS 64 + RS 64 + sp/rsp/w/ip 8 **are** `vm_live`'s 136 — already in the line above | 0 extra | 0 |
| Page table + LRU | 250 | `ptab` 16 + `ptab_lru_reserve` 234 | 250 | 0 |
| Mailbox + rings | 600 | `mailbox` 216 + `out_ring` 256 + `cmd_ring` 128 | 600 | 0 |
| Line buffer | 128 | `tib` 128 | 128 | **+128** |
| ULP hooks / REPL glue | 142 | `pl_emit` 34 + `pl_halt` 46 (+ `pl_key`, `pl_hw` inlined) — **all inside `.text`, i.e. already paid in the 3412 engine**, 0 B in the fixed lines | 0 | **−142** |
| C stack (pool top) | 320 | **no symbol, no section** — reserved only by `LENGTH = 8176 − 320` | 0 | **−320** |
| Forth memory `MEMSZ` | 908 | `mem` 908 | 908 | 0 |
| Task state 3 × 140 (row marked −420) | 420 | `tsk` 420 | 420 | **+420** |
| *no §4.3 row* — startup + entry + main skeleton | 0 | `p32_control.elf` `.text` 196 = `reset_vector` 4 + `__start` 16 + `ulp_riscv_rescue_from_monitor` 20 + `ulp_riscv_halt` 36 + `main` 120 (+ `.size` padding) | 196 | **+196** |
| *no §4.3 row* — engine-TU statics | 0 | `seed.0` 8 + `cur` 4 + `savehere` 4 + `savelatest` 4 + `halt_status` 4 + `ring_head` 4 + `ti`/`tl`/`junk`/`errf` 4, + 2 B of `.bss` alignment | 34 | **+34** |
| **total** | **4418** | | **4740** | **+322** |

`+6 + 128 − 142 − 320 + 420 + 196 + 34 = +322`. Both negative terms are the same defect seen twice, and it
is **not** arithmetic slips:

* **`hooks 142` is a code line in a table of symbols.** `pl_emit`/`pl_halt` are ordinary `.text` in the
  engine TU; they are inside C's 3412 B. Counting them a second time as a fixed line would make the ceiling
  look 142 B larger than it is.
* **`C stack 320` is a line with no artifact at all.** It exists only as `8176 − 320 = 7856` in the linker
  script, and — §1.2 — the script does not actually keep it out of the image.

Everything the brief listed as a suspect is now closed: `tsk` 420 was in no fixed line at all (it is a
negative "−420" row that was never added to the sum) — **this alone is bigger than the 296 B gap**;
`tib` 128 had a row that the 4418 sum forgot; `mailbox` 216 is inside the 600 line and is correct;
`ptab_lru_reserve` 234 + `ptab` 16 is exactly the tabled 250, not the 234 the brief suspected; there is **no
`.rodata` double count** — engine `.rodata` is 160 B and the only non-engine rodata is `seed.0` 8 B, counted
once.

### 1.2 The corrected ceiling — and the second one under it

`7856 − 4740 = 3116`, so **C (3412) is 296 B over**, exactly as P31 reported. But the 4740 excludes a line
that the linker never reserved:

* `src/ulp_p31.ld`: `ram : ORIGIN = 0, LENGTH = 7856` and `__stack_top = ORIGIN(ram) + LENGTH(ram)` = **7856**.
* `ulp_core/start.S`: `la sp, __stack_top` — the disassembly of the linked `__start` is
  `auipc sp,0x3; addi sp,sp,-292` = `sp ← 0x2ee0`, i.e. the *end of the region*.
* The stack therefore grows **down from 7856 into the last 320 B of `.bss`**. Sections are allowed to link
  up to 7856. Shrinking `LENGTH` from 8176 to 7856 protected the top of the *pool*, not the image.

So with the script as linked, sections have **7536 B**, and the engine ceiling is `7536 − 4740 = **2796 B**`:
C is **616 B** over, D **1120 B**. One line fixes the convention without moving a byte —
`__stack_top = ORIGIN(ram) + LENGTH(ram) + 320;` — and then the first ceiling (3116) is the honest one.
Both are reported; the headline uses **3116** because that is the number §4.3's own budget is written in,
and the fix is a linker-script edit, not a scope decision.

### 1.3 Variant D — what the language costs

D = P31's C + `-DP_HAVE_{I,J,UNLOOP,GPIOS,TICK,CONSTANT,PAREN,DOTQ,PDOTQ}`, same source, same flags, same
script (`p32_build.py`, `logs/p32_D.log`). `(.")` is restored with `."` because `."` in compile state writes
the `(.")` token into the dictionary; without its case body a compiled string prints nothing and says nothing.

| | C (P31) | **D (P32)** | Δ |
| --- | --- | --- | --- |
| primitive entries | 37 + 3 pseudo = 40 | **46 + 3 = 49** | +9 |
| engine, sections (`.text − control.text` + `.rodata`) | 3412 (3252 + 160) | **3916 (3720 + 196)** | **+504** |
| engine, `.bin − control` | 3424 | **3928** | +504 |
| `.bss` | 4532 | 4532 | 0 |
| **region need** | 8152 | **8656** | +504 |
| real 7856 B link | FAIL, 296 over | **FAIL `0x21d0`, 800 over** | |
| gap vs corrected ceiling 3116 | +296 | **+800** | |
| gap vs stack-reserved ceiling 2796 | +616 | **+1120** | |

Where the 504 B goes (`artifacts/p32_D_diff.txt`, `nm -S`, both images):

| symbol | C | D | Δ | why |
| --- | --- | --- | --- | --- |
| `vm_enter` | 1354 | **1794** | **+440** | the nine restored case bodies — **48.9 B/entry**, consistent with P31's 44.5 B/entry for the 26 removed ones |
| `.rodata` | 160 | **196** | **+36** | the nine primitive **name strings** in the headers (`CONSTANT`, `GPIO!`, `UNLOOP`, …) |
| `main` | 762 | 624 | −138 | inlining balance of the outer interpreter shifts |
| `mkhdr` | 194 | 148 | −46 | same |
| `wr16` | 66 | 36 | −30 | same |
| `word` | 172 | 202 | +30 | same |
| `find` / `clit` / `wr8` | 0 / 0 / 0 (inlined) | 148 / 34 / 30 | **+212** | the same three functions stop being inlined at this size |

`440 + 36 + (−138 − 46 − 30 + 30 + 212) = 504`. The eight names a programmer needs are therefore **504 B of
engine**, and nine entries at ~49 B is the whole story — no hidden lever, no reshuffle worth chasing.

### 1.4 The three options, priced, not chosen

Against **D** (need 8656, pool 7856, gap **800 B**). Every number is from D's own `nm -S` inventory, which is
identical to C's (`frm` 2048 `ptab` 16 `ptab_lru_reserve` 234 `cmd_ring` 128 `out_ring` 256 `mailbox` 216
`tib` 128 `mem` 908 `vm_live` 136 `tsk` 420, all present).

| option | bytes | residual against 800 | what it costs functionally |
| --- | --- | --- | --- |
| **(a) drop paging from the first machine** | **−2466**: pool `frm` 2048 + `ptab` 16 + `ptab_lru_reserve` 234 = **−2298**, engine `pg_load` 108 + `rd16_paged` 60 = **−168** (`resolve` is inlined, 0 B of symbol) | **fits with 1666 B spare** (1346 if the C stack is reserved) | No page frames, no 16-bit paged fetch, no page-fault retry/resume — P03/P16/P19's whole mechanism leaves the first machine; the dictionary becomes directly addressed and its 908 B are all the Forth there is. The *language* does not change: paging is invisible to Forth words, so it can be re-added later without touching a single primitive — the only requirement in this budget with that property. |
| **(b) two tasks instead of three** | **−140** (`tsk` 420 → 280, `NTSK=2`) | **660 B short** | One fewer concurrent thing; R4 drops from 3 tasks to 2, and every "3 tasks" measurement in P27/P29/P31 becomes an extrapolation. Not sufficient alone. |
| **(c) `mem` 908 → 676** | **−232** | **568 B short** | `MEMSZ` falls to the measured resident need exactly: **0 B of slack** for a dictionary that grows (no room for `LOAD`, no room for the operator's own words beyond what P26 already occupies). Not sufficient alone; (b)+(c) = −372, still **428 B short**. |

Only (a) closes the gap by itself, and the gap it closes includes the C stack problem for free (freeing 2466 B
of pool buys back the 320 B the script never reserved). (b) and (c) are each cheaper in functional terms and
each *insufficient* — they are not levers against 800 B, they are levers against a smaller gap that does not
exist yet.

## 2. Evidence

### 2.1 Commands (all under `timeout`; build in tmux with `nice -n 10`; every output inside this directory)

```sh
mkdir -p artifacts src logs
cp -r ../P31-primitive-set/src src/            # the engine copy, verbatim
cp ../P31-primitive-set/p31_build.py p32_build.py
python3 - <<'EOF'                              # add variant D, rename p31_* -> p32_* output paths
EOF
sed -e 's/p31_build.py/p32_build.py/' ../P31-primitive-set/run.sh > run.sh
tmux new-session -d -s p32 './run.sh D 908'    # timeout 300 nice -n 10 python3 p32_build.py D 908
cat logs/p32_D.log
# audit, off P31's existing artifacts — no rebuild
riscv32-esp-elf-size -A ../P31-primitive-set/artifacts/p31_C_diag.elf        # 3448/160/8/4/4532 = 8152
riscv32-esp-elf-size -A ../P31-primitive-set/artifacts/p31_control.elf       # .text 196
riscv32-esp-elf-nm -S --defined-only .../p31_C_diag.elf                      # -> artifacts/audit_nm.txt
riscv32-esp-elf-objdump -d --stop-address=0x30 .../p31_C_diag.elf            # __start: sp <- 0x2ee0
join -j1 <(nm -S C) <(nm -S D) | awk '$2!=$3'                                # -> artifacts/p32_D_diff.txt
```

### 2.2 The audit is reproducible from two section tables and one `nm`

```
p31_C_diag.elf: .text 3448  .rodata 160  .srodata.seed.0 8  .data 4  .bss 4532   Total 8152  (= "needed")
p31_control.elf: .text 196                                                            (= the non-engine .text)
engine = (3448 − 196) + 160 = 3412        fixed = 8152 − 3412 = 4740        7856 − 4740 = 3116
```

`artifacts/audit_nm.txt` holds the array symbols (`frm` 0x800, `mem` 0x38c, `tsk` 0x1a4, `out_ring` 0x100,
`ptab_lru_reserve` 0xea, `mailbox` 0xd8, `vm_live` 0x88, `tib` 0x80, `cmd_ring` 0x80, `ptab` 0x10 — 4490 B),
the statics, the control `.text` symbols and the hooks, so every line of §1.1 can be re-read without a build.

### 2.3 One defect found in P31's B/C while adding D (reported, not fixed)

`src/p31_cases.inc:183` guards the shared block

```c
#if !defined(P31_SUBSET) || defined(P_HAVE_TICK)
        case P_TICK: case P_BTICK:
```

on **`P_HAVE_TICK`**, but `p31_required.defs` enables **`P_HAVE_BTICK`** and not `P_HAVE_TICK` (the layer
uses `[']`, never `'`). In B and C the block is therefore dropped and **`[']` has no case body** — the
`GROUPED = {"BTICK": "TICK"}` mapping in `p31_gen.py` only covers the two-label-split form
(`case P_LOOP:` / `case P_PLOOP:` on separate lines), not this one-line pair. D restores `TICK`, which
brings `BTICK` back, so **D is whole** — but C's 3412 B is ~1 case body light, and P31's claim that C's
required set is *functional* (not just counted) should carry that caveat. It does not change any number here
by more than the size of one `case` body, and D is measured with the block present.

## 3. Verdict

**The 322 B was never slack. The machine's real gap is 800 B with a usable language, not 296 B — and the
300-ish B of "unexplained" budget was `tsk` 420 plus the startup 196, offset by a hooks line and a C-stack
line that the image never pays.**

On the probe's own criteria:

* *every byte of the 322 B attributed* — **met**, twelve rows in §1.1, `+6+128−142−320+420+196+34 = +322`,
  each row an `nm -S` symbol, a section, or (for the C stack) the absence of both.
* *variant D built and linked, with its real result* — **met**: `LINK-FAIL address 0x21d0` = 8656 of 7856,
  800 over; engine 3916 (3928 `.bin − control`).
* *three options priced, none chosen* — **met** (§1.4), and the pricing says something the probe did not
  expect: with the language restored, two of the three options **cannot close the gap alone**.
* *no array vanished* — **met for D**: `frm/mem/tsk/out_ring/ptab_lru_reserve/mailbox/vm_live/tib/cmd_ring/ptab`
  all present, same sizes as C.

The plain statement: **§4.3's 4418 B is not wrong by 322 B of arithmetic — it is wrong by 322 B of
convention.** It counts a code line (hooks 142) among allocation lines, counts a line that is not in the image
(C stack 320) as if it were, omits the task records (420) that its own footnote lists, and omits startup (196).
Corrected, the engine ceiling is 3116 B; the language a programmer needs costs 504 B more than P31's 40, so D
sits **800 B over** — and, because the C stack was never actually carved out of the pool, possibly **1120 B**
over. Only dropping paging closes that alone, and it is the only one of the three options that can be taken
back later without changing the language. **Recommendation to the operator: (a).** The choice is not made here.

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.3 — the corrected table, every `nm` symbol mapped to a line

```
**Resident budget, corrected against the linked image (`P32`).** Two independent measurements disagree with
the table below by 322 B (4418 tabled vs 4740 linked); every byte of that difference is now named. The lines
are not all of one kind, which is what the table concealed:

| Item | Bytes | Artifact (`nm -S` unless stated) |
| --- | --- | --- |
| Engine, 49 primitives (D: 40 + I J UNLOOP GPIO! ' CONSTANT ( `."` `(.")`) | **3916** (`.text` 3720 + `.rodata` 196) | P32, `.bin − control` 3928 |
| Engine, 40 primitives (C) | 3412 (3252 + 160) | P31 |
| Page frames 4 × 512 | 2048 | `frm` |
| VM state + counters | 156 | `vm_live` 136 + `vm_depth`/`vm_max_depth`/`vm_sw_first`/`vm_switches`/`vm_sw_taskexit` 4 each |
| Forth stacks (DS 64 + RS 64) | (inside `vm_live`) | no separate symbol — they are `vm_live`'s first 128 B |
| Page table + LRU | 250 | `ptab` 16 + `ptab_lru_reserve` 234 |
| Mailbox + rings | 600 | `mailbox` 216 + `out_ring` 256 + `cmd_ring` 128 |
| Line buffer | 128 | `tib` |
| Task state, 3 × 140 | **420** | `tsk` — a line §4.3 carried as a footnote, not as a budget line |
| Forth memory `MEMSZ` | 908 | `mem` |
| Startup + entry + `main` skeleton | **196** | control image `.text` (`__start`, `reset_vector`, `pl_*` excluded) |
| Engine-TU statics + `seed` | **34** | `seed.0` 8 + `cur`/`savehere`/`savelatest`/`halt_status`/`ring_head` 4 each + 4 × 1 B flags + 2 B align |
| ULP hooks `pl_emit` 34 + `pl_halt` 46 (+ `pl_key`, `pl_hw` inlined) | **80, inside the engine** | not a fixed line: §4.3's "142" double-counted them |
| C stack 320 | **0 in the image** | no symbol, no section; `LENGTH = 8176 − 320` is the only trace |
| **total fixed (non-engine)** | **4740** | 196 + 8 + 4 + 4532 `.bss` |

The corrected engine ceiling is therefore **7856 − 4740 = 3116 B**, not 3438. And a stricter ceiling waits
under it: `__stack_top = ORIGIN + LENGTH`, so the C stack grows down into the last 320 B of the linked image
while sections may link to 7856; reserving it (`__stack_top = ORIGIN + LENGTH + 320`) gives sections 7536 B
and a ceiling of **2796 B**. The 296 B figure is the optimistic one.
```

### 4.2 `probe/EVIDENCE.md` — the audit table and D's numbers

```
P32 — the 322 B audited, and the price of a usable language:

4418 (§4.3) -> 4740 (linked).  Delta = +322 =
  +420 tsk (no fixed line; a "minus 420" footnote never added)
  +196 startup+entry+main skeleton (no row: control .text)
  +128 tib (row exists, absent from the 4418 sum)
   +34 engine-TU statics/seed/cur (no row)
    +6 VM counters (150 tabled -> 156 measured)
  -142 hooks (tabled as a fixed line; pl_emit 34 + pl_halt 46 are .text, inside the engine)
  -320 C stack (tabled as a fixed line; not in the image at all)
untouched and exact: frm 2048, ptab 16 + ptab_lru_reserve 234 = 250, mailbox 216 + out_ring 256 +
cmd_ring 128 = 600, vm_live 136, mem 908.

engine ceiling: 7856 - 4740 = 3116   (2796 if the 320 B C stack is reserved: __stack_top is ORIGIN+LENGTH,
                                      so the stack grows down into the image; sections get 7536)

variant  entries   engine (sections)   .bin - control   needed of 7856   real link
C        37+3      3412 (3252+160)     3424             8152             FAIL 0x1fd8, 296 over
D        46+3      3916 (3720+196)     3928             8656             FAIL 0x21d0, 800 over
D = C + I J UNLOOP GPIO! ' CONSTANT ( ." (+ (.")   ; +504 B, 48.9 B/entry in vm_enter, +36 B name strings

options vs D's 800:  (a) drop paging -2298 pool -168 engine => 6190, fits with 1666 spare
                     (b) two tasks   -140 => 8516, 660 short
                     (c) mem -> 676  -232 => 8424, 568 short   ; (b)+(c) = 8284, still 428 short
```

### 4.3 `docs/JOURNAL.md` — the options, since none is chosen

```
**The 322 bytes are accounted for, and they were never slack.** P31 left a 322 B hole between the tabled
4418 B of fixed lines and the 4740 B the linked image actually carries. Audited symbol by symbol, the hole is
`tsk` 420 (a footnote, never a budget line), startup and the entry code 196, the line buffer 128, 34 B of
statics and 6 B of counters, minus two lines the table counted but the image does not pay the way it says: the
80 B of hooks are `.text` inside the engine, and the 320 B C stack is not in the image at all. The engine
ceiling is 3116 B, not 3438 — and if the C stack is honoured inside the pool (it is not: `__stack_top` is the
end of the link region, so the stack grows down into the last 320 B of `.bss`) the ceiling is 2796 B. On the
same accounting, a Forth someone can actually program costs 504 B more than P31's derived 40: `I`, `J`,
`UNLOOP`, `GPIO!`, `'`, `CONSTANT`, `(` and `."` are nine entries at ~49 B each, and variant D lands at 3916 B
— **800 B over the corrected ceiling, 1120 B over the stack-honest one**. The three options are priced and
none is taken: dropping paging frees 2466 B and fits with room (P32's recommendation, because paging is the
only requirement that can return without changing the language), two tasks frees 140 B (660 short), and
`MEMSZ` 676 frees 232 B (568 short). The operator decides; the port waits on that decision.
```

## 5. Follow-ups

1. **Fix the C stack reservation before any further budget arithmetic.** `src/ulp_p31.ld` sets
   `__stack_top = ORIGIN + LENGTH`, so the "320 B C stack" never leaves the pool; every "fits" in P22/P29/P31
   is 320 B optimistic. One-line change, then re-read the ceiling as 3116.
2. **Do not re-derive the fixed lines from the target again.** The 4740 came from `needed − engine`; the 4418
   came from a sum of rows, and the two conventions differ. §4.3's corrected table now names the artifact for
   each line so the next probe can check a line without a build.
3. **`pl_key` and `pl_hw` have no symbols** — they are inlined into `vm_enter`, so "hooks 142" cannot be
   checked from `nm` for those two. If the hooks line matters again, build the stubs TU alone with the real
   defines and read *that* control image (196 → hooks).
4. **P31's B/C drop the `case P_TICK: case P_BTICK:` block** (guard keys on `TICK`; the set enables only
   `BTICK`), so `[']` has no body in those two variants. D restores it. If B/C are ever quoted as *working*
   40-primitive engines, that needs a line in P31's RESULT.
5. **`-Oz` on D** was not tried (P31's follow-up 4 still open). One build, and the switch is exactly the shape
   `-Oz` optimises; if it recovers >170 B the (b)+(c) combination becomes interesting.

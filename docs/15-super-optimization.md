# 15 — Super-optimization for application space: everything on the table

The goal is **application space**, with **every feature intact** and the image **verified on the device**.
Speed is not the goal, but it is not the enemy either: an idea that costs cycles is acceptable if another
idea buys them back, and the ideas that win on both axes rank highest.

## 0. The rule that makes this a search

```
app space = MEMSZ − BLKSZ − dictionary − code area − free gap
pool      = .text + .rodata + .data + .bss ,  and .data = MEMSZ + 16
```

`.data` holds `mem[]`, so **every byte removed from `.text`, `.rodata` or `.bss` becomes exactly one byte of
`MEMSZ`, which is exactly one byte of application space** — after a re-bake (`tools/bake.sh <MEMSZ>`). There
is no multiplier and no lossy step. That is why this document attacks everything *except* `mem[]`: shrinking
`mem[]` costs a feature, shrinking the C around it costs nothing.

Current budget, all measured on the shipping image:

| section | bytes | contents |
| --- | --- | --- |
| `.text` | **4 926** | 1 698 instructions; `vm_enter` **2 306**, `main` 890, everything else ≤ 170 |
| `.rodata` | **340** | dispatch jump table 268, P54 op table 56, misc 16 (plus 6 in `.srodata`) |
| `.data` | **1 704** | `mem[]` 1 688 + 16 B interpreter variables |
| `.bss` | **877** | `tsk` 280, `vm_live` 136, rings 192, `tib` 128, counters ~40, `blkvars` 18, `mailbox` 16 |
| **pool** | **7 853 / 7 856** | 3 B spare |
| **app space** | **727** | code 578 + headers 255 + window 128, `free 727` |

`mem[]` detail: variables 0–21, `PAD` 24–55, `DICT` 56 → code 578 B (= 170 code fields + 116 inline
operands + 236 tokens + 56 system bytes), headers 255 B (85 × 3, from `HDRTOP` 1 560 down), block window
128 B, free 727 B.

## 1. What the CPU actually gives us (measured, not assumed)

| fact | measurement | consequence |
| --- | --- | --- |
| RVC compression | **933 of 1 698 instructions are 2-byte**, 2.90 B/instr | encoding density is **saturated**; "use 16-bit instructions" is already done |
| `lui` for address materialisation | **120 occurrences, 480 B** (7 %) | a reserved base register could recover part of it (§5 F1) |
| `-march` | `rv32imc_zicsr_zifencei` — M extension present | `/` and `%` are single instructions; no libgcc division |
| address space | ULP links at **0**, RTC RAM is zero-based | no 32-bit address constants; `lui` is per-4 KB page |
| registers | 32 × 32-bit, currently ~8 live | **20+ idle registers**: the largest untapped resource |
| memory | 8 KB RTC slow RAM, ~1-cycle-per-byte-ish at 19 MHz | fast enough that registers, not memory, are the bottleneck |
| `-msave-restore` | adopted (−224 B) | but it costs a `jal` in every prologue and epilogue |

## 2. Ideas — `.text`, the dispatcher (`vm_enter`, 2 306 B)

| id | idea | estimate | risk | status |
| --- | --- | --- | --- | --- |
| A1 | **asm dispatcher**: replace the C switch with a hand-written loop + jump table, keeping a C fallback per case | **−400 … −700 B** (P50 measured 278 B for loop + 4 bodies; the projection falls short of the 719 B upper bound because the wrap-checked operand sequence is 5 instructions per two-operand body) | high: board-only verification, `vm_switch`/`PAUSE` must spill any new pinned register | **open, biggest single prize** |
| A2 | **extend the table-driven kernel** beyond the 10 same-shape ops already converted (−280 B measured) | **−80 … −200 B** | low: same shape as the shipped one | open — the census of shape-distinct bodies is the map |
| A3 | **register-resident VM**: TOS, SP, RSP, W, IP, `mem` base in fixed registers instead of memory cells | **−150 … −300 B** *and* faster (removes ~6 loads/stores per dispatch) | medium: interacts with A1 and with the task snapshot (136 B must still spill) | **open, best risk/reward** |
| A4 | **subroutine-thread** single-accessor primitives (`@`, `!`, `C@`, `C!`) into the dispatch tail | −40 … −80 B | low | open |
| A5 | **superinstructions** for the hot pairs (`DUP @`, `OVER +`, `SWAP DROP`, `DUP 1+`) | −30 … −80 B text | low; also shrinks the code area (§6 E6) | open |
| A6 | **merge primitive epilogues** (`PUSH`/`RPUSH`/`POP` tails) | −20 … −40 B | low | partly done (one tail merged for −52 B) |
| A7 | **2-byte dispatch table entries** (case offset instead of 4 B pointer) | −134 B **rodata**, `+4` B text for the add | low | open |
| A8 | **cold-bucket call**: move the ~20 least-used primitives behind one call site | −100 … −150 B | medium: P50 measured that a call *per token* loses; one call site for cold cases does not | open |
| A9 | **drop the per-token checkpoint write** (`P27` resumability) | −30 … −60 B | **rejected**: it is the resumability contract for task switching | — |
| A10 | per-function `optimi**ze("O2")`** on `vm_enter` only | ±0 … −40 B | low | measure |
| A11 | `__builtin_expect` on the error/`default` paths, cold-section placement | −10 … −30 B | low | measure |
| A12 | remove `vm_depth`/`vm_max_depth`/`vm_faults` counters | −20 … −40 B | **excluded**: `tests/deep.fs` depends on the depth measurement | — |

## 3. Ideas — `.text`, everything else (2 620 B)

| id | idea | estimate | risk |
| --- | --- | --- | --- |
| B1 | `main` **890 B** — audit the every-wake publish block; move to one `noinline` helper, or fold the four `repl_*` stores into a table-driven loop | −100 … −200 B | low; must keep "republish every wake" (E-079) |
| B2 | `word` **170 B** + `number` **126 B** — share the tokeniser: `number` currently re-scans characters `word` already classified | −60 … −120 B | low |
| B3 | `blk_xfer` **144 B** — hand-written already; tighten the poll loop and the checksum | −20 … −40 B | low |
| B4 | `mkhdr` **130 B** — the 3-byte write is `wr16` + `wr8`; add a single `wr24` | −20 … −40 B | low |
| B5 | `find` **106 B** — read the two hash bytes with one `lhu` at `h+1` (both hash halves are adjacent) | −20 … −30 B | low |
| B6 | `vm_switch` 74 + `vm_next_ready` 62 + `vm_task_leave` 70 — a fixed 2-slot round robin is a pair of branches, not a search | −60 … −100 B | low (NTSK is compile-time 2) |
| B7 | `pl_emit` **66 B** — ring write with drop policy; needs the drop counter exported anyway | ±0 … −20 B | low |
| B8 | `err` 54 B + `errf_msg` — already shared; remaining call sites cost `li a0,code` (68 B total, unremovable) | **0** | measured |
| B9 | count the `__riscv_save_*`/`restore_*` helpers and inline only the hot ones | −20 … −40 B | low |

## 4. Ideas — `.rodata` (340 B)

| id | idea | estimate |
| --- | --- | --- |
| C1 | dispatch table → 2-byte offsets (= A7) | **−134 B** |
| C2 | pack the P54 op table from 4 B to 2 B entries | −28 B |
| C3 | message table is already 1 B/code | 0 |

## 5. Ideas — machine-level, from the CPU research

| id | idea | estimate | risk |
| --- | --- | --- | --- |
| F1 | **reserved base register**: `-ffixed-x31` plus a global register variable holding the RTC RAM base, so `mem[i]` becomes `addi + lbu` instead of `lui + add + lbu` | **−100 … −200 B** (120 `lui` = 480 B is the ceiling; most are already hoisted, so the realistic slice is ¼–½) | medium: GCC may ignore or mis-handle `-ffixed` on this target — measure before designing around it |
| F2 | `gp` linker relaxation with a proper `__global_pointer$` in the ULP link script | ~0 given F1 measures the same effect honestly | low |
| F3 | use `c.jr`/`c.jalr` for tails and returns | −10 … −20 B | low |
| F4 | RVC-aware asm scheduling in A1/A3 (pick compressed forms GCC misses) | −20 … −50 B | low, and only inside A1/A3 |
| F5 | RVC density in general | **already saturated** — 933/1 698 instructions are 2-byte | closed |
| F6 | `-mrelax`, `-Oz`, `-flto`, `-fno-builtin`, `-fno-stack-protector` | **0 B, measured** | closed |

## 6. Ideas — `mem[]` layout (this is where features live, so each is checked twice)

| id | idea | estimate | feature cost |
| --- | --- | --- | --- |
| E1 | **fold the code field into the header**: `170 B` of 2-byte code fields exist only to say "DOCOL / DOVAR / DOCON / primitive id". The header already has spare bits (§ the census) | **+85 … +170 B app space**, minus ~40 B text to decode | none — same words, same semantics; needs `xt` → "start of body" discipline |
| E2 | **2-byte headers** | **impossible**: need `xt` (10 bits) + imm (1) + hash. An 8-bit hash over 85 words has ~14 expected collisions; a 10-bit hash leaves no room for `xt` | — |
| E3 | shrink the system-variable block | **0 B, measured**: bytes 0–21 are variables, `PAD` 24–55, `DICT` 56 — nothing is free | — |
| E4 | **small-literal token** (`LIT8` for 0–255): saves 3 B per small literal in the baked image and in user code | +20 … +40 B | none (a `LIT` for large values still exists) |
| E5 | **branch operands to 1 byte** (relative to IP, ±127) | +12 B (6 operands × 2 B) | none, but needs a range check |
| E6 | **superinstruction tokens** (= A5): each costs ~30 B text and saves 2 B per use; worth it only for pairs used ≥ 20× | +30 … +80 B | none |
| E7 | block window 128 B → 64 B | +64 B | **capacity**: 8 blocks × 64 B instead of 128 |
| E8 | 16-bit data cells | would halve user data | **feature**: the acceptance checksums (`832501`, `67000`) are 32-bit values |
| E9 | compress the token stream | ceiling **118 B**, measured NO-GO (prototype: −44 B for +352 B) | — |

## 7. Ideas — structure and tradecraft

| id | idea | estimate | note |
| --- | --- | --- | --- |
| G1 | unify the two task VM snapshots with the live VM (one 136 B snapshot instead of `tsk[2]` + `vm_live`) | −136 B | medium risk: a switch must still spill; interacts with A3 |
| G2 | move the block window into `.bss` | **0 B** | 1:1 pool either way |
| G3 | `line.fs` loaded on demand from a block instead of baked | −? (small) | adds a boot dependency; the block server needs the HP awake |
| G4 | speed-for-space swaps: any of A1–A3 trade cycles for bytes, and each also *gains* cycles | — | the only trades worth making |
| G5 | paging / overlays of the dictionary | **rejected earlier**: 888 B dictionary + 2 520 B of C | — |
| G6 | primitive subset | **excluded**: removes words (the feature rule) | measured −344 B, not shippable under this brief |
| G7 | `NTSK` 3→1 | **excluded**: removes concurrency | measured −358 B, not shippable under this brief |

## 8. Ranked shortlist

Rank = expected bytes per week of work, discounted by verification risk. Everything here keeps every word.

| # | idea | bytes | effort | why this rank |
| --- | --- | --- | --- | --- |
| 1 | **E1** code field → header bits | +85 … +170 | 1 day | biggest per-unit risk; census already proved the 170 B exists |
| 2 | **A3** register-resident VM | −150 … −300 | 2 days | wins bytes *and* cycles; the 20 idle registers are free |
| 3 | **A7/C1** 2-byte dispatch table | −134 (rodata) | 2 h | mechanical |
| 4 | **A1** asm dispatcher | −400 … −700 | 3–5 days | biggest absolute prize, but board-only validation and it subsumes A3 |
| 5 | **A2** extend the table kernel | −80 … −200 | 1 day | proven shape, incremental |
| 6 | **B1/B2/B6** audit `main`, share the tokeniser, flatten the scheduler | −220 … −420 | 2 days | many small, low-risk wins in one pass |
| 7 | **F1** reserved base register | −100 … −200 | 1 day | needs a measurement first; may be 0 |
| 8 | **A8** cold bucket for rarely-used primitives | −100 … −150 | 1 day | needs the per-primitive frequency data |
| 9 | **A5/E6** superinstructions | −30 … −80 text, +30 … +80 app | 1 day | only for pairs measured ≥ 20 uses |
| 10 | **G1** one task snapshot | −136 | 1 day | real, but touches the resumability contract |

## 9. Falsifiers — what would kill each top idea

| idea | dies if |
| --- | --- |
| E1 | decoding the code-field kind from the header costs more text than the 85–170 B it frees; or any primitive is reachable without a header (the `V_XLIT`/`V_XEXIT`/`V_XSTR` xts are exactly such words — they are compiled by C, so their "code field" may be the only thing describing them) |
| A3 | the task snapshot must spill every pinned register on switch, eating the win; or GCC cannot be made to keep `mem`'s base in a fixed register |
| A1 | the C fallback per case reintroduces the call cost P50 already rejected; or the fallback cannot express the five bodies that `continue`/`return` |
| A2 | the remaining bodies are all shape-distinct — the census says 10 of 64 are same-shape, so the next tranche is smaller by construction |
| B1 | the publish block is already minimal and `main` is dominated by the wake path that cannot move |
| F1 | `-ffixed-x31` exceeds the register pressure and GCC spills something else, netting ≥ 0 |

## 10. Verification protocol — every idea, no exceptions

1. **Twin build** (`measure.sh`): the baseline must reproduce the flashed `.text` **sha256** before any delta
   is quoted. A delta from an unverified twin is not a measurement.
2. **Host suite** `tests/run.sh` green — and any new check **mutation-tested** (break it, watch it fail).
3. **Re-bake** at the new `MEMSZ` (bake and build must agree on `MEMSZ` *and* every dictionary-shaping flag).
4. **Board** — this is the part the host cannot answer: `10 FIB .` → 55, `15 FIB .` → `ERR_STACK`,
   `0 BLOCK .`, a `SAVE`/`BLOCK C@` round trip, two tasks printing, and `2 3 + .` afterwards.
5. **Bench** `bench/run.sh` — results must be *identical*; DISP may change only where the idea changes
   instruction counts, and the change must be explained.

## 11. Already-settled ground (do not re-litigate)

| idea | measurement | verdict |
| --- | --- | --- |
| 1-byte tokens | ceiling 118 B; prototype −44 B for **+352 B** | NO-GO |
| merged rings | 64 + 128 already one contiguous 192 B block | NO-GO |
| unchecked accessors | −58 B, writes outside `mem[]` | refused |
| `-fno-jump-tables` | +356 text / −268 rodata = **+88 net** | refused |
| `-Oz`, `-flto`, `-fno-builtin`, `-fno-stack-protector` | 0 B | closed |
| `NTSK` 3→1, primitive subset | −358 / −344 B, features removed | excluded by the brief |
| `SD 32` | +394 B | rejected; F-120 is a bounds bug, not a depth bug |
| paging / overlays | 888 B dictionary + 2 520 B C | rejected |

## 12. The shape of what remains

`.text` is 63 % of the pool and the dispatcher is 47 % of `.text`. Everything else combined — the whole rest
of the C — is smaller than `vm_enter`. So the ranking above is really one statement:

> **The remaining prize is in the dispatcher, and the dispatcher is where hand-written assembly plus 20 idle
> registers beats what a compiler will do for bytecode.** A1 + A3 together are the only pair whose ranges
> overlap enough to plausibly double application space again (727 → ~1 300 B) without removing a word.

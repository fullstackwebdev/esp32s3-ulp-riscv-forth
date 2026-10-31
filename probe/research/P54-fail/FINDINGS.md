# P54-fail — do the error/message call sites cost bytes?

**Verdict up front.** Measured, not projected:

| question | answer |
|---|---|
| do the message sites cost bytes? | yes — **120 B** for the 17 message sites that exist in the image, **134 B** including the call to `err()` and the one shared emit tail |
| is the **~120 B** guess reclaimable? | **no, and this is the whole result.** 120 B is the *gross* size of those sites' instructions. `li a0,<code>` alone is 68 B of it. All three shapes the task proposed are measured: (a) **+8 B**, (b) **−16 B but unshippable**, (b1, the shippable half of b) **+12 B**, (c) **−48 B** |
| is there anything worth taking? | yes, but it is **not the call sites**: one six-way code-selection table in `blk_errmsg()` is duplicated work that GCC compiled into a 26 B dispatch + a 24 B jump table. Hoisting the tail measures **−48 B** (`var_c`), or **−52 B** with the `errf = 1` store folded into one helper |

Nothing in this report is estimated. Every byte below comes from `objdump -d` on a twin whose `.text` sha256 equals the shipping image's, and every pool number is the end of the last placed section of the linked ELF.

---

## 1. Method, and the proof that the twin is the shipped machine

`./measure.sh <name>` (from agentA, extended here) recompiles `src/ulp_repl.c` with the **shipping** ULP flags and the **shipping** link line, from the commands IDF itself recorded, and the object list minus our own. `SRCDIR=` points it at a variant copy.

```
$ ./measure.sh base
base                   baseline twin .text == shipped .text (sha=5e9434a7c6096071)
base                   elf .text=5252  .rodata=308   .data=1416   .bss=877   | sha=5e9434a7c6096071
base                   pool span=7853 B
$ objcopy -O binary --only-section=.text probe/repl/build/esp-idf/main/ulp_main/ulp_main.elf out/ship.text
$ sha256sum out/ship.text out/base.text
5e9434a7c6096071…  out/ship.text        <- the flashed image
5e9434a7c6096071…  out/base.text        <- the twin
```

`.text` 5 252 and pool **7 853** reproduce `../SHARED_BRIEF.md` exactly, and `src/` is byte-identical to `probe/repl/src/` (`diff -r`), so the twin is the shipped source compiled by the shipped flags. Every row below is a delta from this twin.

The sha comparison used to be an operator step (read two hashes, compare by eye). It is now an assertion inside `measure.sh`: the `base` row **refuses to print a pool span** unless its `.text` sha256 equals the shipped ELF's, because a delta from a twin that is not the flashed machine is not a measurement. Mutation-tested by compiling the wrong tree as the baseline — `SRCDIR=variants/var_c_shared_tail ./measure.sh base` prints

```
measure: BASELINE MISMATCH — twin .text sha=1f44e980c0161b13, shipped .text sha=5e9434a7c6096071
measure: no delta from this twin is a measurement. Fix the compile line before quoting one.
```
and exits 1. (It also overwrites `out/base.*` with the wrong build — which is why the assertion is worth having rather than remembering: `./measure.sh base` has to be re-run before the next delta.)

Two measurement tools were written for this probe (both in `tools/`):

* `sites.py <elf> --table` — maps every instruction to a source line with `addr2line` and prints one row per message site: the `li a0,<code>` **plus** the transfer that follows it, in encoded bytes. It follows a one-instruction jump, because the compiler sends six of the sites through one shared tail.
* `difftest.sh <variant>` — builds the baseline and the variant host engines with `tests/run.sh`'s exact flags and compares the **raw byte stream** of every `tests/*.fs` plus `src/line.fs`. Raw bytes, not expanded text: the transcript is a projection of those bytes through `src/msg_expand.h`, so a changed code that still expands to the same sentence today is a wire change.

### A measurement trap this probe hit, and fixed

`measure.sh`'s old row printed only `.text/.rodata/.data/.bss`, and GCC puts the byte table that `var_c` generates in its **own** section (`.srodata.CSWTCH.420`, 6 B) because of `-fdata-sections`. A variant can therefore look 24 B lighter while 6 B simply moved into a section the row never printed. `measure.sh` now also prints

```
pool span = max(addr+size) over all placed sections
```

which is the number that becomes application space. All deltas below are `span` deltas. For `var_c` that is the difference between "−56 B" (text+rodata only, wrong) and "**−48 B**" (the truth: −32 text, −24 rodata, +6 `.srodata`, +2 alignment re-pad).

### A second harness trap: two `difftest.sh` runs at once

`difftest.sh` writes fixed paths (`artifacts/diff/base.raw`, `var.raw`) and `cmp`s them. Two runs in parallel therefore compare **one run's baseline against the other run's variant**, and the output is a spurious `DIFF blocks_noserver` whose "changed" bytes are `addr.fs`'s `0000`. That happened here while pricing `var_c` and `var_f` at the same time; it is indistinguishable from a real diagnostic change until you read the bytes. `difftest.sh` now takes `flock -n` on `artifacts/diff/.lock` and exits 3 with "another run holds … run them one at a time" instead of reporting. Mutation-tested by holding the lock outside:

```
$ flock artifacts/diff/.lock -c './tools/difftest.sh variants/var_c_shared_tail'
difftest: another run holds artifacts/diff/.lock — run them one at a time    (rc=3)
```

### Independent re-run of every numbered claim

Every row in §3–§7 was re-derived from scratch in a second session, after the first attempt's `FINDINGS.md` already existed, to make sure the report is reproducible rather than transcribed:

| claim | how it was re-checked | result |
|---|---|---|
| twin == shipped `.text` | `objcopy -O binary --only-section=.text` on the shipped ELF, `sha256sum` vs `out/base.text` | both `5e9434a7c6096071…` |
| shipped source == probed source | `diff -r src probe/repl/src` | identical, no output |
| pool span 7 853 | `./measure.sh base` | 7853 |
| 20 `msg(MSG_*)` sites, 14 + 6 | `grep -c` per file | 14 + 6 |
| 6 `err()` call sites in source, 3 in image | `grep -n '\berr()'` + `sites.py` | 6 source, 3 in image (one serves 4 source sites) |
| per-site table (§3) | `./measure.sh dbg -g` (sha unchanged) + `./tools/sites.py out/dbg.elf --table` | identical 20 rows, `TOTAL 130 B in 22 transfer instructions` |
| `err()` = 54 B | `nm -S` | `00000556 00000036 t err` |
| `.rodata` jump table = 24 B | `objdump -s -j .rodata` at `0x15a0` | 6 × 4 B words `0x0fe6,0x0fe0,0x0fec,0x0fda,0x0fd4,0x0fce` |
| six-way dispatch = 26 B | `objdump -d` `0x0fb6..0x0fcc` | `addi/li/bltu/lui/slli/addi/add/lw/jr` = 26 B |
| `var_d` helper = 16 B | `nm -S` | `0000058c 00000010 t errf_msg` |
| variants table (§5) | `measure.sh` per variant, all 8 rows | every `.text/.rodata/span` reproduced to the byte |
| suite (§5–§6) | `tests/run.sh` on `src/` and on all 7 variants | 11 PASS each; mutant FAILs `blocks.fs` + `block error codes` |
| diagnostics byte-identical | `difftest.sh` on `var_c`, `var_f`, mutant | 9 × SAME, code set `0x88 0x89 0x8a 0x8b 0x8c 0x8e 0x8f`; mutant DIFFs `blocks` |

Two numbers in the first draft of this report did not survive that pass and are corrected below: the `(d)` decomposition in §5 (it is 22 B of stores against a 16 B helper ⇒ **−6 B of `.text`**, of which 2 B is re-eaten by section alignment in the span) and the case count of `blkerr_test` in §6 (8, not 9).

---

## 2. The claim, audited before anything was measured

The task says: *20 `err(ERR_*)`/`msg(MSG_*)` sites (14 `src/uforth.c`, 6 `src/ulp_repl.c`)*.

* `msg(MSG_*)`: **20 sites, and the split is exactly right** — 14 in `uforth.c` (548, 696–701, 707, 712, 754, 818, 867, 872, 873), 6 in `ulp_repl.c` (173, 177, 344, 347, 384, 431).
* `err(ERR_*)`: **does not exist any more.** `err()` takes no argument; it prints the unknown word from PAD plus `"?\n"`. There is no `ERR_*` code for it. The label is left over from the pre-P52 string design.
* `err()` has **6** call sites, not zero and not part of the 20: `uforth.c` 556, 747, 749, 811, 846 **and `src/p31_cases.inc:186`** (the tick case inside the inlined dispatcher). So the source has **26** call sites, not 20.
* Not all of them are in the image. `forth_quit()` (`uforth.c:859`) is the host-only REPL loop; `--gc-sections` drops it from the ULP, so its three message sites (867, 872, 873) cost **0 B** in the shipping image and are also never executed by the suite (it runs with `-i` off).

**In the shipping image: 20 sites.** 17 `msg` + 3 `err`. The three `err` sites serve six source sites, because GCC cross-jumped four callers onto one block:

| in-image site | serves (source) |
|---|---|
| `0x0596 jal err` | `uforth.c:556` (`mkhdr`) |
| `0x0cd4 jal err` | `uforth.c:747`, `:749` (`vm_spawn_name`), `:811` (`default: err()`), `p31_cases.inc:186` |
| `0x1342 jal err` | `uforth.c:846` (`interpret`) |

That is not a curiosity — it is the answer to variant (c) before we write any code: the compiler already hoists identical tails, including across three `err(); return -1;` sites whose return value it proved unused (`case P_SPAWN: vm_spawn_name(); break;`).

---

## 3. What the 20 in-image sites actually cost (measured, per site)

`./tools/sites.py out/dbg.elf --table` (`out/dbg.elf` = the `-g` twin, `.text` sha unchanged at `5e9434a7c6096071`):

| site | code | argument | transfer | bytes | note |
|---|---|---|---|---|---|
| `0x0596` | — (`err`) | — | `c.jal` 2 | **2** | in range → compressed call |
| `0x05c4` | `0x87` ERR_DICT | 4 | `c.jal` 2 | **6** | |
| `0x0686` | `0x89` ERR_STACK | 4 | `c.jal` 2 | **6** | the stack resets sit *between* the `li` and the call |
| `0x0cd4` | — (`err`) | — | `jal` 4 | **4** | 4 source sites |
| `0x0f62` | `0x8f` ERR_RANGE | 4 | `jal` 4 | **8** | out of `c.jal` range |
| `0x0f7e` | `0x8e` ERR_DIRTY | 4 | `jal` 4 | **8** | |
| `0x0fce` | `0x8a` ERR_BUSY | 4 | `j` 2 → tail | **6** | shared tail |
| `0x0fd4` | `0x8b` ERR_NO_SERVER | 4 | `j` 2 → tail | **6** | shared tail |
| `0x0fda` | `0x8c` ERR_CRC | 4 | `j` 2 → tail | **6** | shared tail |
| `0x0fe0` | `0x8d` ERR_BUFOVER | 4 | `j` 2 → tail | **6** | shared tail |
| `0x0fe6` | `0x8e` ERR_DIRTY | 4 | `j` 2 → tail | **6** | shared tail |
| `0x0fec` | `0x90` ERR_UNNAMED | 4 | `j` 2 → tail | **6** | shared tail |
| `0x1060` | `0x88` ERR_TASKS | 4 | `jal` 4 | **8** | |
| `0x1196` | `0x85` BANNER | 4 | `jal` 4 | **8** | |
| `0x1234` | `0x86` TASK_STACK | 4 | `jal` 4 | **8** | |
| `0x12b6` | `0x84` OK | 4 | `jal` 4 | **8** | |
| `0x1342` | — (`err`) | — | `jal` 4 | **4** | |
| `0x13a0` | `0x83` UNDERFLOW | 4 | `jal` 4 | **8** | |
| `0x13ca` | `0x81` ERASE | 4 | `jal` 4 | **8** | |
| `0x1408` | `0x82` LINE_TOO_LONG | 4 | `jal` 4 | **8** | |
| **total** | | **68** (17 × `li`) | **62** (9 × 2 B + 11 × 4 B) | **130** | the 17 `msg` rows are 68 + 52 = **120 B**; the 3 `err` calls add 10 B; one shared `jal pl_emit` (4 B) sits behind the six `0x8a..0x90` cases → **134 B of site code** |

Distribution, not just a total:

```
 2 B  x 1 site      (err, compressed call)
 4 B  x 2 sites     (err, call out of c.jal range)
 6 B  x 8 sites     (li 4 + j 2 to the shared tail, and li 4 + c.jal 2)
 8 B  x 9 sites     (li 4 + jal 4 — every site more than 2 KiB from pl_emit)
--------------------
130 B in the sites + 4 B of shared call = 134 B
```

**No `li` can be cheaper than 4 B.** The codes are `0x81..0x90`; `c.li` reaches only −32..+31, and `addi a0,zero,imm` is 4 B as well. 68 B of the 120 is therefore irreducible *as long as a distinct code has to be materialised per site*, and 52 B is the transfer. The nine 8 B rows are 8 B rather than 6 B purely because `pl_emit` at `0x514` is more than 2 048 B from them — call range, not duplication (and `-mrelax` cannot help: there is nothing in range to compress *to*).

The rest of the diagnostics layer, same method:

| item | bytes | where |
|---|---|---|
| the 20 sites above | 134 | `.text` |
| `err()` body (word from PAD + `?` + `\n` + `errf=1`) | 54 | `.text`, 20 insns |
| three explicit `errf = 1;` statements (548, 754, 818) | 22 | `.text`, `c.lui`+`sb` each, plus a `c.li` at two of them (8 + 6 + 8 — the `NTSK` site already holds 1 in a register) |
| `blk_errmsg` 6-way selection | 26 | `.text` (range check + jump-table load + `jr`) |
| its 6-entry jump table | 24 | `.rodata` @ `0x15a0` |
| **total** | **260 B** | 3.3 % of the 7 853 B pool |

The `~120 B` guess is therefore **the gross size of the message sites' own instructions, not a saving.** As a saving it is refuted by measurement: of that 120 B, 68 B is the code constants, 12 B is jumps into a tail that already serves six cases, and the remaining 40 B is one call per site to the only emitter that exists.

---

## 4. What is genuinely duplicated

1. **`errf = 1` three times** (548, 754, 818): 8 + 6 + 8 = 22 B, each a `c.lui`+`sb` (plus `c.li` twice) because `errf`'s address has to be materialised again. Real duplication. → `var_d`.
2. **The six-way status→code selection in `blk_errmsg`.** This is the only large one: the chain is compiled to a range check plus an indirect `jr` through a **24 B `.rodata` jump table**, and each of the six cases is a `li` + `j` into a shared emit. 50 B to choose one of six bytes. Every other message site in the image is a constant. → `var_c`, `var_e`.
3. **Repeated epilogues / PAD-format setup: not duplicated.** GCC already merges them: four `err()` callers share one block, six `msg` cases share one `jal pl_emit`, every `err(); return X;` tail is a 2 B `j __riscv_restore_N`, and `err()` itself is a single 54 B function called by three sites rather than inlined five times. There is nothing left for a human to hoist — the measurement is in §5 (a) and (c).

---

## 5. Variants, measured

Every row: a full copy of `src/` in `variants/<name>/` (never an in-place edit), `SRCDIR=` to `measure.sh`, and the whole suite.

| variant | shape | `.text` | `.rodata` | `.srodata` | **pool span** | **Δ span** | suite |
|---|---|---|---|---|---|---|---|
| `base` | shipping | 5252 | 308 | — | **7853** | — | 11 PASS |
| `var_a_msg_noinline` | (a) one noinline `msg(u8)` taking the code in a register | 5258 | 308 | — | 7861 | **+8** | 11 PASS |
| `var_b_err_noreturn` | (b) `noreturn` `err()` — **UB, upper bound only** | 5234 | 308 | — | 7837 | **−16** | 11 PASS (!) |
| `var_b1_err_returns` | (b1) shippable half of (b): `err(ret)` returns the caller's value, so `return err(0)` is a sibling call | 5264 | 308 | — | 7865 | **+12** | 11 PASS |
| `var_c_shared_tail` | (c) one `msg()` call behind the six-way selection | 5220 | 284 | 6 | 7805 | **−48** | 11 PASS |
| `var_d_errf_msg` | fold `msg(X); errf = 1;` into `errf_msg(X)` | 5246 | 308 | — | 7849 | **−4** | 11 PASS |
| `var_e_blk_arith` | compute the code from `st` instead of selecting it | 5238 | 284 | — | 7817 | **−36** | 11 PASS |
| `var_f_c_plus_d` | (c) + (d) | 5214 | 284 | 6 | 7801 | **−52** | 11 PASS |
| `mut1_crc_as_bufover` | MUTANT (`0x8c`→`0x8d`) — instrument check, not a candidate | 5214 | 284 | 6 | 7801 | −52 | **FAIL** (`blocks.fs` + `blkerr_test`) |

Read the deltas off the `span` column only; see §1 for why the four named sections are not the image. Where a `.text` delta and a span delta differ by 2 B it is section padding, and it is real: base `.text` 5 252 is 4-aligned, so `.rodata` starts at 5 252; a `.text` of 5 246 (`var_d`), 5 258 (`var_a`) or 5 214 (`var_f`) pushes `.rodata` — and behind it `.data` and `.bss` — to the next 4-byte boundary. Hence `var_d` = −6 `.text` but −4 pool, `var_a` = +6 `.text` but +8 pool, `var_b` = −18 `.text` but −16 pool.

### (a) one `noinline` helper taking the code in a register — **+8 B, and it is the wrong question**

`msg()` *is* that helper: `static void msg(u8 c) { pl_emit((int)c); }`. Because it is a one-line wrapper, the shipped build inlines it and every site becomes exactly `li a0,code; <call pl_emit>` — the shape (a) asks for, with the code in a register, one call. Forcing it to stay a function (`__attribute__((noinline))`) adds the wrapper's own tail call: **+8 B of pool** (+6 `.text`, +2 re-pad), and one extra call/ret per message. There is nothing to share because there is nothing duplicated: 68 B of arguments + 52 B of calls, all of them distinct sites.

### (b) a `noreturn` helper — **the upper bound is −16 B, and it is not shippable**

`err()` must **return**: it sets `errf` and the outer interpreter unwinds to the prompt, which is why a bad line costs the line and not the session. A genuinely `noreturn` `err()` could only mean *halt*. To price the most that shape could ever save, `err()` was declared `noreturn` while still returning — the compiler then deletes every instruction after each of the 3 call sites. Result: **−16 B**. That is the ceiling, it is 16 B, and it is paid for by turning every named error into a dead machine. Reject.

Two things worth recording about that row: it is UB, and **the suite still passes 11/11** with it — the host tests cannot see the deletion, which is the reason it must never be measured into a plan and then quietly adopted.

The shippable half of (b) — `err()` returning the caller's value so `return err(0);` becomes a sibling call and the caller's epilogue disappears — is `var_b1`: **+12 B**. Why: the three sites that are *shared* already (the `errf`-unwind block, the dispatch `default`) cannot tail-call and each pays +2 B for the argument load, while the epilogues that would be removed are already 2 B shared jumps. A loss.

### (c) hoisting the shared tail — **−48 B. This is the only thing that measured as a win.**

The compiler had already hoisted the *call*; what it had not done is stop **storing** the code six times. Rewriting the chain to choose a code and emit once:

```c
u8 c = MSG_ERR_UNNAMED;
if (st == BK_BUSY)          c = MSG_ERR_BUSY;
else if (st == BK_NOSERVER) c = MSG_ERR_NOSERVER;
else if (st == BK_CRC)      c = MSG_ERR_CRC;
else if (st == BK_BUFOVER)  c = MSG_ERR_BUFOVER;
else if (st == BK_DIRTY)    c = MSG_ERR_DIRTY;
msg(c);
```

lets GCC emit a range check + a **6-byte** `.srodata` byte table + one `lbu` + the one shared `jal pl_emit`, instead of a 26 B dispatch + a 24 B `.rodata` jump table + six `li`+`j` pairs. Measured −32 `.text`, −24 `.rodata`, +6 `.srodata`, +2 re-pad ⇒ **−48 B of pool**.

Note what this is and is not: **it is not a call-site change.** The five other message clusters and all three `err()` sites are untouched, because measurement says there is nothing there to take.

### (d) folding the error-flag store — **−4 B of pool, −6 B of `.text`**

`errf_msg(u8)` costs 16 B (`__riscv_save_0`/`__riscv_restore_0` + `jal` + `lui`/`li`/`sb` + `j`, measured: `0000058c 00000010 t errf_msg`) and removes 22 B of repeated stores across three sites — 14 B → 6 B at `mkhdr`, 14 → 8 at the `NTSK` site (its call was already out of `c.jal` range), 14 → 6 at the stack-overflow site: **−22 + 16 = −6 B of `.text`**. The span moves only **−4 B**, because `.text` 5 246 is not 4-aligned and `.rodata` therefore re-pads by 2 B (`.text` 5252 → 5246, `.data` @5560 → @5556). Quoting `−6` would be quoting text and calling it pool.

It also adds a call and a frame to three error paths. Keep it only if the last 4 B matter.

### (e) computing the code instead of selecting it — **−36 B, and rejected on risk**

The six codes are contiguous and the five reachable statuses are nearly so, so `msg(MSG_ERR_BUSY + f(st))` removes the table entirely (`.rodata` −24, `.text` −14, +2 re-pad ⇒ **−36 B of pool**). But `BK_*` is *not* linear — `BK_BUSY=-2 … BK_DIRTY=-7` skips `-5` (`BK_RANGE`), which is a client-side code `blk_xfer()` never returns — so the variant needs three range tests plus an explicit hole-skip. That is a second encoding of the enumeration, exactly the R6 failure: the day someone renumbers `BK_*` the ULP starts naming the wrong failure. It is also *smaller* than (c) by 12 B. Rejected in favour of (c), which is bigger, and whose predicates are byte-for-byte the shipped ones.

---

## 6. Diagnostics are byte-identical (the point of one-byte codes)

Three independent checks, in increasing strength:

1. **`tests/run.sh` 11/11 on every shippable row.** The .fs goldens pin the *text*: `deep.fs` → `ERR_STACK`, `ntsk.fs` → `ERR_TASKS`, `blocks.fs` → `ERR_DIRTY -7` / `ERR_RANGE -5` / `ERR_CRC -4`, `blocks_noserver.fs` → `ERR_NO_SERVER -3` / `ERR_BUSY -2`, `addr.fs`, `lookup.fs`, `semantics.fs`, `suite.fs`, plus the ring drain and the unknown-code check.
2. **`tools/difftest.sh`** — baseline vs variant, **raw byte streams** over every `.fs` plus `src/line.fs`: all `SAME`, and the set of message codes emitted is identical (`0x88 0x89 0x8a 0x8b 0x8c 0x8e 0x8f` — 7 of the 16). Not "still an error": the same bytes.
3. **A new test, `tools/blkerr_test.c`**, wired into `tests/run.sh`, which calls `blk_errmsg()` with **8 cases** — the five named statuses plus `BK_RANGE`, `BK_OK` and `-99` (the last three must all fall through to `ERR_UNNAMED`) — and asserts the exact code byte. It exists because the Forth-level suite can reach only three of the six (`ERR_BUFOVER` needs a misplaced buffer, `ERR_UNNAMED` needs a status no layer returns), i.e. the very branches (c) and (e) rewrite were the untested ones. It asserts `0x8a..0x90`, not expanded text: `msg_expand.h` is the *other* copy of the mapping, so a text-level check passes even when the ULP chose the wrong code.

**Mutation-tested** (`variants/mut1_crc_as_bufover`, `ERR_CRC`→`ERR_BUFOVER`):

```
$ ./tools/difftest.sh variants/mut1_crc_as_bufover
DIFF  blocks
-  53 140  45  52  10        (raw bytes: … 140 '?' …)
+  53 141  45  52  10
DIFF  message-code set differs
$ SRCDIR=variants/mut1_crc_as_bufover ./tests/run.sh
FAIL  blocks.fs
FAIL  blk_errmsg(-4): emitted 1 byte(s), first 0x8d, want one byte 0x8c  [BK_CRC]
FAIL  block error codes
```

Both instruments bite; the mutant is kept in `variants/` as the record.

---

## 7. The diff of the winner

`variants/var_c_shared_tail/uforth.c` (**−48 B**, 11/11, differential identical):

```diff
--- src/uforth.c
+++ variants/var_c_shared_tail/uforth.c
@@ -693,12 +693,16 @@
 
 static void blk_errmsg(i32 st)
 {
-    if (st == BK_BUSY)         msg(MSG_ERR_BUSY);
-    else if (st == BK_NOSERVER) msg(MSG_ERR_NOSERVER);
-    else if (st == BK_CRC)      msg(MSG_ERR_CRC);
-    else if (st == BK_BUFOVER)  msg(MSG_ERR_BUFOVER);
-    else if (st == BK_DIRTY)    msg(MSG_ERR_DIRTY);
-    else                        msg(MSG_ERR_UNNAMED);
+    /* GUARDRAIL: the six-way chain used to store the code six times behind a 24 B .rodata jump table
+     * (26 B of dispatch + 36 B of `li`+`j`); choosing the code first and emitting once measures −48 B
+     * of pool (P54-fail). The predicates and the UNNAMED fallback are the shipped ones. */
+    u8 c = MSG_ERR_UNNAMED;
+    if (st == BK_BUSY)          c = MSG_ERR_BUSY;
+    else if (st == BK_NOSERVER) c = MSG_ERR_NOSERVER;
+    else if (st == BK_CRC)      c = MSG_ERR_CRC;
+    else if (st == BK_BUFOVER)  c = MSG_ERR_BUFOVER;
+    else if (st == BK_DIRTY)    c = MSG_ERR_DIRTY;
+    msg(c);
 }
```

The predicates, their order and the fallback are the shipped ones; that is why `blocks.fs`, `blocks_noserver.fs` and the new `blkerr_test` are the right instruments and why no `_Static_assert` about enum layout is needed (unlike (e)).

`var_f_c_plus_d` is the same change plus `errf_msg()`, for **−52 B**; its full diff is in `variants/var_f_c_plus_d/uforth.c`.

### What it costs

* **Dispatch:** (c) removes one indirect `jr` per *failed* block operation and replaces it with up to five compares and one `lbu` — at most ~6 instructions, on a path that has just spent 2 740+ cycles in `blk_xfer`/`BLKWAIT`. The success path is unaffected (`if (st == BK_OK)` is before the call). No new call, no new frame. (d) adds one call + `__riscv_save_0`/`restore_0` per `errf` site.
* **Complexity:** the winner is a local rewrite of six lines with unchanged predicates. (e) would have raised complexity for less.
* **Risk:** none identified beyond the ordinary. The two unreachable-today branches (`ERR_BUFOVER`, `ERR_UNNAMED`) are covered by the new unit test, and the three reachable ones by the .fs goldens.
* **What it is not:** 48 B of app space *yet*. It is 48 B of **pool**; converting it needs a re-bake at a raised `MEMSZ` (`tools/bake.sh <MEMSZ>`), which is another lever's decision and was not run here. It would be 48 B of 354 B — 14 %.

---

## 8. What could not be measured, and must not be quoted as measured

1. **Cycles on the chip.** No board access in this probe (no `/dev/ttyACM*`, no flash, no `idf.py`). All dispatch statements above are host instruction counts, not ULP cycles.
2. **The pool → application-space conversion.** Not re-baked: `MEMSZ` and `src/image.h` are one decision and not mine to move. The number delivered is pool bytes.
3. **The six `msg()` sites in `ulp_repl.c` (`0x81..0x86`)** are not reachable from the host harness (the test driver calls `interpret()`, not the byte-pump loop), so "diagnostics unchanged" for those rests on the diff showing those lines are untouched, not on a run. (`forth_quit`'s three sites are not in the image at all — `--gc-sections` drops them — so there is nothing to compare.) The same is true of `0x8d`/`0x90` before the new unit test existed.
4. **`ERR_DIRTY` and `ERR_UNNAMED` as `blk_errmsg` cases** are unreachable in the shipping image (`blk_xfer` returns `BK_OK/BUSY/NOSERVER/CRC/BUFOVER` only, and `BK_DIRTY`/`BK_RANGE` are raised by `p_blk_block` itself). They are pinned by the unit test, not by an end-to-end path. Removing them is a further ~20 B that was **not taken**: an unreachable branch that silently prints nothing if it ever becomes reachable is a fail-loud violation, and the codes are an append-only wire format.
5. **`-mrelax` / call-range compression.** Nine sites pay 8 B instead of 6 B because `pl_emit` is >2 KiB away. Relaxation cannot help (nothing in range) and moving `pl_emit` is a link-order experiment, not a call-site change. Not attempted; noted because it is the only other 20 B visible in this area.

---

## 9. Reproduce

```sh
./measure.sh base                                  # asserts twin .text sha == shipped .text, span 7853
./measure.sh dbg -g && ./tools/sites.py out/dbg.elf --table   # per-site table (§3)
for v in var_c_shared_tail var_f_c_plus_d; do SRCDIR=variants/$v ./measure.sh $v; done
SRCDIR=variants/var_f_c_plus_d ./tests/run.sh      # 11 PASS
./tools/difftest.sh variants/var_f_c_plus_d        # all SAME, same code set
./tools/difftest.sh variants/mut1_crc_as_bufover   # DIFF on blocks — the instrument check
```

Three mutation tests of the instruments themselves (an instrument nobody has seen fail is not known to work):

```sh
SRCDIR=variants/var_c_shared_tail ./measure.sh base    # BASELINE MISMATCH, exit 1 — the sha assertion bites
flock artifacts/diff/.lock -c './tools/difftest.sh variants/var_c_shared_tail'   # "another run holds …", exit 3 — the lock bites
SRCDIR=variants/mut1_crc_as_bufover ./tests/run.sh     # FAIL blocks.fs + block error codes — the suite bites
```

Files: `measure.sh` (extended: `SRCDIR`, `pool span`, the baseline-sha assertion), `tools/sites.py`, `tools/difftest.sh` (extended: the `artifacts/diff/.lock` flock), `tools/blkerr_test.c`, `tests/run.sh` (SRCDIR + the new unit test), `variants/` (8 trees), `out/sites.txt`, `out/variants.txt`, `out/variants_verify.txt` (the §5 table re-measured row by row).

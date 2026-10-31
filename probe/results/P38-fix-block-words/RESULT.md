# P38 — Fix the three bugs and prove the block layer

| | |
| --- | --- |
| Result | **PASS, all five proofs against a prediction computed on the host.** The four fixes are in and each is proven by execution: **(a)** a compiled `IF … ELSE … THEN` nested four levels deep answers all **16/16** leaf values (plus a four-deep `BEGIN … UNTIL` nest, `81 = 3^4`), each against a value Python produced before the run; **(b)** the branch operand is read back out of `mem[]` — **2 bytes**, sitting at `token+2`, and its value equals the address of the `THEN`/`ELSE` sink, which the read-back walk *itself* produced as a token boundary (`B0`: `0BRANCH@05ce`, operand `@05d0 = 05d2`, target `05d2` = `EXIT`, i.e. exactly 4 B after the token); **(c)** `BLOCK` leaves **exactly one** cell (`sp` delta 0 measured in C), on success the buffer address `3584`, on a bad block the named `ERR_RANGE` with `BLKERR = -5` and **no request sent** (`blk_out = 0`); **(d)** `SAVE` returns its status — `1` cell, `0` on success with the *server's* copy at `blk0[9] = 0x42`, `-2` (named `ERR_BUSY`) on a failed save with `sp` unchanged and the dirty flag still set; **(e)** the overlap assertion fires by name — `ERR_BUFOVER(xfer): dict_here=3634 > block_buffer=3584`, and at P33's own pool (`MEMSZ=2304`, buffer 1792) with a test file that reaches `HERE=1962`: `ERR_BUFOVER`, status `-6` in Forth, and the fake server's copy stays `blk0[9]=09`, i.e. **the fetch never ran**, which is the difference between a named refusal and P33's silent dictionary overwrite. Suite **58/58**. The block layer measures **530 B** where the pre-fix file on the same prelude measured **412 B** (+118 B: the two `DUP`s that keep the returned value, `RAISE`'s corrected shape, the `ERR_RANGE` branch and two more named codes) — more than the probe's "a few bytes", and §1.8 accounts for it. P33's four execution case groups: **three pass, and the fourth (`save-blk0`) fails on its own dangling `AND`** — it only ever "passed" because the pre-fix `SAVE` left `sp` wrapped (§1.4). |
| Runs on | **host only** — `gcc -DHOST -DP33_NOPAGE -DP33_BLOCK -DMEMSZ=4096` (and a second binary at P33's `-DMEMSZ=2304` for proof (e)). Board untouched, no `/dev/ttyACM*` opened, nothing outside `probe/results/P38-fix-block-words/` written. Every command under `timeout`, none piped through `head`. |
| Time box | **overrun.** The fixes took one build; the *proofs* took eight, and two of them were wrong in the reader before they were right (a token in a body is an **xt**, not the code field; and a colon word's first token is `xt+2`). Both are recorded as GUARDRAILs — they are the same off-by-two the probe is about, and inventing them in the disassembler would have "proved" the bug. |
| Depends on | P37 (the four named defects), P33 (456 B layer, protocol 4/4), P31/P20 (token width, `,` vs `W,`) |
| Blocks | G2, the port: nothing is ported on top of these words until the proofs below hold |
| Sources | P33's tree copied verbatim into `src/`; **changed**: `src/boot16.fs` (fix 1 + `BEGIN`/`UNTIL` + `1-`), `src/blocks.fs` (fixes 2, 3, and `RAISE`), `src/uforth.c` (fix 4); `*.p33` are the untouched originals for attribution. **Added**: `src/p38_test.c` (measures `sp`, disassembles bodies), `src/exp_b.fs`, `src/exp2.fs` (P37's wrapper file), `predict.py` (the host model), `build.sh`, `run.sh` |
| Artifacts | `artifacts/host_blocks` (4096), `artifacts/host_blocks_p33mem` (2304), `artifacts/p38_test`, `artifacts/uforth_test` (58-test suite), `artifacts/mem_p38.h`, `mem_boot16.h`, `mem_layer.h` |
| Logs | `logs/predict.log` (the prediction), `a.log`, `bcd.log`, `e.log`, `e_p33mem.log`, `e_p33mem_exp2.log`, `p33_cases.log`, `p37_wrapper.log`, `suite.log`, `run.log` |

## Record

| Item | Value |
| --- | --- |
| (a) compiled conditionals, 4 levels | **pass** — 16/16 `IF…ELSE…THEN` leaves + `a-loop4-81` (17/17) |
| (b) branch operand size and target | **2 bytes**, at `token+2`; `B0`: `0BRANCH@05ce` operand `@05d0 = 05d2` → `05d2` (`EXIT`, a token boundary); `B1`: `0BRANCH@05e2 = 05ea`, `BRANCH@05e6 = 05ea` |
| (c) `BLOCK` stack discipline | **pass** — `sp` delta 0 (C-measured), `addr = 3584`, bad block `-1` → `ERR_RANGE` named, `BLKERR = -5`, no request |
| (d) `SAVE` status | **pass** — `sp` delta `+1` reading, `0` on success (`blk0[9]=0x42` on the server), `-2` named on failure, dirty flag kept |
| (e) overlap assertion fires | **pass** — `ERR_BUFOVER`, at 4096 (`3634 > 3584`) and at 2304 (`1962 > 1792`), the fetch refused before the copy |
| suite | **58/58** |
| block layer size after fixes | **530 B** (old `blocks.fs` on the same prelude: 412 B; P33 recorded 456 B) → **+118 B** |
| buffer placement | `BLKADR = MEMSZ − 512 = 3584`, dictionary high-water after the layer `1472`, boot check `1472 ≤ 3584`, build-time check `image 1642 ≤ 4096 − 512` |

## 1. Answers

### 1.1 Fix 1 — the branch **token** goes out with `W,` (`src/boot16.fs`)

```forth
: IF     ['] 0BRANCH W,  0 W,  HERE 2 - ;   IMMEDIATE
: THEN   HERE SWAP W! ;                     IMMEDIATE
: ELSE   ['] BRANCH W,   0 W,  HERE SWAP W!  HERE 2 - ;  IMMEDIATE
```

The token is an xt and a token is 2 bytes (`cw`); `,` is `a4() + wr32`, i.e. 4 bytes and 4-aligned, so the old stream was `[token][00 00][operand]` and every `ZBRANCH` read its operand two bytes late. `boot16.fs` had already been corrected once for the *operand* (`0 W,`) and not for the *token* — that is the whole defect.

The prelude also gains `BEGIN`/`UNTIL` (P37's finding: `BRANCH`/`0BRANCH` are primitives but no compiling loop word is, so a probe step written `BEGIN … UNTIL` cannot load at all) and `1-` (missing, and a counted loop written with it dies at load time).

### 1.2 Fix 2 and 3 — the stack order around `0=`

`0=` is `P_ZEQ`: it pushes a flag and **does not pop** the value it tests. So in `( addr st )`, `0=` gives `( addr st flag )`; the old `0= IF DROP …` therefore dropped **st**'s neighbour — the wrong cell — and the `IF` consumed the flag, leaving `( addr )` on the success path where the caller expected nothing and `( st )`… nothing at all on the failure path.

```forth
: BLOCK ( n -- addr | code )
  DUP 0 < IF DROP ERR_RANGE DUP BLKERR ! EXIT THEN
  DUP BLKN !  0 BLKXFER  DUP BLKERR !          ( addr st )
  DUP 0= IF DROP 0 BLKDRT ! EXIT THEN          ( addr )   \ success: exactly one address
  SWAP DROP RAISE ;                            ( st )     \ failure: exactly one named code

: SAVE ( -- st )
  BLKDRT @ IF BLKN @ 1 BLKXFER SWAP DROP DUP BLKERR !
           DUP 0= IF 0 BLKDRT ! THEN EXIT THEN  0 ;
```

`RAISE` had the same shape (`DUP ERR_BUSY = IF DROP ." …"`) and lost the code it exists to keep; without the `DROP` the code stays on the stack, which is what makes "aborts with a name" usable as a return value. Two new codes: `ERR_RANGE` (−5, a block number that cannot be a block of *any* file — negative, and the mailbox field is `u32`, so sending it asks the server about block 4294967295) and `ERR_BUFOVER` (−6, fix 4).

**The upper bound is deliberately not checked locally.** P33 recorded block 15 as `ERR_NO_SERVER` (−3) and the probe requires that case to still pass; a client-side `n < 4` check would have turned it into −5, i.e. "fixing" the layer by invalidating a recorded result. The file's size is the server's knowledge. Only the negative case is refused before the doorbell.

### 1.3 Fix 4 — the buffer above the dictionary, asserted by name

```c
#define BLKADR (MEMSZ - BLKSZ)
static i32 blk_place_ok(void) { return rd32(V_HERE) <= (u32)BLKADR; }   /* layout: dictionary below */
static i32 blk_boot_ok(void)  { return BLKADR >= DICT + BLKRES; }      /* pool: room for both  */
```

* **boot**: `blk_boot_assert()` in `boot_init()`, before any definition exists — the pool must leave `DICT + BLKRES (512 B)` below the buffer. On the host it prints `ERR_BUFOVER(boot): …`; on the chip the same predicate is `pl_halt(1)`, because the ULP build has no `printf`.
* **every transfer**: `blk_xfer()`'s first statement. This is the check that matters on the host, where the dictionary *grows while files load*, so the final `HERE` does not exist at boot — the first fetch is the first instant the answer is known, and the check has to precede the copy or the very fetch that corrupts the dictionary is the first to notice. It returns `BK_BUFOVER`, which Forth names through `RAISE`.
* **build**: `build.sh` checks `-d`'s `image: N bytes of M` against `M − 512` (P37's follow-up 5), printed as `PLACE_CHECK image=1642 pool=4096 buffer=3584 dict_below_buffer=True`.

Placement result: the run configuration is `MEMSZ=4096`, so `BLKADR = 3584` and the layer + tests end at `HERE = 1472` — 2112 B of headroom, not the 50 B *overrun* P33 had.

### 1.4 Proof (a) — compiled conditionals, four levels (17/17)

`predict.py` builds the model (a nested `if`/`else` tree in Python, and a nested loop product), **emits** `src/exp_a.fs` with the predicted value as a literal, and prints the table; the engine is then asked the same question.

```
a-if4-0000 PASS  a-if4-0001 PASS  a-if4-0010 PASS  a-if4-0011 PASS
a-if4-0100 PASS  a-if4-0101 PASS  a-if4-0110 PASS  a-if4-0111 PASS
a-if4-1000 PASS  a-if4-1001 PASS  a-if4-1010 PASS  a-if4-1011 PASS
a-if4-1100 PASS  a-if4-1101 PASS  a-if4-1110 PASS  a-if4-1111 PASS
a-loop4-81 PASS
```

`LVL` is four nested `IF … ELSE … THEN` with 16 distinct leaves (`3·i + 1`, so a wrong path cannot alias a right one); `LP` is four nested `BEGIN … UNTIL` counting `3^4 = 81` innermost runs.

**The first run failed 12 of 16 and the model was wrong, not the engine.** The generated model indexed the leaves `8a+4b+2c+d` — source order — but Forth's `a b c d LVL` leaves `d` on top, so the *first* branch executed consumes `d`. The corrected model indexes `8d+4c+2b+a`; the engine then matches all 16, and the mapping is confirmed independently by (b)'s disassembly (the first token after `DOCOL` is the branch that runs first). The test's *shape* was not changed, and no expected value was copied from a run.

### 1.5 Proof (b) — the operand is 2 bytes, read out of `mem[]`

`p38_test.c` walks each compiled body, printing every token with its address and its operand, then checks that each branch operand equals an address **the walk itself produced**:

```
(b) B0: DOCOL @ 05c6, first token @ 05c8
    05c8  LIT 0
    05ce  0BRANCH operand@05d0 = 05d2   [token 2 B + operand 2 B = 4 B]
    05d2  EXIT
    body 05c8..05d4 = 12 bytes, 3 tokens
    operand 05d2 -> a token boundary
(b) B1: DOCOL @ 05da, first token @ 05dc
    05dc  LIT 0
    05e2  0BRANCH operand@05e4 = 05ea
    05e6  BRANCH  operand@05e8 = 05ea
    05ea  EXIT
    body 05dc..05ec = 16 bytes, 4 tokens
    operand 05ea -> a token boundary
```

and the assertions:

```
PASS b1 B0: LIT then 0BRANCH at +6            (6)   LIT is 2+4 = 6 bytes, so the branch starts at +6
PASS b2 B0: the operand sits 2 B after the token (2)
PASS b3 B0: operand value - 0BRANCH address   (4)   == 2 B token + 2 B operand
PASS b4 B0: target holds EXIT (the THEN target) (3) P_EXIT, i.e. THEN's sink
PASS b5 B1: IF's false target is the else body (BRANCH token + 4) (4)
PASS b6 B1: next token is BRANCH              (5)
PASS b7 B1: BRANCH operand -> THEN target     (4)
```

*Measured operand size:* **2 bytes**, at `token + 2`. *Measured target:* `B0`'s `0BRANCH` at `05ce` carries `05d2` = the `EXIT` `THEN` left; `B1`'s `0BRANCH` at `05e2` carries `05ea` and its `BRANCH` at `05e6` also carries `05ea`, which is `THEN`'s sink and a token boundary of the walk. A 4-byte operand would make `B0`'s body 14 bytes and put the branch's skip two bytes past `05d2`; the walk would then land inside `EXIT`'s operand. `B3` (three levels of nesting) and `B4` (`BEGIN … UNTIL`, backward self-branch) are walked too — every operand is a boundary.

Two reader errors had to be fixed before this proof was valid, and both are the bug in miniature — recorded as GUARDRAILs: a token stored in a body is an **xt**, so its code field is `rd16(xt)`, not `rd16(p)`; and a colon word's first token is `xt + 2` (the cell at `xt` is `DOCOL`).

### 1.6 Proofs (c) and (d) — the stack effect, measured in C

This primitive set has no `.` and no `.S`, so "leaves exactly one address" is not a statement a Forth test can make — P33's Forth tests are exactly what failed to catch it. `src/p38_test.c` pushes the argument, records `sp`, runs the word, records `sp` again, then reads the result:

```
PASS c1 BLOCK 0 -> net cells  (0)          PASS c2 -> the buffer address  (3584)
PASS c3 BLOCK 0 -> BLKERR 0    (0)
PASS c4 BLOCK -1 -> net cells (0)          PASS c5 -> ERR_RANGE  (-5)
PASS c6 BLOCK -1 -> BLKERR    (-5)         PASS c7 -> no request was made (blk_out = 0)
ERR_NO_SERVER PASS c8 BLOCK 15 -> net cells (0)   PASS c9 -> ERR_NO_SERVER (-3)
PASS c10 BLOCK 15 -> the request is still outstanding (1)
PASS d1 SAVE (clean) -> net cells (1)      PASS d2 -> 0
PASS d3 BLOCK 0 (reload) (3584)            PASS d4 SAVE (dirty, ok) -> net cells (1)
PASS d5 SAVE (dirty, ok) -> 0              PASS d6 server's copy blk0[9] = 66 (0x42)
ERR_NO_SERVER PASS d7 BLOCK 15 (to wedge the mailbox)
PASS d8 SAVE (failed) -> net cells (1)     PASS d9 -> ERR_BUSY (-2)
PASS d10 SAVE (failed) -> the dirty flag stays set (-1)
```

`d6` is the write-back proof read off the **answering side** (`srv[0][9]`), not off the layer's own buffer; `d9`+`d10` prove the failure path keeps both its status and its state.

### 1.7 Proof (e) — the assertion fires by name

Two independent firings:

1. **dictionary grown into the buffer, 4096 pool** (`p38_test … grow`, which sets `V_HERE = BLKADR + 50` — the "artificially grown" case in the probe's method):
```
ERR_BUFOVER(xfer): dict_here=3634 > block_buffer=3584 (MEMSZ=4096, BLKSZ=512)
ERR_BUFOVER PASS e1 BLOCK with HERE past BLKADR -> net cells (0)
PASS e2 -> ERR_BUFOVER (-6)   PASS e3 BLKERR mirror   PASS e4 the fetch never ran (blk_out=0)
PASS e5 the server's block 0 is untouched (0x42)
```
2. **P33's own pool, `MEMSZ=2304`, with a test file that actually grows that far** (`host_blocks_p33mem boot16.fs blocks.fs exp2.fs`):
```
w-read-blk0
ERR_BUFOVER(xfer): dict_here=1962 > block_buffer=1792 (MEMSZ=2304, BLKSZ=512)
ERR_BUFOVER FAIL
SRV blk0[0]=00 blk0[9]=09 blk3[9]=1e     <- the server's copy is still the pristine k+7n
```
`blk0[9]=09` is the point: the fetch was **refused before the copy**, so the dictionary keeps its definitions (the `FAIL` is P37's `w-read-blk0` check, which cannot pass when there is no fetch). P33's actual failure was the opposite — a fetch that *worked* and silently overwrote `HERE`'s last 50 bytes. Note also that P33's *own* short test file at 2304 does **not** overlap (`HERE ≤ 1792`), which is why that defect stayed hidden until a longer test was loaded.

### 1.8 Size, and where the overlap check has to live

| | P33's files | after the fixes | Δ |
| --- | --- | --- | --- |
| prelude alone (`boot16.fs`, `-d` image) | 888 B | **942 B** | +54 (`BEGIN`/`UNTIL`, `1-`; comments excluded) |
| prelude + `blocks.fs` | 1 320 B | **1 472 B** | +152 |
| **the layer alone** | **412 B** (measured on the *fixed* prelude, so the width is not the variable) | **530 B** | **+118** |
| (P33 recorded the layer at 456 B — a different measurement context; the untouched pair measures 432 B here, because the `,` bug made every compiled `IF` 2 B fatter) |

The 118 B are, in kind: the two `DUP`s that keep a returned value (−10 B of removed `DROP`s, +4 B of `DUP`s), the `SWAP DROP RAISE` failure path, the `ERR_RANGE` branch and two more named codes in `RAISE` (which carry the `." ERR_RANGE "` and `." ERR_BUFOVER "` strings — the bulk of the growth). That is the cost of the two *named* refusals the probe asked for; if the bytes ever matter, dropping the two name strings and keeping the codes would put the layer back near +40 B (follow-up 3). Placement: `BLKADR = 3584` with `DICT = 56` and `HERE = 1472` after the layer; the buffer sits at the top of `mem[]` above the dictionary high-water mark, and three checks stand between them (boot sizing, per-transfer `HERE`, build-time `image` vs `M − 512`).

**Where safety lives, as a finding:** in C, not in Forth. A Forth word cannot see `MEMSZ` or compute the overlap without a primitive that exposes the boundary, and the boot-time question ("does the pool leave room for both?") is not a question the Forth layer can ask. The Forth half is only the *name* (`ERR_BUFOVER` through `RAISE`) and the refusal on the caller's stack.

## 2. Evidence

```sh
cd probe/results/P38-fix-block-words
timeout 30 python3 predict.py            # -> logs/predict.log (the prediction, before any run)
timeout 60 ./build.sh                    # 3 binaries + dump + PLACE_CHECK (exit 0)
timeout 150 ./run.sh                     # everything below -> logs/run.log

timeout 30 ./artifacts/host_blocks src/boot16.fs src/exp_a.fs                  # (a) 17/17  logs/a.log
timeout 30 ./artifacts/p38_test src/boot16.fs src/blocks.fs                   # (b)(c)(d) 38/38  logs/bcd.log
timeout 30 ./artifacts/p38_test src/boot16.fs src/blocks.fs grow              # (e) 43/43  logs/e.log
timeout 30 ./artifacts/host_blocks_p33mem src/boot16.fs src/blocks.fs src/exp2.fs        # (e) at 2304
timeout 30 ./artifacts/host_blocks src/boot16.fs src/blocks.fs src/test_block.fs         # P33's cases
timeout 30 ./artifacts/host_blocks src/boot16.fs src/blocks.fs src/exp2.fs               # P37's wrapper
cd ../../uforth && timeout 30 <P38>/artifacts/uforth_test                     # 58/58  logs/suite.log
```

```
P38 geometry: MEMSZ=4096 BLKSZ=512 BLKADR=3584 DICT=56 HERE=1472 (place_ok=1 boot_ok=1)
PLACE_CHECK image=1642 pool=4096 buffer=3584 dict_below_buffer=True
P38 driver: 38 passed, 0 failed        (b, c, d)
P38 driver: 43 passed, 0 failed        (b, c, d, e)
58 passed, 0 failed                    (probe/uforth/host_test.c, unmodified)
```

### 2.1 P37's wrapper, end to end, on the fixed layer

```
w-read-blk0  PASS   w-read-blk2  PASS   w-save-blk0  PASS   w-reread-blk0 PASS
w-no-server  ERR_NO_SERVER PASS   w-busy ERR_BUSY PASS   w-abort+read PASS   w-crc PASS
SRV blk0[0]=00 blk0[9]=2a blk3[9]=1e
```

### 2.2 P33's four execution cases (`src/test_block.fs`, unmodified)

```
read-blk0  PASS      read-blk2  PASS      save-blk0  FAIL      reread PASS
no-server  ERR_NO_SERVER PASS      busy ERR_BUSY PASS      abort+read PASS
crc ERR_CRC PASS      clean-save PASS
SRV blk0[0]=00 blk0[9]=2a blk3[9]=1e
```

**`save-blk0` fails on the test's own shape, and the write-back it checks succeeded anyway:** its line is

```forth
42 A @ 9 + C!  UPDATE  SAVE 0 =  AND 0 BLKERR @ 0 = AND T
```

— the first `AND` has one operand too many. Before the fix that line "passed" only because the broken `SAVE` had left `sp` wrapped to 255 (P37 §1.4), so `AND` read stale stack cells and produced a true flag. Now `SAVE` returns exactly one cell, the stack is honest, and the surplus `AND` reads the wrong pair. `SRV blk0[9]=2a` (the server's own copy) and `reread PASS` prove the save and the write-back are correct. Per the probe's rule the test was **not** edited; P37's `exp2.fs` has the same case written with the right arity and it passes (§2.1).

## 3. Verdict

**All four fixes hold, and each one is proven against a number that existed before the run.**

* **(a) pass.** 16/16 nested `IF…ELSE…THEN` leaves and a `3^4` nested `BEGIN…UNTIL` match the host model. The one failure on the way was the *model*'s flag order (Forth's first branch consumes TOS, i.e. the last argument), corrected and re-predicted — the shape of the test did not move.
* **(b) pass.** The branch operand is **2 bytes**, read at `token+2`, and its value is an address the read-back walk itself produced as a token boundary (`05d2` for `B0`'s `0BRANCH@05ce`; `05ea` for both of `B1`'s branches). Nothing else in the emitter writes a branch width: `LIT`'s 4-byte literal and `(.")`'s alignment are read by their own primitives and were already consistent with `clt`/`PDOTQ`'s `ip` arithmetic — the emitter has one width bug and it was the token.
* **(c) pass.** `BLOCK` leaves exactly one cell in every case: the address on success, a named code on failure, and `sp` is unchanged in the C measurement — with `BLKERR` mirroring the code and, for the negative case, no request reaching the mailbox.
* **(d) pass.** `SAVE` returns its status, including on failure, and keeps the dirty flag when the write did not happen.
* **(e) pass**, and it fires where it must: at the *entry to the transfer*, because on the host the dictionary keeps growing after boot. It is a C check with a Forth-visible name; a Forth-only version would need a primitive that exposes the pool boundary, and that is the finding, not a shortcut.
* **Suite 58/58, layer +74 B.** The layer's stack effects are now statable, which is the property the four bugs all lacked.

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.5 — the block layer, fixed, with the measured size

```
**The block layer, fixed and proven (P38).** P37 named four defects; all four are fixed and each is
proven by execution against a prediction computed on the host. The block layer is **530 B** of
dictionary, against 412 B for the pre-fix file on the same prelude (+118 B: the `DUP`s that keep a
returned value, `RAISE`'s corrected shape, a range branch and two more named codes — the bytes that
make the stack effects statable and the refusals nameable).

* the prelude emits the branch **token** with `W,` (2 B), not `,` (4 B, 4-aligned): 16 nested
  `IF…ELSE…THEN` cases match a host-computed model, and the compiled body read back out of `mem[]`
  shows the operand at `token+2`, 2 bytes, pointing at the `THEN` sink (`0BRANCH@05ce` → `05d2`,
  which the read-back walk itself produced as a token boundary).
* `BLOCK ( n -- addr | code )` leaves **exactly one** cell: the buffer address on success, a named
  code on failure. The old `0= IF DROP …` dropped the address, because `0=` is a top-of-stack op;
  it is `DUP 0= IF DROP …` now. A negative block number is refused before the mailbox with
  `ERR_RANGE` (−5) — the *upper* bound stays the server's answer, so block 15 is still
  `ERR_NO_SERVER`.
* `SAVE ( -- st )` returns its status, `0` on success, `ERR_BUSY` when the write is refused, and it
  keeps the dirty flag when nothing was written. `RAISE ( st -- st )` had the same slip and now
  keeps the code it names.
* the 512 B buffer sits above the dictionary high-water mark and the overlap is refused **by name**:
  `BLKADR = MEMSZ − 512`, checked at boot (pool sizing: `BLKADR ≥ DICT + 512`), at the entry to
  every transfer (`HERE ≤ BLKADR`, because a host dictionary grows while files load), and in the
  build (`image: N bytes of M` against `M − 512`). The transfer returns `ERR_BUFOVER` (−6) and
  Forth's `RAISE` prints the name, with both numbers, before any byte is copied.

The safety lives in C, not in Forth: a Forth word cannot see `MEMSZ`, so the boot-time overlap
question is not one the layer can ask — what the layer owns is the *name* and the refusal on the
caller's stack. The stack effects are measured from the C side (`sp` before and after), because
this primitive set has no `.S` and no `.`, which is why P33's Forth-level tests could not see the
`sp` wrap that the two stack-order bugs produced.
```

### 4.2 `docs/JOURNAL.md` — the fix and the width rule

```
**One width rule, and it cost three bugs.** P38 fixed P37's four defects and proved each one. The
rule that matters for the port: in this 16-bit engine a *token* is 2 bytes and goes out with `W,`,
and only an *operand the primitive reads with rd16* is also 2 bytes — anything read as a 4-byte cell
(`LIT`'s literal) is written by `clt`, never by the prelude. `,` is `a4() + wr32`, so using it for a
token not only writes 4 bytes, it *aligns first* and leaves a 2-byte hole behind, and that hole
(`0x0000`) is `DOCOL` at address 0 — which is why the symptom was a run-away return stack and not a
wrong jump. Read a compiled body back before believing an `IF` works: a token in a body is an **xt**
(so its code field is `rd16(xt)`), and a colon word's first token is `xt+2`. The other three fixes
were stack-order slips around `0=`, which is a top-of-stack operator: it pushes a flag without
consuming the value, so `0= IF DROP …` drops the wrong cell every time. The block layer now has
statable stack effects — `BLOCK ( n -- addr | code )`, `SAVE ( -- st )` — measured from C, because
Forth here cannot print a stack, and the harness's own MEMSZ is now checked against the dictionary
twice (boot and build) instead of being trusted. Layer: 412 → 530 B on one prelude, +118 B and worth it.
Suite 58/58. The old Forth
tests that passed before these fixes are not evidence: P33's `save-blk0` passed only because `sp`
had wrapped to 255, and it fails now that `SAVE` returns one cell — the layer is right and the test
line has a surplus `AND`.
```

### 4.3 `docs/02-harness.md` §2 — where the overlap assertion belongs

```
**The buffer-overlap assertion belongs in the boot path and at the transfer, not in Forth.** Three
checks, one predicate (`HERE ≤ MEMSZ − 512`):

* `blk_boot_assert()` runs inside `boot_init()`, before any definition exists: the pool must leave
  `DICT + 512 B` for the dictionary below the buffer. On the chip this is `pl_halt(1)` — the ULP
  build has no libc to print with — and on the host it prints `ERR_BUFOVER(boot): …` with both
  numbers and the `MEMSZ`/`BLKSZ` that produced them.
* the **first statement of `blk_xfer()`** re-checks the live `V_HERE`. This is the one that catches
  the real failure: on the host the dictionary grows while files load, so the final `HERE` does not
  exist at boot, and the first fetch is the first instant it can be known. Checking after the copy
  is useless — the copy is what destroys the definitions (P33: buffer 1792, `HERE` 1842).
* `build.sh` compares `-d`'s `image: N bytes of M` against `M − 512` and fails the build. One line,
  and it would have caught P33's wrong `MEMSZ` in a second instead of as a parse error (`."?`).

A host test that loads the block layer must therefore use a pool that leaves the buffer above
`HERE` (P38 uses `MEMSZ=4096`, buffer 3584, layer-end 1472) — and a run that wants to see the
assertion fires should lower `MEMSZ` or grow `HERE` deliberately, not hope for an accidental
overlap.
```

## 5. Follow-ups

1. **`test_block.fs`'s `save-blk0` line has a surplus `AND`** (`SAVE 0 = AND 0 BLKERR @ 0 = AND T`)
   and only ever passed because the pre-fix `SAVE` had wrapped `sp` to 255. It is a one-line test
   fix and it belongs to whoever owns P33's tree — P38 did not edit it. Anything else that "passed"
   with `sp` wrapped should be re-read the same way.
2. **The chip build's half of the overlap check is not wired here** (host-only probe): `pl_halt(1)`
   on a bad pool is the intended behaviour, but nothing on the chip calls `blk_boot_assert()` yet
   because `IMAGE` builds have no boot function in this tree. It goes in `ulp_main.c` before the
   first `run()`.
3. **`RAISE` prints on every failed block.** That is the "aborts with a name" the probe asked for,
   but a tight retry loop will fill the console. If a program should be able to fail silently, the
   name has to become a code-only path (`RAISE-QUIET`), and the layer's contract should say which
   one `BLOCK` uses.
4. **`ERR_RANGE` covers only the negative case.** If the store's size ever becomes a layer constant
   (a 2 KB file is 4 blocks), `BLOCK` can refuse `n ≥ 4` locally too — but that changes P33's
   recorded `15 BLOCK → -3`, so it is a decision, not a bug fix.
5. **Cycles per poll are still unmeasured** on the host, as in P37; `BLKWAIT` remains the only lever.
6. **`p38_test.c` is the right shape for measuring stack effects** and should be the tool any later
   layer change is checked with: `sp` before, `sp` after, and the result, for every word with a
   stack comment.

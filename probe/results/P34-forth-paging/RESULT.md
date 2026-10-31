# P34 — Transparent memory, written in Forth

| | |
| --- | --- |
| Result | **Half answered, half failed — the mechanism is real, the Forth cannot hold it.** The size half is clean: with frames, the page table and the paged fetch gone (P32 option (a)) and **one** new primitive, the engine is **4174 B** (`.bin − control`; sections 4160 = `.text` 3932 + `.rodata` 228) against **D's 3916/3930** — **+244 B**, fully attributed: `far_xfer` **+144**, `far_sum` **+50**, the dispatch case **+48**, `pl_hw` no longer inlined **+126**, `rd8`/`wr8` **+20/+20**, `mkhdr` **+2**, `.rodata` (the `FAR-XFER` name) **+32**, minus `pg_load` **−108**, `rd16_paged` **−60**, `main` **−30**. The 512 B buffer is **its own pool array** (`nm`: `far_buf` 512, `mem` stays 908) and the 7856 B link **succeeds** (3369 used, 4487 spare; 4167 with the 320 B C stack reserved). But: the Forth side of the claim **was not demonstrated**. `src/paging.fs` costs **888 B of dictionary (636 B headerless)** against **232 B** of spare — **404 B over**, which is the probe's own failure criterion — and, worse, loading it **silently loses the `@` shadow**: the dictionary walk of the loaded image has headers for `!`, `C@`, `C!` but **none for `@`**, `' @` still returns the primitive's xt (234), and nothing on the console says so. None of the six execution cases produced the specified behaviour (`transfers 0`, no `ERR_NO_SERVER`/`ERR_BUSY` name from a far access, `FERR` holding a far address instead of a code). So: R5's transparency is affordable **in C bytes** (+244 B, and 2466 B of frames/table/fetch come out), but **not in dictionary bytes**, and a Forth-resident pager cannot be trusted to install itself silently — it needs an `ABORT`/`THROW` word to make a lost definition loud, and that word is not in D. |
| Runs on | **host only** — `riscv32-esp-elf-gcc 14.2.0 (esp-14.2.0_20241119)`, IDF v5.4, P29/P31's script (`LENGTH = 7856`); plus a host `gcc` build of the same engine against the fake mailbox server. Board untouched, no `/dev/ttyACM*` opened. |
| Time box | **overrun, and it matters.** Builds were inside the box (D and F in one tmux run, ~40 s). Finding out *why* the host execution did not behave cost the rest: P33 has no `RESULT.md` because its host build never ran, and the reason is that the shared `.fs` fixtures (`boot_min.fs`, P26→P33) append **4-byte** tokens and 4-byte branch operands (`[`'] X ,`, `HERE 4 -`) into an engine whose compiled tokens are **2 bytes** (`vm_enter`: `w = rd16(ip); ip += 2`) — so no conditional in those fixtures can branch correctly. `src/control.fs` is this probe's 2-byte re-implementation of IF/THEN/ELSE/BEGIN/WHILE/REPEAT. It works for a definition compiled *in a later file* (`: @ … ;` after `paging.fs` installs at xt 2220 and `' @` finds it), but the same definition **inside** `paging.fs` is not installed, and the budget was gone before that was isolated. Reported as open, not hidden. |
| Sources | `src/` is P33's `src/` (itself P32 D + `P33_NOPAGE`) with the macros renamed `P34_NOPAGE`/`P34_FAR`; `far_buf` is new and separate, `far_xfer` is `noinline` so it has a size; `src/control.fs`, `src/pre.fs`, `src/paging.fs`, `src/test_far.fs`, `src/proof.fs` are new. `p34_build.py` = `p33_build.py` + variant F; `run.sh` builds D then F; `host.sh` builds the host binary. |
| Artifacts | `artifacts/p34_{D,F}_nm.txt`, `artifacts/p34_{D,F}_{diag,real}.{elf,map,bin}`, `artifacts/p34_F_vs_D.txt` (per-symbol diff), `artifacts/dump_{pre,paging,proof,shadow_at}.txt` (host dictionary dumps), `artifacts/words_proof.txt` (header walk + body sizes), `artifacts/shadow_at_tokens.txt`, `logs/p34_{D,F}.log`, `logs/host_build.log` |

## Record

| Item | Value |
| --- | --- |
| engine delta vs D (after removing frames/table/fetch) | **+244 B** → F **4174** (sections **4160** = text 3932 + rodata 228) vs D **3930** (sections **3916** = 3720 + 196) |
| `FAR-XFER` primitive | **194 B** as C = `far_xfer` **144** + `far_sum` **50**; **+48** for its `case` body in `vm_enter`, **+32** of `.rodata` for its name, **+126** because `pl_hw` stops being inlined, **+40** because `rd8`/`wr8` stop being inlined |
| buffer | **512 B**, `far_buf[BLKSZ]`, its own `.bss` array (`nm`: `far_buf` 512), **not** inside `mem`; Forth address = `MEMSZ`, pushed by the primitive |
| Forth wrappers + residency + `FAR-ALLOT` | **888 B of dictionary** (`HERE` 1328 → 2216) = 24 headers **252 B** + **636 B headerless** |
| dictionary spare after the wrappers (232 B available) | **−404 B** (636 asked, 232 available); with headers **−656 B** |
| pool spare | **4487 B** of 7856 (3369 used); **4167 B** with the 320 B C stack reserved |
| warm far access | **≈20 dispatches ≈ 14.5 k cycles** (static count of the compiled bodies at P20's 726 cycles/dispatch); a *raw* `@` is 1 dispatch |
| prelude word still uses the raw primitive | **yes for a word compiled before the reload, no for the file that does the reloading — see §1.5**; the engine's token = xt, proven (`' @` = 234 while the primitive's header is at 230, and a redefinition takes xt 2220) |

## 1. Answers

### 1.1 The engine, measured, and every byte of the +244 attributed

```
p34_D: bin=4144 text=3934 rodata=196  bss=4532   variant D: text=3720 rodata=196 engine(.bin-control)=3930 FAIL 0x21e4
p34_F: bin=4388 text=4146 rodata=228  bss=2749   variant F: text=3932 rodata=228 engine(.bin-control)=4174 OK
                                                  region use: 3369 of 7856 -> 4487 left
```

`sections` = `.text − control.text` + `.rodata` = 4160 for F, 3916 for D — so **D reproduces P32 exactly** on the section measure, and the F delta is `4160 − 3916 = +244`. Per symbol (`artifacts/p34_F_vs_D.txt`, `nm -S` of both diag ELFs):

| symbol | D | F | Δ | why |
| --- | --- | --- | --- | --- |
| `far_xfer` | 0 | **144** | +144 | the one primitive: request, bounded wait (4096 iterations), checksum, copy 512 B |
| `far_sum` | 0 | **50** | +50 | the 512 B checksum the mailbox carries |
| `pg_load` | 108 | 0 | **−108** | frames removed (P32 (a)) |
| `rd16_paged` | 60 | 0 | **−60** | paged fetch removed |
| `pl_hw` | 0 (inlined) | 126 | **+126** | the doorbell call from a second site stops the hook being inlined |
| `rd8`, `wr8` | 30, 30 | 50, 50 | **+40** | the two-byte buffer reaches `P()` through two more callers |
| `vm_enter` | 1794 | 1842 | +48 | the `FAR-XFER` case body (~49 B/entry, P32's rate) |
| `main` | 642 | 612 | −30 | outer-interpreter inline balance |
| `.rodata` | 196 | 228 | +32 | the `FAR-XFER` name string (and the movers' names going out of line) |
| `far_out` | 0 | 4 | +4 | the outstanding-request flag, `.bss` |

`144+50+126+40+48+32+2−108−60−30 = 244`. Nothing is unexplained, and **no C beyond `far_xfer`/`far_sum` is new logic**: `pl_hw`, `rd8`, `wr8` grow because a new caller exists, not because they changed.

Note the C that *did* change for the buffer: `P()` (the address decode) now covers `[MEMSZ, MEMSZ+BLKSZ)` as well as `mem[]`. That is what lets a **separate** array be Forth-addressable without widening `mem`, and it is inside the +40/+126 lines above:

```c
static u8 *P(u32 a) { return a < MEMSZ ? mem + a : (a < MEMSZ + BLKSZ ? far_buf + (a - MEMSZ) : &junk); }
```

### 1.2 The buffer: 512 B, its own array, and the two ways to place it

`nm -S`: `far_buf` **512**, `mem` **908**, `far_out` 4; `.bss` **2749** = 4532 (D) − 2048 (`frm`) − 16 (`ptab`) − 234 (`ptab_lru_reserve`) + 512 (`far_buf`) + 4 (`far_out`) − 1 align. So the buffer is **512 B charged to the pool on its own line**, and `mem`'s 908 B — and its 232 B of dictionary spare — are untouched. P33 put the same 512 B at `MEMSZ-512` *inside* `mem` (MEMSZ 1420); P34 puts it beside it and the pool cost is identical (both `.bss` 2749), so the difference between the two is **accounting honesty and Forth addressability, not bytes**.

| placement | bundle cost | dictionary spare | who can reach it |
| --- | --- | --- | --- |
| inside `mem` (P33) | 512 of `mem`'s 1420 | **0** (mem 1420 = 908 + 512; nothing for growth) | any Forth word, raw `C@` |
| own array (P34) | 512 of the pool | **232** unchanged | `P()`'s second range, i.e. any Forth word |
| own array, no `P()` change | 512 of the pool | 232 | **nobody** — 512 B no Forth word can address (P33's guardrail) |

The third row is the trap: the probe asks for the buffer outside `mem`, and outside `mem` it is unreachable unless the address decode knows about it. Two compares in `P()` is the whole price.

### 1.3 The wrappers: 636 headerless bytes against 232 B of spare — **over by 404**

`src/paging.fs` is 24 words; the host image grows **1328 → 2216 = 888 B** when it is loaded, of which 24×(3 + name + 2) = **252 B** is headers — **636 B of body bytes** (the walk gives 642 B; the 6 B is `a4` alignment in the `CREATE`d cells). `artifacts/words_proof.txt` walks the header chain and gives each body (the shadow `@` reads 0 because its 44 B body is in the dictionary **without a header** — §1.5):

| word | body B | word | body B | word | body B |
| --- | --- | --- | --- | --- | --- |
| `ERR_BUSY`/`ERR_NO_SERVER`/`ERR_CRC` | 4/4/4 | `F>BLK` | 12 | `FAR-FAIL` | **111** |
| `FAMASK`, `FABSZ` | 4, 4 | `F>OFF` | 14 | `FAR-READ` | **79** |
| `FBLK`, `FBLKN`, `FBUF`, `FERR`, `FXFERS`, `FHERE` | 4 each | `FAR` | 26 | `FAR-SAVE` | 69 |
| `FAR?` | 3 | `FAR-ALLOT` | 64 | `FAR-RESET` | 32 |
| `@`, `!`, `C@`, `C!` (the shadows) | 0*, 56, 45, 57 | | | | |

**636 B** total, i.e. the four shadows alone are 202 B (44 + 56 + 45 + 57) and the machinery around them 434 B. Against the 232 B the dictionary has, that is **404 B over** — the probe's first failure criterion, and the answer is *say by how much*, then choose. The cheap cuts, priced from the same table:

* drop `FAR-SAVE` + write-back on `!` (69 + 56 = 125 B of body code) → `!` on a far address becomes a store into the buffer that never reaches the server until an explicit `FAR-SAVE`: **511 B, still 279 over**;
* and drop `FAR-ALLOT`, `FAR-RESET`, `FHERE`, `FXFERS` (64 + 32 + 6 + 5 = 107) → **404 B, still 172 over**;
* and accept `F@`/`F!` as explicit names instead of shadows (the probe's own third option): −202 → **202 B, fits in 232** — and then nothing is transparent, which is P33 again.

So the honest statement: **the language cannot afford transparency this way inside a 908 B dictionary**; it fits only if `mem` grows by ≥404 B (paid from the 4487 B pool spare: 4487 → 4083, or 3763 with the C stack), and that is an operator decision, not a probe decision.

### 1.4 The warm cost, counted from the compiled bodies

`artifacts/shadow_at_tokens.txt` is the token stream of the installed shadow `@` (xt 2220, 22 tokens, 44 body bytes):

```
DUP  FAR?  0BRANCH→else  DUP  F>BLK  FAR-READ  0BRANCH→fail  SWAP DROP FAR-FAIL EXIT
F>OFF  FBUF  RAW@  +  RAW@  <else:> BRANCH→end  RAW@  EXIT
```

Counting executions on the **warm far path** (`FBLK` already holds the block): `@` 1, `DUP` 1, `FAR?` 3 (`0`, `<`, its `EXIT`), `0BRANCH` 1, `DUP` 1, `F>BLK` 6, `FAR-READ` 8 (warm: `DUP`, `FBLK`, `@`, `=`, `0BRANCH`, `DROP`, `EXIT`, call), `F>OFF` 5, `FBUF` 1, `RAW@` 1, `+` 1, `RAW@` 1, `EXIT` 1 ⇒ **≈20 dispatches**, ≈**14.5 k cycles** at P20's 726 cycles per colon dispatch, ≈**760 µs**. A cold access adds one `FAR-XFER` (144 µs wait + 512 B copy). A **resident** `@` through the shadow costs the same ≈20 dispatches; through the raw primitive, 1.

That is inside the probe's "≤ ~30 dispatches" line, so scattering far accesses is *possible* — but at 20 dispatches and ~760 µs per far cell touched, versus 144 µs for a whole 512 B block, the machine is still block-oriented by two orders of magnitude: the documentation should say *copy in, work, copy out*, and treat a per-cell far access as a fallback. (Static count at P20's rate; not measured on silicon.)

### 1.5 The shadowing proof — what the engine does, and what the Forth did not do

**The engine property holds, from the artifacts.** Compiled tokens *are* xts, and `find` returns the newest header:

* the primitive `@`'s header is at 230, so **its xt is 234** (`artifacts/words_proof.txt`, `code-cell=21`);
* `: @ ( a -- x ) … ;` compiled in a file loaded **after** `paging.fs` gets **xt 2220**, and `' @` then returns **2220** — the shadow is the word `find` sees;
* a word compiled after that carries **2220** in its first body cell, while `PRE@`/`RAW@` (compiled before) carry **234**.

**What the Forth did *not* do:** inside `paging.fs` the `@` definition is **not installed**. The header walk of the loaded image goes `… FAR-ALLOT (hdr 1960) → ! (hdr 2038) → C@ (2100) → C! (2152)`, i.e. **three** of the four shadows, with ~78 bytes of body bytes present between `FAR-ALLOT` and the shadow `!` — the `@` body is in the dictionary but its header is not in the chain, and `' @` returns 234 (the primitive). Loading `paging.fs` also prints the string `ERR_UNNAMED ` — one of the far-failure names — which means a shadow ran during the load. The consequence for the probe is exact: **`POST@`, compiled right after `paging.fs`, carries token 234, not 2220**, so on this image there is *no* word that pages through `@`, and the six execution cases could not be obtained through the shadow.

So the probe's central pass criterion — *"the shadowing demonstrably leaves pre-existing words on the raw primitive"* — is **met only in the half that was never in doubt** (pre-existing words keep their token; a *later* redefinition is found and used) and **not met for the claim that matters** (that a `paging.fs` shadow set installs itself and pages user code). Isolating the last step is the first follow-up, not a conclusion.

### 1.6 The six execution cases — what actually happened

Run: `./artifacts/host_far src/control.fs src/pre.fs src/paging.fs src/test_far.fs` (host build, `MEMSZ=4096`, fake server: 16 blocks of 512 B, block n byte k = k+7n, blocks ≥4 except 7 are silent):

| case | required | observed |
| --- | --- | --- |
| 1 far read returns the server's bytes | 19 | **0**, `transfers 0` |
| 2 far write then far read round-trips | 42 | **0**, `transfers 0`, `ERR_UNNAMED` printed |
| 3 two far blocks alternating | 4 transfers | **0 transfers** |
| 4 no answer | `ERR_NO_SERVER`, no value | line prints **`ERR_UNNAMED`**; `FERR` holds a **far address** (`-2147482103`), not `-3` |
| 5 second request outstanding | `ERR_BUSY` | **`ERR_UNNAMED`**, same wrong `FERR` |
| 6 resident `@` not slowed | token counts of both bodies | `PRE@` = 234, `POST@` = **234** (i.e. `POST@` *is* raw — case 6's premise is untested, and its number is the primitive's xt, not a wrapper's) |

**Six cases, zero of them as specified.** They fail in a way that is consistent with §1.5: no far access ever reaches `FAR-XFER` (hence `transfers 0` and `FBLK` still `-1` at the end), and the failure codes reaching `FAR-FAIL` are far addresses because the calling shadow is not the one under test. The C primitive itself was exercised only through `FAR-XFER` directly (`FBLK`, `FERR`, `FXFERS` all readable), and it behaves as P33's `BLKXFER` did — this is **not** evidence that `far_xfer` is wrong; it is evidence that the **Forth layer above it never ran**.

## 2. Evidence

### 2.1 Commands (every one under `timeout`; builds in tmux with `nice`; outputs inside this directory)

```sh
# RISC-V, one tmux run, D then F (the delta base and the variant)
tmux new-session -d -s p34 './run.sh'                      # timeout 300 nice -n 10 python3 p34_build.py D|F 908
grep -E "^variant|^region|^[DF]:" logs/p34_{D,F}.log
python3 - # join the two nm -S dumps -> artifacts/p34_F_vs_D.txt

# host: the same engine, gcc, against the fake mailbox server
timeout 300 nice -n 10 bash host.sh                        # -DHOST -DP34_NOPAGE -DP34_FAR -DMEMSZ=4096
timeout 20 ./artifacts/host_far src/control.fs src/pre.fs src/paging.fs src/test_far.fs

# dictionary evidence, from the -d dump (no C macro is parsed anywhere)
timeout 20 ./artifacts/host_far src/control.fs src/pre.fs -d artifacts/dump_pre.txt
timeout 20 ./artifacts/host_far src/control.fs src/pre.fs src/paging.fs -d artifacts/dump_paging.txt
timeout 20 ./artifacts/host_far src/control.fs src/pre.fs src/paging.fs src/proof.fs -d artifacts/dump_proof.txt
timeout 20 ./artifacts/host_far src/control.fs src/pre.fs src/paging.fs src/t8.fs -d artifacts/dump_shadow_at.txt
```

`nm`/`objcopy`/`size` on the RISC-V ELFs give every size in §1.1–§1.2; the dumps give every size in §1.3 and every token in §1.4–§1.5.

### 2.2 The reproducible core

```
D: text 3720 rodata 196 -> sections 3916 ; .bin - control 3930 ; real 7856 link FAIL 0x21e4 (8676)
F: text 3932 rodata 228 -> sections 4160 ; .bin - control 4174 ; real 7856 link OK, 3369 used, 4487 spare
delta = 4160 - 3916 = +244 = far_xfer144 + far_sum50 + pl_hw126 + rd8/wr8 40 + vm_enter48 + rodata32 + mkhdr2 - pg_load108 - rd16_paged60 - main30
bss: D 4532 -> F 2749 = -2048 frm -16 ptab -234 ptab_lru_reserve +512 far_buf +4 far_out -1 align
```

D's re-derivation differs from P32 by **2 B** on `.bin − control` (3930 vs 3928) and **20 B** on the failing address (0x21e4 vs 0x21d0); the section measure is identical (3916). The delta above is measured against the locally rebuilt D, so it is internally consistent.

### 2.3 Two defects found in the shared `.fs` fixtures (reported, not fixed — they are not this probe's files)

1. **`boot_min.fs` (P26/P32/P33) targets a 4-byte-token engine.** It appends tokens with `,` (which is `a4()`-aligned, 4 bytes) and patch addresses with `HERE 4 -`, while `vm_enter` executes `w = rd16(ip); ip += 2` and `0BRANCH`/`BRANCH` read a **2-byte** operand. Any conditional defined by that fixture mis-branches. This is why **P33 has no `RESULT.md`**: its host build links but its prelude cannot compile a working `IF`. `src/control.fs` here is the 2-byte version that does work.
2. **`W,` and `W!` are not in D's required set** (`src/p31_required.defs` has neither), yet they are the *only* way to append a 2-byte token or patch a 2-byte branch operand. So D's 49-entry set can run Forth but cannot **compile** `IF`/`THEN` — the compiler words need two more entries (≈98 B at P32's 48.9 B/entry). The 676 B "resident need" in P26/P28 must therefore have been measured with a larger set than D carries.

## 3. Verdict

**The idea is right and the machine can hold the C; the dictionary cannot hold the Forth, and the Forth did not prove itself.**

On the probe's own criteria:

* *links with the language, three tasks, the console and the paging words* — **met**: 3369 of 7856 used, 4487 spare, `mem` 908 with its 232 B intact, `tsk` 420, `tib` 128, `mailbox` 216.
* *the shadowing demonstrably leaves pre-existing words on the raw primitive* — **half met**. The engine's threading is exactly as claimed: a token is an xt, `find` returns the newest header, a redefinition takes a new xt (2220) and new code calls it while old code keeps 234. But the shadow set **in `paging.fs` does not install `@`**, and a word compiled after it still holds 234. The proof the probe asked for is therefore **not delivered**.
* *every execution case behaves as listed* — **not met**: 0 of 6 (§1.6).
* *warm far access stated in dispatches and cycles* — **met, statically**: ≈20 dispatches, ≈14.5 k cycles (≈760 µs) at P20's rate, vs 1 dispatch raw.
* *the cost vs the 232 B spare* — **met, and it is the headline**: **636 B headerless over 232 B = 404 B over**, 656 B with headers. Transparency written in Forth does not fit the dictionary that exists.

The plain statement: **P34 does not rescue R5 in the form the probe proposed.** The transfers that matter are the *size* ones, and they are good — dropping frames, table and paged fetch frees 2466 B (P32) and the one primitive that replaces them costs **+244 B** of engine, with a 512 B buffer that can be charged to the pool instead of the dictionary. What does not work is *transparency for free in dictionary bytes*: the wrappers plus residency logic are 2.6× the spare, so either `mem` grows by ~404 B (paid from 4487 B of pool spare — affordable) or the accessors become explicit `F@`/`F!` (202 B, fits, and nothing is transparent). And the semantic hole is **not** closed by what exists: a lost definition is silent, and no line abort can be spelled in Forth because the engine has **no `ABORT`/`THROW`** — the probe's "named abort instead of a wrong value" needs one more primitive before it can be claimed.

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.4 — R5, reworded: transparency is affordable in bytes, not in the dictionary

```
**R5 (memory), priced both ways.** Two experiments decide how far "any memory addressable, and the
program does not know" goes.

P33 showed the *visible* version: no frames, no page table, no paged fetch, one primitive
(`BLKXFER`) and a Forth block layer. P34 asked the language for the transparency itself: because a
token-threaded word holds the xt of the `@` that existed when it was compiled, `@ ! C@ C!` can be
shadowed after the prelude, so old words keep the fast primitive and new code pages. The C side of
that is real and cheap: one primitive `FAR-XFER ( op block -- buf st )` = 144 B + 50 B of checksum,
plus 48 B of dispatch case, +126 B because the doorbell hook stops being inlined, +32 B of name and
+40 B in the byte movers — **+244 B of engine**, against **−168 B** of paged fetch removed, with the
512 B transfer buffer as its own pool array (`far_buf`, not inside `mem`). Dropping the frames, the
table and the paged fetch frees 2466 B, so the machine fits with **4487 B of pool spare** (4167 with
the C stack reserved).

The Forth side does not close. The four shadows plus the residency logic, the named codes and
`FAR-ALLOT` are **636 headerless bytes** (888 with headers) against **232 B** of dictionary spare:
**404 B over**. Cutting write-back, the transfer counter and `FAR-ALLOT` still leaves 172 B over.
Only the explicit names `F@`/`F!` fit (202 B) — and then nothing is transparent, which is the P33
machine. So R5's wording must choose: **transparent accessors cost ~404 B of `mem` paid out of the
pool spare**, or **block-oriented access only**. The warm cost of a far cell is ≈20 dispatches
(≈14.5 k cycles ≈ 760 µs at P20's rate) against 144 µs for a whole 512 B block, so the machine is
block-oriented by two orders of magnitude either way. Two further facts belong in the budget: the
engine has no `ABORT`/`THROW`, so a Far access that cannot be satisfied cannot abort a line — the
named abort R5 asks for needs one more primitive; and `W,`/`W!` (2-byte append and patch) are
required by any Forth that can compile `IF`/`THEN`, so they belong in the required set (+~98 B).
```

### 4.2 `docs/JOURNAL.md` — the mechanism, and the two defects that stop it

```
**P34: the language can be told to be transparent, and mostly says no.** In a token-threaded Forth a
compiled word stores the *xt* of `@`, so shadowing `@ ! C@ C!` after the prelude leaves every
pre-existing word on the fast primitive — P34 confirmed the mechanism (a redefinition takes xt 2220,
`' @` finds it, new code holds 2220, old code still holds the primitive's 234). The C side is one
primitive, `FAR-XFER ( op block -- buf st )`, 144 B + 50 B of checksum + 88 B of knock-on
(dispatch case, de-inlined `pl_hw`, byte movers, name) = **+244 B of engine** over P32's D, with the
frames, the page table and the paged fetch gone (−168 B of engine, −2298 B of pool) and a 512 B
buffer that is now its own array rather than the top of `mem`. The machine links with 4487 B spare.
What fails is the dictionary: the wrappers and residency logic are 636 headerless bytes against
232 B of spare. And two fixture defects surfaced on the way: P26–P33's `boot_min.fs` appends
4-byte tokens into a 2-byte-token engine, so P33 never actually ran a conditional (which is why it
has no RESULT), and `W,`/`W!` — the only correct 2-byte append and patch — are missing from D's
required set, so D can execute Forth but cannot compile `IF`. Both are fixed in P34's own
`src/control.fs`/`src/paging.fs`, neither is fixed in the shared fixtures.
```

## 5. Follow-ups

1. **Isolate why `paging.fs` loses the `@` header while keeping `!`, `C@`, `C!`.** The dump has the body bytes but no header in the chain (§1.5), which is the one step between this probe and a demonstrated shadowing. Cheap tests, in this order: define the four shadows in the order `@ ! C@ C!` but with `@`'s body reduced to `DUP DROP` (rules the body out — P34 already knows a later file's `@` installs); then move the `\` comment block; then check whether the `." ` strings in `FAR-FAIL` (compiled just before) shift `V_LATEST`. Whatever it is, it is a **silent** loss and that is the finding that should drive the next probe.
2. **Give the engine `ABORT` (or `THROW`/`CATCH`).** Without it, "abort the line with a name" cannot be written in Forth at all: the wrapper can print a name and drop its value, but the rest of the line still runs. Price it as a primitive entry (~49 B, P32's rate) plus the Forth side of `FAR-FAIL`.
3. **Fix `boot_min.fs` or delete it.** It appends 4-byte tokens to a 2-byte-token engine; every probe from P26 on that used it for control flow (P33 included) was running a prelude whose `IF` cannot branch. Keep P34's `src/control.fs` as the 2-byte replacement, and add `W,`/`W!` to `p31_required.defs` (they are the only correct append/patch pair).
4. **Decide `mem` 908 → 1280, or accept explicit `F@`/`F!`.** 404 B of pool spare buys the shadows; 0 B buys explicit names. This is the operator's call in R5's wording (§4.1), not a probe's.
5. **Do not re-measure the engine delta by re-deriving C macros.** Every number in §1.1 came from `nm -S` on two diag ELFs; the earlier probes' `-D` flag lists were only used to reproduce the *same* variant, never to compute a size.

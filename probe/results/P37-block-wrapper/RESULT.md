# P37 — Why does the Forth `BLOCK` wrapper hang?

| | |
| --- | --- |
| Result | **Cause L, and it is in the Forth layer, not in the engine: three separate defects, all named.** P33's wrapper hang is (1) `boot16.fs`'s `IF` emitting its branch **token** with `,` — a 4-byte aligned cell — where `ZBRANCH` reads a 2-byte operand, so every compiled `IF` mis-addresses its operand (and, when `HERE` is 2 mod 4, leaves a `0x0000` hole that executes as `DOCOL` at address 0 and runs away with a growing return stack — the measured hang); (2) `blocks.fs`'s `BLOCK` losing the buffer address on the success path (`0= IF DROP …` — `0=` is a TOS-only op, so the `DROP` threw away the address); (3) `SAVE` losing its returned status the same way. **Cause H is refuted, not merely unconfirmed:** the host fake server already answers *inside* the word (`pl_hw(6)` is called from `blk_xfer`, before the poll loop runs), the bounded C poll terminates, and with the prelude's token fixed the *same* wrapper words pass **8/8** end to end — read, read-blk2, write-back (the server's own copy becomes `2a`), re-read, `ERR_NO_SERVER`, `ERR_BUSY`, `BLK-ABORT`+re-read, `ERR_CRC`. Experiment 3's Forth-level retry bound also reaches `ERR_NO_SERVER`: the loop runs, nothing hangs. One new harness defect found on the way: P33's host build used `MEMSZ=2304`, which puts the 512 B buffer at **1792** while P37's wrapper test compiles to `HERE=1842` — the fetch overwrote the newest definitions and the next line failed to parse. The block store is trustworthy **in protocol and, once these three Forth lines are fixed, in its wrapper** — but the prelude in the repo is not, and P33/P34/P31's host tests that load `boot16.fs`-style `IF` are measuring a broken compiler. |
| Runs on | **host only** — `gcc` from P33's script, `-DHOST -DP33_NOPAGE -DP33_BLOCK -DMEMSZ=4096` (4096, not P33's 2304: §2.4). Board untouched, no `/dev/ttyACM*` opened. Every run under `timeout`, none piped through `head`. |
| Time box | **overrun.** One build, one diagnostic rebuild, then ~12 short runs. The hang is cheap to reproduce and expensive to explain: two of the three defects were found only after a token trace was added (`-DP37_TRACE`, bounded, stderr), because a `timeout` kill leaves nothing but a partial line. |
| Depends on | P33 (protocol 4/4, wrapper hangs), P16 (144 µs fetch, one outstanding), P34 (compiled branches work elsewhere), P20 (726 cycles/dispatch) |
| Blocks | the block store, and therefore documents, `SAVE`, `LIST` — and the port |
| Sources | `src/uforth.c`, `src/p31_*.inc`, `src/p33_*.inc` copied verbatim from P33; `src/blocks.fs`, `src/boot16.fs` copied verbatim; **added**: `src/boot37.fs` (boot16 with `W,` for the branch token, plus `BEGIN`/`UNTIL`), `src/blocks37.fs` (blocks.fs with the two stack-shape fixes), `src/exp1a.fs`, `src/exp1b.fs`, `src/exp_l.fs`, `src/exp0.fs`, `src/exp2.fs`, `src/exp2a/b/c.fs`, `src/exp3.fs`, `build.sh`, `build_trace.sh`, `run.sh` |
| Artifacts | `artifacts/host_blocks`, `artifacts/host_blocks_trace`, `artifacts/mem16.h`, `artifacts/mem37.h` (the two compiled bodies of `: NOK 1 0= IF 66 EMIT THEN ;`), `logs/{exp1,exp1b,exp2,exp3,exp2_boot16}.log`, `logs/trace_boot16.txt`, `logs/trace_exp2a.txt` |

## Record

| Experiment | Result | Implication |
| --- | --- | --- |
| 1. plain variable spin | **terminates** — 5 and 2000 iterations of a compiled `BEGIN … UNTIL`, a spin on `FLAG @` set between interpreter steps, and P33's own repro (`IF` body storing to a `CREATE`'d cell) all PASS | compiled loops and compiled branches work; the language is not broken in general — this reproduces P34 |
| 1b. spin whose flag only the host can write *during* the call | **hangs** (`timeout 5` → 124) | true of *any* spin in a single-threaded interpreter with no hook; says nothing about the block layer, so it does not separate the causes by itself |
| 1c. P33's prelude (`boot16.fs`), ten-line `IF` | **hangs** (124, no output) | the defect is in the prelude's branch *token*, before the mailbox is involved |
| 2. mailbox serviced during the spin, real wrapper | **completes 8/8 PASS** (`boot37.fs` + `blocks37.fs`), server's copy `blk0[9]=2a` | cause **H confirmed false**: the server already answers inside the word and the wrapper is the only broken part |
| 3. bounded wait, in Forth (`BLOCKR`, 4 polls → `ERR_NO_SERVER`) | **reaches the error** (`e3-bounded-noserver PASS`) | the loop runs; it does not hang before the bound — H again |
| wrapper cycles per poll | **not measured** | the `HOST` build has no cycle counter; `BLKWAIT` 4096 is a C counted loop, not a dispatch, so 726 cycles/dispatch is not the right yardstick (P33 already priced it at ~10× P16's 2740-cycle fetch) |

## 1. Answers

### 1.1 Experiment 1 — the language runs a compiled spin

`src/boot37.fs` is `boot16.fs` with one change (the branch token is emitted with `W,`, not `,`) plus
`BEGIN`/`UNTIL`, which this primitive set does not have at all (`p31_prims.inc` has `BRANCH` and
`0BRANCH` and no compiling loop words — a probe step written with `BEGIN … UNTIL` cannot even load
against `boot16.fs`, which is itself a finding).

```
e1-loopcount5 PASS          : E1A  5 SPINN 0 = T ;            5 iterations, no host involvement
e1-spin2000   PASS          : E1B  2000 SPINN 0 = T ;         2000 iterations
e1-branchstore KPASS        : B7  0= IF 0 OTHER ! 75 EMIT THEN ;   P33's exact repro ("any IF whose
                                                                body stores to a CREATE'd cell")
e1-preset-spin PASS         SETFLAG on one line, SPINF on the next: the doc's experiment 1
```

The last line is the doc's own protocol — the host sets `FLAG` between interpreter steps, then the
spin runs and terminates on the first poll. The complementary case (`0 FLAG !` then `SPINF`, nothing to
set it during the dispatch) hangs, **as it must**: `interpret()` is the only writer and the spin never
returns to it. That is not evidence about the block layer — the same hang happens for any spin on any
variable.

### 1.2 Cause L, precisely: the prelude emits the branch token with `,`

`P_COMMA` is a **4-byte, 4-aligned** comma:

```c
case P_COMMA:  a4(); a = rd32(V_HERE); wr32(a, POP()); wr32(V_HERE, a + 4); break;
```

while `ZBRANCH` reads its operand with `rd16_paged(ip)` and skips it with `ip += 2`, and `P_BRANCH`
reads `rd16_paged(ip)`. A token is 2 bytes (`cw`). `boot16.fs`'s `IF` is

```forth
: IF  ['] 0BRANCH ,  0 W,  HERE 2 - ;  IMMEDIATE
```

so the compiled stream is `[0BRANCH][0000][operand][body]`: the true path's `ip += 2` lands on the
zero filler (which then gets *executed* as a token), and the false path reads the filler as the branch
target — `0` — i.e. "return to C" and silently truncate the enclosing word. When `HERE` was 2 mod 4,
`a4()` also leaves a two-byte hole *before* the token, and that hole (`0x0000` = `DOCOL` at address 0)
is what actually hangs first. Measured, with the token trace:

```
TOK w=03b4 cf=0000 ip=0000 sp=0 rsp=0      DOCOL  (TRUE-IF)
TOK w=0048 cf=0004 ip=03b8 sp=0 rsp=1      LIT 0
TOK w=017a cf=0026 ip=03be sp=1 rsp=1      0=
TOK w=037c cf=0000 ip=03c0 sp=1 rsp=1      DOCOL  (T, the word with the IF)
TOK w=0000 cf=0000 ip=0380 sp=1 rsp=2      <- T's body starts with the 2-byte hole
TOK w=0000 cf=0000 ip=0004 sp=1 rsp=3      <- DOCOL at 0, recursively; rsp climbs 2,3,4,...
...
TOK w=0000 cf=0000 ip=0004 sp=1 rsp=68     (never returns: this is the "hang")
```

and the byte-level comparison of the same definition compiled by both preludes (`-d` dump, `NOK` is
the last word in the image):

```
mem16.h  … 48 00 | 01 00 00 00 | 7a 01 | 60 00 | 00 00 | 96 03 | 48 00 | 42 00 00 00 | a4 01 | 40 00
         LIT      1            0=      ZBRANCH  filler  operand  LIT     66            EMIT     EXIT
mem37.h  … 48 00 | 01 00 00 00 | 7a 01 | 60 00 | ca 03          | 48 00 | 42 00 00 00 | a4 01 | 40 00
         LIT      1            0=      ZBRANCH  operand          LIT     66            EMIT     EXIT
```

`mem16.h` is two bytes longer and the extra `00 00` sits exactly where `ZBRANCH` looks for its
operand. That is P33's "any `IF` whose body stores to a `CREATE`'d cell hangs, while the same body
under a bare `IF` runs": whether the extra bytes are fatal depends on what the stream happens to
execute next, not on the store.

### 1.3 Cause H is refuted: the server already answers inside the word

In the `HOST` build the fake server is not a separate thread and does not run "between interpreter
steps". `blk_xfer` rings the doorbell with `pl_hw(6, 0, 0)` **inside** the request, before its poll
loop:

```c
*st = 0;                                  /* 0 = pending */
pl_hw(6, 0, 0);                           /* doorbell: the host answers here (srv_answer) */
for (i = 0; i < BLKWAIT; i++) if (*st) break;
```

and the host's `pl_hw` case 6 calls `srv_answer()`, which writes the buffer, the checksum and the
status. So the mailbox is answered while the ULP is still inside `blk_xfer` — the model the probe
asked for in experiment 2 is already the model the harness has. That being so, a hang *cannot* be a
wait for the server: the answer is there before the loop starts, and for a black-hole block the C
bound runs out and returns `-3` (`w-no-server PASS` in §1.4 is exactly that, through the wrapper).
Cause H is consequently not "unconfirmed" but **false as an explanation of the hang**.

### 1.4 Three defects, and the wrapper passing 8/8 once they are fixed

| # | Where | Defect | Evidence |
| --- | --- | --- | --- |
| 1 | `boot16.fs` `IF`/`ELSE` | branch **token** emitted with `,` (4-byte, aligned) instead of `W,` (2 bytes) — operand mis-addressed, and a 2-byte hole executes as `DOCOL` at 0 | §1.2 |
| 2 | `blocks.fs` `BLOCK` | `0= IF DROP 0 BLKDRT ! EXIT THEN`: `0=` is TOS-only, so the `DROP` removed the **buffer address**, and `BLOCK` returned nothing — the caller's `!` popped an empty stack (`sp` wrapped to 255). Fixed by keeping a copy: `DUP 0= IF DROP …` | trace `sp=0` at `EXIT` with `BLKADR` expected; `A@0K@` test failed with `BLKERR=0` |
| 3 | `blocks.fs` `SAVE` | `… DUP BLKERR ! 0= IF …THEN EXIT`: the flag replaced the status, so `SAVE` returned nothing either | `w-reread-blk0` underflow right after `w-save-blk0`; fixed with `DUP 0=` |

With `boot37.fs` + `blocks37.fs` the **real wrapper words** exercise the whole layer end to end:

```
w-read-blk0  PASS     w-save-blk0  PASS     w-no-server  PASS     w-abort+read PASS
w-read-blk2  PASS     w-reread-blk0 PASS    w-busy        PASS     w-crc        PASS
SRV blk0[0]=00 blk0[9]=2a blk3[9]=1e
```

`blk0[9]=2a` is the *server's* copy: the write-back proof is still read off the answering side, now
through `BLOCK`/`UPDATE`/`SAVE` instead of through `BLKXFER`.

### 1.5 Experiment 3 — the bound, in Forth

`src/exp3.fs` polls `BLKXFER` at most four times and then raises `ERR_NO_SERVER`, entirely in Forth
(`BEGIN … UNTIL` on a `CREATE`'d counter — no C change, no harness hook):

```
e3-bounded-noserver PASS
```

i.e. block 15 (a black hole) is requested four times, each C poll runs out its `BLKWAIT`, the loop
counts down, `BLKERR` becomes `-3` and the word returns `-3`. **The loop runs to its bound; it does
not hang before it** — H again, and the "bound must be Forth" requirement is met: a program can see
the code. (The `stack underflow` printed after it is the *next* test word in `exp3.fs`, whose `AND`
chain is my own bad test shape, not the layer: `e3-server-answers` never ran.)

### 1.6 A fourth defect, in the harness: the pool must leave the buffer above the dictionary

P33's host build used `MEMSZ=2304`, so `BLKADR = 2304 - 512 = 1792` while the dictionary starts at 56.
`P37`'s wrapper test compiles to `image: 1842 bytes of 2304` — **50 bytes past the buffer**: the first
fetch overwrote the newest definitions and the next line failed to parse (`."?` at line 18 of exp2.fs,
with `w-read-blk0 PASS` just printed). Rebuilt with `-DMEMSZ=4096`; on the chip `mem` is 1420 of which
the dictionary keeps 908, so the 908/512 split P33 measured is the real constraint — but a host test
that loads a 456 B layer plus eight definitions has to leave the buffer above `HERE`, or a block test
measures dictionary corruption.

## 2. Evidence

### 2.1 Experiments 1 and 3

```sh
timeout 10 ./artifacts/host_blocks src/boot37.fs src/exp1a.fs     # -> logs/exp1.log
timeout 5  ./artifacts/host_blocks src/boot37.fs src/exp1b.fs     # the hang, expected: exit 124
timeout 25 ./artifacts/host_blocks src/boot37.fs src/blocks37.fs src/exp3.fs
```

```
e1-loopcount5 PASS
e1-spin2000   PASS
e1-branchstore KPASS
e1-preset-set e1-preset-spin PASS
e3-bounded-noserver PASS
```

### 2.2 The prelude defect, reproduced with P33's own prelude

```sh
timeout 5 ./artifacts/host_blocks src/boot16.fs src/exp_l.fs        # -> exit 124, no output
timeout 5 ./artifacts/host_blocks src/boot16.fs src/blocks.fs src/test_block.fs   # -> exit 124
timeout 5 ./artifacts/host_blocks src/boot37.fs src/exp_l.fs        # -> L-true PASS / L-false FAIL
```

`src/exp_l.fs` is ten lines: two `IF` words, one taking the branch and one falling through. Under
`boot16.fs` neither returns; under `boot37.fs` both do the right thing. (`L-false FAIL` is the
*expected* output: the branch falls through into `.\" FAIL"`.)

### 2.3 The token trace that named it

```sh
P37_TRACE=3000 timeout 5 ./artifacts/host_blocks_trace src/boot16.fs src/exp_l.fs 2>logs/trace_boot16.txt
grep -n "w=0000" logs/trace_boot16.txt | head -3
```

```
118:TOK w=0000 cf=0000 ip=0380 sp=1 rsp=2
119:TOK w=0000 cf=0000 ip=0004 sp=1 rsp=3
120:TOK w=0000 cf=0000 ip=0004 sp=1 rsp=4
```

`cf=0000` is `DOCOL`; `w=0000` is address 0. The return stack climbs one cell per iteration and never
unwinds — the definition of "hangs", and the reason a `timeout` kill alone could never say where.

### 2.4 The two compiled bodies

```sh
./artifacts/host_blocks -d artifacts/mem16.h src/boot16.fs src/exp_dump.fs
./artifacts/host_blocks -d artifacts/mem37.h src/boot37.fs src/exp_dump.fs
```

`exp_dump.fs` is one line, `: NOK 1 0= IF 66 EMIT THEN ;`. The byte comparison is in §1.2.

### 2.5 The wrapper, end to end

```sh
timeout 25 ./artifacts/host_blocks src/boot37.fs src/blocks37.fs src/exp2.fs
```

Eight checks, eight PASS, `SRV blk0[0]=00 blk0[9]=2a blk3[9]=1e` — see §1.4.

## 3. Verdict

**Cause L. The block layer's protocol was never the problem and neither was the harness: the Forth
that wraps it was wrong in three places, and the prelude's `IF` was the one that hung.**

* **(H) is refuted.** The host fake server answers *inside* `blk_xfer`, at the doorbell, before the
  poll loop; the bounded C poll returns `-3` for a black-hole block; and the same wrapper words
  complete with the right bytes once the Forth is fixed. There is no missing concurrent server in the
  model — there never was one.
* **(L) is confirmed, at three named places:** `boot16.fs`'s `IF`/`ELSE` emit the branch token with
  `,` (4-byte, aligned) instead of `W,` (2 bytes) — §1.2 names the bytes; `BLOCK` drops the buffer
  address on success; `SAVE` drops its returned status. The first hangs; the second and third
  silently mis-shape the stack (host: `sp` wrapped to 255).
* **What it means for trusting the block layer:** the protocol claim (P33's 4/4) stands and the
  wrapper claim now stands **too, on the corrected words** — 8/8 through `BLOCK`/`UPDATE`/`SAVE`, with
  the write-back read off the server's copy. What must *not* be trusted is `blocks.fs` as P33 left it,
  and, more urgently, **`boot16.fs` as a compiler**: any host test that loaded it measured a broken
  `IF` (P33's wrapper tests, and any P26/P31/P34 host test with the same prelude). The bound the probe
  asked for exists and is visible to a program: `ERR_NO_SERVER` after N polls (§1.5).
* **The port is not implicated.** Nothing here is about wake length or the main core answering inside
  144 µs; the machine's branches, loops and dispatch are the same machine P34 exercised.

## 4. Doc deltas (verbatim, for the orchestrator to apply — `docs/` was not edited)

### 4.1 `docs/01-proposal.md` §4.5 — the wrapper's status, and the bound

```
**The block layer's wrapper, and why P33 saw it hang (P37).** The C protocol was never at fault and
neither was the harness: in the host build the answering side runs *inside* `blk_xfer` at the
doorbell, before the bounded poll, so a "missing concurrent server" cannot explain a hang. The Forth
that wraps the protocol had three defects, and they are fixed:

* the prelude's `IF` emitted its branch **token** with `,` — a 4-byte, 4-aligned cell — while `ZBRANCH`
  reads a 2-byte operand. Every compiled `IF` therefore read its target from a zero filler (true path)
  or jumped to 0 (false path), and when `HERE` was 2 mod 4 the two-byte hole in front of the token was
  executed as `DOCOL` at address 0, which is the hang P33 recorded. The token must be emitted with `W,`.
* `BLOCK` ran `0= IF DROP 0 BLKDRT ! EXIT THEN` on a stack of ( addr st ). `0=` is a top-of-stack op,
  so the flag replaced the status and the `DROP` threw away the buffer address: on success `BLOCK`
  returned nothing and the caller's `!` popped an empty stack. It needs `DUP 0= IF DROP …`.
* `SAVE` lost its returned status the same way, and needs `DUP 0= IF …THEN` too.

With those three lines corrected the wrapper words pass end to end on the host: `BLOCK` read, `SAVE`
write-back (the *server's* copy becomes the new bytes), `ERR_NO_SERVER`, `ERR_BUSY`, `BLK-ABORT` then a
re-read, and `ERR_CRC` — 8 of 8. The wait is bounded in Forth as well as in C: a retry counter in the
program reaches `ERR_NO_SERVER` after N polls, so the bound is a value a program can see, not a
harness timeout. A synchronous wait is safe for the same reason it was always safe — the main core
answers the doorbell inside the wake (P16: 144 us) — and the layer never relies on anything but that.
```

### 4.2 `docs/02-harness.md` §2 — how the harness models the answering side

```
**The block server runs inside the request (P37).** The host build does not need a second thread: the
engine's doorbell, `pl_hw(6, 0, 0)`, is called from `blk_xfer` *before* its poll loop, and the host's
`pl_hw` case 6 calls `srv_answer()`, which fills the buffer, the checksum and the status. That is the
model the chip has — the main core answers while the ULP is still inside the word — so any hang seen
in a block test is in the Forth above the handshake, never a missing server. Two rules follow:

* the pool must leave the 512 B buffer **above** the dictionary. P33's host build used `MEMSZ=2304`,
  which puts `BLKADR` at 1792 while P37's wrapper test compiles to `HERE=1842`: the first fetch
  overwrites the newest definitions and the next line fails to parse (`."?`). Use `MEMSZ=4096` on the
  host, or check `-d`'s `image: N bytes of M` against `M-512` before blaming the layer.
* a compiling prelude must emit **tokens** with `W,` (2 bytes) and only *operands* with `,`/`W,` as
  the primitive reads them. `boot16.fs` is otherwise the correct 16-bit prelude, but its `IF`/`ELSE`
  are not: fix them before any host test loads them.
```

### 4.3 `docs/JOURNAL.md` — the answer, because it decides whether the block store is trusted

```
**The block store hangs were mine, not the machine's.** P33 left the wrapper words hanging and the
right question open: was the harness missing a server, or were the compiled branches broken? P37
answered it with three cheap experiments. The fake server already answered *inside* `blk_xfer` — at the
doorbell, before the poll — so no concurrent server was ever missing, and a black-hole block returned
`ERR_NO_SERVER` from the bounded poll without hanging. The hang had three causes, all in Forth: the
prelude's `IF` emitted its branch token with the 4-byte `,` instead of the 2-byte `W,`, so every
compiled branch read its operand two bytes from where `ZBRANCH` looks (and a `0x0000` hole in front of
the token executed as `DOCOL` at address 0 — the actual hang); `BLOCK` dropped the buffer address on
the success path because `0=` is a top-of-stack op and the `DROP` removed the address, not the status;
`SAVE` lost its returned status the same way. Fix the three lines and the wrapper passes 8 of 8 end to
end, with the write-back read off the server's own copy. A fourth defect was the harness: `MEMSZ=2304`
on the host put the 512 B buffer at 1792 while the test's dictionary reached 1842, so the fetch
overwrote the definitions and the next line failed to parse. The lesson is bigger than the block file:
`boot16.fs`'s branch words were wrong, and every host test that loaded it — P33's, and any of
P26/P31/P34's with the same prelude — measured a broken compiler. The block store keeps its claim
(protocol 4/4, wrapper 8/8) on the corrected words; the layer as P33 left it does not.
```

## 5. Follow-ups

1. **Fix `boot16.fs`'s `IF`/`ELSE` in `probe/` as one prelude (P37's `src/boot37.fs`), and re-run the
   host tests that loaded the old one** — P33's wrapper test, and any P26/P31/P34 host build with the
   same branch words. Anything that "hung" under the old prelude should be re-read as unmeasured.
2. **`BEGIN`/`UNTIL` are not primitives and not in any prelude** — a probe step written as the doc
   wrote it (experiment 1) does not load. `boot37.fs` adds them in six lines; they belong in the same
   shared prelude as the branch words.
3. **`RAISE` in `blocks.fs` has the same stack-shape bug** (`DUP ERR_BUSY = IF DROP …` drops the code
   it promises to keep). It does not affect `BLOCK`/`SAVE`, but it is the next thing a caller will
   trip on.
4. **The failure path of `BLOCK` should return the code, not the flag.** With `DUP 0= IF DROP …` the
   failure path returns the status (measured: `15 BLOCK` leaves a value, `BLKERR @ -3 =` true), but the
   order (`SWAP DROP` after `0=`) is fragile: a reader cannot tell from the line which cell is
   returned. Spell it with the status copied to a variable, or with `RAISE`.
5. **Host `MEMSZ` must be checked against `HERE`** (§1.6). A one-line assert in `build.sh`
   (`image: N` vs `M-512`) would have caught it in a second instead of a wrong parse error.
6. **Cycles per poll are still unmeasured** — the host has no cycle model. If the number matters for
   the wake budget, it needs the chip or P14's harness, and `BLKWAIT` 4096 is the only lever.

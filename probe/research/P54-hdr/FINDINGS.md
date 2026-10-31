# P54 — 3-byte dictionary header: **GO**, app space 354 → **439 B**, and the `.text` side is a wash (−8 B)

Question (falsifiable): can the dictionary header be `hash13 | xt10 | imm1` — 3 bytes instead of 4 — so that
`V_LATEST` rises by 85 B and the freed dictionary area becomes application space, at a `.text` cost smaller
than 85 B?

**Answer: yes.** The dictionary area shrinks 340 → 255 B (−85 B) and the measured whole-ELF `.text` delta is
**−8 B**, so at the shipping `MEMSZ` 1400 the app space goes 354 → 439 B and the pool goes 7 853 → 7 845 of
7 856 (3 → 11 B of headroom). Two caveats are stated up front because they decide how much of this is a win:

1. **The −8 B is not the design's cost.** The functions that actually changed cost **+82 B** (`find` +48,
   `mkhdr` +26, `main` +8). The other **−90 B** is GCC un-inlining `wr8()`/`wr16()` once `mkhdr_pad` calls
   `wr8` a third time, which a later edit could undo. If it is undone, `.text` ≈ 5 334 and, at the fixed pool,
   the app-space gain collapses from +85 B to ~+3 B. The dictionary saving is unconditional; the `.text` side
   is a coin that currently lands face up. §4 gives the arithmetic.
2. **The design's own guard rails found two real traps**, both recorded as `// GUARDRAIL`s and both caught by
   measurement, not review: a 1-bit-wide mask error in the `xt/2` reconstruction (§2.4), and the fact that the
   prelude's `IMMEDIATE` writes the flag with a *cell* store that a 3-byte stride breaks (§2.5).

---

## 0. Method and the twin-build check

`./measure.sh <name>` compiles `src/ulp_repl.c` (which `#include`s `src/uforth.c` and the baked `src/image.h`)
with the **shipping** ULP compile command out of `probe/repl/build/esp-idf/main/ulp_main/compile_commands.json`,
links with the **shipping** link line out of `build.ninja` and the shipping object list minus our own, then reads
`riscv32-esp-elf-size -A` and the sha256 of `.text`.

Baseline self-check (must reproduce the flashed image before any delta is believed):

```
$ ./measure.sh base
base       elf .text=5252  .rodata=308  .data=1416  .bss=877 | obj .text=6106 | sha=5e9434a7c6096071
$ riscv32-esp-elf-objcopy -O binary --only-section=.text <shipping ulp_main.elf> out/ship.text
$ sha256sum out/ship.text out/base.text
5e9434a7c609607128949f1741f0af0e1ba207ab31a04ef5980da676a3e0a7f1  out/ship.text
5e9434a7c609607128949f1741f0af0e1ba207ab31a04ef5980da676a3e0a7f1  out/base.text
```

The twin is the flashed image, byte for byte. No board, no flash, no `idf.py`; `/dev/ttyACM*` untouched.

---

## 1. Go/no-go: the hash search

### 1.1 The search runs on the engine's own vocabulary, not a re-parse

`src/uforth.c` gained a `-DP54_NAMES` dump inside `mkhdr_pad` (host bake only) — the one place a name becomes a
header. A regex over the prelude would be a second derivation of the same list (R6) and a name missed there is
exactly the collision the search never sees.

```
$ gcc <bake flags> -DP54_NAMES -o out/bake_names src/uforth.c
$ ./out/bake_names -d out/image_names.h src/p39_prelude.fs src/line.fs 2> out/names_final.log
$ grep -c '^NAME ' out/names_final.log
85
```

Cross-check that this lexicon *is* the dictionary: recomputing djb2/m33/seed 5381 over those 85 names and
masking to 13 bits reproduces every stored key, in order (`stored hash13 == recomputed hash13 for every name:
True`, §5.3).

### 1.2 Result

```
$ tools/hashsearch.py out/names_final.log
vocabulary: 85 words, 13-bit key (8192 values), expected collisions for a random hash = 0.436
baseline djb2 m=33 seed=5381 low13: 0 colliding pairs
searched 15330 (multiplier, seed, fold) triples: 5976 collision-free
    OK mult=33    seed=5381   fold=None
    OK mult=3     seed=0      fold=None
    ...
chosen: mult=33 seed=5381 fold=None  (the shipping constants: only the mask changes)
```

- **A collision-free hash13 exists.** 5 976 of the 15 330 searched `(odd multiplier, seed, fold)` triples are
  injective over these 85 names.
- **The shipping hash already is one**, at no cost: `djb2 × 33 + c`, seed 5 381, masked to 13 bits, has **zero**
  colliding pairs. So `hash_pad`'s loop is unchanged — only its mask moved — and the risk of "a new hash
  function that behaves differently at bake time than at run time" is zero by construction.
- The expected count for a random hash is 0.44 pairs, i.e. this was a **coin flip that landed heads**; the
  search is what turns it into a fact, and the bake-time check (§1.3) is what keeps it a fact when a word is
  added.
- Headroom, measured rather than asserted: the same shipping hash first collides at **11 bits** (`SAVE` vs
  `THEN`, 0x2d4); at 12 and 13 it is clean. So 13 is margin, not luck. A word added later collides with the
  existing set with probability 85/8192 = **1.0 %** (2.1 % at 12 bits) — and the bake refuses rather than
  mis-dispatching.

The tool is mutation-tested (R12): append a name chosen to collide at 13 bits (`ZDSX`, found by brute force
against `I`) and it must report the pair —

```
$ python3 tools/hashsearch.py out/names_mut.log
vocabulary: 86 words, 13-bit key (8192 values), ...
baseline djb2 m=33 seed=5381 low13: 1 colliding pairs
    COLLISION 'I' vs 'ZDSX' at 0x15ee
```

### 1.3 Enforcement: the bake-time check now guards 13 bits, and it fires

The `-d` path's pairwise check was re-expressed for the 3-byte entry (`rd24(a) >> 11`) and the same collision
was driven through the **bake**, not the tool:

```
$ ./out/bake_names -d out/image_collide.h out/collide_prelude.fs src/line.fs   # prelude + ": ZDSX ;"
image: code 582 + headers 258, free 432 (MEMSZ 1400, 86 words x 3 B)
FATAL: hash collision 0x15ee between xt=578 and xt=70 — widen the hash or rename a word
bake exit=3
```

`tools/bake.sh` runs under `set -e`, so it never prints "baked". (It does leave the already-dumped `image.h`
behind — see risk R-2.)

---

## 2. The layout, and the deliberate revisit of two alignment assumptions

### 2.1 Entry

24 bits per entry, little-endian, written/read byte-wise:

```
bit  0      imm        (the prelude's IMMEDIATE writes this, with one C!-sized RMW)
bits 1..10  xt/2       (10 bits: 2 KiB of code area)
bits 11..23 hash13
byte 0 = imm | (xt/2 & 0x7f) << 1
byte 1 = (xt/2 >> 7) & 7 | (hash13 & 0x1f) << 3
byte 2 = hash13 >> 5
```

`HDRSZ 3u`; entries grow down from `HDRTOP`; `V_LATEST = HDRTOP − 3·N`; `N = 85` for the baked prelude.

**Why `imm` is at bit 0 and not inside a byte somewhere:** the prelude's `IMMEDIATE` is the only writer of that
flag and the only thing it can do is one byte read-modify-write. Any packing that buries `imm` mid-byte turns
`IMMEDIATE` into a two-byte RMW over its neighbour's entry.

### 2.2 Alignment: the two old `_Static_assert`s are gone, on purpose

`_Static_assert(MEMSZ % 4)` and `_Static_assert(HDRTOP % 4)` existed **only** so that a 4-byte entry could be
one `lw`. With a 3-byte stride, `HDRTOP − 3k` alternates parity with `k`, half of the entries are at odd
addresses, and an `lh`/`lw` there **traps** on rv32 (F-78). So:

- every access to the header area is a **byte** access (`mem[h]`, `wr16 + wr8`, `C@`/`C!`);
- the two old asserts are replaced by the invariants the new layout actually needs:
  `_Static_assert(MEMSZ <= 2048)` (10-bit `xt/2` ⇒ code area under 2 KiB) and
  `_Static_assert(HDRTOP <= MEMSZ)` (this is what licences `find()`'s unchecked `mem[...]` reads: the loop
  bounds `h + 3 <= HDRTOP`, so `h + 2 < MEMSZ` is *proved*, not hoped).

### 2.3 `image_boot_assert`: the `& 3` test had to change or it would halt every correct image

```
-    if (latest > MEMSZ || (latest & 3u) != 0u || here > latest) pl_halt(0x51u);
+    if (latest > MEMSZ || ((u32)HDRTOP - latest) % HDRSZ != 0u || here > latest) pl_halt(0x51u);
```

`latest & 3` is false for the new images by construction (`V_LATEST = 1017`), so keeping it would have turned a
correct bake into a `pl_halt(0x51)` on the chip. What it was *for* — an image and an engine that disagree about
the header geometry (E-079's class) — is now expressed as "the baked span is a whole number of entries": a
4-byte image against a 3-byte engine leaves `HDRTOP − latest ≡ 1 (mod 3)`, and so does any hand-baked image.
`latest > MEMSZ` stays as the guard against a bake at another `MEMSZ`, because the image carries an absolute
`V_LATEST`. Verified on the real image: `latest 1017 ≤ 1400`, `(1272−1017) % 3 == 0`, `here 578 ≤ 1017`.

### 2.4 `xt/2`: proved in code, and the guard earns its 6 bytes

`xt` is a byte offset into `mem[]` and tokens are `u16`, so every code offset is even. Proof, in this order:

- `_Static_assert(MEMSZ <= 2048, "xt is stored as xt/2 in 10 bits …")` — the *capacity* half. The host suite
  builds at `MEMSZ 2048` where the last even offset is 2046 and `xt/2 == 1023` still fits; anything above needs
  a 4th byte (i.e. no saving) or a token-indexed `xt`.
- a bake-time check in `mkhdr_pad`, the only place an offset becomes a header field:

```c
if (x & 1u) { msg(MSG_ERR_DICT); errf = 1; return 0; }   /* x = V_HERE */
```

  The only writers of `V_HERE` are `cw()` (+2), `a4()` (round up to 4), `boot_init` (`DICT` = 56) and a state
  restore, so an odd value is an engine bug, not user input — and an odd `xt` would be *halved* into a
  wrong-word dispatch with no `?` anywhere. Measured cost of keeping it unconditional in the ULP: **6 B**
  (5 244 → 5 238 with it compiled out of the `IMAGE` build). Kept.
- The mask bug this guard would not have caught was found by the bake instead: the first version returned
  `((b1>>5)|(b2<<3)) & 0x7fe`, which clears `xt/2`'s bit 0, so every word at `xt ≡ 2 (mod 4)` resolved one
  halfword low (`SPAWN` → xt 94 while its header said 190). The mask-then-double form
  (`(((b1 & 7u) << 8) | (b0 & 0xfeu))`) is what ships; the guardrail is on those lines.

### 2.5 The prelude's `IMMEDIATE` was a 4-byte cell store — it had to become a byte store

```
-: IMMEDIATE  LATEST DUP @ 1 OR SWAP ! ;
+: IMMEDIATE  LATEST DUP C@ 1 OR SWAP C! ;
```

Unchanged, this is the interesting failure: `@` at `V_LATEST` reads 4 bytes spanning the newest entry **and**
the one above it, ORs bit 0, and `!` writes those 4 bytes back over the neighbour. The dictionary then has one
corrupted entry, `IMMEDIATE` "works", and the symptom appears lines later (`IF?`, `HERE?`). Same size class as
before (7 tokens vs 8), and the whole prelude still lands at `V_HERE = 578` — the code area did not grow.

---

## 3. Measured variants

All rows: `MEMSZ 1400`, bake flags from `tools/bake.sh`, suite = `tests/run.sh` (11 PASS lines = 9 test files +
the ring drain + the unknown-code check). `.data` is 1 416 in every row because `mem[MEMSZ]` is a fixed-size
array and the header area lives *inside* it — **the 85 B does not appear as a section delta**; it appears as
`V_LATEST − V_HERE` in the baked image. `.rodata` and `.bss` are unchanged by every variant.

| variant | what changed | `.text` | Δ`.text` | `.rodata` | `.data` | `.bss` | suite |
|---|---|---|---|---|---|---|---|
| `base` (shipping twin) | 4-byte entry, `hash20` | 5 252 | — | 308 | 1 416 | 877 | green (10 PASS; `hdr.fs` did not exist yet) |
| A | 3-byte entry; `find` = byte filter; `mkhdr` = 3×`wr8`; odd-`xt` guard | 5 256 | **+4** | 308 | 1 416 | 877 | 11 PASS |
| **B (winner)** | A with `mkhdr` = `wr16` + `wr8` | **5 244** | **−8** | 308 | 1 416 | 877 | **11 PASS** |
| C | B with a word-shaped store at `h−1` (`wr32(h-1, v<<8)`), room check tightened to `x+1 > h` | 5 324 | +72 | 308 | 1 416 | 877 | 11 PASS |
| D | B with the odd-`xt` guard compiled out of the `IMAGE` build | 5 238 | −14 | 308 | 1 416 | 877 | 11 PASS |

C is the interesting negative: buying a word-shaped store costs **1 byte of app space** (the room check must
leave the slack byte below the newest entry free) and **72 B of `.text`**. Not shipped.

D is the "how much is the guard worth" row: 6 B. Not shipped — §2.4.

### 3.1 Where B's −8 B comes from, exactly (this is the caveat in the headline)

Per-symbol, `riscv32-esp-elf-nm -S --size-sort` on `base` vs `B`; the sum closes to the section delta:

| symbol | base | B | Δ |
|---|---|---|---|
| `find` | 58 | 106 | **+48** — the design's own cost |
| `mkhdr` (has `mkhdr_pad` inlined) | 112 | 138 | **+26** — packing + 3-byte store |
| `main` (boot assert inlined) | 882 | 890 | **+8** — `% 3` stride check |
| `wr16` | 66 | 26 | −40 — now two calls to `wr8` |
| `vm_enter` | 2 782 | 2 704 | −78 — 4 inlined `wr8` bodies became calls |
| `word` | 172 | 170 | −2 |
| `wr8` | (inlined, no symbol) | 30 | +30 — became a real function (9 call sites) |
| **sum** | | | **−8** = measured Δ`.text` |

So: **the design costs +82 B; the compiler gives back −90 B because a third `wr8` reference in `mkhdr_pad`
tips `wr8` over the inlining threshold.** That is a real property of *this* build (byte-writing primitives —
`C!`, `."`, … — now pay one call each instead of an inline bounds test), and it is honest to measure it, but it
is not a property of the design. It is why §4 gives both the shipped figure and the pessimistic bound.

### 3.2 What it does to lookup cost (instructions, not cycles)

A `find()` miss is the whole cost of this function (P46 measured find as the dominant cost of typing).

- base, per entry: 6 instructions in `find` (`mv`, `addi`, `bgeu`, `jal rd32`, `srli`, `bne`) + `rd32`'s own 9
  + **two** `rd16` calls at 9 each — ≈ **33 instructions and 3 calls per miss**.
- B, per entry: `addi`, `mv`, `addi`, `bgeu`, `lbu`, `bne` — **6 instructions and no calls per miss**; only a
  candidate pays the second `lbu` and one more compare.

  (Counted off `riscv32-esp-elf-objdump -d` of both ELFs, straight-line path; not cycles.)

That is the direction the change wants (fewer instructions on the input path, a narrower 3-byte entry), but
**cycles and microseconds are not measurable on the host** — see §7.

---

## 4. Net byte figure

```
app space = V_LATEST − V_HERE = (MEMSZ − BLKSZ − 3·85) − V_HERE
          = (1400 − 128 − 255) − 578 = 1017 − 578 = 439 B        (was (1400−128−340) − 578 = 354 B)
pool      = .text + .rodata + .data + .bss = 5244 + 308 + 1416 + 877 = 7845 of 7856   (was 7853)
```

| | base | B | Δ |
|---|---|---|---|
| headers | 340 B (85 × 4) | 255 B (85 × 3) | **−85** |
| `V_HERE` | 578 | 578 | 0 |
| `V_LATEST` | 932 | 1017 | +85 |
| **app space** | **354 B** | **439 B** | **+85 B (+24 %)** |
| `.text` | 5 252 | 5 244 | −8 |
| pool used / 7 856 | 7 853 | 7 845 | −8 (3 → 11 B free) |
| app-space **ceiling** (pool spent down to 0 B headroom: `7856 − non-mem total − 961`) | 357 B (MEMSZ 1403) | 450 B (MEMSZ 1411) | +93 |

Shipped at the unchanged `MEMSZ 1400`: **+85 B app space and +8 B of pool headroom**, i.e. the change pays for
itself and leaves a little.

**Pessimistic bound (stated so it is not a surprise later):** if the `wr8`/`wr16` un-inlining is undone by a
later edit, Δ`.text` becomes +82, `MEMSZ` at the same pool can only be 1 321, and the app space becomes
1 321 − 961 = **360 B**, i.e. **+6 B** instead of +85 B. The dictionary saving is real in both worlds; the
`.text` side is what decides how much of it survives.

---

## 5. Validation

### 5.1 Suite (re-baked `src/image.h`, `tools/bake.sh 1400`)

```
$ ./tools/bake.sh 1400
image: code 578 + headers 255, free 439 (MEMSZ 1400, 85 words x 3 B)
baked src/image.h at MEMSZ=1400

$ ./tests/run.sh
PASS addr.fs (4 bytes)      PASS lookup.fs (6 bytes)      PASS suite.fs (42 bytes)
PASS blocks.fs (45 bytes)   PASS ntsk.fs (10 bytes)       PASS ring drain: order, completeness, …
PASS blocks_noserver.fs     PASS semantics.fs (8 bytes)   PASS unknown message code is named
PASS deep.fs (12 bytes)     PASS hdr.fs (4 bytes)
```

`lookup.fs` (case-insensitivity, newest-wins) and `semantics.fs` (storage rules) both pass, unchanged. No golden
file needed editing: the only layout-dependent numbers a test prints are `HERE`/`LATEST`, and `suite.fs` prints
`HERE .` (same value) and `LATEST 0 <> .` (a truth value).

### 5.2 The new test, `tests/hdr.fs`, and its mutation tests

It asserts the two things a 3-byte entry can get wrong *silently*:

```
LATEST : H1 ; LATEST - .        \ one definition moves LATEST by exactly one entry → 3
: HI 42 EMIT ; IMMEDIATE
: USEHI 43 EMIT HI 44 EMIT ;    \ IMMEDIATE must run while USEHI is being COMPILED …
USEHI                          \ … so '*' comes out BEFORE '+,' — the ordering is the proof
```
expected `3*+,`.

Mutation A — stride back to 4 bytes (`#define HDRSZ 4u`):

```
FAIL  hdr.fs
  want: 3*+,
  got : 4*+,
```

Mutation B — the immediate flag read from bit 1 instead of bit 0 (`*imm = (u8)((b0 >> 1) & 1u)`):

```
FAIL  hdr.fs
  want: 3*+,
  got : GUARDRAIL:?          (the prelude cannot load: its immediate words are no longer immediate)
```

Both restored; `PASS hdr.fs` again afterwards.

### 5.3 The baked image is the dictionary (the path the chip takes)

A `-DIMAGE` host build reads the *baked* `src/image.h` instead of building a dictionary:

- `'-tick'` every one of the 85 names out of the baked image and compare with the header bytes:
  `tick == stored xt for every word: True`, all xt distinct, all even, all inside `[56, 578)`;
  `stored hash13 == recomputed hash13 for every name: True`;
  the words whose stored `imm` bit is set are exactly
  `; [' ] LITERAL ." \ ( IF THEN ELSE BEGIN UNTIL WHILE REPEAT` — the compile-time set, so the flag at bit 0
  round-trips through the bake and through `find()`.
- Same visible behaviour as a freshly-built dictionary: `suite`, `lookup`, `semantics`, `addr`, `deep`, `ntsk`
  and `hdr` produce **byte-identical** transcripts from the baked image and from the rebuild. (`blocks*` differ
  only by the `BLKADR`/`V_HERE` values they print, which follow `MEMSZ`; the untouched shipping tree shows the
  same difference, so it is pre-existing and not this change.)

---

## 6. The diff (winner B)

Full text in `out/win.diff` (275 lines, both source files). `src/image.h` is regenerated by
`tools/bake.sh 1400` (same 6 522 B file, 50 lines of dictionary bytes changed) and is not shown.

```diff
--- probe/repl/src/uforth.c
+++ src/uforth.c
@@ static void wr32(u32 a, u32 v)   { wr16(a, v); wr16(a + 2, v >> 16); }
+/* GUARDRAIL: host-only. A 3-byte header entry (P54) cannot be read with rd32 at all — half of the
+ * entries sit at odd addresses and an `lw` there traps on rv32 — so the bake-time collision check needs
+ * this reader. find() must NOT call it: there the bytes are compared one at a time on purpose, so the
+ * load is the filter. Guarded out of the ULP image, where nothing reads a whole entry. */
+#ifdef HOST
+static u32 rd24(u32 a)           { return rd8(a) | (u32)rd8(a + 1) << 8 | (u32)rd8(a + 2) << 16; }
+#endif

@@ (- moves the P51 header-layout block ABOVE image_boot_assert, which now needs HDRTOP/HDRSZ)
+ * ---- P54: 3-byte entries, 24 bits = `imm1 | xt10 | hash13` (little-endian: imm is bit 0) ----
+ * GUARDRAIL: the 4-byte entry was `imm1 | xt11 | hash20`, i.e. 8 spare bits per word …
+ * GUARDRAIL: the stride is 3 now, so an entry is NOT 2- or 4-aligned … Every access to this area is a
+ * byte access — do not "optimise" find() back to rd16/rd32.
+ * GUARDRAIL: imm stays at BIT 0 because the prelude's IMMEDIATE … can only reach one byte.
+ * GUARDRAIL: the previous `_Static_assert(MEMSZ % 4)`/`(HDRTOP % 4)` existed ONLY for the 4-byte
+ * entries' alignment, and they are gone with them …
+ * GUARDRAIL: xt/2 assumes every code offset is EVEN … mkhdr_pad asserts that rather than trusting it.
+ * GUARDRAIL: 13 bits over 85 words has an expected 0.44 collisions … tools/hashsearch.py proves
+ * injectivity … 12 also works; 11 collides (SAVE vs THEN).
+#define HDRSZ 3u                 /* bytes per entry: 24 bits = imm1 | xt10 | hash13 */
+_Static_assert(MEMSZ <= 2048, "xt is stored as xt/2 in 10 bits: the code area must stay under 2 KiB");
+_Static_assert((HDRTOP) <= MEMSZ, "the header area lives inside mem[]: find() indexes it without rd8()");

@@ image_boot_assert
-    if (latest > MEMSZ || (latest & 3u) != 0u || here > latest) pl_halt(0x51u);
+    if (latest > MEMSZ || ((u32)HDRTOP - latest) % HDRSZ != 0u || here > latest) pl_halt(0x51u);

@@ hash_pad
-    return h & 0xfffffu;                     /* 20 bits: the entry has 11 for xt and 1 for immediate */
+    return h & 0x1fffu;                      /* 13 bits: the entry has 10 for xt/2 and 1 for immediate */

@@ find
-    u32 key, hs, h;
+    u32 hs, h;
+    u8 b0, b1;
-    for (h = rd32(V_LATEST); h + 4u <= (u32)HDRTOP; h += 4u) {
-        key = rd32(h);
-        if ((key >> 12) != hs) continue;
+    for (h = rd32(V_LATEST); h + HDRSZ <= (u32)HDRTOP; h += HDRSZ) {
+        if (mem[h + 2u] != (u8)(hs >> 5)) continue;      /* 8-bit filter: a miss is one lbu */
+        b1 = mem[h + 1u];
+        if ((b1 >> 3) != (u8)(hs & 0x1fu)) continue;
+        b0 = mem[h];
-        *imm = (u8)(key & 1u);
-        return (u16)((key >> 1) & 0x7ffu);
+        *imm = (u8)(b0 & 1u);
+        return (u16)((((u32)(b1 & 7u)) << 8) | (b0 & 0xfeu));

@@ mkhdr_pad
-    u32 hs = hash_pad(rd8(PAD)), x = rd32(V_HERE), h = rd32(V_LATEST) - 4u;
-    if (x + 2u > h || (x & 0x7ffu) != x) { msg(MSG_ERR_DICT); errf = 1; return 0; }
+    u32 hs = hash_pad(rd8(PAD)), x = rd32(V_HERE), h = rd32(V_LATEST) - HDRSZ, v;
+    if (x + 2u > h || x >= 2048u) { msg(MSG_ERR_DICT); errf = 1; return 0; }
+    if (x & 1u) { msg(MSG_ERR_DICT); errf = 1; return 0; }          /* xt/2 is lossless only if x is even */
+    v = ((hs << 11) | ((x >> 1) & 0x3ffu) << 1) | (u32)(imm & 1u);
-    wr32(h, (hs << 12) | ((x & 0x7ffu) << 1) | (u32)(imm & 1u));
+    wr16(h, (u16)v); wr8(h + 2u, (u8)(v >> 16));

@@ main() -d path
-    fprintf(stderr, "image: code %u + headers %u, free %u (MEMSZ %u, %u words)\n", …, / 4u);
+    fprintf(stderr, "image: code %u + headers %u, free %u (MEMSZ %u, %u words x %u B)\n", …, / HDRSZ, HDRSZ);
-    for (a = rd32(V_LATEST); a + 4u < (u32)HDRTOP; a += 4u) { ka = rd32(a) >> 12; …
+    for (a = rd32(V_LATEST); a + HDRSZ < (u32)HDRTOP; a += HDRSZ) { ka = rd24(a) >> 11; …
+            (collision report prints xt as rd24(x) & 0x7fe)

--- probe/repl/src/p39_prelude.fs
+++ src/p39_prelude.fs
-: IMMEDIATE  LATEST DUP @ 1 OR SWAP ! ;
+: IMMEDIATE  LATEST DUP C@ 1 OR SWAP C! ;
 (+ 5 lines of GUARDRAIL: a 32-bit RMW at V_LATEST spans two entries and rewrites the older one)
```

New files in this directory: `tools/hashsearch.py` (the injectivity search, §1.2), `tests/hdr.fs` +
`tests/hdr.expected` (§5.2), and the `-DP54_NAMES` dump inside `mkhdr_pad` (§1.1) with `rd24()` for the
bake-time check.

---

## 7. What the host cannot answer (R8)

- **Cycles and µs.** `find()` went from ~18 instructions + 3 calls per miss to ~6 instructions + 0 calls
  (§3.2) — that is an instruction count from `objdump`, not a timing. The chipless benefit claim must be
  confirmed with the device bench (`bench/run.sh`), which I could not run.
- **The trap class.** An odd-address `lh`/`lw` traps only on rv32; on the host the same mistake reads a
  plausible number. Every alignment statement above therefore ends in "byte access" rather than in a test.
- **The wrong-word class.** A hash collision, or a half-offset `xt`, dispatches the wrong word with no error
  on the chip; the host catches it only because the tests compare a transcript. The bake-time check is the
  real defence and it only covers the *baked* vocabulary (§R-1).
- **Pool fit.** `flash_safe.sh` owns that number; I measured sections only, and the pool arithmetic in §4
  assumes the shipping non-`mem` overhead is exactly what `size -A` reports.

---

## 8. Residual risks

- **R-1 — a collision at run time is not checked, only at bake time.** Words defined at the prompt (or by a
  test `.fs`) that collide at 13 bits from an existing word shadow it silently; the `-d` check never sees them.
  This gap existed before (at 20 bits it was ~4 000× less likely). Closing it means a check in `mkhdr_pad`,
  which is on the chip (`:` reachable) and would cost `.text` on every definition path — a decision for the
  next probe, not a silent addition here.
- **R-2 — the bake writes the image *before* the collision check.** A colliding bake exits 3 (`bake.sh`
  aborts under `set -e`) but leaves the poisoned `src/image.h` behind. Moving the pairwise check above the
  `fopen` would make the guard also protect the artifact; it is host-only code and would cost 0 B of ULP
  `.text`. Not done here because it changes the bake tool's behaviour beyond this task's scope.
- **R-3 — the `.text` figure depends on a compiler inlining decision** (§3.1). Re-measure `.text` after any
  edit that touches byte-written primitives; if `wr8` gets inlined again, expect ≈ 5 334 and re-derive `MEMSZ`.
- **R-4 — `P31_TRACE`'s `p31_report()` still decodes the pre-P51 name layout** (`rd8(h + 2) & 31`). It is
  compiled into no build, and with a 3-byte stride it would decode nonsense. Left untouched (not this task),
  but it must not be revived as-is.
- **R-5 — `MEMSZ` must be re-baked with the engine.** Unchanged in this task (`ulp_repl.c` still says 1400,
  `tools/bake.sh 1400` re-baked `src/image.h`), and `image_boot_assert` now also checks the stride class.

---

## 9. Verdict

**GO.** A collision-free 13-bit hash exists — the shipping djb2 multiplier already is one, so only the mask
moved — and the 3-byte entry is worth **+85 B of application space** (354 → 439 B) at the shipping `MEMSZ`,
with `.text` measured **−8 B** across the whole ELF. The `.text` side is not free: the changed functions cost
+82 B and the remainder is a −90 B un-inlining that a later edit could take back, in which case the net would
fall to ≈ +6 B. Every alignment assumption the old code made was revisited deliberately (two `_Static_assert`s
replaced, `image_boot_assert`'s `& 3` replaced by a `% 3` stride check), `xt/2` is proved in code rather than
in prose, and the two silent-failure traps this layout introduces (the `xt` mask, the prelude's cell-wide
`IMMEDIATE`) are now both in the source as guardrails plus one new mutation-tested regression test.

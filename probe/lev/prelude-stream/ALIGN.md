# Is every `rd32` call site 4-byte aligned? (alignment audit for a single-load `rd32`)

**Question.** If `rd32` became one 32-bit load, `*(volatile u32 *)(mem + a)`, is every call
site 4-byte aligned? On rv32imc a misaligned load traps (this core has no misaligned-access
fixup), so this is a correctness question, not a style question.

**Verdict (short).** **No.** 16 of the 18 `jal <rd32>` sites are provably 4-aligned. Two are not:

| site | what it reads | status |
|---|---|---|
| `0x792` in `vm_enter` — `rd32(ip)`, the inline 32-bit literal fetch | token stream | **only 2-aligned; 8 real literals in the shipped dictionary land at `≡2 (mod 4)` → a single-load `rd32` traps** |
| `0x938` in `vm_enter` — `rd32(TOS)`, the `@` primitive | arbitrary Forth address | **unproven, cannot be proven at all: the address is a value the program computed** |

The literal site is not a theoretical risk: I walked the shipped dictionary in `ulp_main.elf`
and 8 of the 18 real 32-bit literal sites have their value at `mem + 0x…2`, including
`HERE` (value `4` at `mem+0x27e`), which the primitive set calls during boot. A single-load
`rd32` would trap on the first `HERE`.

---

## 0. Method / commands

```
riscv32-esp-elf-objdump -d --no-show-raw-insn \
  .../repl/build/esp-idf/main/ulp_main/ulp_main.elf > dis.txt     # this directory
grep -nE "(j|jal)\s+22c <rd32>" dis.txt   # 18 sites
grep -nE "(j|jal)\s+1e6 <rd16>" dis.txt   #  8 sites
readelf -sW .../ulp_main.elf | grep ' mem$'   # 000014f4 1500 OBJECT LOCAL DEFAULT 3 mem
objdump -s -j .data  .../ulp_main.elf         # mem[] contents (= the shipped dictionary)
```

`mem` is at **`0x14f4`, size 1500 B** (so `MEMSZ == 1500` in this image), the first object in
`.data`, which starts at `0x14f4` because `.rodata` ends there (`0x1398 + 0x15c`).
`0x14f4 & 3 == 0`, so **for this image the base is 4-aligned** — but see §5, nothing enforces it.

Current reader, from `uforth.c:74-81` (the shipped image matches: `rd16` is one `lhu`,
`rd32` is two `rd16` calls — see `dis.txt` 0x1e6 and 0x22c):

```c
#if defined(ALIGN_TRAP)
static u16 rd16(u32 a)           { if (a & 1u) pl_halt(0x50u); return *(volatile u16 *)(mem + a); }
#else
static u16 rd16(u32 a)           { return a + 1u < MEMSZ ? *(volatile u16 *)(mem + a) : 0u; }
#endif
static void wr16(u32 a, u16 v)   { wr8(a, v); wr8(a + 1, v >> 8); }
static u32 rd32(u32 a)           { return rd16(a) | (u32)rd16(a + 2) << 16; }
static void wr32(u32 a, u32 v)   { wr16(a, v); wr16(a + 2, v >> 16); }
```

Two consequences worth stating up front:

* **Today `rd32` already needs `a` even** (two halfword loads at `a` and `a+2`). The proposed
  change raises the requirement from `a & 1 == 0` to `a & 3 == 0`.
* **`rd16` is not the safe reader some of the comments imply** — it is a single `lhu` and it
  already traps on odd addresses, at two of its own call sites (§4).

---

## 1. Call-site table — `rd32` (18 sites, all found by `grep … <rd32>`)

`a0` is the argument. "provable" means the value of `a0` is fixed by the instructions before the
call, and `mem` is 4-aligned in this image.

| # | call addr | function | how `a0` was produced | `a0` | class | `a0 % 4` | verdict |
|---|---|---|---|---|---|---|---|
| 1 | `0x390` | `find` | `0x37c: li a0,8` | `V_LATEST` | (a) constant | 0 | **provable** |
| 2 | `0x414` | `cw` | `0x40e: li a0,4` | `V_HERE` | (a) constant | 0 | **provable** |
| 3 | `0x458` | `a4` | `0x454: li a0,4` | `V_HERE` | (a) constant | 0 | **provable** |
| 4 | `0x608` | `vm_enter` (`:`) | `0x602: li a0,4` | `V_HERE` | (a) constant | 0 | **provable** |
| 5 | `0x60e` | `vm_enter` (`:`) | `0x60c: li a0,8` | `V_LATEST` | (a) constant | 0 | **provable** |
| 6 | `0x740` | `vm_enter` (docon body) | `0x73a: addi a0,s5,5` / `0x73e: andi a0,a0,-4` (`s5` = `W`, field at VM+130) | `(W+5)&~3` | (a) constant-after-mask | 0 by construction | **provable** |
| 7 | `0x792` | `vm_enter` (**LIT**: `PUSH(rd32(ip)); ip+=4`) | `0x78e: lhu a0,132(s0)` (VM+132 = `IP`) | `ip` | (c) thread pointer | **0 or 2** (even, not 4) | **NOT aligned — proven broken in this image (§3)** |
| 8 | `0x938` | `vm_enter` (**`@`**: `TOS = rd32(TOS)`) | `0x934: lw a0,0(s5)`, `s5 = &DS[(sp-1)&15]` | `TOS` | (c) program value | unknown | **unproven — cannot be proven** |
| 9 | `0xc9c` | `vm_enter` (`C,`) | `0xc9a: li a0,4` | `V_HERE` | (a) constant | 0 | **provable** |
| 10 | `0xcc8` | `vm_enter` (`:`) | `0xcc6: li a0,4` | `V_HERE` | (a) constant | 0 | **provable** |
| 11 | `0xcd4` | `vm_enter` (`:`) | `0xcd2: li a0,8` | `V_LATEST` | (a) constant | 0 | **provable** |
| 12 | `0xd20` | `vm_enter` (`,`) | `0xd1e: li a0,4` | `V_HERE` | (a) constant | 0 | **provable** |
| 13 | `0xdc6` | `vm_enter` (`."` case) | `0xdc4: li a0,0` | `V_STATE` | (a) constant | 0 | **provable** |
| 14 | `0xe14` | `vm_enter` (`."` case) | `0xe12: li a0,4` | `V_HERE` | (a) constant | 0 | **provable** |
| 15 | `0x119e` | `main` (interpret) | `0x119c: li a0,0` | `V_STATE` | (a) constant | 0 | **provable** |
| 16 | `0x11c8` | `main` (`number()`) | `0x11c6: li a0,12` | `V_BASE` | (a) constant | 0 | **provable** |
| 17 | `0x123e` | `main` (interpret) | `0x123c: li a0,0` | `V_STATE` | (a) constant | 0 | **provable** |
| 18 | `0x1262` | `main` (error path) | `0x125c: li a0,0` | `V_STATE` | (a) constant | 0 | **provable** |

Offsets correspond to the `enum` at `uforth.c:56-59`: `V_STATE = 0, V_HERE = 4, V_LATEST = 8,
V_BASE = 12`. **There is no `rd32` of a dictionary link field anywhere** — see §3.

Class (a) = "constant offset from a 4-aligned base": 15 sites. Class (a-with-mask) = site 6, also
provable: `a4()` (`uforth.c:402`) rounds the constant body up to 4, and
`(W+5)&~3 == ((W+2)+3)&~3` is exactly that rounded body address, so the mask makes it 4-aligned
regardless of `W`.

Class (c) sites 7 and 8 are the whole problem.

---

## 2. Why site 6 is safe but site 7 is not (both are "read 4 bytes from the dictionary")

Site 6 masks: `andi a0,a0,-4` forces `a0 ≡ 0 (mod 4)` for **every** `W`, so it is aligned by
construction and stays aligned even if `W` is odd.

Site 7 does not: `ip` is a token-stream byte offset, and the loop advances it by 2
(`dis.txt 0x72e: addi s5,s5,2`, `0x79a: addi a5,a5,4` for the literal), `run()` sets `ip = 0`
and `vm_enter`'s colon-word entry sets `ip = W+2`. So `ip` is **even but only 2-aligned**, and
the literal's value sits at `ip = w + 2` where `w` is the address of the LIT token. Whether that
is `0 mod 4` or `2 mod 4` depends on how many 2-byte tokens precede it in that thread — i.e. on
the source of `boot.fs`, not on anything the engine controls.

---

## 3. Site 7 is not hypothetical: 8 real literals in the shipped dictionary are at `≡2 (mod 4)`

I extracted `mem[0..1500]` from `ulp_main.elf`'s `.data` (objdump -s) and walked the dictionary:
header chain from `V_LATEST = 0x3f2`, `n = mem[h+2] & 31`, `cf` at `x = (h+3+n+1) & ~1`,
`P_DOCOL = 0` (confirmed by `0x0cde: li a0,0; jal mkhdr` = `:`), `xt_lit = mem[16..17] = 0x48`
(`LIT`), `xt_exit = mem[18..19] = 0x40` (`EXIT`), `V_HERE = 1146`.

Walking each colon word from its body (`x+2`), accepting only tokens whose value is a real code
field address, to the terminating `EXIT`, gives **16 words that walk cleanly** and 18 literal
sites. 8 of them are misaligned for a 32-bit load:

| word | LIT token addr | value addr (`= ip`, `mem+ip`) | value | `ip % 4` | `lw` at |
|---|---|---|---|---|---|
| `HERE` | `0x27c` | `0x27e` | 4 | 2 | `0x1772` |
| `IMMEDIATE` | `0x2c0` | `0x2c2` | 2 | 2 | `0x17b6` |
| `IMMEDIATE` | `0x2cc` | `0x2ce` | 128 | 2 | `0x17c2` |
| `IF` | `0x2f4` | `0x2f6` | 2 | 2 | `0x17ea` |
| `UNTIL` | `0x354` | `0x356` | 96 | 2 | `0x184a` |
| `1-` | `0x394` | `0x396` | 1 | 2 | `0x188a` |
| `WHILE` | `0x3c8` | `0x3ca` | 2 | 2 | `0x18be` |
| `REPEAT` | `0x3e0` | `0x3e2` | 84 | 2 | `0x18d6` |

`0x14f4 + 0x27e = 0x1772`, and `0x1772 & 3 == 2` → misaligned load → trap. `HERE` is the
cheapest reproducer: it is `LIT 4 ;`, and the prelude/primitive set uses `HERE`.

The 10 aligned literal sites (`LATEST`, `STATE`, `1+`, `ELSE`×3, `IF`×2, `WHILE`×2) show the
split is ~50/50 and image-specific, so it cannot be "reasoned away" — it is decided by the token
count before each literal.

*Confidence:* the walk is mechanical and every token it accepted is a valid code-field address,
and the recovered word names are real (`HERE`, `IMMEDIATE`, `WHILE`, `REPEAT`, `UNTIL`, `1-`,
`ELSE`, `IF`, `STATE`, `LATEST`, `1+`), so I regard these 8 addresses as established, not
guessed. What I did **not** prove is that the case at `0x78e` is *exactly* the Forth `LIT`
primitive (its id would be visible in `p33_cases.inc`, which was out of scope); the pattern
(`PUSH(rd32(ip)); ip += 4`, entered with `ip` past the token just fetched) admits no other
reading than "read the inline 32-bit literal from the thread".

---

## 4. `rd16` call sites (for completeness — they already require 2-alignment)

8 `jal <rd16>` sites plus 3 inlined halfword loads at `mem`:

| addr | argument | parity | verdict |
|---|---|---|---|
| `0x236`, `0x23e` | `a`, `a+2` inside `rd32` | same parity as `a` | inherits the caller's `a` |
| `0x406` (`find`) | `h` = link field of the header being walked | even | **provable** (§3 below) |
| `0x6ce` | `W` (VM+130) | even | **provable** — `W` is an xt, and every xt comes from `(h+3+n+1)&~1` |
| `0x72c`, `0x7a2`, `0xeec` | `ip` | even | provable given token addresses stay even (`0x7a2` overwrites `ip` from a thread word — see §5) |
| `0x9be` | `TOS` (`TOS = rd16(TOS)`) | **unknown** | **unproven, same class as site 8** |
| inline `0x436` | `mem+16` (`V_XLIT`) | 0 | fine as `lhu`; would trap as `lw` |
| inline `0xcf4` | `mem+18` (`V_XEXIT`) | **2** | fine as `lhu` (even); **would trap if `rd16` ever became a 32-bit read** |
| inline `0xe08` | `mem+20` (`V_XSTR`) | 0 | fine |

So the codebase **already** has an unproven 2-byte alignment assumption at the two
arbitrary-address sites (`0x938` `rd32(TOS)` and `0x9be` `rd16(TOS)`): `@` of an odd address
traps today. The proposed change widens that hazard from "odd" to "odd or `2 mod 4`".

---

## 5. Part 3(b): are the dictionary link fields 4-aligned? No — and they are not read with `rd32`

The question imagined that some `rd32` sites are header-link reads. They are not: `find()` reads
the link with `rd16`, and the only `rd32` in the walk is the *constant* `V_LATEST`. The relevant
lines from `/home/user/research/esp32-rv32/probe/repl/src/uforth.c` (read-only):

**Write** — `mkhdr_pad` (`uforth.c:405-414`); the header link is written with `wr16`:

```c
static u16 mkhdr_pad(u8 cf, u8 imm)
{
    u8 n = rd8(PAD), i; u32 h = rd32(V_HERE), x;
    wr16(h, rd32(V_LATEST)); wr8(h + 2, n | (imm << 7));      /* link = wrapper of 2 bytes */
    for (i = 0; i < n; i++) wr8(h + 3 + i, rd8(PAD + 1 + i));
    x = (h + 3 + n + 1) & ~1u;                                /* cf: pad to EVEN, not to 4 */
    wr16(x, cf);
    wr32(V_LATEST, h); wr32(V_HERE, x + 2);
    return x;
}
```

**Read** — `find` (`uforth.c:368-383`):

```c
    for (h = rd32(V_LATEST); h; h = rd16(h)) {    /* link walk: rd16, 2 bytes */
        f = rd8(h + 2);
        ...
            *imm = f >> 7; return (h + 3 + n + 1) & ~1u; }   /* xt: also only even */
```

Layout comment, same file (`uforth.c:343`): `/* dictionary entry: [link:2][flags|len:1][name][pad to even][cf:2][body] */`

Reasoning:

* The pad is `& ~1u`, i.e. **the header layout only promises evenness**, by design: the entry is
  `2 + 1 + n + pad`, so the next header starts at `x + 2` and the link of *that* header is at an
  even address, but its `mod 4` depends on the parity of `n`.
* Empirically, in the shipped dictionary (81 headers walked to `h == 0`): **81/81 header
  addresses are even, only 37/81 are 4-aligned; 81/81 cf addresses are even, only 47/81 are
  4-aligned.** So a 4-byte read of a link field would trap on 44 of 81 entries — it would be
  wrong *today*, before any paging/threading change.
* Therefore: the link path is safe from the proposed `rd32` change **only because it does not use
  `rd32`**. If anyone ever "optimises" `h = rd16(h)` into `rd32`, the pad-to-even contract has to
  become pad-to-4 *and* `V_HERE`/`V_LATEST` (and the baked `image.h`) re-generated, or the walk
  traps.
* Constant bodies are the opposite case: `a4()` (`uforth.c:402`,
  `wr32(V_HERE, (rd32(V_HERE) + 3) & ~3u)`) forcibly 4-aligns them, which is exactly why site 6
  (`(W+5)&~3`) is sound.

---

## 6. Part 4: what is proven, what is only probable, what is unproven

**Provably 4-aligned under a single-load `rd32`** (16/18 sites):

* 1, 2, 3, 4, 5, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18 — constant `a0 ∈ {0, 4, 8, 12}` on the
  `enum` at `uforth.c:56-59`, all `≡ 0 (mod 4)`; base `mem = 0x14f4 ≡ 0 (mod 4)` in this image.
* 6 (`0x740`) — `a0 = (W+5)&~3`, 4-aligned by the mask itself.

**Provably misaligned in practice (1/18):**

* 7 (`0x792`, the inline literal fetch). `ip` is only 2-aligned by construction, and 8 concrete
  literals in `ulp_main.elf` (table in §3) sit at `≡ 2 (mod 4)`, e.g. `HERE` → `lw` at `0x1772`.

**Unproven, and not provable from the source (1/18):**

* 8 (`0x938`, `@` = `rd32(TOS)`). The address is whatever the Forth program pushed. Nothing in
  the engine constrains it, and `uforth.c` has no alignment discipline for values on the data
  stack. Under the current `rd32` this is safe unless the address is *odd*; under a single-load
  `rd32` half of all even addresses become fatal. Provisional mitigation would have to be a
  policy ("cells are 4-aligned by convention") that no code enforces — I did not establish one.

**Also unproven / not covered by the constant-offset proof:**

* `mem`'s own 4-alignment. `mem` is `static u8 mem[MEMSZ]` (byte array; `uforth.c:60` / the
  `-d`-generated `image.h` is documented at `uforth.c:778` as `static u8 mem[MEMSZ] = {…}`), so
  its alignment requirement in C is **1**. It is 4-aligned here only because `.data` starts at
  `0x14f4` and `mem` is the first object in it. If `.rodata`/`.data` layout shifts by 1-3 bytes
  (a string edit, a new constant), **every** site in the table becomes misaligned at once. The
  constant-offset sites are therefore "provably aligned *for this image*", not "structurally".
* Branch targets: `0x7a2: lhu a0,132(s0) … sh a0,132(s0)` assigns `ip` from a word in the thread.
  Its evenness is inherited from thread layout, not enforced.
* `ALIGN_TRAP` today (`uforth.c:75`) only checks `a & 1u` inside `rd16`. It cannot see the new
  failure mode, and because `rd32` is currently spelled as two `rd16` calls, an `ALIGN_TRAP`
  build of the *current* code would not even reach a 4-byte requirement.

---

## 7. The single runtime check that settles it

Build with a single-load `rd32` plus a 4-byte trap, and run the prelude/tests; the first trap
identifies the offending site by its `ra`:

```c
#if defined(ALIGN_TRAP)
/* GUARDRAIL: a 32-bit load needs a & 3 == 0, not a & 1 == 0 — copying rd16's check here leaves the
 * 2-mod-4 literals (HERE, IMMEDIATE, IF, …) silently trapping in hardware with no diagnostic. */
static u32 rd32(u32 a) { if (a & 3u) pl_halt(0x51u); return *(volatile u32 *)(mem + a); }
#else
/* GUARDRAIL: the bound check must grow from "a+1 < MEMSZ" to "a+3 < MEMSZ"; keeping the 16-bit bound
 * makes rd32(1498) read two bytes past mem[] (it is safe today only because the second rd16 returns 0). */
static u32 rd32(u32 a) { return a + 3u < MEMSZ ? *(volatile u32 *)(mem + a)
                                               : (u32)rd16(a) | (u32)rd16(a + 2) << 16; }
#endif
```

Notes on that check:

* `pl_halt(0x51)` (rather than reusing `0x50`) keeps the two failures distinguishable: `0x50` =
  odd halfword/misaligned `rd16`, `0x51` = 4-byte `rd32`.
* Expected result on the current prelude: `0x51` fires on the first `HERE` (site 7), because
  `HERE` is `LIT 4 ;` with its value at `mem+0x27e`.
* The cheapest *static* check that needs no build: assert `((uintptr_t)mem & 3u) == 0` at boot
  (the constant-offset sites all depend on it), and add `__attribute__((aligned(4)))` to `mem`
  in both the engine and the generated `image.h` if the invariant is to be kept deliberately.
* To settle site 8 (`rd32(TOS)`) there is no static check at all — it needs the `ALIGN_TRAP`
  build plus whatever the test programs actually compute (that is the only evidence available).

---

## 8. Residual risks not settled by this audit

1. Site 8 (and its `rd16` twin at `0x9be`) depend on program-supplied addresses; no amount of
   image analysis settles them.
2. `mem`'s 4-alignment is incidental (§6) and would silently invalidate all 16 "provable" sites
   if `.data` is re-laid-out.
3. The literal-site evidence in §3 comes from the dictionary baked into `ulp_main.elf`; a prelude
   edit shifts every literal by 2 bytes and flips half of them. The audit is image-specific and
   should be re-run after any `boot.fs` change.
4. Out-of-range behaviour changes even where alignment holds: `rd16(1498)` is in range
   (`1499 < 1500`), so a single-load `rd32(1498)` would read 2 bytes beyond `mem[]` unless the
   bound is widened (§7).
5. I did not inspect `p33_prims.inc` / `p33_cases.inc` / `image.h` (out of scope), so primitive
   *names* for cases are inferred from the `mkhdr(0/1/2)` = `:`/`DOCOL`/`DO CONST` call sites and
   from the pattern of the case bodies, not read from the table.

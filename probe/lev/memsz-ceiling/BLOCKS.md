# BLOCKS.md — what the block layer costs, in arithmetic

Scope: arithmetic only, from numbers already on the books. No build, no new measurement.
Every figure is tagged **[Q]** quoted from a named file, **[G]** given as current measured state in the task
brief, or **[D]** derived in a shown line below. `ESTIMATE` marks the three places where a number is neither.

## Inputs

| Symbol | Value | Source |
|---|---|---|
| `MEMSZ` | **1 500** | [G]; E-055 ("`MEMSZ` 1 500") |
| `V_HERE` at boot | **1 146** | [G]; E-055 ("`V_HERE` 1 146"); 13-levers (R4 row: "dictionary at boot … **1 146** (+10 for the `SPAWN` header)") |
| pool / limit | **7 842 / 7 856** (14 spare) | [G]; E-055 ("pool **7 842 / 7 856** (14 spare)") |
| app space today | **354 B** | [Q] E-055; check: 1 500 − 1 146 = **354** [D] |
| `.text` with R4 | **5 014** | [Q] 13-levers R4 row (".text 4 518 → **5 014** (+496)"); F-73 |
| `.bss` with rings 64/128 | **960** | [Q] 13-levers, "two corrections": "`.bss` 960" |
| `.data` | `MEMSZ + 16` | [G] current build. (E-054 supports `MEMSZ + 8` at the pre-R4 build: `MEMSZ` 1 280 → `.data` 1 288; the extra +8 since R4 is not itemised in the named files) |
| block layer, Forth | **456 B** | [Q] F-07; E-042 ("**456 B** measured by watermark (888 → 1 344)"); uforth.c `BLKRES` comment ("the layer fits in (P33 measured 456 B)") |
| `BLKSZ` | **512** | [Q] uforth.c `#define BLKSZ 512` |
| `BLKRES` | **512** | [Q] uforth.c `#define BLKRES 512` |
| `BLKADR` | `(MEMSZ - BLKSZ)` | [Q] uforth.c `#define BLKADR (MEMSZ - BLKSZ)` |
| `DICT` | **56** | [Q] uforth.c `enum { … PAD = 24, DICT = 56 }` |
| `blk_boot_ok()` | `BLKADR >= DICT + BLKRES` | [Q] uforth.c |
| `blk_place_ok()` | `rd32(V_HERE) <= BLKADR` | [Q] uforth.c |
| pool limit | **7 856** | [Q] F-01; E-054 |

---

## 1. What `MEMSZ` the block layer's predicates require

The layer has **two** predicates, and only the second one binds.

**(a) `blk_boot_ok()` — the sizing question asked at boot:**

```
BLKADR >= DICT + BLKRES
MEMSZ - BLKSZ >= 56 + 512
MEMSZ - 512   >= 568
MEMSZ         >= 568 + 512 = 1080            [D]
```

So the boot assert passes from **`MEMSZ` 1 080** upward. It already passes at today's 1 500 — `BLKADR` = 1 500 − 512
= **988** ≥ 568 [D]. `blk_boot_ok()` is therefore *not* the binding constraint in this image.

**(b) `blk_place_ok()` — the question that actually decides it**: the 456 B of block words are compiled *into* the
dictionary, so `V_HERE` rises before the first `BLOCK`:

```
V_HERE_after_blocks = 1 146 + 456 = 1602                     [D]
blk_place_ok: 1602 <= MEMSZ - 512
              MEMSZ >= 1602 + 512 = 2114                     [D]
```

**`MEMSZ` 2 114 is the smallest value at which blocks can boot without the buffer overlapping the dictionary.**
Check against the failure uforth.c records: at `MEMSZ` 2 304, `BLKADR` = 1 792 and P33's dictionary reached
HERE = 1 842 → overlap, silent corruption, `." ?` parse error [Q] uforth.c guardrail. Our HERE after blocks is
1 602, i.e. 1 792 − 1 602 = **190 B** clear at 2 304 [D] — under 200 B, which is why 2 304 is not enough either.

At today's `MEMSZ` 1 500: `BLKADR` = 988, `V_HERE` would be 1 602 → **614 B of overlap** [D]. Blocks cannot boot
today at any app-space setting; the dictionary itself would sit on top of the buffer.

## 2. Usable application space with blocks loaded

```
app = (MEMSZ - 512) - V_HERE_after_blocks
    = (MEMSZ - 512) - 1602
    = MEMSZ - 2114                                           [D]
```

| `MEMSZ` | `BLKADR` = MEMSZ−512 | `V_HERE` | app space = MEMSZ−2114 | note |
|---|---|---|---|---|
| 1 500 (today) | 988 | 1 602 | **−614** | dictionary overlaps buffer; `blk_place_ok` false |
| 2 114 | 1 602 | 1 602 | **0** | blocks boot, zero room for a program |
| 2 314 | 1 802 | 1 602 | **200** | smallest value meeting the ≥200 B requirement |
| 2 468 | 1 956 | 1 602 | **354** | holds today's 354 B app space unchanged |
| 2 604 (the figure in the brief) | 2 092 | 1 602 | **490** | 290 B more app space than the minimum |

The 200 B line is what the brief asks for, so **the arithmetic requires `MEMSZ` 2 314**, not 2 604:
`1 146 + 456 + 200 + 512 = 2314` [D]. 2 604 is 2 604 − 2 314 = **290 B above** the minimum [D] and is a valid
choice only if the extra 490 B of app space is wanted and paid for out of the pool (it is not — see §4).

## 3. Pool as a function of `MEMSZ`

`pool` counts `.text` + `.rodata` + `.data` + `.bss`, and `.data` = `MEMSZ + 16` [G], so `pool` is linear in `MEMSZ`
with slope exactly 1 — the same 1:1 the +120 sweep measured ([Q] F-68, E-054: "+120 `MEMSZ` → +120 `.data` exactly").

Derivation from the measured pair:

```
pool(MEMSZ) = MEMSZ + K
7 842       = 1 500 + K                     [Q] measured at MEMSZ 1 500
K           = 7 842 - 1 500 = 6342          [D]

check, MEMSZ 1 500:  1 500 + 6 342 = 7 842  ✓  matches the measured 7 842
```

Independent cross-check, using the spare instead of the pool:

```
ceiling MEMSZ = 7 856 - 6 342 = 1 514       [D]
measured spare at 1 500 = 1 514 - 1 500 = 14 ✓ matches the measured 14 spare
```

What `K` is made of (with `.data` = `MEMSZ + 16`):

```
K = .text + .rodata + .bss + 16
6 342 = 5 014   + .rodata + 960 + 16        [Q] .text 5 014, .bss 960
6 342 = 5 990   + .rodata
.rodata = 352                                [D]  ← residual, not independently quoted
```

(`.rodata` 352 is consistent with E-054's 316 plus ~36 B of `SPAWN`/error strings, which is an **ESTIMATE**: the
named files give 316 for the pre-R4 build and do not itemise the R4 strings.)

The point that survives regardless of the residual: **`pool = MEMSZ + 6342` is exact for this image**, and
`7 856 − 6 342 = 1 514` is the largest `MEMSZ` the pool pays for today.

## 4. Bytes that must be freed at `MEMSZ` 2 604 (and at the minimum, 2 314)

```
pool(2 604) = 2 604 + 6 342 = 8 946                                   [D]
over        = 8 946 - 7 856 = 1090 B must be freed                    [D]

pool(2 314) = 2 314 + 6 342 = 8 656                                   [D]
over        = 8 656 - 7 856 =  800 B must be freed                    [D]
```

Same answer the app-space route gives, which is why it is worth stating twice: blocks cost 968 B *of pool*
(456 + 512, both inside `mem[]`, and every `MEMSZ` byte costs one pool byte — F-68), today's free pool is 14 B, so

```
keep today's 354 B app:  968 - 14                    =  954 B short  (MEMSZ 2 468)  [D]
keep 200 B app:          968 - 14 - (354 - 200)      =  800 B short  (MEMSZ 2 314)  [D]
brief's 490 B app:       968 - 14 + (490 - 354)      = 1090 B short  (MEMSZ 2 604)  [D]
```

(the third line is the only place the ask grows past 968: at 2 604 the app space is 136 B *larger* than today, so
136 B of the 1 090 is a feature request, not a block cost)

**Measured levers, with their measured sizes** ([Q] 13-levers, F-68…F-71):

| Lever | Measured yield | Still available today? |
|---|---|---|
| `MEMSZ` slack (the free lunch) | 592 B of idle pool existed at the pre-R4 build; ceiling then 1 872 | **No — spent.** Today's ceiling is 1 514 and 1 500 is in use (14 left) |
| rings cmd 128→64, out 256→128, tib 128→96 | **−224 B** `.bss` (1 152 → 928) | **No — already applied** in this build (`.bss` 960 is the ring-shrunk figure) |
| `NTSK` 3→1 (two task records) | **−280 B** `.bss` **and −78 B** `.text` = **−358 B** | Yes mechanically — but it removes two of the three task slots R4 just demonstrated (F-73: `SPAWN TA SPAWN TB SPAWN TA` → 131242 uses three) |
| full `tsk` removal | **−420 B** upper bound (symbol size), plus R4's own **−496 B** `.text` = **−916 B** | Only by deleting R4 itself |
| C-stack reserve 320 → smaller | **−320 B** | **Forbidden**: 13-levers, "P21 measured 244 B worst case … **Do not spend it**"; F-09 |

Sum of what is reachable **while keeping R4**: **0 B** (rings and the `MEMSZ` slack are already inside the 7 842).
With `NTSK` 1: **358 B**. With R4 deleted outright plus the forbidden C stack: 420 + 496 + 320 = **1 236 B**.

## 5. Verdict

**Blocks are not reachable today.** The numbers:

```
blocks cost, in pool:        456 (Forth words) + 512 (buffer) = 968 B      [D]
free pool today:             14 B                                          [Q]
shortfall at MEMSZ 2 314 (the arithmetic minimum, 200 B app):   800 B      [D]
shortfall at MEMSZ 2 604 (the brief's figure, 490 B app):      1090 B      [D]
shortfall to hold today's 354 B app space (MEMSZ 2 468):        954 B      [D]

levers available without touching R4:                             0 B      [D]
levers available with NTSK 1 (kills 2 of 3 task slots):         358 B      [Q]
forbidden C-stack reserve:                                      320 B      [Q]
```

- At `MEMSZ` 1 500 the layer cannot even boot: `blk_place_ok` fails by 1 602 − 988 = **614 B** [D].
- At the minimum `MEMSZ` 2 314 the pool is **800 B over**; the only levers that exist sum to 358 B without
  deleting R4, and the remaining 320 B is a safety margin the project has ruled out spending.
- At `MEMSZ` 2 604 the pool is **1 090 B over**; even spending the forbidden C stack *and* `NTSK` 1 (320 + 358 =
  678 B) leaves 1 090 − 678 = **412 B short** [D].
- 2 604 also exceeds the historical non-paged link maximum of **2 196 B** ([Q] F-05, E-040: "2 196 links, 2 197
  fails") by 2 604 − 2 196 = **408 B** [D]. That 2 196 was a *pool* ceiling measured when the engine was smaller
  (4 096 B class, E-042), not an address-space limit; today's equivalent ceiling is 1 514, so the honest statement
  is that the ceiling has *fallen*, not that 2 604 is somehow architecturally available.

So: **968 B plus a larger `MEMSZ` is a 954–1 090 B ask against 14 B of actual headroom.** The block layer becomes
reachable only after something *outside* this table gives back ≈1 KB — and the measured levers on the books
(rings, `MEMSZ` slack) are already spent.

### Two things the 968 B does not include (flagged, not counted)

1. **The layer's own C.** `BLKXFER`, `blk_sum`, `blk_out`, the boot/place asserts (uforth.c) are real `.text`.
   E-040 measured the block layer's engine cost at **352 B total** (348 engine + 4 `blk_out`); E-042 puts the
   "layer's own C" at ≈366 B. Whichever figure is right, it is **not** in the 6 342 constant, which was measured
   from a build without `P33_BLOCK`. If it must be added, the shortfalls become 800 + 352 = **1 152 B** (at 2 314)
   and 1 090 + 352 = **1 442 B** (at 2 604) [D]. *Caveat, stated rather than assumed:* if any of that C is already
   in today's 5 014 B `.text`, adding 352 double-counts it — the F-08/F-56 class of error. Unmeasured here.
2. **`BLKRES` 512 is a sizing reserve, not the vocabulary.** 456 B is the measured watermark of the Forth layer;
   `BLKRES` deliberately reserves 512 so the boot predicate has slack. Blocks therefore cost *at least* 968 B and
   the predicate is willing to spend 512 + 512 + 56 = **1 080 B** of address space before it even looks at `V_HERE`.

### What would change the verdict (arithmetic, not a proposal)

Freeing bytes is only useful if the freed bytes are *pool* bytes, and the ask scales 1:1 with `MEMSZ`:

```
free 954 B  →  MEMSZ 2 468  →  blocks + today's 354 B app space
free 800 B  →  MEMSZ 2 314  →  blocks + the required 200 B app space
free 1 090 B → MEMSZ 2 604 →  blocks + 490 B app space
```

No combination of the measured levers that keeps R4 reaches 800 B, so the honest verdict is **not today** — and the
gap is ~1 KB, not the "456 B of words" that F-07's summary alone suggests.

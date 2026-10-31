# P02 — Token width: 16-bit vs 32-bit xt

| | |
| --- | --- |
| Probe | P02 (`docs/probes/P02-token-width.md`) |
| Runs on | host only (gcc), no board, no `idf.py` |
| Status | **COMPLETE** |
| Wall clock | started 19:30 UTC, finished ~19:40 UTC (cap 30 min) |
| Result dir | `probe/results/P02-token-width/` |

Two builds of the same source, both passing the full host suite:

* **A — 16-bit tokens** (`a16/`): `probe/uforth/` copied verbatim, unmodified.
* **B — 32-bit xts** (`b32/`): the same files with `cw`/`clit`/`find`/branch operands and `ip`
  widened to 4 bytes. Only `uforth.c` and `boot_min.fs` differ; `host_test.c` is byte-identical
  in both directories. Full diff: `a16-to-b32.diff`.

---

## 1. Answers

**Q: What does 16 → 32-bit tokens cost in dictionary density?**

**1.49× the dictionary**, and **+14.1 bytes per word** on a mixed corpus of 46 definitions
(25.09 → 39.22 B/word). For boot-layer-style words (small aliases, the mix §7's "21" was
measured on) it is **21.00 → 32.44 B/word**, i.e. **+11.4** — the proposal's "~30" was
optimistic by 8 %, and for real-sized definitions it is optimistic by 30 %.

The cost splits into **+13.2 B/word of body** (tokens and their operands literally double: a
call goes 2 → 4 B, a literal 4 → 8 B, a branch 4 → 8 B, an inline string 2 → 4 B per cell) and
**+5.0 B/word of header** (the code field is a token, 2 → 4 B, and the code field must be
padded to 4 so that `P_COMMA`'s alignment cannot inject pad bytes into a body; that padding
costs a further ~3 B/word on this corpus' name lengths).

Body composition at 32-bit (46 words, 1420 body bytes): literals **376 B (26.5 %, 47 LITs)**,
branch operands 112 B (7.9 %, 14), inline strings 44 B (3.1 %, 4 strings), plain calls the
remaining 888 B (62.5 %). Headers are 1108 B — **44 % of the whole 2528-byte dictionary is
headers**, not code.

**Q: How often does a real definition straddle a 512 B page boundary?**

At 32-bit: **6.5 %–8.7 %** (3–4 of 46 definitions), depending on whether the page origin is
absolute or at `DICT` and whether the dictionary is taken as compiled or repacked at 4-byte
alignment. At 16-bit: 2.2 %–4.3 %. At 256 B pages the 32-bit rate is **10.9 %–15.2 %**.

Both observed rates sit where the arithmetic predicts: a mean-sized definition straddles with
probability ≈ mean/page = 39.22/512 = 7.7 % at 32-bit and 25.09/512 = 4.9 % at 16-bit. So the
straddle rate is not a property of the compiler, it is a property of **mean definition size
divided by page size**, and 32-bit tokens move a corpus of this shape from "under 5 %" to
"over 5 %".

**No definition in the corpus comes anywhere near 512 B.** Largest body: 52 B (A) / 88 B (B);
largest whole definition: 60 B (A) / 96 B (B). At 32-bit, 512 B is ≈ 64 tokens, so
`ERR_WORD_TOO_BIG` would need a hand-written 64-token word to fire; the refusal rule is
therefore almost never the user-visible cost. The straddle check is what the compiler (and the
user's page discipline) actually pays for.

## 2. Evidence

### Builds and gate (both builds, `host_test.c` unchanged)

```
cd probe/results/P02-token-width/a16
gcc -DHOST -std=c99 -Wall -Wextra -o uforth_test host_test.c && timeout 60 ./uforth_test
  -> "53 passed, 0 failed"  (baseline; boot dictionary 1352 of 2560 bytes)

cd probe/results/P02-token-width/b32
gcc -DHOST -std=c99 -Wall -Wextra -o uforth_test host_test.c && timeout 60 ./uforth_test
  -> "53 passed, 0 failed"  (boot dictionary 1956 of 2560 bytes; "fits in 2 KB" still passes)
```

Logs: `a16/test16.txt`, `b32/test32.txt`.

### Measurement harness (identical source for both builds)

`measure.c` compiles `boot_min.fs` + `corpus_extra.fs` exactly like `host_test.c` does
(`load()` → `interpret()`), records `HERE` before `:` and after `;` for every definition,
resolves each xt through `find()`, and compares the packed layout against the real one. It
also decodes every body token by token and **verifies the decode lands exactly on the
definition's end** (`DECODE-MISMATCH` would be printed; none were).

```
cd a16
gcc -DHOST -DMEMSZ=8192 -std=c99 -Wall -Wextra -o measure measure.c
timeout 60 ./measure boot_min.fs corpus_extra.fs > meas16.txt

cd ../b32
gcc -DHOST -DTOKW=4 -DMEMSZ=8192 -std=c99 -Wall -Wextra -o measure measure.c
timeout 60 ./measure boot_min.fs corpus_extra.fs > meas32.txt
```

`-DMEMSZ=8192` is applied to **both** builds and changes nothing but `P()`'s bounds check: the
32-bit dictionary needs 2592 B, over the 2560 default, and `P()` maps every address past
`MEMSZ` onto one shared junk byte, so without it the last definitions read back as zeros (this
was observed, then fixed — see follow-ups). `-DTOKW=4` only tells the decoder the cell width of
the build under test; the numbers themselves come from the interpreter.

Corpus: `boot_min.fs` (36 definitions) + `corpus_extra.fs` (10 definitions, incl. the ~18-token
`MIX` and the three-string `BANNER`), 46 definitions total.

### Measured table

`bytes/word` = whole definition (header + code field + body) unless marked "body";
primitive headers are excluded and reported separately.

| Metric | A: 16-bit tokens | B: 32-bit xts | B/A |
| --- | --- | --- | --- |
| Definitions compiled (words) | 46 | 46 | 1.00 |
| Primitive headers | 540 B | 724 B | 1.34 |
| Dictionary bytes, definitions only | 1154 | 1804 | 1.56 |
| **Dictionary bytes, total (prims+defs)** | **1694** | **2528** | **1.49** |
| **bytes/word mean** | **25.09** | **39.22** | **1.56** |
| bytes/word max | 60 | 96 | 1.60 |
| body bytes/word mean | 17.70 | 30.87 | 1.74 |
| body bytes/word max | 52 | 88 | 1.69 |
| mean, boot-layer words only (36) | 21.00 | 32.44 | 1.54 |
| mean, "real code" words only (10) | 39.80 | 63.60 | 1.60 |
| **definitions with body > 512 B** | **0 / 46** | **0 / 46** | — |
| definitions with total > 512 B | 0 / 46 | 0 / 46 | — |
| **straddles @ 512 B** (actual layout, page origin 0) | **2 (4.3 %)** | **4 (8.7 %)** | — |
| straddles @ 512 B (actual layout, page origin `DICT`) | 2 (4.3 %) | 3 (6.5 %) | — |
| straddles @ 512 B (repacked, 4-byte aligned, origin 0) | 2 (4.3 %) | 3 (6.5 %) | — |
| straddles @ 512 B (repacked, 4-byte aligned, origin `DICT`) | 1 (2.2 %) | 3 (6.5 %) | — |
| **straddles @ 256 B** (actual layout, origin 0) | **4 (8.7 %)** | **6 (13.0 %)** | — |
| straddles @ 256 B (actual layout, origin `DICT`) | 4 (8.7 %) | 7 (15.2 %) | — |
| straddles @ 256 B (repacked, 4-byte aligned, origin 0) | 4 (8.7 %) | 7 (15.2 %) | — |
| straddles @ 256 B (repacked, 4-byte aligned, origin `DICT`) | 3 (6.5 %) | 5 (10.9 %) | — |
| host suite | 53 passed, 0 failed | 53 passed, 0 failed | — |

Per-group straddle counts (32-bit, 512 B, repacked@`DICT`): boot 2/36 (5.6 %), corpus 1/10
(10 %). The larger the words, the worse the rate — the corpus with real code straddles 1 in 10
at 512 B and 2 in 10 at 256 B.

Body census (both builds decode exactly to `HERE`):

| | A: 16-bit | B: 32-bit |
| --- | --- | --- |
| body bytes | 814 | 1420 |
| literals (count / bytes / share) | 47 / 188 / 23.1 % | 47 / 376 / 26.5 % |
| branch operands (count / bytes) | 14 / 56 | 14 / 112 |
| inline strings (count / bytes) | 4 / 32 | 4 / 44 |

### What the width change was, exactly (`a16-to-b32.diff`)

* memory map: `V_XLIT/V_XEXIT/V_XSTR` 2 → 4 bytes each, `PAD` 24 → 28, `DICT` 56 → 64;
* `cw()` stores 4 bytes and advances `HERE` by 4; `clit()` emits one 4-byte operand instead of
  two 2-byte halves;
* `find()` / `mkhdr_pad()` return `u32` and place the code field at `(h+3+n+3) & ~3` (was
  `& ~1`), and `HERE` after the code field is `x+4` (was `x+2`);
* `run()`: `ip` and `w` are `u32`, every fetch is `rd32`/`+4`, `BRANCH`/`0BRANCH`/`LOOP`/`+LOOP`
  operands are `rd32`, `(DO)`/`(LOOP)` bodies shift by 4, `P_EXEC` keeps a full 32-bit xt, the
  inline-string advance is `(ip+n+4) & ~3`;
* `boot_min.fs`: the twelve compile-time operand sites move from `W,`/`W!`/`HERE 2 -` to
  `,`/`!`/`HERE 4 -`.
* Nothing else: header layout, primitives, interpreter structure, error handling and stack
  behaviour are untouched, and `host_test.c` is not.

## 3. Verdict

**PASS — adopt 32-bit xts, with two document changes and one compiler-behaviour change.**

* No behavioural regression: 53/53 in both builds, with `host_test.c` unchanged. The width
  change is not a bug.
* Density: 1.49× the dictionary, mean **39.2 B/word** on a mixed corpus (32.4 B/word on
  boot-layer words alone, max 96 B). That is **above the 35 B/word failure trigger in the
  brief**, so §7's "~30 bytes per word" is confirmed optimistic and must be replaced with the
  measured numbers rather than the estimate. It is not a reason to abandon the change: the
  budget cost is ~850 B for this corpus, not a factor of two.
* Page rule: the 512 B straddle rate at 32-bit is **6.5–8.7 %, over the 5 % trigger**, so
  §4.2 rule 1 changes from "refuse a straddling definition" to **"a definition may span at most
  two pages; pin both frames"**. At 256 B the rate is **10.9–15.2 %, over the 10 % trigger**, so
  **256 B pages are dead — keep 512 B**. (Both triggers fire; the brief asks for the numbers,
  and the orchestrator makes the page-size call.)
* The refusal path (`ERR_WORD_TOO_BIG`) is practically unreachable at 512 B / 32-bit (≈64
  tokens, against a largest measured body of 88 B = 22 cells), so the extra
  compiler work is the page-pinning, not the refusal.
* Unlisted cost found while measuring: **`MEMSZ` 2560 is too small for the 32-bit build** — the
  boot layer alone is 1956 B (was 1352) and boot+corpus needs 2592 B, so the default silently
  ran off the end of `mem[]`. Any 32-bit-xt build must raise `MEMSZ` (the resident-budget table
  in §4.3 assumes the 16-bit figure).

## 4. Doc deltas

`docs/01-proposal.md` §7, bullet 4 — replace (verbatim target):

```
* **References are 32-bit** virtual addresses (xts), because 16-bit tokens cannot index more than
  64 KB and R5 requires a larger space. Cost: ~30 bytes per word instead of the measured 21.
```

with (verbatim replacement, numbers from P02):

```
* **References are 32-bit** virtual addresses (xts), because 16-bit tokens cannot index more than
  64 KB and R5 requires a larger space. Cost, measured (P02: 46 definitions of boot layer plus
  sample code): 21.0 → 32.4 bytes per word for boot-layer words, 25.1 → 39.2 for a mixed corpus —
  1.49× the whole dictionary, primitive headers included. Max 96 bytes for a 22-cell word;
  literals are 26.5 % of body bytes and headers 44 % of the dictionary.
```

`docs/01-proposal.md` §4.2 rule 1 — replace (verbatim target):

```
1. **One definition per page.** The compiler refuses a definition that would straddle a page
   (`ERR_WORD_TOO_BIG`). This converts the worst class of faults into a compile-time error.
```

with (verbatim replacement):

```
1. **A definition spans at most two pages.** The compiler pins every page the definition being
   compiled touches (two frames at most) and refuses only a definition larger than a page
   (`ERR_WORD_TOO_BIG`). With 32-bit tokens 6.5–8.7 % of definitions straddle a 512 B boundary
   (≈ mean definition size ÷ page size), so "refuse a straddle" would reject one definition in
   fourteen; at 256 B pages the rate is 10.9–15.2 %, which is why the page stays 512 B.
```

Optional third delta (not in the brief's list, both are measurements, not decisions):
§4.3 resident budget — the "engine" and "resident dictionary" lines assume 16-bit tokens; the
primitive header table alone grows 540 → 724 B and the boot layer 1352 → 1956 B.

## 5. Follow-ups

1. **`MEMSZ` must rise for 32-bit xts.** Boot layer 1956 B, boot+corpus 2592 B; the default
   2560 overflows without any error (`P()` aliases everything past `MEMSZ` to one junk byte).
   Decide the new default (≥ 4 KB) before the two-page compiler work, or the first 32-bit
   image will silently corrupt itself. Add a host test that asserts `HERE <= MEMSZ`.
2. **The header is the dominant per-word cost, not the literals.** 24.1 B/word of header at
   32-bit (vs 19.1 at 16-bit) against 30.9 B/word of body. A 2-byte "small literal" encoding
   would save 2 B per literal → 47 × 2 = 94 B = **2.0 B/word**, taking the mean from 39.2 to
   ≈ 37.2 — real but not enough on its own to get under 35. Padding the code field to 4 (which
   the `P_COMMA` alignment forces) costs ~3 B/word; a narrower/structured header is the bigger
   lever and is not covered by this probe.
3. **The header link is still 2 bytes.** `find()` walks `rd16(h)`; a dictionary larger than
   64 KB — the whole reason for 32-bit xts — cannot be walked. Widening it costs +2 B/word
   (mean 39.2 → 41.2) and must land before R5's > 64 KB data space is used, together with a
   check that the flags byte's 5-bit name length (31 chars) is still wanted.
4. **The boot layer is not width-portable.** Twelve sites in `boot_min.fs` had to change
   (`W,`/`W!`/`HERE 2 -` → `,`/`!`/`HERE 4 -`). Whatever prelude ships should express "emit one
   compiled cell" once — e.g. make `,` the only comma word used for operands and let its width
   follow the token width — otherwise every prelude rewrite carries this class of silent
   2-byte-hole bug.
5. **Two-page rule needs a test before it ships:** define a word deliberately at
   `page_end - size/2` in both widths and assert (a) it compiles, (b) both frames are pinned,
   (c) a definition that genuinely exceeds a page still raises `ERR_WORD_TOO_BIG`.
6. **Straddle rate is a corpus property.** The measured rate tracks mean_size/page, so it will
   rise with the real prelude (whose words will be larger than `boot_min.fs`'s aliases). Before
   freezing §4.2, re-run this harness on the actual prelude once it exists; the single-line
   command is in §2 above.

# One-byte ULP message codes — design, measurement, risks

**Verdict: the scheme works and it is worth 144 B, not ~60 B.** The ULP no longer contains any message
text. `.rodata` fell from 372 B to 268 B, and the 268 B that remain are *entirely* the 67-entry dispatch
jump table (code addresses — not movable to the host). `.text` fell another 40 B because the
`while (*s) pl_emit(*s++)` helper and its call sites are gone.

Everything below was measured in `probe/research/agentB/` — the shipping `probe/repl/src` and
`probe/repl/main` were **not** touched (copies: `agentB/src`, `agentB/src_base`, `agentB/main`).

| | before | after | delta |
|---|---|---|---|
| `.text` | 4 764 | 4 724 | **−40 B** |
| `.rodata` | 372 | 268 | **−104 B** |
| `.data` (baked dictionary) | 1 720 | 1 720 | 0 |
| `.bss` | 824 | 824 | 0 |
| ULP `.bin` (text+rodata+data) | 6 856 | 6 712 | **−144 B** |
| blocks countdown `gap` (`countdown.sh` arithmetic) | 376 | 232 | **−144 B** |

`have` (app 810 + pool spare) goes 986 → 1 130 B. Reproduce all of it with `./tools/verify.sh`.

## 1. The `.rodata` audit — parent's estimate confirmed in kind, refined in size

```
$ riscv32-esp-elf-objdump -s -j .rodata probe/repl/build/esp-idf/main/ulp_main/ulp_main.elf
 129c 4552525f 44494354 20000000 4552525f  ERR_DICT ...ERR_
 12ac 5441534b 53200000 0a756c70 20666f72  TASKS ...ulp for
 12bc 74680a20 6f6b0a00 73746163 6b3f0a00  th. ok..stack?..
 12cc 206f6b0a 00000000 08200800 0a6c696e   ok...... ...lin
 12dc 6520746f 6f206c6f 6e670a00 0a746173  e too long...tas
 12ec 6b73206e 65656420 616e2065 6d707479  ks need an empty
 12fc 20737461 636b0a00 a4050000 b6050000   stack..........
 130c ... (4-byte code addresses to 0x140c)
```

* message text: `0x129c..0x1303` = **104 B** (not ~90: the parent's list missed `"\b \b"` — 4 B with
  padding — and the per-string 4-byte alignment padding, ~4 B)
* dispatch table: `0x1304..0x140f` = **268 B = 67 entries** (parent said 63/252). Three targets appear
  twice (`0x67a`, `0xc20`, `0xe40`), so a de-duplicating dispatcher would recover ~12 B more — not text,
  and out of scope here.
* the table is `jr`-dispatched from `vm_enter` (`addi a4,s4,772 # 1304` at `0x576`); it is code
  addresses and **cannot** move to the host.

So the recoverable amount was 104 B of text, not 150 B, and not ~60 B. The scheme takes all of it plus
40 B of `.text`.

## 2. Code table (`src/msg_codes.h:28-35`)

| code | name | text emitted by the host | ULP site(s) |
|---|---|---|---|
| `0x81` | `MSG_ERASE` | `"\b \b"` (4 B) | `src/ulp_repl.c:259`, `src/uforth.c:742` |
| `0x82` | `MSG_LINE_TOO_LONG` | `"\nline too long\n"` (16 B) | `src/ulp_repl.c:264` |
| `0x83` | `MSG_UNDERFLOW` | `"stack?\n"` (8 B) | `src/ulp_repl.c:136`, `src/uforth.c:749` |
| `0x84` | `MSG_OK` | `" ok\n"` (8 B) | `src/ulp_repl.c:140`, `src/uforth.c:750` |
| `0x85` | `MSG_BANNER` | `"\nulp forth\n ok\n"` (16 B) | `src/ulp_repl.c:301` |
| `0x86` | `MSG_TASK_STACK` | `"\ntasks need an empty stack\n"` (28 B) | `src/ulp_repl.c:340` |
| `0x87` | `MSG_ERR_DICT` | `"ERR_DICT "` (12 B) | `src/uforth.c:489` |
| `0x88` | `MSG_ERR_TASKS` | `"ERR_TASKS "` (12 B) | `src/uforth.c:641` |

Sizes in brackets are the `.rodata` bytes each string occupied (rounded up to 4 B with its NUL);
they sum to exactly 104 B, which is what `tools/check_strings.py` asserts against the shipping ELF.

Not encoded, deliberately: the offending word in `err()` (`uforth.c:359-360`) and the digits from the
number printer are *dynamic* text produced on the ULP; only their fixed wrappers could ever be codes, and
`'?'`/`'\n'` cost 2 immediate bytes already.

### Why `0x80` and up is a free escape space
Every byte the ULP otherwise puts in `repl_out[]` is ASCII: the echo is gated on `c >= 32 && c < 127`
(`ulp_repl.c:262`), the number printer emits `'-'`, digits and `' '`, and `err()` emits the word from
`PAD` (upper-cased, from the same gated input) plus `'?'`. `0x80` itself is left **unassigned** so the
"is this a code" test is one comparison (`b < 0x80`) and an off-by-one cannot pass a non-ASCII byte
through as text.

## 3. Design

* **One list, both cores.** `src/msg_codes.h` holds `MSG_LIST(X)` as `X(name, code, text)`. The ULP
  compiles only the enumerators (the `text` argument is never emitted — measured: `.rodata` holds no
  string at all); the host compiles only the table. This is R6 done structurally rather than by two
  parallel lists plus a `_Static_assert`.
* **Single emit path on the ULP:** `static void msg(u8 code) { pl_emit((int)code); }`
  (`src/uforth.c:59`). `echo()` and `say()` are deleted; `pl_emit()` is still the only thing that
  touches the ring.
* **Host expansion** lives in `src/msg_expand.h`, one implementation used by the bridge *and* by the
  host test filter:
  ```c
  /* src/msg_expand.h, in the bridge's drain */
  static uint32_t msg_drain_ring(const volatile uint8_t *ring, uint32_t mask, uint32_t in_head,
                                 uint32_t *in_tail, char *dst, uint32_t cap)
  {
      uint32_t ot = *in_tail, k = 0; char scratch[MSG_OUT_TEXT];
      while (ot != in_head && k < cap) {
          const char *t; size_t n = msg_byte_text(ring[ot & mask], scratch, sizeof scratch, &t);
          if (k + n > cap) break;              /* no room right now: leave this byte UNREAD */
          memcpy(dst + k, t, n); k += (uint32_t)n; ot++;
      }
      *in_tail = ot; return k;
  }
  ```
  and in `main/repl_main.c:83-87` the ring tail is published only after the expansion, so a byte that
  did not fit is retried next pass — never dropped, never split.
* **Fail loud.** An unknown code expands to `"\nulp: ERR_ULPCODE 0x%02x (unknown code)\n"` *in place*,
  at the position where the message should have been (not to a log the operator cannot see).
* **Compile-time guarantees** (`src/msg_expand.h`): the table length must equal the number of entries in
  `MSG_LIST` (catches a code with no string, or a hole in the numbering), and every message must fit
  `MSG_OUT_TEXT` = 64 B (catches the message that could never fit, which would freeze the drain).

## 4. Measurement method

`tools/measure.sh` is `tools/disasm.sh`'s twin-build idea generalised: it compiles the given source tree
with the exact per-file command IDF recorded in `ulp_main/compile_commands.json` and links with the exact
line from `build.ninja`, swapping only the `ulp_repl.c` object. Checks built in, because a silent
mismatch here produces a plausible number for the wrong program:

* the baseline twin reproduces the shipping ELF exactly (4 764 / 372 / 1 720 / 824) — the harness measures
  the same program;
* the rewrite is *verified* to point at the copy: the object path `.../ulp_repl.c.obj` contains the
  source path as a substring, so a naive `sed` rewrites the object name and recompiles the **shipping**
  source, reporting −0 B for an edit that is not in the measurement. That happened on the first run.
* the full IDF build in `agentB/build/` (which also compiles the new `repl_main.c`) gives
  `.text` 4 724 / `.rodata` 268, and its `.rodata` is byte-identical to the twin's
  (sha256 `e4bc80be…`), so the twin is the shipping machine.

## 5. The echo path, and the banner

* **`pl_emit` cannot move.** It is 66 B of `.text` and it *is* the channel: an RTC-memory ring write plus
  the drop counter (`ulp_repl.c:91-101`). The bytes it carries — echoed characters, digits from `.`, the
  offending word — are produced on the ULP by the interpreter. Moving it to the host would mean moving
  the interpreter.
* **What did go away:** the per-character string loop `echo()`/`say()`, 20 B of `.text` (GCC had already
  folded the two into one function — identical code folding), and its call sites; 18 `jal` to
  `pl_emit`/`echo` became 16. `pl_emit` call sites are now only: echo of accepted input, the accepted
  `'\n'`, `'?'`, the number printer, and `msg()`.
* **The banner** (`"\nulp forth\n ok\n"`, 16 B of text + a `lui/addi/jal`) now costs **1 byte**. It must
  *not* be moved to the host entirely: `ulp_repl.c:301`'s GUARDRAIL is that the prompt arrives from the
  ULP, so "the HP printed it" can never be mistaken for "Forth ran". A code preserves that proof — the
  byte is still written by the ULP, in the same ring position — while a host `printf` in `app_main`
  would print the banner even if the ULP never booted. For the record, deleting it outright was measured
  too (`src_nobanner/`): `.text` 4 724 → 4 716, i.e. **8 B more**, and `.rodata` unchanged. 8 B is not
  worth losing the only evidence that the coprocessor is alive.

## 6. Validation (`./tools/verify.sh`, no board)

1. `tools/check_strings.py <shipping ELF>` — all 8 messages are byte-for-byte the strings in the shipping
   image, and the text region is *fully* covered by them (no orphan, no invention). This is the check
   that covers the four messages no host run can reach (`MSG_BANNER`, `MSG_LINE_TOO_LONG`,
   `MSG_TASK_STACK`, `MSG_ERR_DICT`).
2. `tools/transcript.sh` — builds the host engine from `src_base` and from `src`, runs the shipping
   regression suite plus a scripted interactive session, and requires the expanded transcript to be
   byte-identical to today's:
   * `tests/expected.txt` reproduced by the baseline (harness check);
   * `5\b\x7f9` prints `5\b \b9` today and `5\x819` now → **the code sits between echoed characters and
     expands in place**, which is the ordering risk answered by measurement, not argument;
   * `BOGUS` → `BOGUS?\n` unchanged (dynamic text still from the ULP), `" ok\n"` → `0x84`;
   * `tests/ntsk.fs` → `ERR_TASKS ` still named, now code `0x88`;
   * an unlisted code `0x90` produces `ulp: ERR_ULPCODE 0x90 (unknown code)`, not silence.
3. `tools/ring_test.c` — drives the *real* `msg_drain_ring` through a 128 B ring with a 64 B staging
   buffer, 86 B in 2 passes, including the pass where a 27 B message does not fit and is left unread.
4. `idf.py build` in `agentB/build/` — the HP side (new `repl_main.c`, relative include, static asserts)
   compiles and links clean; `src/ulp_p39.c` and `src/ulp_stub.c` still compile.

## 7. Risks

1. **Drop semantics change (the only non-identical case).** `pl_emit` drops when the 128 B ring is full
   (`ulp_repl.c:95`), so today a message can arrive *truncated* (`stack` without `?`). With codes a
   message is atomic: it arrives whole or not at all, and ring pressure drops 4–28× for messages. That is
   strictly better and `repl_out_drop` still counts, but it is not byte-identical *in the overflow case*.
   The transcript is byte-identical whenever nothing is dropped, which is the normal case.
2. **The two cores must be flashed together.** The codes are a wire format. A stale ULP `.bin` with a new
   host (or the reverse) prints the *wrong* message for a renumbered code — silently, because every code
   is valid. Mitigation in place: "append only" is written into `msg_codes.h`, and an *unknown* code is a
   named error. Not done, and recommended (~8 B of `.data`, not measured): export `repl_msg_base` and
   `repl_msg_last` from the ULP and assert equality with `MSG_BASE` / the last code at boot, next to the
   existing ring-size assert (`repl_main.c:125`).
3. **`-DP42_BENCH` was already broken and stays broken.** Measured both trees: `p42_dispatches`
   undeclared and `BENCH_TAG` undefined (it is defined inside a dead `#ifdef` in `ulp_repl.c`). My change
   adds one more error there (`echo` no longer exists). Note added in `src/p42_bench.inc` and
   `src/ulp_repl.c` so nobody reads that as the cause.
4. **`Forth ran` proofs:** the banner code is written by the ULP before the first reply; keep that
   ordering if `main()` ever changes.
5. **`uforth.c` is shared** by the ULP image, the host suite and `ulp_p39.c`. All three still build; the
   host suite's transcript now contains code bytes, so any future host-side diff must go through
   `tools/expand.c` (or `msg_expand.h`) or it will "fail" against `tests/expected.txt` for a reason that
   is not a regression. `tests/run.sh` itself was left untouched — it lives in `probe/repl` and will
   fail once this change lands there; it needs `| artifacts/expand` in two places (see below).

## 8. Not done / next steps

* Spend the 144 B: raising `MEMSZ` 1 704 → 1 848 keeps `pool used` at today's 7 680/7 856 and adds 144 B
  of app space — **arithmetic, not measured**: it requires re-baking `src/image.h`, a separate step with
  its own `.data` measurement.
* Wire `tests/run.sh` in `probe/repl` through an expansion filter (two lines) when the change is adopted.
* If `-DP42_BENCH` is ever resurrected, give its labels codes and define `BENCH_TAG` on the host side,
  where text now belongs.

## Files (all under `probe/research/agentB/`)

* `src/msg_codes.h` — the code table (new)
* `src/msg_expand.h` — code → text + `msg_drain_ring` (new)
* `src/uforth.c` — `msg()`, 5 sites converted, `say()` deleted
* `src/ulp_repl.c` — `echo()` deleted, 5 sites converted
* `main/repl_main.c` — includes `msg_expand.h`, expands while draining
* `src_base/` — pristine copy, byte-identical to `probe/repl/src` (`diff -rq` clean), used as the
  "before" build; the shipping tree itself was never written to
* `src_nobanner/` — throwaway variant for the banner measurement (§5)
* `measure.sh`, `cc.txt` — the twin-build harness and the recorded IDF compile+link command
* `tools/{verify.sh,transcript.sh,check_strings.py,expand.c,ring_test.c}`
* artifacts, safe to delete: `build/` (real `idf.py build`, ~130 MB), `out/` (twins, logs),
  `out.stale/` (the invalid first run — see `out.stale/WHY.txt`)

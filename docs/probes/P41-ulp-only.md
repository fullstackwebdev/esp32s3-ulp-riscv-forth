# P41 — Does any Forth execute on the ESP32's main cores?

| | |
|---|---|
| **Question** | R6 claims the main cores are only a byte server. Is there an *assertion*, or only an intention? |
| **Answer** | **Neither existed before this probe.** Now two independent checks do: a static one that fails if the main-core executable contains an evaluator, and a counterfactual one that fails if the console answers with the coprocessor switched off. |
| **Time** | 15 min, one run |
| **Verdict** | **PASS** — static 6/6, counterfactual silent (`b''`), restored image answers `5 ok` |

## Why an intention is not an assertion

Before this probe the evidence was: *"`repl_main.c` does not include `uforth.c`."* That is a statement about
source intent, and this project has already rejected two claims of exactly that shape:

* P32 — "the budget is 3 438 B" was a **convention error**, not a measurement.
* P25 — "these pages are hot" was **occupancy**, not access.

Both had looked fine. A structural argument is the same category of evidence: it is true today and it stops
being true, silently, the first time someone adds a `#include` or a helper.

## Static check — `probe/repl/tools/assert_ulp_only.py`

Six assertions, each of which can fail on its own:

| # | Assertion | Result |
|---|---|---|
| 1 | the HP executable carries the ULP image as data | `_binary_ulp_main_bin_start` present, blob **6 108 B** at file offsets `0x9f51..0xb72d` |
| 2 | the dictionary payload is present in the HP image only *inside* that blob | 1 occurrence, inside |
| 3 | the HP executable defines no evaluator | none of `interpret`, `vm_enter`, `do_colon`, `vm_run`, `run_line`, `repl_drain` |
| 4 | the evaluator *is* on the ULP | `main` = **2 956 B** (inlined dispatch loop, P39) |
| 5 | the ULP holds the dictionary resident | `mem` = **1 280 B** |
| 6 | the HP bridge source has no line discipline | no `interpret`, `tib[`, `find(`, `pl_emit` in code |

### Two lessons the checker taught us about checkers

**Substring matching is worthless here.** The HP image genuinely contains `SWAP` and `OVER` — inside the
embedded ULP blob, which it must carry in order to load it. And it contains `DUP` twice as a fragment of IDF's
own `ESP_ERR_MESH_DISCARD_DUPLICATE` and UART's `MODE_RS485_HALF_DUPLEX`. A word-based sweep reports three hits
on a perfectly correct image; a checker you have learned to ignore is worse than no checker. The assertion
therefore matches the **1 280-byte dictionary payload** byte for byte and requires every occurrence to fall
inside the blob.

**The first version flagged its own comment.** Check 6 failed with `references ['interpret']` — because a
GUARDRAIL comment in the bridge explains that *the interpreter is on the ULP*. The fix is to strip comments and
match identifiers, not to delete the explanation.

## Counterfactual check — the stub image

`src/ulp_stub.c`, built with `REPL_ULP_STUB=1`: same rings, same sizes, a `main` that bumps a counter and
returns. It reads no command byte, echoes nothing, interprets nothing.

```
boot: ulp forth bridge, 132 B image       <- HP alive, 132 B ULP image
ulp woke 76 times                          <- coprocessor alive: 76 x 6.5 ms = 0.5 s
>>> "2 3 + ." -> b''                       <- zero bytes. no echo, no prompt, no error
```

And the same bridge with the real image restored:

```
ulp woke 76 times
>>> "2 3 + ." -> b'2 3 + .\n5 ok\n'
```

**Why the wake counter matters.** Silence alone is ambiguous: it could mean the coprocessor never started. The
`ulp woke N times` line is printed by the main core from a ULP-written counter, so in the stub run it proves the
coprocessor ran **and** produced nothing. That turns a negative result into evidence.

## Build lesson

The stub first failed to build: `'ulp_repl_cmd' undeclared`. The linker's `--gc-sections` had dropped the unused
ring arrays, so the IDF map generator exported no `ulp_*` symbols for them and the HP side had nothing to link
against. A stub that does nothing still has to *look like* it uses what it defines.

## What this does not prove

* The bridge still moves bytes — by design (R6). The claim is about **Forth**, not about the main core being
  idle. `console_task` copies UART bytes into the ring and ring bytes out to UART, and that is the whole of it.
* Nothing here constrains the *ULP* to be the only evaluator across a firmware swap; re-run the checker, it is
  0.4 s.

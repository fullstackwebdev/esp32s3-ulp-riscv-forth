# archive/ — kept, not deleted

Nothing here was thrown away. These trees were moved out of the active layout because they are either
superseded or regenerate, and this file exists so that no future reader has to guess what happened to them.

| path | what it is | why it is here | where the live version is |
| --- | --- | --- | --- |
| `research-superseded/agentA` | P52 lever sweep: dispatch and accessor variants (computed goto, `UC_FOLD`, `-fno-jump-tables`, frame pointer, ICF) | its findings were adopted or explicitly rejected; the twin-build harness it introduced lives on | `probe/research/P54-*/measure.sh` |
| `research-superseded/agentB` | P52 message-code work (one-byte codes, `MSG_LIST`, host-side expansion) | adopted into the shipping image; findings are in `probe/EVIDENCE.md` E-081 | `probe/repl/src/msg_codes.h`, `msg_expand.h` |
| `research-superseded/agentC` | P52 stack-depth study (`SD 16` is a correctness bug; `SD 32` costs +394 B) | the defect was fixed loudly at +22 B instead (`ERR_STACK`), so the +394 B build was never taken | `probe/repl/tests/deep.fs` |
| `old-probes/uforth` | the original host prototype of the engine (`boot_min.fs`, `host_test.c`) | the engine now lives in `probe/repl/src/uforth.c` and the interpreter runs on the chip | `probe/repl/src/` |
| `old-probes/lcd-hello` | display bring-up | the display work was cancelled by decision; no display code is in the shipping image | — |
| `logs/` | 77 loose build logs from `probe/repl/*.log` | evidence of a build, not of an idea; kept because deleting evidence is how a project starts lying about its history | numbers derived from them are in `probe/EVIDENCE.md` |

**Not archived, deliberately:** `probe/results/` (per-probe RESULT.md, kept images and `flash_args`),
`probe/repl/probe-results/` (P42/P52/P54 measurement artifacts), `probe/lev/` (the `rdcycle` harness),
`probe/isa/`, `probe/research/P54-*` (the five latest lever probes — the live idea set), `docs/`,
`probe/EVIDENCE.md`, `CONSTRAINTS.md`.

**Removed, not archived:** `probe/**/build*/` — IDF build trees, 134 MB each, 2.86 GB in total, zero
tracked files, fully reproducible. The live build tree `probe/repl/build` stays.

To bring anything back: `mv archive/old-probes/uforth probe/uforth` (paths are unchanged inside each tree).

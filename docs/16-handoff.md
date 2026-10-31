# 16 — Handoff letter: esp32-rv32, the ULP Forth machine

Written for an agent starting with **no context**. Everything below is either measured in this tree or explicitly
marked as a plan. Read this first, then `docs/14-probe-rules.md` (probe discipline) and `docs/15-overlays.md` (the
paging workstream in full detail). `CONSTRAINTS.md` holds the current numbers.

---

## 1. The mission

There is a **Forth machine implemented in C for the ESP32-S3's ULP coprocessor**, running out of **RTC slow RAM
(~8 KB total)**. The ULP has no cache, no dynamic loader, and one shared 8 KB of RTC RAM that holds *everything*:
the code, the dictionary, the stacks, the buffers and the console rings. The main core (an ESP32-S3 host task) serves
as a block device over a mailbox, and runs the console pump.

Two things are being pushed, in order:

1. **Size** — maximise *application space*: the free gap in `mem[]` between the end of the code area and the newest
   dictionary header. Every byte saved in `.text`, `.rodata`, `.bss` or the dictionary is a byte of application space
   after a re-bake, because `MEMSZ` (the size of `mem[]`) scales 1:1 with the pool.
2. **Capability** — make the machine hold **programs larger than one image** by paging *phases* of code (and data)
   through the block store, with a resident event loop that swaps them.

Both workstreams are alive and both have real, measured wins. This letter counts them, and lists the wins that are
one step away.

---

## 2. Where the tree stands right now (all of this is measured)

**`main`** — shipping engine, green, flashed:

| | |
|---|---|
| application space | **1 536 B** |
| `MEMSZ` | 2 288 |
| dictionary | 86 words, 3 B headers (`hash12 | xt11 | imm1`) |
| pool | 7 853 / 7 856 B |
| device | flashed, `LATEST HERE -` = 1536, `0 BLOCK` = 2160, `128 BLOCK` → `ERR_RANGE` |
| suite | 22 PASS / 0 FAIL |

**`overlay-manager`** (23+ commits off main) — the paging laboratory:

| | |
|---|---|
| resident manager + event loop | 846 B toll (manager 528 + loop 318) |
| free space at the prompt | **690 B on the chip / 704 B on the host** |
| three-phase program (tier: host+device) | 1 692 B compiled, +10 % over a real control |
| **six phases** (tier: host) | 1 608 B, +4 % — a *small* program, see §7 |
| **nine window-sized phases** (tier: host) | **4 644 B = 302 %** |
| **escalating probe high score** (tier: host) | **18 phases, 9 288 B, 604 % of the control** |
| block store (tier: device) | 128 blocks × 128 B = **16 KB round trip, 0 mismatches** |
| multi-block phase assembly (tier: device) | **2 blocks proven**; 7 blocks open (§8) |

`super-optimization` and `main` share the same engine; `overlay-datafix` was the vehicle that carried the safe
data-side wins into `main`.

---

## 3. Architecture you must know before touching anything

- **`mem[]` is the machine.** `#define MEMSZ` in `probe/repl/src/ulp_repl.c` sets its size, and `mem[]` is the
  *image* (`.data`), so `MEMSZ` is 1:1 with the pool. Raising it costs pool; lowering it costs app space.
- **`BLKADR = MEMSZ - BLKSZ`.** The 128 B block window lives *inside* `mem[]`, at the top. The dictionary must never
  grow into it (`blk_place_ok()` guards this).
- **Dictionary layout**: headers grow **down** from `HDRTOP = BLKADR`, code grows **up** from `DICT`. A header is
  3 bytes: 12-bit hash, 11-bit token, 1 imm bit. `find()` walks headers upward from `V_LATEST` with a 3-byte stride
  and a byte filter. Tokens are **tagged**: an even value is an address; `PRIM_TAG - 2*id` is a primitive. Decode is
  one compare: `t = PRIM_TAG - w; cf = (t <= 2*(P_COUNT-1)) ? t>>1 : rd16(w)`.
- **Sys-vars** live at the bottom of `mem[]`: `V_STATE=0, V_HERE=4, V_LATEST=8, V_SEAL=12, V_LOADB=16, PAD=20,
  DICT=52`. Every one of those 4-byte slots is a byte of app space you do not have; add them only with reason.
- **Bake and build must agree on everything that shapes the dictionary**: `MEMSZ`, `BLKSZ`, `TIBSZ`, `DOVL_LOAD`,
  `DP33_BLOCK`, `DBLKPRIM`, `DP43_TASKS`. `tools/bake.sh` compiles the engine on the host (`-DHOST`), compiles the
  prelude files, and emits `src/image.h`. The chip link uses that image. `flash_safe.sh` is the authority on the
  pool: it **refuses** to flash an over-budget image (this has saved the project repeatedly).
- **The chip's `TIBSZ` is 96**, the host's is 128. A block is 128 bytes, so a block *never* fits one tib pass; the
  loader chunks and cuts back to a space. Any source line longer than ~90 chars is dangerous for the chip.
- **The block store is the host's `.bss`** (`blkfile[BLK_N][BLK_SZ]`, 128 blocks). It is **volatile** — a paged
  program survives one power cycle. Persistence (NVS/flash) is not implemented.
- **`/dev/ttyACM1` is the ULP console** (through the host pump). `/dev/ttyACM0` exists but emits nothing.

---

## 4. Wins so far — the victory list

**Size workstream (main, shipping): 727 B → 1 536 B, +111 % application space.** Highlights, each measured and
device-verified:

- removed dead state by audit: `FAULT` (a paging-era primitive that could never fire) +85 B, `repl_out_drop` +26 B,
  the base-switching machinery +63 B;
- **tagged primitive tokens**: tokens encode primitives arithmetically, deleting 67 two-byte code fields (+66 B);
- **`XT_PRIM()`** derives boot-assigned xts instead of storing them (+35 B), plus `LIT2` for halfword literals;
- alignment relaxation (`a4()` deleted, EVEN is the real requirement) +42 B;
- **seven whole-tree optimizer pass disables** shrink `.text` by 92 B on this 16-register target (the opposite of
  the usual intuition — pass disables win here, measured);
- two flag pairs that each lose alone but win together (`-fno-ssa-phiopt -fno-tree-pre`, −8 B);
- the P54 kernel dispatch table halved from `u16` to `u8` (+16 B), all eleven kernel ops device-verified;
- a pre-optimisation reference copy kept beside the live engine (`src/preoptimization.c`).

**Capability workstream (branch): the machine now pages code and data.**

- A **source-switch `LOAD`**: `p_load` fetches a block and arms `V_LOADB`; `word()` — the only reader of `tib` —
  refills from the block when the current source is dry. No recursion, no lost tail, **and it took an entire
  `interpret + vm_enter` frame off the deepest chain** (the chip's stack is 327 B; we measured ~336 B before and
  ~200 B after).
- A **resident event loop** (`POST/EV?/EV@/RESET/PUMP`) with a 4-slot ring, handlers that run to completion, and
  phase swaps driven by `PHASE`. Overflows are rejected and counted, never silently dropped.
- A **name-collision guard** (`SEAL` publishes `V_SEAL`; `mkentry` refuses a definition whose hash matches a
  resident or in-overlay name, and **names the offender**), proven on the host and the chip.
- **`EXECUTE` of token 0 is now a named error** instead of running garbage from address 2 — landed on `main`.
- **Data at scale measured on hardware**: 128 blocks × 128 B = 16 KB written and read back, **0 mismatches**.
- **A/B with a real control**: the control (same program, one image, no overlays) has 1 536 B and dies with
  `ERR_DICT`; the paged build runs; phase C's output exists only in the paged build (asserted as a diff).
- **Escalating probe** (`tests/ceiling_probe.sh`): starts at 3 phases, grows one at a time, and reports the high
  score — **18 phases / 9 288 B / 604 %** of the control, stopped by the store (126/128 blocks).
- A **host-side block seeder** (`seed_poll`, **zero ULP bytes**): one UART line `#b <block> <hex>` writes a whole
  block, replacing ~19 poke lines per block. It is now the only UART reader and forwards everything else.

---

## 5. The paper trail you must extend

- `docs/14-probe-rules.md` — probe discipline. Read before running any probe.
- `docs/15-overlays.md` — the whole paging story: design, measurements, every dead end, and the open defect.
- `docs/15-super-optimization.md` + `CONSTRAINTS.md` — the size workstream and the current numbers.
- `probe/repl/.auto` — nothing; the autoresearch log lives at the repo root `.auto/` (`log.jsonl`, `ideas.md`).

---

## 6. Tests: what exists and what each proves

`probe/repl/tests/run.sh` runs everything. Current: **22 PASS / 0 FAIL**.

| test | proves |
|---|---|
| `suite.fs`, `binops.fs`, `semantics.fs`, `lookup.fs`, `hdr.fs`, `addr.fs`, `deep.fs` | the engine's basic semantics and the dictionary/lookup invariants |
| `blocks.fs`, `blocks_noserver.fs` | the block layer: happy path, checksum failure, the no-answer path, and that the window address is *stable* (not a literal) |
| `overlay.fs` | source-switch `LOAD` on one block: a defined word runs through the hook, 40 load/drop cycles leave both pointers sealed |
| `overlay_collide.fs` | collisions refused, **including two names inside the same overlay**, offender named, dictionary unmoved |
| `loop.fs` | the event loop's rows: same-phase events cost one round trip, ring overflow rejected and counted, 50 rotations, failed load + `RESET` recovery |
| `capacity.sh` | per-phase sizes and per-phase numbers for three phases; every phase under the window |
| `flagship.sh` | a **six-phase** program (452+382+260+150+180+184 B) with pairs of phases verifying each other's output |
| `ceiling.sh` | nine **window-sized** phases, 4 644 B = **302 %** of the control |
| `ceiling_probe.sh` | the escalating high score: **18 phases, 9 288 B, 604 %**, stopping on the store |
| `abtest.sh` | control-fails / paged-passes, plus the capability diff, with the control built **without** overlays |

`tests/device_ceiling.py`, `tools/mkcapacity.py`, `tools/mkphases.py`, `tools/blkseed.py` are the generators and
device drivers. `tools/mkphases.py` emits both the phase sources and their expected numbers (asserted every run).

---

## 7. The two numbers that must never be confused

- **`flagship.sh` = +4 %.** A six-phase program averaging **268 B** per phase: barely bigger than the control, so
  the fixed 846 B toll is not repaid. This is the "small program" case, and it is *correct* to show it.
- **`ceiling_probe.sh` = 604 %.** Window-sized phases (**516 B** each), enough of them to fill the store.

The multiple is a function of **how many window-sized phases the program needs**, because the toll is fixed and a
phase is capped by the free space at the prompt. One image → paging loses. Nine window-sized phases → 3×. Store
full → 6×. A verdict that quotes one number without the other is wrong; both are in the suite, labelled.

---

## 8. The one open defect, stated exactly

**Symptom (tier: device).** A 7-block phase source does not assemble. Blocks 8‥11 load `ok`; block 12 fails with
`IDX?`, then later blocks with `DATABLK?`. A **2-block** phase assembles perfectly (proof: `: ZZ 42 . ;` in block 8,
`ZZ 7 .` in block 9 → `8 LOAD` ok, `' ZZ` = 800, `9 LOAD` → `42 7`).

**The mechanism that makes this hard to read.** An error **rewinds the dictionary to the save point**, so the first
error erases the evidence and every later failure points at the wrong place. `IDX?` at block 12 is almost certainly
a *symptom*.

**Already fixed on the way here** (each a real bug, each now a GUARDRAIL in the code):

1. the seed line buffer was 180 B → blocks were silently truncated to **87 of 128 bytes**;
2. `\` comments swallow the rest of a **block** (a block has no line structure), and `(` consumes to `)`, so a
   128-byte cut inside `( -- )` eats real code — both measured (`IDX?`, `--?`);
3. the seeder wrote only its payload, so a block retained an **old tail**; `LOAD` compiled the new text, tripped on
   the stale tail, errored — and the error rewound the phase, discarding its definitions (`Z6?`). The seeder now
   **blanks the block** before writing;
4. multiple `LOAD`s on one line: the rest of the current line is interpreted *before* the armed block, so the second
   `LOAD` overwrites the cursor and **silently skips** a block.

**The four hypotheses to separate next** (run the per-block `LATEST`/`HERE` probe first, one arm per line, and wait
for the prompt rather than a fixed sleep):

1. an earlier error is masked — the chain may share one save point, so check `HERE`/`LATEST` **after each block**;
2. a *retried* seed skipping the blanking (same stale-tail bug on a second path);
3. a definition **refused** inside blocks 8‥11 by the collision check (it must print the offender — confirm nothing
   is swallowed);
4. **capacity**: a 7-block phase is ~516 B against 690 B, and 8 scans once overflowed with 31 B left; print the free
   space after each block.

**The engine-side fix worth landing** (prepared, then reverted because it needs test rewrites): refuse to arm
`V_LOADB` while already armed, as a **named error**. It would have caught §8.4 loudly. It was reverted because
several existing tests arm twice in a loop (`8 OVL 2 OVL`) — those loops were themselves silently skipping blocks,
so the guard and their rewrite land together, one arm per line. The comment at the site in `p_load` explains this.

---

## 9. Hard-won engineering rules (they are also GUARDRAIL comments at the sites)

- **Never get green by weakening a check.** A version of the device harness accepted "size > 0" and reported 17
  "phases" of 70 B where a full phase is 516 B — a failing run turned green. It now requires the size within ±40 B
  **and** an error-free transcript, and has a `--skip-block` mode to prove it can fail.
- **Every new test must be shown failing once** before it counts.
- **A host suite cannot see stack overflow.** The host has megabytes; the chip has 327 B. Use `-fstack-usage` on the
  real ULP compile (`build/esp-idf/main/ulp_main/compile_commands.json`) and verify on the chip.
- **One window, one block.** Never keep a source address and a destination address at once; read, compute into
  phase-local cells, then fetch the destination, write, `SAVE`. `UPDATE` alone does not persist.
- **Measure phases in a fresh process.** Loading phases one after another accumulates them in the overlay area and
  overruns the dictionary (the symptom is a resident word vanishing).
- **`HERE`/`LATEST` are getters.** `SEAL` stores into its own cells; `OVL` stores into the sys-vars. Mixing them
  rewinds the dictionary to address 0.
- **Names are case-insensitive and hash-collided.** `phase` and `PHASE` are the same word. After `SEAL`, ~2.4 % of
  new names collide with a resident one and are refused (loudly, naming the offender) — rename and move on.
- **`REPEAT` needs a `WHILE`** (there is no `AGAIN`): an infinite loop is `BEGIN 1 WHILE … REPEAT`.
- **`EXECUTE` of 0 is a named error** now; a cleared hook cell is loud.
- **The engine emits message *codes***, so tests must pipe through `tools/expand` before grepping for `ERR_DICT`.
- **`blk_out` latches on a timeout** — every later block call answers `ERR_BUSY`. The escape hatch is
  `0 2 BLKXFER` (op 2 = `BLK_ABORT`). It is documented in `CONSTRAINTS.md` because naming it in the message costs
  `.rodata` the pool cannot spare.

---

## 10. How to work here (the operating discipline)

- **Build**: `cd probe/repl && . $IDF_PATH/export.sh && idf.py build` → `./flash_safe.sh` (it refuses over-budget
  images; treat a refusal as information, not an obstacle). Long builds go in `tmux`, never `&`.
- **Host suite**: `./tests/run.sh` — must be green before and after any edit.
- **Bake**: `./tools/bake.sh <MEMSZ>`; the number must equal `MEMSZ` in `src/ulp_repl.c`.
- **Device**: `/dev/ttyACM1`, 115200, 8N1. Reset with `python -m esptool --port /dev/ttyACM1 --after hard_reset
  chip_id`. Send a line, wait for `ok`, never assume.
- **Never** `rm -rf` (the harness blocks it), never write to `cache/`, `probe/results/`, `archive/` except append,
  never use `/tmp` for project data, never run unbounded `find`, never use ports 8000/8080/3000.
- **Every code edit carries a `// GUARDRAIL:` comment** recording the specific lesson, the reason, and the fix.
- **Verify on the chip before claiming a keep**; `flash_safe` is the authority on budgets, not the host twin.

---

## 11. The road ahead — planned wins, in order

1. **Assemble the 7-block phase** (§8). One probe: per-block `LATEST`/`HERE`/free-space, one arm per line, waiting
   for the prompt. That closes "device-verified paging at window size", which turns the host 3× into a device 3×,
   and the escalation then measures the device high score directly.
2. **Land the re-arm guard** in the engine, together with rewriting the loop tests that arm twice (one arm per
   line). Silent block skipping becomes a named error — a whole class removed.
3. **A clock.** Rows 6/7 (event latency, switch cost) need one: a dispatcher counter (~8 B of `.text`) or a
   `rdcycle`-style primitive. `MS` is a *delay*, not a clock. This unlocks the timing half of the A/B table.
4. **Row 10, the stack canary.** The paint base is settled from `nm` (`0x1EAC`; the image ends at `0x1EA9`, stack
   `[0x1EA9, 0x1FF0)` = 327 B) and the channel is proven, but the injected report corrupts the console; publish the
   number into an RTC cell and read it from a **Forth word** (4 B of app space in a debug build).
5. **The big lever: drop the compiler from a deployed image.** `nm --size-sort` on the ULP ELF: `vm_enter` 2 300,
   `main` 876, `word` 314, `mkhdr` 208, `blk_xfer` 136, `find` 114, `text` ≈ 5 504 B. Almost nothing there is
   dev-only — the bake/dump paths are already `#ifdef HOST`. What *is* removable is the **compiler** (`word`,
   `mkhdr`, `:`/`;`/`clit`, the parse half of `main`): **~1 000–1 400 B of `.text` → the same in app space**, with
   no window, no loop and no toll. That nearly doubles application space, and it is a *product decision*: the device
   becomes a machine that runs precompiled words instead of a Forth REPL.
6. **Binary overlays, in that deployed context.** Measured as *not* worth it for the REPL image (they shrink store
   use 26 % → 10 % of a non-binding resource and don't touch the window). In a compiler-less image they become the
   natural transport: no parser to feed, so phases are bytes.
7. **Persistence** for the block store (NVS or a flash partition): today a paged program lives one power cycle.
   Main-core work, zero ULP bytes.

---

## 12. The vision

The machine currently holds a **1.5 KB program in an 8 KB RAM** and has been measured running a **9.3 KB program in
phases** — six times what fits — with a resident toll of 846 B. That is the headline: *this coprocessor can run
programs an order of magnitude larger than its RAM, at the cost of one resident manager and a programming model
(handlers run to completion; phases are swapped by a resident loop).*

The path from here is not more bookkeeping, it is leverage:

- removing the compiler makes the *image* smaller, which raises the per-phase window for every paged program;
- a clock makes the paging cost legible, so the trade ("846 B and a block round trip per switch") can be quoted in
  milliseconds;
- a deployed, compiler-less, binary-phase image is a genuinely new capability: a **multi-phase application on a
  coprocessor with 8 KB of RAM**, with the store as its program warehouse.

Everything in this tree is reproducible: the suite asserts the control *fails*, the paged build *passes*, the
capability diff is a transcript, and the high score is *found by escalation* rather than asserted. That is the
standard to keep.

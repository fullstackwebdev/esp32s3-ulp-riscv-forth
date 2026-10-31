# 17 — Probe checklist

`[ ]` unchecked · `[x]` done, with the one-line result · predictions live in `docs/17-predictions.md` and are never
edited after a run.

Parallelism note: **every device probe shares `/dev/ttyACM1`**, so they run sequentially — two writers to one board
corrupt each other's transcripts and dictionaries. Host-only probes (P1, P2) could be parallel in a worktree, but they
edit the same file (`src/uforth.c`) as the in-flight work, so they are sequenced too.

## Session A — device, cheap (padding, boundaries, confirm)

- [x] **P2c-a** `: ZZ 42 . ;` padded to a full block — predict **ok**, `' ZZ` resolves
- [x] **P2c-b** `4 CONSTANT QP` padded — predict **ok**, `' QP` resolves
- [x] **P2c-c** 128 B ending on a token, no trailing space (`: ZC 42 . ;` + spaces + `ZC`) — predict **42 printed, ok**
- [x] **P2c-d** block ends on a bare name (`CREATE ZT`) — predict **ok**, `' ZT` resolves
- [x] **P2c-e** 7 blocks, one definition each, loaded one per line — **PASSED**: all 7 ok, LATEST 1481→1463, `' E1` 794, `' E7` 854
- [x] **P2c-f** colon body spanning a block boundary — loads `ok`, and the deeper finding is that it only works when the closing `;` is delivered in the SAME tib pass (see P1)
- [x] **P3** per block `LATEST`/`HERE` + `' <NAME>` — block 8 `ok` and `DATABLK`=794 after a reset; the earlier frozen reading was a non-reset board (now a GUARDRAIL)

## Session B — device, instruments

- [x] **P2** instrument verified against KNOWN content: 128 spaces ⇒ `32,32,32`; 128 `A` ⇒ `65,65,65`; deliberate `B` at offset 64 ⇒ reads 66 where 65 wanted ⇒ **the instrument can fail**. (A `BEGIN/WHILE/REPEAT` checksum was tried first and abandoned: no `DEPTH`, no `DO/LOOP` on this machine.)
- [x] **P2b** transport before execution — **72/72 byte checks match** on the chip (9 blocks × 8 offsets incl. 126,127)

## Session C — host, free

- [x] **P1** traced host run — `refusals=0` (counter proven able to fire), tokens correct, `STATE=1` at end-of-source, `10`/`LOAD` read at `ST=1`, stray `;` after the next line began ⇒ block/tib-pass fault
- [x] **P1b** decision — fifth outcome, not in the table: leftover tail after the next line started ⇒ fix the splitter

## Session D — device, follow-ups (only what P1/P3 point at)

- [x] **P4** rename/CREATE tests — not name-related: `CREATE`/`CONSTANT` succeed from prompt and blocks, refusal counter 0
- [x] **P3b** chip refusal counter — condition false and now evidence-backed: P1 is unambiguous and the host counter was **shown to fire** (`refusals=1` on a deliberate `CREATE` collision) before its zero on the phase was trusted
- [x] **P5** content bisect **127 ⇒ ok (−18 B), 64 ⇒ ok (−12), 32 ⇒ ok (−6), 16 ⇒ `?` (−0)** — the 16 B prefix cuts inside a token, so the bisect bounds the break precisely
- [x] **P6** length ladder **2 ⇒ 130 B ok, 3 ⇒ 132 ok, 4 ⇒ 184 ok, 5/6/7 ⇒ 184 with `12 LOAD → Z4?`**; content swap (slot 10 ← block 14's text) still fails at **block 12** ⇒ position, not content

## Always

- [x] **P7** lessons as tests — `tools/fsplit.py --selftest` (3/3) in `tests/run.sh`, and the defect registered in `tools/known_defects.sh` as **F-BLK-TAIL** (states the correct behaviour `42`, currently reports `DEFECT ... got ':?TAILTEST?'`)
- [x] **P8** suite green — 22 PASS / 0 FAIL including the fsplit selftest
- [x] harness deliberate-failure — `--skip-block` implemented in `tests/device_ceiling.py`; size window (±40 B of 516) and error-text checks restored after the false-pass incident

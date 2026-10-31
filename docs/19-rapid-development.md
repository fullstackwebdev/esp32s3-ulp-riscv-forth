# 19 — Rapid development: what is fast, what was slow, and the timings

Written after a session where device probing dominated the clock. Every number here is measured in this tree; the
harness changes are committed and the measurements are reproducible.

## The short version

| lane | cost now | how |
|---|---|---|
| host suite (`tests/run.sh`) | **5.8 s** for 24 checks | already fast; four gcc builds are 0.44 s each |
| `tests/block_boundary.sh` | **0.6 s** | one build + two device-less runs |
| `tests/ceiling_probe.sh` | **0.85 s** | host only |
| device probe command | **20 ms** (was 370 ms) | read until the machine's end-of-line marker instead of sleeping |
| device seeding | **16 ms/block** (was 30 ms) | send everything, parse ONE transcript for acks, retry only what is missing |
| device phase load (8 blocks) | **~0.97 s** | 121 ms/block, of which ~50 ms is the block round trip |

## What was slow, and why

**Fixed sleeps after every command.** Each probe slept 0.25–0.6 s per command and issued hundreds of them. Measured,
20 identical commands: **370 ms/command with a 0.35 s drain, 20 ms reading until `ok`/`?` — 18.6×**. That is the
difference between a 3-minute device run and a 10-second one. This was the single biggest waste in the session.

**Per-block seeding round trips.** A block travels as 256 hex characters, so seeding is **UART-transmit-bound**, not
round-trip-bound: ~30 ms per block is the wire. A first "optimisation" that batched the writes and then re-verified
each block individually was **slower** (54 ms/block) because the verification pass cost more than the round trips it
saved. The correct form — send all lines, drain once, parse the acknowledgements out of that one transcript, retry only
what is missing — is **16 ms/block, 1.9× faster**, verified with `missing=[]`.

**A hard reset per variant, not per command.** ~2 s each. Necessary (a previous variant's SEALed, rewound dictionary
otherwise persists) but it belongs per variant, and it is explicit in `tools/devio.py`, never hidden inside a command.

## A silent limit that was costing runs: interactive lines are 63 bytes

`CMD_SIZE` is 64 in `src/ulp_repl.c` and the console **forwarded a longer line partially**:

```
: BLKBLANK 0 BEGIN DUP 128 < WHILE 32 OVER W + C! 1 + REPEAT DROP ;     (71 chars)
→ echoed as `... 1 + REPEAT DRO`, compiled a definition that never closed, NO error anywhere,
  and every following line was compiled into it instead of being interpreted.
```

That is the same failure class as the lost block tail, and it was silent. It now refuses by name:

```
line too long: 67 bytes, the ring holds 63 - NOT sent
```

**Rules that follow:** an interactive line must be ≤ 63 bytes; anything longer is **seeded into a block** (the `#b`
path has its own 320-byte buffer and is unaffected) and loaded with `N LOAD`. Long definitions were never typeable, and
learning that from a truncation rather than a refusal cost a debugging round.

## Measured timings (device, `tests/device_timing.py`)

```
BLOCK fetch              : n=20 min=49.1 med=50.2 max=50.4 ms
phase load (8 blocks)    : n=50 min=969.5 med=970.7 max=972.4 ms
per block                : 121.3 ms
per char of source       : 1197 us
after 50 cycles          : ' DATABLK -> 794     (pointers still stable)
```

Reading these honestly:

- **~50 ms of each 121 ms block is the mailbox round trip** (`N LOAD` → prompt), so parse + compile + collision check
  is ≈ **70 ms per 128-byte block ≈ 0.55 ms per source character**.
- The earlier estimate of "0.5 s per block" for a switch was **4× pessimistic**; a switch is ~1 s for a whole
  8-block phase, not per block.
- A phase switch costs ~1 s today. Fine for "pick a tool from a menu"; unusable for alternating between two phases in a
  hot loop — which matches the capability statement: tools, not one interwoven program.
- Variance is tiny (max − min = 3 ms over 50 loads), so these are real numbers, not noise.

## The workflow this implies

**Inner loop (seconds).** `tests/run.sh` (host) + `tools/fsplit.py --selftest`. No device, no flashing. This covers
engine changes, chunking rules, and every pure-Forth semantic.

**Probe loop (tens of seconds).** `tools/devio.py`: one reset per variant, prompt-driven commands, batched seeding,
and a `timed()` helper. Do not hand-roll sleeps; the 18.6× is already measured.

**Gate loop (minutes).** `idf.py build` + `flash_safe.sh` + `tests/device_ceiling.py`, only when something is kept.
The flash is the authority on the pool; a refusal is information, not an obstacle.

## Things not to do again

- A fixed `sleep` between a command and its read. Wait for the marker; time out loudly.
- Re-verify a batch per item after already receiving the acknowledgements in one transcript.
- Type a definition longer than 63 bytes at the prompt (it is refused now, which is the point).
- Trust a harness that has never been shown to fail. `tests/device_ceiling.py --skip-block` exists for that.
- Measure a UART round trip and call it the machine's speed: 50 ms of the 121 ms per block is the wire.

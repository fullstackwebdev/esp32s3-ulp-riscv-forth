# P08 — Flash partition, snapshot round trip, PSRAM retention

| | |
| --- | --- |
| Runs on | **board (exclusive)** — overwrites the firmware and **writes to flash**. Get approval first. |
| Time box | **15 min**, one run, hard cap |
| Depends on | P07 (byte server working) |
| Blocks | R7 acceptance, `01-proposal.md` §4.2 rule 4 |
| Serves | R7 (all items), open question Q6 |

## Timebox — 15 minutes, one run, no slices

* **Hard cap: 15 minutes total**, from the first command to the written `RESULT.md`.
* **At T−2 minutes stop starting new work.** Wrap up, write `RESULT.md`, kill processes, kill the tmux
  session.
* **It all has to fit.** A cold ESP-IDF build is 2–3 minutes and a flash ~20 s, so if the probe needs
  a build, start it in the first five minutes — not at minute ten.
* **Every command carries `timeout`**: builds `timeout 300`, device ops `timeout 30`, host test runs
  `timeout 20`. No bare long-running command, no `&`, no `nohup`, no `/tmp`.
* **Every loop is bounded twice**: by iteration count *and* a wall-clock check inside the loop.
* **A hang is a `FAIL`**, with the exact command and the last output recorded.
* **If the question does not fit in 15 minutes, the question is too big.** Report what was measured;
  the orchestrator will cut a narrower question. Running the same probe again is not the answer, and
  splitting a probe into slices is not the answer either.

## Question

1. What do erase and program actually cost for the storage partition, and does sector rotation hold
   up under a realistic write pattern?
2. Can a dictionary snapshot be written and restored so that after a power cycle the dictionary is
   byte-identical?
3. Does PSRAM content survive deep sleep, as assumed in `01-proposal.md` §4.1?

## Why it matters

R7 forbids NVS and makes flash the only system of record. §4.2 rule 4 claims "dirty pages go to PSRAM
immediately, to flash on FLUSH/SAVE, with sector rotation" — but nobody has measured an erase, and no
one has verified that a 4 KB sector rewrite is affordable every time a page is saved. Q6 (PSRAM
retention) also decides whether PSRAM can hold anything that matters.

## Method

1. Project under `probe/results/P08-flash/`, using a **dedicated partition** (add one to the partition
   table; do not touch `nvs` or `factory`).
2. **Timings.** Using `esp_partition_*` (and the raw `esp_flash_*` only if you must to separate erase
   from program), measure 50 iterations each: 4 KB erase, 1 KB program, 512 B program, 512 B read,
   4 KB read. Report min/median/max µs, and note that flash operations may require cache
   disable/IRAM-resident code — record whether the driver handled it and whether Wi-Fi/anything else
   was running.
3. **Snapshot round trip.** Write a 3 KB blob (standing in for a dictionary) with a header
   `{magic, layout_ver, len, fnv1a}`, read it back, compare. Then:
   - **power cycle** the board (`esptool` reset or physical), read it back, compare again;
   - corrupt one byte, verify the checksum rejects it;
   - bump `layout_ver`, verify it is refused;
   - truncate the blob mid-write (abort the write deliberately), verify the old snapshot is still
     readable (copy-on-write / shadow sector) or that the corruption is detected.
4. **Rotation.** 200 iterations of "modify one page, save". Count erases per sector, verify no sector
   exceeds a threshold, and report total erases and elapsed time. If the erase count equals the write
   count, rotation is not working — say so.
5. **PSRAM retention (Q6).** Write a 64 KB pattern to PSRAM, enter deep sleep for 30 s with the ULP
   armed and the timer running, wake, read and compare. Repeat with PSRAM powered down explicitly if
   the API allows. Report "retained / lost", plus whether the failure was total or partial.
6. **Contention.** With the ULP writing to RTC memory continuously, confirm that a flash write does
   not disturb the ULP's state (sanity check for §4.1's claim that the two do not interact).

## Record

| Item | Value |
| --- | --- |
| 4 KB erase / 1 KB program / 512 B program / 512 B read | µs min/median/max |
| snapshot write + verify time for 3 KB | ms |
| restore time | ms |
| power-cycle identity | identical yes/no |
| corrupted header / bumped version | refused yes/no |
| aborted write | old snapshot intact yes/no |
| 200 saves | erases total, max per sector, elapsed s |
| PSRAM after deep sleep | retained / lost / partial |
| ULP state disturbed by flash write | yes/no |

## Pass criteria

* every write is verified by read-back and checksum;
* power-cycle identity holds;
* corrupted and version-mismatched snapshots are refused with a named error (not run);
* an aborted write does not destroy the previous snapshot;
* PSRAM retention answered definitively (retained or lost — no "probably").

## Failure criteria — and what each changes

* **Erase > 100 ms** ⇒ a `SAVE` during a live session will stall the console; §7 must make snapshot
  an explicit blocking operation with a progress indicator, or move it off the interactive path.
* **PSRAM lost on deep sleep** ⇒ PSRAM becomes pure scratch; it may hold page frames but never the
  only copy of anything. `01-proposal.md` §4.1 table already says this — confirm it and delete any
  wording that implies otherwise.
* **Aborted write destroys the previous snapshot** ⇒ the flash layout needs double-buffering with a
  generation counter; add it to §4.2 rule 4 as a requirement, not a nicety.
* **Erase count == write count** ⇒ rotation is not implemented; §4.2 rule 4 is aspirational and must
  say "not yet implemented" rather than describing a mechanism that does not exist.

## Doc deltas to hand back

* `docs/01-proposal.md` §4.2 rule 4 — replace the mechanism description with what was measured and
  what was implemented.
* `docs/01-proposal.md` §4.1 table — PSRAM row: confirmed volatile or not, with evidence.
* `docs/01-proposal.md` §7 — snapshot cost, if it is visible to the user.
* `probe/EVIDENCE.md` — new entry with the timing table.

## Do not

* Do not use the device's NVS partition for anything, not even a test key. R7.
* Do not count "erase" as "write" without reading the driver's behaviour; report what actually hit
  the chip.
* Do not power-cycle by pulling USB if that also removes power from the flash mid-write; use a
  controlled reset and state which method was used.

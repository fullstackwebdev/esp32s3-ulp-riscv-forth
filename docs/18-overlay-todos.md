# 18 — Overlay manager: TODO later

Deferred work for the block-paging / overlay manager, in priority order. Each item states **why it exists** (with the
measurement that motivates it), **what to do**, and **how it is accepted** — a box is only ticked when the acceptance
command or measurement exists in the tree.

## State when this list was written (measured, device)

| fact | value | tier |
|---|---|---|
| device ceiling | **15 phases × 516 B = 7 740 B = 504 %** of the 1 536 B control, stopped by the store | device |
| host ceiling | 18 phases, 9 288 B, 604 % | host |
| per-phase capacity | ~690 B at the prompt (`LATEST HERE -` = 690 on the chip) | device |
| resident toll | 846 B (manager 528 + event loop 318) | device |
| store | 128 blocks × 128 B = 16 KB, in the host core's `.bss` — **volatile** | device |
| pool / stack | 7 845 / 7 856; stack reserve 347 B | device |
| suite | 24 PASS / 0 FAIL (22 tests + `fsplit` selftest + `block_boundary` 2 checks) | host |

**The claim that is NOT yet allowed:** "unbounded". Two things are missing — the store is volatile (a power cycle loses
the program), and it is a hard 16 KB. Size *and* persistence are both required.

---

## T1 — Flash-backed block store on the main core (highest priority)

**Why.** The store lives in the host's `.bss`: every paged program dies at reset. For a ULP — whose whole point is to
survive deep sleep — a program that vanishes is not a deployed program. This is also the only path that removes the
16 KB bound. Costs **zero ULP bytes** (main-core work).

**Do.**
- Use a **raw `esp_partition`**, not NVS. NVS is key-value with per-entry overhead; blocks are fixed 128 B records.
  Reserve a data partition sized to at least 128 × 128 B, ideally 4× that so the store can grow past 16 KB.
- **Erase granularity is 4 KB sectors**, so one block write is read-modify-write of a sector. Cache dirty blocks in
  main-core RAM and write back **in batches aligned to sectors**; write only when a sector is full or on an explicit
  flush. Do not write per `SAVE` — latency and wear both suffer.
- Keep the existing mailbox protocol identical (block number + op + checksum). The ULP must not learn about flash.
- Fail loudly: a partition that is missing, too small, or whose CRC does not match the stored header must abort with a
  named reason, never fall back to a RAM copy silently.

**Accept.** `round trip survives a power cycle`: write all 128 blocks from the ULP, `esptool --after hard_reset`
(or a 10 s deep sleep), then read them back and compare **byte for byte** — 0 mismatches, and the comparison is the
same `C@`-at-known-offsets readback already used for P2b (72/72 today).

**Watch.** Write amplification and sector wear must be *measured*, not assumed: record bytes written per logical
`SAVE` and the number of sector erases over a full 128-block fill.

## T2 — Measure the main-core wake cost per miss

**Why.** Every block miss needs the main core awake. That is at best a light-sleep wake, at worst a deep-sleep reboot.
Battery claims are not allowed before this number exists, and it decides whether phases should be as large as possible.

**Do.** Time (a) light-sleep wake → answer → sleep, and (b) deep-sleep boot → answer. Prefer a counter read from the
ULP side over wall clock; `MS` in this system is a *delay*, not a clock (recorded dead end).

**Accept.** A number in microseconds for both paths, in `CONSTRAINTS.md`, plus the derived "cost per phase switch =
toll + wake" figure. If only a deep-sleep reboot is available, say so plainly — it changes the programming model.

## T3 — Device persistence test in the suite

**Why.** T1's acceptance must be permanent, not a one-off probe.

**Do.** Add a device test (not a host test — persistence is a device property) that writes a known phase, resets,
reloads and runs it, asserting its output. Keep it out of `tests/*.fs` if it needs a reboot cycle; follow the
`known_defects.sh` pattern for probes that are not golden-file comparable.

**Accept.** The test fails before T1 and passes after; it is named in `tests/run.sh`'s device lane or documented as a
manual device gate with the exact commands.

## T4 — Re-measure the ceiling with the flash-backed store

**Why.** 504 % is bounded by 128 blocks. With a real partition the bound moves, and the number must be re-derived
rather than extrapolated.

**Do.** Grow the partition, re-run the escalation (`tests/device_ceiling.py`) and report phases, bytes and the new
stopping reason. Keep the deliberate-failure run (`--skip-block`) as the proof the harness can fail.

**Accept.** A device row in `CONSTRAINTS.md`: phases, bytes, % of control, and the stopping reason. The escalation must
still stop for a *named* reason, never by timing out.

## T5 — Only then use the word "unbounded"

**Why.** Precision. Today the correct sentence is: *"bounded by the block store, not by the coprocessor's RAM"*.

**Accept.** When T1–T4 are done, the claim may become: *"program size is bounded by flash, not by the ULP's 8 KB of
RAM, and the program survives reset"*. Until then, that sentence stays out of the docs and the handoff.

## T6 — Retry the engine-side guard for a line arriving mid-block (with the test pattern rewritten)

**Why.** The guard was written, then withdrawn because it fires on a pattern `tests/overlay_collide.fs` relies on: an
intentional refusal leaves a partially consumed block whose tail the next line deliberately discards. The *class* is
real — a line starting while a block still has code is the corruption that cost six probes — so it should be enforced
once the pattern is expressed differently.

**Do.** Rewrite the collide test so the refused block is abandoned explicitly (blank it or clear the cursor), then
re-land the guard as a **named error** with `tools/fsplit.py` still enforcing the safe-boundary rule.

**Accept.** The collide test passes *and* a new test shows a line submitted with pending block code raising the named
error. Costs a few bytes of `.text`; re-measure the pool and pay from the diagnostic, not from `MEMSZ`.

## T7 — Phase authoring rules (documented, enforced)

**Why.** Two rules were learned the hard way and both cost probes: a block boundary is **not** a line boundary, and a
block may be at most `BLKSZ`. With the loader fixed, blocks may use the full 128 B and a definition may span *passes*,
but a definition must still not straddle a **block** boundary in a driver-loaded phase.

**Do.** Keep `tools/fsplit.py` as the only way phases are chunked (interpret-state cuts, hard refusal when a definition
cannot fit one block). Document the rule in the user guide. Optionally add an automatic splitter that breaks a long
definition into two named words.

**Accept.** `fsplit --selftest` in `tests/run.sh` (already), plus a documented note in the paging chapter.

## T8 — Larger phases vs. fewer misses

**Why.** The toll is fixed at 846 B but the miss cost (T2) is per switch. Bigger phases mean fewer switches and a
larger per-phase dictionary window; the trade must be measured, not guessed.

**Do.** Sweep phase size (window-sized, half, quarter) against switch count and total run time.

**Accept.** A table with the trade-off and a recommended default, both device-measured.

## T9 — Keep the store honest under failure

**Why.** A latched mailbox already costs a reset (`blk_out` latches on a timeout; escape hatch `0 2 BLKXFER`). With
flash underneath there are more ways to fail: a partial sector write, a power loss mid-flush.

**Do.** Define and test: power loss during a batched write-back leaves either the old sector or the new one, never a
hybrid; a checksum mismatch names the block and the reason. Never silently return zeros.

**Accept.** A test that simulates an interrupted flush (write half a sector, reset, read) and asserts a named error or a
consistent old sector.

## T10 — Re-freeze the baselines after each landed item

**Why.** `CONSTRAINTS.md` must stay measured; a bench re-freeze is only legitimate with a documented reason.

**Accept.** Each of T1–T9 that changes a measured number updates `CONSTRAINTS.md`, `docs/15-overlays.md` and the
handoff's tier table in the same commit.

---

## Do not do

- **NVS for blocks.** Key-value overhead and semantics for fixed-size records; use a raw partition.
- **Binary overlays for the REPL image.** Measured as not worth it: it shrinks a non-binding resource (store use
  26 % → 10 %) and does not touch the window. Revisit only for a deployed compiler-less image.
- **Lower `MEMSZ` to pay for code.** That spends application space — the metric being optimised. Pay from `.text`
  instead (see the compiler-removal decision in `docs/16-handoff.md`).
- **Record a gap to get a green suite.** A known behaviour goes in `tools/known_defects.sh` with the *correct* expected
  result, so a fix reports FIXED and the probe is promoted.
- **Trust a harness that has not been shown to fail.** Every new check gets a deliberate-failure run first.

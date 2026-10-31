# P16 — What does one page fetch actually cost, and what period absorbs it?

| | |
| --- | --- |
| Runs on | **board (exclusive)**, ESP32-S3, flashed over `/dev/ttyACM1` (UART0/CH343) |
| Run date | 2025-10-30, 13:30–13:45 box |
| Image flashed | `p16_page_fetch.bin`, sha256 in `image.sha256`, write args in `flash_args` |
| Board state at end | run complete, ULP **stopped**, server task **parked** (`P16 SERVER stopped`), no deep-sleep wake source armed |
| Verdict | **PARTIAL** — A measured (200/200), four failure modes measured; **B and C not measured** (named reasons below) |

## 1. Answers

All numbers are the ULP client's own `rdcycle` deltas around one 512 B request/response, converted
with P05's constants (**122.6 cycles/tick, 6.46 µs/tick** ⇒ 19.0 MHz ULP core). Log: `run5.log`.

| Config | n | median ticks / µs | p95 ticks / µs | max ticks / µs | min ticks / µs |
| --- | --- | --- | --- | --- | --- |
| **A** HP awake, polling the request slot | 200 / 200 ok | **22.35 ticks / 144 µs** (2740 cyc) | 22.84 / 147 (2800) | 23.41 / 151 (2870) | 21.85 / 141 (2679) |
| **B** HP awake, blocked on a ULP signal | **0** | **not measured** — the doorbell never reached the HP: `DOORBELL isr_count=0`, so all 200 fetches hit the client's own timeout | — | — | — |
| **C** HP deep sleep, woken by the ULP, booted | **0** | **not measured** — the deep-sleep wake path is not implemented in this image (`C-STATUS NOT_MEASURED`) | — | — | — |

Raw cycles (A): min 2679, median 2740, mean 2743, p95 2800, max 2870. Spread max/min = 1.07×, so the
distribution is tight: this is a deterministic transport cost, not a jittery one.

**Throughput.** 512 B per 2740-cycle fetch ⇒ **3.55 MB/s median, 3.63 MB/s best** at 200 sequential
fetches (no gap widening between iterations: the 200 fetches took 129 ms wall on the HP side, i.e.
~645 µs each including wakes and the ULP's own loop, which is the HP's view of the same run and is
1.8× the ULP-visible latency plus the HP's polling of the pass flag).

**Largest request.** 512 B — one page, the single `page[512]` buffer in the mailbox (§2 of
`02-harness.md`). The window served is **2048 B (4 × 512, P19)** and the bounds check rejects anything
above `WINDOW_BYTES - PAGE_BYTES = 1536`. No larger request was attempted because there is no larger
buffer to answer into: the mailbox has exactly one page slot. A multi-page request would have to be
pipelined page-by-page at the measured per-page cost.

**The four failure modes** (each deliberate, each with the status the ULP saw — `FAULT` lines):

| Failure mode | Injected how | What the ULP saw | Named, detectable? |
| --- | --- | --- | --- |
| server stopped | server task parked (`fault_inject` bit 1) | `rsp_seq` stayed 0, client hit its own 3 000 000-cycle cap ⇒ `TIMEOUT_NO_ANSWER` (≈158 ms bound) | **yes** — no hang, no zero-fill |
| bad CRC | HP flipped one bit in the reply checksum | reply arrived (`rsp_seq=11`), page checksum mismatch ⇒ `CHECKSUM_REJECTED`, page discarded | **yes** |
| out-of-range address | client asked for `0x100000` (window is 2048 B) | reply arrived (`rsp_seq=12`) with `rsp_status=2` and **no page copied** ⇒ `RANGE_REJECTED` | **yes** — status word, not a silent zero page |
| two requests in flight | client wrote req `seq=1 addr=0`, then req `seq=2 addr=512` before the answer | the answer to `seq=1` arrived carrying **page 1's bytes** (`page_marker=1`, expected 0) ⇒ `TWO_IN_FLIGHT_CORRUPT` | **yes** — corrupts state, and the *only* reason it is detectable is the per-page marker word; the reply checksum matched the wrong bytes perfectly |

**Break-even period.** `page_miss_cycles / 122.6` = 2740 / 122.6 = **22.35 ticks**, so a period that
absorbs one page fetch is **ceil = 23 ticks** (median; 24 ticks if sized on the observed max, 2870
cycles). Adding the wake entry (81 cycles = 0.66) and one trimmed-set dispatch (726 cycles = 5.9) gives
**≈ 30 ticks for a wake that faults once and executes one dispatch** — under §8's 64-tick upper bound,
but *over* its 32-tick lower bound once a 4-token typing slice (23.7 ticks) shares the wake:
23.7 + 22.4 + 6.6 ≈ 53 ticks. So §8 cannot keep "32–64 ticks" unchanged while allowing a fault and a
typing slice in the same wake; see the doc deltas.

**Against P20's estimate.** The host model estimated a page miss at ≈ 18 700 cycles (0.99 ms). Measured
round trip with the HP polling is **2740 cycles (144 µs) — 6.8× cheaper**. Two caveats that keep this a
lower bound rather than a refutation: (a) the test page lives in **internal RAM** (PSRAM is not enabled
in this project's `sdkconfig`, inherited from P06), so a PSRAM cache-miss penalty is not in the number;
(b) the measured body is transport (HP reads 512 B, copies it into RTC slow memory, checksums it) at
3.55 MB/s, which is RTC-bus dominated. The failure threshold in the brief (A > 2 ms) is **not** tripped:
144 µs is 14× under it, so paging stays usable per 512 B and pages do not have to grow to 1 KB.

## 2. Evidence

Everything in `probe/results/P16-page-fetch/`. Commands, in order (all under a 15-minute box, one
board lock, flashing only over `UART0`):

```
# board lock lives in env.sh (flock -n on probe/results/.board.lock, exits 3 if busy)
source ./env.sh && timeout 300 idf.py build           # 3 builds: build.log (fail), build2.log (fail),
                                                      # build3..6.log — see "Bugs found" below
timeout 30 python -m esptool --chip esp32s3 -p /dev/ttyACM1 -b 460800 --before default_reset \
  --after hard_reset write_flash --flash_mode dio --flash_freq 80m --flash_size 2MB \
  0x0 build/bootloader/bootloader.bin 0x8000 build/partition_table/partition-table.bin \
  0x10000 p16_page_fetch.bin                          # flash.log, flash2..5.log
timeout 20 python3 capture_g.py /dev/ttyACM1 run5.log  # pyserial, DTR/RTS held low, sends 'g' at t+1 s
```

Complete output of the run that produced the numbers (`run5.log`, verbatim):

```
[capture] sent 'g' at t+1.01s
P16 GO gate=console
STATS A_poll n=200 ok=200 pass_done=1 pass_ms=129 min_cyc=2679 med_cyc=2740 p95_cyc=2800 max_cyc=2870 mean_cyc=2743
TICKS A_poll min=21851 med=22349 p95=22838 max=23409 mean=22373
US A_poll min=141 med=144 p95=147 max=151 mean=144
BYTES_PER_S A_poll median=3546295 best=3627064
STATS B_blocked n=0 pass_done=1
DOORBELL isr_count=0
FAULT server_stopped case=1 done=1 rsp_seq_seen=0 page_marker=4294967295 status=1 name=TIMEOUT_NO_ANSWER
FAULT bad_crc case=2 done=1 rsp_seq_seen=11 page_marker=4294967295 status=2 name=CHECKSUM_REJECTED
FAULT out_of_range case=3 done=1 rsp_seq_seen=12 page_marker=4294967295 status=3 name=RANGE_REJECTED
FAULT two_in_flight case=4 done=1 rsp_seq_seen=1 page_marker=1 status=5 name=TWO_IN_FLIGHT_CORRUPT
C-STATUS NOT_MEASURED reason=deep-sleep-wake-path-not-implemented-in-this-pass
P16 done
P16 SERVER stopped
[capture] end t+4.03s sent_g=True bytes=876
```

Reproducibility: `run3.log` and `run4.log` are two earlier runs of the same measurement
(A med 2750 / 2751 cycles, B still 0); A reproduces to within 0.4 %. Boot banner of every run:
`P16 BOOT stage=wdt wdt_init=0` → `P16 SETUP doorbell=gpio4 pages=internal-ram` → gate.

**Bugs found and fixed during the box** (each left a `GUARDRAIL` in the source, each was a real
run-ender):

1. `(void *)ulp_page` is the *value* stored at the mapgen symbol (0 at boot), not its address ⇒
   `memcpy(...,512)` on address 0 ⇒ `StoreProhibited`, reboot loop, console alive throughout. Fixed with
   `&ulp_page`. (`run.log` is the crash log, kept as evidence; the board was recovered by re-flashing,
   never by a hands-on reset.)
2. `volatile uint32_t fault_inject` in ULP `.bss` was dropped by `--gc-sections` because the ULP itself
   never reads it ⇒ `ulp_fault_inject undeclared` at build; moved to HP-local state.
3. The `g` gate was 20 s and the capture opened the port after the banner ⇒ the whole box's first run
   spent 20 s waiting. Gate now 8 s and the capture sends `g` at t+1 s whether or not it saw `READY`.
4. Per-fetch timeout in the A/B loops was 158 ms, so a dead doorbell would have cost 200 × 158 ms; it is
   now 200 000 cycles (10.5 ms) per fetch, keeping the phase bounded at ~2 s.

**Why B produced no number (named cause, not a shrug).** The client raises a doorbell by writing the
RTC-IO output registers from the ULP (`RTCIO` base `0xA400` in the ULP window:
`ENABLE_W1TS 0xA410`, `OUT_W1TS 0xA404`, `OUT_W1TC 0xA408`, bit 4 = RTC GPIO4), and the HP blocks on a
`GPIO_INTR_HIGH_LEVEL` interrupt on GPIO4 → binary semaphore → service. Two pad configurations were
tried in two runs:

* pad in its **GPIO mux** (`gpio_config` only): 0 ISR events;
* pad in its **RTC mux** (`rtc_gpio_init` + `RTC_GPIO_MODE_INPUT_ONLY`): 0 ISR events.

So the ULP's RTC-IO write is not reaching the pad-visible level that the HP's digital input sees, in
either muxing. That is a harness question, not a paging question — but it means **B has no number** and
the brief's "all three configurations measured" item is **not met**.

**Why C produced no number.** Configuration C costs a full HP boot per fetch (deep sleep wake → ROM →
bootloader → app) and each boot re-enters `app_main`; the ULP would have to trigger the wake
(`RTCCNTL` GPIO wake / ext0), stay powered through deep sleep, and the HP would have to find the pending
request in RTC memory after boot. That is a second staged image and its own 15-minute box, and P06's
precedent is explicit that mixing a new wake path into a boot that still has measurements to capture
loses the run. The image therefore prints `C-STATUS NOT_MEASURED` rather than a guessed number.

## 3. Verdict

**PARTIAL.**

* Pass criteria met: A measured with a full distribution; **every failure mode produced a named,
  detectable outcome on the ULP** (no hang, no silent zero-fill); the break-even period computed and
  compared against §8's 32–64 tick claim.
* Pass criteria **not** met: B (awake, blocked) and C (deep sleep, woken) have no numbers. The B path is
  a doorbell-plumbing failure with two configurations tried and `isr_count=0` both times; C was never
  attempted in-image.
* Failure criteria: **none tripped.** A = 144 µs is 14× under the 2 ms line, so pages stay 512 B and
  faults do not have to batch. C > 100 ms is **undetermined** — that is the open question, and it is the
  one that would remove paging from autonomous mode.
* Two-in-flight requests **do** corrupt state: the seq-1 answer for page 0 carried page 1's bytes, and
  its checksum was self-consistent (correct over the wrong bytes). The single-outstanding rule is
  therefore not a style choice; it is required (doc delta below).

## 4. Doc deltas

**`docs/01-proposal.md` §8 (the paragraph that ends "…the connected period stays at 32–64 ticks.")**

old (last two sentences of that paragraph):
> But the number that now dominates everything is the
> **page miss: ≈ 18 700 cycles ≈ 0.99 ms, 26× a dispatch.** Paging policy, not instruction choice, sets
> the period: resident code types at 153 µs/frame, and one cold page costs 1 ms on top. Until page faults
> are measured on the chip (P16) the connected period stays at 32–64 ticks.

new:
> But the number that dominates a wake that faults is the **page fetch, now measured (P16): 2740 cycles
> median, p95 2800, max 2870 — 22.4 ticks ≈ 144 µs, 3.8× a dispatch** — a 512 B request/response round
> trip with the main core awake and polling, over the mailbox's single page buffer, answering from
> internal RAM at **3.55 MB/s**. The host model's 18 700-cycle estimate (P20) was **6.8× too high**
> because it priced the fetch as a byte-wise load chain rather than one bulk copy plus one checksum. Two
> bounds apply: the page sits in internal RAM in that build (PSRAM was not enabled), so a PSRAM miss is
> not in the number; and the cost of the same fetch with the main core blocked (B) or deep-slept (C) is
> **not measured**. Break-even for one fetch alone is **23 ticks**; a wake that faults once *and*
> executes one dispatch costs ≈30 ticks, and one that also runs a 4-token typing slice costs ≈53 ticks —
> so the connected period is **64 ticks when a fault may land in the same wake as a typing slice, 32
> ticks only for wakes that cannot fault** (faults batch to one per wake).

**`docs/01-proposal.md` §4.2 rule 3 (append to the sentence ending "the cycle fits.")**

old:
> Hence **4 × 256 B** (§4.3): same RAM, four slots, the cycle fits.

new:
> Hence **4 × 256 B** (§4.3): same RAM, four slots, the cycle fits. The retry's *cost* is now measured
> too (P16): one 512 B page fetch is **22.4 ticks ≈ 144 µs** with the main core polling the mailbox
> (p95 22.8, max 23.4), so a three-address livelock cycle is ~67 ticks of pure transport per dispatch if
> the loop is not broken — which is why the progress bound above is a hard abort and not a counter.

**`docs/02-harness.md` §2 (mailbox struct and rules)**

old (field line):
>     volatile uint16_t rsp_crc;

new:
>     volatile uint16_t rsp_crc;
>     volatile uint32_t host_alive;   /* HP increments every time it drains the request slot.
>                                        A server that is *stopped* cannot write rsp_status, so
>                                        "no server" is a timeout on req_seq, never ERR_NO_SERVER
>                                        (P16: server stopped ⇒ ULP saw req_seq=0 frozen). */

old (last rule bullet, ending "…rather than corrupting."):
> * Cross-core mutual exclusion uses the IDF Peterson lock (`ulp_riscv_lock_acquire/release`) around
>   any multi-field update, and **only one host task may touch the mailbox** (the doc is explicit that
>   the lock is not safe from multiple host threads). A re-entrancy guard in the bridge fails loudly
>   rather than corrupting.

new: (same bullet, plus two)
> * Cross-core mutual exclusion uses the IDF Peterson lock (`ulp_riscv_lock_acquire/release`) around
>   any multi-field update, and **only one host task may touch the mailbox** (the doc is explicit that
>   the lock is not safe from multiple host threads). A re-entrancy guard in the bridge fails loudly
>   rather than corrupting.
> * **One outstanding request, enforced by the ULP, not by convention.** Measured (P16): writing
>   `req_seq=1 addr=0` and then `req_seq=2 addr=512` before the first answer is consumed returns an
>   answer tagged `seq=1` that carries **page 1's bytes**, and its checksum is valid over the wrong
>   bytes — the corruption is invisible to CRC. The ULP therefore never issues `req_seq+1` while
>   `rsp_seq != req_seq`; a second request is a local `ERR_REQ_BUSY`, and the server re-reads `req_seq`
>   once per iteration.
> * Every wait on `rsp_seq` has its own cycle bound on the ULP side (**3 000 000 cycles ≈ 158 ms** in
>   P16's client, 200 000 cycles ≈ 10.5 ms per fetch in the timed loop) that publishes
>   `ERR_NO_SERVER`; nothing in the protocol may wait unbounded on the HP, because a stopped server
>   cannot report that it is stopped.

**`docs/01-proposal.md` §10 R6 (three bullets restated with measured outcomes)**

old:
> - [ ] Stopping the server task (deliberately) makes the next paged access fail with
>       `ERR_NO_SERVER` within a bounded retry count — not a hang and not a zero-filled page.

new:
> - [x] Stopping the server task (deliberately) makes the next paged access fail **with the ULP's own
>       cycle bound** (measured, P16: the reply never came, `req_seq`/`rsp_seq` frozen, status
>       `TIMEOUT_NO_ANSWER` after 3 000 000 cycles ≈ 158 ms) — not a hang, not a zero-filled page. Note
>       the name: a stopped server cannot write `ERR_NO_SERVER`, so the error is published by the
>       *client's* timeout, and `02-harness.md` §2 now carries a `host_alive` heartbeat for it.

old:
> - [ ] A CRC mismatch on a page reply is reported as `ERR_CRC` and the page is discarded, not used.

new:
> - [x] A CRC mismatch on a page reply is reported as `ERR_CRC` and the page is discarded, not used
>       (measured, P16: one flipped checksum bit ⇒ `CHECKSUM_REJECTED`, page discarded, no retry of the
>       bad bytes).
>
> - [ ] **A second request while one is in flight is refused locally** (not measured as a feature yet,
>       measured as a *hazard*, P16: two outstanding requests made the `seq=1` answer carry page 1's
>       bytes with a valid checksum ⇒ `TWO_IN_FLIGHT_CORRUPT`). Acceptance is `ERR_REQ_BUSY` with no
>       state change on the server side.

## 5. Follow-ups

* **What does a page fetch cost with the main core blocked (B)?** The two runs here produced
  `isr_count=0`: a ULP write to `RTCIO OUT_W1TS/ENABLE_W1TS` (bit 4) did not appear as a level on GPIO4
  in either the GPIO mux or the RTC mux, so the HP's level interrupt never fired. Which pad/mux
  configuration lets an RTC-IO write from the ULP be seen by the HP's digital GPIO interrupt (or should
  the signal be an `esp_ipc`/RTC interrupt instead)? Needed to price the difference between polling and
  interrupt-driven service.
* **What does a page fetch cost from deep sleep (C), and is it under the 100 ms usability line?**
  Requires the ULP-triggered HP wake path, RTC-memory-persisted request, and one fetch per boot; it needs
  its own staged image and box, and it decides whether autonomous mode keeps paging at all.
* **Does the 2740-cycle figure survive PSRAM?** The test page was in internal RAM. Enabling Octal PSRAM
  and repeating A adds a cache-miss term the host model assumed — the gap between 2740 cycles and P20's
  18 700 is where that term would live.
* **What is the largest request the mailbox can carry?** 512 B was not challenged because there is one
  page slot. A 1 KB or 2 KB request would need a second buffer; its cost should be measured before §8
  assumes a 1 KB page doubles throughput.

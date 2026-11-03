# Docs index

Every document in `docs/`, newest work at the bottom. Generated from each file's own title so the index cannot
drift from the files it lists.

| doc | title | size |
| --- | --- | --- |
| [`00-background.md`](00-background.md) | 00 — Background: what the hardware actually is | 14 KB |
| [`01-proposal.md`](01-proposal.md) | 01 — Proposal: an interpretive Forth OS on the ESP32-S3 ULP | 59 KB |
| [`02-harness.md`](02-harness.md) | 02 — The harness: how we talk to the ULP without JTAG | 15 KB |
| [`03-prototype-review.md`](03-prototype-review.md) | 03 — Review of the reference prototype (`uforth.c`) | 13 KB |
| [`06-repl.md`](06-repl.md) | 06 — The command-line REPL (requirement R8) | 10 KB |
| [`07-status.md`](07-status.md) | 07 — Status report | 11 KB |
| [`08-psion.md`](08-psion.md) | 08 — Sprint: the Psion-class device | 14 KB |
| [`09-display-wiring.md`](09-display-wiring.md) | 09 — Wiring the 1602A character LCD to the ESP32-S3 | 7 KB |
| [`10-references.md`](10-references.md) | 10 — Reference material: what we actually hold, and what it is good for | 5 KB |
| [`11-findings.md`](11-findings.md) | 11 — Findings register | 78 KB |
| [`12-what-opens-up.md`](12-what-opens-up.md) | 12 — What the unverified wins would actually unlock | 6 KB |
| [`13-levers.md`](13-levers.md) | 13 — The levers, measured | 18 KB |
| [`14-probe-rules.md`](14-probe-rules.md) | 14 — Probe rules | 24 KB |
| [`15-overlays.md`](15-overlays.md) | 15 — Overlays: what the friend's plan got right, and what the code says | 65 KB |
| [`15-super-optimization.md`](15-super-optimization.md) | 15 — Super-optimization for application space: everything on the table | 14 KB |
| [`16-handoff.md`](16-handoff.md) | 16 — Handoff letter: esp32-rv32, the ULP Forth machine | 19 KB |
| [`17-checklist.md`](17-checklist.md) | 17 — Probe checklist | 4 KB |
| [`17-predictions.md`](17-predictions.md) | 17 — Prediction ledger | 9 KB |
| [`17-probe-plan.md`](17-probe-plan.md) | 17 — Probe plan: the 7-block phase (v2) | 9 KB |
| [`18-overlay-todos.md`](18-overlay-todos.md) | 18 — Overlay manager: TODO later | 10 KB |
| [`19-rapid-development.md`](19-rapid-development.md) | 19 — Rapid development: what is fast, what was slow, and the timings | 4 KB |
| [`20-strategy.md`](20-strategy.md) | 20 — Strategy | 40 KB |
| [`21-checkpoint.md`](21-checkpoint.md) | 21 — Checkpoint: paging capabilities, before flash-backed storage | 4 KB |
| [`22-flash-store.md`](22-flash-store.md) | 22 — Flash-backed block store: outline, then implementation | 20 KB |
| [`23-memory-reclaim.md`](23-memory-reclaim.md) | 23 — Reclaiming ULP memory (branch `reclaim-app-space`) | 6 KB |
| [`24-dispatch.md`](24-dispatch.md) | 24 — The asm dispatcher: what must not change, and the gate that proves it | 10 KB |
| [`25-program-library.md`](25-program-library.md) | 25 — A program library: resident launcher + behaviour images | 21 KB |
| [`26-app-store.md`](26-app-store.md) | 26 — The App Store: a shelf of always-on apps on a 1.2 KB window | 24 KB |
| [`27-spi-lora.md`](27-spi-lora.md) | 27 — External SPI memory and LoRa on the ULP-RISC-V: research notes | 9 KB |
| [`28-sx126x-ulp.md`](28-sx126x-ulp.md) | 28 — SX126x on the ULP-RISC-V, and whether it can be Forth | 34 KB |
| [`29-lora-measurements.md`](29-lora-measurements.md) | 29 — LoRa on the ULP-RISC-V: every measured number, one place | 12 KB |
| [`30-budget-ledger.md`](30-budget-ledger.md) | Budget ledger — what the 7 932 B wall costs, and what is left | 13 KB |
| [`30-forth-lora-driver.md`](30-forth-lora-driver.md) | 30 — The SX1262 driver, written in Forth | 55 KB |
| [`31-meshtastic-fit.md`](31-meshtastic-fit.md) | Does the Meshtastic stack fit? — measured against this machine's budget | 62 KB |
| [`32-handoff-meshtastic-interop.md`](32-handoff-meshtastic-interop.md) | Handoff — Meshtastic interoperability for the ULP-RISC-V Forth LoRa stack | 23 KB |
| [`JOURNAL.md`](JOURNAL.md) | JOURNAL — everything tried, learned and rejected | 187 KB |
| [`USER-MANUAL.md`](USER-MANUAL.md) | The 8 KB Computer — a user manual | 13 KB |

Reading order for someone new:

1. `00-background.md` → `01-proposal.md` (what was attempted and why).
2. `11-findings.md` + `14-probe-rules.md` (what is measured, and the rules that keep measurements honest).
3. `27-spi-lora.md` → `31-meshtastic-fit.md` (the radio work, ending in the Meshtastic wire facts, Appendix N).
4. `32-handoff-meshtastic-interop.md` (exact state at handoff: what works, what does not, every experiment run).

`JOURNAL.md` is the append-only lab notebook; `USER-MANUAL.md` is how to drive the machine.

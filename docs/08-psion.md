# 08 — Sprint: the Psion-class device

> **SCOPE CANCELLED 2026-10-30 by the operator.** All display work is dropped — breadboard 1602A leg and
> integrated-panel leg both. This document is kept as the record of *what a display would have cost* (32–160 B of
> screen memory, a character-cell driver, 552–620 B of app space, one app at a time) and of the hardware lessons in
> J-51/J-54. Nothing here is active. The live plan is `01-proposal.md` plus the open gates in `JOURNAL.md`.

**Status:** cancelled — plan only, and no longer the plan. Nothing in this document has run on the chip yet.
**Basis:** every budget figure below is measured (P01–P35, `probe/EVIDENCE.md`); every estimate is marked.
**Gates:** two open bugs block the start (P36 overlays, P37 block-wrapper hang). Nothing here may begin until
they report.

---

## 1. What the device is

An 8 KB Forth machine that behaves like a 1980s pocket computer: a character display, a keyboard, a shell with
small apps, documents held in flash blocks, and a serial console for when you want to program it.

It is not a phone. It is the class of machine that ran a diary, a word processor and a calculator on 8 KB of RAM
— Psion Organiser, TRS-80 Model 100, Cambridge Z88. The difference is that this one is a **coprocessor**: the
main ESP32 cores sleep, and the device keeps running.

**The one-sentence target:** pick it up, press a key, see the screen update within one wake, write a note, save
it to flash, put it down for an hour, pick it up and find the note still on screen — with the main cores asleep
the entire time.

---

## 2. Why this shape and not a touchscreen app platform

Measured, not a preference:

| Display | Screen memory | Full refresh from the ULP |
| --- | --- | --- |
| **40 × 4 characters** | **160 B** | ~6–16 ms (estimate; 4-bit bus, 160 chars × 40–100 µs) |
| 128 × 64 mono pixels | 1 024 B | ~1.3 GB of framebuffer *does not fit*: 1 KB is half the pool |
| 240 × 320 pixels | 9 600 B | **larger than the entire machine** |

A pixel framebuffer cannot exist here, and an ASCII font alone is 768 B — most of the app space. So the device
gets a **character display**, which is exactly what its ancestors had, for exactly this reason.

Touch is possible (RTC I2C on GPIO 1–3, or the SAR ADC for resistive) but it buys "tap a row" at ~150 B of
driver and a pin conflict with the boot strap. **Buttons and a rotary encoder are the correct input for this
class of machine** and cost almost nothing.

---

## 3. Hardware specification

| Item | Specification | Rationale |
| --- | --- | --- |
| MCU | ESP32-S3 (already owned), ULP RISC-V coprocessor | 8176 B RTC RAM, 19 MHz, measured |
| Display | **40 × 4 character LCD, HD44780-compatible, 4-bit parallel** — bring-up on a **16 × 2 (1602A)** | 160 cells = 160 B screen memory; 6 GPIO; cheap. The 1602A is 32 cells and a strict subset — wiring, power and the init sequence are in [`09-display-wiring.md`](09-display-wiring.md) |
| Display pins | RS GPIO1, E GPIO2, D4 GPIO4, D5 GPIO5, D6 GPIO6, D7 GPIO7 | all RTC-capable, none forbidden |
| Backlight | GPIO14 via transistor | one pin, PWM later if desired |
| Keys | **6** — Up, Down, Left, Right, Select, Back — active low, pull-ups | 6 GPIO: 8, 9, 10, 11, 12, 13 |
| Encoder (optional) | 2 pins + push, alternative to Up/Down | for menu-heavy use |
| Console | UART0 via the CH343 bridge, `/dev/ttyACM1`, 115200 | also the flashing and recovery port |
| Storage | flash blocks through the main cores, 512 B each, ≥ 1 MB reserved | 144 µs per fetch, measured |
| Power | ULP awake, HP asleep; **not specified this sprint** | needs a meter; a probe, not a guess |

**Forbidden pins, in writing:** GPIO19/20 (native USB D±), 26–37 (flash/PSRAM), 43/44 (UART0), 0/3/45/46
(strapping). Driving any of them has cost hours on this project already.

**Block layout:** block 0 = directory; blocks 1+ = documents, app source, and app overlays. A block is 512 B;
the device reserves at least 1 MB (2 048 blocks) even though only the directory and a handful of documents are
in use.

---

## 4. The measured machine it has to fit in

All figures measured; sources in `probe/EVIDENCE.md`.

| Line | Bytes | Note |
| --- | --- | --- |
| Engine (interpreter, 49 primitives, `vm_switch`, block transfer) | **4 096** | P33/P34 |
| Forth memory `MEMSZ` | **2 196** | P35, links; 1 880 if the C stack is honoured in the pool |
| └ block buffer (inside `MEMSZ`) | 512 | P33 |
| └ prelude (headerless, 16-bit tokens) | 676 | P28 |
| └ block words (`BLOCK`/`UPDATE`/`SAVE`) | 456 | P33 |
| **└ left for applications** | **552** (236 conservative) | P33/P35 |
| Task state, 3 × 140 | 420 | P27 |
| Rings + mailbox + line buffer | 600 | P04/P10 |
| C stack + guard | 320 | P21 |

Timing: RTC tick **6.46 µs**, period floor **22 ticks (142 µs)**, dispatch **726 cycles ≈ 38 µs**, block fetch
**144 µs**, key-to-event **≤ one period** (measured uniform, P18), display refresh **≤ 20 ms** (estimate, to be
measured).

**Consequences that shape the product, stated plainly:**

* The application code space is **552 B** — about 20 words. Therefore the **shell and editor core must be
  resident and shared**, and apps beyond the first must be **overlays** (P36) or not exist.
* Block fetches are cheap enough to be synchronous inside a wake, so `SAVE` can be a blocking word with a named
  timeout rather than a state machine.
* Events are **coalesced to one per key per wake**, so the input driver must treat a key as "state", not as a
  stream of presses: holding a key produces one event per wake, which is what key-repeat needs anyway.

---

## 5. Requirements

Numbered **D1–D12** to keep them clear of the platform requirements R1–R8. Each is a behaviour, not an
implementation. All are unchecked.

### Functional

| # | Requirement |
| --- | --- |
| **D1** | **Display.** An HD44780-compatible character LCD driven entirely by the ULP through 6 GPIO, with `EMIT`, `CR`, `CLS`, `AT ( row col -- )`. Bring-up panel is a **1602A: 16 × 2 = 32 cells**; the target is 40 × 4 = 160 cells and the same driver serves both. A full refresh completes in ≤ 20 ms. **Note:** line 2 of a 1602A starts at DDRAM `0x40`, not `0x10`. |
| **D2** | **Input.** Six keys, debounced, each producing exactly one event per wake; held keys repeat at one event per wake. No key event is ever lost while the device is idle. |
| **D3** | **Shell.** A list of installed apps; Up/Down to move, Select to launch, Back to return. The shell is resident. |
| **D4** | **Shared editor core.** Insert, delete, cursor left/right/up/down, line wrap at 40 columns, and a status line showing position. Used by every text app; resident. |
| **D5** | **Notes.** Create, edit and save a text document to a block range; open an existing one. At least 8 documents addressable. |
| **D6** | **Todo.** Add, toggle done, delete, and scroll a list; persisted to a block. At least 64 items. |
| **D7** | **Calculator.** + − × ÷ over signed 32-bit integers, single-line input with the answer on the next line. |
| **D8** | **Storage.** `SAVE` writes through to flash and reports success; a power cut during a save leaves the previous version intact (double-buffered block or a generation counter). No silent data loss, ever. |
| **D9** | **Console.** `ulpctl`/`picocom` attaches over UART0, gets a prompt, can `LIST` a block, `EDIT` a block as text, and `SAVE` it. |
| **D10** | **Continuity.** Put the device down mid-app and return: the app state and screen are as left. RTC RAM is retained across deep sleep; verify it, do not assume it. |
| **D11** | **Named failures.** Every error — no server, bad checksum, full block, unknown app, key log overflow — appears on the display as a short `ERR_*` string and a status bit. Nothing fails silently, and nothing displays a stale value. |
| **D12** | **It fits.** The linked image is ≤ 7 856 B with **one application** resident. Overlays are **out of v1** (P36: loader 1 400 B against 620 B of app space). A second app requires finding app space first — see §10. |

### Non-functional

| # | Requirement |
| --- | --- |
| **D13** | A keystroke to screen change is ≤ one wake period + 20 ms, measured. |
| **D14** | No unbounded wait anywhere: every blocking word has a bounded retry with a named error. |
| **D15** | The device boots to the shell within 2 s of power-on, or reports the reason it cannot. |
| **D16** | Every requirement above is verified by an executed test, recorded in `probe/EVIDENCE.md`; no box is ticked from inspection. |

---

## 6. Application model

**Revised by G0 (P36, failed): there are no overlays in v1.**

```
resident:  engine · prelude · ONE application · block words · display driver · key driver
data:      blocks; one 512 B buffer, explicit BLOCK/UPDATE/SAVE
```

The overlay mechanism itself was proven — compile into the buffer, save, clear, reload, execute, and the reloaded
copy calls resident words correctly — but the **loader, directory and error strings cost 1 400 B resident**, and
the machine has **620 B** of app space. A loader that does not fit cannot manage apps that do not fit.

So the device ships **one application at a time**, and the "shell" is either a menu inside that application or
does not exist. The apps that were going to be overlays (Todo, Calculator) are **deferred until app space is
found**, and §10 names the levers that would find it.

---

## 7. Milestones and gates

| Gate | What | Blocks | Status |
| --- | --- | --- | --- |
| **G0** | P36 overlays | **FAILED** — mechanism works, loader costs 1 400 B against 620 B of app space. Overlays out of v1; one app at a time | done |
| **G1** | P37: why the Forth `BLOCK`/`SAVE` wrapper hangs — harness or real bug | D5, D6, D8, D9 | not started |
| **G2** | Port the engine to the ULP and boot to a prompt on the chip | everything below | not started |
| **G3** | Display driver + `CLS`/`AT`/`EMIT` on real hardware, 20 ms refresh measured | D1 | not started |
| **G4** | Key driver, one event per wake, repeat measured | D2 | not started |
| **G5** | Shell + editor core resident, measured bytes | D3, D4, D12 | not started |
| **G6** | Notes and Todo on blocks, with power-cut safety | D5, D6, D8 | not started |
| **G7** | Console: `LIST`, `EDIT`, `SAVE` a block | D9 | not started |
| **G8** | Continuity across deep sleep, and the named-failure sweep | D10, D11 | not started |

Nothing starts before G0 and G1 report. G2 is the first thing that runs on the chip; G0–G1 are host-only.

---

## 8. Scope

**In scope:** the device above, on the ESP32-S3 already owned, with a character display and six keys.

**Out of scope for this sprint, and not to be smuggled in:** pixel graphics, touch, Wi-Fi, Bluetooth, audio,
floating point, a filesystem with names and directories, multi-tasking beyond three tasks, power measurement,
and any claim about battery life.

**Explicitly deferred, but not lost:** transparent paging (P34 priced it at 888 B of dictionary — 88 % of the app
space), full word-processor formatting, and any display larger than 40 × 4.

---

## 9. Acceptance checklist

Unchecked. Each item is executable and each names its failure.

### Display and input
- [ ] `CLS` then four lines of 40 characters: all 160 cells correct, measured **≤ 20 ms**, timing recorded.
- [ ] `AT 2 10 EMIT` places the character at row 2, column 10 and nowhere else.
- [ ] Each of the six keys produces **exactly one** event per press; holding a key produces one event per wake
      (measured over 100 wakes, no duplicates, no losses).
- [ ] A key pressed while the display is mid-refresh is not lost.

### Shell, editor, apps
- [ ] The shell lists ≥ 3 apps and launches each; Back returns to the shell with the app's state discarded
      cleanly.
- [ ] The editor handles a 160-character document: insert, delete, cursor over all four directions, wrap at 40.
- [ ] Notes: create, save, power-cycle, reopen — content identical (checksum recorded).
- [ ] Todo: 64 items, toggle, delete, persist, reload — identical.
- [ ] Calculator: `7 3 −` and `7 3 ÷` and `0 ÷` (named error, not a trap) all correct.

### Storage and failure
- [ ] `SAVE` reports success; a deliberately aborted save leaves the **previous** version readable.
- [ ] No server: `BLOCK` fails with `ERR_NO_SERVER` on screen, never a zero-filled buffer.
- [ ] Bad checksum: `ERR_CRC`, block discarded, previous buffer contents unchanged.
- [ ] Block out of range: `ERR_RANGE`, nothing written.
- [ ] An overlay calling another overlay is refused with `ERR_SEG_UNRESIDENT`.

### Console
- [ ] `picocom` gives a prompt; `LIST` prints a block as 4 lines of 40; `EDIT` + typed text + `SAVE` round-trips.

### Continuity and boot
- [ ] Deep sleep 60 s and wake: app state and screen contents as left, checksum equal.
- [ ] Boot to shell ≤ 2 s, measured over 10 boots.
- [ ] Every error string above is reachable and was executed at least once.

---

## 10. Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| **Overlays do not work (G0)** | the app model collapses to one app in 552 B | then the sprint ships **one** app (Notes) plus a calculator, and says so |
| **The wrapper hang is real (G1)** | block-backed documents are impossible | fall back to explicit `F@`/`F!` at 202 B, or fix the branch bug |
| **620 B is not enough for shell + editor + app** | it is not: one app at a time is the honest model | D3 (shell) becomes a menu inside the app, or is dropped |
| **App space is 620 B, not 1 008 B** | every earlier per-app estimate is 40 % optimistic | the levers, with measured values: drop from 3 tasks to 1 (**+280 B**), shrink the block layer from 900 B toward P33's 456 B (**+444**), move the `ERR_*` strings into a block (**~100**) |
| **Key events coalesce to one per wake** | fast typing loses presses | repeat-at-wake-rate is the design; if it feels wrong, add a key FIFO in the dictionary (≈ 40 B) |
| **Display refresh slower than 20 ms** | the UI feels like a fax | characters are addressed individually; refresh only the changed rows |
| **The chip wedges again** | hours lost, as before | watchdog first, UART0 flashing, staged start behind a console key — all mandatory |

---

## 11. What this sprint does not promise

It does not promise a battery life figure, a touchscreen, or that three apps fit. It promises a **measured,
named** outcome: either a device that holds a note across a power cut and shows it on a character display with
the main cores asleep, or a report saying exactly which requirement fell and what it would cost to get it back.

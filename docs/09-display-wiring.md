# 09 — Wiring the 1602A character LCD to the ESP32-S3

For bring-up. The 1602A is a 16 × 2 HD44780-compatible module: **32 characters**, arranged as two lines of 16.
Our sprint spec says 40 × 4 as the target; 16 × 2 is a strict subset and is the right thing to prove the wiring
with (it costs 32 B of screen memory instead of 160 B).

---

## 1. First: which 1602A do you have?

Look at the back.

| If it has… | Then |
| --- | --- |
| **16 pins in a row** (VSS, VDD, V0, RS, RW, E, D0–D7, A, K) | bare parallel module — **this document** |
| **4 pins** (GND, VCC, SDA, SCL) on a small board soldered on the back | it has a PCF8574 I²C backpack — different wiring, see §7 |

Both are "1602A". The 16-pin one is what the rest of this assumes.

---

## 2. Power: what, where, and whether the ESP32-S3 can do it

**Yes, the ESP32-S3 can power it** — from the **5 V pin** (VBUS, which is USB 5 V), not from 3V3.

| LCD pin | Name | Connect to | Notes |
| --- | --- | --- | --- |
| 1 | **VSS** | **GND** | ground, first pin on the left |
| 2 | **VDD** | **5 V** (devkit `5V`/`VBUS` pin) | this is the module's power |
| 3 | **V0** | **pot wiper** (10 kΩ between 5 V and GND) | **contrast — see §4, this is the #1 blank-screen cause** |
| 15 | **A** (LED+) | **5 V through a 220 Ω resistor** | backlight anode |
| 16 | **K** (LED−) | **GND** | backlight cathode |

Current: logic draws 1–2 mA; the backlight ~15–25 mA through 220 Ω. USB supplies 500 mA, so this is nothing.

**Do not** power VDD from 3V3 if you can avoid it. The module's contrast circuit is built for 5 V; at 3.3 V many
units show nothing legible. (If you *only* have 3.3 V, it often works with V0 tied to GND — dim but usable. Try it
only after 5 V is ruled out.)

---

## 3. The signal wiring (4-bit mode, write-only)

Seven wires, and two of them are not what people expect.

| LCD pin | Name | ESP32-S3 GPIO | Why |
| --- | --- | --- | --- |
| 4 | **RS** | **GPIO1** | register select: 0 = command, 1 = character |
| 5 | **RW** | **GND** (not a GPIO!) | read/write. Tied low = write-only, and **this is what protects the ESP32** |
| 6 | **E** | **GPIO2** | enable strobe, pulsed per nibble |
| 11 | **D4** | **GPIO4** | data 4 — high nibble first |
| 12 | **D5** | **GPIO5** | data 5 |
| 13 | **D6** | **GPIO6** | data 6 |
| 14 | **D7** | **GPIO7** | data 7 |
| 7–10 | **D0–D3** | **leave unconnected** | 4-bit mode does not use them |

**RW must go to GND.** Two reasons, and the second one costs hardware:

1. Write-only is all we need — the module never has to tell us anything.
2. The module runs at **5 V**. If RW is tied to +5 V (read mode), the HD44780 drives D4–D7 as **outputs at 5 V**
   into ESP32 pins that are only 3.3 V tolerant. That is how you kill a GPIO. With RW grounded, the data pins are
   inputs on the LCD side and **no 5 V ever reaches the ESP32**.

The ESP32 driving 3.3 V *into* a 5 V HD44780 is fine: its VIH is 2.2 V, so 3.3 V is comfortably a logic high.

### Pins to avoid, on this board, forever

GPIO19/20 (native USB D±), GPIO26–37 (flash and PSRAM), GPIO43/44 (UART0), GPIO0/3/45/46 (strapping).
Writing to any of these has already cost this project hours and one wedged board.

---

## 4. The three things that go wrong

| Symptom | Cause | Fix |
| --- | --- | --- |
| **Blank screen, backlight on** | contrast | turn the V0 pot slowly; if you have no pot, put a 1–2 kΩ resistor from V0 to GND and accept a fixed contrast |
| **One row of solid blocks** | the module has power but was never initialised | the init sequence did not run (§5) |
| **Garbage or half-characters** | a D4–D7 wire is wrong or on the wrong pin | check nibble order: D4 is the *high* nibble |
| **Nothing at all, no backlight** | A/K reversed or the resistor omitted | A = anode to +5 V via 220 Ω, K = cathode to GND |

Put the **contrast pot on first and adjust it before writing any code** — with 5 V on VDD and V0 floating, a
working module shows a blank screen and looks dead.

---

## 5. The init sequence (4-bit, write-only)

Because RW is grounded there is no busy flag to poll, so use delays: **2 ms** after clear/home, **50 µs** after
anything else. Each byte is sent as two nibbles, high first, each strobed with E.

```
power on, wait 50 ms
send 0x3   (as a nibble, three times, with 5 ms / 1 ms / 1 ms waits)   -> forces 8-bit state
send 0x2   (once)                                                     -> switch to 4-bit
send 0x28  (function set: 4-bit, 2 lines, 5x8 font)   delay 50 us
send 0x0C  (display on, cursor off)                    delay 50 us
send 0x06  (entry mode: increment, no shift)           delay 50 us
send 0x01  (clear)                                     delay 2 ms
```

To write a character: RS = 1, send the byte as two nibbles, delay 50 µs. To send a command: RS = 0, same.
To put the cursor somewhere: RS = 0, command `0x80 | address`.

**The address map is not linear.** Line 1 is DDRAM `0x00–0x0F`; line 2 is `0x40–0x4F`. So row 2 column 0 is
`0x40`, not `0x10`. Getting this wrong is the classic "second line prints in the middle of the first".

---

## 6. Bring-up order — prove the hardware before the Forth

1. **Power only.** 5 V, GND, contrast pot, backlight via 220 Ω. Adjust until you can see the top row of blocks.
   Do not connect any signal pins yet.
2. **Wire RS/E/D4–D7, RW to GND.** No code.
3. **Prove it with the main core first.** The ESP32-S3's two big cores are the right tool for this one step,
   because a wiring fault and a driver bug look identical otherwise: a 20-line Arduino/IDF sketch that clears the
   screen and prints `hello` settles the question in a minute.
4. **Only then move the driver to the ULP.** The ULP writes GPIO through primitives and runs from RTC RAM at
   19 MHz; every failure there has two possible causes, and you want the hardware already eliminated.
5. Record the timing you actually get: `CLS` + two lines of 16 characters. The sprint's requirement is ≤ 20 ms
   for a full refresh; 32 characters × ~50 µs ≈ 2 ms, so there is plenty of headroom for the ULP.

**Do not** start on the ULP. Debugging the 4-bit protocol and the coprocessor's memory map at the same time is how
this project has already lost several hours.

---

## 7. If you have the I²C backpack instead

Four pins and a PCF8574 expander: `GND`, `VCC` (5 V), `SDA`, `SCL`, all with 4.7 kΩ pull-ups to 5 V — **which is
a 5 V bus on ESP32 pins**, so this variant needs a level shifter (a BSS138 pair, or a 3.3 V-powered backpack if
yours accepts it).

The ULP's only I²C is the **RTC I²C**, and its pins are restricted: **SDA on GPIO1 or GPIO3, SCL on GPIO0 or
GPIO2** (measured from the IDF docs). GPIO0 is a boot-strapping pin, so the sane choice is SDA = GPIO3,
SCL = GPIO2. That works for the ULP and is worth knowing, but the 16-pin parallel wiring above is simpler, needs
no level shifter, and is the one to prove first.

---

## 8. What the sprint spec says, adjusted for this panel

| Spec line | Was | With a 1602A |
| --- | --- | --- |
| Display | 40 × 4 characters, 160 B screen memory | **16 × 2, 32 B screen memory** — the same driver, a smaller map |
| D1 | ≥ 160 characters | **≥ 32 characters**; the 40 × 4 target stays as the upgrade path |
| Refresh ≤ 20 ms | measured on 160 cells | 32 cells → ~2 ms expected, so the requirement is easy and the headroom goes to the ULP |
| Editor width | 40 columns | **16 columns** — the editor's wrap test changes, and a notes line is short |

The two-line address map (`0x00`, `0x40`) is the only driver change; everything else in `08-psion.md` stands.

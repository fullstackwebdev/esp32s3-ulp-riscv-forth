# 30 — The SX1262 driver, written in Forth

`examples/apps/lora/lora1.fs` is a transmit-only SX1262 driver written in this machine's Forth. It bit-bangs SPI on
`GPIO!` / `GPIO@` alone — **no new primitives** — and it is verified on the host against the byte stream the proven C
driver puts on the wire.

| | |
|---|---|
| driver source | `examples/apps/lora/lora1.fs` |
| compiled size | **958 B** (`HERE` 786 → 1 744 on the host engine at device geometry) |
| phase window | **1 037 B** → fits, with 79 B spare |
| primitives needed | **0** (`GPIO!`, `GPIO@`, `MS`, `C@`/`C!` and arithmetic are already resident) |
| test | `probe/repl/tests/lora_spi.py`, wired into `probe/repl/tests/run.sh` (host suite: 30 PASS) |
| status | **wire-verified on the host; not yet packaged as a device phase** (see §5) |

## 1. How it is tested without a radio

The host engine's `pl_hw(op=1, pin, level)` prints `[gpio pin=level]` for every pin write, and `op=0` reads a simulated
pin word. `tests/lora_spi.py` reconstructs the wire from that trace: `NSS` frames transactions, `SCK` rising edges sample
`MOSI`, and the result is the exact byte sequence an SX1262 would have received. It then compares it to the cold-init
sequence the C driver runs on real hardware (docs/29), **transaction by transaction** — a flat byte comparison would pass
if two adjacent commands had their bytes shuffled across a boundary, which on the chip is a completely different command.

```
transactions: 14   bytes on the wire: 55
send: 17 transactions after init
all checks pass
```

The transmit path is checked through `SetTx` (`WriteBuffer` with the 20 payload bytes, `ClearIrqStatus`, `SetTx`), and the
test states what it cannot know: with no radio behind the pins, `DIO1` never rises, so `LORA_SEND` correctly returns 0. A
test expecting 1 there would be a test lying about hardware it does not have.

## 2. Shape of the driver, and why

| piece | why it looks like that |
|---|---|
| `LORA_SHIFT ( b -- b*2 )` | one bit of SPI mode 0; stack-neutral, so eight of them in a row (unrolled) shift a whole byte with no index to juggle |
| `LORA>B` | eight `LORA_SHIFT` steps then `DROP` — the unrolled loop is the shape docs/27 recommended for speed and it is also the shape this dialect can actually execute (see F-146) |
| `LORA_CLOCK` | one clock with MOSI low, returning MISO. Only the **last** bit of a word is ever needed (TxDone is bit 0 of the 16-bit IRQ status and SPI sends MSB first), so nothing accumulates |
| `LORA_CMD1 ( op arg -- )` | the two-byte commands; longer ones are written out explicitly, which costs bytes and buys clarity where the payload matters |
| busy/DIO1 waits | bounded loops that return 0 on exhaustion — never an unbounded wedge |

## 3. Bugs this found, all before any hardware was involved

1. **F-146 — this dialect's `>R` / `R>` leak.** A byte loop built on them left **two extra cells per byte**
   (`7 9 LORA_SPIX . . .` printed three numbers), which silently shifted every argument after the first: the second byte
   of a command came out as `0x00`. The fix is structural: no return-stack juggling in the bit path, an unrolled shift.
2. **R15 in person — one name, two meanings.** The pin constant `LORA_RESET` and the word `: LORA_RESET` collided, so
   `1 LORA_RESET LORA!` called the reset *word* recursively and the machine answered `error` with no name. The constant is
   now `LORA_NRST`.
3. **A 16-bit field needs both bytes.** `SetPacketParams` starts with a 16-bit preamble (0x0008), and the driver sent only
   the low byte, so the payload length landed where the CRC type belongs. Caught by the wire comparison, not by reading.
4. **A stack bug the compiler cannot see.** `DUP IF DUP 48 + ELSE DROP 165 THEN` consumed the loop index in the false
   branch, so the following `1+` underflowed (`ERR_STACK`).

## 4. What this settles about the Forth question

docs/28 §4 asked whether the driver could be Forth and what it would cost. Measured now:

| | C (`probe/lora`) | Forth (`lora1.fs`) |
|---|---|---|
| driver bytes | 2 804 | **958** |
| fits the 1 037 B phase window | no (needs the whole image) | **yes** |
| new primitives | n/a | **0** |
| wire bytes for cold init | 55, in 14 transactions | **identical** |
| SPI clock | 144.6 kHz measured | ~30–40 kHz (estimated from tokens; unmeasured — needs the board) |
| share of a packet's energy | 5 % of the awake window | 5–10 % of the awake window |

The energy answer from docs/29 makes the speed difference irrelevant: 95 % of the ULP's awake window is the packet on air,
so a 4× slower bus moves the power budget by a few per cent at any sane transmit period. **Bytes were the constraint, and
the Forth driver is a third of the C driver's size.**

## 5. Why it does not run on the device yet: a 125-byte wall

Not a logic problem — a budget one, and the numbers are exact.

On the chip, `GPIO!` / `GPIO@` were **stubs**: `pl_hw` in `src/ulp_repl.c` implemented only op 3 (`MS`) and returned 0 for
everything else, so the driver's pin writes went nowhere (F-148). Implementing the two ops — RTC registers, with the
`W1TS` field shift that F-141 cost four flash cycles to find — measures:

| implementation | ULP image | vs POOL 7 892 |
|---|---|---|
| today (no GPIO ops) | **7 891** | 1 B free |
| raw `REG_WRITE` / `REG_READ`, shared bit expression | **8 017** | **125 B over** |
| IDF `ulp_riscv_gpio_*` helpers | **8 039** | 147 B over |

`flash_safe.sh` refuses that image, so the Forth driver still cannot touch a pin on the chip. The three ways forward, with
their measured costs:

1. **Reclaim ~125 B from the interpreter.** Two levers exist: the stack reserve is `8000-ish − 300`, and the measured
   high-water is **240 B** (docs/23), so `POOL` can rise by ~60 B safely — leaving ~65 B to find. Sizes from
   `riscv32-elf-nm`: `p54_binop` 98 B, `find` 116 B, `mkhdr` 210 B, `interpret` 302 B, `word` 318 B, `vm_enter` 2 162 B,
   plus 142 B of `disp_tbl` rodata. Removing vocabulary (`ADC@` and `WAKE` are *themselves* non-functional on the ULP)
   would close it, but that is a product decision, not a refactor.
2. **Absolute-address GPIO in Forth** (`W!` / `W@` on `0x60008006` / `0x60008026`): **0 B of pool**, since the registers
   are 16 bits from pin 6 upward and the LoRa pins are 8–14. Cost: those addresses do not exist on the host, so the host
   test that verifies the wire bytes would need a memory shim before it could run — i.e. this trades the test for the bytes.
3. **Keep the C driver for the radio** (`probe/lora`, 2 804 B, transmitting on hardware with `TxDone`) and treat the
   Forth driver as host-verified pending a budget decision.

Nothing was shaved to make it fit: the image is back at 7 891/7 892 and the GPIO work is kept as a stash plus the
measurements above.

## 5b. What happened when it ran on the board (measured)

Our Forth firmware was flashed onto the Heltec V3 and the driver typed into its REPL (every line ≤63 B — the device input
ring refuses anything longer, which cost a full debugging cycle because the refusal arrives as "line too long" on a line
the operator can see is fine). Results:

| step | result |
|---|---|
| driver source loads | **1 100 B** compiled (`HERE` 786 → 1 886), fits the window |
| `LORA_INIT` | returns **1** — but see the last row: BUSY reading 0 always makes that check vacuous |
| `LORA_SEND` | **0** (no TxDone) |
| chip status via a Forth `GetStatus` | **0x00**, where the C driver on this board reads **0x2a** |
| pin readback `1 8 LORA! 8 LORA@` | **0** |

Cause (F-149): the engine's pointer guard, `P(a) = a < MEMSZ ? mem + a : &junk`, is shared by both builds, so on the
chip every register access from Forth lands in a one-byte `junk` cell. The host test passed because the RTCIO window added
to the *host's* `rd16`/`wr16` accepted precisely the addresses the chip refuses.

So option 2 does not work as written, and the reason is not the driver: **Forth cannot address a peripheral at all** on
this machine. The repair is a primitive pair that bypasses `P()` on purpose (`HW@` / `HW!` taking an absolute address),
which is a `.c` change and therefore pool bytes — the same wall as option 1, one level down.

## 5c. The repair, measured: `HW@` / `HW!` cost 62 B

A primitive pair that bypasses `P()` on purpose — `HW@ ( addr -- v )`, `HW! ( v addr -- )` on absolute 32-bit addresses
— is implemented behind `-DHWPRIMS` and **measures 62 B**: the image goes 7 891 → **7 953** against a `POOL` of 7 892.

| funding source | bytes | result |
|---|---|---|
| free pool | 1 | 61 short |
| stack reserve slack (300 B reserved, **240 B measured high-water**) | 60 | **1 short** |

So it is parked off, with the number recorded next to the flag. One byte is the entire gap, which is a much better problem
than "we do not know how big it is" — but it still has to come from somewhere honest (a real reclaim, then a re-measurement
of the stack high-water), not from shaving a word the interpreter needs.

### The gated `P()` — built, optimised, measured, and it still does not fit

Instead of a primitive pair, the guard itself can open **one 64-byte window** (0x60008400..0x6000843F, the RTC GPIO
register file) and leave everything else landing in `junk`. That is strictly better design than the primitives — the hot
path is unchanged (`a < MEMSZ` still returns first) and an accident cannot reach the window, because `-1 !` or an
underflowed address lands nowhere near it. It was implemented three ways and measured:

| shape | `.text` cost | image | stack high-water |
|---|---|---|---|
| range test inline in `P()` | +42 B | 7 933 | 240 B |
| all of `P()` `noinline` | **+12 B** | 7 903 | **269 B (+29)** |
| fast path inline, `P_slow()` `noinline` | +38 B | 7 929 | 240 B |

The cheap shape buys its bytes by making **every** byte access pay a call frame, and the paint caught it: 240 → 269 B of
stack, which is exactly the margin the reserve was borrowing. The shapes that leave the stack alone cost ~40 B, and
`POOL` is 7 892 with an image of 7 891.

So: **the gate is correct, implemented, and off** (`-DHW_GATE`), with these four numbers written next to the flag. It is a
one-flag change the day ~40 B of real reclaim exists. That is the honest end of this line of enquiry: not "we could not
build it", but "we built all three versions and none of them fits the machine we have".

### Why not relax `P()` instead?

Because `P()` is the single reason a wild pointer in **any** Forth word is harmless: `@`, `!`, `C@`, `C!`, `W@`, `W!`, the
dictionary, the compiler and the block copies all go through it. Relaxing it to let peripheral addresses through would be
cheaper in bytes (a range test, a few bytes) and far more expensive in everything else:

* **A Forth bug becomes a hardware write.** A stray `-1 !`, an underflowed address or a miscalculated offset would reach
  a timer, the RTC, the brownout detector or the flash controller instead of a one-byte `junk` cell. That is the opposite
  of this project's "fail loudly, and never silently".
* **It changes the meaning of every memory access at run time.** Below `MEMSZ` an address is memory, above it a register;
  the same opcode then has a silent behavioural cliff.
* **It spreads the exception over five accessors** (`rd8/wr8/rd16/wr16/rd32/wr32`) instead of owning it in one word pair
  that is named for what it does.

One narrow, auditable door beats a memory model with a hole in it.


* **It is not yet a device phase.** `probe/repl/tools/lint_forth.py` refuses it as phase source: a block has no line
  boundaries, so `\` comments compile as words (R1 — 40-odd of them here), and R11 refuses a definition that does not fit
  inside one 92 B block (`LORA_INIT` is the long one). Packaging means `( … )` comments and a split that keeps each
  definition whole — `tools/fsplit.py` is the tool, and its safe-after rules forbid cutting before `CONSTANT`.
* **It has never run on a radio.** The host test proves the wire bytes; only the board can prove the packet. The board to
  use is the Heltec, which currently runs the C driver — flashing this phase needs the Forth firmware there, not the
  `probe/lora` C image.
* **The ~30–40 kHz estimate is an estimate.** `docs/27` describes the measurement (a counted loop timed by the main core);
  it needs our interpreter on this board, which is the same missing piece as above.

## 6. The gate is on, and it works (measured, 2026-11-01)

The `HW_GATE` shape described in §5c was enabled and run on the board. Three separate problems were found by running it,
and all three matter beyond LoRa.

### 6a. The gate reaches the registers — proved, not assumed

`262144 1610646528 ! 1610646528 @ .` answers `262144`, and `12345 … @ .` answers `12345`. A Forth word wrote an RTCIO
register and read the value back. **F-149 is closed**: `P_slow()` returns a real pointer and `!`/`@` are enough.

### 6b. F-151 — byte-decomposed stores do not latch a W1TS register

`wr32` is `wr16(a,v); wr16(a+2,v>>16)`, i.e. **four byte stores**. That is correct for memory and wrong for
`RTC_GPIO_OUT_W1TS`: the register is write-one-to-set and a byte write does not latch, so **the pad never moved**, the SPI
clock never clocked, and `GetStatus` read `0x00` while every address round-trip "passed" — the round-trip used a plain
read/write register (`OUT_REG`), which byte writes *do* update. The C driver never hit this because `REG_WRITE` is a
single `sw`.

Fix: `wr32` now takes the gate path with a genuine 32-bit store (`*(volatile u32 *)a = v`). Gate addresses are register
bases, so they are 4-byte aligned by construction and the wide store is safe there and only there. Cost: **+30 B**
(7 929 → 7 959). Lesson: a write that "works" on one register proves the bus, not the store width.

### 6c. F-150 — a stack that overlaps the image corrupts the dictionary *silently*

With the gate on, the image grew to 7 959 B and the reserve was cut to 200 B to make it fit. The machine then answered
`ok` to `: XX 42 ;` and `XX?` to `XX .`; `7 CONSTANT SEVEN` followed by `SEVEN .` gave `SEVEN?`; `HERE` never moved;
**no error was ever reported**. `#k` gave the answer: `high-water 184 B of 184 B region (0 B free)` — the stack was
running through the paint and into the image, overwriting dictionary writes.

This looks exactly like a broken compiler, and it was diagnosed as one for several build cycles. The rule: the paint is
a lower bound, not a guarantee. Require `image + reserve <= 8192` with margin, and treat any "definition compiles but
does not exist" as a stack-overlap symptom, not a compiler bug.

The measured high-water with the driver loaded and `INIT`/`SEND` executed is **240 B of 244** — which vindicates
`docs/23`'s 240 B. The 144 B reading came from a session where the driver was not loaded, i.e. it measured a different
workload. Paint must be re-established per boot and read after the *heaviest* workload, not the first one.

### 6d. F-152 — never write arbitrary bits to `RTC_GPIO_OUT_REG`

`12345 1610646528 !` **reboots the S3** (`ESP-ROM:esp32s3-20210327` on the console). Bits 0..21 of that register are RTC
GPIO 0..21, which include pads tied to flash, PSRAM and the brownout detector. Only single-bit writes through
`RTC_GPIO_OUT_W1TS` are safe. This also retires the address round-trip as a test method: use a scratch register, never
this one.

### 6e. Where it stands

| | |
|---|---|
| image | **7 907 B / 7 932 B** (POOL 7932 = 8192 − 260 reserve) |
| stack | **240 B used of 244 B region, 4 B free** — too tight, needs ~40 B more headroom |
| `MEMSZ` | 2 550 (baked 2 422/2 550) |
| driver | 950 B compiled (was 1 100 B; compaction saved only 8 B — headers dominate, not names) |
| host suite | 30 PASS, `lora_spi.py` still wire-identical to the C driver |
| on the board | `INIT .` → `1`, `GetStatus` → **0x00**, `SEND .` → `0` |

`INIT` returning 1 is **vacuous**: BUSY reads 0 because the input path returns 0 for every pin, so "BUSY low → ready"
passes on a dead bus. The next probe must be one that *cannot* pass vacuously: drive a pad high from the main core and
require the ULP to read 1. Until that passes, Forth SPI is unproven in either direction — 6b proves the store is right,
not that the pads are muxed.

## 7. Width is a contract: reads too (F-153), and where the pads stop answering (F-154)

### F-153 — `rd32` needed the same 32-bit path as `wr32`

Fixing `wr32` (§6b) made register *writes* land, and register *reads* still returned 0 — because `rd32` is
`rd16(a) | rd16(a+2)<<16` and every `rd16` is two `rd8` loads, i.e. **four byte loads**. RTCIO does not answer byte
accesses. After giving `rd32` a real 32-bit load inside the gate, `1610646544 @ .` returned `14642` where it had returned
`0`, and `532480 1610646712 ! 1610646712 @ .` round-trips the pad-13 mux register exactly. Cost: **+24 B**
(7 907 → 7 931). Store and load must agree on width, or half the bus is invisible and the failure looks like a dead chip.

### F-154 — `RTC_GPIO_IN` is not usable from the ULP yet (open)

Measured, in this order, all with the pad mux registers holding `MUX_SEL|FUN_IE`:

| probe | result |
|---|---|
| `#h` (HP core drives pin 13 high) then `13 @P .` | `0` |
| `#l` (HP core drives it low) then `13 @P .` | `0` |
| `RTC_GPIO_IN` raw, before/after driving | `33620481` (= `0x02010201`, **unchanged**) |
| ULP drives pin 8 via `W1TS` bit 18, reads `IN` | `33620481` (unchanged) |
| ULP drives pin 11 via `W1TS` bit 21, reads `IN` | `33620481` (unchanged) |

A register that returns one constant for every input state is not tracking the pads: either the pads are not in RTC-IO
mode at read time (the HP core's `rtc_gpio_init` claims them, but something re-muxes them afterwards), or the ULP's APB
read of this offset is answered by something other than the pad inputs. The earlier `#h` probe also had a genuine flaw
of its own (recorded in the code GUARDRAIL): `OUTPUT_ONLY` clears `FUN_IE`, so it switched off the buffer it meant to
read; it now uses `INPUT_OUTPUT`, and the answer is still 0, so that flaw was not the whole story.

Note the contradiction this leaves: the C driver **did** read MISO from the ULP (chip status `0x2c` from the ULP,
`ReadBuffer` matching the transmitted payload, `TxDone` on 4/4 wakes). So the ULP input path works **when the pad
configuration is the C driver's**. The difference is configuration, not silicon — which is exactly why the next probe
must be the C driver's own pad sequence translated to Forth, not another guess.

### Budget, as of this run

| | |
|---|---|
| image | **7 931 B / 7 932 B** (1 B free — the wall again) |
| stack | 240 B used, 261 B available (reserve 260) |
| `MEMSZ` | 2 550 |
| host suite | 30 PASS |

The gate now costs +76 B in total over the ungated 7 891 B build (32-bit store + 32-bit load + the range tests). That is
what the 12 B "cheap" shape in §5c was hiding: it bought bytes by paying in `rd32`/`wr32` correctness, and the hardware
charge for that was two silent, total failures of the bus.

### F-155 — the gate window must include SENS, or the pads are muxed but inert

`ulp_riscv_gpio_init()` — what the C driver's ULP calls for every pad — does two things this project had not: it enables
the **RTC IO MUX clock gate** (`SENS_SAR_PERI_CLK_GATE_CONF_REG` at `0x60008904`, bit 31) and it clears `FUN_SEL` with a
read-modify-write. `0x60008904` is **outside** a `0x200` window from `0x60008400`, so from Forth the clock gate was
unreachable: the pads could hold `MUX_SEL|FUN_IE` and still never move. The span is now `0x600` (RTCIO + SENS), which is
still one compare against one constant and cost **0 B** — the image stayed at 7 931.

### The remaining unknown, stated exactly

With the clock gate reachable, `MUX_SEL|FUN_IE` written to `RTC_IO_TOUCH_PAD{11,13,14}`, outputs enabled and the HP core
driving pin 13 high, `13 @P .` still answers `0`, and `RTC_GPIO_IN` (base+0x24, `RTC_GPIO_IN_NEXT_S` verified as 10)
answers `0x02010201` — **two identical halves**, which is the signature of a 16-bit fallback read rather than a live
register, even though `rd32`'s gate branch is demonstrably compiled (`P_slow` is in the ELF) and `MUX_SEL|FUN_IE`
round-trips exactly (`532480` in, `532480` out) at `+0x84 + pin*4`.

The next step is not another guess: run the **C driver** (`probe/lora`, which passes `hal_pad_selftest` with mask 0) and
print the raw `RTC_GPIO_IN` it sees while it drives a pad, then compare that number with what the Forth interpreter reads
at the same address in the same image. Same register, same core, two builds — the difference will name the fault.

### F-156 — the ULP's RTCIO accesses are swallowed while the HP core is awake (two-reader proof)

This is the answer to the question §7 left open, and it needed a second reader to see. `#g` prints the RTC GPIO
registers **as the HP core sees them**, so both readers can be compared in one board state:

| | Forth (ULP) | HP core (`#g`) | agree? |
|---|---|---|---|
| `OUT` | `0x1C000000` | `0x00440000` | no |
| `IN` | `0x02010201` | `0x00000400` (bit 23 = pin 13 driven) | no |
| `pad13` after writing `532480` | `532480` (echoes the write) | `0x40082000` (unchanged) | no |
| `0 → OUT`, then read back | `0` (echoes the write) | `0x00440000` (unchanged) | no |
| memory `777 → 5000`, read back | **`0`** | — | — |

Two things fall out of that table:

1. **The gate is definitely active.** An address above `MEMSZ` (`5000`) does *not* round-trip — it lands in the one-byte
   `junk` cell and reads back `0` — while a register address echoes its written value exactly. Registers and junk behave
   differently, so `P_slow()` is being reached and it is returning the real pointer. The disassembly confirms it
   (`wr32` does `sw a1,0(a0)` behind the `0x60008400 … +0x5FF` compare, `rd8`/`wr8` both call `P_slow`).
2. **The accesses do not reach the peripheral.** The ULP's store is accepted by *something* that echoes it back on read,
   while the HP core sees the register unchanged. That is the signature of an APB access to a clock-gated peripheral.

The C driver did exactly the same `REG_WRITE(RTC_GPIO_OUT_W1TS_REG, …)` from exactly the same core and it worked — and
in every one of those runs **the HP core was asleep** (`esp_deep_sleep_start`, 31/31 packets). The Forth REPL, by
definition, runs with the HP core awake because it is feeding the interpreter over UART. So the working hypothesis is now
precise and testable: **the RTCIO file is only reachable from the ULP while the HP core is not holding the bus.**

The experiment that settles it does not need a guess: have the HP core queue a Forth line, enter light sleep for ~1 s,
and read `#g` after waking. If the register changed, the contention hypothesis is right and the Forth driver needs the
same shape as the C driver — ULP owns the radio *while the CPU sleeps*, which is also what the power budget in `docs/29`
assumes anyway.

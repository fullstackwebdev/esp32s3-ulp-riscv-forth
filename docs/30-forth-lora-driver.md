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

### F-157 — the contention hypothesis is dead; the write is swallowed even with the HP core asleep

`#n` clears `OUT` bit 18 (`100` = pin 8) **from the HP core** — a baseline that cannot already satisfy the test — queues
`262144 1610646532 !` (a `W1TS` set of that same bit) into the ring, enters light sleep for 1 s so the ULP owns the bus,
and then reads the register:

```
gpio: cleared bit18 (HP), OUT now 0x00400000
gpio: queued '262144 1610646532 !', sleeping 1 s
gpio: after sleep OUT 0x00400000 (bit18 clear)
262144 1610646532 !   ok
```

The ULP ran the command (`ok`) and the register did not move. So F-156's hypothesis — "RTCIO is only reachable from the
ULP while the HP core is asleep" — is **wrong**, and it is retired rather than left standing.

What is left, and what it is now measured against:

* The gate is **active**: `wr32`/`rd32` contain the real `sw`/`lw` behind the `0x60008400…+0x5FF` compare (verified in
  the disassembly of the flashed blob, which is fresh: `ulp_main.bin` rewritten at flash time), and an address above
  `MEMSZ` behaves differently from a register address — `532480 → pad13 → 532480` round-trips exactly, while `5000`
  does not round-trip at all, because `junk` is one byte and all four byte writes alias onto it.
* The store reaches *something* that echoes it back on read, while the HP core sees no change, in both directions.
* The C driver's `REG_WRITE(RTC_GPIO_OUT_W1TS_REG, …)` from the same core at the same address works — the radio answered.

The next experiment is a **minimal C function in this same ULP binary** — five lines that do one `REG_WRITE` to
`RTC_GPIO_OUT_W1TS_REG` and return — invoked from the HP core. That separates "this ULP program cannot reach a
peripheral" from "this interpreter's access path cannot", which no Forth-level probe can distinguish. It needs ULP
bytes, so it waits for the budget: the image is at **7 931 / 7 932 B**, one byte free, and the honest place to find them
is the driver's own dictionary (`MEMSZ`), not another squeeze of the engine.

`docs/30` §6e's table still stands, with one line changed: `INIT .` → `1` is not merely vacuous, it is **known** to be
vacuous, because the pad read that would make it real returns 0 for every input state.

### The linter learned this session (R21-R24)

Every failure above that was *static* is now a rule, because each one cost a flash cycle and none of them had to:

| rule | what it refuses | earned by |
|---|---|---|
| **R21** (`--repl`) | a source line over 63 B | four comment lines of 64–80 B that the ring refused silently, leaving `NAME?` on innocent lines |
| **R22** | a `:` opened before the previous `;`, or a name defined twice | the stray duplicate `: !P` that swallowed `: S` and answered `S?` two definitions away |
| **R23** | `W!`/`W@`/`C!`/`C@` on a register address | F-151 (stores) and F-153 (loads): both read 0 with no error |
| **R24** | writing `1610646528` (`RTC_GPIO_OUT_REG`) | F-152: `12345 → OUT` reboots the S3 |

Two false positives were found and fixed before shipping the rules, which is the whole reason `tools/sink.py` exists: R21
first fired on `02_loops.fs` (72 B) and `03_digits.fs` (77 B), both of which the board compiles today — because the
corpus travels as **92 B blocks**, not typed lines. That made R21 opt-in via `--repl`. R22's first version tracked state
per line and called every ordinary one-line definition "unterminated"; it now scans tokens.

Also fixed while wiring it up: `\` comments were parsed as definitions (`\ … no loop: run_line zeroes …` defined a word
called `run_line` whose body ate the real `: WB … ;`), the same class of bug the file already fixed for `( … )`.

`tools/lora_device.py` now **requires a clean `--repl` lint** before typing a single line, and `tests/run.sh` lints the
driver on the host. The driver lints clean, and the suite is 30 PASS.

## 8. The probe was wrong, not the bus (F-158)

Everything in §7 rested on a probe that reads a register back **from the ULP**. That probe is invalid, and the way it
failed is worth more than the conclusion it produced.

The same three lines were added to the *working* firmware (`probe/lora`), whose ULP demonstrably transmits
(`tx_ok` 4/4 in a 20 s stay-awake run, `status 0x2C`):

| reader | `RTC_GPIO_OUT` | `SENS_SAR_PERI_CLK_GATE_CONF` |
|---|---|---|
| HP core (trustworthy) | `0x00440000` | `0xC0000000` |
| ULP, in the **working** firmware | `0x1C008000` | `0x090A0811` |
| ULP, in the Forth firmware | `0x1C008000` | `0x090FC811` |

**The ULP's register reads are garbage in both firmwares**, including the one where every write works. So:

* every conclusion drawn from "the ULP read back 0x…" was worthless, including the `0x02010201` that looked like a
  dead bus and the "two identical halves = 16-bit fallback" reasoning;
* the only trustworthy reader is the **HP core**, which is also why `#g` exists;
* and the C driver never cared, because `pin_read()` samples `RTC_GPIO_IN` for a *bit* and the garbage happens to carry
  usable pad bits - the reference's `hal_pad_selftest` passes with the same reads that misled this investigation.

What survives, all measured with the HP core as the reader:

1. **The board's ULP can drive RTCIO with the HP core awake.** The reference firmware was rebuilt with `STAY_AWAKE`
   (`-DLORA_STAY_AWAKE=1`) and transmitted 4 packets in 20 s with the CPU running; `wakes 13 tx_ok 12` follows in deep
   sleep. So "the radio belongs to the CPU's sleep window" is **false**, and F-157's retirement of the contention theory
   was right for the wrong reason.
2. Config is not the difference: the two `sdkconfig`s differ only in flash size, log level and partition table; the ULP
   RAM reserve was tested on the reference at both 4096 and 8176 with no effect.
3. Pad ownership is not the difference: `gpio_reset_pin()` before `rtc_gpio_init()` (the reference's own step) was
   added and changed nothing; the SENS clock gate is already open (`0xC0000000`) before anything runs.
4. Placing the store at the **first instructions of `main`**, before the interpreter, changes nothing.
5. What is still true: a store to `RTC_GPIO_OUT_W1TS` from the Forth firmware's ULP does not appear in the HP core's
   view of `RTC_GPIO_OUT`, while the same store in the reference firmware does.

So the remaining difference is the **image itself** (7 831 B with a 4.9 KB interpreter vs 2 904 B) or something the
engineer has not looked at yet. The next experiment is a bisect, not a theory: build this ULP with the interpreter
compiled out (`P42_ONLY`, the existing bench main) plus the three-line store, and see whether that image can move the
pad. That splits "this image" from "this hardware" in one flash, and it is cheap because the bench main already exists.

### The rule this earns (docs/14 R20)

**Validate the instrument on a known-good system before believing a single number from it.** Three hypotheses died
because a probe was trusted in the firmware where everything fails, without ever running the same probe in the firmware
where everything works - where it would have been caught in one flash. The reference build was sitting in the tree the
whole time.

### F-159 — a bench image that does not report wakes is not running, and `EARLY_ULP` was a trap

Two bisect results from §8 had to be thrown away, and both were thrown away **after** being recorded as measurements:

* The interpreter-free image (`P42_ONLY` + a three-line store, 3 606 B) also failed to move a pad. That result is void:
  the same check that would have caught it — `#u` reporting `wakes` — reads **0**, so the coprocessor never executed the
  store. `P42_ONLY` returns from `main()` before `repl_wake_count` is incremented in the path the app reads, so the
  counter was not a valid liveness signal *for that build*, and nobody checked.

  **Before any conclusion from a modified ULP image, prove the image runs.** The cheapest proof is a counter the image
  itself increments and the HP core prints (`wakes`, `pl_hwcnt`), read *in the same session* as the measurement. A bench
  build needs its own liveness line.

* Starting the ULP early — right after `lora_pads_setup()`, to eliminate the watchdog/UART/flash/block-task init from
  the suspect list — silently **kills the coprocessor**: `canary_paint()` runs later in `app_main` and writes 260 bytes of
  stack paint at `CANARY_BASE`, which is the ULP's stack. The ULP then never runs again (`wakes 0`), which looks exactly
  like "started early, still cannot write the register". The paint has to happen before `ulp_riscv_run()` for a reason
  that is now written down twice.

Reverted: `EARLY_ULP` is gone, the probe build is gone, and the firmware is back to the measured configuration
(**7 931 / 7 932 B**, `wakes` climbing, `1 2 + .` → `3`). The `HWPROBE` store and the `ULP_EXTRA_DEFS` CMake hook stay
in the tree as the tool for the next attempt, both off by default.

**What is still true after all of this** (each with the HP core as the only reader, and `wakes` confirmed non-zero):

1. The board's ULP can drive RTCIO — the reference firmware transmits 4 packets in 20 s with the HP core **awake**.
2. Config, pad ownership, `gpio_reset_pin`, the SENS clock gate and store placement are all eliminated.
3. In the Forth firmware, the ULP runs (`+6` wakes per 40 ms) and its store to `RTC_GPIO_OUT_W1TS` does not appear in the
   HP core's `RTC_GPIO_OUT`.

**The next experiment must be a bisect with a liveness check**: build the reference `probe/lora` ULP source *into this
firmware's* slot (`REPL_ULP_SRC` accepts an alternative source tree; the bridge variables would need the same `keep`
block the stub uses), and confirm `wakes > 0` and a moving pad before touching anything else. If the known-good ULP
source fails here, the difference is provably this app's HP-side environment, and the remaining candidates are the ones
no theory has touched yet: linker placement of `.rtc.*`, and the flash-store's partition access.

### Note on the reference build's size

The cross-firmware probe (F-158) adds two words and three lines to `probe/lora`'s ULP, so its image measures **2 904 B**
where `docs/29` records **2 804 B**. The 100 B difference is the probe only - the SPI loop, the driver and every timing in
`docs/29` are unchanged, and the probe is one store plus two reads per wake. `probe/lora` also gained a documented
`-DLORA_STAY_AWAKE=1` build switch that keeps the HP core running for 20 s and prints the counters every second; that is
the tool that proved the ULP drives RTCIO with the CPU awake, and it is the one to reuse for the bisect in §8.

## 9. F-160: the difference is neither the flags nor the config (measured, both directions)

Three classes were opened and closed against the **only trustworthy reader** (the HP core, `#g`/`staytest.py`), with the
ULP's own wake counter as proof of liveness:

| experiment | result |
|---|---|
| Working ULP source compiled with **this firmware's full ULP flag set** (`-msave-restore -fno-strict-aliasing` + the nine tree flags) | store **LANDS** — flags eliminated |
| Working firmware built with **this app's entire `sdkconfig`** (8 176 B ULP reserve, custom partitions, 2 MB flash, warn-level logs) | store **LANDS** — config eliminated |
| This app, `P42_ONLY` image (3 616 B, **no interpreter linked**), ULP started immediately after pad setup, `wakes` verified moving | store **LOST** |
| Same, plus `esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ON)` — the one RTC power call the reference makes and this app did not | store **LOST** |

So the fault is in **this app binary**, not in how the ULP is compiled, not in the build configuration, and not in the
interpreter. Everything the HP-side bisect could reach has been eliminated except the two things named at the end of §8:
linker placement of `.rtc.*`, and what `flash_store`/`store_boot()` do to the memory map.

### Two more invalid tests discarded on the way (same instrument mistake, twice)

* Probing **pad 11** (`bit21`) as a store target. In this firmware pad 11 is `RTC_GPIO_MODE_INPUT_ONLY` — its `OUT` data
  bit is not a meaningful thing to set. A round trip on an output pad, not a bit in a register, is the test.
* Passing `-DULP_EARLY` **only** through `ULP_EXTRA_DEFS`, which feeds the ULP sub-build's CFLAGS. The HP side silently
  kept the normal boot path, so "started early, still lost" was measured on a firmware that had not been changed. A flag
  that reaches one of two builds is a footgun: the switch is now a CMake option that defines it on **both** sides
  (`main/CMakeLists.txt`), and `strings build/*.elf | grep EARLYTEST` is the check that the code being run is the code
  being tested.

### Tools left in the tree, off by default

* `probe/repl`: `-DULP_EARLY=1` (HP) + `-DULP_EXTRA_DEFS="-DP42_ONLY -DHWPROBE"` (ULP) builds the minimal liveness+store
  probe; `tools/waketest.py` reads it from the port.
* `probe/lora`: `-DLORA_STAY_AWAKE=1` prints one `AWAKETEST` line per ULP wake; `tests/staytest.py` decides LANDED/LOST.
* `main/CMakeLists.txt` (lora): `-DLORA_FLAGS='...'` replaces any single flag, so one flash per hypothesis.

### Restored and verified

Shipping configuration rebuilt and flashed: **7 931 / 7 932 B**, `boot: ulp forth bridge, 7424 B image`, store formatted,
`1 2 + .` → `3`, and a deliberately bad op failing loudly (`stack?`). Host suite below.

### F-161 — footprint eliminated too; the matrix has exactly one cell left

Continuing the §9 bisect with `#z` (the store probe as a console command, so the answer no longer depends on when the
harness opens the port — printing from `app_main` before `uart_driver_install` simply produced **no output at all**, which
read as "the test never ran"):

| build | image | result |
|---|---|---|
| `P42_ONLY -DHWPROBE` at `MEMSZ 2550` | 3 616 B (data 2 568) | `storetest: LOST (clear, 60 ULP wakes, OUT 0x00400000)` |
| same at `MEMSZ 900` | **1 924 B** (data 916 — smaller than the reference's 2 816 B) | `storetest: LOST (clear, 61 ULP wakes, OUT 0x00400000)` |

Both with the ULP verified alive (60+ wakes observed inside the 400 ms window), on an **output** pad, after an HP-side
clear, in the shipping pad configuration. So the ULP image's footprint in RTC slow memory is not the cause either.

Everything measured so far, with the HP core as the only trustworthy reader:

| cell | lora app | repl app |
|---|---|---|
| lora ULP (with repl's flag set) | **LANDS** | — |
| repl ULP (any of: shipping 7 931 B, `P42_ONLY` 3 616 B, `MEMSZ 900` 1 924 B) | **LANDS** | **LOST** |

The one blank cell is **the reference ULP source built and booted by this app**, and it is the only experiment left that
can separate "this app's HP side" from "this app's ULP build", because every ULP-content variable (size, footprint,
flags, placement) has now been varied without changing the answer. Building it needs a small bridge shim: `probe/lora`'s
`ulp_main.c` defines none of `repl_cmd/repl_out/mailbox/mem/repl_status/...` that this app links against, so it has to be
included from a file that also carries `src/ulp_stub.c`'s "touch every exported symbol" block. That is the next action,
and it is one build + one flash.

### Shipping state, restored and verified

`MEMSZ 2550`, no probe paths compiled in (`strings build/*.elf | grep -c EARLYTEST` → `0`),
**7 931 / 7 932 B**, boot banner + store formatted, `1 2 + .` → `3 ok`.

### F-162 — the ULP's own `ulp_riscv_gpio_init()` is not the fix either

The last hypothesis that could explain the register-level evidence from the peripheral side: the reference ULP calls
`ulp_riscv_gpio_init()` on every pad, and that helper's first statement is a `SET_PERI_REG_MASK` on the RTC IO MUX clock
gate **executed by the ULP**. If that clock-enable were per-master, the HP core's set of the same bit would not open the
ULP's path — which would explain every symptom (HP writes visible, ULP reads and writes vanish, register dumps look
identical between the two firmwares).

Tested: the probe image calls `ulp_riscv_gpio_init(8)` and `ulp_riscv_gpio_output_enable(8)` from the ULP immediately
before the store (text grew 600 -> 700 B, so the helpers really linked and ran). Result, three times, with the ULP
verified alive:

```
storetest: LOST (clear, 60 ULP wakes, OUT 0x00400000)
```

Hypothesis retired. That closes every hypothesis built from the register evidence.

### The one experiment left, and where I stopped

Blank cell of the §9 matrix: **the reference ULP source built and booted by this app**. `REPL_ULP_SRC` already accepts an
alternative ULP tree, but `probe/lora/main/ulp/ulp_main.c` defines none of the variables this app links against
(`repl_cmd`, `repl_out`, `mailbox`, `mem`, `repl_status`, ...), so it needs a small bridge shim carrying `src/ulp_stub.c`'s
"touch every exported symbol or `--gc-sections` eats it" block. One build + one flash then separates "this app's HP side"
from "this app's ULP build" for the last time. I am stopping there rather than guessing past it, because every guess in
this investigation has already been paid for with a flash cycle that produced a void result (F-159, F-161).

### State of the two radios, plainly

| | status |
|---|---|
| `probe/lora` (C bit-bang ULP driver) | **transmits** — `tx_ok` rising, `status 0x2C`, 12/12 packets, including with the HP core awake |
| `examples/apps/lora/lora1.fs` (Forth driver) | **does not transmit.** Wire-identical to the C driver on the host (14 transactions / 55 bytes, suite 30 PASS); refused by the board only by the peripheral access above |
| App Store (the original goal) | done, merged to `main`, 16/16 through a pty |

## 10. The decompile and the register diff (F-163, negative — and that is the answer)

Two machines, both sides read by the HP core, one command.

**Disassembly.** `reset_vector`, `__start` (`auipc sp` / `addi sp` / `jal ulp_riscv_rescue_from_monitor` / `jal main` /
`jal ulp_riscv_halt`), and the store itself are the same instructions in both images:

```
reference:  17e: lui  a5,0x60008   182: lui a4,0x40    186: sw a4,1028(a5)   # 60008404  (OUT_W1TS, bit18)
ours:       138: sw a3,1028(a5)    # 60008404          (same encoding, same value, reached from main's first block)
```

**Register diff.** `#d` (probe/repl) and the stay-awake build (probe/lora) print the *same* 544 words — RTCIO
`0x60008400..0x60008800`, SENS `0x60008800..0x60008900`, RTC_CNTL `0x60010000..0x60010300`, SYSTEM
`0x600C0000..0x600C0080`. Four differences, all explained:

| register | ours | ref | explanation |
|---|---|---|---|
| `0x600088A8..0x600088D8` (10 words) | various | various | SAR/ADC analog block — reads change with every sample |
| `0x60010100 RTC_CNTL_ULP_CP_CTRL` | `0x60` | `0x62` | **dynamic**: writing bit 1 (`COCPU_START_2_RESET_DIS`) and reading it back 1 µs later gave `0x0010023F` — the two machines were sampled at different points in the ULP timer sequence. Setting the bit (before *and* after `ulp_riscv_run()`) left the store LOST. |
| `0x60010200` | `0x13` | `0x91` | RTC_CNTL status register — by definition a snapshot |
| `0x600C0020 SYSTEM_PERIP_RST_EN0` | `0x9EFF1FF8` | `0x9EFF1FB8` | bit 6 = `SPI2`; the reference's `bus_probe()` initialises and releases hardware SPI2, this app never uses it. Nothing to do with RTCIO. |

So there is **no enable bit difference**, which is itself the strongest evidence yet that the difference is not in
configuration at all. Combined with §8–§9 (flags, sdkconfig, footprint, HP ordering, the ULP's own `gpio_init`, this
bit) the eliminated list is now: everything the register-level view can see.

**What that leaves**, and it is the §9 matrix's blank cell, unchanged: the reference ULP source, built and booted by this
app. It needs a bridge shim (the exported variables), and it is the only remaining experiment that can separate "this
app's HP side" from "this app's ULP build". Every other shape of that question has now been asked and answered.

### F-164 — the reference's exact ULP preamble, inside our app: still LOST

`ulp_riscv_gpio_init()` on all 7 pads, `ulp_riscv_gpio_output_enable()` on the 4 outputs,
`ulp_riscv_gpio_input_enable()` on the 3 inputs, then the store — the reference's `hal_init()` instruction for
instruction, executed by our ULP on every wake (text 600 → 826 B, so it linked and ran; `#z` showed 60 wakes per window):

```
storetest: LOST (clear, 60 ULP wakes, OUT 0x00400000)     x3
```

Combined with §9/§10 that closes the question "does the ULP program have to *do* something first?" — no. Our ULP can
now execute anything the reference's does, byte-for-byte, and its APB write is still discarded while the identical
write in the reference app lands.

The one hypothesis that survives every measurement so far is a **HP-side gate outside the range the 544-word diff
covered**: the RTC peripheral clock gate on the S3 lives in the SYSTEM block, and `#d` sampled
`0x600C0000..0x600C0080` only. Next probe is the same command widened to `0x600C0100` (and RTC_CNTL past `0x300`) —
a one-line change to both lists and one flash, and it is the only place the difference can still be hiding.

## 11. The inverse bisect found the gate (F-171 - F-175)

Walking from the artifact that LANDS toward ours, one deletion per flash, `#z`/staytest as witness, every result attributed
to a distinct artifact size (the stale-binary trap caught twice on the way):

| cut | image | ULP wakes | bit 18 (`RTC_GPIO_OUT`) | verdict |
|---|---|---|---|---|
| radio work deleted, `hal_init()` kept | 550 B | 1 → 7 | returns to **SET** | **LANDED** |
| `hal_init()` deleted | 300 B | 1 → 6, 15 samples | stays cleared | **LOST** |
| full `hal_init()` minus the two pull operations | 458 B | 3 → 6 | SET | **LANDED** |
| full `hal_init()` minus the three level writes | **466 B** (distinct artifact) | 3 → 6 | cleared | **LOST** |

So: the 195 ms of SPI traffic was never the reason; **`hal_init()` is the gate, and inside it the pad level writes
(`pin_high(NSS)`, `pin_high(RESET)`, `pin_low(SCK)`) are the necessary part** - the pull operations are not. That is also
the first finding in this whole investigation that says something *positive* about what the Forth driver must do: it has to
own the pad levels from the ULP, not inherit them from `lora_pads_setup()` on the HP core.

**F-175 (the fix attempt) did not work**: reproducing the config ULP-side - `ulp_riscv_gpio_init()` on all 7 pads, the 4
output enables, the 3 input enables, then NSS/NRST high and SCK low through `W1TS`/`W1C` - costs ~430 B of text (dictionary
funded it 1:1, image 7 915 B) and still measures `storetest: LOST` at 104 wakes. The reproduction is therefore *not*
equivalent to `hal_init()`, and the disassembly shows why the search must go there next: in the reference image
`ulp_riscv_gpio_init` issues its clock-gate store through a link-time **alias** (`# c904 <SENS+0x104>`, i.e. `SENS` is
`0xC800` in the ULP link, not `0x6000_8800`), so the helper's real writes are not all the absolute addresses I have been
assuming. Next measurement is zero-flash: diff our image's inlined helper against the reference's, instruction for
instruction, and match the *alias* window rather than the SoC addresses.

Two build traps hit and recorded while doing this, both worth repeating:

* CMake caches the ULP sub-build's `CMAKE_C_FLAGS`, so an experiment flag removed from the command line can remain live in
  the sub-build - the image that "proved" a cut was sometimes the previous cut. Always check the artifact size differs
  (R21).
* The ULP linker region comes from `CONFIG_ULP_COPROC_RESERVE_MEM`; a stale generated `ulp_riscv.ld` reports
  "`.bss` not within region ram" for a perfectly good image. `idf.py fullclean` before trusting a size change.

## 12. The environment was never the blocker (F-176 .. F-176j)

The inverse bisect kept saying `hal_init()` is the gate, so the next step was to compile *that file* into our own image
instead of transcribing it. Result, every verdict attributed to a distinct artifact size:

| what our image did | artifact | HP-side witness |
|---|---|---|
| real `hal_init()` compiled in, called at wake start | 7 249 | **NSS(bit18) SET** |
| `output_enable(NSS)` only | 7 025 | clear |
| `init` + `output_enable` for one pad | 7 069 | clear |
| all seven pads configured, no level writes | 7 219 | clear |
| burst of 11 stores to `OUT_W1TS` | 7 239 | clear |
| `hal_init()` + our own store to SCK (engine drives it low) | 7 257 | NSS SET, SCK clear |
| **engine's own C SPI: `hal_reset()` then GetStatus** | **7 917** | **`eng_status = 0x2A`** |

Read the last row with the first: **inside our firmware, driven by our app, the C engine's SPI transaction returns
`0x2A` from the SX1262** - the same value the C driver's bring-up recorded (docs/29). So the coprocessor can move these
pads in this firmware, the pads are configured, the radio answers, and nothing about this app or its build was ever the
obstacle. What remains is narrower than the 165 probes before it: instructions from `hal_engine.c` move the pads, and
instructions from the *interpreter's* `!` do not - both measured on the uncontended pad 10 (MOSI), where the register
mirror shows Forth's bit after its own store (`OUT` reads `0x100000`) and yet nothing the engine does afterwards is
disturbed.

Two measurement corrections came out of the same series, both worth repeating:

* **`RTC_GPIO_IN` is not a witness for pads the engine did not input-enable.** Only MISO/BUSY/DIO1 get
  `ulp_riscv_gpio_input_enable()`, so reading `IN` for pad 8/9/10 stays constant however those pads are driven - it told
  me nothing about NSS and I nearly concluded "the pin doesn't follow".
* **A "witness" bit that is ORed into the write it watches can destroy that write.** `#z` once set bit 18 *and* bit 23 in
  one `OUT_W1TS` word; the word never landed at all and the SET I was after came from the engine's own single-bit store.
  One pad per set/clear word.

Traps hit while doing this (each cost a run, all three are recorded rules already):

* Retiring a switch by wrapping it in `#if 0` when the thing under test sits in its `#else` deletes the thing too - the
  build that "proved" no write lands had no `hal_init()` in it (text 4 984 against 5 220 is what caught it).
* CMake keeps probe flags in its cache: `-DULP_EXTRA_DEFS` left at `-DULP_HAL=1 -DENGINE_TEST=1` made the *shipping*
  build overflow its region, and only reconfiguring with explicit zeros brought 7 931 back.
* A per-wake `printf` from the coprocessor floods the console and corrupts every reply. Reports are one-shot and short.

The next question is specific and cheap: why does a store from the interpreter's `wr32` not move a pad that a store from
`REG_WRITE` moves, in the same image, on the same core, to the same address? Difference candidates left, in order:
store-buffer drain at the end of the interpreter's turn (`ulp_riscv_halt()` immediately after), the width/alignment the
two compilers choose, and the possibility that the engine's write is followed by reads of other addresses which force
the write out. The cheap discriminator is to make Forth's `!` followed by an engine read of the same register.

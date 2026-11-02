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

## 6. What is NOT done, precisely

* **It is not yet a device phase.** `probe/repl/tools/lint_forth.py` refuses it as phase source: a block has no line
  boundaries, so `\` comments compile as words (R1 — 40-odd of them here), and R11 refuses a definition that does not fit
  inside one 92 B block (`LORA_INIT` is the long one). Packaging means `( … )` comments and a split that keeps each
  definition whole — `tools/fsplit.py` is the tool, and its safe-after rules forbid cutting before `CONSTANT`.
* **It has never run on a radio.** The host test proves the wire bytes; only the board can prove the packet. The board to
  use is the Heltec, which currently runs the C driver — flashing this phase needs the Forth firmware there, not the
  `probe/lora` C image.
* **The ~30–40 kHz estimate is an estimate.** `docs/27` describes the measurement (a counted loop timed by the main core);
  it needs our interpreter on this board, which is the same missing piece as above.

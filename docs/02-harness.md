# 02 — The harness: how we talk to the ULP without JTAG

The ULP has no JTAG, no `printf` by default, and a ~155 kHz heartbeat (6.46 µs per tick, measured —
not the 136 kHz / 7.35 µs the docs imply). Everything below exists to
make it *addressable*: a fixed shared-memory contract, a framed link over the main CPU, and a
workstation tool that turns that into `info`, `peek`, `forth` and `trace`.

Nothing here is speculative — each mechanism is either an IDF API verified in
[`00-background.md`](00-background.md) or a measurement scheduled in the
[experiment queue](#experiment-queue).

---

## 1. Topology

```
┌──────────────┐  USB CDC      ┌─────────────────────────┐   RTC slow mem    ┌──────────────┐
│  ulpctl      │ /dev/ttyACM1  │  main CPU (Xtensa)      │   0x50000000      │  ULP RISC-V  │
│  (python3)   │◄─────────────►│  bridge firmware        │◄─────────────────►│  Forth VM    │
│              │  framed proto │  · protocol             │  mailbox + rings  │  · threads   │
└──────────────┘               │  · RTC mem peek/poke    │                   │  · events    │
                               │  · image load/run       │                   └──────────────┘
       ▲                       └─────────────────────────┘
       │ esptool / openocd                 ▲
       └── /dev/ttyACM0 (USB-Serial/JTAG) ─┘   flashing only
```

**Port roles (deliberate):**

| Port | Device | Role |
| --- | --- | --- |
| `/dev/ttyACM1` | CH343 → UART0 | application console **and flashing**. The bridge's DTR/RTS drive EN/IO0, so this path can always force download mode — it is the recovery port. |
| `/dev/ttyACM0` | native USB-Serial/JTAG | JTAG debugging for the main core. **Not** the flashing default: it wedges when the app crashes (measured, E-017). |

Measured (E-017): after P06's image hung, `/dev/ttyACM0` still enumerated but every write timed out,
through the stub flasher, `--before usb-reset`, `--before no-reset` and DTR/RTS alike. `esptool -p
/dev/ttyACM1 chip-id` reset the chip and flashed normally on the first attempt. **Flash over UART0.**

Two independent ports means flashing never fights the console for the device. The ULP is **not**
debuggable on either port — that is the whole reason for §5.

---

## 2. The shared-memory contract

Everything the two cores exchange lives in one struct, at a **fixed offset inside the ULP image**, so
the generated `ulp_*.ld` gives the main CPU an absolute address (`0x50000000 + off`) and the ULP a
0-based one. One translation function, host side only:

```c
#define RTC_BASE 0x50000000u
static inline const void *ulp_to_host(uint32_t p) { return (const void *)(RTC_BASE + p); }
```

```c
/* ULP space. All addresses inside are ULP-space; the host translates on the way out. */
struct uforth_mailbox {
    volatile uint32_t magic;        /* 'UFTH' — refuses to run against a mismatched image */
    volatile uint16_t layout_ver;
    volatile uint16_t image_len;    /* bytes of image the host loaded */
    volatile uint32_t image_hash;   /* FNV-1a over the image bytes */

    volatile uint32_t wake_count;   /* increments once per wake, never reset */
    volatile uint32_t status;       /* ERR_* bitfield, sticky */
    volatile uint32_t overrun;      /* wake-budget misses since boot */
    volatile uint32_t last_cycles;  /* rdcycle delta of the previous wake */
    volatile uint32_t max_cycles;   /* worst observed wake */
    volatile uint32_t ip_shadow;    /* VM ip, written once per wake */
    volatile uint32_t drops_out;    /* bytes refused by the output ring */

    /* host → ULP: command/character stream, single producer, single consumer */
    volatile uint16_t cmd_head, cmd_tail;
    uint8_t  cmd[128];

    /* ULP → host: terminal output + status frames */
    volatile uint16_t out_head, out_tail;
    uint8_t  out[256];

    /* ULP → host: paging/storage requests (requirement R5/R6). The reply carries raw
       bytes and a status word; the host never returns a computed value. */
    volatile uint16_t req_seq;      /* incremented by the ULP for every new request   */
    volatile uint16_t req_op;       /* 0 = read page, 1 = write page, 2 = erase block */
    volatile uint32_t req_addr;     /* Forth virtual address (0x1… PSRAM, 0x2… flash) */
    volatile uint16_t req_flags;    /* REQ_PENDING / REQ_ACK                           */
    volatile uint16_t rsp_seq;      /* echoes req_seq when the reply is valid          */
    volatile uint16_t rsp_status;   /* 0 = ok, else ERR_CRC / ERR_RANGE / ERR_NO_SERVER */
    volatile uint16_t rsp_crc;
    volatile uint16_t faults;       /* page faults since boot                          */
    uint8_t  page[512];             /* one page of bytes, either direction             */
};
```

Rules that keep this honest:

* `magic` mismatch, `layout_ver` mismatch, or `image_hash` mismatch ⇒ the ULP refuses to interpret
  and publishes `ERR_IMAGE_MISMATCH`. A snapshot of a dictionary from a different build must fail
  loudly, never run.
* The host never writes `cmd_head`; the ULP never writes `cmd_tail`. One producer per index.
* Ring overflow increments `drops_out` (and refuses the write) rather than wrapping silently.
* Cross-core mutual exclusion uses the IDF Peterson lock (`ulp_riscv_lock_acquire/release`) around
  any multi-field update, and **only one host task may touch the mailbox** (the doc is explicit that
  the lock is not safe from multiple host threads). A re-entrancy guard in the bridge fails loudly
  rather than corrupting.

---

## 3. Wire protocol

Host ↔ bridge, over UART0. Deliberately boring so the failure modes are obvious:

```
frame := COBS( body ) 0x00
body  := ver:u8 | type:u8 | seq:u16 | len:u16 | payload[len] | crc16:u16
```

* **COBS** so any byte value can appear in the payload; `0x00` is the only delimiter.
* **CRC-16/CCITT** over `ver..payload`; a bad CRC is reported with the frame number and the frame is
  dropped — never "best effort" parsed.
* `seq` is echoed in the reply, so a timeout names the exact request that got no answer.
* Unknown `type` ⇒ `ERR_UNKNOWN_OP` reply, not silence.
* Maximum payload 64 bytes (the ULP line buffer is 128; a 64-byte chunk keeps the host stack small).

Operations (v1):

| Type | Name | Payload | Reply |
| --- | --- | --- | --- |
| `0x01` | `PING` | – | proto version, chip, IDF version |
| `0x02` | `INFO` | – | reserve bytes, image len/hash, hexdump of `status` |
| `0x10` | `LOAD` | `off:u32, len:u8, bytes` | running offset, hash so far |
| `0x11` | `RUN` | `period_ticks:u32` | `ulp_riscv_run()` result |
| `0x12` | `STOP` | – | timer stopped |
| `0x13` | `RESET` | – | `ulp_riscv_reset()` |
| `0x20` | `PEEK` | `ulp_addr:u32, len:u8` | bytes (bounds-checked against the reservation) |
| `0x21` | `POKE` | `ulp_addr:u32, len:u8, bytes` | bytes written |
| `0x22` | `SYM` | `name` | address from the generated `.ld`, plus the host address |
| `0x30` | `CONS_W` | characters | queued into `cmd[]` |
| `0x31` | `CONS_R` | – | up to 64 bytes from `out[]` |
| `0x40` | `TRACE` | index | one of `wake_count / last_cycles / max_cycles / ip_shadow / status / overrun` |
| `0x50` | `SNAP_SAVE` | name | dictionary image + state written to the storage partition (no NVS), returns hash |
| `0x51` | `SNAP_LOAD` | name | restore after `LOAD`, then `RUN` |

`PEEK`/`POKE` bounds: `0 <= ulp_addr` and `ulp_addr + len <= CONFIG_ULP_COPROC_RESERVE_MEM`. A
request outside that range gets `ERR_RANGE`, with both numbers in the reply. No clamping.

---

## 4. `ulpctl` — the workstation tool

Python 3, `pyserial` only (present: 3.5). No network access, no telemetry, no auto-install.

**Status: the passthrough half is built and working.** `probe/repl/main/repl_main.c` is the HP byte pump,
`probe/repl/src/ulp_repl.c` is the ULP REPL, `probe/repl/repl` is a terminal client. The framed protocol and the
`ulpctl` opcodes below are still design — they were designed before the machine ran, and the machine has since
settled two arguments for them:

* **the ULP sends a bare `\n`.** A client that clears `OPOST|ONLCR` (which `tty.setraw()` does) produces the
  staircase — every reply indented one more space. Re-enable output mapping, or pass `--imap lfcrlf` to
  `picocom`.
* **`\r` and `\n` are both end-of-line.** A CRLF file therefore runs the line *and* an empty line, giving two
  prompts. Strip CRLF before sending.

```
ulpctl info                 # chip, IDF, reserve, image hash, wake heartbeat
ulpctl monitor              # live: wake_count, cycles/wake, overrun, status
ulpctl peek ADDR [LEN]      # prints 0x0000_1234 (ulp) / 0x5000_1234 (host) side by side
ulpctl poke ADDR HEXBYTES
ulpctl load IMAGE.bin       # chunked LOAD + verify hash
ulpctl run --period-ms 100
ulpctl forth [FILE | -]     # REPL: lines go to cmd[], output comes back from out[]
ulpctl sym NAME             # resolve via ulp_*.ld, so scripts never hardcode addresses
ulpctl trace                # wake histogram + worst-wake cycle count
ulpctl snap save|load NAME
```

Behavioural rules for the tool (these are the ones that save hours):

* every command prints the port it used; a wrong port is a diagnosis, not a mystery;
* `--offline` refuses to do anything that requires the board, with a named reason;
* a timeout names the opcode, the sequence number and the elapsed time;
* `forth` sends one line at a time and waits for the prompt byte, so a hung ULP cannot queue up
  hundreds of lines that then execute in a burst later;
* the symbol table is parsed from the build output (`ulp_*.sym` / `ulp_*.ld`), so `ulpctl sym status`
  keeps working when the layout moves.

---

## 5. Debug channels inside the ULP

No JTAG means the observability has to be designed in:

| Channel | Cost | Answers |
| --- | --- | --- |
| `wake_count` + `last_cycles` (`rdcycle`) | 2 stores/wake | "is it alive", "how much of the budget did it use" |
| `ip_shadow` written at every wake exit *and* before every `PAUSE` | 1 store | "where did it stop" — the only postmortem we get |
| sticky `status` bits (`ERR_ADDR`, `ERR_DICT_FULL`, `ERR_STACK`, `ERR_IMAGE_MISMATCH`, `ERR_LINE_TOO_LONG`) | 1 store on error | named failure instead of a hang |
| `drops_out` | 1 store on refusal | "the console is too slow" as a number |
| trap | hardware | main CPU wakes with `ESP_SLEEP_WAKEUP_COCPU_TRAP_TRIG`; the host then dumps the mailbox |
| bit-banged UART TX (`ulp_riscv_uart_*`, 678 B image measured) | ~550 B of the 8176 | real output while the main CPU sleeps — **not** in v1, only when we go autonomous |

The design rule that follows from having no debugger: **every failure must be a bit in `status`, and
every wake must leave a trace in the mailbox.** A silent wrong answer is the one outcome we cannot
afford (see D1/D2 in the [prototype review](03-prototype-review.md)).

---

## 6. Iteration loops

| Loop | Change | Cost | Used for |
| --- | --- | --- | --- |
| **L0** | edit C/asm primitive → `idf.py build` → flash | ~60–120 s | primitives, VM core |
| **L1** | edit `boot_min.fs` / prelude → `ulpctl forth` | ~ms | high-level words, apps |
| **L2** | build a second ULP image → `ulpctl load` (no flash) | seconds | A/B two VM builds |
| **L3** | `ulpctl snap save` / `load` | ms | persistence, cold-boot restore |
| **L4** | `ulpctl peek`/`poke` on a live mailbox | instant | poking a variable to reproduce a state |

L2 is worth calling out: `ulp_riscv_load_binary()` copies a blob into RTC memory at runtime, so a
new ULP image can be tested **without reflashing the chip** — the image just has to be sent over the
protocol. That is the difference between a 90-second and a 2-second loop.

---

## 7. Experiment queue

Each experiment has a named pass, a named failure, and a design consequence. The full,
self-contained briefs live in [`probes/`](probes/README.md) — E1→P05, E2→P09, E3→P09, E4→P06,
E5→P06, E6→P08, with P01–P04 covering size, token width, paging and console, which this table
does not have.

| # | Question | Method | Pass | Failure ⇒ |
| --- | --- | --- | --- | --- |
| **E1** | cycles per RTC tick, cycles per token, cycles per wake | ULP loop: `rdcycle` before/after N tokens; publish `last_cycles`; host divides by `wake_count` and by a token counter | stable ratio over 1000 wakes, < 5 % spread | a budget model that cannot be met at any period ⇒ redesign (threading/asm primitives) |
| **E2** | image load + run from the protocol (L2) | `ulpctl load` two different images, run each | `image_hash` changes, `wake_count` restarts, no reflash | `load_binary` cannot be used at runtime ⇒ drop L2, keep L0 |
| **E3** | postmortem quality after a deliberate trap | an image with an illegal instruction | `status`/`ip_shadow` identify the offending word; the host prints it | trap path gives nothing ⇒ add a shadow PC ring |
| **E4** | what happens when a wake overruns its period | period = 1 tick, body busy-waits 10× the budget | documents *exactly* one of: tick lost, tick latched, re-entry | the event loop's deadline model must match reality, not the doc |
| **E5** | timer + RTC-IO wakeup together | enable both register bits, toggle a pin | both wake causes observed with correct attribution | GPIO events must be polled inside timer wakes instead |
| **E6** | dictionary snapshot round-trip | save to the storage partition, cold boot, restore | checksum equal, `WORDS` identical, one named failure on a corrupted header | the snapshot/rotation policy in `01-proposal.md` §7 does not hold ⇒ redesign the flash layout before any Forth feature work |

E1 and E4 are the two that can invalidate parts of the design, so they come first once the bridge
exists.

---

## 7b. Recovery: the bridge must never make the board unreachable

Measured the hard way (P06): an image that hung early left `/dev/ttyACM0` enumerating but refusing
writes, and the console silent on `/dev/ttyACM1`. No software path recovered it — not the esptool stub,
not `--before usb-reset`, not DTR/RTS control lines. The fix was physical.

That is a product hazard, not just an inconvenience: this board runs a language the user types into,
so "my word hung and now I can't flash it" is one bad line away. Three rules follow:

1. **The bridge task is watchdogged** (`esp_task_wdt`). A hung bridge resets the chip instead of eating
   the console and the flashing port. It must be the *first* thing enabled in `app_main`.
2. **The ULP can never hang the main cores.** R6 already forbids the ULP from running HP code; the
   remaining risk is a ULP program that never retires, which the wake budget turns into `overrun`
   rather than a stall. Every ULP `main` ends in `return` (→ `ulp_riscv_halt`) on all paths including
   errors.
3. **The console is on UART0, not the native USB.** If a hang takes the USB-JTAG peripheral, the
   console survives long enough to say so — which is how this failure was diagnosable at all.

Recovery procedure, in order, and it belongs in the README next to the flash command:

| Step | Action | When it works |
| --- | --- | --- |
| 1 | `esptool -p /dev/ttyACM0 chip-id` | the board is alive |
| 2 | press **EN** (reset) | app hang, USB still fine |
| 3 | hold **BOOT**, press **EN**, release BOOT | app disables USB or reboots into itself |
| 4 | unplug USB for 5 s, replug | USB-JTAG peripheral wedged |

## 8. What "working" means

The harness is done when, from a cold shell, this sequence needs no manual steps and no guessing:

```sh
idf.py -p /dev/ttyACM0 flash
ulpctl --port /dev/ttyACM1 info
ulpctl --port /dev/ttyACM1 load build/ulp_main.bin
ulpctl --port /dev/ttyACM1 run --period-ms 100
ulpctl --port /dev/ttyACM1 monitor          # wake_count climbing, overrun 0
ulpctl --port /dev/ttyACM1 forth            # : SQ DUP * ; 5 SQ .  ->  25 ok
```

and when it fails, it says which of those four things is wrong.

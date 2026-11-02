/* repl_main.c — the HP side: a dumb byte pump between UART0 and the ULP's two rings.
 *
 * It does not parse Forth, does not queue commands, and does not decide anything. That is the whole
 * point of the split: the interpreter is on the ULP, this core moves bytes and nothing else (R6).
 *
 * You talk to it with any terminal:  picocom -b 115200 /dev/ttyACM1
 *
 * GUARDRAIL: the ULP is armed only after the banner is printed and the port is up. A board that is
 * armed before it can talk is a board that wedges silently — the P06 lesson, which cost a physical
 * reset and the firmware that was on the chip.
 *
 * GUARDRAIL: one writer per ring index. This task writes cmd_head and out_tail; the ULP writes
 * cmd_tail and out_head. Both are u32-aligned, so no lock is needed for the counters, and adding one
 * would be the only place a deadlock could live.
 */
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "soc/soc.h"
/* GUARDRAIL: RTC_GPIO_* and RTC_IO_TOUCH_PAD0_* live in soc/rtc_io_reg.h, not in soc.h - the pad driver pulls it in
 * transitively for its own translation units, so #g failed to compile the first time with "undeclared". */
#include "soc/rtc_io_reg.h"
/* GUARDRAIL: F-163: the 544-word register diff found it in RTC_CNTL_ULP_CP_CTRL_REG, so that block is included. */
#include "soc/rtc_cntl_reg.h"
#if defined(FOREIGN_ULP)
/* GUARDRAIL: F-165 - the last cell of the matrix: boot the ULP program that is KNOWN to work on this board (probe/lora's,
 * which reports tx_ok rising) from THIS app. Nothing about the pads, flags, config or image content can be the cause any
 * more, so the question is asked directly: which app, which program. The Forth bridge commands cannot work here (the
 * foreign image defines none of repl_cmd/repl_out/...), which is why the ring-size handshake is skipped - and why the
 * only witness is the pad bit the HP core clears and that image's own store sets.
 * Regenerate src/foreign_ulp.h with tools/embed_ulp.py after every rebuild of probe/lora.
 */
#include "../src/foreign_ulp.h"
#endif
/* GUARDRAIL: SENS holds the RTC IO MUX clock gate (SENS_SAR_PERI_CLK_GATE_CONF_REG bit 31). The C driver's ULP enables
 * it from the ULP via ulp_riscv_gpio_init; our ULP cannot write any peripheral (F-157), so it has to be done HERE. */
#include "soc/sens_reg.h"
/* GUARDRAIL: gpio_reset_pin() needs driver/gpio.h; rtc_gpio_* comes from driver/rtc_io.h. */
#include "driver/gpio.h"
/* The ULP writes ONE byte per message into repl_out[] (0x81..) and msg_expand.h turns it back into text
 * here. Every other byte in that ring is ASCII (echoed input, digits, the offending word, '?', '\n'), so a
 * byte >= 0x80 is unambiguously a code, and the expansion is a substitution at the same position in the
 * stream: the transcript keeps its bytes and its order against the echo.
 * GUARDRAIL: a relative include, not an include dir. main/CMakeLists.txt deliberately keeps
 * COMPONENT_ADD_INCLUDEDIRS empty so the ULP can never pick up a different uforth.c; adding src/ to the
 * host's search path to reach one header would undo that. One list, both cores (R6). */
#include "../src/msg_expand.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "esp_sleep.h"
#include "ulp_riscv.h"
#include "ulp_main.h"
#include "flash_store.h"
#include "esp_system.h"
#include "driver/rtc_io.h"
#include "esp_rom_sys.h"   /* GUARDRAIL: esp_rom_delay_us is the bounded hot poll at the end of the server loop - see the note there */

static void seed_poll(void);   /* defined after blkfile[]; called from the UART pump */

#define CONSOLE_UART  UART_NUM_0
#define CONSOLE_BAUD  115200

static const char *TAG = "repl";

/* The generated header declares these as uint32_t; the ring members are bytes inside them, so the
 * address is what matters. Same trick P22 proved with mem[]. */
#define CMD_BYTES  ((volatile uint8_t *)&ulp_repl_cmd)
#define OUT_BYTES  ((volatile uint8_t *)&ulp_repl_out)
/* GUARDRAIL: must equal the ULP's CMD_SIZE/OUT_SIZE. They lived in two files with no link between
 * them; when the ULP rings shrank to 64/128 and this stayed at 128/256, the host wrote past the end of
 * repl_cmd[] into repl_out[] and the REPL replayed old characters. The boot assert below is the link. */
#define CMD_SIZE   64u
#define OUT_SIZE   128u
#define CMD_MASK   (CMD_SIZE - 1u)
#define OUT_MASK   (OUT_SIZE - 1u)

extern const uint8_t bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t bin_end[]   asm("_binary_ulp_main_bin_end");

/* ---- R5: the block byte server -------------------------------------------------
 * The ULP cannot reach flash or PSRAM: it sees only its own 256 B window in RTC RAM. This task is the
 * other end of the protocol — it polls one flag, copies bytes, checksums, and writes the status LAST so
 * the ULP can never read a half-copied buffer. Backend today is an 8 x 256 B RAM array; flash (R7) plugs
 * in here without touching the protocol, which is the whole point of keeping the coprocessor dumb.
 * GUARDRAIL: the ULP links at address 0, so the addresses it publishes are OFFSETS into RTC slow memory.
 * Dereferencing one directly panics: LoadProhibited, EXCVADDR = the mailbox offset (E-073).
 * GUARDRAIL: created BEFORE the console pump: a higher-priority task that never yields can starve app_main,
 * and then anything created after it silently never exists. */
#define ULP_RAM_BASE ((uint32_t)SOC_RTC_DATA_LOW)

static void console_task(void *arg)
{
    (void)arg;
    /* GUARDRAIL: no read buffer here. The UART is drained one byte at a time by seed_poll(), which owns both
     * disciplines, and a 64-byte `buf` sat here unused for exactly that reason - the compiler named it every build.
     * The old form read a burst into `buf` and `break`ed when the ring filled, which had already taken those bytes
     * out of the UART FIFO: measured as an 88-character definition arriving mangled (`ARITH?`, then `DUP?`) with the
     * tail silently lost. The whole-line refusal that replaced it lives in seed_poll ("line too long ... NOT sent").
     * A warning that is always there is how a real dead variable gets ignored later. */

    for (;;) {
        /* the UART is read by seed_poll(), which forwards non-seed lines into the ring */
        seed_poll();   /* fast block seeding, host-side (see seed_poll) */

        /* out ring -> UART */
        uint32_t oh = ulp_repl_out_head;
        uint32_t ot = ulp_repl_out_tail;
        if (oh != ot) {
            /* GUARDRAIL: the expansion AND the ring bookkeeping live in msg_drain_ring() so the host test
             * drives the same code, including the "does not fit" path: a message dropped instead of retried
             * looks exactly like a healthy line with no reply, and that path only fires when the staging
             * buffer is nearly full. */
            char out[MSG_OUT_TEXT];
            uint32_t n = msg_drain_ring(OUT_BYTES, OUT_MASK, oh, &ot, out, sizeof out);
            ulp_repl_out_tail = ot;
            if (n) uart_write_bytes(CONSOLE_UART, out, n);
        }

        vTaskDelay(1);
    }
}

/* GUARDRAIL: the server body is the one the experimental tree verified on hardware (E-074); it is
 * 2048 B of stack on the HP and never touches the ULP's pool. */
/* GUARDRAIL: 8 -> 128 blocks (16 KB at the ULP's 128 B transfer size). Eight blocks is 1 024 B of source,
 * about 600-800 B of compiled code, which is LESS than the 1 183 B of resident app space the overlay build
 * has - so overlays could not raise the program ceiling at all while the store was 8 blocks. Measured on the
 * board: blocks 0..7 answered and 8+ nacked. The host has megabytes; the ULP's RAM is the scarce side, so
 * the store is the cheap place to buy capacity. 128 x 256 B = 32 KB of host RAM. */
#define BLK_N     128
#define BLK_SZ    256
static uint32_t blk_sz;      /* transfer size, published by the ULP */
/* GUARDRAIL: test-only stall for the op-3 race test. `#s <ms>` makes this task sleep once, so the ULP times out on its
 * next block request. Main-core only, zero ULP bytes; without it the race cannot be provoked deliberately. */
static uint32_t stall_ms;
static uint32_t apply_stall_ms;   /* test-only: stall INSIDE the op-3 critical section, after the age check */
static int blk_out_prev;      /* level of the ULP's outstanding-request flag, for `#u` only */
/* GUARDRAIL: freshness is a LEVEL, not an edge. It used to be `fresh = blk_out && !blk_out_prev`, i.e. "a request I
 * happened to SAMPLE arrive" - and this task polls only once per FreeRTOS tick (10 ms at CONFIG_FREERTOS_HZ=100, which
 * R3 measured: pdMS_TO_TICKS(2) is 0). An ULP that cleared and re-raised blk_out between two polls was therefore never
 * serviced: it waited out BLKWAIT (~845 ms), returned BK_NOSERVER, deliberately left blk_out set, and every later adopt
 * answered BK_BUSY. Measured as a chain stalling at the SECOND hop, and as a test that passed 19/19 one run and died at
 * the first adopt the next. A 20 ms gap in the launcher hid it; this removes the need for the gap.
 *
 * The level that cannot be missed is the mailbox's own answered word: the ULP writes 0 when it issues a request and
 * this core writes 1 when it answers. So "outstanding AND not yet answered" IS the pending request, whatever happened
 * between two polls. The age check below still does its job - it is now measured from when this core first SAW the
 * pending level, and reset by an answer, so a missed transition cannot make a fresh request look stale. */
static uint32_t req_ms;       /* when this core first saw the current PENDING request (0 = none) */
/* GUARDRAIL: one `printf` per adopt was 4.5 of the 5.1 ms a phase hop cost. At 115200 baud a 55-character line is
 * ~4.8 ms of UART, and this task cannot poll while it is writing, so the chain waited for its own log line. The answer
 * is written BEFORE the print (see the op-3 handler), so only latency was lost, never correctness. `#v 1` brings it
 * back for debugging; the default is quiet because a chain of 24 phases printed 24 identical lines nobody reads, and
 * the STATUS already travels back to Forth (PICKX checks it). Failures stay unconditional - a REFUSED adopt is never
 * silent. */
static int img_verbose;
/* GUARDRAIL: see the note at the bottom of the server loop - the hot counter is the latency fix that does not change
 * the system-wide tick rate. 8 x 150 us = 1.2 ms of fast polling after each service, which covers the ~100-300 us a
 * chained phase needs before it asks again. */
static int hot;
/* GUARDRAIL: `#u` showed the ULP silent while the HP console answered, which cannot distinguish "the ULP never asked"
 * from "the HP never answered". This ring records the last 16 requests this task actually SERVICED (op, blk, ms since
 * boot). It lives in .bss, NOT RTC memory: RTC slow RAM is fully owned by the ULP pool (adding 192 B there overflowed
 * rtc_slow_seg by 188 B), and `#u` is answerable DURING the hang because the HP console stays alive - measured. */
static uint32_t req_log[16][3];   /* op, blk, ms */
static uint32_t req_idx;
static uint32_t req_total;
/* GUARDRAIL: when this task first SAW the request. The ULP's wait (BLKWAIT 2 000 000 iterations) is ~845 ms MEASURED
 * on hardware, and on a timeout the ULP deliberately leaves blk_out set - so the flag alone cannot distinguish "still
 * waiting" from "gave up". A destructive op (image load) must therefore be applied only inside a conservative fraction
 * of that window; outside it, refuse loudly instead of adopting a dictionary the machine was told it does not have.
 * Failure mode is a named nack, never silent corruption. */
/* GUARDRAIL: this declaration is now `req_ms` (above, next to the level test it belongs to). The old `edge_ms` was the
 * same idea KEYED TO A SAMPLED EDGE, so a missed poll made a fresh request look old; keeping the name would have kept
 * the bug's shape. One variable, one meaning: "when this core first saw the request that is pending right now". */
static uint8_t blkfile[BLK_N][BLK_SZ];   /* the ARRAY is sized for the max; blk_sz is the transfer size */
/* GUARDRAIL: blkfile is now a CACHE of the flash store, not the store. Placing it in flash is what makes a paged program
 * survive reset; keeping the array keeps the 16 existing direct indexes correct, but every WRITE must be committed or the
 * data dies with the power. `store_ok` is false when the superblock failed validation, so writes fail by NAME instead of
 * quietly living only in RAM - which would look like a working store that forgets everything at reset. */
static int store_ok;

/* GUARDRAIL: a write that must NOT touch flash still has to be recorded, or the next `#f` silently drops it - the
 * coherence bug class that made an image's last partial block look corrupt after a reboot. */
static int blkfile_dirty;   /* declared before use: C needs it above blk_dirty, not below */
static void blk_dirty(uint32_t blk)
{
    (void)blk;
    blkfile_dirty = 1;
}

/* GUARDRAIL: BISECT_NO_FLASH_WRITE isolates "any flash write" from everything else: main (no store) passed 15/15, this
 * branch with this defined passed 15/15 twice, and with it undefined it hangs at phase 1-3 - so a flash erase/program is
 * the trigger. It is now UNDEFINED again (writes live) and this switch must stay undefined in any shipping build. */
/* #define BISECT_NO_FLASH_WRITE 1 */

static void blk_commit(uint32_t blk)
{
    blkfile_dirty = 1;                 /* recorded, so `#f` would still commit it in a real build */
#if defined(BISECT_NO_FLASH_WRITE)
    (void)blk;
#else
    if (!store_ok) return;             /* already reported at boot; do not spam per block */
    int r = fs_write(blk, blkfile[blk]);
    if (r != FS_OK) printf("store: WRITE FAILED block %u: %s\n", (unsigned)blk, fs_strerror(r));
#endif
}

static void store_boot(void)
{
    int r = fs_init();
    if (r != FS_OK) {
        printf("store: REFUSED %s\n", fs_strerror(r));
        store_ok = 0;
        return;
    }
    store_ok = 1;
    for (uint32_t b = 0; b < BLK_N && b < fs_block_count(); b++) {
        int rr = fs_read(b, blkfile[b]);
        if (rr != FS_OK) { printf("store: READ FAILED block %u: %s\n", (unsigned)b, fs_strerror(rr)); store_ok = 0; return; }
    }
    printf("store: flash %u blocks x %u B (%u blocks/sector cache)\n",
           (unsigned)fs_block_count(), (unsigned)fs_block_size(), 32u);
}
/* ---- ULP stack high-water probe (row 10 of the A/B) ---------------------------------------------------------
 * The ULP stack grows down from ulp___stack_top (0x50001ff0) into .bss, so an overflow corrupts engine state
 * instead of faulting - that is how a 336 B chain silently broke block I/O earlier. The main core can WRITE RTC
 * slow RAM, so it paints the region above the image with 0xA5 before the ULP starts, and afterwards reports the
 * lowest byte the ULP has touched. That turns the frame arithmetic into a measurement at zero cost in ULP bytes.
 *
 * GUARDRAIL: the paint starts at 0x1EB0, not at pool_end. The pool ends at 0x1EA7 with this image (7847 B) and
 * painting from below that would erase mem[]/tib/mailbox - a "measurement" that destroys the thing it measures.
 * If the image grows past 0x1EB0 this must move down with it, which is why the end is asserted at boot.
 */
/* GUARDRAIL: the base is READ OFF THE MAP, not guessed. `riscv32-esp-elf-nm -n ulp_main.elf` puts the highest
 * .bss symbol at `junk` 0x1EA8, so the image ends at 0x1EA9 and the stack occupies [0x1EA9, 0x1FF0) = 327 B.
 * The first attempt used 0x1EB0 from the pool arithmetic and reported 1 byte, which is impossible for a machine
 * that enters vm_enter per token - the paint must be verified against this base before any number is believed.
 * GUARDRAIL: leave the injected report OFF for shipping images (comment out CANARY below): it puts a stray
 * "<n> ." line on the operator's console four seconds after boot.
 * GUARDRAIL: never write a nested comment terminator inside this comment. Writing the flag as a quoted C comment
 * here ended the enclosing block early, so the two functions below became comment text and the call in app_main
 * failed with "implicit declaration" - which reads like a missing prototype, not a comment bug. */
/* GUARDRAIL: OFF. Enabling it corrupts the console: injecting a line into the command ring made the ULP emit
 * binary noise (0x78/0x00 bytes) instead of text, so the report destroyed the very channel it used. The ring is
 * single-writer per index and the UART pump owns cmd_head in the same task, which is the likely collision - but
 * the fix is not a patch here: publish the number into an RTC cell and let a FORTH word read it, so the report
 * travels through the interpreter instead of being spliced into its input.
 * GUARDRAIL: the base IS settled: nm -n on ulp_main.elf puts the highest .bss symbol at `junk` 0x1EA8, so the
 * image ends at 0x1EA9 and the stack occupies [0x1EA9, 0x1FF0) = 327 B. 0x1EAC is the map's answer, not the
 * pool arithmetic that guessed 0x1EB0. */
/* GUARDRAIL: the paint is ON, the ring-injection report is GONE. Injecting a Forth line to print the number corrupted the
 * console (binary noise) because the ring is single-writer per index and the UART pump owns cmd_head in the same task.
 * The measurement now goes out through `#k`, which is an HP console command: no ULP bytes, no ring writer, no collision. */
#define CANARY 1
/* GUARDRAIL: the paint base must be DERIVED from the pool budget, never copied from a map. It was 0x1EAC "from nm", and
 * when the image grew past it - by TWO BYTES, 7 877 -> 7 879 - the paint started covering live .bss: `repl_blk_out` and
 * `repl_blk_req` are only ever ZEROED at boot (everything else in that area is assigned by the ULP at run time, which is
 * why only the flags broke), so both became 0xA5A5A5A5 for ever. A "flag" of 0xA5A5A5A5 is truthy to a level test, so
 * the block server answered a request nobody had made 5 600 times a second (measured: 12 028 in 2 s), trampling the
 * transfer window under a real LOAD - which surfaced as `ERR_CRC` on the first block read and a cascade of NAME?.
 * The budget below is the SAME number flash_safe.sh refuses to exceed (POOL=7892), so the paint can never overlap the
 * image unless the gate is bypassed: image end <= 0x1EC7 < base 0x1ED0. If POOL changes there, change it here. */
/* GUARDRAIL: this constant MUST equal POOL in flash_safe.sh. It is the point where the stack paint begins, so a value
 * below the real image size paints live .bss and the boot assertion fires - which is exactly what happened when the
 * hardware gate in P() moved the image to 7 903 B: "the stack paint is covering live .bss". The assertion is the feature;
 * the fix is to keep the two numbers tied (F-131's lesson: an instrument that writes must derive its base from an
 * enforced budget). */
#define ULP_POOL_BUDGET 7932u
#define STACK_TOP   0x1FF0u
/* the paint starts exactly AT the budget: flash_safe.sh refuses any image whose size passes ULP_POOL_BUDGET, so the
 * image can never reach this address. Deriving it from STACK_TOP instead was off by 16 B (0x1FF0, not 0x2000) and put
 * the base three bytes inside the image - the same mistake in a new dress. */
#define CANARY_BASE ((uint32_t)ULP_POOL_BUDGET)
#define CANARY_VAL  0xA5u

static void canary_paint(void)
{
    volatile uint8_t *p = (volatile uint8_t *)(ULP_RAM_BASE + CANARY_BASE);
    uint32_t i;
    for (i = 0; i < STACK_TOP - CANARY_BASE; i++) p[i] = CANARY_VAL;
}

static uint32_t canary_used(void)
{
    volatile uint8_t *p = (volatile uint8_t *)(ULP_RAM_BASE + CANARY_BASE);
    uint32_t i, low = STACK_TOP - CANARY_BASE;
    /* GUARDRAIL: keep the MINIMUM changed index, not the last one. The old loop assigned unconditionally, so it ended
     * holding the HIGHEST changed byte and reported `324 - 323 = 1 B` for a machine that obviously uses more - the
     * "impossible 1 byte" that sent two earlier attempts looking for a wrong base. The base was always right. */
    for (i = 0; i < STACK_TOP - CANARY_BASE; i++) if (p[i] != CANARY_VAL && i < low) low = i;
    /* the stack grows DOWN from STACK_TOP, so the deepest touch is the LOWEST painted byte that changed */
    return (low < STACK_TOP - CANARY_BASE) ? (STACK_TOP - CANARY_BASE - low) : 0u;
}

/* ---- the resident IDENTITY sum, written once ---------------------------------------------------------------
 * An image carries absolute addresses and calls resident words by xt, so an adopt is only safe onto the dictionary
 * it was built on. This sum is that check, and its range is the whole point:
 *
 *   [V_SEAL, blk_off)   the resident HEADER area, and NOTHING else.
 *
 * Header entries are 3 bytes, `imm1 | xt11 | hash12` (P54), so this region pins every resident name AND the xt the
 * image will call - the only mismatch that makes an adopt execute garbage.
 *
 * GUARDRAIL: it must NOT cover [52, cs). That was the original range and it is the launcher's LIVE state: `SEL`, `q`,
 * `qh`, `qt`, `qovf`, `brt`, `bh`, `bl`, `curblk` all live in it, and pressing `k` on the menu writes `SEL`. Measured
 * with tests/adopt_sum.py on the device: the header area was byte-identical through three adopts and a `SEL` write,
 * while [52, cs) moved by exactly 1 - sum 36585 -> 36586 - and the loader refused a dictionary that had not changed
 * at all (`img: REFUSED resident dictionary changed (sum 36586, built on 36585)`, which is verbatim the message
 * docs/25 recorded as unexplained). A guard that fires on ordinary use is worse than no guard: it teaches the
 * operator to ignore the refusal.
 *
 * GUARDRAIL: the tradeoff is stated, not hidden. A resident BODY edit that keeps every header and every length is not
 * detected here (nor by the pointer checks). Detecting it would mean knowing which resident bytes are mutable cells,
 * which the header table does not record - a bigger machine change than this guard is worth, and a body edit that
 * keeps the interface leaves a stale image perfectly callable.
 *
 * GUARDRAIL: one derivation, three callers (#d, op 3, and the retired #l). The old range was spelled out at each
 * site, which is how the same bug gets fixed twice in two places and left in the third (R6).
 */
static unsigned resident_sum(const uint8_t *mi, unsigned top)
{
    unsigned hs = (unsigned)mi[12] | ((unsigned)mi[13] << 8);   /* V_SEAL = the sealed V_LATEST */
    unsigned s = 0, k;
    /* GUARDRAIL: clamp an impossible seal into range instead of returning a CONSTANT. A constant would match
     * itself, so two differently-corrupt dictionaries would agree and the guard would pass the one case it must
     * never pass. Clamping keeps the answer a function of the bytes. */
    if (hs < 52u) hs = 52u;
    if (hs > top) hs = top;
    for (k = hs; k < top; k++) s = (s + mi[k]) & 0xffffu;
    return s;
}

static void seed_poll(void)
{
    /* GUARDRAIL: this lives AFTER blkfile[] and BLK_N because it writes them; the first placement sat above the
     * store's declaration and failed with "'BLK_N' undeclared", which reads like a missing include.
     * Line format:  #b <block> <hex bytes>   - intercepted here, never forwarded to the ULP. */
    /* GUARDRAIL: 320 bytes, not 180. A full 128-byte block arrives as ~264 hex characters plus the "#b N " prefix,
     * so a 180-byte line buffer silently seeded 87 of 128 bytes per block and the phase source could not assemble
     * (measured as IDX? / Z1? during the load, and as a readback of 87 bytes). Size for the worst case. */
    static char ln[320];
    static int n;
    /* GUARDRAIL: a terminal PROGRAM needs keystrokes as they happen, not lines. In raw mode every byte goes straight into
     * the ULP's command ring, where the running program's KEY consumes it - the interpreter is blocked inside that
     * program, so there is no second reader. `!LINE` (scanned in the byte stream, never forwarded) leaves raw mode; it is
     * how the host gets its line discipline back without the operator having to press Enter on a magic word. */
    static int raw_mode;
    static char rawbuf[5];
    static int rawn;
    static TickType_t raw_skip_until;   /* the CR that ends the !RAW line is not a keystroke */
    static uint8_t keyq[8];   /* raw bytes waiting for the program to drain the keybox */
    static uint32_t keyq_head, keyq_tail;
    unsigned char c;
    /* hand the program one queued byte whenever its keybox is free */
    if (keyq_head != keyq_tail && ulp_repl_keybox == 0xFFFFFFFFu) {
        ulp_repl_keybox = keyq[keyq_head % sizeof keyq];
        keyq_head++;
    }
    while (uart_read_bytes(CONSOLE_UART, &c, 1, 0) == 1) {
        if (raw_mode) {
            /* GUARDRAIL: forward a byte the moment it CANNOT be part of `!LINE`. The first version held five bytes and
             * only flushed when the buffer filled, so a single keystroke was never delivered - measured: 'j' pressed,
             * nothing drawn. The prefix test keeps the escape sequence unharmed and makes every other byte immediate. */
            /* GUARDRAIL: swallow the CR that terminates the `!RAW` line the operator/host just sent. It arrives AFTER the
             * line was consumed and would be delivered as key 13 (Enter) - measured: the app started, received the CR
             * immediately, treated it as "quit" and exited before the first keystroke could be drawn. */
            /* GUARDRAIL: this used to swallow "the next CR", but the CR that ends `!RAW` is consumed by the LINE parser,
             * so the flag stayed armed and ate the operator's FIRST keypress whenever it was Enter - measured: pressing
             * Enter on a menu did nothing at all, and only the following key worked. The terminator may only be skipped
             * inside the same dispatch, so the window is 50 ms of ticks: no human presses a key that fast. */
            if (c == '\r' || c == '\n') {
                if (raw_skip_until && xTaskGetTickCount() < raw_skip_until) { raw_skip_until = 0; continue; }
            }
            rawbuf[rawn++] = c;
            while (rawn > 0) {
                int is_pref = (rawn <= 5) && !memcmp(rawbuf, "!LINE", (size_t)rawn);
                if (rawn == 5 && is_pref) { raw_mode = 0; rawn = 0; break; }   /* the escape sequence arrived */
                if (is_pref) break;                                            /* may still become it */
                /* GUARDRAIL: raw keystrokes go to the KEYBOX, not to the command ring (writing them to the ring made the
                 * interpreter treat them as the rest of the line being executed: KEY answered 75, the 'K' of "KEY").
                 * GUARDRAIL: QUEUE here rather than write straight through. The ULP drains one byte per program poll, and
                 * an arrow key is THREE bytes (ESC [ A) arriving within microseconds - with a pass-through write the
                 * middle byte was lost and arrows did nothing while j/k worked. Holding up to 8 bytes on this side costs
                 * nothing on the ULP and delivers sequences intact. */
                keyq[keyq_tail % (sizeof keyq)] = rawbuf[0];
                keyq_tail++;
                rawn--;
                memmove(rawbuf, rawbuf + 1, (size_t)rawn);
            }
            continue;
        }
        if (c == '\n' || c == '\r') {
            ln[n] = 0;
            if (!strcmp(ln, "!RAW")) {
                raw_mode = 1; rawn = 0; keyq_head = keyq_tail = 0;
                raw_skip_until = xTaskGetTickCount() + pdMS_TO_TICKS(50);
                /* GUARDRAIL: no message here. The switch happens while a full-screen program owns the terminal, so a
                 * line of text lands in the middle of its screen (measured: "raw: keystrokes go to the program now"
                 * printed across the app's title bar). The mode is documented instead of announced; !LINE still works. */

                n = 0;
                continue;
            }
            if (n > 4 && ln[0] == '#' && ln[1] == 'b' && ln[2] == ' ') {
                unsigned blk = 0, k = 3, w = 0;
                int hi = 0, bad = 0;
                while (ln[k] >= '0' && ln[k] <= '9') blk = blk * 10u + (unsigned)(ln[k++] - '0');
                while (ln[k] == ' ') k++;
                /* GUARDRAIL: blank the block BEFORE writing the payload. Writing only the payload leaves the rest
                 * of the block holding whatever a previous seed put there; LOAD then compiles the new text and
                 * trips over the stale tail, which errors the line and REWINDS the phase - measured as a phase
                 * whose own definitions vanished (Z6?, and a minimal `: ZZ 42 . ;` in one block + `ZZ` in the
                 * next answering ZZ?). */
                if (blk < BLK_N) {
                    unsigned i2;
                    for (i2 = 0; i2 < sizeof(blkfile[0]); i2++) blkfile[blk][i2] = (uint8_t)' ';
                }
                while (ln[k] && w < (unsigned)sizeof(blkfile[0]) * 2u) {
                    int v;
                    char d = ln[k];
                    if (d >= '0' && d <= '9') v = d - '0';
                    else if (d >= 'a' && d <= 'f') v = d - 'a' + 10;
                    else if (d >= 'A' && d <= 'F') v = d - 'A' + 10;
                    else { bad = 1; break; }
                    if ((w & 1u) == 0u) hi = v;
                    else if (blk < BLK_N) blkfile[blk][w >> 1] = (uint8_t)((hi << 4) | v);
                    w++; k++;
                }
                if (!bad && blk < BLK_N) { blk_commit(blk); printf("seed: block %u <- %u bytes\n", blk, w / 2u); }
                else                     printf("seed: REJECTED (bad hex, or block >= %d)\n", BLK_N);
                fflush(stdout);
                n = 0;
                continue;                       /* a seed line is consumed here, never forwarded */
            }
            /* GUARDRAIL: `#d` builds an IMAGE of the loaded phase on the MAIN CORE, at zero ULP bytes. A Forth dumper
             * cannot do it: given the same 690 B window it needs ~370 B for the copy loop plus the 516 B phase, measured
             * as ERR_DICT. The main core already reads the ULP's mem[] (ULP_RAM_BASE + ulp_repl_mem_addr) and owns the
             * block store, so it is the right place for this - no parsing, no window, no resident cost.
             * Format:  #d <desc_blk> <code_start> <code_end> <hdr_start> <hdr_end>
             * The four addresses come from the machine: `bh @ . bl @ . HERE . LATEST .` after SEAL.
             * Descriptor v2 (20 B then the payload): FI(2) ver(1) code_len(2) hdr_len(2) code_start(2)
             * hdr_start(2) payload_sum(2) resident_sum(2) entry_xt(2) reserved(3).
             * GUARDRAIL: the ENTRY XT is part of the descriptor because a binary load cannot run what the phase's
             * top-level text ran (hook assignment, PUMP, initial stores). The caller receives the xt and EXECUTEs it;
             * the phase itself must define things and nothing else. */
            if (n > 4 && ln[0] == '#' && ln[1] == 'd' && ln[2] == ' ') {
                unsigned v[6] = {0}; int k = 3, vi = 0, bad2 = 0;
                unsigned vseal_now;
                {   /* the machine's own sealed LATEST: the caller must not be the oracle for it */
                    const uint8_t *sv = (const uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr);
                    vseal_now = (unsigned)sv[12] | ((unsigned)sv[13] << 8);
                }
                while (vi < 6) {
                    while (ln[k] == ' ') k++;
                    if (!ln[k] || ln[k] < '0' || ln[k] > '9') { bad2 = 1; break; }
                    while (ln[k] >= '0' && ln[k] <= '9') v[vi] = v[vi] * 10u + (unsigned)(ln[k++] - '0');
                    vi++;
                }
                if (bad2 || vi < 6) {
                    printf("dump: REJECTED (want: #d <blk> <cs> <ce> <hs> <he> <entry_xt>)\n");
                } else if (v[0] + 1u >= BLK_N || v[2] < v[1] || v[4] <= v[3]
                           || 20u + (v[2] - v[1]) + (v[4] - v[3]) > (BLK_N - v[0]) * 128u) {
                    printf("dump: REJECTED (range or block overflow)\n");
                } else if (v[4] != vseal_now) {
                    /* GUARDRAIL: `he` must BE the machine's sealed LATEST - `bl @ .`, not `LATEST .`. Checked here, with
                     * the other geometry checks, because the header bytes are COPIED from [v[3], v[4]): a wrong `he`
                     * bakes a corrupt image that no adopt will ever accept, and the refusal would then surface at load
                     * time as "sealed pointers moved" - a message about the guest, not about the caller's mistake. */
                    printf("dump: REJECTED (hdr_end %u is not the sealed LATEST %u - pass `bl @ .`, not LATEST)\n",
                           v[4], vseal_now);
                } else {
                    const uint8_t *memimg = (const uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr);
                    /* GUARDRAIL: the descriptor SHARES the first payload block (12 B of its 128), it does not get a
                     * block of its own. Measured: 576 B of payload is 5 blocks, and reserving a block for the
                     * descriptor made it 6 - which is the difference between passing the <=65% gate and failing it. */
                    unsigned i2, payload = 0, sum = 0, blk = v[0], off = 20;
                    for (i2 = 0; i2 < BLK_SZ; i2++) blkfile[v[0]][i2] = (uint8_t)' ';
                    /* GUARDRAIL: flush on the TRANSFER size (blk_sz, published by the ULP = 128), never on BLK_SZ.
                     * BLK_SZ is only the array's row WIDTH (256). Flushing at 256 packed two blocks into one row, so the
                     * ULP read the first 128 bytes and everything after was invisible - measured as image byte 0
                     * matching while bytes at 127, 300 and 500 did not.
                     * GUARDRAIL: this macro must stay on ONE line. Splitting it to add the comment above broke the
                     * backslash continuation, the body became real code, and the build failed with 'by_' undeclared. */
#define DUMP_EMIT(byte) do { uint8_t by_ = (uint8_t)(byte); sum = (sum + by_) & 0xffffu; blkfile[blk][off++] = by_; if (off == (blk_sz ? blk_sz : 128u)) { off = 0; blk++; } payload++; } while (0)
                    for (i2 = v[1]; i2 < v[2]; i2++) DUMP_EMIT(memimg[i2]);   /* code */
                    for (i2 = v[3]; i2 < v[4]; i2++) DUMP_EMIT(memimg[i2]);   /* headers */
#undef DUMP_EMIT
                    {
                        uint8_t *d2 = blkfile[v[0]];
                        unsigned cl = v[2] - v[1], hl = v[4] - v[3];
                        d2[0] = 'F'; d2[1] = 'I'; d2[2] = 1;
                        d2[3] = (uint8_t)cl;  d2[4] = (uint8_t)(cl >> 8);
                        d2[5] = (uint8_t)hl;  d2[6] = (uint8_t)(hl >> 8);
                        d2[7] = (uint8_t)v[1]; d2[8] = (uint8_t)(v[1] >> 8);
                        d2[9] = (uint8_t)v[3]; d2[10] = (uint8_t)(v[3] >> 8);
                        /* GUARDRAIL: 16 bytes: FI(2) ver(1) code_len(2) hdr_len(2) code_start(2) hdr_start(2)
                         * payload_sum(2) resident_sum(2) reserved(1).
                         * GUARDRAIL: the RESIDENT sum is a separate field on purpose - the payload sum only proves the
                         * image arrived intact, it says nothing about the dictionary it will be pasted onto. But it is
                         * the IDENTITY of that dictionary (its header table: name hash + xt per word), NOT a sum of
                         * the resident code region - that region holds live cells and moves under the operator's
                         * fingers. See resident_sum() for the measurement. */
                        d2[11] = (uint8_t)sum; d2[12] = (uint8_t)(sum >> 8);
                        /* GUARDRAIL: the entry xt must be written AFTER every other descriptor field. The 16-byte
                         * layout's old `d2[15] = 0` ("reserved") still ran after this line and zeroed the LOW byte:
                         * measured as an image whose header said RUNPH1=1282 while the descriptor handed back 1280,
                         * so the caller EXECUTEd the wrong address (cells stayed 0). Reserved bytes are not free real
                         * estate - check the field map before reusing one. */
                        d2[15] = (uint8_t)v[5]; d2[16] = (uint8_t)(v[5] >> 8);   /* entry xt, 0 = none */
                        d2[2] = 2;                                              /* descriptor version 2 */
                        {
                            unsigned rs = resident_sum(memimg, (unsigned)ulp_repl_blk_off);
                            d2[13] = (uint8_t)rs; d2[14] = (uint8_t)(rs >> 8);
                        }
                    }
                    for (i2 = v[0]; i2 <= blk && i2 < BLK_N; i2++) blk_commit(i2);   /* last block is partial */
                    printf("dump: code %u + hdr %u = %u B, descriptor packed -> %u blocks from block %u, sum %u\n",
                           (unsigned)(v[2] - v[1]), (unsigned)(v[4] - v[3]), payload,
                           (20u + payload + 127u) / 128u, v[0], sum);
                }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#a <ms>` stalls INSIDE the op-3 critical section (after the age check, before the copy). It
             * exists because the interesting failure is not "a late request" but "the request was timely and the task
             * then stalled": an age check evaluated only on entry cannot see that. Test-only, main core, 0 ULP bytes. */
            if (n > 3 && ln[0] == '#' && ln[1] == 'a' && ln[2] == ' ') {
                unsigned ms = 0; int k = 3;
                while (ln[k] == ' ') k++;
                while (ln[k] >= '0' && ln[k] <= '9') ms = ms * 10u + (unsigned)(ln[k++] - '0');
                apply_stall_ms = ms;
                printf("stall: op-3 critical section will sleep %u ms after the age check\n", ms);
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: when the ULP stops answering but the HP console does not, the only way to name the stall is the
             * shared window. `#u` dumps every field the bridge exposes, so "silent ULP" becomes a concrete state (pending
             * command, full output ring, latched block layer) instead of a guess. */
            if (n >= 2 && ln[0] == '#' && ln[1] == 'u' && (ln[2] == 0 || ln[2] == ' ')) {
                {
                    uint32_t i3, k3 = req_idx < 16u ? 0u : req_idx & 15u;
                    printf("info: last %u serviced requests (op blk ms):", (unsigned)(req_idx < 16u ? req_idx : 16u));
                    for (i3 = 0; i3 < (req_idx < 16u ? req_idx : 16u); i3++) {
                        uint32_t e = (k3 + i3) & 15u;
                        printf(" %u/%u/%u", (unsigned)req_log[e][0], (unsigned)req_log[e][1], (unsigned)req_log[e][2]);
                    }
                    printf(" | total %u\n", (unsigned)req_total);
                    fflush(stdout);
                }
                /* GUARDRAIL: the ring DROPS bytes when it is full and used to do so invisibly - the phase's screen simply
                 * came out short (measured: the reader lost the tail of every 70-column row). This line is the reader the
                 * old counter never had: `dropped 0` after a paced frame is proof the pacing works, and any non-zero value
                 * says exactly how many bytes to give back. */
                printf("info: ulp blk_out %u req %u off %u sz %u | cmd h%u t%u (%u B) | out h%u t%u (%u B) | dropped %u | wakes %u\n",
                       (unsigned)ulp_repl_blk_out, (unsigned)ulp_repl_blk_req, (unsigned)ulp_repl_blk_off,
                       (unsigned)ulp_repl_blk_sz, (unsigned)ulp_repl_cmd_head, (unsigned)ulp_repl_cmd_tail,
                       (unsigned)ulp_repl_cmd_bytes, (unsigned)ulp_repl_out_head, (unsigned)ulp_repl_out_tail,
                       (unsigned)ulp_repl_out_bytes, (unsigned)ulp_repl_out_drop, (unsigned)ulp_repl_wake_count);
                /* GUARDRAIL: blk_out alone cannot say whether the HP ever SAW the edge, and the two readings have different
                 * owners: a set blk_out with blk_out_prev=0 means this task has not polled since the request (HP-side);
                 * both set means the request was seen and answered or dropped (ULP-side). Print both. */
                /* GUARDRAIL: with the ULP silent and blk_out clear, "waiting on the store" is excluded - so the next
                 * question is WHICH interpreter loop. The sys-vars answer it at zero ULP bytes: a nonzero V_LOADB means
                 * the machine is inside LOAD, and V_STATE says whether it is compiling. Read them through mem[]. */
                {
                    const uint8_t *mi = (const uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr);
                    printf("info: ulp vars: V_STATE %u V_HERE %u V_LATEST %u V_SEAL %u V_LOADB %u\n",
                           (unsigned)(mi[0] | (mi[1] << 8)), (unsigned)(mi[4] | (mi[5] << 8)),
                           (unsigned)(mi[8] | (mi[9] << 8)), (unsigned)(mi[12] | (mi[13] << 8)),
                           (unsigned)(mi[16] | (mi[17] << 8)));
                    fflush(stdout);
                }
                printf("info: hp view: blk_out_prev %d pending_ms %u now_ms %u | store_ok %d\n",
                       blk_out_prev, (unsigned)req_ms,
                       (unsigned)(xTaskGetTickCount() * portTICK_PERIOD_MS), store_ok);
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#k` reports the ULP stack high-water mark on demand. The stack grows DOWN from 0x1FF0 into .bss,
             * so an overflow corrupts engine state instead of faulting - which is how a 336 B chain once broke block I/O
             * silently. This is the only measurement that can tell whether the 327 B region has slack, and slack is the
             * only ULP memory that can be reclaimed after boot without shrinking the image. */
            if (n >= 2 && ln[0] == '#' && ln[1] == 'k' && (ln[2] == 0 || ln[2] == ' ')) {
#if defined(CANARY)
                uint32_t used = canary_used();
                printf("stack: high-water %u B of %u B region (%u B free), base 0x%04X\n",
                       (unsigned)used, (unsigned)(STACK_TOP - CANARY_BASE),
                       (unsigned)(STACK_TOP - CANARY_BASE - used), (unsigned)CANARY_BASE);
#else
                printf("stack: high-water probe is OFF in this build\n");
#endif
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#h` / `#l` / `#r` drive the LoRa BUSY pad (pin 13) from the HP core so the ULP's input path can
             * be tested with a value it cannot produce itself. `LORA_INIT` returning 1 is VACUOUS on a dead bus - BUSY
             * reads 0 for every pin, so "BUSY low, so ready" passes with nothing connected. A read that must return 1 when
             * the pad is driven high is the only version of this test that can fail. `#r` returns the pad to INPUT_ONLY
             * because leaving it driven would fake a busy radio for every later probe. */
            /* GUARDRAIL: name the three letters, never a range. `ln[1] >= 'h' && ln[1] <= 'r'` silently swallowed
             * `#n` (the light-sleep probe) and drove the pad low instead - an untyped range over a CLI alphabet is a
             * trap that grows every time a command is added inside it. */
            /* GUARDRAIL: `#z` is the store probe as a command, because printing from app_main before the console exists
             * races the port and reports nothing at all (measured: EARLYTEST simply absent). Clear the bit, wait a
             * window that contains many ULP wakes, and read it back - all on demand, so the answer never depends on when
             * the harness happened to open the port. */
            /* GUARDRAIL: `#z` measures the ULP's peripheral write in a build that has the HWPROBE store compiled in; in
             * the shipping image there is no such store, so "LOST" here only means "this build is not the probe build".
             * Confirm with strings on the elf (search for the HWPROBE probe string) before trusting either answer.
             * GUARDRAIL: never write a glob-plus-star inside a block comment - the compiler takes it as a nested comment
             * open and -Werror=comment fails the build, which is how this line changed. */
            /* GUARDRAIL: `#d` dumps the register blocks the ULP's peripheral access depends on, one word per line, in a
             * fixed order so two firmwares' output can be diffed literally. The disassembly of the working and broken
             * ULP images is instruction-for-instruction the same store to the same address, so the difference HAS to be
             * some enable bit - and the only way to find an unknown bit is to ask two machines the same question and
             * compare their answers. Read from the HP core, which is the trustworthy reader (F-158).
             * GUARDRAIL: read-only. Writing RTC_GPIO_OUT with arbitrary bits reboots the S3 (F-152); these are reads of
             * read-mostly config registers, plus RTC_GPIO_IN, which is an input. */
            if (n >= 2 && ln[0] == '#' && ln[1] == 'd' && (ln[2] == 0 || ln[2] == ' ')) {
                /* GUARDRAIL: F-164's follow-up: the S3's RTC peripheral clock gate lives in the SYSTEM block, which the
                 * first pass of this diff sampled only as far as +0x80. 0x200 words there and 0x600 in RTC_CNTL. */
                static const uint32_t blocks[4] = { 0x60008400u, 0x60008800u, 0x60010000u, 0x600C0000u };  /* RTCIO SENS RTC_CNTL SYSTEM */
                static const uint32_t lens[4]   = { 0x400u, 0x100u, 0x600u, 0x200u };
                for (int b = 0; b < 4; b++)
                    for (uint32_t o = 0; o < lens[b]; o += 4) {
                        printf("REG 0x%08X = 0x%08X\n", (unsigned)(blocks[b] + o),
                               (unsigned)REG_READ(blocks[b] + o));
                        vTaskDelay(1);      /* GUARDRAIL: see the reference build's note: a partial dump beats a full diff */
                    }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#p <pad>` answers the question the ULP's own register reads cannot (F-158) and the
             * echo test cannot either: it asks the HP core, the only honest reader, for the PHYSICAL level of a pad
             * the coprocessor has just been asked to drive. RTC_GPIO_IN reflects the pin, not a register latch and
             * not a store buffer, so it is the one witness that separates "the write reached the pad" from
             * "the write updated the register". The input path must be enabled for the pad first
             * (RTC_GPIO_MODE_INPUT_OUTPUT keeps the output driver on and turns the input on too), which is why this
             * sets the direction rather than trusting whatever the caller left. */
            /* GUARDRAIL: the console letters are a shared namespace - `#p` was ALREADY taken by the poke-three-values
             * command, and quietly adding a second handler for the same key makes the older one unreachable. Free
             * letters were checked against the table above first (`grep -oE "ln\[1\] == '.'"`). */
            if (n >= 3 && ln[0] == '#' && ln[1] == 'y' && ln[2] == ' ') {
                int pad = (int)strtol(ln + 3, NULL, 10);
                rtc_gpio_set_direction((gpio_num_t)pad, RTC_GPIO_MODE_INPUT_OUTPUT);
                uint32_t in = REG_READ(RTC_GPIO_IN_REG);
                uint32_t out = REG_READ(RTC_GPIO_OUT_REG);
                printf("pad %d: IN bit %u = %u (OUT bit %u = %u, IN 0x%08X)\n", pad, (unsigned)(pad + 10),
                       (unsigned)((in >> (pad + 10)) & 1u), (unsigned)(pad + 10),
                       (unsigned)((out >> (pad + 10)) & 1u), (unsigned)in);
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#q <hex>` prints one 32-bit word, read by the main core. `#d` cannot answer this
             * question: it walks four whole blocks with a tick per line, so one register costs minutes of
             * transcript and gets truncated by any harness that will not wait. The main core is the trusted reader
             * (F-158: the coprocessor's own register reads return noise), which also makes this the only way to ask
             * whether a coprocessor write landed in a block other than RTCIO. */
            if (n >= 3 && ln[0] == '#' && ln[1] == 'q' && ln[2] == ' ') {
                uint32_t a = (uint32_t)strtoul(ln + 3, NULL, 16);
                printf("REG 0x%08X = 0x%08X\n", (unsigned)a, (unsigned)REG_READ(a));
                fflush(stdout);
                n = 0;
                continue;
            }
            if (n >= 2 && ln[0] == '#' && ln[1] == 'z' && (ln[2] == 0 || ln[2] == ' ')) {
                /* GUARDRAIL: F-176, TWO witness bits. Every previous `#z` watched only bit 18 (pad 8 / NSS), the pad the
                 * HP core itself configures and drives - so "LOST" there cannot tell "the coprocessor's store was
                 * discarded" apart from "the HP core's own pad driver state owns that bit". Bit 23 (pad 13 / BUSY) is an
                 * HP-side INPUT: nothing in this firmware writes its OUT data bit, so a store from the ULP to it is
                 * unambiguous. Clearing both and reporting both is the one measurement the 165 probes before it skipped. */
                /* GUARDRAIL: F-176h - clear and watch THREE bits: bit 18 (the engine's own NSS write), bit 19 (SCK, which
                 * the engine drives LOW, so a SET there is proof of OUR store reaching RTCIO) and bit 23 (BUSY, never
                 * output-enabled: the control that must stay clear or the witness means nothing). */
                const uint32_t both = (1u << (8 + 10)) | (1u << (13 + 10)) | (1u << (9 + 10));
                REG_WRITE(RTC_GPIO_OUT_W1TC_REG, both);
                uint32_t w0 = ulp_repl_wake_count;
                int bit18 = 0, bit23 = 0, sck19 = 0;
                for (int i = 0; i < 40 && !(bit18 && bit23 && sck19); i++) {
                    vTaskDelay(pdMS_TO_TICKS(10));
                    uint32_t out = REG_READ(RTC_GPIO_OUT_REG);
                    if (out & (1u << (8 + 10))) bit18 = 1;
                    if (out & (1u << (13 + 10))) bit23 = 1;
                    if (out & (1u << (9 + 10))) sck19 = 1;
                }
                printf("storetest: NSS(bit18) %s  SCK(bit19,ours) %s  BUSY(bit23) %s  (%u wakes, OUT 0x%08X)\n",
                       bit18 ? "SET" : "clear", sck19 ? "SET" : "clear", bit23 ? "SET" : "clear",
                       (unsigned)(ulp_repl_wake_count - w0),
                       (unsigned)REG_READ(RTC_GPIO_OUT_REG));
                fflush(stdout);
                n = 0;
                continue;
            }
            if (n >= 2 && ln[0] == '#' && (ln[1] == 'h' || ln[1] == 'l' || ln[1] == 'r') &&
                (ln[2] == 0 || ln[2] == ' ')) {
                if (ln[1] == 'r') {
                    rtc_gpio_set_direction((gpio_num_t)13, RTC_GPIO_MODE_INPUT_ONLY);
                    printf("pad13: input (released)\n");
                } else {
                    /* GUARDRAIL: INPUT_OUTPUT, not OUTPUT_ONLY. OUTPUT_ONLY clears FUN_IE, and RTC_GPIO_IN only latches
                     * a pad whose input buffer is on - so the first version drove the pad high and read 0, which looked
                     * exactly like a dead ULP input path while it was the probe switching off the buffer it meant to
                     * read. (rtc_gpio_input_enable does not exist in this IDF; the mode bit is the supported route.) */
                    rtc_gpio_set_direction((gpio_num_t)13, RTC_GPIO_MODE_INPUT_OUTPUT);
                    rtc_gpio_set_level((gpio_num_t)13, ln[1] == 'h' ? 1 : 0);
                    printf("pad13: %s\n", ln[1] == 'h' ? "driven high" : "driven low");
                }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#n` settles F-156 - does the ULP's RTCIO access reach the hardware at all when the HP core is
             * asleep? It queues a single-bit W1TS write (pin 8 = NSS, never an arbitrary OUT value: F-152 showed 12345
             * rebooting the S3 because those bits are flash/brownout pads), enters light sleep for 1 s so the ULP runs
             * with the bus to itself, then prints the register as this core sees it. If OUT gains bit 18, the contention
             * hypothesis is right and the driver must own the radio only while the CPU sleeps - which is the shape
             * docs/29's power budget already assumes. */
            if (n >= 2 && ln[0] == '#' && ln[1] == 'n' && (ln[2] == 0 || ln[2] == ' ')) {
                static const char *probe_cmd = "262144 1610646532 !";
                uint32_t h = ulp_repl_cmd_head, tl = ulp_repl_cmd_tail, i, L = (uint32_t)strlen(probe_cmd);
                if (CMD_SIZE - (h - tl) < L + 1u) {
                    printf("gpio: ring full - probe NOT queued\n");
                } else {
                    for (i = 0; i < L; i++) CMD_BYTES[(h + i) & CMD_MASK] = (uint8_t)probe_cmd[i];
                    CMD_BYTES[(h + L) & CMD_MASK] = '\r';
                    ulp_repl_cmd_head = h + L + 1u;
                    /* GUARDRAIL: clear the bit from the HP core FIRST. The first version queued only the ULP's set and
                     * read back "bit18 SET" - but NSS is idled high by lora_pads_setup, so the bit was already set and
                     * the probe could not fail. A test whose baseline already satisfies it proves nothing; and the ULP
                     * cannot clear it either, because a ULP W1TC is swallowed exactly like W1TS (that is the question
                     * being asked, so it cannot be part of the question's setup). */
                    REG_WRITE(RTC_GPIO_OUT_W1TC_REG, 1u << (8 + 10));
                    printf("gpio: cleared bit18 (HP), OUT now 0x%08X\n", (unsigned)REG_READ(RTC_GPIO_OUT_REG));
                    printf("gpio: queued '%s', sleeping 1 s\n", probe_cmd);
                    fflush(stdout);
                    esp_sleep_enable_timer_wakeup(1000000ULL);
                    esp_light_sleep_start();
                    printf("gpio: after sleep OUT 0x%08X (bit18 %s)\n", (unsigned)REG_READ(RTC_GPIO_OUT_REG),
                           (REG_READ(RTC_GPIO_OUT_REG) & (1u << (8 + 10))) ? "SET" : "clear");
                }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#g` prints the RTC GPIO registers as the HP core sees them. The ULP's own read of RTC_GPIO_IN
             * returns 0x02010201 whatever drives the pads (two identical halves = the shape of a 16-bit fallback read),
             * and there is no way to tell "the register really holds that" from "the ULP cannot read this address"
             * without a second reader on the same silicon. Two readers, one register: if both agree, the pads are not
             * reaching the register; if they disagree, the ULP's load path is the fault. Never conclude a hardware
             * cause from a single reader - that is exactly how F-149 stayed hidden for a whole bring-up. */
            if (n >= 2 && ln[0] == '#' && ln[1] == 'g' && (ln[2] == 0 || ln[2] == ' ')) {
                printf("gpio: OUT 0x%08X ENABLE 0x%08X IN 0x%08X | pad8 0x%08X pad11 0x%08X pad13 0x%08X\n",
                       (unsigned)REG_READ(RTC_GPIO_OUT_REG), (unsigned)REG_READ(RTC_GPIO_ENABLE_REG),
                       (unsigned)REG_READ(RTC_GPIO_IN_REG),
                       (unsigned)REG_READ(RTC_IO_TOUCH_PAD0_REG + 8 * 4),
                       (unsigned)REG_READ(RTC_IO_TOUCH_PAD0_REG + 11 * 4),
                       (unsigned)REG_READ(RTC_IO_TOUCH_PAD0_REG + 13 * 4));
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#c <desc_blk>` compares the image IN THE STORE against what is pasted in mem[], byte for byte.
             * The loader's own checks bracket the copy; this one is for AFTER the machine has run (or wedged), where the
             * question is "is the code executing the code that was compiled". It reads mem[] only, so it answers while
             * the ULP is frozen inside one wake. */
            if (n > 3 && ln[0] == '#' && ln[1] == 'c' && ln[2] == ' ') {
                unsigned dblk = 0, k = 3;
                while (ln[k] == ' ') k++;
                while (ln[k] >= '0' && ln[k] <= '9') dblk = dblk * 10u + (unsigned)(ln[k++] - '0');
                if (dblk >= BLK_N) printf("cmp: REJECTED (block)\n");
                else {
                    const uint8_t *d2 = blkfile[dblk];
                    const uint8_t *mi = (const uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr);
                    unsigned cl2 = (unsigned)d2[3] | ((unsigned)d2[4] << 8);
                    unsigned hl2 = (unsigned)d2[5] | ((unsigned)d2[6] << 8);
                    unsigned cs2 = (unsigned)d2[7] | ((unsigned)d2[8] << 8);
                    unsigned hs2 = (unsigned)d2[9] | ((unsigned)d2[10] << 8);
                    unsigned psum2 = (unsigned)d2[11] | ((unsigned)d2[12] << 8);
                    unsigned b2 = dblk, o2 = 20, i4, mism = 0, firstma = 0, ssum = 0, msum = 0;
                    /* GUARDRAIL: the image's HEADERS do not follow its code in mem[]. Code sits at cs (it was compiled
                     * upward from the seal) and the headers sit at hs, ABOVE it, growing down from the seal's LATEST -
                     * measured: code 1666..1822 but headers 2020..2032, so the old `mi[cs2 + i4]` read 12 unrelated
                     * bytes at 1822 and reported "12 byte(s) differ" on a perfect image. A check that lies teaches the
                     * operator to ignore it, and this one is read exactly when something else is already wrong. */
                    for (i4 = 0; i4 < cl2 + hl2; i4++) {
                        uint8_t sv = blkfile[b2][o2];
                        unsigned ma = (i4 < cl2) ? cs2 + i4 : hs2 + (i4 - cl2);
                        uint8_t mv = mi[ma];
                        ssum = (ssum + sv) & 0xffffu; msum = (msum + mv) & 0xffffu;
                        if (sv != mv && !mism) { firstma = ma; }
                        if (sv != mv) mism++;
                        if (++o2 == (blk_sz ? blk_sz : 128u)) { o2 = 0; b2++; }
                    }
                    printf("cmp: %u B payload (%u code @%u, %u hdr @%u) | store sum %u, mem sum %u, descriptor %u | "
                           "%u byte(s) differ%s",
                           cl2 + hl2, cl2, cs2, hl2, hs2, ssum, msum, psum2, mism,
                           mism ? " -> FIRST AT " : " (mem[] holds the last ADOPTED image; before an adopt this "
                                  "compares against whatever was pasted there before)\n");
                    if (mism) {
                        unsigned off = firstma < cs2 + cl2 ? firstma - cs2 : cl2 + (firstma - hs2);
                        unsigned bb = dblk, oo = 20;
                        oo += off; while (oo >= (blk_sz ? blk_sz : 128u)) { oo -= (blk_sz ? blk_sz : 128u); bb++; }
                        printf("mem[%u] payload %u (mem[]=%u, store b%u o%u=%u)\n", firstma, off,
                               (unsigned)mi[firstma], bb, oo, (unsigned)blkfile[bb][oo]);
                    }
                }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#m <addr> <n>` prints n u16 cells of the ULP's mem[] from addr. It exists because a spinning
             * phase cannot be asked anything - its own counters are the only witnesses, and reading them from the HP
             * costs 0 ULP bytes and works while the ULP is frozen inside one wake. */
            if (n > 4 && ln[0] == '#' && ln[1] == 'm' && ln[2] == ' ') {
                unsigned a = 0, cnt = 1, k = 3; int vi = 0;
                unsigned v2[2] = {0, 1};
                while (vi < 2 && ln[k]) {
                    while (ln[k] == ' ') k++;
                    if (ln[k] < '0' || ln[k] > '9') break;
                    v2[vi] = 0;
                    while (ln[k] >= '0' && ln[k] <= '9') v2[vi] = v2[vi] * 10u + (unsigned)(ln[k++] - '0');
                    vi++;
                }
                a = v2[0]; cnt = v2[1] ? v2[1] : 1u;
                if (cnt > 16u) cnt = 16u;
                if (a + cnt * 2u > (unsigned)ulp_repl_blk_off) printf("mem: REJECTED (range)\n");
                else {
                    const uint8_t *mi = (const uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr);
                    printf("mem:");
                    for (k = 0; k < cnt; k++) printf(" [%u]=%u", a + k * 2u, (unsigned)(mi[a + k * 2u] | (mi[a + k * 2u + 1] << 8)));
                    printf("\n");
                }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#i` reports the store's state ON DEMAND. The boot refusal is printed before the serial port is
             * opened by any tool that attaches afterwards, so in practice nobody sees it - measured as gate 3 reporting
             * "no store line". A refusal nobody can read is not a refusal. */
            if (n >= 2 && ln[0] == '#' && ln[1] == 'i' && (ln[2] == 0 || ln[2] == ' ')) {
                uint32_t bp = 0, se = 0, fl = 0; fs_stats(&bp, &se, &fl);
                if (store_ok) {
                    printf("info: store ok, %u blocks x %u B | programmed %u B, %u erase(s), %u flush(es)\n",
                           (unsigned)fs_block_count(), (unsigned)fs_block_size(),
                           (unsigned)bp, (unsigned)se, (unsigned)fl);
                    /* per-sector erases: the hot sector is the one that dies first, so it must be visible */
                    uint32_t k, hot = 0, hotn = 0;
                    printf("info: erases/sector");
                    for (k = 0; k < fs_sector_count(); k++) {
                        uint32_t e = fs_sector_erases(k);
                        printf(" %u:%u", (unsigned)k, (unsigned)e);
                        if (e > hotn) { hotn = e; hot = k; }
                    }
                    printf(" | hottest sector %u (%u)\n", (unsigned)hot, (unsigned)hotn);
                    printf("info: bc %u (before last reset %u) | erase %u us, write %u us, super %u us | reset reason %d\n",
                           (unsigned)fs_bc(), (unsigned)fs_bc_prev(),
                           (unsigned)fs_us(0), (unsigned)fs_us(1), (unsigned)fs_us(2),
                           (int)esp_reset_reason());
                }
                else          printf("info: store REFUSED %s\n", fs_strerror(fs_init()));
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#f` flushes the sector cache and reports write amplification; `#x` formats the store. Both are
             * main-core only and cost 0 ULP bytes. `#x` is the recovery path named by the boot refusal. */
            if (n >= 2 && ln[0] == '#' && ln[1] == 'f' && (ln[2] == 0 || ln[2] == ' ')) {
                /* GUARDRAIL: `#f` commits everything the RAM mirror holds that flash has not seen, then flushes the
                 * sector cache. Without the commit pass, a block written by the ULP and then flushed would be lost on
                 * the next boot while the flush still reported success. */
                if (blkfile_dirty) {
                    uint32_t b;
                    for (b = 0; b < BLK_N; b++) { int rr = fs_write(b, blkfile[b]); if (rr != 0) printf("flush: block %u %s\n", (unsigned)b, fs_strerror(rr)); }
                    blkfile_dirty = 0;
                }
                int r = fs_flush();
                uint32_t bp = 0, se = 0, fl = 0; fs_stats(&bp, &se, &fl);
                if (r == FS_OK) printf("flush: ok | program+erase %u B, %u sector erase(s), %u flush(es)\n",
                                       (unsigned)bp, (unsigned)se, (unsigned)fl);
                else            printf("flush: FAILED %s\n", fs_strerror(r));
                fflush(stdout);
                n = 0;
                continue;
            }
            if (n >= 2 && ln[0] == '#' && ln[1] == 'x' && (ln[2] == 0 || ln[2] == ' ')) {
                int r = fs_format();
                if (r == FS_OK) { store_ok = 1; memset(blkfile, ' ', sizeof blkfile); printf("format: ok, store empty\n"); }
                else            printf("format: FAILED %s\n", fs_strerror(r));
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#v <0|1>` sets the per-adopt log line. It exists because that line is 4.5 ms of the 5.1 ms a
             * phase hop costs (measured), and because a diagnostic you cannot turn on when you need it is worse than no
             * diagnostic: adopt_sum.py and loader_tests.py both still read it, they just have to ask for it now. */
            if (n > 3 && ln[0] == '#' && ln[1] == 'v' && ln[2] == ' ') {
                int k = 3;
                while (ln[k] == ' ') k++;
                img_verbose = (ln[k] == '1');
                printf("verbose: per-adopt lines %s\n", img_verbose ? "ON" : "off");
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#s <ms>` stalls the block task ONCE. Test-only (main core, zero ULP bytes) and the only way
             * to provoke the op-3 race deliberately: without it the host answers within one FreeRTOS tick and the ULP
             * never times out, so "the host does not apply a stale request" could not be demonstrated. */
            if (n > 3 && ln[0] == '#' && ln[1] == 's' && ln[2] == ' ') {
                unsigned ms = 0; int k = 3;
                while (ln[k] == ' ') k++;
                while (ln[k] >= '0' && ln[k] <= '9') ms = ms * 10u + (unsigned)(ln[k++] - '0');
                stall_ms = ms;
                printf("stall: block task will sleep %u ms on its next request\n", ms);
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#p <blk> <off> <val>` pokes ONE byte in the store, so the loader's refusals can be exercised
             * on real data instead of argued about. Test-only, main-core only, zero ULP bytes: without it there is no
             * way to corrupt an image or forge a header hash from the console, and a refusal that has never fired is
             * not evidence. */
            if (n > 3 && ln[0] == '#' && ln[1] == 'p' && ln[2] == ' ') {
                unsigned v3[3] = {0}; int k = 3, vi = 0, bad3 = 0;
                while (vi < 3) {
                    while (ln[k] == ' ') k++;
                    if (!ln[k] || ln[k] < '0' || ln[k] > '9') { bad3 = 1; break; }
                    while (ln[k] >= '0' && ln[k] <= '9') v3[vi] = v3[vi] * 10u + (unsigned)(ln[k++] - '0');
                    vi++;
                }
                if (bad3 || vi < 3 || v3[0] >= BLK_N || v3[1] >= (blk_sz ? blk_sz : 128u) || v3[2] > 255u)
                    printf("poke: REJECTED (want: #p <blk> <off> <val>)\n");
                else {
                    blkfile[v3[0]][v3[1]] = (uint8_t)v3[2];
                    blk_commit(v3[0]);
                    printf("poke: block %u off %u = %u\n", v3[0], v3[1], v3[2]);
                }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#l` is RETIRED. It wrote mem[] from a console command while the REPL was running: it passed
             * only because the ULP had nothing to execute at that instant, i.e. passing by timing, which this project
             * does not accept. A binary load now happens on mailbox op 3 (see block_task): the ULP issues the request
             * and blocks inside blk_xfer, so the main core copies while the ULP is provably quiescent. */
            if (n > 3 && ln[0] == '#' && ln[1] == 'l' && ln[2] == ' ') {
                printf("load: REFUSED #l is retired - use `<desc_blk> 3 BLKXFER` from the ULP, then read the entry "
                       "xt at the block window and EXECUTE it\n");
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#p <blk> <off> <val>` pokes ONE byte in the store, so the loader's refusals can be exercised
             * on real data instead of argued about. Test-only, main-core only, zero ULP bytes: without it there is no
             * way to corrupt an image or forge a header hash from the console, and a refusal that has never fired is
             * not evidence. */
            if (n > 3 && ln[0] == '#' && ln[1] == 'p' && ln[2] == ' ') {
                unsigned v3[3] = {0}; int k = 3, vi = 0, bad3 = 0;
                while (vi < 3) {
                    while (ln[k] == ' ') k++;
                    if (!ln[k] || ln[k] < '0' || ln[k] > '9') { bad3 = 1; break; }
                    while (ln[k] >= '0' && ln[k] <= '9') v3[vi] = v3[vi] * 10u + (unsigned)(ln[k++] - '0');
                    vi++;
                }
                if (bad3 || vi < 3 || v3[0] >= BLK_N || v3[1] >= (blk_sz ? blk_sz : 128u) || v3[2] > 255u)
                    printf("poke: REJECTED (want: #p <blk> <off> <val>)\n");
                else {
                    blkfile[v3[0]][v3[1]] = (uint8_t)v3[2];
                    blk_commit(v3[0]);
                    printf("poke: block %u off %u = %u\n", v3[0], v3[1], v3[2]);
                }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: `#l <desc_blk>` ADOPTS a packed image, on the main core, at zero ULP bytes - it writes the
             * ULP's mem[] directly (the main core already reads it) and then sets V_HERE/V_LATEST, which is the same
             * rewind the machine already trusts. Four refusals, each named, because a binary load that "mostly works"
             * is the worst failure class here: the code carries absolute addresses, so a wrong base does not fail
             * fast, it executes garbage.
             *   1 FI/version      - descriptor sanity
             *   2 resident sum    - the dictionary the image was built against must be unchanged
             *   3 payload sum     - the image bytes in the store must be intact
             *   4 header hashes   - a pasted header must not shadow a resident name
             * Format: #l <desc_blk> */
            if (n > 3 && ln[0] == '#' && ln[1] == 'l' && ln[2] == ' ') {
                unsigned dblk = 0; int k = 3;
                while (ln[k] == ' ') k++;
                while (ln[k] >= '0' && ln[k] <= '9') dblk = dblk * 10u + (unsigned)(ln[k++] - '0');
                {
                    const uint8_t *desc = blkfile[dblk];
                    uint8_t *memimg = (uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr);
                    unsigned cl = (unsigned)desc[3] | ((unsigned)desc[4] << 8);
                    unsigned hl = (unsigned)desc[5] | ((unsigned)desc[6] << 8);
                    unsigned cs = (unsigned)desc[7] | ((unsigned)desc[8] << 8);
                    unsigned hs = (unsigned)desc[9] | ((unsigned)desc[10] << 8);
                    unsigned psum = (unsigned)desc[11] | ((unsigned)desc[12] << 8);
                    unsigned rsum = (unsigned)desc[13] | ((unsigned)desc[14] << 8);
                    unsigned hdrtop = (unsigned)ulp_repl_blk_off;
                    int badl = 0;
                    if (dblk >= BLK_N || desc[0] != 'F' || desc[1] != 'I' || desc[2] != 1) {
                        printf("load: REFUSED bad descriptor (magic/version/block)\n"); badl = 1;
                    }
                    if (!badl && (cs < 52u || hs <= cs || hs > hdrtop || hdrtop - hs < hl)) {
                        printf("load: REFUSED impossible geometry (code %u hdr %u top %u)\n", cs, hs, hdrtop);
                        badl = 1;
                    }
                    if (!badl) {
                        /* GUARDRAIL: the resident check is `resident_sum()`'s job - one definition of the range,
                         * shared with #d and op 3 (R6). The local `sum2` that used to sit here was left unused by
                         * that change and the compiler named it; a warning in this file is how a real dead variable
                         * gets ignored later. */
                        unsigned rs = resident_sum(memimg, hdrtop);
                        if (rs != rsum) {
                            printf("load: REFUSED resident dictionary changed (sum %u, image built on %u)\n", rs, rsum);
                            badl = 1;
                        }
                    }
                    if (!badl) {
                        /* the payload lives from descriptor block, offset 16, and is a plain concatenation */
                        unsigned blk2 = dblk, off2 = 16, k2, sum2 = 0;
                        for (k2 = 0; k2 < cl + hl; k2++) {
                            sum2 = (sum2 + blkfile[blk2][off2]) & 0xffffu;
                            if (++off2 == (blk_sz ? blk_sz : 128u)) { off2 = 0; blk2++; }
                        }
                        if (blk2 >= BLK_N || sum2 != psum) {
                            printf("load: REFUSED image corrupt (sum %u, descriptor %u)\n", sum2, psum);
                            badl = 1;
                        }
                    }
                    if (!badl) {
                        /* refusal 4: any image header hash equal to a resident one would shadow a resident name */
                        unsigned blk2 = dblk, off2 = 16 + cl, k2, j, hb[3], collision = 0;
                        while (off2 >= (blk_sz ? blk_sz : 128u)) { off2 -= (blk_sz ? blk_sz : 128u); blk2++; }
                        for (k2 = 0; k2 + 2 < hl; k2 += 3) {
                            for (j = 0; j < 3; j++) {
                                unsigned p2 = off2 + j;
                                hb[j] = blkfile[blk2 + p2 / (blk_sz ? blk_sz : 128u)][p2 % (blk_sz ? blk_sz : 128u)];
                            }
                            {
                                unsigned ih = ((unsigned)hb[2] << 4) | ((unsigned)hb[1] >> 4), k3;
                                for (k3 = hs + hl; k3 + 2 < hdrtop; k3 += 3) {   /* resident base = sealed LATEST */
                                    unsigned rh = ((unsigned)memimg[k3 + 2] << 4) | ((unsigned)memimg[k3 + 1] >> 4);
                                    if (rh == ih) {
                                        /* GUARDRAIL: name the offsets. A bare hash told us a refusal fired but not
                                         * whether it was a real collision, a misaligned image entry, or a wrong stride
                                         * in the resident scan - three different bugs with the same message. */
                                        if (!collision) {
                                            printf("load: image entry @payload %u (bytes %u %u %u) hash %u == resident @%u "
                                                   "(bytes %u %u %u)\n", k2, hb[0], hb[1], hb[2], ih, k3,
                                                   memimg[k3], memimg[k3+1], memimg[k3+2]);
                                        }
                                        collision = ih;
                                    }
                                }
                            }
                            off2 += 3;
                            while (off2 >= (blk_sz ? blk_sz : 128u)) { off2 -= (blk_sz ? blk_sz : 128u); blk2++; }
                        }
                        if (collision) {
                            printf("load: REFUSED name collision, image header hash %u shadows a resident word\n",
                                   collision);
                            badl = 1;
                        }
                    }
                    if (!badl) {
                        unsigned blk2 = dblk, off2 = 16, k2;
                        for (k2 = 0; k2 < cl + hl; k2++) {          /* code first, then headers, exactly as dumped */
                            memimg[cs + k2] = blkfile[blk2][off2];
                            if (++off2 == (blk_sz ? blk_sz : 128u)) { off2 = 0; blk2++; }
                        }
                        /* GUARDRAIL: the sysvar offsets are duplicated HERE because the main core does not include
                         * src/uforth.c (it would drag the whole engine in). They must match the enum in uforth.c:
                         * V_STATE 0, V_HERE 4, V_LATEST 8, V_SEAL 12, V_LOADB 16, PAD 20, DICT 52. A drift here
                         * would write the pointers into the wrong cells and the machine would execute garbage. */
#define HP_V_HERE   4u
#define HP_V_LATEST 8u
                        memimg[HP_V_HERE] = (uint8_t)((cs + cl) & 0xffu);   /* little-endian, sysvars are u32 */
                        memimg[HP_V_HERE + 1] = (uint8_t)(((cs + cl) >> 8) & 0xffu);
                        memimg[HP_V_HERE + 2] = 0; memimg[HP_V_HERE + 3] = 0;
                        memimg[HP_V_LATEST] = (uint8_t)(hs & 0xffu);
                        memimg[HP_V_LATEST + 1] = (uint8_t)((hs >> 8) & 0xffu);
                        memimg[HP_V_LATEST + 2] = 0; memimg[HP_V_LATEST + 3] = 0;
                        printf("load: adopted code %u + hdr %u from block %u (HERE %u, LATEST %u)\n",
                               cl, hl, dblk, cs + cl, hs);
                    }
                }
                fflush(stdout);
                n = 0;
                continue;
            }
            /* GUARDRAIL: everything that is NOT a seed line is forwarded into the ULP's command ring from HERE.
             * The pump used to read the UART as well, and two readers on one port steal each other's bytes:
             * measured as a mangled command (`LOAD?` where a LOAD was intended) and blocks that never arrived. */
            {
                uint32_t h = ulp_repl_cmd_head, tl = ulp_repl_cmd_tail, space = CMD_SIZE - (h - tl);
                uint32_t i;
                /* GUARDRAIL: a line longer than the ring was forwarded PARTIALLY - `for (... && i < space ...)` cut it
                 * and the ULP then executed a truncated command. Measured: a 71-char definition echoed as
                 * `... 1 + REPEAT DRO` and compiled a definition that never closed, with NO error anywhere; the next
                 * lines were then compiled into it instead of being interpreted. The interactive limit is CMD_SIZE-1
                 * = 63 bytes (the seeder's `#b` path has its own 320-byte buffer and is unaffected). Refuse the whole
                 * line by name: a partial command must never reach the machine. */
                if ((uint32_t)n + 1u > space || (uint32_t)n + 1u > CMD_SIZE) {
                    printf("line too long: %d bytes, the ring holds %u - NOT sent\r\n", n, (unsigned)(CMD_SIZE - 1u));
                    fflush(stdout);
                    n = 0;
                    continue;
                }
                ln[n] = '\r';
                for (i = 0; i <= (uint32_t)n; i++) CMD_BYTES[(h + i) & CMD_MASK] = (uint8_t)ln[i];
                ulp_repl_cmd_head = h + i;
            }
            n = 0;
        } else if (n < (int)sizeof(ln) - 1) {
            ln[n++] = (char)c;
        }
    }
}

static void block_task(void *arg)
{
    (void)arg;
    /* GUARDRAIL: the first board run answered ERR_NO_SERVER on the ULP side while this task looked
     * healthy, so the server now reports what it can actually see: the published addresses once, and a
     * count of requests. Without this the only symptom is a timeout on the other core. */
    /* GUARDRAIL: this diagnostics block interleaves with the operator's own echo and turns a clean
     * transcript into noise. Keep it behind a flag, OFF by default: the console is the product. */
    /* GUARDRAIL: this initialisation must NOT be inside a debug guard. It spent one build inside
     * `#if defined(BLK_DEBUG)`, so with debug off `blk_sz` stayed 0, every copy loop did nothing, and the
     * only symptom was SAVE reporting +4 (a nacked checksum over zero bytes) while the data never moved.
     * A variable that decides correctness is not a diagnostic.
     * GUARDRAIL: the size comes from the ULP, never from a local constant: two `#define BLK_SZ` values that
     * disagree make every SAVE nack with a plausible code and overrun mem[] on the way. Refuse to serve
     * rather than serve wrongly. */
    blk_sz = (uint32_t)ulp_repl_blk_sz;
    if (blk_sz == 0u || blk_sz > BLK_SZ) {
        printf("FATAL: ULP block size %u does not fit this server (%u)\n", (unsigned)blk_sz, (unsigned)BLK_SZ);
        fflush(stdout);
        vTaskDelete(NULL);
    }
#if defined(BLK_DEBUG)
    printf("blksrv up: mem=0x%08x blkoff=%u mb=0x%08x blksz=%u\n",
           (unsigned)ulp_repl_mem_addr, (unsigned)ulp_repl_blk_off,
           (unsigned)ulp_repl_mb_addr, (unsigned)blk_sz);
    fflush(stdout);
#endif
#if defined(BLK_DEBUG)
    uint32_t seen = 0;
#endif
    for (;;) {
        /* GUARDRAIL: `pending` is "a request is out and nobody has answered it". The answered word (mailbox[2]) is
         * written 0 by the ULP when it issues and 1 by this core when it answers, so the pair survives any number of
         * missed polls - which is the whole point (see the note on `req_ms`). The two nastier variants of "service
         * whatever blk_out advertises" stay excluded: a late service is refused by the age check below, and a
         * completed request cannot be re-serviced because this core's own answer sets mailbox[2] away from 0. */
        volatile uint32_t *mbp = (volatile uint32_t *)(ULP_RAM_BASE + ulp_repl_mb_addr);
        uint32_t now_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
        int out_now = (int)ulp_repl_blk_out;      /* read once: the other core clears it when it has the answer */
        /* GUARDRAIL: `== 1`, not "nonzero". The flag is written as 0 or 1, so anything else is not a request - it is
         * corrupt memory, and treating it as truthy made this task service 5 600 phantom requests a second (see the
         * note on CANARY_BASE). Fail by name instead of spinning. */
        if (out_now != 0 && out_now != 1) {
            static int complained;
            if (!complained) {
                complained = 1;
                printf("FATAL: ULP blk_out = 0x%08x, which is not a flag - image/paint overlap?\n", (unsigned)ulp_repl_blk_out);
                fflush(stdout);
            }
            vTaskDelay(1);
            continue;
        }
        int pending = (out_now == 1) && (mbp[2] == 0u);  /* a request this core has not answered */
        blk_out_prev = out_now;
        if (pending) { if (!req_ms) req_ms = now_ms; }
        else req_ms = 0;
        if (ulp_repl_blk_req || pending) {
                hot = 8;                  /* GUARDRAIL: the next request in a chain is ~100-300 us away - stay awake */
                if (stall_ms) { vTaskDelay(pdMS_TO_TICKS(stall_ms)); stall_ms = 0; }
#if defined(BLK_DEBUG)
            if (seen < 3) {
                volatile uint32_t *dbg = (volatile uint32_t *)(ULP_RAM_BASE + ulp_repl_mb_addr);
                printf("blksrv: req #%u blk=%u op=%u sum=%u\n", (unsigned)++seen,
                       (unsigned)dbg[0], (unsigned)dbg[1], (unsigned)dbg[3]);
                fflush(stdout);
            }
            seen++;
#endif
            volatile uint32_t *mb = (volatile uint32_t *)(ULP_RAM_BASE + ulp_repl_mb_addr);
            req_log[req_idx & 15u][0] = mb[1];
            req_log[req_idx & 15u][1] = mb[0];
            req_log[req_idx & 15u][2] = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
            req_idx++; req_total++;
            volatile uint8_t  *buf = (volatile uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr + ulp_repl_blk_off);
            uint32_t blk = mb[0], op = mb[1];
            if (blk >= BLK_N) {
                /* GUARDRAIL: send the MAGNITUDE of the ULP's negative BK_* code, because blk_xfer decodes a
                 * nack as `(i32)(0u - st)`. This was 2, which decoded as -2 = BK_BUSY, so "no such block"
                 * arrived at Forth as "server busy" and the operator got a misleading name for a range
                 * error. 5 decodes as BK_RANGE, which is what it is. */
                mb[2] = 5;                       /* nack: no such block -> BK_RANGE */
            } else if (op == 3u) {               /* LOAD IMAGE: validate, copy into mem[], hand back the entry xt */
                /* GUARDRAIL: this is the ONLY safe place to write mem[] from the main core. The ULP asked for it and
                 * is spinning inside blk_xfer waiting for the answer, so it is provably not fetching tokens from the
                 * region being written. A console command cannot make that promise (that is why `#l` is retired).
                 * GUARDRAIL: four named refusals, coarse codes to the ULP (which has names for 4/5/6) and a precise
                 * line to the console, because a binary load that "mostly works" executes garbage: the image carries
                 * absolute addresses.
                 *   magic/geometry    -> 5 (BK_RANGE)
                 *   sealed pointers   -> 5 (BK_RANGE)   code base and header base must match THIS machine
                 *   resident sum      -> 4 (BK_CRC)     the dictionary the image was built on
                 *   image sum         -> 4 (BK_CRC)     the bytes in the store
                 *   header collision  -> 6 (BK_BUFOVER) a pasted header must not shadow a resident name */
                const uint8_t *desc = blkfile[blk];
                uint8_t *mi = (uint8_t *)(ULP_RAM_BASE + ulp_repl_mem_addr);
                uint32_t age = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS) - req_ms;
                if (age > 400u) {          /* 400 ms < BLKWAIT ~845 ms: past this the ULP has certainly given up */
                    /* GUARDRAIL: answer the ULP FIRST, print second. The ULP is blocked on this word, and stdout can
                     * stall for milliseconds on the USB console - measured as 50 adoption cycles where an op-3 answer
                     * arrived too late and the cycle test failed. The console must never sit between the work and the
                     * answer. */
                    mb[3] = 0; mb[2] = 5;
                    printf("img: REFUSED stale request (%u ms old, the ULP has given up) - nothing applied\n",
                           (unsigned)age);
                    goto img_done;
                }
                if (apply_stall_ms) { vTaskDelay(pdMS_TO_TICKS(apply_stall_ms)); apply_stall_ms = 0; }
                /* GUARDRAIL: re-evaluate the age AFTER the critical-section stall, immediately before anything is
                 * copied. The entry check alone is not enough: a stall of 2 s inside the section happened after the
                 * check passed, and the copy would then land in a dictionary the ULP had already been told it does not
                 * have. The bound has to be tested where the decision is taken. */
                age = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS) - req_ms;
                if (age > 400u) {
                    mb[3] = 0; mb[2] = 5;
                    printf("img: REFUSED stale request after the stall (%u ms old) - nothing applied\n", (unsigned)age);
                    goto img_done;
                }
                unsigned cl = (unsigned)desc[3] | ((unsigned)desc[4] << 8);
                unsigned hl = (unsigned)desc[5] | ((unsigned)desc[6] << 8);
                unsigned cs = (unsigned)desc[7] | ((unsigned)desc[8] << 8);
                unsigned hs = (unsigned)desc[9] | ((unsigned)desc[10] << 8);
                unsigned psum = (unsigned)desc[11] | ((unsigned)desc[12] << 8);
                unsigned rsum = (unsigned)desc[13] | ((unsigned)desc[14] << 8);
                unsigned entry = (unsigned)desc[15] | ((unsigned)desc[16] << 8);
                unsigned top = (unsigned)ulp_repl_blk_off;
                unsigned vhere = (unsigned)mi[4] | ((unsigned)mi[5] << 8);
                unsigned vseal = (unsigned)mi[12] | ((unsigned)mi[13] << 8);
                uint32_t nack = 0; int bad = 0, answered = 0; unsigned k2;
                if (desc[0] != 'F' || desc[1] != 'I' || desc[2] != 2 || cl == 0u || hl == 0u
                    || hl % 3u != 0u || cs < 52u || hs <= cs || hs + hl > top) {
                    nack = 5; bad = 1; mb[3] = 0; mb[2] = 5; answered = 1; printf("img: REFUSED bad descriptor (magic/version/geometry)\n");
                }
                if (!bad && (cs != vhere || hs + hl != vseal)) {
                    nack = 5; bad = 1; mb[3] = 0; mb[2] = 5; answered = 1;
                    printf("img: REFUSED sealed pointers moved (image built on HERE %u LATEST %u, this machine has %u and %u)\n",
                           cs, hs + hl, vhere, vseal);
                }
                if (!bad) {
                    unsigned rs = resident_sum(mi, top);
                    if (rs != rsum) { nack = 4; bad = 1; mb[3] = 0; mb[2] = 4; answered = 1; printf("img: REFUSED resident dictionary changed (sum %u, built on %u)\n", rs, rsum); }
                }
                if (!bad) {
                    unsigned b2 = blk, o2 = 20, s2 = 0;
                    for (k2 = 0; k2 < cl + hl; k2++) {
                        s2 = (s2 + blkfile[b2][o2]) & 0xffffu;
                        if (++o2 == blk_sz) { o2 = 0; b2++; }
                    }
                    if (b2 >= BLK_N || s2 != psum) { nack = 4; bad = 1; mb[3] = 0; mb[2] = 4; answered = 1; printf("img: REFUSED image corrupt (sum %u, descriptor %u)\n", s2, psum); }
                }
                if (!bad) {
                    unsigned b2 = blk, o2 = 20 + cl, k3, j, hb[3], coll = 0;
                    while (o2 >= blk_sz) { o2 -= blk_sz; b2++; }
                    for (k3 = 0; k3 + 8 < hl; k3 += 3) {          /* +8: skip the last two entries, they are anchors */
                        for (j = 0; j < 3; j++) hb[j] = blkfile[b2 + (o2 + j) / blk_sz][(o2 + j) % blk_sz];
                        {
                            unsigned ih = ((unsigned)hb[2] << 4) | ((unsigned)hb[1] >> 4), r3;
                            for (r3 = hs + hl; r3 + 2 < top; r3 += 3) {
                                unsigned rh = ((unsigned)mi[r3 + 2] << 4) | ((unsigned)mi[r3 + 1] >> 4);
                                if (rh == ih) { if (!coll) { mb[3] = 0; mb[2] = 6; answered = 1; printf("img: REFUSED name collision, header hash %u shadows a resident %u\n", ih, r3); } coll = ih; }
                            }
                        }
                        o2 += 3;
                        while (o2 >= blk_sz) { o2 -= blk_sz; b2++; }
                    }
                    if (coll) { nack = 6; bad = 1; }
                }
                if (!bad) {
                    unsigned b2 = blk, o2 = 20;
                    for (k2 = 0; k2 < cl + hl; k2++) {
                        mi[cs + k2] = blkfile[b2][o2];
                        if (++o2 == blk_sz) { o2 = 0; b2++; }
                    }
                    /* GUARDRAIL: verify AFTER pasting, not only before. The pre-copy check proves the STORE is intact;
                     * it says nothing about what landed in mem[]. A spin that touches no memory and asks for nothing
                     * is the signature of executing bytes that are not the ones compiled, so the pasted region must
                     * be summed too - and a mismatch must be loud, not a silent "adopted". */
                    {
                        unsigned post = 0, k4;
                        for (k4 = 0; k4 < cl + hl; k4++) post = (post + mi[cs + k4]) & 0xffffu;
                        if (post != psum) {
                            printf("img: REFUSED pasted code differs from the image (mem sum %u, descriptor %u)\n",
                                   post, psum);
                            mb[3] = 0; mb[2] = 4; answered = 1;
                            bad = 1;
                        }
                    }
                    if (bad) goto img_post;
                    mi[4] = (uint8_t)((cs + cl) & 0xffu); mi[5] = (uint8_t)(((cs + cl) >> 8) & 0xffu);
                    mi[6] = 0; mi[7] = 0;
                    mi[8] = (uint8_t)(hs & 0xffu); mi[9] = (uint8_t)((hs >> 8) & 0xffu);
                    mi[10] = 0; mi[11] = 0;
                    /* the entry xt rides back in the block window: 4 bytes, little-endian */
                    buf[0] = (uint8_t)(entry & 0xffu); buf[1] = (uint8_t)((entry >> 8) & 0xffu);
                    buf[2] = 0; buf[3] = 0;
                    /* GUARDRAIL: clear req_ms WITH the answer. Waiting for the next poll to notice mailbox[2] != 0
                     * would leave the previous request's timestamp in place, and a request that arrived inside that
                     * same poll window would inherit an age it never had. */
                    mb[3] = 0; mb[2] = 1u; req_ms = 0;   /* answer FIRST - see the GUARDRAIL above */
                    if (img_verbose) printf("img: adopted code %u + hdr %u from block %u, entry %u\n",
                                            cl, hl, (unsigned)blk, entry);
                    answered = 1;
                }
                if (!answered) { mb[3] = 0; mb[2] = bad ? nack : 1u; }
img_post:   ;
img_done:   ;
            } else if (op == 0u) {               /* READ */
                uint32_t s = 0; int i;
                for (i = 0; i < (int)blk_sz; i++) { buf[i] = blkfile[blk][i]; s += blkfile[blk][i]; }
                /* GUARDRAIL: a checksum disagreement between the two cores has three possible owners —
                 * the store, the copy, or the check — and the board transcript cannot tell them apart.
                 * Print what this core actually has AFTER the copy, so the ULP's complaint has a number
                 * to compare against instead of being an argument about who is wrong. */
#if defined(BLK_DEBUG)
                if (seen <= 6) {
                    printf("blksrv: READ blk=%u file=%u,%u buf=%u,%u sum=%u\n", (unsigned)blk,
                           (unsigned)blkfile[blk][0], (unsigned)blkfile[blk][1],
                           (unsigned)buf[0], (unsigned)buf[1], (unsigned)(s & 0xffffu));
                    fflush(stdout);
                }
#endif
                mb[3] = s & 0xffffu;
                mb[2] = 1u; req_ms = 0;      /* GUARDRAIL: an answer ends the pending episode here, not on the next poll */
            } else {                             /* WRITE */
                uint32_t s = 0; int i;
                for (i = 0; i < (int)blk_sz; i++) s += buf[i];
                if ((s & 0xffffu) != mb[3]) {
                    /* GUARDRAIL: same decoding rule as the range nack above: 0xFFFFFFFC decodes as +4 (not
                     * -4), so a checksum mismatch would have reached Forth as an unnamed positive status. 4
                     * decodes as BK_CRC. This path is not covered by the host tests (they use the engine's
                     * fake server), so the rule, not a test, is what keeps it honest. */
                    mb[2] = 4;                   /* nack: checksum mismatch -> BK_CRC (-4) */
                } else {
                    for (i = 0; i < (int)blk_sz; i++) blkfile[blk][i] = buf[i];
                    /* GUARDRAIL: do NOT commit to flash here. This is the one path the ULP BLOCKS ON (its write waits for
                     * this reply), so calling flash erase+write from this task puts a 20-34 ms flash operation inside the
                     * ULP's critical path - measured: the ULP then stopped answering its own REPL while the HP console
                     * stayed alive (intermittent, 2 of 5 attempts). Persistence is explicit: `#f`, `#d`, seeding. The
                     * cost of this rule is that SAVE alone does not persist, and the claim says so. */
                    blk_dirty(blk);
                    mb[2] = 1u; req_ms = 0;  /* GUARDRAIL: same rule on the WRITE path - an answer resets the age */
                }
            }
        }
        /* GUARDRAIL: the painted high-water mark is reported by `#k`, not from this loop. Injecting a Forth line into the
         * command ring from here corrupted the console (binary noise) because this task and the UART pump both own
         * cmd_head. A reader (`#k`) cannot collide with the writer. */
        /* GUARDRAIL: this delay IS the block-request latency - the ULP has nothing to run on until it is answered - and
         * one FreeRTOS tick is 10 ms at CONFIG_FREERTOS_HZ=100, so a naive poll charges every phase hop an average of
         * half a tick: measured 10.7 ms/hop, all of it this line.
         * Raising CONFIG_FREERTOS_HZ to 1000 DID cut the hop to 2.2 ms (measured) but made block seeding/LOADing
         * intermittently deliver garbage (`ulp: ERR_ULPCODE 0xff`, then NAME? cascades) - 5 failures in 11 trials at
         * 1 kHz against 0 in 6 at 100 Hz. That is a REAL finding (F-131), not a reason to crank the clock, so the tick
         * stays at 100 Hz and the latency is bought narrowly instead:
         *
         * `hot` is the number of extra 150 us polls to do after servicing a request, because a chain's next request
         * arrives ~100-300 us later (the ULP copies 128 B, runs a 20 B phase and asks again). A bounded spin on the hot
         * path costs ~1.2 ms of this core ONLY while a chain is running, and falls back to the tick the moment it goes
         * quiet - do NOT make this an unbounded busy-wait: this task and the console task share a core, and a task that
         * never yields starves the console (R3). */
        if (hot) { hot--; esp_rom_delay_us(150); }
        else vTaskDelay(1);                       /* idle: one tick, and the console keeps the core */
    }
}

/* GUARDRAIL: declared here because app_main creates the server before this file defines it — an
 * undeclared-call error, which is the good kind: it fails at compile time instead of linking a task
 * that never starts. */

static void block_task(void *arg);

/* LoRa pads for the Heltec V3 (SX1262): SCK 9, MOSI 10, MISO 11, NSS 8, NRST 12, BUSY 13, DIO1 14.
 *
 * GUARDRAIL: the ULP cannot put a pad into RTC GPIO mode by itself reliably - measured on this board, a Forth driver that
 * wrote RTC_IO_TOUCH_PADn / RTC_GPIO_ENABLE by hand read every pin back as 0, and "BUSY is low" then made a completely
 * dead SPI link look like a successful radio init. The main core does it here, exactly as the working C driver does
 * (probe/lora/main/lora_main.c), and it costs APP flash - not one byte of the 7 892 B ULP pool.
 * GUARDRAIL: rtc_gpio_hold_en() must NOT be called on these: hold freezes the pad and the ULP can no longer drive it. */
static void lora_pads_setup(void)
{
    const int outs[4] = { 8, 9, 10, 12 };
    const int ins[3]  = { 11, 13, 14 };
    /* GUARDRAIL: detach every pad from the GPIO matrix BEFORE rtc_gpio_init(). This is the one call the working driver
     * (probe/lora start_ulp) makes and this firmware did not, and it is what the reference build's own comment says:
     * "gpio_reset_pin(): detach from the GPIO matrix before handing to RTC". With the pads still claimed by the digital
     * side, MUX_SEL says RTC while the pad is not actually under RTC control - so the ULP's RTCIO accesses are accepted
     * and discarded (measured: an unconditional C store to OUT_W1TS lost on every wake, res=0, while the same store
     * transmits on the reference firmware). */
    for (int i = 0; i < 4; i++) gpio_reset_pin((gpio_num_t)outs[i]);
    for (int i = 0; i < 3; i++) gpio_reset_pin((gpio_num_t)ins[i]);
    for (int i = 0; i < 4; i++) {
        rtc_gpio_init((gpio_num_t)outs[i]);
        rtc_gpio_set_direction((gpio_num_t)outs[i], RTC_GPIO_MODE_OUTPUT_ONLY);
        rtc_gpio_pullup_dis((gpio_num_t)outs[i]);
        rtc_gpio_pulldown_dis((gpio_num_t)outs[i]);
    }
    for (int i = 0; i < 3; i++) {
        rtc_gpio_init((gpio_num_t)ins[i]);
        rtc_gpio_set_direction((gpio_num_t)ins[i], RTC_GPIO_MODE_INPUT_ONLY);
        rtc_gpio_pullup_dis((gpio_num_t)ins[i]);
        rtc_gpio_pulldown_dis((gpio_num_t)ins[i]);
    }
    rtc_gpio_set_level((gpio_num_t)8, 1);    /* NSS idle high */
    rtc_gpio_set_level((gpio_num_t)12, 1);   /* NRST idle high */
    rtc_gpio_set_level((gpio_num_t)9, 0);    /* SCK idle low */
}

void app_main(void)
{
    lora_pads_setup();
#if defined(ULP_EARLY)
    /* GUARDRAIL: F-160 app bisect. Start the coprocessor immediately after the pads are configured, before the watchdog,
     * the UART driver and the flash store - the three things this firmware does that the working reference does not. If
     * the store lands here, the cause is one of them; if it does not, it is earlier still (the bootloader image or the
     * linker layout). GUARDRAIL: canary_paint() MUST be skipped in this build - it writes 260 B of paint at CANARY_BASE,
     * which is the ULP's own stack, so painting after the coprocessor starts silently kills it (F-159). */
    /* GUARDRAIL: keep the RTC peripheral power domain ON. The reference firmware (probe/lora) calls
     * esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_OPTION_ON) and THIS firmware never did - and the RTCIO block
     * lives in that domain, so a ULP access to it is not guaranteed to be served while the domain is left to its
     * default. This is the last HP-side call the two firmwares differ on. */
    ESP_ERROR_CHECK(esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_OPTION_ON));
#if defined(FOREIGN_ULP)
    ESP_ERROR_CHECK(ulp_riscv_load_binary(foreign_ulp_bin, foreign_ulp_bin_len));
    printf("FOREIGN_ULP: booted probe/lora's image, %u B\n", (unsigned)foreign_ulp_bin_len);
#else
    ESP_ERROR_CHECK(ulp_riscv_load_binary(bin_start, (size_t)(bin_end - bin_start)));
#endif
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, 6460));
    /* GUARDRAIL: F-163 was tested and REJECTED here, and the rejection is the finding: setting
     * RTC_CNTL_COCPU_START_2_RESET_DIS (the one bit that differed in the 544-word register dump) both before and after
     * ulp_riscv_run() left the store LOST, and the read-back proved the register is a dynamic snapshot - it read
     * 0x0010023F microseconds after the set, so 0x60-vs-0x62 was two machines sampled at different points in the ULP
     * timer sequence, not a configuration difference. Do not re-pursue this bit. */
    ESP_ERROR_CHECK(ulp_riscv_run());
#if defined(ULP_EARLY)
    /* GUARDRAIL: clear pad 8's data bit AFTER arming the coprocessor, then sample on the ULP's own cadence (it wakes
     * every 6.46 ms, so a 200 ms window contains ~30 wakes). The bit returning SET can only mean the ULP's store landed -
     * nothing else drives pad 8, and lora_pads_setup's own set already happened. Sampling the EVENT, not a guess. */
    {
        REG_WRITE(RTC_GPIO_OUT_W1TC_REG, 1u << (8 + 10));
        for (int i = 0; i < 20; i++) {
            vTaskDelay(pdMS_TO_TICKS(10));
            uint32_t o = REG_READ(RTC_GPIO_OUT_REG);
            if (o & (1u << (8 + 10))) {
                printf("EARLYTEST: ULP store LANDED after %d ms (OUT 0x%08X)\n", i * 10 + 10, (unsigned)o);
                break;
            }
            if (i == 19) printf("EARLYTEST: ULP store LOST (OUT 0x%08X)\n", (unsigned)o);
        }
        fflush(stdout);
    }
#endif
#endif
    /* Watchdog first (P06): a hung bridge takes the console *and* the flashing port with it. */
    esp_task_wdt_config_t wdt = { .timeout_ms = 5000, .idle_core_mask = 0, .trigger_panic = true };
    esp_task_wdt_reconfigure(&wdt);

    uart_config_t cfg = {
        .baud_rate = CONSOLE_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    /* GUARDRAIL: the RX ring must absorb a flash stall. `#b` seed lines arrive at ~263 B each and this task is the only
     * reader; a flash erase+program inside seed_poll froze it for 34 ms measured, the 1 KB ring overflowed, bytes were
     * lost mid-line, and the seeder still acked - the phase then compiled a truncated source (576 B image became 135 B)
     * and EXECUTE spun in code that had been pasted past its own body. 4 KB of HP RAM, 0 ULP bytes. The harness now also
     * verifies each ack's byte count, so a loss is a named refusal instead of a hang. */
    ESP_ERROR_CHECK(uart_driver_install(CONSOLE_UART, 4096, 1024, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(CONSOLE_UART, &cfg));

    printf("\nboot: ulp forth bridge, %u B image\n", (unsigned)(bin_end - bin_start));
    printf("type Forth at the prompt; 'picocom -b %d /dev/ttyACM1'\n", CONSOLE_BAUD);
    fflush(stdout);

    /* GUARDRAIL: boot the store BEFORE the ULP is started, so the first block request is answered from a validated
     * store rather than from a zeroed RAM array. A refusal here is named and printed; the console's `#x` formats. */
    store_boot();
#if !defined(ULP_EARLY)
    ESP_ERROR_CHECK(ulp_riscv_load_binary(bin_start, (size_t)(bin_end - bin_start)));
#endif

    /* Loud before anything else: if these disagree, every byte the user types is written to the wrong
     * place in the coprocessor's memory and the symptom looks like Forth corruption, not like a bug in
     * a size constant. Refuse to run the bridge at all rather than serve a broken console. */
#if defined(FOREIGN_ULP)
    /* GUARDRAIL: the first version wrote `if (0) {} else if (mismatch)` and the mismatch STILL fired - an else-if keeps
     * the test, it only re-homes where it runs. Disabling a check means replacing its condition, not wrapping it.
     * The handshake tests nothing here anyway: the foreign image defines none of these variables, so the values read are
     * whatever its own data occupies, and FATALing on them would boot nothing at all. */
    if (0) {
#else
    if (ulp_repl_cmd_bytes != CMD_SIZE || ulp_repl_out_bytes != OUT_SIZE) {
#endif
        printf("FATAL: ring size mismatch — ULP cmd=%u out=%u, host cmd=%u out=%u\n",
               (unsigned)ulp_repl_cmd_bytes, (unsigned)ulp_repl_out_bytes,
               (unsigned)CMD_SIZE, (unsigned)OUT_SIZE);
        fflush(stdout);
        for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
    }
    /* 1 000 ticks at the measured 6.46 us/tick = 6 460 us. The API takes microseconds. */
    ESP_ERROR_CHECK(ulp_set_wakeup_period(0, 6460));
#if defined(CANARY) && !defined(ULP_EARLY)
    canary_paint();                      /* before the ULP runs: the only moment the stack is untouched */
#endif
#if !defined(ULP_EARLY)
    ESP_ERROR_CHECK(ulp_riscv_run());
#endif
    ESP_LOGI(TAG, "ulp armed");

    /* GUARDRAIL: report the ULP's own wake counter before handing over. Without it, a silent console is
     * ambiguous — "the coprocessor never started" and "the coprocessor started and did nothing" look
     * identical from the port, and the counterfactual test in P41 is worthless if it cannot tell them
     * apart. This line is the proof that the ULP is alive; its absence is a different failure. */
    vTaskDelay(pdMS_TO_TICKS(500));
    printf("ulp woke %u times\n", (unsigned)ulp_repl_wake_count);
    /* GUARDRAIL: prove the paint did not land on live state BEFORE anything uses the block layer. These two words are
     * the only ULP globals that are zeroed at boot and never rewritten, which makes them the canary for the canary -
     * 0xA5A5A5A5 here cost two hours of chasing ERR_CRC through the LOAD path. Cheap, loud, at boot. */
    if (ulp_repl_blk_out > 1u || ulp_repl_blk_req > 1u) {
        printf("FATAL: ULP block flags read 0x%08x / 0x%08x - the stack paint is covering live .bss\n"
               "       (CANARY_BASE 0x%X vs pool budget %u B) - fix ULP_POOL_BUDGET before anything else\n",
               (unsigned)ulp_repl_blk_out, (unsigned)ulp_repl_blk_req, (unsigned)CANARY_BASE, (unsigned)ULP_POOL_BUDGET);
        fflush(stdout);
        for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
    }
    fflush(stdout);

    /* GUARDRAIL: console_task installs the UART driver, so it must exist before anything that prints at
     * startup — created the other way round, the server's own "blk size" diagnostic went nowhere and a
     * size of 0 looked like a silent protocol failure. The server still gets a higher priority, so it can
     * never be starved by the pump. */
    xTaskCreate(console_task, "console", 4096, NULL, 10, NULL);
    BaseType_t ok = xTaskCreate(block_task, "blocksrv", 2048, NULL, 12, NULL);
    printf("blocksrv %s\n", ok == pdPASS ? "up" : "FAILED"); fflush(stdout);
}

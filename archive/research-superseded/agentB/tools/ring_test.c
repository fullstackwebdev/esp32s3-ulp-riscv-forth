/* ring_test.c — drive the bridge's real drain (src/msg_expand.h: msg_drain_ring) over a wrapping ring
 * and check the stream comes out in order, complete, and exactly once, including the pass where the
 * staging buffer fills up just before a long message.
 *
 * GUARDRAIL: this exercises the ONE implementation the firmware uses — it does not re-implement the ring
 * walk. Testing a copy of the loop would prove nothing about the firmware, which is the way a benchmark
 * ends up measuring the wrong program (R9).
 *
 * GUARDRAIL: the producer must stop at RING-1 outstanding bytes, exactly like the ULP's pl_emit (which
 * drops and counts instead of overwriting) and like the console task (which stops when the cmd ring is
 * full). A test that keeps pushing into a full ring measures a ring that lost bytes, and then blames the
 * drain — the first version of this file did exactly that and reported 179 B of doubled text.
 *
 * GUARDRAIL: the staging buffer must be at least MSG_OUT_TEXT (the longest message, assert-checked in
 * msg_expand.h). With a smaller one the drain makes no progress on that message and the ring freezes —
 * a livelock, not a truncation, which is why MSG_OUT_TEXT is a compile-time constant and not a guess.
 */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "../src/msg_expand.h"

#define RING 128u                    /* the real ring's size; the indices wrap many times over this run */

static volatile uint8_t ring[RING];
static uint32_t head, tail;
static char got[512];
static uint32_t total, passes;

/* drain everything currently in the ring, exactly as console_task does (one bounded pass at a time) */
static int pump(void)
{
    while (tail != head) {
        char stage[MSG_OUT_TEXT];
        uint32_t n = msg_drain_ring(ring, RING - 1u, head, &tail, stage, sizeof stage);
        if (n == 0) { printf("FAIL  drain made no progress at tail=%u head=%u\n", tail, head); return 1; }
        if (total + n > sizeof got) { printf("FAIL  check buffer too small\n"); return 1; }
        memcpy(got + total, stage, n);
        total += n;
        passes++;
    }
    return 0;
}

static void push(uint8_t b)
{
    if (head - tail >= RING - 1u && pump()) return;
    ring[head & (RING - 1u)] = b;
    head++;
}
#define PUSH_STR(s) do { for (const char *q_ = (s); *q_; q_++) push((uint8_t)*q_); } while (0)

int main(void)
{
    /* 50 raw bytes (the echo of a typed line) then a 27 B message: at k = 50 the message cannot fit in a
     * 64 B staging buffer, so that pass must return the 50 bytes and leave the code UNREAD. */
    const char *want = "01234567890123456789012345678901234567890123456789"
                       "\ntasks need an empty stack\n" "\b \b" "\n" " ok\n" "Z";
    int fails = 0;

    PUSH_STR("01234567890123456789012345678901234567890123456789");
    push(MSG_TASK_STACK);
    push(MSG_ERASE);
    push('\n');
    push(MSG_OK);
    push('Z');
    if (pump()) return 1;

    if (total != strlen(want) || memcmp(got, want, total) != 0) {
        printf("FAIL  transcript mismatch\n  want %zu B: %s\n  got  %u B: %s\n", strlen(want), want, total, got);
        fails++;
    } else if (passes < 2) {
        printf("FAIL  only %u passes: the buffer-full retry path was never exercised\n", passes);
        fails++;
    } else {
        printf("ok   %u B out in %u passes through a %u B ring, %u B staging — order and content exact\n",
               total, passes, RING, (unsigned)MSG_OUT_TEXT);
    }
    if (tail != head) { printf("FAIL  ring not drained: tail=%u head=%u\n", tail, head); fails++; }
    else printf("ok   ring drained exactly once, no byte consumed twice or left behind\n");
    return fails ? 1 : 0;
}

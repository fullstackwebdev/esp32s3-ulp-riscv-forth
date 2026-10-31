/* msg_expand.h — the ONE implementation of "ULP output byte -> operator text" (R6, R9).
 *
 * Included by main/repl_main.c (the bridge that feeds UART) and by tools/expand.c (the host test filter
 * that expands a captured ULP transcript). Both therefore expand the same bytes the same way: a test
 * that used a second copy of this mapping would prove something about the copy, not about the bridge.
 *
 * Bytes below 0x80 are passed through unchanged (echoed input, digits, the offending word, '?', '\n');
 * bytes from 0x80 up are codes from msg_codes.h. An unlisted code yields a NAMED error line instead of
 * an empty string — a message that prints nothing looks exactly like a healthy line with no reply.
 */
#ifndef MSG_EXPAND_H
#define MSG_EXPAND_H

#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "msg_codes.h"

/* Staging size for one drain. GUARDRAIL: it must hold the LONGEST message; a message that can never fit
 * would be skipped on every pass with the ring head never advancing, freezing the console silently. The
 * per-entry assert below makes "it always fits at k == 0" a compile-time fact, so the caller's
 * "no room right now" break cannot become a livelock. */
#define MSG_OUT_TEXT 64u

#define MSG_STR(name, code, text) [code - MSG_BASE] = text,
static const char *const MSG_TEXT[] = { MSG_LIST(MSG_STR) };
#undef MSG_STR
#define MSG_N(name, code, text) + 1
enum { MSG_TEXT_N = 0 MSG_LIST(MSG_N) };
#undef MSG_N

/* GUARDRAIL: a code added to msg_codes.h without a string, or codes renumbered with a hole, makes the
 * table shorter than the list. Without this assert the array would get NULL slots and the operator
 * would read that as "the machine said nothing", which is the failure this scheme exists to prevent. */
_Static_assert(sizeof MSG_TEXT / sizeof MSG_TEXT[0] == MSG_TEXT_N,
               "msg_codes.h: a code has no string, or the codes are not contiguous");

#define MSG_L(name, code, text) \
    _Static_assert(sizeof text <= MSG_OUT_TEXT, #name " is longer than MSG_OUT_TEXT");
MSG_LIST(MSG_L)
#undef MSG_L

/* Expand one output byte. Returns the length and points *text at it; *text is either a table entry or
 * `scratch` (used for a raw byte, and for the ERR_ULPCODE line of an unknown code). Never returns 0. */
static size_t msg_byte_text(uint8_t b, char *scratch, size_t scratch_cap, const char **text)
{
    const char *t;
    size_t i;

    if (b < 0x80u) { scratch[0] = (char)b; *text = scratch; return 1u; }
    /* 0x80 is deliberately not a code, so this test is also the boundary check. */
    if (b >= MSG_BASE) {
        i = (size_t)(b - MSG_BASE);
        if (i < sizeof MSG_TEXT / sizeof MSG_TEXT[0] && (t = MSG_TEXT[i]) != NULL) {
            *text = t;
            return strlen(t);
        }
    }
    {
        int n = snprintf(scratch, scratch_cap, "\nulp: ERR_ULPCODE 0x%02x (unknown code)\n", (unsigned)b);
        size_t len = ((size_t)n < scratch_cap) ? (size_t)n : scratch_cap - 1u;
        *text = scratch;
        return len;
    }
}

/* Drain a ring of output bytes into `dst`, expanding codes. `in_head` is the ULP's write index, `*in_tail`
 * this side's read index (updated). Returns the bytes written to dst; a byte that does not fit is left
 * UNREAD so the next pass picks it up, which is what makes a bounded staging buffer lossless.
 *
 * GUARDRAIL: the consume happens after the fit check, and the tail is published by the caller — a version
 * that advanced the tail with the code it could not write would drop a message silently, and a dropped
 * message is indistinguishable from a healthy line that got no reply. The host test (tools/ring_test.c)
 * runs this exact function, including the no-room path, because that path only triggers when the buffer
 * happens to be nearly full and a board session would rarely produce it.
 */
static uint32_t msg_drain_ring(const volatile uint8_t *ring, uint32_t mask, uint32_t in_head,
                               uint32_t *in_tail, char *dst, uint32_t cap)
{
    uint32_t ot = *in_tail;
    uint32_t k = 0;
    char scratch[MSG_OUT_TEXT];

    while (ot != in_head && k < cap) {
        const char *t;
        size_t n = msg_byte_text(ring[ot & mask], scratch, sizeof scratch, &t);
        if (k + n > cap) break;              /* no room right now: leave this byte unread */
        memcpy(dst + k, t, n);
        k += (uint32_t)n;
        ot++;
    }
    *in_tail = ot;
    return k;
}

#endif

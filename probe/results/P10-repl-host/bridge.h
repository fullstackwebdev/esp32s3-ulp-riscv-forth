/* bridge.h - the P10 bridge model: dumb terminal <-> cmd ring -> ULP -> out ring -> terminal.
 *
 * Nothing here knows about Forth. The bridge only moves bytes and implements 06-repl.md
 * sections 3 and 5: the 0x1D escape table with exactly one byte of lookahead, and the XOFF
 * water mark at 75 % occupancy of the 128-byte command ring.
 */
#ifndef P10_BRIDGE_H
#define P10_BRIDGE_H

#define CMD_RING 128        /* command ring, measured in P04 */
#define OUT_RING 256        /* output ring, measured in P04  */
#define XOFF_WM  96         /* 75 % of CMD_RING: stop accepting above this */

#define BR_PASSTHROUGH 0
#define BR_FRAMED      1

typedef struct bridge {
    unsigned char cmd[CMD_RING]; unsigned cmd_w, cmd_r, cmd_n;   /* bytes from terminal to ULP */
    unsigned char out[OUT_RING]; unsigned out_w, out_r, out_n;   /* bytes from ULP to terminal */
    unsigned char mode;        /* BR_PASSTHROUGH | BR_FRAMED */
    unsigned char esc;         /* one byte of lookahead: a 0x1D with no second byte yet */
    unsigned char quit;        /* 0x1D q was seen */
    unsigned xoff;             /* 1 while occupancy >= XOFF_WM */
    unsigned accepted;         /* bytes that entered cmd[] */
    unsigned refused;          /* bytes held back by XOFF (never lost: the caller keeps them) */
    unsigned dropped;          /* bytes lost. Must stay 0. */
    unsigned esc_literal, esc_mode, esc_state, esc_quit, esc_unknown;
    unsigned long cks_in;      /* order/identity proof: checksum of bytes entering cmd[] */
    unsigned long cks_out;     /* checksum of bytes pulled out of cmd[] */
} bridge;

void br_init(bridge *b);
/* returns the number of bytes consumed from buf; the caller must keep buf[used..n) and offer
 * them again after the ULP has drained. Counts as XOFF when it stops early. */
unsigned br_feed(bridge *b, const unsigned char *buf, unsigned n);
/* the source has no more bytes this poll: a pending 0x1D is flushed as a literal. */
void br_idle(bridge *b);
int  br_cmd_get(bridge *b);            /* ULP side: next byte, or -1 when empty  */
unsigned br_cmd_n(const bridge *b);    /* occupancy                             */
void br_out_put(bridge *b, int c);     /* ULP side: emit one byte               */
int  br_out_get(bridge *b);            /* terminal side: drain, or -1 when empty */
void br_state_line(bridge *b, char *dst, unsigned cap);  /* one ASCII line, NUL-terminated */

#endif

/* P34: P31's generated primitive table, unchanged, plus the one primitive the Forth paging words
 * cannot be: the request/bounded-wait/response handshake over the mailbox (P16: one outstanding
 * request only; 144 us per 512 B fetch).
 * GUARDRAIL: the extra entry lives in this wrapper, not inside p31_prims.inc — editing the
 * generated table would change what every earlier variant's row means (P31 kept it one entry per
 * line precisely so a primitive could be priced by ID). */
#include "p31_prims.inc"
#if defined(P34_FAR)
X(FARXFER,"FAR-XFER",0)
#endif

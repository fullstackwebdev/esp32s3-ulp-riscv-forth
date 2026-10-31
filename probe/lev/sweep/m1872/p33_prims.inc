/* P33: P31's generated primitive table, unchanged, plus the one primitive a visible block layer
 * cannot be Forth: the request/bounded-wait/response handshake over the mailbox.
 * GUARDRAIL: the extra entry lives in this wrapper, not inside p31_prims.inc — editing the
 * generated table would change what every earlier variant's row means (P31 kept it one entry per
 * line precisely so a primitive could be priced by ID). */
#include "p31_prims.inc"
#if defined(P33_BLOCK)
X(BLKXFER,"BLKXFER",0)
#endif

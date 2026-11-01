\ Gate 2 for LANE-MAIL: the page arithmetic and the list indexing of examples/apps/mail/mail1.fs,
\ as words. The phase cannot be run without the store, so the numbers it computes are pinned here.
\ START 80 is the mail content base (docs/26 block table: mail 80-103, three pages): page p is seeded at
\ 80 + 8p, and the list is lines 1..2 of page 0, so item i is block 81+i and opens page 1+i.
\ The mirrors below are the phase's own bodies: PB/IB/IP are its addressing, NX/PV its n/p clamp,
\ JD/KU its selection move, NM its quit-marker normalisation.
( PB page -> block, the one literal the whole phase derives its block numbers from)
: PB ( p -- b ) 8 * 80 + ;
\ GUARDRAIL: item i is line 1+i of page 0, so block 81+i - not 80+i, which is the heading line.
: IB ( i -- b ) 81 + ;
: IP ( i -- p ) 1+ ;
\ GUARDRAIL: there is no `>` on this machine, so a clamp is written with `<`, `=` and the operands swapped.
: NX ( p -- p ) DUP 2 < IF 1+ THEN ;
: PV ( p -- p ) DUP 1 = IF EXIT THEN 1- ;
: JD ( s -- s ) DUP 0= IF DROP 1 THEN ;
: KU ( s -- s ) DUP IF DROP 0 THEN ;
\ GUARDRAIL: view 3 is the quit marker the main loop tests; DR normalises it to 0 (the list) or a re-entry draws a body.
: NM ( v -- v ) 2 OVER < IF DROP 0 THEN ;
0 PB . 1 PB . 2 PB . 10 EMIT
2 PB 7 + . 10 EMIT
0 IB . 1 IB . 10 EMIT
0 IP . 1 IP . 10 EMIT
0 IP PB . 1 IP PB . 10 EMIT
1 NX . 2 NX . 1 PV . 2 PV . 10 EMIT
0 JD . 1 JD . 1 KU . 0 KU . 10 EMIT
0 NM . 1 NM . 2 NM . 3 NM . 10 EMIT

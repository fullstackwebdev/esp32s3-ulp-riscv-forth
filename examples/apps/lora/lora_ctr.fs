\ lora_ctr.fs - the CTR layer: keystream into ST, XOR over
\ BUF, counter bump.
\
\ WHY SEPARATE FROM THE CIPHER: measured, lora_aes.fs plus
\ these words ended at free 0 B with CXB onwards refused
\ with ERR_DICT. NONC and BUF are packet data, so they live
\ with the packet layer. Load AFTER lora_aes.fs: a phase
\ cannot see another phase's words, and this file calls AESB.
\
\ GUARDRAIL: the counter is the LAST byte only (15 NONC +
\ ...). Data{portnum,payload} fits one 16 B block, so a
\ carry into the next byte never happens here; a larger frame
\ needs the block loop and a real 128-bit increment.
CREATE BUF
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
CREATE NONC
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
  0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C, 0 C,
CREATE LEN 0 C, 0 C,

: CPYN ( -- ) NONC SRC ! CPYS ;
: CXB ( -- ) BUF A C@ + DUP C@ A C@ ST + C@ XOR SWAP C! ;
: CXOR ( -- )
  0 A C! BEGIN A C@ LEN C@ < WHILE CXB A C@ 1+ A C! REPEAT ;
: INCB ( -- ) 15 NONC + DUP C@ 1+ SWAP C! ;
: CTR ( n -- ) LEN C! CPYN AESB CXOR INCB ;

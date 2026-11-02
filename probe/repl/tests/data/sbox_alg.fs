\ sbox_alg.fs - can the AES S-box be COMPUTED cheaper than
\ the 256 B table it replaces? Measure, do not guess.
\
\ S(x) = affine(inv(x)) in GF(2^8), poly 0x11B, affine
\ constant 0x63 (FIPS-197 5.1.1).
\
\ GUARDRAIL: every control structure is COMPLETE on one
\ typed line - BEGIN..WHILE..REPEAT inside a single line,
\ which is what the engine accepts (measured: splitting it
\ answers ERR_STACK and the word never exists). The loop
\ body is a named helper so the REPEAT line stays under
\ 63 B, the ring limit that drops longer lines SILENTLY.
\
\ GUARDRAIL: `2*` is NOT a word on this machine. The linter
\ answered R2 order and the board would have refused the
\ definition; the doubling is `2 *`.
\
\ GUARDRAIL: the rotations are FOUR explicit cells, not
\ `ROL1` applied to the running sum. Rotating the
\ accumulated XOR adds rotl^2 of everything instead of
\ rotl(b) for each step - it produced a wrong S-box that
\ still looked like bytes. Measured against the table.
\
\ GUARDRAIL: inv(x) = x^254 is an ADDITION CHAIN, not a
\ loop: 7 squarings and 6 multiplies cover the binary
\ exponent 11111110.

CREATE MA 0 ,
CREATE MB 0 ,
CREATE MP 0 ,
CREATE GC 0 ,
CREATE ISQ 0 ,
CREATE IPR 0 ,
CREATE IB 0 ,
CREATE R1 0 ,
CREATE R2 0 ,
CREATE R3 0 ,
CREATE R4 0 ,

: XT ( a -- 2a )
  DUP 128 AND IF 2 * 255 AND 27 XOR ELSE 2 * 255 AND THEN ;

: GSTP ( -- )
  MB @ 1 AND IF MP @ MA @ XOR MP ! THEN
  MA @ XT MA !
  MB @ 1 RSHIFT MB ! GC @ 1+ GC ! ;

: GFMUL ( a b -- p )
  MB ! MA ! 0 MP ! 0 GC !
  BEGIN GC @ 8 < WHILE GSTP REPEAT MP @ ;

: GINV ( x -- i )
  ISQ ! 1 IPR !
  ISQ @ ISQ @ GFMUL ISQ ! IPR @ ISQ @ GFMUL IPR !
  ISQ @ ISQ @ GFMUL ISQ ! IPR @ ISQ @ GFMUL IPR !
  ISQ @ ISQ @ GFMUL ISQ ! IPR @ ISQ @ GFMUL IPR !
  ISQ @ ISQ @ GFMUL ISQ ! IPR @ ISQ @ GFMUL IPR !
  ISQ @ ISQ @ GFMUL ISQ ! IPR @ ISQ @ GFMUL IPR !
  ISQ @ ISQ @ GFMUL ISQ ! IPR @ ISQ @ GFMUL IPR !
  ISQ @ ISQ @ GFMUL ISQ ! IPR @ ISQ @ GFMUL IPR !
  IPR @ ;

: ROL1 ( b -- r )
  DUP 128 AND IF 2 * 255 AND 1 OR ELSE 2 * 255 AND THEN ;

: AFF ( i -- s )
  IB !
  IB @ ROL1 R1 !
  R1 @ ROL1 R2 !
  R2 @ ROL1 R3 !
  R3 @ ROL1 R4 !
  IB @ R1 @ XOR R2 @ XOR
  R3 @ XOR R4 @ XOR 99 XOR ;

: SB ( b -- s ) GINV AFF ;

\ hdr.fs — the P54 header shape: the two things a 3-byte entry can get wrong SILENTLY.
\ Failure mode 1: the stride is not what the layout assumes. LATEST is the newest header's address
\ (LATEST pushes V_LATEST), so one definition moves it down by exactly one entry, i.e. 3.
LATEST : H1 ; LATEST - .
\ Failure mode 2: the immediate flag no longer reaches a lookup. An IMMEDIATE word runs while the
\ NEXT word is being COMPILED, so its output has to appear BEFORE the output of the definition it
\ sits inside — that ordering is the only visible proof, since running it either way prints a char.
: HI 42 EMIT ; IMMEDIATE
: USEHI 43 EMIT HI 44 EMIT ;
USEHI

\ flagship_common.fs — resident scaffold shared by all flagship phases: the block numbers and the scratch cells.
\ GUARDRAIL: define the shared names ONCE, resident, instead of re-defining them in every phase. Re-defining
\ constants and cells per phase (and re-defining a helper named HIST) made later phases fail to define their own
\ words in this engine - measured as a word that is clearly defined (head -12 of the phase succeeds) yet cannot be
\ found one line later. One resident definition per name removes the whole class.
4 CONSTANT DATABLK
12 CONSTANT HISTBLK
13 CONSTANT XFM
CREATE vb1 0 ,
CREATE vb2 0 ,
CREATE vb3 0 ,
CREATE vb4 0 ,
CREATE vb5 0 ,

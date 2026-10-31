SHELVED, NOT RUN BY THE SUITE. The 6-phase flagship program (the row that would decide whether the 846 B
resident cost is worth paying at scale).

State when shelved:
  flagship_a  = the existing tests/capacity_a.fsx (fill + basic statistics) - WORKS, 606 B, numbers verified
                against Python (8128 690880 0 0 127).
  flagship_b  = 16-bucket histogram of the data window - IN PROGRESS, errors. The first version kept TWO block
                addresses at once and silently read the wrong bytes; see the GUARDRAIL in the file.
  flagship_c  = verify the histogram out of the store - written, verified only against bad data.
  flagship_d  = write a transform of the data into another block - errors.
  flagship_e  = read that block back and count mismatches - errors.

The constraint that stopped it, measured: THE WINDOW HOLDS ONE BLOCK. Reading the source block and writing a
destination block in the same phase cannot be done by keeping two addresses - the second fetch overwrites the
window (measured: histogram buckets summing to 44 instead of 128). The correct pattern, which phase B was being
rewritten to, is: read the source window, compute into PHASE-LOCAL CELLS, then fetch the destination block,
write it, and SAVE (UPDATE alone leaves the store's old bytes, measured as all zeros).

Next step for whoever picks this up: rewrite B with that pattern (the cells and the TALLY loop in the file are
correct), then D/E as a write/verify pair, then F as a padded report. Each phase must fit ~704 B.

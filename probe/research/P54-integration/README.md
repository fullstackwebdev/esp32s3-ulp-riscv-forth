# P54 integration — the two patches that were actually merged

Idea 1 (`P54-ops`, table-driven kernel) was applied by copying the five source files it touched.
Ideas 2 and 3 both rewrote the **same line** in `mkhdr_pad`, so they were merged as patches:

| file | what it is |
| --- | --- |
| `idea2.patch` | `var_f_c_plus_d`: one `errf_msg()` helper plus a single shared tail behind the six-way message selection — 5 hunks, pool −52 B |
| `idea3.patch` | 3-byte headers `hash13 | xt10/2 | imm1` — 7 hunks, but **hunk 6 does not apply** to a tree that already has idea 2 |

That conflict is the interesting part and it is why this directory exists: hunk 6 replaces `mkhdr_pad`
wholesale, and idea 2 had already turned its room-check line into `errf_msg(MSG_ERR_DICT)`. The merge
took idea 3's body and kept idea 2's error form on both sites, asserted in code
(`assert new_fn.count("errf_msg") == 2`). A mechanical `patch` would have silently reverted idea 2's
win on those two lines.

Measured result of the merged pair (baked at `MEMSZ` 1688): pool 7 853 / 7 856, `.text` 4 926,
dictionary 255 B, **app space 727 B**.

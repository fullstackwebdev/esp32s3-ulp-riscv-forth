#!/usr/bin/env python3
"""Regenerate src/foreign_ulp.h from probe/lora's ULP binary.

GUARDRAIL: an embedded binary must be regenerated, never hand-edited, and the file it embeds must be the one that is
KNOWN to work on the board (probe/lora's, which reports tx_ok rising). Regenerate after every rebuild of probe/lora or
the experiment silently tests yesterday's image.
"""
import pathlib
root = pathlib.Path(__file__).resolve().parents[2].parent
b = (root / "probe/lora/build/esp-idf/main/ulp_lora/ulp_lora.bin").read_bytes()
out = ["/* GUARDRAIL: the FOREIGN image - probe/lora's ULP binary, embedded verbatim so this app can boot it. F-165's\n"
       " * whole point is that the ULP program is the one known to work on this board; the app loading it is the variable.\n"
       " * Regenerate with: python3 tools/embed_ulp.py  (kept beside this file). */\n",
       "#ifndef FOREIGN_ULP_H\n#define FOREIGN_ULP_H\n", "#include <stdint.h>\n",
       f"static const uint32_t foreign_ulp_bin_len = {len(b)}u;\n",
       "static const uint8_t foreign_ulp_bin[] = {\n"]
for i in range(0, len(b), 12):
    out.append("    " + ",".join(str(x) for x in b[i:i + 12]) + ",\n")
out += ["};\n", "#endif\n"]
pathlib.Path(__file__).resolve().parents[1].joinpath("src/foreign_ulp.h").write_text("".join(out))
print("foreign_ulp.h:", len(b), "bytes embedded")

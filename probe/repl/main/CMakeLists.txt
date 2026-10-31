# P39: the HP side is the p39 driver; the ULP side is our engine + prelude + one line.
# GUARDRAIL: the ULP source must live in src/ next to uforth.c — ulp_p39.c includes "uforth.c" and
# the .inc files by quoted include, which resolves relative to ulp_p39.c's own directory. Adding
# include dirs here instead would let the ULP pick up a *different* uforth.c than the host build.
set(COMPONENT_SRCS "repl_main.c")
set(COMPONENT_ADD_INCLUDEDIRS "")
set(COMPONENT_REQUIRES ulp soc esp_timer esp_hw_support driver esp_system)

register_component()

set(ulp_app_name ulp_main)
# REPL_ULP_STUB=1 builds the counterfactual image (src/ulp_stub.c): same bridge, no evaluator.
if(DEFINED ENV{REPL_ULP_STUB})
  set(ulp_riscv_sources "${CMAKE_CURRENT_LIST_DIR}/../src/ulp_stub.c")
elseif(DEFINED ENV{REPL_ULP_SRC})
  # P42: an alternative ULP source tree (same HP bridge), used to compare two fetch implementations.
  set(ulp_riscv_sources "$ENV{REPL_ULP_SRC}")
else()
  set(ulp_riscv_sources "${CMAKE_CURRENT_LIST_DIR}/../src/ulp_repl.c")
endif()
set(ulp_exp_dep_srcs "repl_main.c")

# GUARDRAIL: -msave-restore measured -224 B of .text on this image (4 828 -> 4 604, flagtest/), the largest
# single byte win available without touching source. The ULP sub-build takes its flags from IDF's own
# toolchain file, which offers no "extra flags" hook — the supported path is EXTRA_CMAKE_ARGS, which
# IDF forwards to the external project's command line. Passing -DCMAKE_C_FLAGS REPLACES that baseline,
# so the baseline is READ OUT OF IDF'S TOOLCHAIN FILE here rather than retyped: a second copy of
# "-Os -march=rv32imc_zicsr_zifencei -mdiv ..." would silently diverge the day IDF changes it, and a
# missing -mdiv or -march is a different machine, not an optimisation. Fails loudly if the file changes shape.
set(_ulp_tc "${idf_path}/components/ulp/cmake/toolchain-ulp-riscv.cmake")
file(READ "${_ulp_tc}" _ulp_tc_text)
string(REGEX MATCH "set\\(CMAKE_C_FLAGS \"([^\"]*)\"" _ulp_m "${_ulp_tc_text}")
if(NOT CMAKE_MATCH_1)
  message(FATAL_ERROR "ULP toolchain flags not found in ${_ulp_tc} — refusing to build with a guessed baseline")
endif()
# GUARDRAIL: -fno-strict-aliasing is a CORRECTNESS flag here, not a pessimisation. vm_copy copies the VM
# through a u32* while W/IP are u16, which is a strict-aliasing violation; -O2/-Os exploited it and a resumed
# task ran another task's body (F-122: measured -O0/-O1 correct, -O2/-Os wrong, this flag correct again).
# Cost: +16 B of .text, versus +68 B for the type-safe rewrite that removes the violation outright.
# GUARDRAIL: the day someone writes that rewrite, this flag can go — but it must not be dropped first.
# GUARDRAIL: seven flags measured one at a time on the twin, each against the shipping baseline, then as a
# set: -fno-tree-vrp -fno-tree-loop-im -fno-tree-fre -fno-tree-scev-cprop -fno-tree-forwprop -fno-tree-sink
# -fno-move-loop-invariants. Together .text 4 788 -> 4 696 (-92 B, and every byte of text is a byte of
# application space). Each was negative ALONE too (-12, -42, -24, -8, -4, -2 and the set re-measured at -92);
# none was accepted from an assumption. They disable value-range propagation, loop-invariant motion, full
# redundancy elimination, scalar-evolution copy propagation, forward propagation and sinking.
# GUARDRAIL: this is a TRADEOFF, not free optimisation: those passes normally make code faster and smaller,
# and on this target they make it BIGGER (more live values across the big switch, more spill/restore traffic
# in a machine with 16 registers). Expect modestly slower dispatch; the objective here is bytes, and the
# correctness proof is the host suite run with this exact flag set plus the board checks, NOT this comment.
# GUARDRAIL: the HOST build does not use these flags, so a green host suite alone would NOT validate them —
# tests/run.sh's binaries are built without them. Run the twin check when changing this line.
set(_ulp_cflags "${CMAKE_MATCH_1} -msave-restore -fno-strict-aliasing -fno-tree-vrp -fno-tree-loop-im -fno-tree-fre -fno-tree-scev-cprop -fno-tree-forwprop -fno-tree-sink -fno-move-loop-invariants")
message(STATUS "ULP C flags: ${_ulp_cflags}")
idf_build_set_property(EXTRA_CMAKE_ARGS "-DCMAKE_C_FLAGS=${_ulp_cflags}" APPEND)

ulp_embed_binary(${ulp_app_name} "${ulp_riscv_sources}" "${ulp_exp_dep_srcs}")

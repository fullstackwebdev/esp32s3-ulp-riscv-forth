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

ulp_embed_binary(${ulp_app_name} "${ulp_riscv_sources}" "${ulp_exp_dep_srcs}")

# P39: the HP side is the p39 driver; the ULP side is our engine + prelude + one line.
# GUARDRAIL: the ULP source must live in src/ next to uforth.c — ulp_p39.c includes "uforth.c" and
# the .inc files by quoted include, which resolves relative to ulp_p39.c's own directory. Adding
# include dirs here instead would let the ULP pick up a *different* uforth.c than the host build.
set(COMPONENT_SRCS "p39_main.c")
set(COMPONENT_ADD_INCLUDEDIRS "")
set(COMPONENT_REQUIRES ulp soc esp_timer esp_hw_support driver esp_system)

register_component()

set(ulp_app_name ulp_main)
set(ulp_riscv_sources "${CMAKE_CURRENT_LIST_DIR}/../src/ulp_p39.c")
set(ulp_exp_dep_srcs "p39_main.c")

ulp_embed_binary(${ulp_app_name} "${ulp_riscv_sources}" "${ulp_exp_dep_srcs}")

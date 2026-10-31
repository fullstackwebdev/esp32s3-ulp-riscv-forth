# Minimal app component: it only exists to give ulp_embed_binary a component to hang off.
set(COMPONENT_SRCS "main.c")
set(COMPONENT_ADD_INCLUDEDIRS "")
set(COMPONENT_REQUIRES ulp)

register_component()

set(ulp_app_name ulp_main)
set(ulp_riscv_sources "${CMAKE_CURRENT_LIST_DIR}/../../ulp_stubs.c")
set(ulp_exp_dep_srcs "")

ulp_embed_binary(${ulp_app_name} "${ulp_riscv_sources}" "${ulp_exp_dep_srcs}")

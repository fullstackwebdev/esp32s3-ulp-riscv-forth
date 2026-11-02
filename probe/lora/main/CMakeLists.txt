# Legacy component style on purpose: it is what the installed IDF 5.4 ULP-RISC-V examples use (ulp_embed_binary).
# GUARDRAIL: legacy component style - use add_definitions(), not target_compile_definitions(${COMPONENT_LIB}).
if(LORA_STAY_AWAKE)
    add_definitions(-DCONFIG_LORA_STAY_AWAKE=1)
endif()

set(COMPONENT_SRCS "lora_main.c")
set(COMPONENT_ADD_INCLUDEDIRS "")
set(COMPONENT_REQUIRES soc ulp driver esp_timer)
register_component()

set(ulp_app_name ulp_lora)

# ULP-RISC-V sources. The ULP directory must not appear in COMPONENT_SRCS.
set(ulp_riscv_sources "ulp/ulp_main.c" "ulp/sx126x_ulp_hal.c" "ulp/sx126x_min.c")

# This file includes the generated ulp_lora.h that exports the ULP's variables.
set(ulp_exp_dep_srcs "lora_main.c")

ulp_embed_binary(${ulp_app_name} "${ulp_riscv_sources}" "${ulp_exp_dep_srcs}")

# The bit-bang loop IS the measurement (docs/28 §4.4): build that translation unit for speed, not for debug (-Og).
set_source_files_properties(
    "ulp/sx126x_ulp_hal.c"
    PROPERTIES COMPILE_OPTIONS "-O2"
)

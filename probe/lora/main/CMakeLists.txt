# Legacy component style on purpose: it is what the installed IDF 5.4 ULP-RISC-V examples use (ulp_embed_binary).
# GUARDRAIL: legacy component style - use add_definitions(), not target_compile_definitions(${COMPONENT_LIB}).
if(LORA_STAY_AWAKE)
    add_definitions(-DCONFIG_LORA_STAY_AWAKE=1)
endif()

# GUARDRAIL: F-170's cut needs the define on the ULP side, which is fed by LORA_FLAGS (see LORA_REPL_FLAGS below),
# not by add_definitions - the ULP is a separate sub-build and a flag that reaches one build is a footgun (F-160).
if(LORA_MIN)
    set(LORA_FLAGS "${LORA_FLAGS} -DLORA_MIN=1")
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

# GUARDRAIL: F-160 bisect - build this KNOWN-GOOD ULP with probe/repl's exact flag set. Those flags exist because GCC
# miscompiled the interpreter on this target (F-122 and the byte sweep), so they are the one difference nobody has tested
# against a working radio. If the store stops landing here, the flags - not the board, not the Forth image - are the cause.
if(LORA_REPL_FLAGS)
    set(_tc "${idf_path}/components/ulp/cmake/toolchain-ulp-riscv.cmake")
    file(READ "${_tc}" _tct)
    string(REGEX MATCH "set\\(CMAKE_C_FLAGS \"([^\"]*)\"" _m "${_tct}")
    if(NOT CMAKE_MATCH_1)
        message(FATAL_ERROR "ULP baseline flags not found - refusing to guess")
    endif()
    set(_seed "${CMAKE_MATCH_1}")
    # GUARDRAIL: the flag set is a PARAMETER, so a bisect is one -D per build instead of one source edit per build. The
    # whole set was what broke the store, so which member matters is the next question and it should cost flashes, not edits.
    set(_replbs "-msave-restore -fno-strict-aliasing -fno-tree-vrp -fno-tree-loop-im -fno-tree-fre -fno-tree-scev-cprop -fno-tree-forwprop -fno-tree-sink -fno-move-loop-invariants -fno-ssa-phiopt -fno-tree-pre")
    if(DEFINED LORA_FLAGS)
        set(_replbs "${LORA_FLAGS}")
    endif()
    idf_build_set_property(EXTRA_CMAKE_ARGS "-DCMAKE_C_FLAGS=${_seed} ${_replbs}" APPEND)
    message(STATUS "ULP extra flags: ${_replbs}")
endif()

ulp_embed_binary(${ulp_app_name} "${ulp_riscv_sources}" "${ulp_exp_dep_srcs}")

# The bit-bang loop IS the measurement (docs/28 §4.4): build that translation unit for speed, not for debug (-Og).
set_source_files_properties(
    "ulp/sx126x_ulp_hal.c"
    PROPERTIES COMPILE_OPTIONS "-O2"
)

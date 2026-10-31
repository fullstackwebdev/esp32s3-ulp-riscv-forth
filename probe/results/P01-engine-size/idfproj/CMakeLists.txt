# Throwaway ESP-IDF project for probe P01: only exists so that ulp_embed_binary builds the uforth
# engine with the supported ULP-RISC-V path. Host only, nothing is ever flashed.
cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(p01_engine_size)

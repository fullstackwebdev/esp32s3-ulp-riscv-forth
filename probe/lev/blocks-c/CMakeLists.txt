# P39: ESP-IDF project for the first on-chip run of our engine. Builds the ULP image with
# ulp_embed_binary (the supported ULP-RISC-V path) and flashes the HP app + ULP .bin over
# /dev/ttyACM1.
cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(p39_first_chip_run)

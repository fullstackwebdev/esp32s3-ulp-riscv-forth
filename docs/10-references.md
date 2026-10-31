# 10 — Reference material: what we actually hold, and what it is good for

Written because the question "do we have the manual?" kept needing a search to answer. Everything below is in
`cache/` (bytes, hashes and journal entries) or in the local IDF tree. Nothing here is fetched twice; nothing
here is a summary of a summary.

---

## 1. Held, cached, hashed

| Source | Where | Size | What it is authoritative for |
|---|---|---|---|
| **ESP32-S3 Technical Reference Manual v1.8** | `cache/objects/b944c82a…/v0001.bin` (sha256 `4484bf8a69035ec4…`), text at `cache/derived/esp32s3-trm.txt` | 14.5 MB, **1 531 pages** | register semantics, memory map, sleep/wake workflow, the ULP chapter (§2, p. 304) |
| **ULP RISC-V API guide (IDF 5.5)** | `cache/objects/2bb0d599…/v0001.bin`, text at `cache/derived/2bb0d599….txt` | 118 KB HTML | the supported C API, macros and build flow |
| **IDF source + headers** | `$IDF_PATH` (v5.4) | — | `soc/esp32s3/register/soc/rtc_cntl_reg.h` and friends: the register map as *machine-readable* truth, generated from the same manual |
| **RISC-V ISA manual (unprivileged, ratified 20191213)** | `cache/objects/b15c7807…/v0001.bin`, text at `cache/derived/riscv-isa-spec-20191213.txt` | 1.0 MB, **238 pages** | normative RV32I/RV32M/RV32C semantics: what `lhu` does with an unaligned address, what `div` does on divide-by-zero, which encodings exist |
| **RISC-V ELF psABI 1.0** | `cache/objects/652cde45…/v0001.bin`, text at `cache/derived/riscv-elf-psabi-1.0.txt` | 274 KB, **56 pages** | the calling convention we are bound to: ILP32, `a0-a7` arguments, soft-float, `EF_RISCV_RVC` |
| **Toolchain** | `riscv32-esp-elf-gcc 14.2.0` | — | the ISA actually implemented: `-march` is what the ULP accepts, not what a PDF says |

Adopting the manual was itself a cache operation — it was fetched through `tools/fetch.py`, so the URL, the
final URL, the HTTP status, the byte count and the sha256 are journaled. There is no way to reach a state where
"the manual" means something different in two weeks.

## 2. The numbers the manual *does* give — and they change the design

TRM §2.6.1: the coprocessor supports **RV32IMC**, 32 general-purpose registers, a 32-bit multiplier and divider,
and interrupts. TRM §2.6.2 **Table 2.6-1** gives the cost of the arithmetic that a small Forth cannot avoid:

| Instruction | Cycles | |
|---|---|---|
| `MUL` | **34** | lower 32 bits of a product |
| `MULH` / `MULHU` / `MULHSU` | **66** | upper 32 bits |
| `DIV` / `DIVU` / `REM` / `REMU` | **34** | quotient, remainder |

Read against the measured budget (P05: 122.6 cycles/tick; P14: 1 074 cycles per dispatch) that means:

* one `*` or `/` in Forth costs **28 % of a wake** and **3.2 % of a token dispatch**;
* `MULH` costs **more than half a wake**, so a double-width multiply in the inner loop is out of the question;
* spending a multiply to avoid a shift in an index computation is never worth it — `slli` is one cycle.

Verified against the compiler rather than assumed (`probe/isa/codegen.c`, built with the ULP's exact flags):
`mul`, `div`, `rem` each compile to **one instruction with no stack frame**, so the 34 cycles are the
instruction, not a library call. And `ret` assembles to a 2-byte `c.jr`, so **compressed encodings are live** —
hand-written assembly can buy code density, not just cycles.

## 3. The ISA boundary is a command line, not a document

Taken from the ULP sub-build's own `compile_commands.json` (`build/esp-idf/main/ulp_main/`), which is the
authority for what was actually compiled:

```
-Os -march=rv32imc_zicsr_zifencei -mdiv -ffunction-sections -fdata-sections
```

`-march=rv32imc_zicsr_zifencei` is the whole contract. `zicsr` is why `rdcycle` works (P05) and `zifencei` is a
formality for a core with no instruction cache. ABI: **ILP32, soft-float** — `a0-a7` carry arguments, `a0-a1`
return values, and there is no hardware stack, so every `call` costs a `sw`/`lw` pair through software `sp`.

## 4. What the manual does **not** answer

This matters more than what it does, because it decides where optimisation effort goes.

* **No per-instruction timing for the ULP RISC-V.** §1.7 "Instruction Performance" is about the Xtensa cores.
  §2.5.2.1 "ALU – Perform Arithmetic and Logic Operations" is about the *ULP-FSM*, a different machine. The
  RISC-V coprocessor's cycle costs are simply not in this document.
  **Source of truth instead:** `rdcycle` on the chip — P05 (122.6 cycles/tick, 6.46 µs), P14 (1 074
  cycles/dispatch, 90.9 % of it token fetch). Those remain the only numbers we trust for timing.
* **No wake-cause field name we could use.** P06 found the wake cause reads 0 on every wake; the TRM's §2.4
  describes the sleep/wake *workflow* without naming a readable cause register for the coprocessor. The finding
  stands on measurement, not on documentation.
* **No compiler guidance.** Whether a C construct costs 4 bytes of code or 40 is decided by GCC at `-Os` with
  the ULP's linker script; the manual has nothing to say. `.su` files and `nm -S` remain the evidence (the rule
  in `02-harness.md`).

## 5. The rule this document enforces

A fact belongs in the docs with **one** of three pedigrees, stated plainly:

1. **measured** on this board (with a probe number),
2. **read** in a named section of a cached source, or
3. **derived** from a compiler artifact (`nm`, `.su`, `.map`, ELF).

Anything else is a rumour, and the project has three corrections on the books (P25, P32, and the `COCPU_*`
wedge) that began as rumours which happened to be true.

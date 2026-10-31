       
ENTRY(reset_vector)
MEMORY
{
    /* P22: LENGTH is the 8176 B RTC pool MINUS the 320 B C stack of P21 (worst case 244 B),
     * i.e. 7856. The stock script sets LENGTH = 8176 and __stack_top = top of the region, so the
     * C stack grows down into .bss and nothing at link time reserves it.
     * GUARDRAIL: leave the 320 B subtracted here — putting LENGTH back to 8176 makes the link
     * pass by silently overlapping the dictionary with the C stack, which is exactly the mistake
     * P21 was run to stop. */
    /* P35 optimistic: LENGTH stays 7856 with __stack_top at its top, i.e. sections may use the
     * whole 7856 B and the 320 B C stack grows down into the last of them. This is the convention
     * P22/P29/P31 linked under, and it is kept here only as the "stack not reserved" case.
     * GUARDRAIL: this script is the OPTIMISTIC case — quoting its MEMSZ alone would repeat P32's
     * 1120 B optimism; every figure from it is reported beside pk_stack's. */
    ram(RW) : ORIGIN = 0, LENGTH = 7856   /* 8176 - 320 (P21 C stack), sections get all of it */
}
SECTIONS
{
    . = ORIGIN(ram);
    .text :
    {
        *ulp_riscv_vectors.S.obj(.text.vectors)
        *(.text)
        *(.text*)
    } >ram
    .rodata ALIGN(4):
    {
        *(.rodata)
        *(.rodata*)
    } > ram
    .data ALIGN(4):
    {
        *(.data)
        *(.data*)
        *(.sdata)
        *(.sdata*)
    } > ram
    .bss ALIGN(4) :
    {
        *(.bss)
        *(.bss*)
        *(.sbss)
        *(.sbss*)
    } >ram
    __stack_top = ORIGIN(ram) + LENGTH(ram);
}

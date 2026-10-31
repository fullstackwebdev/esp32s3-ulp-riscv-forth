       
ENTRY(reset_vector)
MEMORY
{
    /* P22: LENGTH is the 8176 B RTC pool MINUS the 320 B C stack of P21 (worst case 244 B),
     * i.e. 7856. The stock script sets LENGTH = 8176 and __stack_top = top of the region, so the
     * C stack grows down into .bss and nothing at link time reserves it.
     * GUARDRAIL: leave the 320 B subtracted here — putting LENGTH back to 8176 makes the link
     * pass by silently overlapping the dictionary with the C stack, which is exactly the mistake
     * P21 was run to stop. */
    ram(RW) : ORIGIN = 0, LENGTH = 7856   /* 8176 - 320 (P21 C stack) */
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

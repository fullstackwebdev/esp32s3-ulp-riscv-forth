       
ENTRY(reset_vector)
MEMORY
{
    /* P22: LENGTH is the 8176 B RTC pool MINUS the 320 B C stack of P21 (worst case 244 B),
     * i.e. 7856. The stock script sets LENGTH = 8176 and __stack_top = top of the region, so the
     * C stack grows down into .bss and nothing at link time reserves it.
     * GUARDRAIL: leave the 320 B subtracted here — putting LENGTH back to 8176 makes the link
     * pass by silently overlapping the dictionary with the C stack, which is exactly the mistake
     * P21 was run to stop. */
    /* P35 honest: the 320 B C stack is carved INSIDE the 8176 B pool, so sections get 7536 and the
     * stack lives in 7536..7856. __stack_top is the end of the pool (7856), not of the region.
     * GUARDRAIL: __stack_top must be ORIGIN + LENGTH + 320 here, not ORIGIN + LENGTH — that is the
     * one-line fix P32 §5.1 asked for. Without it the stack silently overlaps .bss and the link
     * "passes" 320 B past the machine's real ceiling (P32 §1.2). */
    ram(RW) : ORIGIN = 0, LENGTH = 7536   /* 8176 - 320 (P21 C stack) carved out of the pool */
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
    __stack_top = ORIGIN(ram) + LENGTH(ram) + 320;   /* end of the 8176 B pool, not of sections */
}

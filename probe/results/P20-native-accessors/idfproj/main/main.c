/* P01: the HP-core side is a placeholder. This probe only builds the ULP image and measures it,
 * it never flashes and never starts the ULP.
 * GUARDRAIL: keep the HP side trivial — anything real here inflates the app build and tempts a
 * flash, and the measurement lives entirely in the ULP image (host-only probe). */
#include <stdio.h>

void app_main(void)
{
    printf("P01: measurement only, see probe/results/P01-engine-size/RESULT.md\n");
}

/* expand.c — host test filter: turn a captured ULP output stream (codes and all) into the operator's
 * transcript, using the SAME mapping the bridge uses (src/msg_expand.h).
 *
 *   ./out/host_coded prelude.fs suite.fs | ./out/expand > coded.txt
 *
 * GUARDRAIL: this is a test tool, not a second implementation — it includes msg_expand.h rather than
 * re-deriving the table, because a filter with its own copy would prove the copy is consistent and say
 * nothing about what the operator actually receives (R9).
 */
#include <stdio.h>
#include <stdint.h>
#include "../src/msg_expand.h"

int main(void)
{
    int c;
    char scratch[MSG_OUT_TEXT];
    const char *t;

    while ((c = getchar()) != EOF) {
        size_t n = msg_byte_text((uint8_t)c, scratch, sizeof scratch, &t);
        fwrite(t, 1, n, stdout);
    }
    return 0;
}

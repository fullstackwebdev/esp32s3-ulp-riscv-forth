/* What the ULP's ISA actually gives us: one instruction or a library call?
 * Compiled with the exact flags IDF uses for ULP sources (see the ULP sub-build's compile_commands.json):
 *   -Os -march=rv32imc_zicsr_zifencei -mdiv -ffunction-sections -fdata-sections
 * GUARDRAIL: this file exists to be disassembled, never executed. A Forth primitive's cost is decided here,
 * not by reading the ISA spec: a multiply that becomes `call __mulsi3` costs ~20 cycles and a stack frame.
 */
int m_mul(int a, int b) { return a * b; }
int m_div(int a, int b) { return a / b; }
int m_mod(int a, int b) { return a % b; }
int m_shl(int a, int b) { return a << b; }
int m_sar(int a, int b) { return a >> b; }

unsigned char mem8[256];
void m_ld8(int i) { mem8[i] = (unsigned char)(mem8[i] + 1); }
void m_ld32(int *p, int v) { *p = v; }
int  m_ld32r(int *p) { return *p; }

/* a switch with a dense range: does the ULP get a jump table, or a compare chain? */
int m_switch(int x) {
    switch (x) {
    case 0: return 11; case 1: return 22; case 2: return 33; case 3: return 44;
    case 4: return 55; case 5: return 66; case 6: return 77; case 7: return 88;
    default: return 0;
    }
}

/* the shape of a token dispatch: an indexed call through a table */
typedef void (*fn)(void);
extern fn table[];
void m_dispatch(int i) { table[i](); }

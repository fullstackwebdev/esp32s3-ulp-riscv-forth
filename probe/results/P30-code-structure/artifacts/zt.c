#include <stdint.h>
typedef uint32_t u32;
#define SD 16
struct VM { u32 DS[SD]; u32 RS[SD]; u32 SP, RSP; uint16_t W, IP; };
struct TSK { struct VM vm; uint16_t entry; uint8_t state; };
extern struct TSK tsk[3];
/* a: plain double loop (P29's form) */
void zero_a(int k){ int j; for (j=0;j<SD;j++){ tsk[k].vm.DS[j]=0; tsk[k].vm.RS[j]=0; } }
/* b: one pointer loop over the whole record, noinline */
__attribute__((noinline)) static void wz(u32 *p, int n){ while(n--) *p++ = 0u; }
void zero_b(int k){ wz((u32*)&tsk[k].vm, sizeof tsk[k].vm/4); }
/* c: pointer loop unrolled by hand, 4 words per iteration */
void zero_c(int k){ u32 *p=(u32*)&tsk[k].vm; int n=(int)(sizeof tsk[k].vm/4); while(n>0){ p[0]=p[1]=p[2]=p[3]=0u; p+=4; n-=4; } }

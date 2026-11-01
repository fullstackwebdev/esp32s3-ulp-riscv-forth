/* flash_store.h — the block store, on a raw esp_partition instead of HP .bss. See docs/22-flash-store.md.
 *
 * GUARDRAIL: every call returns a NEGATIVE named reason on failure and callers must surface it. A store that silently
 * reads zeros looks exactly like an empty one, and an "empty" store makes every phase look missing - the failure class
 * this project keeps finding.
 */
#ifndef FLASH_STORE_H
#define FLASH_STORE_H

#include <stdint.h>
#include <stddef.h>

enum {
    FS_OK = 0,
    FS_E_NO_PARTITION = -1,
    FS_E_BAD_MAGIC    = -2,
    FS_E_BAD_VERSION  = -3,
    FS_E_BAD_GEOMETRY = -4,
    FS_E_BAD_CRC      = -5,
    FS_E_RANGE        = -6,
    FS_E_IO           = -7,
    FS_E_FLUSH        = -8,
};

int      fs_init(void);
int      fs_format(void);
int      fs_read(uint32_t blk, uint8_t *dst);
int      fs_write(uint32_t blk, const uint8_t *src);
int      fs_flush(void);
uint32_t fs_block_count(void);
uint32_t fs_block_size(void);
void     fs_stats(uint32_t *bytes_programmed, uint32_t *sectors_erased, uint32_t *flushes);
const char *fs_strerror(int code);
/* GUARDRAIL: wear is a MEASUREMENT, not an estimate. Per-sector erase counters cost 2 B each in HP .bss (16 sectors =
 * 32 B) and 0 ULP bytes, and they are the only honest way to answer "how long does this sector last". A single total
 * counter would hide a hot sector, which is the failure mode that actually kills a device. */
uint32_t fs_bc(void);              /* last flash step entered; a hang shows the step it never left */
uint32_t fs_bc_prev(void);         /* same, from RTC_NOINIT: survives the reset a hang needs to escape */
uint32_t fs_us(int which);         /* 0 erase, 1 write, 2 superblock */
uint32_t fs_sector_count(void);
uint32_t fs_sector_erases(uint32_t sec);

#endif

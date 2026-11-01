/* flash_store.c — 128-byte blocks on a raw partition, with a one-sector write-back cache.
 *
 * GUARDRAIL: NOR geometry forces the design. A sector is 4 KB and bits only go 1->0 without an erase, so a 128 B block
 * write is a read-modify-write of the whole sector. Writing per block (erase+program per BLOCK SAVE) would cost ~4 KB of
 * erase for 128 B of data and wear the sector out; instead one sector is cached and the erase happens once per flush.
 * GUARDRAIL: reads must consult the cache. A dirty sector means the flash copy is STALE, so a block in it read straight
 * from flash returns the previous contents - a silent wrong answer, measured as "write two blocks in one sector, read the
 * first, get its old value".
 */
#include "flash_store.h"
#include <string.h>
#include "esp_partition.h"
#include "esp_log.h"
#include "esp_timer.h"

#define FS_SECTOR        4096u
#define FS_BLOCK         128u
#define FS_PER_SECTOR    (FS_SECTOR / FS_BLOCK)      /* 32 */
#define FS_MAGIC         0x314B4C42u                 /* "BLK1" little-endian */
#define FS_VERSION       1u

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t block_size;
    uint32_t block_count;
    uint32_t generation;
    uint32_t crc;                                    /* over the five fields above */
} fs_super_t;

static const char *TAG = "flash_store";
static const esp_partition_t *s_part;
static fs_super_t s_super;
static int s_state = FS_E_NO_PARTITION;              /* FS_OK once validated */
static uint8_t s_cache[FS_SECTOR];
static uint32_t s_cache_sector = 0xFFFFFFFFu;        /* none */
static int s_cache_dirty;
static fs_super_t s_pending_super;
static uint8_t s_super_dirty;
static uint32_t s_bytes, s_erases, s_flushes;
#define FS_MAX_SECTORS 16u
static uint16_t s_erase_psec[FS_MAX_SECTORS];
/* GUARDRAIL: a silent hang is not diagnosable from outside, so each flash call records a breadcrumb and its duration.
 * "No reply for 15 s" is consistent with a deadlock, a starved task and a never-returning call alike; the breadcrumb is
 * the only thing that separates them, and it costs 6 words of HP .bss and 0 ULP bytes. */
static volatile uint32_t s_bc;
static volatile uint32_t s_us[3];   /* 0 erase, 1 write, 2 superblock erase+write */
static uint32_t s_nsectors;

static void note_erase(uint32_t sec)
{
    s_erases++;
    if (sec < FS_MAX_SECTORS) s_erase_psec[sec]++;
}

static uint32_t crc32_bytes(const void *p, size_t n)
{
    const uint8_t *b = (const uint8_t *)p;
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; i++) {
        c ^= b[i];
        for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
    }
    return ~c;
}

static uint32_t super_crc(const fs_super_t *s)
{
    return crc32_bytes(s, offsetof(fs_super_t, crc));
}

const char *fs_strerror(int code)
{
    switch (code) {
    case FS_OK:              return "ok";
    case FS_E_NO_PARTITION:  return "no 'blocks' partition (partition table not flashed?)";
    case FS_E_BAD_MAGIC:     return "superblock magic is not BLK1 (store never formatted - run #x)";
    case FS_E_BAD_VERSION:   return "superblock version mismatch";
    case FS_E_BAD_GEOMETRY:  return "superblock geometry does not match this build";
    case FS_E_BAD_CRC:       return "superblock CRC mismatch (torn write or corruption)";
    case FS_E_RANGE:         return "block out of range";
    case FS_E_IO:            return "partition read/write failed";
    case FS_E_FLUSH:         return "flush failed";
    default:                 return "unknown";
    }
}

int fs_init(void)
{
    s_part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, (esp_partition_subtype_t)0x40, "blocks");
    if (!s_part) { s_state = FS_E_NO_PARTITION; return s_state; }
    if (s_part->size < FS_SECTOR + FS_BLOCK) { s_state = FS_E_BAD_GEOMETRY; return s_state; }
    if (esp_partition_read(s_part, 0, &s_super, sizeof s_super) != ESP_OK) {
        s_state = FS_E_IO; return s_state;
    }
    /* GUARDRAIL: FS_SKIP_VALIDATE exists ONLY to show what a store without a boot check does, i.e. to make gate 3's
     * refusal demonstrably able to fail. It must never ship: with it defined a damaged superblock is accepted and every
     * block is served from garbage, which looks like a working store full of nonsense. */
#if defined(FS_SKIP_VALIDATE)
    s_state = FS_OK; return FS_OK;
#endif
    if (s_super.magic != FS_MAGIC)        { s_state = FS_E_BAD_MAGIC;    return s_state; }
    if (s_super.version != FS_VERSION)    { s_state = FS_E_BAD_VERSION;  return s_state; }
    if (s_super.crc != super_crc(&s_super)) { s_state = FS_E_BAD_CRC;    return s_state; }
    uint32_t max_blocks = (s_part->size - FS_SECTOR) / FS_BLOCK;
    if (s_super.block_size != FS_BLOCK || s_super.block_count == 0 || s_super.block_count > max_blocks) {
        s_state = FS_E_BAD_GEOMETRY; return s_state;
    }
    s_nsectors = s_part->size / FS_SECTOR;
    if (s_nsectors > FS_MAX_SECTORS) s_nsectors = FS_MAX_SECTORS;
    s_state = FS_OK;
    return FS_OK;
}

uint32_t fs_bc(void)      { return s_bc; }
uint32_t fs_us(int which) { return (which >= 0 && which < 3) ? s_us[which] : 0u; }
uint32_t fs_sector_count(void)        { return s_nsectors; }
uint32_t fs_sector_erases(uint32_t s) { return s < FS_MAX_SECTORS ? s_erase_psec[s] : 0u; }

int fs_format(void)
{
    if (!s_part) return FS_E_NO_PARTITION;
    if (fs_flush() != FS_OK) return FS_E_FLUSH;
    if (esp_partition_erase_range(s_part, 0, s_part->size) != ESP_OK) return FS_E_IO;
    for (uint32_t k = 0; k < FS_MAX_SECTORS; k++) note_erase(k);
    fs_super_t s = { FS_MAGIC, FS_VERSION, FS_BLOCK, (s_part->size - FS_SECTOR) / FS_BLOCK, 1u, 0u };
    s.crc = super_crc(&s);
    if (esp_partition_write(s_part, 0, &s, sizeof s) != ESP_OK) return FS_E_IO;
    s_bytes += sizeof s;
    s_super = s; s_cache_sector = 0xFFFFFFFFu; s_cache_dirty = 0;
    s_state = FS_OK;
    return FS_OK;
}

uint32_t fs_block_count(void) { return s_state == FS_OK ? s_super.block_count : 0u; }
uint32_t fs_block_size(void)  { return FS_BLOCK; }

void fs_stats(uint32_t *bp, uint32_t *se, uint32_t *fl)
{
    if (bp) *bp = s_bytes;
    if (se) *se = s_erases;
    if (fl) *fl = s_flushes;
}

static uint32_t sector_of(uint32_t blk) { return 1u + blk / FS_PER_SECTOR; }

static int load_sector(uint32_t sec)
{
    if (s_cache_sector == sec) return FS_OK;
    if (fs_flush() != FS_OK) return FS_E_FLUSH;
    if (esp_partition_read(s_part,
                           (size_t)sec * FS_SECTOR,
                           s_cache, FS_SECTOR) != ESP_OK) return FS_E_IO;
    s_cache_sector = sec;
    s_cache_dirty = 0;
    return FS_OK;
}

int fs_flush(void)
{
    if (!s_part) return FS_E_NO_PARTITION;
    int64_t t0;
    if (s_cache_dirty && s_cache_sector != 0xFFFFFFFFu) {
        /* GUARDRAIL: erase THEN program, in that order, and count the erase: the whole reason this cache exists is that
         * one erase per sector must cover up to 32 block writes. */
        s_bc = 1; t0 = esp_timer_get_time();
        if (esp_partition_erase_range(s_part, (size_t)s_cache_sector * FS_SECTOR, FS_SECTOR) != ESP_OK)
            return FS_E_FLUSH;
        s_us[0] = (uint32_t)(esp_timer_get_time() - t0); s_bc = 2;
        note_erase(s_cache_sector);
        t0 = esp_timer_get_time();
        if (esp_partition_write(s_part, (size_t)s_cache_sector * FS_SECTOR, s_cache, FS_SECTOR) != ESP_OK)
            return FS_E_FLUSH;
        s_us[1] = (uint32_t)(esp_timer_get_time() - t0); s_bc = 3;
        s_bytes += FS_SECTOR;
        s_cache_dirty = 0;
        s_flushes++;
    }
    if (s_cache_dirty == 0 && s_super_dirty == 0 && s_cache_sector != 0xFFFFFFFFu) { /* nothing to do */ }
    if (s_super_dirty) {
        s_bc = 4; t0 = esp_timer_get_time();
        if (esp_partition_erase_range(s_part, 0, FS_SECTOR) != ESP_OK) return FS_E_FLUSH;
        note_erase(0);
        if (esp_partition_write(s_part, 0, &s_pending_super, sizeof s_pending_super) != ESP_OK) return FS_E_FLUSH;
        s_us[2] = (uint32_t)(esp_timer_get_time() - t0); s_bc = 5;
        s_bytes += sizeof s_pending_super;
        s_super = s_pending_super;
        s_super_dirty = 0;
        s_flushes++;
    }
    return FS_OK;
}

int fs_read(uint32_t blk, uint8_t *dst)
{
    if (s_state != FS_OK) return s_state;
    if (blk >= s_super.block_count) return FS_E_RANGE;
    uint32_t sec = sector_of(blk);
    if (s_cache_sector == sec && s_cache_dirty) {          /* the flash copy is stale: serve from the cache */
        memcpy(dst, s_cache + (blk % FS_PER_SECTOR) * FS_BLOCK, FS_BLOCK);
        return FS_OK;
    }
    if (esp_partition_read(s_part, (size_t)sec * FS_SECTOR + (blk % FS_PER_SECTOR) * FS_BLOCK,
                           dst, FS_BLOCK) != ESP_OK) return FS_E_IO;
    return FS_OK;
}

int fs_write(uint32_t blk, const uint8_t *src)
{
    if (s_state != FS_OK) return s_state;
    if (blk >= s_super.block_count) return FS_E_RANGE;
    int r = load_sector(sector_of(blk));
    if (r != FS_OK) return r;
    memcpy(s_cache + (blk % FS_PER_SECTOR) * FS_BLOCK, src, FS_BLOCK);
    s_cache_dirty = 1;
    s_bc = 6;
    /* GUARDRAIL: do NOT touch the superblock here. Bumping its generation on every block write made every flush erase
     * sector 0 in addition to the data sector - double the wear for one commit - and it rewrote a CRC'd header for a
     * generation number that only needs to advance once per flush. */
    return FS_OK;
}

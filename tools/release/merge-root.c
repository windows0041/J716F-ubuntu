/* First-install GPT merge for TB-J716F 128GB, before mounting the real root.
 * Only entry 17 and entry 18's start LBA, plus GPT CRCs, may change.
 * --fixture is strictly read-only and accepts regular image files only.
 * Production write mode always uses /dev/sda and enforces the board guard.
 */
#define _GNU_SOURCE
#define _FILE_OFFSET_BITS 64
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <inttypes.h>
#include <linux/fs.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#ifndef ROOTFS_UUID_HEX
#error ROOTFS_UUID_HEX must identify the clean release filesystem
#endif
#define SECTOR 4096U
#define DISK_BYTES UINT64_C(125720068096)
#define SUPER_FIRST UINT64_C(217896)
#define OLD_FIRST UINT64_C(2315048)
#define ROOT_LAST UINT64_C(30693370)
#define ARRAY_BYTES 4096U
#define PRIMARY_BYTES 12288U
#define SECONDARY_BYTES 20480U
#define SECONDARY_OFFSET (DISK_BYTES - SECONDARY_BYTES)

struct region {
    unsigned char old[SECONDARY_BYTES], next[SECONDARY_BYTES];
    size_t size, header, array;
    uint64_t offset;
    const char *name;
};
static struct region regions[2] = {
    {.size = PRIMARY_BYTES, .header = SECTOR, .array = 2 * SECTOR,
     .offset = 0, .name = "sda.primary.bin"},
    {.size = SECONDARY_BYTES, .header = 4 * SECTOR, .array = 0,
     .offset = SECONDARY_OFFSET, .name = "sda.secondary.bin"}
};

static void need(int ok, const char *why) {
    if (!ok) { fprintf(stderr, "GPT merge STOP: %s (errno=%d)\n", why, errno); exit(1); }
}
static uint32_t get32(const void *ptr) {
    const unsigned char *p = ptr;
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t get64(const void *p) { return get32(p) | (uint64_t)get32((const char *)p + 4) << 32; }
static void put32(void *ptr, uint32_t v) {
    unsigned char *p = ptr;
    for (unsigned i = 0; i < 4; i++) p[i] = v >> (8 * i);
}
static void put64(void *p, uint64_t v) { put32(p, v); put32((char *)p + 4, v >> 32); }
static uint32_t crc32(const void *ptr, size_t n) {
    const unsigned char *p = ptr;
    uint32_t crc = ~0U;
    while (n--) {
        crc ^= *p++;
        for (unsigned j = 0; j < 8; j++) crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1)));
    }
    return ~crc;
}
static int zero(const void *ptr, size_t n) {
    const unsigned char *p = ptr;
    while (n--) if (*p++) return 0;
    return 1;
}
static int named(const unsigned char *p, const char *name) {
    p += 56;
    for (size_t i = 0; i < 36; i++) {
        unsigned c = i < strlen(name) ? (unsigned char)name[i] : 0;
        if (p[2 * i] != c || p[2 * i + 1]) return 0;
    }
    return 1;
}
static void read_at(int fd, void *buffer, size_t n, uint64_t offset) {
    unsigned char *p = buffer;
    while (n) {
        ssize_t done = pread(fd, p, n, offset);
        if (done < 0 && errno == EINTR) continue;
        need(done > 0, "short read");
        n -= done; p += done; offset += done;
    }
}
static int write_at(int fd, const void *buffer, size_t n, uint64_t offset) {
    const unsigned char *p = buffer;
    while (n) {
        ssize_t done = pwrite(fd, p, n, offset);
        if (done < 0 && errno == EINTR) continue;
        if (done <= 0) return 0;
        n -= done; p += done; offset += done;
    }
    return fsync(fd) == 0;
}
static void board_guard(void) {
    unsigned char b[4096];
    int fd = open("/proc/device-tree/compatible", O_RDONLY | O_CLOEXEC);
    need(fd >= 0, "missing device-tree board identity");
    ssize_t n = read(fd, b, sizeof(b)); close(fd);
    int found = 0;
    for (ssize_t i = 0; i + 12 < n; i++)
        if ((!i || !b[i - 1]) && !memcmp(b + i, "lenovo,j716f", 12) && !b[i + 12]) found = 1;
    need(found, "board must be lenovo,j716f");
}
static void unmounted_guard(void) {
    FILE *f = fopen("/proc/self/mountinfo", "r");
    need(f != NULL, "cannot inspect mounts");
    char line[4096];
    unsigned a, b;
    dev_t devices[64]; size_t count = 0;
    glob_t paths;
    need(glob("/sys/class/block/sda*/dev", 0, NULL, &paths) == 0 && paths.gl_pathc < 64,
         "cannot enumerate target disk devices");
    for (size_t i = 0; i < paths.gl_pathc; i++) {
        FILE *d = fopen(paths.gl_pathv[i], "r");
        need(d != NULL && fscanf(d, "%u:%u", &a, &b) == 2, "cannot read target device number");
        fclose(d); devices[count++] = makedev(a, b);
    }
    globfree(&paths);
    while (fgets(line, sizeof(line), f)) {
        need(sscanf(line, "%*u %*u %u:%u", &a, &b) == 2, "malformed mount info");
        for (size_t i = 0; i < count; i++)
            need(makedev(a, b) != devices[i], "a target LUN partition is mounted");
    }
    need(!ferror(f), "mountinfo read failed"); fclose(f);
    f = fopen("/proc/swaps", "r"); need(f != NULL, "cannot inspect swap");
    need(fgets(line, sizeof(line), f) != NULL, "missing swap header");
    need(fgets(line, sizeof(line), f) == NULL && !ferror(f), "swap is active"); fclose(f);
}
static void validate_header(struct region *r, unsigned index) {
    unsigned char h[92];
    memcpy(h, r->old + r->header, sizeof(h));
    uint32_t expected = get32(h + 16); put32(h + 16, 0);
    need(!memcmp(h, "EFI PART", 8) && get32(h + 8) == 0x10000 && get32(h + 12) == 92 &&
         crc32(h, sizeof(h)) == expected && get32(h + 20) == 0, "GPT header / CRC mismatch");
    uint64_t last = DISK_BYTES / SECTOR - 1;
    need(get64(h + 24) == (index ? last : 1) && get64(h + 32) == (index ? 1 : last) &&
         get64(h + 40) == 6 && get64(h + 48) == ROOT_LAST, "unexpected GPT header geometry");
    need(get64(h + 72) == (r->offset + r->array) / SECTOR && get32(h + 80) == 32 &&
         get32(h + 84) == 128 && get32(h + 88) == crc32(r->old + r->array, ARRAY_BYTES),
         "GPT entry array geometry / CRC mismatch");
}
/* Returns 10 for the original layout, 0 when already merged. */
static int plan(int fd) {
    for (unsigned i = 0; i < 2; i++) {
        read_at(fd, regions[i].old, regions[i].size, regions[i].offset);
        validate_header(&regions[i], i);
    }
    unsigned char *entries = regions[0].old + regions[0].array;
    need(!memcmp(entries, regions[1].old + regions[1].array, ARRAY_BYTES), "GPT arrays disagree");
    need(!memcmp(regions[0].old + regions[0].header + 56,
                 regions[1].old + regions[1].header + 56, 16), "GPT disk GUIDs disagree");
    unsigned char *sp = entries + 16 * 128, *root = entries + 17 * 128;
    need(named(root, "userdata") && !zero(root, 16) && !zero(root + 16, 16) &&
         get64(root + 40) == ROOT_LAST, "unexpected userdata entry");
    int merged = get64(root + 32) == SUPER_FIRST;
    need(merged ? zero(sp, 128) :
         (named(sp, "super") && !zero(sp, 16) && !zero(sp + 16, 16) &&
          get64(sp + 32) == SUPER_FIRST && get64(sp + 40) == OLD_FIRST - 1 &&
          get64(root + 32) == OLD_FIRST), "not an approved stock or merged layout");
    for (unsigned i = 0; i < 32; i++) {
        unsigned char *e = entries + 128 * i;
        if (zero(e, 128)) continue;
        uint64_t start = get64(e + 32), end = get64(e + 40);
        need(!zero(e, 16) && start >= 6 && start <= end && end <= ROOT_LAST, "invalid GPT entry");
        if (i != 16 && i != 17) need(end < SUPER_FIRST, "another partition occupies merge range");
        for (unsigned j = i + 1; j < 32; j++) {
            unsigned char *other = entries + 128 * j;
            if (!zero(other, 128))
                need(end < get64(other + 32) || start > get64(other + 40), "partitions overlap");
        }
    }
    if (merged) { puts("GPT: userdata already merged (124827545600 bytes)"); return 0; }
    /* Only a freshly flashed, unmounted clean release may be used as source. */
    unsigned char sb[1024];
    read_at(fd, sb, sizeof(sb), SUPER_FIRST * SECTOR + 1024);
    char hex[33];
    for (unsigned i = 0; i < 16; i++) snprintf(hex + 2 * i, 3, "%02x", sb[104 + i]);
    need(sb[56] == 0x53 && sb[57] == 0xef && get32(sb + 24) == 2 &&
         get32(sb + 4) == 2097152 && get32(sb + 336) == 0 &&
         !memcmp(sb + 120, "j716f-ubuntu\0\0\0\0\0", 16) && !strcmp(hex, ROOTFS_UUID_HEX),
         "super does not contain this release's 8 GiB ext4 filesystem");
    need((sb[58] & 1) && !(get32(sb + 96) & 4), "source ext4 is not cleanly unmounted");
    for (unsigned i = 0; i < 2; i++) {
        struct region *r = &regions[i];
        memcpy(r->next, r->old, r->size);
        unsigned char *array = r->next + r->array, *header = r->next + r->header;
        memset(array + 16 * 128, 0, 128);
        put64(array + 17 * 128 + 32, SUPER_FIRST);
        put32(header + 88, crc32(array, ARRAY_BYTES));
        put32(header + 16, 0); put32(header + 16, crc32(header, 92));
        for (size_t j = 0; j < r->size; j++) {
            int allowed = (j >= r->array + 16 * 128 && j < r->array + 17 * 128) ||
                          (j >= r->array + 17 * 128 + 32 && j < r->array + 17 * 128 + 40) ||
                          (j >= r->header + 16 && j < r->header + 20) ||
                          (j >= r->header + 88 && j < r->header + 92);
            need(r->old[j] == r->next[j] || allowed, "candidate changed unrelated bytes");
        }
    }
    puts("GPT: original super + userdata; narrowly scoped merge prepared"); return 10;
}
static void save_file(const char *dir, const char *name, const void *data, size_t len) {
    char path[4096];
    need(snprintf(path, sizeof(path), "%s/%s", dir, name) < (int)sizeof(path), "backup path too long");
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    need(fd >= 0, "cannot create exclusive backup file");
    need(write_at(fd, data, len, 0), "backup write failed"); close(fd);
}
static void save_plan(const char *dir) {
    need(mkdir(dir, 0700) == 0, "backup directory must be new");
    for (unsigned i = 0; i < 2; i++) {
        save_file(dir, regions[i].name, regions[i].old, regions[i].size);
        char name[80]; snprintf(name, sizeof(name), "%s.after", regions[i].name);
        save_file(dir, name, regions[i].next, regions[i].size);
    }
    const char receipt[] = "{\n  \"disk\":\"/dev/sda\",\n  \"sector_bytes\":4096,\n"
        "  \"disk_bytes\":125720068096,\n  \"primary_offset\":0,\n"
        "  \"secondary_offset\":125720047616,\n  \"old_userdata_start_lba\":2315048,\n"
        "  \"new_userdata_start_lba\":217896,\n  \"userdata_last_lba\":30693370,\n"
        "  \"merged_userdata_bytes\":124827545600,\n  \"rootfs_uuid_hex\":\"" ROOTFS_UUID_HEX "\"\n}\n";
    save_file(dir, "plan.json", receipt, sizeof(receipt) - 1);
    int d = open(dir, O_RDONLY | O_DIRECTORY); need(d >= 0 && fsync(d) == 0, "backup directory fsync failed"); close(d);
}
static void compare_backups(const char *dir) {
    unsigned char buffer[SECONDARY_BYTES]; char path[4096]; struct stat st;
    for (unsigned i = 0; i < 2; i++) {
        struct region *r = &regions[i];
        need(snprintf(path, sizeof(path), "%s/%s", dir, r->name) < (int)sizeof(path), "backup path too long");
        int fd = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
        need(fd >= 0 && fstat(fd, &st) == 0 && S_ISREG(st.st_mode) && st.st_size == (off_t)r->size,
             "missing or invalid pre-merge backup");
        read_at(fd, buffer, r->size, 0); close(fd);
        need(!memcmp(buffer, r->old, r->size), "GPT changed after backup");
    }
}
static int commit(int fd, int next) {
    unsigned char check[SECONDARY_BYTES];
    for (int i = 1; i >= 0; i--) {
        struct region *r = &regions[i];
        const unsigned char *wanted = next ? r->next : r->old;
        if (!write_at(fd, wanted, r->size, r->offset)) return 0;
        ssize_t n = pread(fd, check, r->size, r->offset);
        if (n != (ssize_t)r->size || memcmp(check, wanted, r->size)) return 0;
    }
    return 1;
}
int main(int argc, char **argv) {
    int fixture = argc == 4 && !strcmp(argv[1], "--fixture");
    int status = argc == 2 && !strcmp(argv[1], "--status");
    int save = argc == 3 && !strcmp(argv[1], "--save");
    int apply = argc == 3 && !strcmp(argv[1], "--apply");
    need(fixture || status || save || apply, "usage: --status | --save DIR | --apply DIR | --fixture FILE OUTDIR");
    umask(0077);
    /* Previous bulk I/O stalls were observed on CPU 5; metadata is only 32 KiB. */
    cpu_set_t affinity;
    if (!sched_getaffinity(0, sizeof(affinity), &affinity)) {
        CPU_CLR(5, &affinity); (void)sched_setaffinity(0, sizeof(affinity), &affinity);
    }
    if (!fixture) { board_guard(); unmounted_guard(); }
    int fd = open(fixture ? argv[2] : "/dev/sda", (apply ? O_RDWR : O_RDONLY) | O_CLOEXEC | O_NOFOLLOW);
    struct stat st; need(fd >= 0 && fstat(fd, &st) == 0, "open target failed");
    if (fixture) need(S_ISREG(st.st_mode) && st.st_size == (off_t)DISK_BYTES, "fixture must be a correctly sized regular file");
    else {
        uint64_t bytes = 0; unsigned sector = 0;
        need(S_ISBLK(st.st_mode) && ioctl(fd, BLKSSZGET, &sector) == 0 && sector == SECTOR &&
             ioctl(fd, BLKGETSIZE64, &bytes) == 0 && bytes == DISK_BYTES, "unexpected target disk capacity / sector size");
    }
    int result = plan(fd);
    if (!result) { close(fd); return 0; }
    if (save || fixture) { save_plan(fixture ? argv[3] : argv[2]); close(fd); return fixture ? 0 : 10; }
    if (apply) {
        compare_backups(argv[2]); unmounted_guard();
        if (!commit(fd, 1)) {
            int rolled_back = commit(fd, 0);
            fprintf(stderr, "GPT write/readback failed; rollback %s. Stay in rescue.\n", rolled_back ? "verified" : "FAILED");
            close(fd); return 1;
        }
        puts("GPT merge committed and read back. Reboot REQUIRED before mounting userdata.");
        close(fd); return 10;
    }
    close(fd); return result;
}

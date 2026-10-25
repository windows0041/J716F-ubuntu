// SPDX-License-Identifier: GPL-2.0-only
/*
 * J716F persistent sensor diagnostic and match client for the J716F stock Goodix QSEE application.
 *
 * TEE discovery, SHM, name-session and modified-command transport adapted from
 * wrobelda/goodix-fp-spi-linux, harness/gfharness.c, GPL-2.0-only:
 * https://github.com/wrobelda/goodix-fp-spi-linux/blob/
 * 5a07b0869dd072105e7bb13614afbb29da88d21d/harness/gfharness.c
 * The Lenovo sizes and offsets are derived from this tablet's stock HAL;
 * see lenovo-hal-analysis.md. This is not the gfenu protocol profile.
 *
 * Default: GET_DEV_INFO. --detect adds DETECT_SENSOR. --initialize additionally
 * owns power/reset/IRQ and sends the Lenovo INIT/INIT_FINISHED sequence.
 * Explicit test modes may enrol and match only within the wrapper-owned /run store.
 * The reference challenge-only token is experimental, never a signed-HAT claim.
 * No template deletion or image/template dump commands.
 * It does not load a TA or register TEE filesystem listeners.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <linux/tee.h>
#include <linux/netlink.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define QSEECOM_IMPL_ID 5U /* Out-of-tree QSEECOM TEE ABI, not qcomtee. */
#define INFO_CMD 1089U
#define INFO_LEN 5496U
#define DETECT_CMD 1000U
#define DETECT_LEN 512U
#define BODY_OFFSET 96U
#define REQ_LEN 128U
#define RSP_LEN 64U
#define INIT_CMD 1001U
#define INIT_LEN 344U
#define FINISH_CMD 1005U
#define FINISH_LEN 100U
#define IRQ_CMD 1016U
#define IRQ_LEN 327584U /* Lenovo Milan handler 0x5ae54, not gfenu 327624. */
#define IRQ_MODE 0x4fd65U
#define IRQ_SIZE 0x4fd94U
#define IRQ_ARM 0x4ff9cU
#define NAV_CMD 1071U
#define CANCEL_CMD 1009U
#define NAV_LEN 100U
#define PRE_CMD 1006U
#define ENROLL_CMD 1007U
#define AUTH_CMD 1010U
#define SAVE_CMD 1012U
#define GROUP_CMD 1014U
#define ENUM_CMD 1015U
#define AUTH_FINISH_CMD 1086U
#define MAX_SHM (1024U * 1024U)

static uint32_t last_status;

struct shm {
	int fd;
	int id;
	uint8_t *map;
	size_t size;
};

static void put32(uint8_t *p, uint32_t v)
{
	for (unsigned i = 0; i < 4; ++i)
		p[i] = (uint8_t)(v >> (8 * i));
}

static uint32_t get32(const uint8_t *p)
{
	return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
	       (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void free_shm(struct shm *m)
{
	if (m->map && m->map != MAP_FAILED)
		munmap(m->map, m->size);
	if (m->fd >= 0)
		close(m->fd);
	*m = (struct shm){ .fd = -1, .id = -1 };
}

static int alloc_shm(int fd, size_t size, struct shm *m)
{
	struct tee_ioctl_shm_alloc_data a = { .size = size };
	if (!size || size > MAX_SHM) {
		fprintf(stderr, "invalid SHM request: %zu\n", size);
		return -1;
	}
	m->fd = ioctl(fd, TEE_IOC_SHM_ALLOC, &a);
	if (m->fd < 0) {
		perror("TEE_IOC_SHM_ALLOC");
		return -1;
	}
	if (a.id < 0 || a.size < size || a.size > MAX_SHM || a.size > SIZE_MAX) {
		fprintf(stderr, "invalid returned SHM id/size\n");
		free_shm(m);
		return -1;
	}
	m->size = (size_t)a.size;
	m->id = a.id;
	m->map = mmap(NULL, m->size, PROT_READ | PROT_WRITE, MAP_SHARED, m->fd, 0);
	if (m->map == MAP_FAILED) {
		perror("mmap SHM");
		free_shm(m);
		return -1;
	}
	memset(m->map, 0, m->size);
	return 0;
}

static int try_client(const char *path)
{
	struct tee_ioctl_version_data v = {0};
	int fd = open(path, O_RDWR | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (ioctl(fd, TEE_IOC_VERSION, &v) || v.impl_id != QSEECOM_IMPL_ID) {
		close(fd);
		return -1;
	}
	printf("TEE %s: impl_id=%u impl_caps=0x%x gen_caps=0x%x\n",
	       path, v.impl_id, v.impl_caps, v.gen_caps);
	return fd;
}

static int find_client(const char *explicit_path)
{
	if (explicit_path) {
		int fd = try_client(explicit_path);
		if (fd < 0)
			fprintf(stderr, "%s is not an accessible QSEECOM impl_id=5 TEE\n",
				explicit_path);
		return fd;
	}
	for (unsigned i = 0; i < 32; ++i) {
		char path[32];
		snprintf(path, sizeof(path), "/dev/tee%u", i);
		int fd = try_client(path);
		if (fd >= 0)
			return fd;
	}
	fprintf(stderr, "No accessible QSEECOM TEE (impl_id=5).\n");
	return -1;
}

static int open_session(int fd, uint32_t *session)
{
	struct {
		struct tee_ioctl_open_session_arg arg;
		struct tee_ioctl_param p[1];
	} b = {0};
	struct shm name = { .fd = -1, .id = -1 };
	int result = -1;
	if (alloc_shm(fd, 64, &name))
		return -1;
	memcpy(name.map, "goodixfp", sizeof("goodixfp"));
	b.arg.num_params = 1;
	b.arg.ret = UINT32_MAX;
	b.p[0].attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INPUT;
	b.p[0].b = sizeof("goodixfp");
	b.p[0].c = (uint32_t)name.id;
	struct tee_ioctl_buf_data bd = { .buf_ptr = (uintptr_t)&b, .buf_len = sizeof(b) };
	if (ioctl(fd, TEE_IOC_OPEN_SESSION, &bd)) {
		perror("OPEN_SESSION goodixfp (TA must already be loaded)");
	} else {
		printf("OPEN_SESSION goodixfp: ret=0x%08x origin=0x%08x session=%u\n",
		       b.arg.ret, b.arg.ret_origin, b.arg.session);
		if (b.arg.ret == 0) {
			*session = b.arg.session;
			result = 0;
		}
	}
	free_shm(&name);
	return result;
}

static int timestamp_ms(uint64_t *out)
{
	struct timespec ts;
	struct tm tm;
	if (clock_gettime(CLOCK_REALTIME, &ts) || !localtime_r(&ts.tv_sec, &tm)) {
		perror("local timestamp");
		return -1;
	}
	*out = ((uint64_t)tm.tm_hour * 3600 + tm.tm_min * 60 + tm.tm_sec) * 1000 +
	       (uint64_t)ts.tv_nsec / 1000000;
	return 0;
}

static void show_info(const uint8_t *p, size_t len)
{
	printf("Payload first 256 bytes (Lenovo body starts at +96):\n");
	for (size_t i = 0; i < len && i < 256; ++i) {
		if (!(i % 16)) printf("  %04zx:", i);
		printf(" %02x", p[i]);
		if (i % 16 == 15 || i + 1 == len) putchar('\n');
	}
	printf("Printable information strings (offsets are from payload start):\n");
	for (size_t i = BODY_OFFSET; i < len;) {
		size_t start = i;
		while (i < len && p[i] >= 32 && p[i] < 127) ++i;
		if (i - start >= 4)
			printf("  +%zu: %.*s\n", start, (int)(i - start), (const char *)p + start);
		if (i == start) ++i;
	}
}

static int command(int fd, uint32_t session, uint32_t cmd, uint8_t *returned, size_t capacity)
{
	/* This whitelist is the complete command surface of this executable. */
	size_t len;
	if (cmd == INFO_CMD) len = INFO_LEN;
	else if (cmd == DETECT_CMD) len = DETECT_LEN;
	else if (cmd == INIT_CMD) len = INIT_LEN;
	else if (cmd == FINISH_CMD) len = FINISH_LEN;
	else if (cmd == IRQ_CMD) len = IRQ_LEN;
	else if (cmd == CANCEL_CMD || cmd == GROUP_CMD) len = 100;
	else if (cmd == PRE_CMD) len = 104;
	else if (cmd == ENROLL_CMD) len = 176;
	else if (cmd == SAVE_CMD) len = 108;
	else if (cmd == ENUM_CMD) len = 180;
	else if (cmd == AUTH_CMD || cmd == AUTH_FINISH_CMD) len = 120;
	else return -1;
	struct {
		struct tee_ioctl_invoke_arg arg;
		struct tee_ioctl_param p[4];
	} b = {0};
	struct shm sb = { .fd = -1, .id = -1 }, pl = { .fd = -1, .id = -1 };
	uint64_t ms;
	static uint32_t token;
	int result = -1;
	if (timestamp_ms(&ms) || alloc_shm(fd, 4096, &sb) || alloc_shm(fd, len, &pl))
		goto out;
	/* One allocation contains request at +0, response at +128, as vendor CA. */
	put32(sb.map + 8, ++token);
	put32(sb.map + 12, 1); /* Normal command class; no factory/dump classes. */
	put32(sb.map + 16, (uint32_t)ms);
	put32(sb.map + 20, (uint32_t)(ms >> 32));
	put32(sb.map + 32, cmd);
	put32(sb.map + 36, (uint32_t)len);
	/* Vendor DETECT_SENSOR passes retry count at +504, initially four. */
	if (cmd == DETECT_CMD) pl.map[504] = 4;
	if (cmd == ENROLL_CMD || cmd == AUTH_CMD || cmd == SAVE_CMD || cmd == AUTH_FINISH_CMD) {
		if (!returned || capacity != len) goto out;
		memcpy(pl.map, returned, len);
	}
	if (cmd == IRQ_CMD) {
		if (!returned || capacity != IRQ_LEN) goto out;
		memcpy(pl.map, returned, len);
		/* Re-arm only the known control fields; retain the TA's drain state. */
		put32(pl.map + IRQ_MODE, 0x02000000);
		put32(pl.map + IRQ_SIZE, 512);
		put32(pl.map + IRQ_ARM, 1);
	}
	b.arg.func = 0;
	b.arg.session = session;
	b.arg.num_params = 4;
	b.arg.ret = UINT32_MAX;
	b.p[0] = (struct tee_ioctl_param){
		.attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INPUT,
		.b = REQ_LEN, .c = (uint32_t)sb.id };
	b.p[1] = (struct tee_ioctl_param){
		.attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_OUTPUT,
		.a = REQ_LEN, .b = RSP_LEN, .c = (uint32_t)sb.id };
	/* Kernel patches a four-byte physical payload address into request +0. */
	b.p[2] = (struct tee_ioctl_param){
		.attr = TEE_IOCTL_PARAM_ATTR_TYPE_VALUE_INPUT, .a = 0, .b = 4 };
	b.p[3] = (struct tee_ioctl_param){
		.attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INOUT,
		.b = len, .c = (uint32_t)pl.id };
	struct tee_ioctl_buf_data bd = { .buf_ptr = (uintptr_t)&b, .buf_len = sizeof(b) };
	printf("Invoking class=1 command=%u payload=%zu timestamp_ms=%" PRIu64 "\n", cmd, len, ms);
	fflush(stdout);
	if (ioctl(fd, TEE_IOC_INVOKE, &bd)) {
		perror("TEE_IOC_INVOKE");
		goto out;
	}
	printf("TEE ret=0x%08x origin=0x%08x response_size=%" PRIu64 " payload_size=%" PRIu64 "\n",
	       b.arg.ret, b.arg.ret_origin, (uint64_t)b.p[1].b, (uint64_t)b.p[3].b);
	if (b.arg.ret || b.p[1].a != REQ_LEN || b.p[1].b < 8 || b.p[1].b > RSP_LEN ||
	    b.p[3].a != 0 || b.p[3].b != len || b.p[1].c != (uint32_t)sb.id ||
	    b.p[3].c != (uint32_t)pl.id) {
		fprintf(stderr, "TEE call failed or returned unexpected buffer metadata.\n");
		goto out;
	}
	/* CA helper reads exception at +4, and returns status +0 via x4. */
	uint32_t status = get32(sb.map + REQ_LEN);
	uint32_t exception = get32(sb.map + REQ_LEN + 4);
	last_status = status;
	printf("Goodix status=%u exception=0x%08x\n", status, exception);
	if (exception || (status && cmd != IRQ_CMD)) goto out;
	bool body_changed = false;
	for (size_t i = BODY_OFFSET; i < len; ++i)
		if (pl.map[i] && !(cmd == DETECT_CMD && i == 504 && pl.map[i] == 4))
			body_changed = true;
	if ((cmd == INFO_CMD || cmd == DETECT_CMD) && !body_changed) {
		fprintf(stderr, "Zero/unchanged information body: result is inconclusive, not successful identification.\n");
		goto out;
	}
	if (cmd == INFO_CMD || cmd == DETECT_CMD) show_info(pl.map, len);
	if (cmd == INIT_CMD) {
		uint32_t width = get32(pl.map + 100), height = get32(pl.map + 104);
		printf("INIT geometry=%u x %u vendor=0x%02x\n", width, height, pl.map[124]);
		if (!width || !height || width > 4096 || height > 4096) {
			fprintf(stderr, "Unexpected INIT geometry; stopping.\n");
			goto out;
		}
	}
	if (cmd == FINISH_CMD)
		printf("INIT_FINISHED fields=%u,%u\n", (unsigned)pl.map[96] | (unsigned)pl.map[97] << 8,
		       (unsigned)pl.map[98] | (unsigned)pl.map[99] << 8);
	if (returned) {
		if (capacity < len) goto out;
		memcpy(returned, pl.map, len);
	}
	result = 0;
out:
	free_shm(&pl);
	free_shm(&sb);
	return result;
}


#define GF_POWER _IO('g', 7)
#define GF_RESET _IO('g', 2)
#define GF_FW_INFO _IOR('g', 11, uint8_t)
#define GF_INIT _IOR('g', 0, uint8_t)
#define GF_IRQ_ON _IO('g', 3)
#define GF_IRQ_OFF _IO('g', 4)
#define GF_CHIP_INFO _IOW('g', 13, uint8_t[8])

static volatile sig_atomic_t stopped;
static void stop_signal(int signo) { (void)signo; stopped = 1; }

static int sensor_open(void)
{
	int fd = open("/dev/goodix_fp", O_RDWR | O_CLOEXEC);
	if (fd < 0) { perror("sensor open"); return -1; }
	uint8_t fw = 0;
	if (ioctl(fd, GF_POWER) || ioctl(fd, GF_RESET) || ioctl(fd, GF_FW_INFO, &fw)) {
		perror("sensor power/reset/fw-info"); close(fd); return -1;
	}
	/* Original Lenovo driver leaves the caller's zero-initialised byte intact. */
	if (fw != 0) {
		fprintf(stderr, "Unexpected FW_INFO flag %u; unsupported profile.\n", fw);
		close(fd); return -1;
	}
	struct timespec settle = { .tv_nsec = 20000000 };
	while (nanosleep(&settle, &settle) && errno == EINTR && !stopped) {}
	return fd;
}

static int sensor_netlink(int sensor)
{
	uint8_t protocol = 0;
	if (ioctl(sensor, GF_INIT, &protocol)) { perror("GF_INIT"); return -1; }
	if (protocol != 25) { fprintf(stderr, "Unexpected netlink protocol %u\n", protocol); return -1; }
	int nl = socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC, protocol);
	if (nl < 0) { perror("netlink socket"); return -1; }
	struct sockaddr_nl local = { .nl_family = AF_NETLINK, .nl_pid = (uint32_t)getpid() };
	struct sockaddr_nl kernel = { .nl_family = AF_NETLINK };
	struct { struct nlmsghdr h; uint8_t body[16]; } hello = {0};
	hello.h.nlmsg_len = NLMSG_LENGTH(sizeof(hello.body));
	hello.h.nlmsg_pid = (uint32_t)getpid();
	if (bind(nl, (struct sockaddr *)&local, sizeof(local)) ||
	    sendto(nl, &hello, hello.h.nlmsg_len, 0, (struct sockaddr *)&kernel, sizeof(kernel)) != (ssize_t)hello.h.nlmsg_len) {
		perror("netlink registration"); close(nl); return -1;
	}
	return nl;
}


#define TEST_ROOT "/var/lib/j716f-fingerprint"
#define GROUP_OFF 0x4fcc0U
#define FINGER_OFF 0x4fcc4U
#define REMAIN_OFF 0x4fcc8U

static unsigned get16(const uint8_t *p) { return p[0] | (unsigned)p[1] << 8; }

static int require_isolated_wrapper(void)
{
	char cwd[4096]; struct stat st, marker;
	if (getuid() || !getcwd(cwd, sizeof(cwd)) || strcmp(cwd, TEST_ROOT) ||
	    lstat(TEST_ROOT, &st) || !S_ISDIR(st.st_mode) || st.st_uid || (st.st_mode & 077) ||
	    lstat(TEST_ROOT "/linux-state-active", &marker) || !S_ISREG(marker.st_mode) ||
	    marker.st_uid || (marker.st_mode & 077)) {
		fprintf(stderr, "Refusing: run only through the root-owned isolated-store wrapper.\n");
		return -1;
	}
	return 0;
}

static int enumerate(int fd, uint32_t session, uint32_t *finger)
{
	uint8_t p[180] = {0}; *finger = 0;
	if (command(fd, session, GROUP_CMD, NULL, 0) || command(fd, session, ENUM_CMD, p, sizeof(p))) return -1;
	uint32_t declared = get32(p + 96); unsigned count = 0;
	for (unsigned i = 0; i < 10; ++i) {
		uint32_t id = get32(p + 140 + 4*i), group = get32(p + 100 + 4*i);
		if (!id) continue;
		printf("TEST_STORE_ENTRY: group=%u finger=%u\n", group, id);
		if (group) { fprintf(stderr, "Unexpected nonzero test group.\n"); return -1; }
		*finger = id; ++count;
	}
	printf("TEST_STORE_COUNT=%u declared=%u\n", count, declared);
	if (declared != count) { fprintf(stderr, "Enumeration mismatch; stopping.\n"); return -1; }
	return (int)count;
}

static int pre_enroll(int fd, uint32_t session, uint8_t out[104])
{
	memset(out, 0, 104);
	if (command(fd, session, PRE_CMD, out, 104)) return -1;
	uint64_t challenge; memcpy(&challenge, out + 96, 8);
	if (!challenge) { fprintf(stderr, "PRE_ENROLL returned zero challenge.\n"); return -1; }
	puts("PRE_ENROLL: fresh nonzero challenge obtained (not logged).");
	return 0;
}

static int wait_kernel_irq(int nl)
{
	struct pollfd p = { .fd = nl, .events = POLLIN };
	int r = poll(&p, 1, 250);
	if (r < 0) return errno == EINTR ? 0 : -1;
	if (!r) return 0;
	if (!(p.revents & POLLIN)) return -1;
	union { struct nlmsghdr aligned; uint8_t b[256]; } msg;
	struct sockaddr_nl from = {0}; socklen_t flen = sizeof(from);
	ssize_t n = recvfrom(nl, &msg, sizeof(msg), 0, (struct sockaddr *)&from, &flen);
	if (n < 0) return errno == EINTR ? 0 : -1;
	struct nlmsghdr *h = (struct nlmsghdr *)msg.b;
	if (flen != sizeof(from) || from.nl_pid || n < (ssize_t)NLMSG_LENGTH(1) ||
	    h->nlmsg_len < NLMSG_LENGTH(1) || h->nlmsg_len > (size_t)n || h->nlmsg_pid) return 0;
	return *(uint8_t *)NLMSG_DATA(h) == 1;
}

static int finish_auth(int fd, uint32_t session, const uint8_t *irq)
{
	uint8_t p[120] = {0};
	/* Lenovo 0x5c840: ordinary LE copies, unlike the reference gfenu codec. */
	put32(p + 100, get32(irq + 100)); put32(p + 104, get32(irq + 96));
	put32(p + 108, get32(irq + GROUP_OFF)); put32(p + 112, get32(irq + FINGER_OFF));
	return command(fd, session, AUTH_FINISH_CMD, p, sizeof(p));
}

static int capture(int fd, uint32_t session, int nl, bool enrolling, uint32_t expected)
{
	struct timespec begin, now; clock_gettime(CLOCK_MONOTONIC, &begin);
	uint8_t *irq = calloc(1, IRQ_LEN);
	if (!irq) return -1;
	int result = -1; unsigned events = 0;
	printf("READY_%s: timeout=%u seconds; persistent Linux store only.\n", enrolling ? "ENROLL" : "VERIFY", enrolling ? 180 : 45);
	fflush(stdout);
	while (!stopped) {
		clock_gettime(CLOCK_MONOTONIC, &now);
		if (now.tv_sec - begin.tv_sec >= (enrolling ? 180 : 45)) break;
		int ready = wait_kernel_irq(nl);
		if (ready < 0) { perror("wait netlink"); goto out; }
		if (!ready) continue;
		if (++events > 1000) { fprintf(stderr, "IRQ limit; stopping.\n"); goto out; }
		memset(irq, 0, IRQ_LEN);
		bool drained = false;
		for (unsigned d = 0; d < 16 && !stopped; ++d) {
			if (command(fd, session, IRQ_CMD, irq, IRQ_LEN)) goto out;
			uint32_t mask = get32(irq + 96), op = get32(irq + 100);
			uint32_t group = get32(irq + GROUP_OFF), finger = get32(irq + FINGER_OFF);
			unsigned remain = get16(irq + REMAIN_OFF);
			printf("LIFECYCLE_IRQ: mask=0x%08x op=%u status=%u remaining=%u group=%u finger=%u%s%s\n",
			       mask, op, last_status, remain, group, finger, mask & 2 ? " DOWN" : "", mask & 4 ? " UP" : "");
			fflush(stdout);
			if (last_status == 1049) { fprintf(stderr, "TA dead; stopping.\n"); goto out; }
			if (!mask) { drained = true; break; }
			if (!(mask & (0x80 | 0x400))) continue;
			if (enrolling) {
				if (op || last_status || remain || !finger || group) continue;
				uint8_t save[108] = {0}; put32(save + 96, group); put32(save + 100, finger);
				if (command(fd, session, SAVE_CMD, save, sizeof(save))) goto out;
				uint32_t listed = 0; int count = enumerate(fd, session, &listed);
				if (count != 1 || listed != finger) { fprintf(stderr, "Save/enum mismatch; not claiming success.\n"); goto out; }
				printf("ENROLL_SAVED: group=0 finger=%u\n", finger);
				result = 0; goto out;
			} else if (op == 1 || op == 2) {
				if (last_status == 1064) { puts("VERIFY_REJECT: TA did not match."); result = 3; goto out; }
				if (last_status) continue;
				if (!finger || finger != expected || group) { fprintf(stderr, "Unrecognised match locator; not accepting.\n"); goto out; }
				if (finish_auth(fd, session, irq)) goto out;
				printf("VERIFY_MATCH: group=0 finger=%u; AUTH_FINISH succeeded.\n", finger);
				result = 0; goto out;
			}
		}
		if (!drained) { fprintf(stderr, "IRQ did not drain.\n"); goto out; }
	}
	fprintf(stderr, "Capture stopped or timed out; no success claimed.\n");
out:
	memset(irq, 0, IRQ_LEN); free(irq); return result;
}

int main(int argc, char **argv)
{
	bool preparing = false, enrolling = false; uint32_t expected = 0;
	if (argc == 2 && !strcmp(argv[1], "--status")) preparing = true;
	else if (argc == 2 && !strcmp(argv[1], "--enroll")) enrolling = true;
	else if (argc == 3 && !strcmp(argv[1], "--verify")) {
		char *end; errno = 0; unsigned long n = strtoul(argv[2], &end, 10);
		if (errno || *end || n < 1 || n > UINT32_MAX) return 2;
		expected = (uint32_t)n;
	} else {
		fprintf(stderr, "Usage: %s --status | --enroll | --verify FINGER_ID\n"
		        "Persistent Linux store only. No PAM, no signed-HAT claim, no delete/image dump.\n", argv[0]); return 2;
	}
	if (require_isolated_wrapper()) return 2;
	struct sigaction sa = { .sa_handler = stop_signal }; sigemptyset(&sa.sa_mask);
	if (sigaction(SIGTERM, &sa, NULL) || sigaction(SIGINT, &sa, NULL)) return 2;
	int sensor = sensor_open(); if (sensor < 0) return 2;
	int fd = find_client(NULL), nl = -1, result = 1; uint32_t session = 0;
	bool opened = false, armed = false;
	if (fd < 0 || open_session(fd, &session)) goto out;
	opened = true;
	uint8_t info[INFO_LEN], init[INIT_LEN];
	if (command(fd, session, DETECT_CMD, NULL, 0) || command(fd, session, INFO_CMD, info, sizeof(info))) goto out;
	if (memcmp(info + 708, "GF_CHIP_3626ZS1", sizeof("GF_CHIP_3626ZS1"))) { fprintf(stderr, "Unsupported model.\n"); goto out; }
	if (command(fd, session, INIT_CMD, init, sizeof(init))) goto out;
	nl = sensor_netlink(sensor);
	if (nl < 0 || ioctl(sensor, GF_IRQ_ON)) goto out;
	if (command(fd, session, FINISH_CMD, NULL, 0)) goto out;
	uint32_t listed; int count = enumerate(fd, session, &listed);
	if (count < 0) goto out;
	if (enrolling && count) { fprintf(stderr, "Refusing enrolment into nonempty test store.\n"); goto out; }
	if (preparing) {
		printf("PERSISTENT_STORE_READY: count=%d\n", count); result = 0; goto out;
	}
	if (enrolling) {
		uint8_t pre[104]; if (pre_enroll(fd, session, pre)) goto out;

		uint8_t p[176] = {0};
		/* Explicit user-selected reference challenge-only provider, not a signed HAT.
		 * HAT69 at+106; version at+106=0, fresh challenge at+107, rest zero.
		 * No invented signing keys, Android state or template import. */
		memcpy(p + 107, pre + 96, 8);
		puts("EXPERIMENTAL_REFERENCE_TOKEN: persistent Linux store, no login integration.");
		if (command(fd, session, ENROLL_CMD, p, sizeof(p))) {
			fprintf(stderr, "TA rejected reference enrolment attempt; no alternate token attempted.\n"); goto out;
		}
	} else {
		if (count != 1 || listed != expected) { fprintf(stderr, "Expected print absent from test store.\n"); goto out; }
		uint8_t p[120] = {0};
		if (command(fd, session, AUTH_CMD, p, sizeof(p))) goto out;
	}
	armed = true;
	result = capture(fd, session, nl, enrolling, expected);
	if (result < 0) result = 1;
out:
	if (opened && (armed || preparing) && command(fd, session, CANCEL_CMD, NULL, 0)) result = 1;
	ioctl(sensor, GF_IRQ_OFF);
	if (opened) { struct tee_ioctl_close_session_arg close_arg = { .session = session }; if (ioctl(fd, TEE_IOC_CLOSE_SESSION, &close_arg)) result = 1; }
	if (fd >= 0) close(fd);
	if (nl >= 0) close(nl);
	close(sensor);
	return result;
}

/* SPDX-License-Identifier: MIT
 * Read-only inventory by default. An explicit unused overlay-plane ID enables
 * a timed display-only test; no block devices or persistent files are opened.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/utsname.h>
#include <time.h>
#include <unistd.h>
#ifndef __user
#define __user
#endif
#include "drm.h"
#include "drm_fourcc.h"

static int fd = -1, overlay_enabled;
static uint32_t test_plane, test_fb, dumb_handle;
static uint32_t test_color = 0x00404040;
static volatile sig_atomic_t stopping;

static void cleanup(void)
{
    if (fd < 0) return;
    if (overlay_enabled) {
        struct drm_mode_set_plane off = { .plane_id = test_plane };
        if (ioctl(fd, DRM_IOCTL_MODE_SETPLANE, &off))
            perror("restore overlay");
        else
            puts("OVERLAY_RESTORED");
        overlay_enabled = 0;
    }
    if (test_fb) ioctl(fd, DRM_IOCTL_MODE_RMFB, &test_fb);
    if (dumb_handle) {
        struct drm_mode_destroy_dumb destroy = { .handle = dumb_handle };
        ioctl(fd, DRM_IOCTL_MODE_DESTROY_DUMB, &destroy);
    }
    close(fd);
    fd = -1;
}

static void die(const char *message)
{
    perror(message);
    exit(1);
}

static void interrupted(int signal_number)
{
    (void)signal_number;
    stopping = 1;
}

static int plane_type(uint32_t plane)
{
    uint32_t ids[64];
    uint64_t values[64];
    struct drm_mode_obj_get_properties properties = {
        .obj_id = plane, .obj_type = DRM_MODE_OBJECT_PLANE,
    };
    if (ioctl(fd, DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &properties) ||
        properties.count_props > 64) return -1;
    properties.props_ptr = (uintptr_t)ids;
    properties.prop_values_ptr = (uintptr_t)values;
    if (ioctl(fd, DRM_IOCTL_MODE_OBJ_GETPROPERTIES, &properties)) return -1;
    for (uint32_t i = 0; i < properties.count_props; i++) {
        struct drm_mode_get_property property = { .prop_id = ids[i] };
        if (!ioctl(fd, DRM_IOCTL_MODE_GETPROPERTY, &property) &&
            !strcmp(property.name, "type")) return (int)values[i];
    }
    return -1;
}

static uint32_t gray_framebuffer(uint32_t width, uint32_t height)
{
    struct drm_mode_create_dumb dumb = { .width = width, .height = height, .bpp = 32 };
    if (ioctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &dumb)) die("create RAM framebuffer");
    dumb_handle = dumb.handle;
    struct drm_mode_fb_cmd2 fb = {
        .width = width, .height = height, .pixel_format = DRM_FORMAT_XRGB8888,
    };
    fb.handles[0] = dumb.handle;
    fb.pitches[0] = dumb.pitch;
    if (ioctl(fd, DRM_IOCTL_MODE_ADDFB2, &fb)) die("add framebuffer");
    test_fb = fb.fb_id;
    struct drm_mode_map_dumb map = { .handle = dumb.handle };
    if (ioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &map)) die("map framebuffer");
    void *memory = mmap(NULL, dumb.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, map.offset);
    if (memory == MAP_FAILED) die("mmap framebuffer");
    for (uint32_t y = 0; y < height; y++) {
        uint32_t *row = (uint32_t *)((char *)memory + y * dumb.pitch);
        for (uint32_t x = 0; x < width; x++) row[x] = test_color;
    }
    __sync_synchronize();
    munmap(memory, dumb.size);
    return fb.fb_id;
}

int main(int argc, char **argv)
{
    unsigned long duration = 25;
    int scaled = 0, gray = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--plane") && i + 1 < argc)
            test_plane = strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--seconds") && i + 1 < argc)
            duration = strtoul(argv[++i], NULL, 10);
        else if (!strcmp(argv[i], "--scaled")) scaled = 1;
        else if (!strcmp(argv[i], "--gray")) gray = 1;
        else if (!strcmp(argv[i], "--color") && i + 1 < argc) {
            test_color = strtoul(argv[++i], NULL, 16);
            if (test_color > 0x00ffffff) return 2;
            gray = 1;
        }
        else {
            fprintf(stderr, "Usage: %s [--plane ID --seconds 1..60 [--scaled|--gray|--color RRGGBB]]\n", argv[0]);
            return 2;
        }
    }
    if (!duration || duration > 60 || ((scaled || gray) && !test_plane)) return 2;
    setvbuf(stdout, NULL, _IONBF, 0);
    atexit(cleanup);
    for (int card = 0; card < 4; card++) {
        char path[64], driver[64] = {0};
        snprintf(path, sizeof(path), "/dev/dri/card%d", card);
        fd = open(path, O_RDWR | O_CLOEXEC);
        if (fd < 0) continue;
        struct drm_version version = { .name_len = sizeof(driver) - 1, .name = driver };
        if (!ioctl(fd, DRM_IOCTL_VERSION, &version) && !strcmp(driver, "msm")) {
            printf("DRM_DEVICE=%s DRIVER=%s\n", path, driver);
            break;
        }
        close(fd);
        fd = -1;
    }
    if (fd < 0) die("find msm DRM device");
    struct drm_set_client_cap cap = { .capability = DRM_CLIENT_CAP_UNIVERSAL_PLANES, .value = 1 };
    if (ioctl(fd, DRM_IOCTL_SET_CLIENT_CAP, &cap)) die("universal planes");
    uint32_t crtcs[16];
    struct drm_mode_card_res resources = {0};
    if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &resources) || resources.count_crtcs > 16)
        die("CRTC resources");
    resources.crtc_id_ptr = (uintptr_t)crtcs;
    resources.count_fbs = resources.count_connectors = resources.count_encoders = 0;
    if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &resources)) die("CRTC list");
    struct drm_mode_crtc active = {0};
    int crtc_index = -1;
    for (uint32_t i = 0; i < resources.count_crtcs; i++) {
        struct drm_mode_crtc crtc = { .crtc_id = crtcs[i] };
        if (ioctl(fd, DRM_IOCTL_MODE_GETCRTC, &crtc)) die("get CRTC");
        printf("CRTC=%u FB=%u MODE=%ux%u ACTIVE=%u\n", crtc.crtc_id,
               crtc.fb_id, crtc.mode.hdisplay, crtc.mode.vdisplay, crtc.mode_valid);
        if (crtc.mode_valid && crtc.fb_id) { active = crtc; crtc_index = i; }
    }
    uint32_t ids[64];
    struct drm_mode_get_plane_res planes = {0};
    if (ioctl(fd, DRM_IOCTL_MODE_GETPLANERESOURCES, &planes) || planes.count_planes > 64)
        die("plane resources");
    planes.plane_id_ptr = (uintptr_t)ids;
    if (ioctl(fd, DRM_IOCTL_MODE_GETPLANERESOURCES, &planes)) die("plane list");
    struct drm_mode_get_plane selected = {0};
    int selected_type = -1;
    for (uint32_t i = 0; i < planes.count_planes; i++) {
        struct drm_mode_get_plane plane = { .plane_id = ids[i] };
        if (ioctl(fd, DRM_IOCTL_MODE_GETPLANE, &plane)) die("get plane");
        int type = plane_type(plane.plane_id);
        printf("PLANE=%u TYPE=%d CRTC=%u FB=%u POSSIBLE=%x\n", plane.plane_id,
               type, plane.crtc_id, plane.fb_id, plane.possible_crtcs);
        if (plane.plane_id == test_plane) { selected = plane; selected_type = type; }
    }
    if (!test_plane) return 0;
    char board[128] = {0};
    int board_fd = open("/sys/firmware/devicetree/base/compatible", O_RDONLY | O_CLOEXEC);
    if (board_fd < 0 || read(board_fd, board, sizeof(board) - 1) <= 0) die("read board");
    close(board_fd);
    struct utsname kernel;
    if (uname(&kernel)) die("uname");
    if (strcmp(board, "lenovo,j716f") ||
        (strcmp(kernel.release, "6.15.11") && strcmp(kernel.release, "7.4.0-rc2-j716f")) ||
        active.mode.hdisplay != 2560 || active.mode.vdisplay != 1600 ||
        crtc_index < 0 || !selected.plane_id || selected_type != 0 /* DRM plane type: Overlay */ ||
        selected.fb_id || !(selected.possible_crtcs & (1u << crtc_index))) {
        fprintf(stderr, "Display test preflight rejected: wrong board/kernel/mode or occupied/non-overlay plane\n");
        return 1;
    }
    if (ioctl(fd, DRM_IOCTL_SET_MASTER, 0) && errno != EINVAL) die("DRM master");
    uint32_t width = active.mode.hdisplay + (scaled ? 2 : 0);
    struct drm_mode_set_plane set = {
        .plane_id = test_plane, .crtc_id = active.crtc_id,
        .fb_id = active.fb_id, .crtc_w = active.mode.hdisplay,
        .crtc_h = active.mode.vdisplay,
        .src_w = width << 16, .src_h = active.mode.vdisplay << 16,
    };
    if (scaled || gray) set.fb_id = gray_framebuffer(width, active.mode.vdisplay);
    signal(SIGINT, interrupted);
    signal(SIGTERM, interrupted);
    signal(SIGHUP, interrupted);
    if (ioctl(fd, DRM_IOCTL_MODE_SETPLANE, &set)) die("enable timed overlay");
    overlay_enabled = 1;
    printf("OVERLAY_ENABLED plane=%u scaled=%d duration=%lu\n", test_plane, scaled, duration);
    struct timespec delay = { .tv_sec = duration };
    while (!stopping && nanosleep(&delay, &delay) && errno == EINTR) {}
    cleanup();
    return 0;
}

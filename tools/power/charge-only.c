// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <linux/fb.h>
#include <linux/input.h>
#include <linux/kd.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include "charge-vbus.h"

struct screen {int fd, tty, old_kd, width, height, stride; size_t length; uint32_t *pixels; struct fb_var_screeninfo var; bool blank;};
static struct screen screen={.fd=-1,.tty=-1};
static volatile sig_atomic_t stopping;
struct setting {char path[512],old[32];};
static struct setting idle[64],brightness;
static size_t idle_count;
static int keyfd=-1;
static const struct glyph {char ch; unsigned char rows[7];} font[]={
 {'0',{14,17,19,21,25,17,14}},{'1',{4,12,4,4,4,4,14}},
 {'2',{14,17,1,2,4,8,31}},{'3',{30,1,1,14,1,1,30}},
 {'4',{2,6,10,18,31,2,2}},{'5',{31,16,16,30,1,1,30}},
 {'6',{14,16,16,30,17,17,14}},{'7',{31,1,2,4,8,8,8}},
 {'8',{14,17,17,14,17,17,14}},{'9',{14,17,17,15,1,1,14}},
 {'A',{14,17,17,31,17,17,17}},{'B',{30,17,17,30,17,17,30}},
 {'C',{14,17,16,16,16,17,14}},{'D',{30,17,17,17,17,17,30}},
 {'E',{31,16,16,30,16,16,31}},{'F',{31,16,16,30,16,16,16}},
 {'G',{14,17,16,23,17,17,15}},{'H',{17,17,17,31,17,17,17}},
 {'I',{14,4,4,4,4,4,14}},{'J',{7,2,2,2,2,18,12}},
 {'K',{17,18,20,24,20,18,17}},{'L',{16,16,16,16,16,16,31}},
 {'M',{17,27,21,21,17,17,17}},{'N',{17,25,21,19,17,17,17}},
 {'O',{14,17,17,17,17,17,14}},{'P',{30,17,17,30,16,16,16}},
 {'Q',{14,17,17,17,21,18,13}},{'R',{30,17,17,30,20,18,17}},
 {'S',{15,16,16,14,1,1,30}},{'T',{31,4,4,4,4,4,4}},
 {'U',{17,17,17,17,17,17,14}},{'V',{17,17,17,17,17,10,4}},
 {'W',{17,17,17,21,21,21,10}},{'X',{17,17,10,4,10,17,17}},
 {'Y',{17,17,10,4,4,4,4}},{'Z',{31,1,2,4,8,16,31}},
 {'%',{17,18,2,4,8,9,17}}
};
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (double)t.tv_sec+t.tv_nsec/1e9;}
static void signal_stop(int sig){(void)sig;stopping=1;}
static int read_text(const char *path,char *buf,size_t size){int fd=open(path,O_RDONLY|O_CLOEXEC);if(fd<0)return -1;ssize_t n=read(fd,buf,size-1);close(fd);if(n<0)return -1;buf[n]=0;while(n>0&&(buf[n-1]=='\n'||buf[n-1]=='\r'))buf[--n]=0;return (int)n;}
static int write_text(const char *path,const char *s){int fd=open(path,O_WRONLY|O_CLOEXEC);if(fd<0)return -1;size_t n=strlen(s);ssize_t done=write(fd,s,n);close(fd);return done==(ssize_t)n?0:-1;}
/* Pin both the PM8150B device and named channel; enumeration order may vary. */
static int usb_voltage_path(char *path, size_t size)
{
    glob_t g;
    int found = -1;
    if (glob("/sys/bus/iio/devices/iio:device*/in_voltage_usbin_v_input", 0, NULL, &g))
        return -1;
    for (size_t i = 0; i < g.gl_pathc; i++) {
        char base[512], namepath[550], name[160], node[550], resolved[1024];
        if (strlen(g.gl_pathv[i]) >= sizeof(base))
            continue;
        snprintf(base, sizeof(base), "%s", g.gl_pathv[i]);
        char *slash = strrchr(base, '/');
        if (!slash)
            continue;
        *slash = 0;
        snprintf(namepath, sizeof(namepath), "%s/name", base);
        if (read_text(namepath, name, sizeof(name)) < 0 ||
            strcmp(name, "c440000.spmi:pmic@2:adc@3100"))
            continue;
        snprintf(node, sizeof(node), "%s/of_node", base);
        if (!realpath(node, resolved) ||
            strcmp(resolved, "/sys/firmware/devicetree/base/soc@0/spmi@c440000/pmic@2/adc@3100"))
            continue;
        if (strlen(g.gl_pathv[i]) >= size)
            continue;
        snprintf(path, size, "%s", g.gl_pathv[i]);
        found = 0;
        break;
    }
    globfree(&g);
    return found;
}

static long usb_voltage(const char *path)
{
    char value[64], *end;
    if (!path[0] || read_text(path, value, sizeof(value)) <= 0)
        return -1;
    errno = 0;
    long uv = strtol(value, &end, 10);
    if (errno || end == value || *end || uv < 0 || uv > 30000000)
        return -1;
    return uv;
}

static int marker(const char *name)
{
    char path[160];
    if (mkdir("/run/j716f-charge-only", 0700) && errno != EEXIST)
        return -1;
    if (snprintf(path, sizeof(path), "/run/j716f-charge-only/%s", name) >= (int)sizeof(path))
        return -1;
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0)
        return -1;
    return close(fd);
}

static uint32_t color(unsigned r,unsigned g,unsigned b){return ((r>>(8-screen.var.red.length))<<screen.var.red.offset)|((g>>(8-screen.var.green.length))<<screen.var.green.offset)|((b>>(8-screen.var.blue.length))<<screen.var.blue.offset);}
static void rect(int x,int y,int w,int h,uint32_t c){for(int yy=y;yy<y+h;yy++){if(yy<0||yy>=screen.height)continue;for(int xx=x;xx<x+w;xx++)if(xx>=0&&xx<screen.width)screen.pixels[(size_t)yy*screen.stride+xx]=c;}}
static void text(const char *s,int y,int scale,uint32_t c){int x=(screen.width-(int)strlen(s)*6*scale+scale)/2;for(;*s;s++,x+=6*scale){for(size_t i=0;i<sizeof(font)/sizeof(font[0]);i++)if(font[i].ch==*s)for(int row=0;row<7;row++)for(int col=0;col<5;col++)if(font[i].rows[row]&(1u<<(4-col)))rect(x+col*scale,y+row*scale,scale,scale,c);}}
static void draw(int percent,const char *status){uint32_t fg=color(225,231,237),green=color(115,225,165),border=color(105,119,130);rect(0,0,screen.width,screen.height,0);int w=screen.width/4,h=screen.height/6,x=(screen.width-w)/2,y=screen.height*36/100,t=screen.width/200;if(t<3)t=3;rect(x,y,w,h,border);rect(x+t,y+t,w-2*t,h-2*t,0);rect(x+w,y+h/3,t*3,h/3,border);int inset=t*3;int fill=(w-2*inset)*percent/100;rect(x+inset,y+inset,fill,h-2*inset,percent<15?color(235,108,105):green);char number[16];snprintf(number,sizeof(number),"%d%%",percent);int big=screen.width/128;if(big<3)big=3;text(number,screen.height*60/100,big,fg);int small=screen.width/430;if(small<2)small=2;const char *caption=strcmp(status,"Full")==0?"FULLY CHARGED":strcmp(status,"Charging")==0?"CHARGING":strcmp(status,"Discharging")==0?"BATTERY POWER":"CHARGE ONLY";text(caption,screen.height*76/100,small,border);text("HOLD POWER TO START UBUNTU",screen.height*88/100,small,fg);}
static void blank(bool value){if(screen.fd>=0)ioctl(screen.fd,FBIOBLANK,value?FB_BLANK_POWERDOWN:FB_BLANK_UNBLANK);screen.blank=value;}
static int setup_screen(void){screen.fd=open("/dev/fb0",O_RDWR|O_CLOEXEC);if(screen.fd<0)return -1;struct fb_fix_screeninfo f;if(ioctl(screen.fd,FBIOGET_FSCREENINFO,&f)||ioctl(screen.fd,FBIOGET_VSCREENINFO,&screen.var))return -1;if(screen.var.bits_per_pixel!=32||screen.var.xres>8192||screen.var.yres>8192||screen.var.red.length>8||screen.var.green.length>8||screen.var.blue.length>8)return -1;screen.width=(int)screen.var.xres;screen.height=(int)screen.var.yres;screen.stride=(int)f.line_length/4;screen.length=f.smem_len;if(screen.width<320||screen.height<240||screen.stride<screen.width||screen.length>256*1024*1024u||(size_t)f.line_length*(screen.var.yoffset+screen.var.yres)>screen.length)return -1;screen.pixels=mmap(NULL,screen.length,PROT_READ|PROT_WRITE,MAP_SHARED,screen.fd,0);if(screen.pixels==MAP_FAILED){screen.pixels=NULL;return -1;}screen.tty=open("/dev/tty1",O_RDWR|O_CLOEXEC);if(screen.tty>=0&&ioctl(screen.tty,KDGETMODE,&screen.old_kd)==0)ioctl(screen.tty,KDSETMODE,KD_GRAPHICS);blank(false);return 0;}
static void idle_policy(void){glob_t g;if(glob("/sys/devices/system/cpu/cpu*/cpuidle/state*/disable",0,NULL,&g)==0){for(size_t i=0;i<g.gl_pathc&&idle_count<64;i++){struct setting *s=&idle[idle_count];snprintf(s->path,sizeof(s->path),"%s",g.gl_pathv[i]);if(read_text(s->path,s->old,sizeof(s->old))>0&&write_text(s->path,"1\n")==0)idle_count++;}globfree(&g);}if(glob("/sys/class/backlight/*/brightness",0,NULL,&g)==0){if(g.gl_pathc){snprintf(brightness.path,sizeof(brightness.path),"%s",g.gl_pathv[0]);if(read_text(brightness.path,brightness.old,sizeof(brightness.old))>0)write_text(brightness.path,"362\n");}globfree(&g);}}
static int power_key(void){glob_t g;int fd=-1;if(glob("/sys/class/input/event*/device/name",0,NULL,&g)!=0)return -1;for(size_t i=0;i<g.gl_pathc;i++){char name[100],event[50],dev[100];if(read_text(g.gl_pathv[i],name,sizeof(name))<0)continue;if(strcmp(name,"pm8941_pwrkey")&&strcmp(name,"pmic_pwrkey"))continue;if(sscanf(g.gl_pathv[i],"/sys/class/input/%49[^/]/device/name",event)!=1)continue;snprintf(dev,sizeof(dev),"/dev/input/%s",event);fd=open(dev,O_RDONLY|O_NONBLOCK|O_CLOEXEC);if(fd>=0&&ioctl(fd,EVIOCGRAB,1)==0)break;if(fd>=0)close(fd);fd=-1;}globfree(&g);return fd;}
static int battery(char *path,size_t size){glob_t g;int found=-1;if(glob("/sys/class/power_supply/*/type",0,NULL,&g)!=0)return -1;for(size_t i=0;i<g.gl_pathc;i++){char type[50];if(read_text(g.gl_pathv[i],type,sizeof(type))>0&&strcmp(type,"Battery")==0){snprintf(path,size,"%s",g.gl_pathv[i]);char *last=strrchr(path,'/');if(last)*last=0;found=0;break;}}globfree(&g);return found;}
static int read_battery(const char *base,char *status,size_t size){char path[600],s[50];snprintf(path,sizeof(path),"%s/capacity",base);if(read_text(path,s,sizeof(s))<0)return -1;char *end;long value=strtol(s,&end,10);if(end==s||value<0||value>100)return -1;snprintf(path,sizeof(path),"%s/status",base);if(read_text(path,status,size)<0)snprintf(status,size,"Unknown");return (int)value;}
static void cleanup(void){if(keyfd>=0){ioctl(keyfd,EVIOCGRAB,0);close(keyfd);}for(size_t i=0;i<idle_count;i++)write_text(idle[i].path,idle[i].old);if(brightness.path[0]&&brightness.old[0])write_text(brightness.path,brightness.old);if(screen.fd>=0)blank(false);if(screen.tty>=0){ioctl(screen.tty,KDSETMODE,screen.old_kd);close(screen.tty);}if(screen.pixels&&screen.length)munmap(screen.pixels,screen.length);if(screen.fd>=0)close(screen.fd);}
static int preview(const char *path,int percent){screen.width=2560;screen.height=1600;screen.stride=2560;screen.var.red.length=screen.var.green.length=screen.var.blue.length=8;screen.var.red.offset=16;screen.var.green.offset=8;screen.var.blue.offset=0;screen.pixels=calloc((size_t)screen.width*screen.height,4);if(!screen.pixels)return 1;draw(percent,percent==100?"Full":"Charging");FILE *f=fopen(path,"wb");if(!f){free(screen.pixels);return 1;}fprintf(f,"P6\n%d %d\n255\n",screen.width,screen.height);for(int y=0;y<screen.height;y++)for(int x=0;x<screen.width;x++){uint32_t p=screen.pixels[(size_t)y*screen.stride+x];unsigned char b[3]={(p>>16)&255,(p>>8)&255,p&255};if(fwrite(b,1,3,f)!=3){fclose(f);free(screen.pixels);return 1;}}fclose(f);free(screen.pixels);return 0;}
int main(int argc, char **argv)
{
    if (argc >= 3 && !strcmp(argv[1], "--preview")) {
        int percent = argc > 3 ? atoi(argv[3]) : 100;
        return percent < 0 || percent > 100 ? 1 : preview(argv[2], percent);
    }
    char board[1000];
    int n = read_text("/sys/firmware/devicetree/base/compatible", board, sizeof(board));
    if (geteuid() || n < 0 || !memmem(board, (size_t)n, "lenovo,j716f", 12)) {
        fprintf(stderr, "J716F root-only charging UI\n");
        return 1;
    }
    char cmdline[4096], *save, *mode = NULL, *reason = NULL;
    if (read_text("/proc/cmdline", cmdline, sizeof(cmdline)) < 0)
        return 1;
    for (char *arg = strtok_r(cmdline, " \t", &save); arg;
         arg = strtok_r(NULL, " \t", &save)) {
        if (!strncmp(arg, "androidboot.mode=", 17))
            mode = arg + 17;
        if (!strncmp(arg, "androidboot.bootreason=", 23))
            reason = arg + 23;
    }
    if (!mode || strcmp(mode, "charger") || !reason ||
        (strcmp(reason, "usb_chg") && strcmp(reason, "charger"))) {
        fprintf(stderr, "Normal boot; skip charging UI\n");
        return 0;
    }
    if (!access("/run/j716f-charge-only/enter-ubuntu", F_OK)) {
        fprintf(stderr, "Ubuntu desktop already selected; skip charging UI\n");
        return 0;
    }
    signal(SIGTERM, signal_stop);
    signal(SIGINT, signal_stop);
    char bpath[512], status[50], old_status[50] = "", vpath[512] = "";
    double deadline = now() + 20;
    int percent = -1;
    while (!stopping && now() < deadline) {
        keyfd = power_key();
        if (keyfd >= 0 && !battery(bpath, sizeof(bpath)) &&
            (percent = read_battery(bpath, status, sizeof(status))) >= 0)
            break;
        if (keyfd >= 0) {
            ioctl(keyfd, EVIOCGRAB, 0);
            close(keyfd);
            keyfd = -1;
        }
        usleep(200000);
    }
    if (stopping || keyfd < 0 || percent < 0 || setup_screen()) {
        fprintf(stderr, "Power key, battery or framebuffer not ready; use normal desktop\n");
        cleanup();
        return stopping ? 0 : 1;
    }
    idle_policy();
    double visible_until = now() + 15, last_read = 0, pressed_at = 0, last_usb = 0;
    bool was_blank = false;
    int old_percent = -1, rc = 0;
    struct charge_vbus vbus = {0};
    if (usb_voltage_path(vpath, sizeof(vpath)))
        fprintf(stderr, "USB voltage channel unavailable; automatic poweroff disabled\n");
    printf("Charge-only UI ready: battery=%d%%; hold physical power for two seconds\n", percent);
    fflush(stdout);
    while (!stopping) {
        double t = now();
        if (t - last_usb >= 0.5) {
            if (!vpath[0])
                usb_voltage_path(vpath, sizeof(vpath));
            long uv = usb_voltage(vpath);
            bool armed = vbus.armed;
            bool poweroff = charge_vbus_update(&vbus, t, uv);
            if (!armed && vbus.armed) {
                printf("USB supply detected: %ld uV; unplug monitor armed\n", uv);
                fflush(stdout);
            }
            last_usb = t;
            if (poweroff) {
                if (marker("poweroff-requested")) {
                    rc = 1;
                    break;
                }
                printf("USB supply absent for three seconds: %ld uV; orderly poweroff\n", uv);
                fflush(stdout);
                rc = 21;
                break;
            }
        }
        if (t - last_read >= 2) {
            int p = read_battery(bpath, status, sizeof(status));
            if (p >= 0)
                percent = p;
            last_read = t;
        }
        if (!screen.blank && (old_percent != percent || strcmp(status, old_status))) {
            draw(percent, status);
            old_percent = percent;
            snprintf(old_status, sizeof(old_status), "%s", status);
        }
        if (!screen.blank && t > visible_until && !pressed_at)
            blank(true);
        struct pollfd pfd = {.fd = keyfd, .events = POLLIN};
        int ready = poll(&pfd, 1, 100);
        if ((ready < 0 && errno != EINTR) ||
            (ready > 0 && (pfd.revents & (POLLERR | POLLHUP | POLLNVAL)))) {
            rc = 1;
            break;
        }
        if (ready > 0 && (pfd.revents & POLLIN)) {
            struct input_event events[16];
            ssize_t bytes = read(keyfd, events, sizeof(events));
            if (bytes > 0)
                for (size_t i = 0; i < (size_t)bytes / sizeof(events[0]); i++) {
                    if (events[i].type != EV_KEY || events[i].code != KEY_POWER)
                        continue;
                    if (events[i].value == 1) {
                        pressed_at = now();
                        was_blank = screen.blank;
                        if (screen.blank) {
                            blank(false);
                            old_percent = -1;
                        }
                        visible_until = now() + 15;
                    } else if (!events[i].value) {
                        if (pressed_at && now() - pressed_at < 2 && !was_blank)
                            blank(true);
                        pressed_at = 0;
                    }
                }
        }
        if (pressed_at && now() - pressed_at >= 2) {
            rc = marker("enter-ubuntu") ? 1 : 20;
            break;
        }
    }
    cleanup();
    return rc;
}

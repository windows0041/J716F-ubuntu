// SPDX-License-Identifier: GPL-2.0
/*
 * Goodix fingerprint SPI pin scanner for the Lenovo TB-J716F.
 *
 * The stock firmware drives this part over a bit-banged SPI bus, but its
 * device tree never says which TLMM pins are used (all 20 hardware SPI
 * controllers are disabled, and there is no spi-gpio node). Rather than
 * guess, let user space drive arbitrary (sck, mosi, miso, cs) pin
 * combinations and look for a combination where MISO stops being a
 * constant 1 (which is what an idle, unconnected line reads).
 *
 * Everything goes through raw TLMM gpio numbers so a single module can
 * test any pin without a rebuild.
 */

#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/gpio.h>
#include <linux/gpio/driver.h>
#include <linux/gpio/machine.h>
#include <linux/delay.h>
#include <linux/slab.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/uaccess.h>

#define MAX_PINS 8

struct fp_scan {
	int sck, mosi, miso, cs;
	int g_miso;
	struct gpio_desc *d_sck, *d_mosi, *d_miso, *d_cs;
	bool claimed;
};

static struct fp_scan scan;

static void release_pins(void)
{
	if (scan.d_sck)  { gpiod_put(scan.d_sck);  scan.d_sck = NULL; }
	if (scan.d_mosi) { gpiod_put(scan.d_mosi); scan.d_mosi = NULL; }
	if (scan.d_miso) { gpiod_put(scan.d_miso); scan.d_miso = NULL; }
	if (scan.d_cs)   { gpiod_put(scan.d_cs);   scan.d_cs = NULL; }
	scan.claimed = false;
}

/*
 * The caller passes TLMM pin numbers (0..179), but gpiolib numbers the
 * chips globally: f100000.pinctrl is gpiochip3 and owns 538..718, so a
 * TLMM pin N is global GPIO 538 + N. Resolve the base at runtime instead
 * of hardcoding it.
 */
static int tlmm_base = -1;

static int tlmm_to_global(int pin)
{
	return tlmm_base + pin;
}

static int claim_pins(int sck, int mosi, int miso, int cs)
{
	int g_sck, g_mosi, g_miso, g_cs;

	release_pins();

	/* TLMM pins 0..179 live on gpiochip3 = global 538..718 */
	if (tlmm_base < 0)
		tlmm_base = 538;

	g_sck  = tlmm_to_global(sck);
	g_mosi = tlmm_to_global(mosi);
	g_miso = tlmm_to_global(miso);
	g_cs   = tlmm_to_global(cs);

	scan.d_sck  = gpio_to_desc(g_sck);
	scan.d_mosi = gpio_to_desc(g_mosi);
	scan.d_miso = gpio_to_desc(g_miso);
	scan.d_cs   = gpio_to_desc(g_cs);
	if (!scan.d_sck || !scan.d_mosi || !scan.d_miso || !scan.d_cs) {
		release_pins();
		return -ENODEV;
	}
	if (gpio_request(g_sck,  "fp-scan-sck") ||
	    gpio_request(g_mosi, "fp-scan-mosi") ||
	    gpio_request(g_miso, "fp-scan-miso") ||
	    gpio_request(g_cs,   "fp-scan-cs")) {
		release_pins();
		return -EBUSY;
	}
	gpiod_direction_output(scan.d_sck, 0);
	gpiod_direction_output(scan.d_mosi, 0);
	gpiod_direction_output(scan.d_cs, 1);
	gpiod_direction_input(scan.d_miso);
	scan.sck = sck; scan.mosi = mosi; scan.miso = miso; scan.cs = cs;
	scan.g_miso = g_miso;
	scan.claimed = true;
	return 0;
}

static inline void sck_hi(void) { gpiod_set_value(scan.d_sck, 1); ndelay(200); }
static inline void sck_lo(void) { gpiod_set_value(scan.d_sck, 0); ndelay(200); }

static u8 bb_xfer(u8 out)
{
	u8 in = 0;
	int i;

	for (i = 7; i >= 0; i--) {
		gpiod_set_value(scan.d_mosi, (out >> i) & 1);
		sck_hi();
		in = (in << 1) | (gpiod_get_value(scan.d_miso) & 1);
		sck_lo();
	}
	return in;
}

/*
 * One Goodix transaction: assert CS, clock out a command byte plus four
 * payload bytes, read the last five bytes back, deassert CS.
 * Returns the bytes read.
 */
static int bb_transaction(u8 cmd, u8 *rx, int n)
{
	int i;

	gpiod_set_value(scan.d_cs, 0);
	ndelay(500);
	bb_xfer(cmd);
	for (i = 0; i < n; i++)
		rx[i] = bb_xfer(0x00);
	gpiod_set_value(scan.d_cs, 1);
	ndelay(500);
	return 0;
}



/* ---- procfs interface: works as soon as the module is loaded ---- */

static int fp_scan_show(struct seq_file *m, void *v)
{
	if (!scan.claimed) {
		seq_puts(m, "unclaimed\n");
		return 0;
	}
	seq_printf(m, "sck=%d mosi=%d miso=%d cs=%d miso_level=%d\n",
		   scan.sck, scan.mosi, scan.miso, scan.cs,
		   gpio_get_value(scan.g_miso));
	return 0;
}

static int fp_scan_open(struct inode *inode, struct file *file)
{
	return single_open(file, fp_scan_show, NULL);
}

static ssize_t fp_scan_write(struct file *file, const char __user *ubuf,
			     size_t count, loff_t *ppos)
{
	char kbuf[64];
	int sck, mosi, miso, cs, ret;
	u8 rx[5];

	if (count >= sizeof(kbuf))
		return -EINVAL;
	if (copy_from_user(kbuf, ubuf, count))
		return -EFAULT;
	kbuf[count] = '\0';

	/* "release" drops the pins; anything else is "sck mosi miso cs" */
	if (sysfs_streq(kbuf, "release")) {
		release_pins();
		return count;
	}

	if (sscanf(kbuf, "%d %d %d %d", &sck, &mosi, &miso, &cs) != 4)
		return -EINVAL;

	ret = claim_pins(sck, mosi, miso, cs);
	if (ret)
		return ret;

	bb_transaction(0xA8, rx, 5);
	pr_info("fp-scan: sck=%d mosi=%d miso=%d cs=%d -> %02x %02x %02x %02x %02x\n",
		sck, mosi, miso, cs, rx[0], rx[1], rx[2], rx[3], rx[4]);
	return count;
}

static const struct proc_ops fp_scan_proc_ops = {
	.proc_open    = fp_scan_open,
	.proc_read    = seq_read,
	.proc_lseek   = seq_lseek,
	.proc_release = single_release,
	.proc_write   = fp_scan_write,
};

static int __init fp_scan_init(void)
{
	proc_create("fp_scan", 0200, NULL, &fp_scan_proc_ops);
	pr_info("fp-scan: ready, use /proc/fp_scan\n");
	return 0;
}

static void __exit fp_scan_exit(void)
{
	remove_proc_entry("fp_scan", NULL);
	release_pins();
}

module_init(fp_scan_init);
module_exit(fp_scan_exit);

MODULE_DESCRIPTION("Goodix fingerprint SPI pin scanner for Lenovo TB-J716F");
MODULE_LICENSE("GPL");

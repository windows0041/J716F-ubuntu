// SPDX-License-Identifier: GPL-2.0
/*
 * Sample a DMIC data line to find out whether a microphone is actually
 * driving it.
 *
 * The TX/VA macro register state can look perfect while the capture port
 * delivers nothing, because the DMIC pads are inside the LPASS and the
 * macro only routes what arrives on them. Reading the pad directly as a
 * GPIO is the cheapest way to tell "microphone is clocking data out"
 * apart from "pad is idle".
 *
 * Usage:
 *   echo "<lpi_pin>" > /proc/dmic_probe     # returns transitions seen
 * A silent pad gives 0 or a tiny number; a live DMIC toggles thousands of
 * times per millisecond.
 */
#include <linux/module.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/uaccess.h>
#include <linux/gpio.h>
#include <linux/delay.h>

#define LPI_GPIO_BASE 719	/* gpiochip4: GPIOs 719-732 (33c0000.pinctrl) */

static int last_pin = -1;
static unsigned long last_transitions;

static ssize_t dmic_probe_write(struct file *file, const char __user *ubuf,
				size_t count, loff_t *ppos)
{
	char kbuf[32];
	int pin, g, i, prev, cur;
	unsigned long transitions = 0;

	if (count >= sizeof(kbuf))
		return -EINVAL;
	if (copy_from_user(kbuf, ubuf, count))
		return -EFAULT;
	kbuf[count] = '\0';

	/*
	 * "selftest <pin>" drives the pad as a GPIO output and reads it back,
	 * so we can tell whether a 0-transition reading means "no signal" or
	 * "the GPIO input path is disconnected while the pin is muxed to a
	 * peripheral function". Without this control the DMIC measurements
	 * are not trustworthy.
	 */
	if (strncmp(kbuf, "selftest", 8) == 0) {
		int sp;

		if (kstrtoint(kbuf + 8, 10, &sp) || sp < 0 || sp > 13)
			return -EINVAL;
		g = LPI_GPIO_BASE + sp;
		if (gpio_request(g, "dmic-selftest"))
			return -EBUSY;
		gpio_direction_output(g, 0);
		prev = gpio_get_value(g);
		transitions = 0;
		for (i = 0; i < 20; i++) {
			gpio_set_value(g, i & 1);
			cur = gpio_get_value(g);
			if (cur != prev) {
				transitions++;
				prev = cur;
			}
		}
		gpio_direction_input(g);
		gpio_free(g);
		last_pin = sp;
		last_transitions = transitions;
		pr_info("dmic-selftest: LPI gpio%d toggled 20x, read back %lu changes\n",
			sp, transitions);
		return count;
	}

	if (kstrtoint(kbuf, 10, &pin) || pin < 0 || pin > 13)
		return -EINVAL;

	g = LPI_GPIO_BASE + pin;
	if (gpio_request(g, "dmic-probe"))
		return -EBUSY;

	gpio_direction_input(g);
	prev = gpio_get_value(g);

	/* ~20 ms of sampling: a 2.4 MHz DMIC clocks ~50k bits in that time */
	for (i = 0; i < 20000; i++) {
		cur = gpio_get_value(g);
		if (cur != prev) {
			transitions++;
			prev = cur;
		}
		udelay(1);
	}

	last_pin = pin;
	last_transitions = transitions;
	pr_info("dmic-probe: LPI gpio%d transitions=%lu\n", pin, transitions);

	gpio_free(g);
	return count;
}

static int dmic_probe_show(struct seq_file *m, void *v)
{
	if (last_pin < 0)
		seq_puts(m, "no sample yet\n");
	else
		seq_printf(m, "lpi_gpio=%d transitions=%lu\n",
			   last_pin, last_transitions);
	return 0;
}

static int dmic_probe_open(struct inode *inode, struct file *file)
{
	return single_open(file, dmic_probe_show, NULL);
}

static const struct proc_ops dmic_probe_ops = {
	.proc_open    = dmic_probe_open,
	.proc_read    = seq_read,
	.proc_lseek   = seq_lseek,
	.proc_release = single_release,
	.proc_write   = dmic_probe_write,
};

static int __init dmic_probe_init(void)
{
	proc_create("dmic_probe", 0200, NULL, &dmic_probe_ops);
	pr_info("dmic-probe: ready, echo <lpi_pin 0-13> > /proc/dmic_probe\n");
	return 0;
}

static void __exit dmic_probe_exit(void)
{
	remove_proc_entry("dmic_probe", NULL);
}

module_init(dmic_probe_init);
module_exit(dmic_probe_exit);

MODULE_DESCRIPTION("DMIC data line activity probe for Lenovo TB-J716F");
MODULE_LICENSE("GPL");

// SPDX-License-Identifier: GPL-2.0
/* j716f bring-up debug: scan every registered I2C adapter once, log ACKs. */
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/init.h>

static int scan_adapter(struct i2c_adapter *adap, void *data)
{
	struct device *dev = data;
	char b = 0;
	int addr;

	for (addr = 0x03; addr < 0x78; addr++) {
		struct i2c_msg m = { .addr = addr, .flags = 0, .len = 1, .buf = &b };
		int rc = i2c_transfer(adap, &m, 1);
		if (rc == 1)
			dev_info(dev, "i2c-scan: %s (bus %d) ACK 0x%02x\n",
				 adap->name, i2c_adapter_id(adap), addr);
	}
	return 0;
}

static int __init i2c_scan_init(void)
{
	struct device *dev = bus_to_dev? NULL : NULL;
	/* iterate adapters via bus_find */
	pr_info("i2c-scan: starting\n");
	i2c_for_each_dev(NULL, NULL);
	return 0;
}
device_initcall(i2c_scan_init);
MODULE_LICENSE("GPL");

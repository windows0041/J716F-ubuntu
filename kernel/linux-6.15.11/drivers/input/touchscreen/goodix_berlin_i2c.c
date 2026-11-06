// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Goodix Berlin Touchscreen Driver
 *
 * Copyright (C) 2020 - 2021 Goodix, Inc.
 * Copyright (C) 2023 Linaro Ltd.
 *
 * Based on goodix_ts_berlin driver.
 */
#include <linux/i2c.h>
#include <linux/gpio/consumer.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/regmap.h>
#include <linux/regulator/consumer.h>
#include <linux/input.h>

#include "goodix_berlin.h"

#define I2C_MAX_TRANSFER_SIZE		256

/*
 * Lenovo J716F: GT7385P does not speak the 32-bit register address the
 * generic Berlin I2C glue assumes. With reg_bits = 32 a write of 8x 0xAA to
 * BOOTOPTION (0x10000) reads back as "00 aa aa aa aa aa 02 00" - the
 * payload is shifted, i.e. the chip consumed a different number of address
 * bytes than we sent. Try 16-bit addressing, which matches the rest of the
 * Goodix parts on this platform.
 */
static const struct regmap_config goodix_berlin_i2c_regmap_conf = {
	.reg_bits = 32,
	.val_bits = 8,
	.max_raw_read = I2C_MAX_TRANSFER_SIZE,
	.max_raw_write = I2C_MAX_TRANSFER_SIZE,
};

/* vendor & product left unassigned here, should probably be updated from fw info */
static const struct input_id goodix_berlin_i2c_input_id = {
	.bustype = BUS_I2C,
};

static int goodix_berlin_i2c_probe(struct i2c_client *client)
{
	const struct goodix_berlin_ic_data *ic_data =
		i2c_get_match_data(client);
	struct regmap *regmap;
	int error;

	regmap = devm_regmap_init_i2c(client, &goodix_berlin_i2c_regmap_conf);
	if (IS_ERR(regmap))
		return PTR_ERR(regmap);

	error = goodix_berlin_probe(&client->dev, client->irq,
				    &goodix_berlin_i2c_input_id, regmap,
				    ic_data);
	return error;
}

static const struct goodix_berlin_ic_data gt9916_data = {
	.fw_version_info_addr = GOODIX_BERLIN_FW_VERSION_INFO_ADDR_D,
	.ic_info_addr = GOODIX_BERLIN_IC_INFO_ADDR_D,
};

/* Lenovo J716F (Xiaoxin Pad Pro 2021): GT7385P, same Berlin "D" address set
 * as GT9916 per the vendor goodix,gt738x node in the stock DT. */
static const struct goodix_berlin_ic_data gt7385p_data = {
	.fw_version_info_addr = GOODIX_BERLIN_FW_VERSION_INFO_ADDR_D,
	.ic_info_addr = GOODIX_BERLIN_IC_INFO_ADDR_D,
};

static const struct i2c_device_id goodix_berlin_i2c_id[] = {
	{ .name = "gt9916", .driver_data = (long)&gt9916_data },
	{ .name = "gt7385p", .driver_data = (long)&gt7385p_data },
	{ }
};

MODULE_DEVICE_TABLE(i2c, goodix_berlin_i2c_id);

static const struct of_device_id goodix_berlin_i2c_of_match[] = {
	{ .compatible = "goodix,gt9916", .data = &gt9916_data },
	{ .compatible = "goodix,gt7385p", .data = &gt7385p_data },
	{ }
};
MODULE_DEVICE_TABLE(of, goodix_berlin_i2c_of_match);

static struct i2c_driver goodix_berlin_i2c_driver = {
	.driver = {
		.name = "goodix-berlin-i2c",
		.of_match_table = goodix_berlin_i2c_of_match,
		.pm = pm_sleep_ptr(&goodix_berlin_pm_ops),
		.dev_groups = goodix_berlin_groups,
	},
	.probe = goodix_berlin_i2c_probe,
	.id_table = goodix_berlin_i2c_id,
};
module_i2c_driver(goodix_berlin_i2c_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Goodix Berlin I2C Touchscreen driver");
MODULE_AUTHOR("Neil Armstrong <neil.armstrong@linaro.org>");

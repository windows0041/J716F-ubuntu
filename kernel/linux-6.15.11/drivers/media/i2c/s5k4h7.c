// SPDX-License-Identifier: GPL-2.0-only
/*
 * Samsung S5K4H7 (ISOCELL 4H7) 8 MP image sensor driver
 *
 * The S5K4H7 uses 16-bit big-endian register addresses over I2C, like the
 * OmniVision parts, and reports its chip ID at register 0x0000. Two modules
 * are fitted to the Lenovo Xiaoxin Pad Pro 2021 (TB-J716F): an RGB one on the
 * front and an IR one beside it.
 *
 * This driver implements the minimum needed to identify the sensor, put it in
 * a known mode and stream raw Bayer frames through the Qualcomm CAMSS
 * pipeline: power sequencing, chip-ID check, one full-resolution mode,
 * exposure/gain controls and a 2-lane MIPI CSI-2 output.
 */

#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/pm_runtime.h>
#include <linux/regmap.h>
#include <linux/regulator/consumer.h>

#include <media/v4l2-ctrls.h>
#include <media/v4l2-device.h>
#include <media/v4l2-fwnode.h>

/* Register access is 16-bit big-endian; values are 8/16/24 bits wide. */
#define S5K4H7_REG_VALUE_08BIT		1
#define S5K4H7_REG_VALUE_16BIT		2
#define S5K4H7_REG_VALUE_24BIT		3

#define S5K4H7_REG_CHIP_ID		0x0000
#define S5K4H7_CHIP_ID_RGB		0x487b
#define S5K4H7_CHIP_ID_IR		0x487d

/*
 * 0x0100/0x0101 form a 16-bit "mode select" register pair: 0x0100 is the
 * high byte and 0x0101 the low byte. The reset value is 0x0100 (high 0x01,
 * low 0x00) and the streaming bit is bit 0 of the low byte, so the stream
 * command is a write of 0x01 to 0x0101.
 */
#define S5K4H7_REG_MODE_SELECT		0x0100
#define S5K4H7_REG_MODE_SELECT_LOW	0x0101
#define S5K4H7_MODE_STANDBY		0x00
#define S5K4H7_MODE_STREAMING		0x01

#define S5K4H7_REG_SOFTWARE_RESET	0x0103
#define S5K4H7_SOFTWARE_RESET		0x01

/* Full-resolution (3264x2448) mode, 2 data lanes, 19.2 MHz XVCLK. */
#define S5K4H7_NATIVE_WIDTH		3264
#define S5K4H7_NATIVE_HEIGHT		2448

/* Link frequency for the 2-lane mode used by the vendor tables. */
#define S5K4H7_LINK_FREQ_480MHZ		480000000ULL

/*
 * Pixel rate from the link frequency: double data rate, 2 lanes, 10 bits per
 * pixel. The /10 matters: without it the value is ten times too high and the
 * VFE clock check in camss-vfe.c fails with -EBUSY ("Failed to power up
 * pipeline"), because the required rate exceeds what VFE1 can supply.
 */
static u64 s5k4h7_link_freq_to_pixel_rate(u64 f)
{
	f *= 2 * 4;	/* DDR * 4 data lanes */
	do_div(f, 10);	/* 10 bits per pixel */

	return f;
}

#define S5K4H7_PIXEL_RATE		s5k4h7_link_freq_to_pixel_rate(S5K4H7_LINK_FREQ_480MHZ)

/* Exposure is 16 bits spread over three registers, VTS is 16 bits. */
#define S5K4H7_REG_EXPOSURE		0x0202
#define S5K4H7_EXPOSURE_MIN		4
#define S5K4H7_EXPOSURE_STEP		1
#define S5K4H7_EXPOSURE_DEFAULT		0x0400
#define S5K4H7_REG_VTS			0x0340
#define S5K4H7_VTS_MAX			0xffff
#define S5K4H7_VTS_DEFAULT		0x09a0

#define S5K4H7_REG_ANALOG_GAIN		0x0204
#define S5K4H7_AGAIN_MIN		0
#define S5K4H7_AGAIN_MAX		0x1f
#define S5K4H7_AGAIN_DEFAULT		0x08

#define S5K4H7_REG_DIGITAL_GAIN		0x020e
#define S5K4H7_DGAIN_MIN		0
#define S5K4H7_DGAIN_MAX		0x3f
#define S5K4H7_DGAIN_DEFAULT		0x10

static const s64 s5k4h7_link_freq_menu[] = {
	S5K4H7_LINK_FREQ_480MHZ,
};

#define S5K4H7_REG_TEST_PATTERN		0x0600
#define S5K4H7_TEST_PATTERN_OFF		0x0000

/*
 * Minimal bring-up sequence. The vendor module ships a 4 kB register table
 * (com.qti.sensormodule.lce_s5k4h7rgb.bin, regSetting at 0xeb8) which this
 * sequence is distilled from: soft reset, PLL setup for 19.2 MHz XVCLK,
 * 2-lane MIPI output, full-resolution readout and raw10 packing.
 */
/*
 * Register sequence for the 3264x2448 mode, taken verbatim from the upstream
 * mainline V4L2 driver for this sensor (drivers/media/i2c/s5k4h7yx.c by Luca
 * Weiss, msm8953-mainline). The large 0x30xx / 0x3Cxx block is the analogue
 * and MIPI block setup that a hand-derived table misses - without it the
 * sensor accepts every register write and reports streaming, but emits no
 * CSI-2 data.
 */
static const struct reg_sequence s5k4h7_init_regs[] = {
	{ 0x0100, 0x00 },
	{ 0x0B05, 0x01 },
	{ 0x3074, 0x06 },
	{ 0x3075, 0x2F },
	{ 0x308A, 0x20 },
	{ 0x308B, 0x08 },
	{ 0x308C, 0x0B },
	{ 0x3081, 0x07 },
	{ 0x307B, 0x85 },
	{ 0x307A, 0x0A },
	{ 0x3079, 0x0A },
	{ 0x306E, 0x71 },
	{ 0x306F, 0x28 },
	{ 0x301F, 0x20 },
	{ 0x306B, 0x9A },
	{ 0x3091, 0x1F },
	{ 0x30C4, 0x06 },
	{ 0x3200, 0x09 },
	{ 0x306A, 0x79 },
	{ 0x30B0, 0xFF },
	{ 0x306D, 0x08 },
	{ 0x3080, 0x00 },
	{ 0x3929, 0x3F },
	{ 0x3084, 0x16 },
	{ 0x3070, 0x0F },
	{ 0x3B45, 0x01 },
	{ 0x30C2, 0x05 },
	{ 0x3069, 0x87 },
	{ 0x3924, 0x7F },
	{ 0x3925, 0xFD },
	{ 0x3C08, 0xFF },
	{ 0x3C09, 0xFF },
	{ 0x3C31, 0xFF },
	{ 0x3C32, 0xFF },
	{ 0x0A02, 0x14 },
	{ 0x0100, 0x00 },
	{ 0x0136, 0x18 },
	{ 0x0137, 0x00 },
	{ 0x0305, 0x06 },
	{ 0x0306, 0x00 },
	{ 0x0307, 0x8C },
	{ 0x030D, 0x06 },
	{ 0x030E, 0x00 },
	{ 0x030F, 0xAF },
	{ 0x3C1F, 0x00 },
	{ 0x3C17, 0x00 },
	{ 0x3C1C, 0x05 },
	{ 0x3C1D, 0x15 },
	{ 0x0301, 0x04 },
	{ 0x0820, 0x02 },
	{ 0x0821, 0xBC },
	{ 0x0822, 0x00 },
	{ 0x0823, 0x00 },
	{ 0x0112, 0x0A },
	{ 0x0113, 0x0A },
	{ 0x0114, 0x03 },
	{ 0x3906, 0x04 },
	{ 0x0344, 0x00 },
	{ 0x0345, 0x08 },
	{ 0x0346, 0x00 },
	{ 0x0347, 0x08 },
	{ 0x0348, 0x0C },
	{ 0x0349, 0xC7 },
	{ 0x034A, 0x09 },
	{ 0x034B, 0x97 },
	{ 0x034C, 0x0C },
	{ 0x034D, 0xC0 },
	{ 0x034E, 0x09 },
	{ 0x034F, 0x90 },
	{ 0x0900, 0x00 },
	{ 0x0901, 0x00 },
	{ 0x0381, 0x01 },
	{ 0x0383, 0x01 },
	{ 0x0385, 0x01 },
	{ 0x0387, 0x01 },
	{ 0x0101, 0x00 },
	{ 0x0340, 0x09 },
	{ 0x0341, 0xE2 },
	{ 0x0342, 0x0E },
	{ 0x0343, 0x68 },
	{ 0x0200, 0x0D },
	{ 0x0201, 0xD8 },
	{ 0x0202, 0x02 },
	{ 0x0203, 0x08 },
};

struct s5k4h7 {
	struct v4l2_subdev sd;
	struct media_pad pad;
	struct clk *xclk;
	struct gpio_desc *reset_gpio;
	struct gpio_desc *powerdown_gpio;

	struct regulator *vana;
	struct regulator *vdig;
	struct regulator *vio;

	struct v4l2_ctrl_handler ctrl_handler;
	struct v4l2_ctrl *exposure;
	struct v4l2_ctrl *again;
	struct v4l2_ctrl *dgain;
	struct v4l2_ctrl *link_freq;
	struct v4l2_ctrl *pixel_rate;

	struct mutex lock;
	bool streaming;
};

/*
 * 16-bit big-endian register access, matching the sensor's I2C protocol.
 * This is the same shape as ov13b10_read_reg(): a two-message transfer with
 * the register address in network byte order.
 */
static int s5k4h7_read_reg(struct s5k4h7 *sensor, u16 reg, u32 len, u32 *val)
{
	struct i2c_client *client = v4l2_get_subdevdata(&sensor->sd);
	struct i2c_msg msgs[2];
	u8 *data_be_p;
	int ret;
	__be32 data_be = 0;
	__be16 reg_addr_be = cpu_to_be16(reg);

	if (len > 4)
		return -EINVAL;

	data_be_p = (u8 *)&data_be;
	/* Write register address */
	msgs[0].addr = client->addr;
	msgs[0].flags = 0;
	msgs[0].len = 2;
	msgs[0].buf = (u8 *)&reg_addr_be;

	/* Read data */
	msgs[1].addr = client->addr;
	msgs[1].flags = I2C_M_RD;
	msgs[1].len = len;
	msgs[1].buf = &data_be_p[4 - len];

	ret = i2c_transfer(client->adapter, msgs, ARRAY_SIZE(msgs));
	if (ret != ARRAY_SIZE(msgs))
		return ret < 0 ? ret : -EIO;

	*val = be32_to_cpu(data_be);

	return 0;
}

static int s5k4h7_write_reg(struct s5k4h7 *sensor, u16 reg, u32 len, u32 val)
{
	struct i2c_client *client = v4l2_get_subdevdata(&sensor->sd);
	struct i2c_msg msg;
	u8 buf[6];
	__be16 reg_addr_be = cpu_to_be16(reg);
	__be32 data_be = cpu_to_be32(val);
	int ret;

	if (len > 4 || len < 1)
		return -EINVAL;

	/* Register address, then the value's significant bytes, big-endian. */
	memcpy(buf, &reg_addr_be, 2);
	memcpy(&buf[2], &((u8 *)&data_be)[4 - len], len);

	msg.addr = client->addr;
	msg.flags = 0;
	msg.len = 2 + len;
	msg.buf = buf;

	ret = i2c_transfer(client->adapter, &msg, 1);
	if (ret != 1)
		return ret < 0 ? ret : -EIO;

	return 0;
}

static int s5k4h7_identify_module(struct s5k4h7 *sensor)
{
	struct i2c_client *client = v4l2_get_subdevdata(&sensor->sd);
	u32 val;
	int ret;

	if (device_property_read_bool(&client->dev, "skip-id-check")) {
		dev_info(&client->dev, "s5k4h7: chip-ID check skipped (DT)\n");
		return 0;
	}

	ret = s5k4h7_read_reg(sensor, S5K4H7_REG_CHIP_ID,
			     S5K4H7_REG_VALUE_16BIT, &val);
	if (ret) {
		dev_err(&client->dev, "failed to read chip id: %d\n", ret);
		return ret;
	}

	if (val != S5K4H7_CHIP_ID_RGB && val != S5K4H7_CHIP_ID_IR) {
		dev_err(&client->dev, "chip id mismatch: 0x%x\n", val);
		return -EIO;
	}

	dev_info(&client->dev, "S5K4H7 detected, chip id 0x%04x\n", val);

	return 0;
}

static int s5k4h7_power_on(struct device *dev)
{
	struct v4l2_subdev *sd = dev_get_drvdata(dev);
	struct s5k4h7 *sensor = container_of(sd, struct s5k4h7, sd);
	int ret;

	ret = clk_prepare_enable(sensor->xclk);
	if (ret) {
		dev_err(dev, "failed to enable xclk: %d\n", ret);
		return ret;
	}

	if (sensor->vio) {
		ret = regulator_enable(sensor->vio);
		if (ret)
			goto err_clk;
	}

	if (sensor->vana) {
		ret = regulator_enable(sensor->vana);
		if (ret)
			goto err_vio;
	}

	if (sensor->vdig) {
		ret = regulator_enable(sensor->vdig);
		if (ret)
			goto err_vana;
	}

	gpiod_set_value_cansleep(sensor->powerdown_gpio, 0);
	gpiod_set_value_cansleep(sensor->reset_gpio, 0);
	usleep_range(5000, 6000);

	return 0;

err_vana:
	if (sensor->vana)
		regulator_disable(sensor->vana);
err_vio:
	if (sensor->vio)
		regulator_disable(sensor->vio);
err_clk:
	clk_disable_unprepare(sensor->xclk);
	return ret;
}

static int s5k4h7_power_off(struct device *dev)
{
	struct v4l2_subdev *sd = dev_get_drvdata(dev);
	struct s5k4h7 *sensor = container_of(sd, struct s5k4h7, sd);

	gpiod_set_value_cansleep(sensor->reset_gpio, 1);
	gpiod_set_value_cansleep(sensor->powerdown_gpio, 1);
	if (sensor->vdig)
		regulator_disable(sensor->vdig);
	if (sensor->vana)
		regulator_disable(sensor->vana);
	if (sensor->vio)
		regulator_disable(sensor->vio);
	clk_disable_unprepare(sensor->xclk);

	return 0;
}

static int s5k4h7_enable_streams(struct v4l2_subdev *sd,
				 struct v4l2_subdev_state *state,
				 u32 pad, u64 streams_mask)
{
	struct s5k4h7 *sensor = container_of(sd, struct s5k4h7, sd);
	struct device *dev = sd->dev;
	int ret;

	ret = pm_runtime_resume_and_get(dev);
	if (ret)
		return ret;

	/* Apply the bring-up table, then the current controls. */
	for (unsigned int i = 0; i < ARRAY_SIZE(s5k4h7_init_regs); i++) {
		ret = s5k4h7_write_reg(sensor, s5k4h7_init_regs[i].reg,
				       S5K4H7_REG_VALUE_08BIT,
				       s5k4h7_init_regs[i].def);
		if (ret)
			goto err_rpm;
	}

	/* The sensor needs ~7.5 ms to settle before the stream-on write. */
	usleep_range(7400, 8000);

	ret = __v4l2_ctrl_handler_setup(&sensor->ctrl_handler);
	if (ret)
		goto err_rpm;

	ret = s5k4h7_write_reg(sensor, S5K4H7_REG_MODE_SELECT,
			       S5K4H7_REG_VALUE_08BIT, S5K4H7_MODE_STREAMING);
	if (ret)
		goto err_rpm;

	/* Diagnostic: read the key registers back so the log shows what the
	 * sensor really has after the bring-up sequence. */
	{
		static const u16 check[] = { 0x0000, 0x0100, 0x0101, 0x0301,
					     0x0303, 0x0305, 0x0307, 0x0309,
					     0x030b, 0x030d, 0x030f, 0x0311,
					     0x0340, 0x0342, 0x0112, 0x0114 };
		for (unsigned int i = 0; i < ARRAY_SIZE(check); i++) {
			u32 v = 0;
			int r = s5k4h7_read_reg(sensor, check[i],
						S5K4H7_REG_VALUE_16BIT, &v);
			dev_info(dev, "s5k4h7: reg 0x%04x = %s0x%04x\n",
				 check[i], r ? "(read failed) " : "", v);
		}
	}

	sensor->streaming = true;

	return 0;

err_rpm:
	pm_runtime_put_autosuspend(dev);
	return ret;
}

static int s5k4h7_disable_streams(struct v4l2_subdev *sd,
				  struct v4l2_subdev_state *state,
				  u32 pad, u64 streams_mask)
{
	struct s5k4h7 *sensor = container_of(sd, struct s5k4h7, sd);

	s5k4h7_write_reg(sensor, S5K4H7_REG_MODE_SELECT,
			 S5K4H7_REG_VALUE_08BIT, S5K4H7_MODE_STANDBY);
	sensor->streaming = false;
	pm_runtime_put_autosuspend(sd->dev);

	return 0;
}

static const struct v4l2_subdev_video_ops s5k4h7_video_ops = {
	/*
	 * The Qualcomm CAMSS driver starts streams through the legacy
	 * video.s_stream op (see video_start_streaming() in camss-video.c),
	 * not through v4l2_subdev_enable_streams(). This helper forwards
	 * s_stream(1/0) to the pad_ops enable_streams/disable_streams
	 * callbacks, which is where the power sequence lives.
	 */
	.s_stream = v4l2_subdev_s_stream_helper,
};

/*
 * Fill the pad format for the requested state (TRY or ACTIVE) and report it
 * back. The state is always updated through v4l2_subdev_state_get_format();
 * writing to fmt->format only would leave TRY handling with a NULL format
 * pointer and oops inside this function.
 */
static int s5k4h7_set_pad_format(struct v4l2_subdev *sd,
				 struct v4l2_subdev_state *state,
				 struct v4l2_subdev_format *fmt)
{
	struct v4l2_mbus_framefmt *framefmt;

	framefmt = v4l2_subdev_state_get_format(state, fmt->pad);
	if (!framefmt)
		return -EINVAL;

	framefmt->width = fmt->format.width ? fmt->format.width
					    : S5K4H7_NATIVE_WIDTH;
	framefmt->height = fmt->format.height ? fmt->format.height
					      : S5K4H7_NATIVE_HEIGHT;
	framefmt->code = fmt->format.code ? fmt->format.code
					  : MEDIA_BUS_FMT_SGRBG10_1X10;
	framefmt->field = V4L2_FIELD_NONE;
	framefmt->colorspace = V4L2_COLORSPACE_RAW;
	framefmt->ycbcr_enc = V4L2_YCBCR_ENC_601;
	framefmt->quantization = V4L2_QUANTIZATION_FULL_RANGE;
	framefmt->xfer_func = V4L2_XFER_FUNC_NONE;

	fmt->format = *framefmt;

	return 0;
}

static int s5k4h7_init_state(struct v4l2_subdev *sd,
			     struct v4l2_subdev_state *state)
{
	struct v4l2_subdev_format fmt = {
		.which = V4L2_SUBDEV_FORMAT_ACTIVE,
		.pad = 0,
		.format = {
			.width = S5K4H7_NATIVE_WIDTH,
			.height = S5K4H7_NATIVE_HEIGHT,
			.code = MEDIA_BUS_FMT_SGRBG10_1X10,
			.field = V4L2_FIELD_NONE,
			.colorspace = V4L2_COLORSPACE_RAW,
			.ycbcr_enc = V4L2_YCBCR_ENC_601,
			.quantization = V4L2_QUANTIZATION_FULL_RANGE,
			.xfer_func = V4L2_XFER_FUNC_NONE,
		},
	};

	return s5k4h7_set_pad_format(sd, state, &fmt);
}

static int s5k4h7_enum_mbus_code(struct v4l2_subdev *sd,
				 struct v4l2_subdev_state *state,
				 struct v4l2_subdev_mbus_code_enum *code)
{
	if (code->index != 0)
		return -EINVAL;

	code->code = MEDIA_BUS_FMT_SGRBG10_1X10;

	return 0;
}

static int s5k4h7_enum_frame_size(struct v4l2_subdev *sd,
				  struct v4l2_subdev_state *state,
				  struct v4l2_subdev_frame_size_enum *fse)
{
	if (fse->index != 0)
		return -EINVAL;

	fse->min_width = S5K4H7_NATIVE_WIDTH;
	fse->max_width = S5K4H7_NATIVE_WIDTH;
	fse->min_height = S5K4H7_NATIVE_HEIGHT;
	fse->max_height = S5K4H7_NATIVE_HEIGHT;

	return 0;
}

static const struct v4l2_subdev_pad_ops s5k4h7_pad_ops = {
	.set_fmt = s5k4h7_set_pad_format,
	.get_fmt = v4l2_subdev_get_fmt,
	.enum_mbus_code = s5k4h7_enum_mbus_code,
	.enum_frame_size = s5k4h7_enum_frame_size,
	.enable_streams = s5k4h7_enable_streams,
	.disable_streams = s5k4h7_disable_streams,
};

/*
 * Open sub-device. v4l2_pipeline_pm_get() walks the media graph and calls
 * this on every entity; without it the CAMSS video node fails to open with
 * "Failed to power up pipeline: -16". It also seeds the per-file try format.
 */
static int s5k4h7_open(struct v4l2_subdev *sd, struct v4l2_subdev_fh *fh)
{
	struct v4l2_mbus_framefmt *try_fmt =
		v4l2_subdev_state_get_format(fh->state, 0);

	try_fmt->width = S5K4H7_NATIVE_WIDTH;
	try_fmt->height = S5K4H7_NATIVE_HEIGHT;
	try_fmt->code = MEDIA_BUS_FMT_SGRBG10_1X10;
	try_fmt->field = V4L2_FIELD_NONE;
	try_fmt->colorspace = V4L2_COLORSPACE_RAW;
	try_fmt->ycbcr_enc = V4L2_YCBCR_ENC_601;
	try_fmt->quantization = V4L2_QUANTIZATION_FULL_RANGE;
	try_fmt->xfer_func = V4L2_XFER_FUNC_NONE;

	return 0;
}

static const struct v4l2_subdev_internal_ops s5k4h7_internal_ops = {
	.open = s5k4h7_open,
	.init_state = s5k4h7_init_state,
};

static const struct v4l2_subdev_ops s5k4h7_subdev_ops = {
	.video = &s5k4h7_video_ops,
	.pad = &s5k4h7_pad_ops,
};

static const struct media_entity_operations s5k4h7_subdev_entity_ops = {
	.link_validate = v4l2_subdev_link_validate,
};

static int s5k4h7_init_controls(struct s5k4h7 *sensor)
{
	struct v4l2_ctrl_handler *ctrl_hdlr = &sensor->ctrl_handler;
	struct v4l2_fwnode_device_properties props;
	int ret;

	ret = v4l2_ctrl_handler_init(ctrl_hdlr, 8);
	if (ret)
		return ret;

	sensor->exposure = v4l2_ctrl_new_std(ctrl_hdlr, NULL,
					     V4L2_CID_EXPOSURE,
					     S5K4H7_EXPOSURE_MIN,
					     S5K4H7_VTS_DEFAULT - 4,
					     S5K4H7_EXPOSURE_STEP,
					     S5K4H7_EXPOSURE_DEFAULT);
	sensor->again = v4l2_ctrl_new_std(ctrl_hdlr, NULL,
					  V4L2_CID_ANALOGUE_GAIN,
					  S5K4H7_AGAIN_MIN,
					  S5K4H7_AGAIN_MAX, 1,
					  S5K4H7_AGAIN_DEFAULT);
	sensor->dgain = v4l2_ctrl_new_std(ctrl_hdlr, NULL,
					  V4L2_CID_DIGITAL_GAIN,
					  S5K4H7_DGAIN_MIN,
					  S5K4H7_DGAIN_MAX, 1,
					  S5K4H7_DGAIN_DEFAULT);

	/*
	 * The CAMSS CSIPHY needs the CSI-2 transmitter link frequency, which it
	 * reads from this read-only menu control. Without it STREAMON fails with
	 * "Cannot get CSI2 transmitter's link frequency".
	 */
	sensor->link_freq = v4l2_ctrl_new_int_menu(ctrl_hdlr, NULL,
						   V4L2_CID_LINK_FREQ,
						   ARRAY_SIZE(s5k4h7_link_freq_menu) - 1,
						   0, s5k4h7_link_freq_menu);
	if (sensor->link_freq)
		sensor->link_freq->flags |= V4L2_CTRL_FLAG_READ_ONLY;

	sensor->pixel_rate = v4l2_ctrl_new_std(ctrl_hdlr, NULL,
					       V4L2_CID_PIXEL_RATE,
					       0, S5K4H7_PIXEL_RATE, 1,
					       S5K4H7_PIXEL_RATE);

	if (ctrl_hdlr->error) {
		ret = ctrl_hdlr->error;
		v4l2_ctrl_handler_free(ctrl_hdlr);
		return ret;
	}

	ret = v4l2_fwnode_device_parse(sensor->sd.dev, &props);
	if (ret)
		goto err_free;

	ret = v4l2_ctrl_new_fwnode_properties(ctrl_hdlr, NULL, &props);
	if (ret)
		goto err_free;

	sensor->sd.ctrl_handler = ctrl_hdlr;

	return 0;

err_free:
	v4l2_ctrl_handler_free(ctrl_hdlr);
	return ret;
}

static const struct of_device_id s5k4h7_of_match[] = {
	{ .compatible = "samsung,s5k4h7" },
	{ /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, s5k4h7_of_match);

static const struct i2c_device_id s5k4h7_id[] = {
	{ "s5k4h7", 0 },
	{ /* sentinel */ }
};
MODULE_DEVICE_TABLE(i2c, s5k4h7_id);

static int s5k4h7_probe(struct i2c_client *client)
{
	struct s5k4h7 *sensor;
	int ret;

	sensor = devm_kzalloc(&client->dev, sizeof(*sensor), GFP_KERNEL);
	if (!sensor)
		return -ENOMEM;

	v4l2_i2c_subdev_init(&sensor->sd, client, &s5k4h7_subdev_ops);
	sensor->sd.internal_ops = &s5k4h7_internal_ops;
	sensor->sd.flags |= V4L2_SUBDEV_FL_HAS_DEVNODE;
	sensor->sd.entity.ops = &s5k4h7_subdev_entity_ops;
	sensor->sd.entity.function = MEDIA_ENT_F_CAM_SENSOR;

	mutex_init(&sensor->lock);

	sensor->pad.flags = MEDIA_PAD_FL_SOURCE;
	ret = media_entity_pads_init(&sensor->sd.entity, 1, &sensor->pad);
	if (ret)
		return ret;

	sensor->xclk = devm_clk_get_optional(&client->dev, NULL);
	if (IS_ERR(sensor->xclk))
		return dev_err_probe(&client->dev, PTR_ERR(sensor->xclk),
				     "failed to get xclk\n");

	/*
	 * The vendor runs every camera MCLK at 24 MHz on this board, and the
	 * sensor's own PLL defaults (P=4, S=6, M=175) only produce the expected
	 * 350 MHz link frequency at that rate. The camcc mclk has a 24 MHz
	 * entry, so ask for it explicitly: without clk_set_rate() the clock
	 * stays at its 19.2 MHz default and the MIPI rate is wrong.
	 */
	/*
	 * NOTE: asking camcc for 24 MHz (clk_set_rate) hangs the boot on this
	 * board - that rate comes from CAM_CC_PLL2, which the display path also
	 * uses. The MCLK therefore stays at camcc's 19.2 MHz default, and the
	 * sensor's PLL registers must be programmed for 19.2 MHz input instead.
	 */
	if (sensor->xclk)
		dev_info(&client->dev, "s5k4h7: MCLK %lu Hz\n",
			 clk_get_rate(sensor->xclk));

	sensor->reset_gpio = devm_gpiod_get_optional(&client->dev, "reset",
						     GPIOD_OUT_HIGH);
	if (IS_ERR(sensor->reset_gpio))
		return dev_err_probe(&client->dev, PTR_ERR(sensor->reset_gpio),
				     "failed to get reset gpio\n");

	sensor->powerdown_gpio = devm_gpiod_get_optional(&client->dev,
							 "powerdown",
							 GPIOD_OUT_HIGH);
	if (IS_ERR(sensor->powerdown_gpio))
		return dev_err_probe(&client->dev,
				     PTR_ERR(sensor->powerdown_gpio),
				     "failed to get powerdown gpio\n");

	sensor->vana = devm_regulator_get_optional(&client->dev, "avdd");
	if (IS_ERR(sensor->vana)) {
		if (PTR_ERR(sensor->vana) != -ENODEV)
			return dev_err_probe(&client->dev, PTR_ERR(sensor->vana),
					     "failed to get avdd\n");
		sensor->vana = NULL;
	}

	sensor->vdig = devm_regulator_get_optional(&client->dev, "dvdd");
	if (IS_ERR(sensor->vdig)) {
		if (PTR_ERR(sensor->vdig) != -ENODEV)
			return dev_err_probe(&client->dev, PTR_ERR(sensor->vdig),
					     "failed to get dvdd\n");
		sensor->vdig = NULL;
	}

	sensor->vio = devm_regulator_get_optional(&client->dev, "dovdd");
	if (IS_ERR(sensor->vio)) {
		if (PTR_ERR(sensor->vio) != -ENODEV)
			return dev_err_probe(&client->dev, PTR_ERR(sensor->vio),
					     "failed to get dovdd\n");
		sensor->vio = NULL;
	}

	ret = s5k4h7_init_controls(sensor);
	if (ret)
		goto err_entity;

	/*
	 * The subdev state lock must be set and the state finalised before the
	 * subdev is registered. v4l2_subdev_enable_streams() takes
	 * sd->state_lock via v4l2_subdev_lock_and_get_active_state(); leaving
	 * it NULL makes STREAMON oops with a NULL-pointer dereference inside
	 * v4l2_subdev_enable_streams().
	 */
	sensor->sd.state_lock = sensor->ctrl_handler.lock;
	ret = v4l2_subdev_init_finalize(&sensor->sd);
	if (ret)
		goto err_ctrl;

	ret = s5k4h7_power_on(&client->dev);
	if (ret)
		goto err_ctrl;

	ret = s5k4h7_identify_module(sensor);
	if (ret)
		goto err_power_off;

	pm_runtime_set_active(&client->dev);
	pm_runtime_enable(&client->dev);
	if (device_property_read_bool(&client->dev, "skip-id-check")) {
		/* Diagnostic mode: stay powered so the bus can be scanned. */
		dev_info(&client->dev,
			 "s5k4h7: diagnostic mode, sensor left powered\n");
	} else {
		pm_runtime_set_autosuspend_delay(&client->dev, 1000);
		pm_runtime_use_autosuspend(&client->dev);
		pm_runtime_idle(&client->dev);
	}

	ret = v4l2_async_register_subdev_sensor(&sensor->sd);
	if (ret)
		goto err_pm;

	return 0;

err_pm:
	pm_runtime_disable(&client->dev);
err_power_off:
	s5k4h7_power_off(&client->dev);
err_ctrl:
	v4l2_ctrl_handler_free(&sensor->ctrl_handler);
err_entity:
	media_entity_cleanup(&sensor->sd.entity);
	return ret;
}

static void s5k4h7_remove(struct i2c_client *client)
{
	struct v4l2_subdev *sd = i2c_get_clientdata(client);
	struct s5k4h7 *sensor = container_of(sd, struct s5k4h7, sd);

	v4l2_async_unregister_subdev(sd);
	v4l2_ctrl_handler_free(&sensor->ctrl_handler);
	media_entity_cleanup(&sd->entity);
	pm_runtime_disable(&client->dev);
	pm_runtime_set_suspended(&client->dev);
}

static DEFINE_RUNTIME_DEV_PM_OPS(s5k4h7_pm_ops, s5k4h7_power_off,
				 s5k4h7_power_on, NULL);

static struct i2c_driver s5k4h7_i2c_driver = {
	.driver = {
		.name = "s5k4h7",
		.of_match_table = s5k4h7_of_match,
		.pm = pm_ptr(&s5k4h7_pm_ops),
	},
	.probe = s5k4h7_probe,
	.remove = s5k4h7_remove,
	.id_table = s5k4h7_id,
};
module_i2c_driver(s5k4h7_i2c_driver);

MODULE_DESCRIPTION("Samsung S5K4H7 image sensor driver");
MODULE_LICENSE("GPL");

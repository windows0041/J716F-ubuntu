// SPDX-License-Identifier: GPL-2.0
/*
 * Minimal Goodix fingerprint bring-up helper for the Lenovo TB-J716F.
 *
 * The stock kernel drives this part through its own "gf_spi" driver, which
 * is not in mainline. Before writing a full SPI driver we need to know
 * whether the hardware comes alive at all: power the rail, release reset,
 * and watch the IRQ line. That is all this module does - it exposes nothing
 * but a few sysfs attributes for poking the lines from user space.
 */

#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/gpio/consumer.h>
#include <linux/regulator/consumer.h>
#include <linux/interrupt.h>
#include <linux/delay.h>
#include <linux/of.h>

struct goodix_fp {
	struct device *dev;
	struct regulator *vdd;
	struct gpio_desc *irq;
	struct gpio_desc *reset;
	struct gpio_desc *envdd;
	int irq_num;
	atomic_t irq_count;
};

static irqreturn_t goodix_fp_irq(int irq, void *data)
{
	struct goodix_fp *fp = data;

	atomic_inc(&fp->irq_count);
	dev_info(fp->dev, "IRQ fired (total %d)\n",
		 atomic_read(&fp->irq_count));
	return IRQ_HANDLED;
}

static ssize_t state_show(struct device *dev, struct device_attribute *attr,
			  char *buf)
{
	struct goodix_fp *fp = dev_get_drvdata(dev);

	return sysfs_emit(buf,
		"vdd_enabled=%d\n"
		"envdd=%d\n"
		"reset=%d\n"
		"irq_level=%d\n"
		"irq_count=%d\n",
		regulator_is_enabled(fp->vdd),
		gpiod_get_value_cansleep(fp->envdd),
		gpiod_get_value_cansleep(fp->reset),
		gpiod_get_value_cansleep(fp->irq),
		atomic_read(&fp->irq_count));
}
static DEVICE_ATTR_RO(state);

static ssize_t reset_store(struct device *dev, struct device_attribute *attr,
			   const char *buf, size_t count)
{
	struct goodix_fp *fp = dev_get_drvdata(dev);
	int val, ret;

	ret = kstrtoint(buf, 0, &val);
	if (ret)
		return ret;

	gpiod_set_value_cansleep(fp->reset, !!val);
	return count;
}
static DEVICE_ATTR_WO(reset);

static ssize_t pulse_store(struct device *dev, struct device_attribute *attr,
			   const char *buf, size_t count)
{
	struct goodix_fp *fp = dev_get_drvdata(dev);

	/* Drive the vendor's power-up sequence: reset low, wait, reset high. */
	gpiod_set_value_cansleep(fp->reset, 0);
	msleep(20);
	gpiod_set_value_cansleep(fp->reset, 1);
	msleep(50);

	dev_info(dev, "reset pulsed, irq_level=%d\n",
		 gpiod_get_value_cansleep(fp->irq));
	return count;
}
static DEVICE_ATTR_WO(pulse);

static struct attribute *goodix_fp_attrs[] = {
	&dev_attr_state.attr,
	&dev_attr_reset.attr,
	&dev_attr_pulse.attr,
	NULL,
};
ATTRIBUTE_GROUPS(goodix_fp);

static int goodix_fp_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct goodix_fp *fp;
	int ret;

	fp = devm_kzalloc(dev, sizeof(*fp), GFP_KERNEL);
	if (!fp)
		return -ENOMEM;
	fp->dev = dev;
	platform_set_drvdata(pdev, fp);

	fp->vdd = devm_regulator_get(dev, "vdd");
	if (IS_ERR(fp->vdd))
		return dev_err_probe(dev, PTR_ERR(fp->vdd),
				     "no vdd supply\n");

	ret = regulator_enable(fp->vdd);
	if (ret)
		return dev_err_probe(dev, ret, "cannot enable vdd\n");

	/*
	 * The board tree uses the vendor's property names verbatim -
	 * fp-gpio-envdd / fp-gpio-reset / fp-gpio-irq - not the
	 * <name>-gpios form gpiod_get() expects, so resolve them by name
	 * with the con_id-less variant and let the DT lookup do the work.
	 */
	/*
	 * Power-up sequence: hold envdd low, then raise it, then release
	 * reset. The vendor gf_spi driver does the same - without the low
	 * phase the MCU never leaves its power-on hold and never raises
	 * INT, which is exactly what we observe (irq_count stays 0 even
	 * after a reset pulse).
	 */
	fp->envdd = devm_gpiod_get(dev, "fp-envdd", GPIOD_OUT_LOW);
	if (IS_ERR(fp->envdd)) {
		ret = PTR_ERR(fp->envdd);
		dev_err(dev, "envdd gpio: %d\n", ret);
		goto err_vdd;
	}
	msleep(10);
	gpiod_set_value_cansleep(fp->envdd, 1);
	msleep(50);

	fp->reset = devm_gpiod_get(dev, "fp-reset", GPIOD_OUT_LOW);
	if (IS_ERR(fp->reset)) {
		ret = PTR_ERR(fp->reset);
		dev_err(dev, "reset gpio: %d\n", ret);
		goto err_vdd;
	}

	fp->irq = devm_gpiod_get(dev, "fp-irq", GPIOD_IN);
	if (IS_ERR(fp->irq)) {
		ret = PTR_ERR(fp->irq);
		dev_err(dev, "irq gpio: %d\n", ret);
		goto err_vdd;
	}

	msleep(20);
	gpiod_set_value_cansleep(fp->reset, 1);
	msleep(50);

	fp->irq_num = gpiod_to_irq(fp->irq);
	if (fp->irq_num < 0) {
		ret = fp->irq_num;
		goto err_vdd;
	}

	/*
	 * Level-low caused an interrupt storm (152k events before we could
	 * even look at them): the sensor evidently idles with its INT line
	 * low while it has nothing to say, so a level trigger re-fires as
	 * fast as the kernel can run the handler. Use falling-edge instead -
	 * that is also what the vendor gf_spi driver ends up programming.
	 */
	ret = devm_request_threaded_irq(dev, fp->irq_num, NULL,
					goodix_fp_irq,
					IRQF_TRIGGER_FALLING | IRQF_ONESHOT,
					"goodix-fp", fp);
	if (ret)
		goto err_vdd;

	dev_info(dev, "ready: irq=%d vdd=%d envdd=%d reset=%d level=%d\n",
		 fp->irq_num, regulator_is_enabled(fp->vdd),
		 gpiod_get_value_cansleep(fp->envdd),
		 gpiod_get_value_cansleep(fp->reset),
		 gpiod_get_value_cansleep(fp->irq));
	return 0;

err_vdd:
	regulator_disable(fp->vdd);
	return ret;
}

static void goodix_fp_remove(struct platform_device *pdev)
{
	struct goodix_fp *fp = platform_get_drvdata(pdev);

	regulator_disable(fp->vdd);
}

static const struct of_device_id goodix_fp_of_match[] = {
	{ .compatible = "goodix,fingerprint" },
	{ }
};
MODULE_DEVICE_TABLE(of, goodix_fp_of_match);

static struct platform_driver goodix_fp_driver = {
	.probe = goodix_fp_probe,
	.remove = goodix_fp_remove,
	.driver = {
		.name = "goodix-fp",
		.of_match_table = goodix_fp_of_match,
		.dev_groups = goodix_fp_groups,
	},
};
module_platform_driver(goodix_fp_driver);

MODULE_DESCRIPTION("Goodix fingerprint bring-up helper (Lenovo TB-J716F)");
MODULE_LICENSE("GPL");

// SPDX-License-Identifier: GPL-2.0-only
#ifndef J716F_CHARGE_VBUS_H
#define J716F_CHARGE_VBUS_H
#include <stdbool.h>

/* ADC5 processed USB voltage is in microvolts. Never infer loss from USB data. */
struct charge_vbus {
    bool armed, absent;
    double absent_since, last_sample;
    unsigned absent_samples;
};

static inline bool charge_vbus_update(struct charge_vbus *s, double t, long uv)
{
    if (t < s->last_sample || t - s->last_sample > 1.5) {
        s->absent = false;
        s->absent_samples = 0;
    }
    s->last_sample = t;
    if (uv < 0 || uv > 30000000 || uv > 2000000) {
        if (uv >= 3500000 && uv <= 30000000)
            s->armed = true;
        s->absent = false;
        s->absent_samples = 0;
        return false;
    }
    if (!s->armed)
        return false;
    if (!s->absent) {
        s->absent = true;
        s->absent_since = t;
        s->absent_samples = 0;
    }
    s->absent_samples++;
    return s->absent_samples >= 6 && t - s->absent_since >= 3.0;
}
#endif

// SPDX-License-Identifier: GPL-2.0-only
#include <assert.h>
#include <stdio.h>
#include "charge-vbus.h"

static struct charge_vbus powered(void)
{
    struct charge_vbus s = {0};
    assert(!charge_vbus_update(&s, 1.0, 5000000));
    assert(s.armed);
    return s;
}

int main(void)
{
    struct charge_vbus s = {0};
    /* An unverified or missing channel must never turn the tablet off. */
    for (int i = 0; i < 100; i++)
        assert(!charge_vbus_update(&s, i * 0.5, i % 2 ? -1 : 0));
    assert(!s.armed);
    s = powered();
    for (int i = 0; i < 100; i++)
        assert(!charge_vbus_update(&s, 1.5 + i * 0.5, 5000000));
    /* A real disconnect has both a duration and a minimum sample count. */
    s = powered();
    for (int i = 0; i < 6; i++)
        assert(!charge_vbus_update(&s, 1.5 + i * 0.5, 20000));
    assert(charge_vbus_update(&s, 4.5, 0));
    /* A short negotiation dip, followed by voltage recovery, is harmless. */
    s = powered();
    for (int i = 0; i < 5; i++)
        assert(!charge_vbus_update(&s, 1.5 + i * 0.5, 0));
    assert(!charge_vbus_update(&s, 4.0, 5000000));
    for (int i = 0; i < 6; i++)
        assert(!charge_vbus_update(&s, 4.5 + i * 0.5, 0));
    assert(charge_vbus_update(&s, 7.5, 0));
    /* Read errors, invalid/out-of-range values and the hysteresis band reset. */
    const long interruptions[] = {-1, 30000001, 2500000};
    for (unsigned j = 0; j < sizeof(interruptions)/sizeof(interruptions[0]); j++) {
        s = powered();
        for (int i = 0; i < 5; i++)
            assert(!charge_vbus_update(&s, 1.5 + i * 0.5, 0));
        assert(!charge_vbus_update(&s, 4.0, interruptions[j]));
        for (int i = 0; i < 6; i++)
            assert(!charge_vbus_update(&s, 4.5 + i * 0.5, 0));
        assert(charge_vbus_update(&s, 7.5, 0));
    }
    /* Long scheduler stalls and a backwards clock are not continuous absence. */
    const double after_gap[] = {20.0, 0.5};
    for (unsigned j = 0; j < 2; j++) {
        s = powered();
        assert(!charge_vbus_update(&s, 1.5, 0));
        assert(!charge_vbus_update(&s, after_gap[j], 0));
        for (int i = 1; i < 6; i++)
            assert(!charge_vbus_update(&s, after_gap[j] + i * 0.5, 0));
        assert(charge_vbus_update(&s, after_gap[j] + 3.0, 0));
    }
    puts("PASS: disconnected startup, stable supply, unplug debounce, voltage recovery, invalid reads, hysteresis, scheduler gaps");
    return 0;
}

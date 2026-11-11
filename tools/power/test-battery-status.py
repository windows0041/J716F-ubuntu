#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
from pathlib import Path
import tempfile
import re
import subprocess

root = Path(__file__).resolve().parents[2] / 'kernel/linux-7.4-rc2'
source = (root/'drivers/power/supply/bq27xxx_battery.c').read_text()
function = re.search(r'static int bq27xxx_battery_current_and_status\(.*?\n\}', source, re.S).group()
temporary = tempfile.TemporaryDirectory(prefix='j716f-battery-status-')
work = Path(temporary.name)
prefix = '''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
typedef int16_t s16;
union power_supply_propval { int intval; };
struct bq27xxx_device_info { unsigned opts; int current; int flags; };
struct bq27xxx_reg_cache { int flags; };
#define BQ27XXX_O_ZERO 1
#define BQ27XXX_REG_AI 1
#define BQ27XXX_REG_FLAGS 2
#define BQ27000_FLAG_CHGS 128
#define BQ27XXX_CURRENT_CONSTANT 3570
#define BQ27XXX_RS 20
#define POWER_SUPPLY_STATUS_CHARGING 1
#define POWER_SUPPLY_STATUS_DISCHARGING 2
#define POWER_SUPPLY_STATUS_NOT_CHARGING 3
#define POWER_SUPPLY_STATUS_FULL 4
#define dev_err(...) ((void)0)
#define dev_dbg(...) ((void)0)
static bool j716f;
static bool of_machine_is_compatible(const char *name) { (void)name; return j716f; }
static int bq27xxx_read(struct bq27xxx_device_info *di,int reg,bool single) {
    (void)single; return reg == BQ27XXX_REG_AI ? di->current : di->flags;
}
static bool bq27xxx_battery_is_full(struct bq27xxx_device_info *di,int flags) {
    (void)di; return flags & 512;
}
'''
suffix = '''
static void check(bool board,int ma,bool full,int expected) {
    struct bq27xxx_device_info di={.current=(uint16_t)(int16_t)ma,.flags=full?512:0};
    union power_supply_propval current={0},status={0};
    j716f=board;
    assert(bq27xxx_battery_current_and_status(&di,&current,&status,NULL)==0);
    assert(current.intval==ma*1000);
    assert(status.intval==expected);
}
int main(void) {
    check(true,-454,true,POWER_SUPPLY_STATUS_DISCHARGING);
    check(false,-454,true,POWER_SUPPLY_STATUS_FULL);
    check(true,133,true,POWER_SUPPLY_STATUS_FULL);
    check(true,0,true,POWER_SUPPLY_STATUS_FULL);
    check(true,500,false,POWER_SUPPLY_STATUS_CHARGING);
    check(true,-500,false,POWER_SUPPLY_STATUS_DISCHARGING);
    check(true,0,false,POWER_SUPPLY_STATUS_NOT_CHARGING);
    struct bq27xxx_device_info di={.current=-5,.flags=512};
    union power_supply_propval status={.intval=123};
    assert(bq27xxx_battery_current_and_status(&di,NULL,&status,NULL)==-5);
    assert(status.intval==123);
    di.current=100;di.flags=-5;
    assert(bq27xxx_battery_current_and_status(&di,NULL,&status,NULL)==-5);
    assert(status.intval==123);
    puts("9 extracted-driver status cases passed");
}
'''
test = work/'test-status.c'
test.write_text(prefix+function+suffix)
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(test),'-o',str(work/'test-status')],check=True)
subprocess.run([str(work/'test-status')],check=True)
temporary.cleanup()

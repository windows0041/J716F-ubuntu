#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read battery-side power and the board's ADC5 USB voltage without root."""
from datetime import datetime
from pathlib import Path


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return None


def number(path):
    try:
        return int(read(path))
    except (TypeError, ValueError):
        return None


def main():
    battery = next((path for path in sorted(Path('/sys/class/power_supply').glob('*'))
                    if read(path / 'type') == 'Battery'), None)
    if battery is None:
        raise SystemExit('没有找到电池供电接口')
    voltage = number(battery / 'voltage_now')
    current = number(battery / 'current_now')
    capacity = number(battery / 'capacity')
    state = read(battery / 'status')
    state = {'Full': '已充满', 'Charging': '充电中', 'Discharging': '放电中',
             'Not charging': '未充电', 'Unknown': '未知'}.get(state, state or '未知')
    print('时间：' + datetime.now().astimezone().isoformat(timespec='seconds'))
    print('电量：' + (str(capacity) + '%' if capacity is not None else '不可用') + '，' + state)
    print('电池电压：' + (f'{voltage / 1000000:.3f} V' if voltage is not None else '不可用'))
    print('电池电流：' + (f'{current / 1000:+.0f} mA' if current is not None else '不可用'))
    power = (f'{voltage * current / 1000000000000:+.2f} W'
             if voltage is not None and current is not None else '不可用')
    print('电池侧净功率：' + power + '（正数充入，负数放出）')
    usb = None
    for path in sorted(Path('/sys/bus/iio/devices').glob('iio:device*/in_voltage_usbin_v_input')):
        value = number(path)
        if value is not None:
            usb = value
            break
    print('USB 实测电压：' + (f'{usb / 1000000:.3f} V' if usb is not None else '不可用'))
    print('USB 输入总功率：当前缺少实际输入电流采样，无法计算')


if __name__ == '__main__':
    main()

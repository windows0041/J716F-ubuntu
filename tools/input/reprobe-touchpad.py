#!/usr/bin/python3
"""Bounded J716F touchpad recovery, including a failed HID child probe."""
import json
import os
from pathlib import Path
import time

DEVICE = Path('/sys/bus/i2c/devices/1-0060')


def snapshot():
    result = {'present': DEVICE.exists(), 'events': [], 'hids': [], 'driver': None}
    if not result['present']:
        return result
    target = DEVICE.resolve()
    if (DEVICE / 'driver').exists():
        result['driver'] = (DEVICE / 'driver').resolve().name
    for p in Path('/sys/class/input').glob('event*'):
        if target in p.resolve().parents:
            result['events'].append({'event': p.name, 'name': (p / 'device/name').read_text().strip()})
    for p in Path('/sys/bus/hid/devices').glob('*04F3:3164.*'):
        if target in p.resolve().parents:
            result['hids'].append({'name': p.name, 'bound': (p / 'driver').exists()})
    return result


def decision(state):
    if not state['present']:
        return 'absent'
    if state['events']:
        return 'healthy'
    if state['driver'] is None:
        return 'probe'
    if (state['driver'] == 'i2c_hid_of' and state['hids']
            and all(not h['bound'] for h in state['hids'])):
        return 'rebind'
    # A binding HID driver may still be registering inputs; never reset it.
    return 'wait'


def recover(read_state, probe, unbind, pause=time.sleep):
    before = read_state()
    result = {'device': '1-0060', 'before': before, 'attempts': []}
    for attempt in range(3):
        state = read_state()
        action = decision(state)
        if action in ('healthy', 'absent'):
            result.update(status=action, after=state)
            return result
        step = {'attempt': attempt + 1, 'action': action}
        try:
            # Recheck immediately before mutations: an asynchronously recovered
            # input endpoint or a now-bound HID child must be left alone.
            if decision(read_state()) != action:
                step['action'] = 'state changed; wait'
            elif action == 'rebind':
                unbind()
                pause(0.3)
                probe()
            elif action == 'probe':
                probe()
        except OSError as e:
            step['error'] = str(e)
        result['attempts'].append(step)
        pause(1)
    after = read_state()
    result.update(after=after, status=decision(after))
    return result


def validate_target():
    assert os.geteuid() == 0
    board = Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0')
    assert b'lenovo,j716f' in board, 'J716F only'
    if DEVICE.exists():
        assert b'touchpad' in (DEVICE / 'of_node/name').read_bytes()
        assert 'hid-over-i2c' in (DEVICE / 'modalias').read_text()


def unbind():
    validate_target()
    assert decision(snapshot()) == 'rebind', 'Touchpad is no longer in the failed HID state'
    driver = (DEVICE / 'driver').resolve(strict=True)
    assert driver == Path('/sys/bus/i2c/drivers/i2c_hid_of')
    (driver / 'unbind').write_text('1-0060\n')


def probe():
    validate_target()
    assert DEVICE.exists() and not (DEVICE / 'driver').exists(), 'Transport already bound'
    Path('/sys/bus/i2c/drivers_probe').write_text('1-0060\n')


def main():
    os.umask(0o077)
    validate_target()
    # Let initial HID/module probing finish before considering a failed child.
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    if uptime < 8:
        time.sleep(8 - uptime)
    result = recover(snapshot, probe, unbind)
    result['time'] = time.time()
    folder = Path('/var/lib/j716f-input')
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    (folder / 'touchpad-last-probe.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return 0 if result['status'] in ('healthy', 'absent') else 1


if __name__ == '__main__':
    raise SystemExit(main())

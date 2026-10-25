#!/usr/bin/python3
"""Enable the individually verified speakers on this tablet's #530 kernel."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

STATE = Path('/var/lib/j716f-speakers')


def call(args):
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=5).stdout


def name(i, suffix):
    return ('' if i == 1 else f'SPK{i} ') + suffix


def get(control):
    result = call(['/usr/bin/amixer', '-c', '0', 'cget', f'name={control}'])
    match = re.search(r'^\s*: values=(.+)$', result, re.M)
    if not match:
        raise RuntimeError(f'Cannot read {control}')
    return match.group(1).strip()


def put(control, value):
    call(['/usr/bin/amixer', '-c', '0', 'cset', f'name={control}', str(value)])


def interrupted(signum, frame):
    raise SystemExit(f'Signal {signum}')


def main():
    assert os.geteuid() == 0
    assert b'lenovo,j716f' in Path('/proc/device-tree/compatible').read_bytes().split(b'\0')
    if '#530 ' not in call(['/usr/bin/uname', '-v']):
        print('Four-speaker setup skipped: kernel is not #530; base route is retained.')
        return
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    digital = [name(i, 'Digital PCM Volume') for i in range(1, 5)]
    other = [name(i, suffix) for i in range(1, 5)
             for suffix in ('Analog PCM Volume', 'PCM Source')]
    pins = [f'SPK{i} SPK Switch' for i in range(2, 5)]
    route = 'PRI_MI2S_RX Audio Mixer MultiMedia1'
    controls = digital + other + pins + [route]
    before = {control: get(control) for control in controls}
    desired = {control: '817' for control in digital}  # 0 dB digital, as tested
    for i in range(1, 5):
        desired[name(i, 'Analog PCM Volume')] = '0'  # minimum +0.5 dB
        desired[name(i, 'PCM Source')] = '0'  # direct ASP, no DSP parameter change
    desired.update({control: 'on' for control in pins + [route]})
    result = {'started': time.time(), 'before': before,
              'physical_positions': {'40': 'bottom-left', '41': 'bottom-right',
                                     '42': 'top-right', '43': 'top-left'},
              'expected_rx1_slots': {'40': 0, '41': 1, '42': 1, '43': 0}}
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    try:
        for control in digital:
            put(control, 0)
        for control in other + pins + [route] + digital:
            put(control, desired[control])
        result['after'] = {control: get(control) for control in controls}
        assert result['after'] == desired, 'Mixer verification failed'
        result['status'] = 'four outputs enabled; stereo listening confirmation pending'
    except BaseException as error:
        result['error'] = repr(error)
        failures = []
        for control in digital:
            try:
                put(control, 0)
            except Exception as restore_error:
                failures.append(f'{control}: {restore_error}')
        for control in other + pins + [route] + digital:
            try:
                put(control, before[control])
            except Exception as restore_error:
                failures.append(f'{control}: {restore_error}')
        result['restore_errors'] = failures
        result['status'] = 'failed; original settings restoration attempted'
        raise
    finally:
        result['finished'] = time.time()
        temporary = STATE / 'stereo-530-mixer.json.new'
        with temporary.open('w') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(STATE / 'stereo-530-mixer.json')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

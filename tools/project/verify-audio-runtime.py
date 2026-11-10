#!/usr/bin/env python3
"""Run an explicit J716F speaker/level test; never save microphone samples."""
import argparse
import array
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
import wave


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--playback', action='store_true')
    parser.add_argument('--capture-levels', action='store_true')
    parser.add_argument('--capture-seconds', type=int, choices=range(2, 11), default=2)
    args = parser.parse_args()
    if not (args.playback or args.capture_levels):
        parser.error('Select a test explicitly')
    if os.getuid() < 1000 or b'lenovo,j716f' not in Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0'):
        parser.error('Run as the tablet desktop user')
    rate = 48000
    failed = False
    if args.playback:
        samples = array.array('h')
        frames = int(rate * .65)
        for repeat in range(3):
            for channel in (0, 1):
                for i in range(frames):
                    envelope = min(1, i / 240, (frames - i) / 240)
                    value = int(4100 * envelope * math.sin(2 * math.pi * 660 * i / rate))
                    samples.extend((value, 0) if channel == 0 else (0, value))
                samples.extend([0] * (int(rate * .2) * 2))
        fd, filename = tempfile.mkstemp(prefix='j716f-test-', suffix='.wav', dir='/run/user/' + str(os.getuid()))
        os.close(fd)
        try:
            with wave.open(filename, 'wb') as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes(samples.tobytes())
            result = subprocess.run(['pw-play', filename], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12)
            print('PLAYBACK_EXIT', result.returncode, result.stderr.decode(errors='replace'), flush=True)
            failed |= result.returncode != 0
        finally:
            Path(filename).unlink()
    if args.capture_levels:
        command = ['pw-record', '--raw', '--target=alsa_input.platform-sound.HiFi__Mic__source',
                   '--rate=48000', '--channels=2', '--format=s16',
                   '--sample-count=' + str(rate * args.capture_seconds), '-']
        started = time.monotonic()
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=args.capture_seconds + 6)
        except subprocess.TimeoutExpired as error:
            print('CAPTURE_TIMEOUT', 'PARTIAL_BYTES', len(error.stdout or b''),
                  'DIAGNOSTIC', (error.stderr or b'').decode(errors='replace'), flush=True)
            return 1
        print('CAPTURE_EXIT', result.returncode, 'BYTES', len(result.stdout),
              'DIAGNOSTIC', result.stderr.decode(errors='replace'), flush=True)
        samples = array.array('h')
        samples.frombytes(result.stdout[:len(result.stdout) // 2 * 2])
        for channel in (0, 1):
            part = samples[channel::2]
            peak = max(map(abs, part), default=0)
            rms = math.sqrt(sum(x * x for x in part) / len(part)) if part else 0
            print('CHANNEL', channel, 'SAMPLES', len(part), 'PEAK', peak, 'RMS', round(rms, 3), flush=True)
        elapsed = time.monotonic() - started
        complete = len(result.stdout) == rate * args.capture_seconds * 2 * 2
        # PipeWire 1.6.8 quits at sample_limit without setting data.drained;
        # pw-cat main() therefore returns EXIT_FAILURE even for a complete capture.
        # https://github.com/PipeWire/pipewire/blob/1.6.8/src/tools/pw-cat.c
        version = subprocess.run(['pw-record', '--version'], capture_output=True,
                                 text=True, timeout=3).stdout
        known_limit_exit = (result.returncode == 1 and not result.stderr.strip()
                            and 'libpipewire 1.6.8' in version and complete)
        if known_limit_exit:
            print('KNOWN_PIPEWIRE_1_6_8_SAMPLE_LIMIT_EXIT', flush=True)
        windows_nonzero = True
        for second in range(args.capture_seconds):
            part = samples[second * rate * 2:(second + 1) * rate * 2]
            peak = max(map(abs, part), default=0)
            print('SECOND', second, 'PEAK', peak, flush=True)
            windows_nonzero &= peak > 0
        print('CAPTURE_COMPLETE', complete, 'ELAPSED', round(elapsed, 3), flush=True)
        failed |= (not (result.returncode == 0 or known_limit_exit) or not complete
                   or elapsed < args.capture_seconds - .2 or not windows_nonzero)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())

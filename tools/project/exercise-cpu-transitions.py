#!/usr/bin/env python3
"""Bounded CPU wake/load/idle exercise for J716F freeze diagnosis, no disk load."""
import argparse
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import time


def worker(cpu, deadline, pause, stop, counts, block_kib, verify_memory):
    os.sched_setaffinity(0, {cpu})
    block = bytes([cpu + 1]) * (block_kib * 1024)
    if verify_memory:
        patterns = [bytes([value ^ cpu]) * len(block) for value in (0x55, 0xaa)]
        expected = [hashlib.sha256(pattern).digest() for pattern in patterns]
        block = bytearray(block)
    count = 0
    while time.monotonic() < deadline and not stop.is_set():
        phase = (time.monotonic() + cpu * .09) % 5
        if pause.is_set() or phase >= 2:
            time.sleep(.05)
            continue
        chunk_end = time.monotonic() + .05
        while time.monotonic() < chunk_end:
            if verify_memory:
                pattern = count % len(patterns)
                block[:] = patterns[pattern]
                if hashlib.sha256(block).digest() != expected[pattern]:
                    raise RuntimeError('Memory verification failed on CPU ' + str(cpu))
            else:
                hashlib.sha256(block).digest()
            count += 1
        counts[cpu] = count


def temperatures():
    values = {}
    for folder in Path('/sys/class/thermal').glob('thermal_zone*'):
        try:
            name = (folder/'type').read_text().strip()
            if 'cpu' in name.lower():
                value = int((folder/'temp').read_text())
                if 0 < value < 130000:
                    values[name] = value
        except OSError:
            pass
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=1200)
    parser.add_argument('--block-kib', type=int, choices=(64, 8192), default=64)
    parser.add_argument('--verify-memory', action='store_true',
                        help='Write alternating patterns and verify every SHA-256 readback')
    args = parser.parse_args()
    if not 30 <= args.seconds <= 3600 or os.getuid() < 1000:
        parser.error('Run as a desktop user for 30..3600 seconds')
    if b'lenovo,j716f' not in Path('/proc/device-tree/compatible').read_bytes().split(b'\0'):
        parser.error('Wrong board')
    if set(os.sched_getaffinity(0)) != set(range(8)):
        parser.error('Require all eight expected CPUs available')
    if len(temperatures()) < 4:
        parser.error('CPU thermal telemetry unavailable')
    context = mp.get_context('fork')
    pause, stop = context.Event(), context.Event()
    counts = context.Array('Q', 8, lock=False)
    started = time.monotonic()
    deadline = started + args.seconds
    workers = [context.Process(target=worker, args=(cpu, deadline, pause, stop, counts, args.block_kib, args.verify_memory)) for cpu in range(8)]
    for process in workers:
        process.start()
    max_temp, paused_seconds, next_report = 0, 0, started
    try:
        while time.monotonic() < deadline:
            temps = temperatures()
            if len(temps) < 4:
                raise RuntimeError('Lost thermal telemetry; stopping exercise')
            hottest = max(temps.values())
            max_temp = max(max_temp, hottest)
            if hottest >= 75000:
                pause.set()
            elif hottest < 68000:
                pause.clear()
            paused_seconds += int(pause.is_set())
            if any(process.exitcode not in (None, 0) for process in workers):
                raise RuntimeError('A worker failed')
            if time.monotonic() >= next_report:
                print(json.dumps({'elapsed': round(time.monotonic()-started, 1),
                                  'temperature_max_mC': hottest,
                                  'thermal_pause': pause.is_set(), 'block_kib': args.block_kib, 'hashes_per_cpu': list(counts)}), flush=True)
                next_report += 60
            time.sleep(1)
    finally:
        stop.set()
        for process in workers:
            process.join(timeout=2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
    if any(process.exitcode != 0 for process in workers):
        raise RuntimeError('A worker failed or did not stop normally')
    if not all(counts):
        raise RuntimeError('Not all workers exercised their CPU')
    print(json.dumps({'completed': True, 'elapsed': round(time.monotonic()-started, 1),
                      'peak_temperature_mC': max_temp, 'thermal_pause_seconds': paused_seconds,
                      'block_kib': args.block_kib,
                      'memory_patterns_verified': args.verify_memory,
                      'hashes_per_cpu': list(counts)}), flush=True)


if __name__ == '__main__':
    main()

#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Conservatively request locked suspend after an abrupt ALS cover event."""
import argparse
import importlib.machinery
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import signal
import subprocess
import time


class CoverDetector:
    def __init__(self, close_lux=3.0, open_lux=20.0, open_seconds=4.0,
                 dark_seconds=4.0, transition_seconds=5.0, drop_ratio=0.1,
                 resume_grace=20.0, maximum_gap=2.0):
        self.close_lux, self.open_lux = close_lux, open_lux
        self.open_seconds, self.dark_seconds = open_seconds, dark_seconds
        self.transition_seconds, self.drop_ratio = transition_seconds, drop_ratio
        self.resume_grace, self.maximum_gap = resume_grace, maximum_gap
        self.reset(0)

    def reset(self, now, grace=0):
        self.cooldown_until = now + grace
        self.last_time = self.open_since = self.last_bright = self.dark_since = None
        self.reference = None
        self.armed = False

    def sample(self, now, lux):
        if not math.isfinite(lux) or lux < 0:
            self.reset(now, max(0, self.cooldown_until - now))
            return False
        if self.last_time is not None and (now < self.last_time or now - self.last_time > self.maximum_gap):
            self.reset(now, max(0, self.cooldown_until - now))
        self.last_time = now
        if now < self.cooldown_until:
            return False
        if lux >= self.open_lux:
            if self.open_since is None:
                self.open_since = now
            self.reference, self.last_bright, self.dark_since = lux, now, None
            if now - self.open_since >= self.open_seconds:
                self.armed = True
            return False
        self.open_since = None
        if lux > self.close_lux:
            self.dark_since = None
            if self.last_bright is None or now - self.last_bright > self.transition_seconds:
                self.armed = False
            return False
        if self.dark_since is None:
            if (not self.armed or self.last_bright is None or
                    now - self.last_bright > self.transition_seconds or
                    lux > self.reference * self.drop_ratio):
                return False
            self.dark_since = now
        if now - self.dark_since < self.dark_seconds:
            return False
        self.reset(now, self.resume_grace)
        return True


def request_suspend(desktop, observe=False):
    account = desktop.account()
    if observe:
        logging.info('Observed an ALS cover event; suspend is disabled')
        return
    # Lock is idempotent. An already locked or blank display must still sleep.
    desktop.lock(account)
    subprocess.run(['/usr/bin/systemctl', '--no-block', 'suspend'],
                   check=True, timeout=10)
    logging.info('ALS cover event requested locked suspend')


def run(args):
    from gi.repository import Gio, GLib, GLibUnix

    if os.geteuid() != 0:
        raise SystemExit('This system service must run as root')
    config = json.loads(Path(args.config).read_text())
    detector = CoverDetector(**config)
    loader = importlib.machinery.SourceFileLoader('j716f_desktop_power', '/usr/local/sbin/j716f-power-key')
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    desktop = module.Desktop()
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    proxy = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
        'net.hadess.SensorProxy', '/net/hadess/SensorProxy', 'net.hadess.SensorProxy', None)
    state = {'owner': None, 'claimed': False, 'sleeping': False,
             'next_claim': 0, 'requests': 0, 'last_warning': 0,
             'sleep_started': None, 'last_sleep_interval': None, 'resumes': 0}
    status = Path(args.state_file)
    status.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    loop = GLib.MainLoop()
    detector.reset(time.monotonic(), 5)

    def sleep_changed(connection, sender, path, interface, name, parameters, _user_data=None):
        state['sleeping'] = parameters.unpack()[0]
        boottime = time.clock_gettime(time.CLOCK_BOOTTIME)
        if state['sleeping']:
            state['sleep_started'] = boottime
        elif state['sleep_started'] is not None:
            state['last_sleep_interval'] = round(boottime - state['sleep_started'], 2)
            state['sleep_started'] = None
            state['resumes'] += 1
            logging.info('Resumed after a %.2f-second sleep cycle', state['last_sleep_interval'])
        detector.reset(time.monotonic(), detector.resume_grace)

    bus.signal_subscribe('org.freedesktop.login1', 'org.freedesktop.login1.Manager',
        'PrepareForSleep', '/org/freedesktop/login1', None,
        Gio.DBusSignalFlags.NONE, sleep_changed)

    def tick():
        now = time.monotonic()
        lux = None
        ready = False
        try:
            owner = proxy.get_name_owner()
            if owner != state['owner']:
                state.update(owner=owner, claimed=False, next_claim=0)
                detector.reset(now, max(5, detector.cooldown_until - now))
            if owner and not state['claimed'] and now >= state['next_claim']:
                state['next_claim'] = now + 10
                proxy.call_sync('ClaimLight', None, Gio.DBusCallFlags.NONE, 10000, None)
                state['claimed'] = True
            has = proxy.get_cached_property('HasAmbientLight')
            unit = proxy.get_cached_property('LightLevelUnit')
            value = proxy.get_cached_property('LightLevel')
            ready = bool(owner and state['claimed'] and has is not None and has.unpack()
                         and unit is not None and unit.unpack() == 'lux' and value is not None)
            if ready and not state['sleeping']:
                lux = float(value.unpack())
                if detector.sample(now, lux):
                    request_suspend(desktop, args.observe)
                    state['requests'] += 1
            elif not state['sleeping']:
                detector.reset(now, max(5, detector.cooldown_until - now))
        except (GLib.Error, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            detector.reset(now, detector.resume_grace)
            if now - state['last_warning'] >= 30:
                logging.warning('ALS cover handling unavailable: %s', error)
                state['last_warning'] = now
        result = {'lux': lux, 'ready': ready, 'armed': detector.armed,
                  'dark_candidate': detector.dark_since is not None,
                  'sleeping': state['sleeping'], 'requests': state['requests'],
                  'observe_only': args.observe, 'resumes': state['resumes'],
                  'last_sleep_interval': state['last_sleep_interval']}
        temporary = status.with_suffix('.tmp')
        temporary.write_text(json.dumps(result) + '\n')
        temporary.chmod(0o600)
        os.replace(temporary, status)
        return True

    GLib.timeout_add(500, tick)
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, sig, lambda *unused: (loop.quit(), False)[1])
    try:
        loop.run()
    finally:
        if state['claimed'] and proxy.get_name_owner() == state['owner']:
            try:
                proxy.call_sync('ReleaseLight', None, Gio.DBusCallFlags.NONE, 3000, None)
            except GLib.Error:
                pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/etc/j716f-als-lid.json')
    parser.add_argument('--state-file', default='/run/j716f-als-lid/status.json')
    parser.add_argument('--observe', action='store_true', help='Observe without locking or suspending')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    run(args)

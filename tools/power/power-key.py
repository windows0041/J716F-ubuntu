#!/usr/bin/python3
"""J716F power-button timing for the graphical session only.

SPDX-License-Identifier: GPL-2.0-only
"""
import fcntl
import logging
import os
from pathlib import Path
import pwd
import re
import select
import struct
import subprocess
import time

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

LOG = logging.getLogger('j716f-power-key')
EVENT = struct.Struct('@llHHi')
EV_KEY, KEY_POWER, EVIOCGRAB = 1, 116, 0x40044590
EVIOCSCLOCKID = 0x400445a0


class KeyState:
    """Distinguish release-to-suspend from a continuous shutdown hold."""
    def __init__(self, sleep_after=1.0, off_after=4.5):
        self.sleep_after, self.off_after = sleep_after, off_after
        self.started = None
        self.waking = self.fired = False

    def press(self, now, dark=False):
        if self.started is not None:
            return None
        self.started, self.waking, self.fired = now, dark, False
        return 'wake' if dark else None

    def hold(self, now):
        if self.started is not None and not self.fired and now - self.started >= self.off_after:
            self.fired = True
            return 'poweroff'
        return None

    def release(self, now):
        if self.started is None:
            return None
        elapsed = now - self.started
        self.started = None
        if self.fired:
            return None
        if elapsed >= self.off_after:
            return 'poweroff'
        if not self.waking and elapsed >= self.sleep_after:
            return 'suspend'
        return None


class Desktop:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

    def properties(self, path, interface):
        reply = self.bus.call_sync(
            'org.freedesktop.login1', path, 'org.freedesktop.DBus.Properties',
            'GetAll', GLib.Variant('(s)', (interface,)), None,
            Gio.DBusCallFlags.NONE, 5000, None)
        return reply.unpack()[0]

    def account(self):
        seat = self.properties('/org/freedesktop/login1/seat/seat0',
                               'org.freedesktop.login1.Seat')
        _, path = seat['ActiveSession']
        session = self.properties(path, 'org.freedesktop.login1.Session')
        if session['Type'] not in ('wayland', 'x11') or not session['Active'] or session['Remote']:
            raise RuntimeError('No active local graphical session')
        return pwd.getpwuid(session['User'][0])

    def call(self, account, destination, path, method, *args):
        runtime = '/run/user/' + str(account.pw_uid)
        result = subprocess.run([
            '/usr/sbin/runuser', '-u', account.pw_name, '--', '/usr/bin/env',
            'XDG_RUNTIME_DIR=' + runtime,
            'DBUS_SESSION_BUS_ADDRESS=unix:path=' + runtime + '/bus',
            '/usr/bin/gdbus', 'call', '--session', '--dest', destination,
            '--object-path', path, '--method', method, *args],
            capture_output=True, text=True, timeout=6)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return result.stdout.strip()

    def dark(self, account):
        value = self.call(account, 'org.gnome.Mutter.DisplayConfig',
                          '/org/gnome/Mutter/DisplayConfig',
                          'org.freedesktop.DBus.Properties.Get',
                          'org.gnome.Mutter.DisplayConfig', 'PowerSaveMode')
        match = re.search(r'<(?:int32 )?(-?\d+)>', value)
        if match is None:
            raise RuntimeError('Unknown display power state')
        return int(match[1]) > 0

    def wake(self, account):
        # Restoring display power does not deactivate or unlock the lock screen.
        self.call(account, 'org.gnome.Mutter.DisplayConfig',
                  '/org/gnome/Mutter/DisplayConfig',
                  'org.freedesktop.DBus.Properties.Set',
                  'org.gnome.Mutter.DisplayConfig', 'PowerSaveMode', '<int32 0>')

    def lock(self, account):
        self.call(account, 'org.gnome.ScreenSaver', '/org/gnome/ScreenSaver',
                  'org.gnome.ScreenSaver.Lock')
        for _ in range(20):
            result = self.call(account, 'org.gnome.ScreenSaver', '/org/gnome/ScreenSaver',
                               'org.gnome.ScreenSaver.GetActive')
            if result == '(true,)':
                return
            time.sleep(0.1)
        raise RuntimeError('Screen did not lock; refusing to suspend')

    def action(self, action):
        if not action:
            return
        LOG.info('Power button: %s', action)
        if action == 'poweroff':
            subprocess.run(['/usr/bin/systemctl', '--no-block', 'poweroff'],
                           check=True, timeout=10)
            return
        account = self.account()
        if action == 'wake':
            self.wake(account)
        elif action == 'suspend':
            self.lock(account)
            subprocess.run(['/usr/bin/systemctl', '--no-block', 'suspend'],
                           check=True, timeout=10)


def power_device():
    for path in sorted(Path('/sys/class/input').glob('event*')):
        try:
            name = (path / 'device/name').read_text().strip()
        except FileNotFoundError:
            continue
        if name in ('pm8941_pwrkey', 'pmic_pwrkey'):
            return Path('/dev/input') / path.name
    raise RuntimeError('Primary PMIC power button is unavailable')


def monitor(desktop):
    state = KeyState()
    with power_device().open('rb', buffering=0) as device:
        # Use event timestamps so a slow desktop D-Bus reply cannot turn an
        # already released short press into a shutdown-length press.
        fcntl.ioctl(device, EVIOCSCLOCKID, struct.pack('@i', time.CLOCK_MONOTONIC))
        fcntl.ioctl(device, EVIOCGRAB, 1)
        LOG.info('Monitoring primary PMIC power button')
        try:
            while True:
                ready, _, _ = select.select([device], [], [], 0.05)
                action = None
                if ready:
                    data = device.read(EVENT.size)
                    if len(data) != EVENT.size:
                        raise RuntimeError('Power button disconnected')
                    seconds, micros, kind, code, value = EVENT.unpack(data)
                    if kind == 0 and code == 3:  # SYN_DROPPED
                        state = KeyState()
                        LOG.warning('Lost power-button events; cancelled pending action')
                    if kind == EV_KEY and code == KEY_POWER:
                        now = seconds + micros / 1000000
                        LOG.debug('Key value=%d time=%.3f pending=%s',
                                  value, now, state.started)
                        if value == 1 and state.started is None:
                            account = desktop.account()
                            dark = desktop.dark(account)
                            LOG.debug('Display dark=%s', dark)
                            action = state.press(now, dark)
                        elif value == 0:
                            action = state.release(now)
                # Drain any queued release before considering the hold timer.
                if action is None and not select.select([device], [], [], 0)[0]:
                    action = state.hold(time.monotonic())
                if action:
                    try:
                        desktop.action(action)
                    except (RuntimeError, subprocess.SubprocessError, GLib.Error) as error:
                        LOG.error('Action failed: %s', error)
        finally:
            fcntl.ioctl(device, EVIOCGRAB, 0)


def main():
    level = logging.DEBUG if os.environ.get('J716F_POWER_KEY_TRACE') == '1' else logging.INFO
    logging.basicConfig(level=level, format='%(message)s')
    monitor(Desktop())


if __name__ == '__main__':
    main()

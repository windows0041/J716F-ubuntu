#!/usr/bin/python3
"""Check timing boundaries without reading a device or invoking power actions."""
import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('power_key', Path(__file__).with_name('power-key.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TimingTests(unittest.TestCase):
    def test_short_tap_does_not_suspend(self):
        key = module.KeyState()
        key.press(10)
        self.assertIsNone(key.release(10.2))

    def test_release_at_two_seconds_suspends(self):
        key = module.KeyState()
        key.press(10)
        self.assertEqual(key.release(12), 'suspend')

    def test_one_second_is_the_suspend_boundary(self):
        key = module.KeyState()
        key.press(10)
        self.assertIsNone(key.release(10.999))
        key.press(20)
        self.assertEqual(key.release(21), 'suspend')

    def test_typical_measured_press_suspends(self):
        key = module.KeyState()
        key.press(10)
        self.assertEqual(key.release(11.187), 'suspend')

    def test_holding_past_suspend_threshold_does_not_suspend(self):
        key = module.KeyState()
        key.press(10)
        self.assertIsNone(key.hold(12))
        self.assertIsNone(key.hold(14.49))
        self.assertEqual(key.hold(14.5), 'poweroff')
        self.assertIsNone(key.hold(16))
        self.assertIsNone(key.release(16))

    def test_release_at_shutdown_threshold_catches_poll_race(self):
        key = module.KeyState()
        key.press(10)
        self.assertEqual(key.release(14.5), 'poweroff')

    def test_wake_press_is_not_a_new_suspend_request(self):
        key = module.KeyState()
        self.assertEqual(key.press(10, dark=True), 'wake')
        self.assertIsNone(key.release(12))
        key.press(13)
        self.assertEqual(key.release(15), 'suspend')

    def test_duplicate_press_does_not_reset_hold_time(self):
        key = module.KeyState()
        key.press(10)
        self.assertIsNone(key.press(13))
        self.assertEqual(key.hold(14.5), 'poweroff')

    def test_stray_release_is_ignored(self):
        self.assertIsNone(module.KeyState().release(10))

    def test_previous_release_does_not_leave_a_shutdown_deadline(self):
        key = module.KeyState()
        key.press(10)
        key.release(12)
        self.assertIsNone(key.hold(100))


class LockTests(unittest.TestCase):
    def desktop(self, locked):
        desktop = module.Desktop.__new__(module.Desktop)
        desktop.is_locked = Mock(side_effect=locked)
        desktop.call = Mock(return_value='()')
        return desktop

    def test_already_locked_does_not_repeat_hanging_lock_call(self):
        desktop = self.desktop([True])
        account = SimpleNamespace(pw_uid=1001)
        desktop.lock(account)
        desktop.call.assert_not_called()

    def test_unlocked_session_is_locked_before_success(self):
        desktop = self.desktop([False, False, True])
        account = SimpleNamespace(pw_uid=1001)
        with patch.object(module.time, 'sleep'):
            desktop.lock(account)
        desktop.call.assert_called_once_with(account, 'org.gnome.ScreenSaver',
            '/org/gnome/ScreenSaver', 'org.gnome.ScreenSaver.Lock')

    def test_failed_lock_is_not_reported_as_success(self):
        desktop = self.desktop([False] * 21)
        with patch.object(module.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                desktop.lock(SimpleNamespace(pw_uid=1001))


if __name__ == '__main__':
    unittest.main()

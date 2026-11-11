#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify cover timing without sensors, D-Bus, locks or power actions."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('als_lid', Path(__file__).with_name('als-lid.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CoverTests(unittest.TestCase):
    def setUp(self):
        self.detector = module.CoverDetector()

    def arm(self, start=0):
        for t in range(start, start + 5):
            self.assertFalse(self.detector.sample(t, 320))
        self.assertTrue(self.detector.armed)

    def test_normal_cover_requires_four_seconds(self):
        self.arm()
        for t in range(5, 9):
            self.assertFalse(self.detector.sample(t, 1))
        self.assertTrue(self.detector.sample(9, 1))

    def test_starting_in_darkness_never_arms(self):
        self.assertFalse(any(self.detector.sample(t, 1) for t in range(60)))

    def test_zero_lux_after_open_is_a_valid_cover(self):
        self.arm()
        self.assertEqual(sum(self.detector.sample(t, 0) for t in range(5, 10)), 1)

    def test_dim_room_never_arms(self):
        self.assertFalse(any(self.detector.sample(t, 8) for t in range(60)))
        self.assertFalse(any(self.detector.sample(t, 1) for t in range(60, 70)))

    def test_short_occlusion_is_cancelled(self):
        self.arm()
        for t in (5, 6, 7):
            self.assertFalse(self.detector.sample(t, 1))
        self.assertFalse(self.detector.sample(8, 300))
        self.assertIsNone(self.detector.dark_since)

    def test_gradual_dimming_is_ignored(self):
        self.arm()
        for t in range(5, 15):
            self.assertFalse(self.detector.sample(t, 10))
        self.assertFalse(any(self.detector.sample(t, 1) for t in range(15, 30)))

    def test_reopening_resets_the_dark_hold(self):
        self.arm()
        for t in (5, 6, 7):
            self.detector.sample(t, 1)
        self.detector.sample(8, 100)
        for t in (9, 10, 11, 12):
            self.assertFalse(self.detector.sample(t, 1))
        self.assertTrue(self.detector.sample(13, 1))

    def test_sample_gap_cancels_pending_cover(self):
        self.arm()
        self.detector.sample(5, 1)
        self.assertFalse(self.detector.sample(10, 1))
        self.assertFalse(self.detector.armed)

    def test_invalid_sensor_data_cancels_pending_cover(self):
        for value in (float('nan'), float('inf'), -1):
            with self.subTest(value=value):
                self.detector = module.CoverDetector()
                self.arm()
                self.detector.sample(5, 1)
                self.assertFalse(self.detector.sample(6, value))
                self.assertFalse(self.detector.armed)

    def test_no_repeat_suspend_while_cover_stays_closed(self):
        self.arm()
        requests = sum(self.detector.sample(t, 1) for t in range(5, 120))
        self.assertEqual(requests, 1)

    def test_resume_grace_survives_invalid_data_and_gaps(self):
        self.detector.reset(0, 20)
        self.detector.sample(1, float('nan'))
        self.detector.sample(6, 320)
        self.assertEqual(self.detector.cooldown_until, 20)
        for t in range(7, 20):
            self.assertFalse(self.detector.sample(t, 320))
            self.assertFalse(self.detector.armed)

    def test_second_cover_needs_a_new_open_baseline(self):
        self.arm()
        self.assertEqual(sum(self.detector.sample(t, 1) for t in range(5, 10)), 1)
        for t in range(10, 30):
            self.assertFalse(self.detector.sample(t, 1))
        self.arm(30)
        self.assertEqual(sum(self.detector.sample(t, 1) for t in range(35, 40)), 1)


class SuspendTests(unittest.TestCase):
    def test_locked_blank_session_still_suspends(self):
        desktop = Mock()
        desktop.account.return_value = 'active-local-session'
        desktop.dark.return_value = True
        with patch.object(module.subprocess, 'run') as command:
            module.request_suspend(desktop)
        desktop.dark.assert_not_called()
        desktop.lock.assert_called_once_with('active-local-session')
        command.assert_called_once_with(['/usr/bin/systemctl', '--no-block', 'suspend'],
                                        check=True, timeout=10)

    def test_failed_lock_does_not_suspend(self):
        desktop = Mock()
        desktop.lock.side_effect = RuntimeError('lock failed')
        with patch.object(module.subprocess, 'run') as command:
            with self.assertRaises(RuntimeError):
                module.request_suspend(desktop)
        command.assert_not_called()

    def test_observe_mode_does_not_lock_or_suspend(self):
        desktop = Mock()
        with patch.object(module.subprocess, 'run') as command:
            module.request_suspend(desktop, observe=True)
        desktop.lock.assert_not_called()
        command.assert_not_called()

    def test_no_local_session_does_not_suspend(self):
        desktop = Mock()
        desktop.account.side_effect = RuntimeError('no local session')
        with patch.object(module.subprocess, 'run') as command:
            with self.assertRaises(RuntimeError):
                module.request_suspend(desktop)
        command.assert_not_called()


if __name__ == '__main__':
    unittest.main()

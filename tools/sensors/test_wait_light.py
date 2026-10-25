#!/usr/bin/python3
"""Exercise ALS startup retries without invoking a sensor or waiting in real time."""
import contextlib
import io
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name('wait-light.py')
SENSOR = "data-type 'ambient_light': 0123456789abcdef0123456789abcdef\n"
COMMAND = ['/usr/bin/python3', '/opt/j716f-sensors/libexec/ssc-discover.py',
           'ambient_light']


class WaitLightTests(unittest.TestCase):
    def execute(self, outcomes):
        output = io.StringIO()
        with patch('subprocess.run', side_effect=outcomes) as run, \
                patch('time.sleep') as sleep, contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exited:
                runpy.run_path(str(SCRIPT), run_name='__main__')
        return exited.exception.code, output.getvalue(), run, sleep

    def test_slow_first_discovery_can_recover_without_restarting_rpc(self):
        code, output, run, sleep = self.execute([
            subprocess.TimeoutExpired(COMMAND, 30),
            subprocess.CompletedProcess(COMMAND, 0, SENSOR),
        ])
        self.assertEqual(code, 0)
        self.assertIn('timed out (attempt 1/3)', output)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_all_timeouts_stop_after_three_attempts_within_unit_budget(self):
        code, output, run, sleep = self.execute([
            subprocess.TimeoutExpired(COMMAND, 30) for _ in range(3)
        ])
        self.assertEqual(code, 'SLPI did not publish an ambient-light sensor')
        self.assertEqual(run.call_count, 3)
        self.assertEqual(output.count('timed out (attempt'), 3)
        for call in run.call_args_list:
            self.assertEqual(call.args, (COMMAND,))
            self.assertEqual(call.kwargs['timeout'], 30)
        elapsed_budget = sum(call.kwargs['timeout'] for call in run.call_args_list)
        elapsed_budget += sum(call.args[0] for call in sleep.call_args_list)
        self.assertEqual(elapsed_budget, 94)
        self.assertLess(elapsed_budget, 100)

    def test_failed_command_with_sensor_text_is_not_accepted(self):
        code, _, run, sleep = self.execute([
            subprocess.CompletedProcess(COMMAND, 1, SENSOR),
            subprocess.CompletedProcess(COMMAND, 0, SENSOR),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_missing_sensor_stops_after_three_attempts(self):
        code, _, run, sleep = self.execute([
            subprocess.CompletedProcess(COMMAND, 0, 'No ambient-light sensor\n')
            for _ in range(3)
        ])
        self.assertEqual(code, 'SLPI did not publish an ambient-light sensor')
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_ready_sensor_exits_without_retry_or_pause(self):
        code, _, run, sleep = self.execute([
            subprocess.CompletedProcess(COMMAND, 0, SENSOR),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()

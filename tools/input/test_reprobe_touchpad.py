import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location('reprobe', Path(__file__).with_name('reprobe-touchpad.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
BROKEN = {'present': True, 'driver': 'i2c_hid_of', 'events': [],
          'hids': [{'name': '0018:04F3:3164.0002', 'bound': False}]}
HEALTHY = {'present': True, 'driver': 'i2c_hid_of', 'events': [{'event': 'event9'}],
           'hids': [{'name': '0018:04F3:3164.0003', 'bound': True}]}


class RecoveryTests(unittest.TestCase):
    def run_recovery(self, states):
        read = Mock(side_effect=states)
        probe, unbind, pause = Mock(), Mock(), Mock()
        result = module.recover(read, probe, unbind, pause)
        return result, probe, unbind, pause

    def test_bound_transport_failed_hid_recovers_once(self):
        result, probe, unbind, _ = self.run_recovery([BROKEN, BROKEN, BROKEN, HEALTHY])
        self.assertEqual(result['status'], 'healthy')
        probe.assert_called_once()
        unbind.assert_called_once()

    def test_working_input_is_never_unbound(self):
        result, probe, unbind, pause = self.run_recovery([HEALTHY, HEALTHY])
        self.assertEqual(result['status'], 'healthy')
        probe.assert_not_called()
        unbind.assert_not_called()
        pause.assert_not_called()

    def test_async_recovery_before_mutation_is_preserved(self):
        _, probe, unbind, _ = self.run_recovery([BROKEN, BROKEN, HEALTHY, HEALTHY])
        probe.assert_not_called()
        unbind.assert_not_called()

    def test_active_hid_without_inputs_is_not_reset(self):
        pending = dict(BROKEN, hids=[{'name': '0018:04F3:3164.0002', 'bound': True}])
        result, probe, unbind, _ = self.run_recovery([pending] * 8)
        self.assertEqual(result['status'], 'wait')
        self.assertEqual(len(result['attempts']), 3)
        probe.assert_not_called()
        unbind.assert_not_called()

    def test_unbound_device_can_still_use_original_probe_path(self):
        missing = dict(BROKEN, driver=None, hids=[])
        result, probe, unbind, _ = self.run_recovery([missing, missing, missing, HEALTHY])
        self.assertEqual(result['status'], 'healthy')
        probe.assert_called_once()
        unbind.assert_not_called()

    def test_persistent_failure_stops_after_three_attempts(self):
        result, probe, unbind, _ = self.run_recovery([BROKEN] * 8)
        self.assertEqual(len(result['attempts']), 3)
        self.assertEqual(probe.call_count, 3)
        self.assertEqual(unbind.call_count, 3)
        self.assertEqual(result['status'], 'rebind')


if __name__ == '__main__':
    unittest.main()

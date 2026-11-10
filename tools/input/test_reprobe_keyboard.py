import importlib.util,unittest
from pathlib import Path
from unittest.mock import Mock
s=importlib.util.spec_from_file_location('kbd',Path(__file__).with_name('reprobe-keyboard.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
BAD={'present':True,'driver':'i2c_hid_of','events':[],'hids':[{'bound':True,'descriptor_sha256':'bad'}]}
GOOD=dict(BAD,events=[{'event':'event6','name':'Keyboard'}])
class RecoveryTests(unittest.TestCase):
 def run_case(self,states):
  read=Mock(side_effect=states);unbind=Mock();probe=Mock();pause=Mock();return m.recover(read,unbind,probe,pause),unbind,probe
 def test_running_keyboard_is_never_reset(self):
  r,u,p=self.run_case([GOOD,GOOD]);self.assertEqual(r['status'],'healthy');u.assert_not_called();p.assert_not_called()
 def test_corrupt_bound_hid_without_inputs_is_retried(self):
  r,u,p=self.run_case([BAD,BAD,BAD,GOOD]);self.assertEqual(r['status'],'healthy');u.assert_called_once();p.assert_called_once()
 def test_async_registration_prevents_reset(self):
  r,u,p=self.run_case([BAD,BAD,GOOD,GOOD]);self.assertEqual(r['status'],'healthy');u.assert_not_called();p.assert_not_called()
 def test_detached_keyboard_does_not_trigger_reset(self):
  absent=dict(BAD,present=False);r,u,p=self.run_case([absent,absent]);self.assertEqual(r['status'],'absent');u.assert_not_called();p.assert_not_called()
 def test_persistent_failure_is_bounded(self):
  r,u,p=self.run_case([BAD]*8);self.assertEqual(len(r['attempts']),3);self.assertEqual(u.call_count,3);self.assertEqual(p.call_count,3)
 def test_unknown_driver_is_not_unbound(self):
  unknown=dict(BAD,driver='unexpected');r,u,p=self.run_case([unknown]*8);self.assertEqual(r['status'],'wait');u.assert_not_called();p.assert_not_called()
if __name__=='__main__':unittest.main()

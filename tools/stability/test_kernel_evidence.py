#!/usr/bin/env python3
"""Exercise fault escalation, restart suppression and boot retention off-device."""
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("evidence", Path(__file__).with_name("kernel-evidence.py"))
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)
BOOT = "11111111-1111-1111-1111-111111111111"


class Follow:
    def __init__(self, data):
        self.stdout = io.BytesIO(data)

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state"
        self.original_text = Path.read_text
        self.original_bytes = Path.read_bytes
        self.original_glob = Path.glob

    def run_collector(self, data):
        def read_text(path, *args, **kwargs):
            if str(path) == "/proc/sys/kernel/random/boot_id":
                return BOOT
            return self.original_text(path, *args, **kwargs)

        def read_bytes(path, *args, **kwargs):
            if str(path) == "/proc/device-tree/compatible":
                return b"lenovo,j716f\0qcom,sm8250\0"
            return self.original_bytes(path, *args, **kwargs)

        def glob(path, pattern):
            return iter(()) if str(path) == "/sys/fs/pstore" else self.original_glob(path, pattern)

        with patch.object(evidence, "STATE", self.state), \
                patch.object(Path, "read_text", read_text), \
                patch.object(Path, "read_bytes", read_bytes), \
                patch.object(Path, "glob", glob), \
                patch.object(evidence, "command", return_value="kernel only"), \
                patch.object(evidence, "snapshot", return_value={"test": True}) as snapshot, \
                patch.object(evidence.subprocess, "Popen", return_value=Follow(data)):
            with self.assertRaisesRegex(SystemExit, "follower stopped"):
                evidence.main()
            return snapshot.call_count

    def test_display_timeout_does_not_hide_later_critical_fault(self):
        data = (b"[7738.94] dpu_encoder_frame_done_timeout: frame done timeout\n" * 3
                + b"[7748.96] Error sending AMC RPMH requests (-110)\n"
                + b"[7751.87] Watchdog detected hard LOCKUP on cpu 0\n" * 3)
        self.assertEqual(self.run_collector(data), 3)  # boot, display and later critical
        current = self.state / ("boot-" + BOOT)
        self.assertTrue((current / "display-fault.json").is_file())
        self.assertIn("RPMH", (current / "critical-fault.json").read_text())
        self.assertEqual(self.run_collector(data), 0)  # restarting cannot refill the archive

    def test_boot_retention_preserves_installation_backup(self):
        self.state.mkdir()
        backup = self.state / "install-before-20261023"
        backup.mkdir()
        for i in range(6):
            (self.state / ("boot-00000000-0000-0000-0000-%012d" % i)).mkdir()
        self.run_collector(b"ordinary kernel log\n")
        self.assertEqual(len(list(self.state.glob("boot-*"))), 4)
        self.assertTrue(backup.is_dir())

    def test_fault_context_is_bounded_after_long_stream(self):
        data = b"z" * 8000 + b"\n"
        data = data * 1100 + b"[4] BUG: soft lockup - CPU stuck\n"
        self.run_collector(data)
        context = self.state / ("boot-" + BOOT) / "critical-fault-context.log"
        self.assertLessEqual(context.stat().st_size, 1024 * 4096)


if __name__ == "__main__":
    unittest.main()

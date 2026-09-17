#!/usr/bin/env python3
"""No-network regression checks for the native one-shot healthcheck."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]

class KeepaliveExitCodes(unittest.TestCase):
    def check_mode(self, mode, expected):
        parent = Path(tempfile.gettempdir()).resolve()
        with tempfile.TemporaryDirectory(prefix="codex-regression-", dir=parent) as name:
            work = Path(name).resolve()
            assert work.parent == parent
            fake = work / "codex-fixture.sh"
            shutil.copyfile(ROOT / "tests/fixtures/fake-codex.sh", fake)
            fake.chmod(0o755)
            prompts = work / "prompts.txt"
            prompts.write_text("Reply with exactly: OK\n", encoding="utf-8")
            env = os.environ.copy()
            env.update({"CODEX_BIN": fake.as_posix(), "PROMPTS_FILE": prompts.as_posix(),
                        "LOG_FILE": (work / "test.log").as_posix(), "FAKE_CODEX_MODE": mode,
                        "REQUEST_TIMEOUT_SEC": "5"})
            bash = os.environ.get("BASH_BIN", "bash")
            result = subprocess.run([bash, (ROOT / "codex-healthcheck.sh").as_posix(), "--once"],
                                    env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            self.assertIn("OK (response=" if expected == 0 else "FAILED (exit=", result.stdout)
    def test_success(self):
        self.check_mode("success", 0)
    def test_failure_propagates(self):
        self.check_mode("fail", 23)
    def test_empty_response_fails(self):
        self.check_mode("empty", 1)

if __name__ == "__main__":
    unittest.main(verbosity=2)

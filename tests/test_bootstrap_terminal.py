from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "posix" and shutil.which("sh"), "requires POSIX sh")
class BootstrapTerminalTests(unittest.TestCase):
    def test_no_controlling_terminal_exits_before_installation(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap.sh"
        result = subprocess.run(
            ["sh", str(script)], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("No interactive terminal", result.stderr)
        self.assertNotIn("==> Installing", result.stdout)

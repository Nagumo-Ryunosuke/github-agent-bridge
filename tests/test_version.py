from __future__ import annotations

import re
import unittest
from pathlib import Path

from github_agent_bridge import __version__


class VersionCase(unittest.TestCase):
    def test_pyproject_and_package_versions_match(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), __version__)


if __name__ == "__main__":
    unittest.main()

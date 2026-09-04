from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from github_agent_bridge.entry import main


class EntryCase(unittest.TestCase):
    def test_root_help_mentions_skill_and_service(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            rc = main(["--help"])
        text = output.getvalue()
        self.assertEqual(0, rc)
        self.assertIn("skill", text)
        self.assertIn("service", text)
        self.assertIn("Codex App", text)

    def test_empty_argv_prints_discoverable_help(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            rc = main([])
        self.assertEqual(0, rc)
        self.assertIn("agent-bridge service install", output.getvalue())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from github_agent_bridge.core import init_repo
from github_agent_bridge.watcher import load_watcher_state, process_once


class WatcherHeartbeatCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        subprocess.check_call(["git", "init", "-b", "main"], cwd=self.repo, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "test@example.com"], cwd=self.repo)
        subprocess.check_call(["git", "config", "user.name", "Test"], cwd=self.repo)
        (self.repo / "README.md").write_text("hello\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "README.md"], cwd=self.repo)
        subprocess.check_call(["git", "commit", "-m", "init"], cwd=self.repo, stdout=subprocess.DEVNULL)
        init_repo(self.repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_long_running_poll_records_heartbeat_even_without_prs(self) -> None:
        process_once(self.repo, prs=[], record_heartbeat=True)
        state = load_watcher_state(self.repo)
        self.assertIn("last_poll_at", state)
        self.assertTrue(state["last_poll_at"])

    def test_one_shot_poll_does_not_claim_service_health(self) -> None:
        process_once(self.repo, prs=[], record_heartbeat=False)
        state = load_watcher_state(self.repo)
        self.assertNotIn("last_poll_at", state)


if __name__ == "__main__":
    unittest.main()

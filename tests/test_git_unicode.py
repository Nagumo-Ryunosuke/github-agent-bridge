from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from github_agent_bridge.git import repo_root, run_git


class GitUnicodeTests(unittest.TestCase):
    def test_repository_in_unicode_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "个人发展"
            repo.mkdir()
            run_git(repo, "init")
            self.assertEqual(repo_root(repo), repo.resolve())

    def test_unicode_commit_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            run_git(repo, "init")
            run_git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "commit", "--allow-empty", "-m", "验证中文提交")
            self.assertEqual(run_git(repo, "log", "-1", "--format=%s"), "验证中文提交")

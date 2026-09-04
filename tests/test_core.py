from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from github_agent_bridge.core import (
    create_task,
    drift_report,
    finish_task,
    get_task,
    init_repo,
    review_task,
    claim_task,
    start_task,
)
from github_agent_bridge.security import scan_text


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


class HandoffTest(unittest.TestCase):
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

    def test_task_flow(self) -> None:
        task_id = create_task(
            self.repo,
            title="Refactor sync",
            objective="Unify synchronization.",
            assigned_to="codex",
            created_by="chatgpt",
            priority="high",
            base_branch="main",
            target_branch="codex/refactor-sync",
        )
        task = get_task(self.repo, task_id)
        self.assertEqual(task["status"], "ready")
        self.assertEqual(task["base"]["commit"], git(self.repo, "rev-parse", "main"))

        claim_task(self.repo, task_id, "codex")
        start_task(self.repo, task_id)
        implementation_commit = git(self.repo, "rev-parse", "HEAD")
        handoff = finish_task(
            self.repo,
            task_id,
            implementation_commit=implementation_commit,
            branch="codex/refactor-sync",
            pr=12,
            summary="Implemented sync refactor.",
            agent="codex",
        )
        self.assertTrue(handoff.exists())
        self.assertEqual(get_task(self.repo, task_id)["status"], "review_required")

        review = review_task(
            self.repo,
            task_id,
            result="approve",
            reviewed_commit=implementation_commit,
            summary="Looks good.",
            reviewer="chatgpt",
        )
        self.assertTrue(review.exists())
        self.assertEqual(get_task(self.repo, task_id)["status"], "approved")

    def test_drift_detects_branch_advance(self) -> None:
        task_id = create_task(
            self.repo,
            title="Pinned task",
            objective="Test drift.",
            assigned_to="codex",
            created_by="chatgpt",
            priority="normal",
            base_branch="main",
            target_branch=None,
        )
        (self.repo / "later.txt").write_text("later\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "later.txt"], cwd=self.repo)
        subprocess.check_call(["git", "commit", "-m", "advance"], cwd=self.repo, stdout=subprocess.DEVNULL)
        report = drift_report(self.repo, task_id)
        self.assertTrue(report["drift"])
        self.assertIn("later.txt", report["changed_files"])

    def test_secret_scan(self) -> None:
        self.assertIn("private-key", scan_text("-----BEGIN PRIVATE KEY-----\nabc"))
        self.assertEqual([], scan_text("ordinary content"))


if __name__ == "__main__":
    unittest.main()

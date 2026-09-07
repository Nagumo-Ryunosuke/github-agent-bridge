from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from github_agent_bridge.config import configure_review, load_config
from github_agent_bridge.connect import check_destination, infer_tests, normalize_remote, prepare_repository
from github_agent_bridge.core import create_task, load_state
from github_agent_bridge.git import run_git


class ConnectCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        run_git(self.source, "init", "-b", "main")
        (self.source / "README.md").write_text("fixture\n", encoding="utf-8")
        run_git(self.source, "add", ".")
        run_git(self.source, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "base")
        self.destination = self.root / "中文 checkout"
        self.calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, command, cwd=None):
        self.calls.append(command)
        if command[:3] == ["gh", "api", "repos/owner/repo"]:
            return json.dumps({"permissions": {"push": True}})
        if command == ["gh", "api", "user"]:
            return json.dumps({"login": "fixture", "id": 123})
        if "clone" in command:
            run_git(self.root, "clone", str(self.source), command[-1])
            run_git(Path(command[-1]), "remote", "set-url", "origin", "https://github.com/owner/repo.git")
            return ""
        self.fail(f"Unexpected command: {command}")

    def prepare(self):
        with mock.patch("github_agent_bridge.connect.doctor_report", return_value={"zero_touch_ready": False, "checks": []}):
            return prepare_repository("git@github.com:owner/repo.git", directory=str(self.destination), runner=self.runner)

    def test_remote_variants(self):
        for remote in ["https://github.com/owner/repo", "https://github.com/owner/repo.git", "git@github.com:owner/repo.git", "ssh://git@github.com/owner/repo.git"]:
            with self.subTest(remote=remote):
                self.assertEqual(normalize_remote(remote), ("owner/repo", "https://github.com/owner/repo.git"))

    def test_rejects_credentials_other_hosts_and_options(self):
        for remote in ["https://token@github.com/owner/repo", "https://example.com/owner/repo", "--upload-pack=bad", "https://github.com/o/..", "https://github.com/o/r?token=x", "file:///tmp/repo", "https://github.com/o/r/tree/main"]:
            with self.subTest(remote=remote), self.assertRaises(ValueError):
                normalize_remote(remote)

    def test_clone_and_resume_preserve_work_and_tasks(self):
        first = self.prepare()
        self.assertTrue(first["repository_prepared"])
        self.assertFalse(first["zero_touch_ready"])
        self.assertFalse(first["reused"])
        self.assertTrue((self.destination / ".agents/skills/github-agent-bridge/SKILL.md").exists())
        task_id = create_task(self.destination, title="Resume", objective="Keep state", assigned_to="chatgpt",
                              created_by="codex", priority="normal", base_branch="main", target_branch="main")
        (self.destination / "README.md").write_text("unfinished work\n", encoding="utf-8")
        configure_review(self.destination, test_commands=["my-existing-test"])
        second = self.prepare()
        self.assertTrue(second["reused"])
        self.assertEqual(len([c for c in self.calls if "clone" in c]), 1)
        self.assertIn(task_id, load_state(self.destination)["tasks"])
        self.assertEqual((self.destination / "README.md").read_text(), "unfinished work\n")
        self.assertEqual(second["test_commands"], ["my-existing-test"])
        self.assertFalse(load_config(self.destination)["github"]["managed"]["write_confirmed"])

    def test_no_write_permission_does_not_clone(self):
        with self.assertRaisesRegex(RuntimeError, "write access"):
            prepare_repository("https://github.com/owner/repo", directory=str(self.destination),
                               runner=lambda command: '{"permissions":{"push":false}}')
        self.assertFalse(self.destination.exists())

    def test_existing_wrong_repository_is_untouched(self):
        self.prepare()
        with self.assertRaises(ValueError):
            check_destination(self.destination, "other/repo")
        self.assertIn("owner/repo", run_git(self.destination, "remote", "get-url", "origin"))

    def test_empty_suite_is_not_invented(self):
        self.assertEqual(infer_tests(self.source), [])

    def test_python_tests_use_worktree_source(self):
        (self.source / "src").mkdir()
        (self.source / "tests").mkdir()
        (self.source / "tests/test_real.py").write_text("import unittest\nclass TestCase(unittest.TestCase):\n    def test_real(self): pass\n", encoding="utf-8")
        command = infer_tests(self.source)[0]
        self.assertIn("PYTHONPATH=src", command)
        self.assertIn("unittest discover", command)

    def test_node_lockfile_selects_package_manager(self):
        (self.source / "package.json").write_text('{"scripts":{"test":"vitest run"}}')
        (self.source / "pnpm-lock.yaml").touch()
        self.assertEqual(infer_tests(self.source), ["pnpm test"])

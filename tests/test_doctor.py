from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from github_agent_bridge.config import bootstrap_config, configure_writer, save_config, load_config
from github_agent_bridge.doctor import doctor_report, parse_github_remote


class DoctorCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".ai/state").mkdir(parents=True)
        (self.repo / ".ai/state/tasks.json").write_text('{"schema_version": 1, "tasks": {}}\n', encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def fake_which(self, command: str):
        if command in {"gh", "codex"}:
            return f"/usr/bin/{command}"
        return None

    def fake_runner(self, cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if cmd[:4] == ["git", "config", "--get", "remote.origin.url"]:
            return subprocess.CompletedProcess(cmd, 0, "git@github.com:owner/repo.git\n", "")
        if "auth" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "authenticated\n", "")
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "codex 1.0\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def test_parse_github_remote_variants(self) -> None:
        self.assertEqual(
            {"host": "github.com", "repository": "owner/repo"},
            parse_github_remote("https://github.com/owner/repo.git"),
        )
        self.assertEqual(
            {"host": "github.com", "repository": "owner/repo"},
            parse_github_remote("git@github.com:owner/repo.git"),
        )
        self.assertIsNone(parse_github_remote("not-a-remote"))

    def test_zero_touch_ready_when_all_requirements_are_confirmed(self) -> None:
        bootstrap_config(
            self.repo,
            mode="managed",
            repositories=["owner/repo"],
            connection_name="writer",
            write_confirmed=True,
            unattended_confirmed=True,
            test_commands=["pytest -q"],
            work_trigger_confirmed=True,
        )
        report = doctor_report(self.repo, runner=self.fake_runner, which=self.fake_which)
        self.assertTrue(report["zero_touch_ready"])
        self.assertTrue(all(item["status"] != "fail" for item in report["checks"]))

    def test_missing_work_trigger_blocks_zero_touch(self) -> None:
        bootstrap_config(
            self.repo,
            mode="managed",
            repositories=["owner/repo"],
            connection_name="writer",
            write_confirmed=True,
            unattended_confirmed=True,
            test_commands=["pytest -q"],
            work_trigger_confirmed=False,
        )
        report = doctor_report(self.repo, runner=self.fake_runner, which=self.fake_which)
        self.assertFalse(report["zero_touch_ready"])
        trigger = next(item for item in report["checks"] if item["name"] == "chatgpt_work_trigger")
        self.assertEqual("fail", trigger["status"])

    def test_repository_allowlist_is_required(self) -> None:
        bootstrap_config(
            self.repo,
            mode="managed",
            repositories=[],
            connection_name="writer",
            write_confirmed=True,
            unattended_confirmed=True,
            test_commands=["pytest -q"],
            work_trigger_confirmed=True,
        )
        report = doctor_report(self.repo, runner=self.fake_runner, which=self.fake_which)
        self.assertFalse(report["zero_touch_ready"])
        allowlist = next(item for item in report["checks"] if item["name"] == "repository_allowlist")
        self.assertEqual("fail", allowlist["status"])

    def test_unattended_confirmation_is_required(self) -> None:
        bootstrap_config(
            self.repo,
            mode="managed",
            repositories=["owner/repo"],
            connection_name="writer",
            write_confirmed=True,
            unattended_confirmed=False,
            test_commands=["pytest -q"],
            work_trigger_confirmed=True,
        )
        report = doctor_report(self.repo, runner=self.fake_runner, which=self.fake_which)
        unattended = next(item for item in report["checks"] if item["name"] == "writer_unattended")
        self.assertEqual("fail", unattended["status"])

    def test_configure_writer_rejects_malformed_repository(self) -> None:
        save_config(self.repo, load_config(self.repo))
        with self.assertRaises(RuntimeError):
            configure_writer(self.repo, mode="readonly", repositories=["bad-repository"])


if __name__ == "__main__":
    unittest.main()

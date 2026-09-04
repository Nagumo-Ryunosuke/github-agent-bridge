from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from github_agent_bridge.config import bootstrap_config, configure_work_trigger, configure_writer, load_config, save_config
from github_agent_bridge.doctor import doctor_report, parse_github_remote


NOW = datetime(2026, 9, 4, 8, 30, 0, tzinfo=timezone.utc)


class DoctorCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".ai/state").mkdir(parents=True)
        (self.repo / ".ai/state/tasks.json").write_text('{"schema_version": 1, "tasks": {}}\n', encoding="utf-8")
        self.write_heartbeat("2026-09-04T08:29:30+00:00")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_heartbeat(self, value: str) -> None:
        path = self.repo / ".git/agent-bridge/watcher.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "reviewed_heads": {}, "last_poll_at": value}) + "\n", encoding="utf-8")

    def fake_which(self, command: str):
        if command in {"gh", "codex"}:
            return f"/usr/bin/{command}"
        return None

    def fake_runner(self, cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if cmd[:4] == ["git", "config", "--get", "remote.origin.url"]:
            return subprocess.CompletedProcess(cmd, 0, "git@github.com:owner/repo.git\n", "")
        if cmd[:4] == ["git", "rev-parse", "--git-path", "agent-bridge/watcher.json"]:
            return subprocess.CompletedProcess(cmd, 0, ".git/agent-bridge/watcher.json\n", "")
        if "auth" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "authenticated\n", "")
        if len(cmd) >= 3 and cmd[1:3] == ["repo", "view"]:
            return subprocess.CompletedProcess(cmd, 0, '{"nameWithOwner":"owner/repo"}\n', "")
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "codex 1.0\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def ready_config(self, **overrides) -> None:
        kwargs = {
            "mode": "managed",
            "repositories": ["owner/repo"],
            "connection_name": "writer",
            "write_confirmed": True,
            "unattended_confirmed": True,
            "test_commands": ["pytest -q"],
            "work_trigger_confirmed": True,
        }
        kwargs.update(overrides)
        bootstrap_config(self.repo, **kwargs)

    def report(self):
        return doctor_report(self.repo, runner=self.fake_runner, which=self.fake_which, now=NOW)

    def test_parse_github_remote_variants(self) -> None:
        self.assertEqual(
            {"host": "github.com", "repository": "owner/repo"},
            parse_github_remote("https://github.com/owner/repo.git"),
        )
        self.assertEqual(
            {"host": "github.com", "repository": "owner/repo"},
            parse_github_remote("https://github.com/owner/repo/"),
        )
        self.assertEqual(
            {"host": "github.com", "repository": "owner/repo"},
            parse_github_remote("git@github.com:owner/repo.git"),
        )
        self.assertIsNone(parse_github_remote("not-a-remote"))

    def test_zero_touch_ready_when_all_requirements_are_confirmed(self) -> None:
        self.ready_config()
        report = self.report()
        self.assertTrue(report["zero_touch_ready"])
        self.assertTrue(all(item["status"] != "fail" for item in report["checks"]))

    def test_missing_work_trigger_blocks_zero_touch(self) -> None:
        self.ready_config(work_trigger_confirmed=False)
        report = self.report()
        self.assertFalse(report["zero_touch_ready"])
        trigger = next(item for item in report["checks"] if item["name"] == "chatgpt_work_trigger")
        self.assertEqual("fail", trigger["status"])

    def test_repository_allowlist_is_required(self) -> None:
        self.ready_config(repositories=[])
        report = self.report()
        self.assertFalse(report["zero_touch_ready"])
        allowlist = next(item for item in report["checks"] if item["name"] == "repository_allowlist")
        self.assertEqual("fail", allowlist["status"])

    def test_unattended_confirmation_is_required(self) -> None:
        self.ready_config(unattended_confirmed=False)
        report = self.report()
        unattended = next(item for item in report["checks"] if item["name"] == "writer_unattended")
        self.assertEqual("fail", unattended["status"])

    def test_stale_watcher_blocks_zero_touch(self) -> None:
        self.ready_config()
        self.write_heartbeat("2026-09-04T08:20:00+00:00")
        report = self.report()
        watcher = next(item for item in report["checks"] if item["name"] == "codex_watcher")
        self.assertEqual("fail", watcher["status"])
        self.assertFalse(report["zero_touch_ready"])

    def test_far_future_watcher_heartbeat_blocks_zero_touch(self) -> None:
        self.ready_config()
        self.write_heartbeat("2026-09-04T08:40:00+00:00")
        report = self.report()
        watcher = next(item for item in report["checks"] if item["name"] == "codex_watcher")
        self.assertEqual("fail", watcher["status"])
        self.assertIn("future", watcher["message"])
        self.assertFalse(report["zero_touch_ready"])

    def test_small_clock_skew_is_tolerated(self) -> None:
        self.ready_config()
        self.write_heartbeat("2026-09-04T08:31:00+00:00")
        report = self.report()
        watcher = next(item for item in report["checks"] if item["name"] == "codex_watcher")
        self.assertEqual("pass", watcher["status"])

    def test_bootstrap_preserves_confirmations_when_omitted(self) -> None:
        self.ready_config()
        bootstrap_config(
            self.repo,
            mode="managed",
            repositories=["owner/repo"],
            connection_name=None,
            write_confirmed=None,
            unattended_confirmed=None,
            test_commands=None,
            work_trigger_confirmed=None,
        )
        config = load_config(self.repo)
        self.assertTrue(config["github"]["managed"]["write_confirmed"])
        self.assertTrue(config["github"]["managed"]["unattended_confirmed"])
        self.assertTrue(config["automation"]["work_trigger_confirmed"])
        self.assertEqual(["owner/repo"], config["automation"]["work_trigger_repositories"])
        self.assertEqual(["pytest -q"], config["review"]["test_commands"])

    def test_repository_scope_change_invalidates_writer_and_trigger_confirmation(self) -> None:
        self.ready_config()
        configure_writer(self.repo, mode="managed", repositories=["owner/other"])
        config = load_config(self.repo)
        self.assertFalse(config["github"]["managed"]["write_confirmed"])
        self.assertFalse(config["github"]["managed"]["unattended_confirmed"])
        self.assertFalse(config["automation"]["work_trigger_confirmed"])
        self.assertEqual([], config["automation"]["work_trigger_repositories"])

    def test_work_trigger_confirmation_snapshots_repository_scope(self) -> None:
        self.ready_config()
        configure_work_trigger(self.repo, confirmed=False)
        configure_work_trigger(self.repo, confirmed=True)
        config = load_config(self.repo)
        self.assertEqual(["owner/repo"], config["automation"]["work_trigger_repositories"])

    def test_writer_mode_change_resets_confirmation(self) -> None:
        self.ready_config()
        configure_writer(self.repo, mode="readonly")
        configure_writer(self.repo, mode="managed")
        config = load_config(self.repo)
        self.assertFalse(config["github"]["managed"]["write_confirmed"])
        self.assertFalse(config["github"]["managed"]["unattended_confirmed"])

    def test_configure_writer_rejects_malformed_repository(self) -> None:
        save_config(self.repo, load_config(self.repo))
        with self.assertRaises(RuntimeError):
            configure_writer(self.repo, mode="readonly", repositories=["bad-repository"])


if __name__ == "__main__":
    unittest.main()

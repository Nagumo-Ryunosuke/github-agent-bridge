from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from github_agent_bridge.service import (
    ServiceError,
    detect_service_backend,
    install_service,
    restart_service,
    service_slug,
    uninstall_service,
)
from github_agent_bridge.skill_install import install_skill, skill_status, uninstall_skill


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], cwd=None) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")


def which_linux(command: str):
    return "/bin/systemctl" if command == "systemctl" else None


def which_mac(command: str):
    return "/bin/launchctl" if command == "launchctl" else None


def which_windows(command: str):
    return "C:/Windows/System32/schtasks.exe" if command in {"schtasks", "schtasks.exe"} else None


class ServiceCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo with space"
        self.repo.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_service_slug_is_stable(self) -> None:
        self.assertEqual(service_slug(self.repo), service_slug(self.repo))
        self.assertIn("repo-with-space", service_slug(self.repo))

    def test_linux_auto_backend_uses_user_systemd(self) -> None:
        runner = FakeRunner()
        self.assertEqual(
            "systemd",
            detect_service_backend(self.repo, platform_name="linux", runner=runner, which=which_linux),
        )
        self.assertTrue(any("show-environment" in call for call in runner.calls))

    def test_linux_without_user_systemd_is_rejected(self) -> None:
        with self.assertRaises(ServiceError):
            detect_service_backend(self.repo, platform_name="linux", runner=FakeRunner(), which=lambda _: None)

    def test_systemd_install_restart_uninstall(self) -> None:
        runner = FakeRunner()
        status = install_service(
            self.repo,
            platform_name="linux",
            home=self.home,
            env={},
            python_executable="/usr/bin/python3",
            runner=runner,
            which=which_linux,
        )
        self.assertTrue(status["installed"])
        self.assertTrue(status["active"])
        definition = Path(status["definition"])
        text = definition.read_text(encoding="utf-8")
        self.assertIn("WorkingDirectory=", text)
        self.assertIn("-m github_agent_bridge.cli watch", text)
        self.assertIn("StandardOutput=\"append:", text)
        self.assertTrue((Path(status["state_dir"]) / "service.json").exists())
        self.assertTrue(restart_service(
            self.repo, platform_name="linux", home=self.home, env={}, runner=runner, which=which_linux
        )["installed"])
        self.assertFalse(uninstall_service(
            self.repo, platform_name="linux", home=self.home, env={}, runner=runner, which=which_linux
        )["installed"])

    def test_launchd_install(self) -> None:
        runner = FakeRunner()
        status = install_service(
            self.repo,
            platform_name="darwin",
            home=self.home,
            env={},
            python_executable="/usr/bin/python3",
            uid=501,
            runner=runner,
            which=which_mac,
        )
        self.assertTrue(status["installed"])
        self.assertTrue(status["active"])
        self.assertTrue(Path(status["definition"]).exists())
        self.assertTrue(any("bootstrap" in call for call in runner.calls))

    def test_windows_task_install(self) -> None:
        runner = FakeRunner()
        env = {"LOCALAPPDATA": str(self.root / "Local")}
        status = install_service(
            self.repo,
            platform_name="win32",
            home=self.home,
            env=env,
            python_executable="C:/Python/python.exe",
            runner=runner,
            which=which_windows,
        )
        self.assertTrue(status["installed"])
        self.assertIsNone(status["active"])
        self.assertNotIn("\\", status["label"])
        wrapper = Path(status["definition"]).read_text(encoding="utf-8")
        self.assertIn("cd /d", wrapper)
        self.assertIn("github_agent_bridge.cli watch", wrapper)
        self.assertTrue(any("/Create" in call for call in runner.calls))
        self.assertTrue(any("/RL" in call and "LIMITED" in call for call in runner.calls))

    def test_service_validates_background_python(self) -> None:
        class BadRunner(FakeRunner):
            def __call__(self, cmd: list[str], cwd=None) -> subprocess.CompletedProcess[str]:
                self.calls.append(list(cmd))
                if "import github_agent_bridge" in cmd:
                    return subprocess.CompletedProcess(cmd, 1, "", "missing")
                return subprocess.CompletedProcess(cmd, 0, "ok", "")
        with self.assertRaises(ServiceError):
            install_service(
                self.repo,
                platform_name="linux",
                home=self.home,
                env={},
                python_executable="/bad/python",
                runner=BadRunner(),
                which=which_linux,
            )


class SkillInstallCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_user_skill_install_status_uninstall(self) -> None:
        result = install_skill(scope="user", home=self.home)
        path = Path(result["path"])
        self.assertTrue(result["installed"])
        self.assertTrue(result["up_to_date"])
        self.assertEqual(self.home / ".agents" / "skills" / "github-agent-bridge", path)
        self.assertTrue((path / "SKILL.md").is_file())
        self.assertTrue((path / "agents" / "openai.yaml").is_file())
        self.assertFalse((path / "SKILL.md").is_symlink())
        self.assertTrue(skill_status(scope="user", home=self.home)["up_to_date"])
        self.assertFalse(uninstall_skill(scope="user", home=self.home)["installed"])

    def test_repo_skill_scope(self) -> None:
        result = install_skill(scope="repo", repo=self.repo)
        self.assertTrue(result["installed"])
        self.assertEqual(
            self.repo / ".agents" / "skills" / "github-agent-bridge",
            Path(result["path"]),
        )

    def test_skill_reinstall_repairs_modified_copy(self) -> None:
        result = install_skill(scope="user", home=self.home)
        skill_md = Path(result["path"]) / "SKILL.md"
        skill_md.write_text("modified\n", encoding="utf-8")
        self.assertFalse(skill_status(scope="user", home=self.home)["up_to_date"])
        repaired = install_skill(scope="user", home=self.home)
        self.assertTrue(repaired["up_to_date"])


if __name__ == "__main__":
    unittest.main()

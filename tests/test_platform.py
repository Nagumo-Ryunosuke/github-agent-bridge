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
    service_status,
    uninstall_service,
)
from github_agent_bridge.skill_install import SkillInstallError, install_skill, skill_status, uninstall_skill


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
            python_executable="C:/Program Files/Python/python.exe",
            runner=runner,
            which=which_windows,
        )
        self.assertTrue(status["installed"])
        self.assertIsNone(status["active"])
        self.assertNotIn("\\", status["label"])
        launcher_path = Path(status["definition"])
        launcher = launcher_path.read_text(encoding="ascii")
        self.assertTrue(launcher.isascii())
        self.assertIn("github_agent_bridge.cli", launcher)
        self.assertIn("sys.path.insert", launcher)
        create = next(call for call in runner.calls if "/Create" in call)
        action = create[create.index("/TR") + 1]
        self.assertIn('"C:/Program Files/Python/python.exe"', action)
        self.assertIn("-E", action)
        self.assertIn("-X utf8", action)
        self.assertIn(str(launcher_path), action)
        self.assertIn("/RL", create)
        self.assertIn("LIMITED", create)
        self.assertIn("/HRESULT", create)

    def test_windows_validation_is_self_contained_and_does_not_persist_install_env(self) -> None:
        runner = FakeRunner()
        env = {
            "LOCALAPPDATA": str(self.root / "Local"),
            "PYTHONPATH": "C:/temporary/source",
            "GH_TOKEN": "do-not-write-this",
        }
        status = install_service(
            self.repo,
            platform_name="win32",
            home=self.home,
            env=env,
            python_executable="C:/Python/python.exe",
            start=False,
            runner=runner,
            which=which_windows,
        )
        validation = runner.calls[0]
        self.assertEqual(["-E", "-X", "utf8", "-c"], validation[1:5])
        self.assertIn("sys.path.insert(0,", validation[-1])
        self.assertIn("src", validation[-1])
        self.assertIn("import github_agent_bridge.cli", validation[-1])
        self.assertNotIn("PYTHONPATH", validation[-1])
        launcher = Path(status["definition"]).read_text(encoding="ascii")
        self.assertNotIn("temporary/source", launcher)
        self.assertNotIn("do-not-write-this", launcher)
        self.assertFalse(any("/Run" in call for call in runner.calls))

    def test_windows_unicode_paths_generate_ascii_launcher(self) -> None:
        repo = self.root / "项目 仓库"
        repo.mkdir()
        env = {"LOCALAPPDATA": str(self.root / "用户数据" / "Local")}
        runner = FakeRunner()
        status = install_service(
            repo,
            platform_name="win32",
            home=self.home,
            env=env,
            python_executable="C:/用户/Python/python.exe",
            start=False,
            runner=runner,
            which=which_windows,
        )
        launcher_path = Path(status["definition"])
        launcher = launcher_path.read_text(encoding="ascii")
        self.assertTrue(launcher.isascii())
        compile(launcher, str(launcher_path), "exec")
        self.assertIn("\\u", launcher)
        create = next(call for call in runner.calls if "/Create" in call)
        action = create[create.index("/TR") + 1]
        self.assertIn("C:/用户/Python/python.exe", action)
        self.assertIn(str(launcher_path), action)

    def test_windows_empty_env_uses_home_localappdata_fallback(self) -> None:
        runner = FakeRunner()
        status = install_service(
            self.repo,
            platform_name="win32",
            home=self.home,
            env={},
            python_executable="C:/Python/python.exe",
            start=False,
            runner=runner,
            which=which_windows,
        )
        self.assertTrue(str(status["state_dir"]).startswith(str(self.home / "AppData" / "Local")))

    def test_windows_legacy_cmd_definition_is_recognized_and_removed(self) -> None:
        runner = FakeRunner()
        env = {"LOCALAPPDATA": str(self.root / "Local")}
        status = install_service(
            self.repo,
            platform_name="win32",
            home=self.home,
            env=env,
            python_executable="C:/Python/python.exe",
            start=False,
            runner=runner,
            which=which_windows,
        )
        definition = Path(status["definition"])
        legacy = definition.with_name("watch.cmd")
        definition.rename(legacy)
        legacy_status = service_status(
            self.repo, platform_name="win32", home=self.home, env=env, runner=runner, which=which_windows
        )
        self.assertTrue(legacy_status["installed"])
        uninstall_service(
            self.repo, platform_name="win32", home=self.home, env=env, runner=runner, which=which_windows
        )
        self.assertFalse(legacy.exists())

    def test_windows_create_access_denied_is_actionable(self) -> None:
        class DeniedRunner(FakeRunner):
            def __call__(self, cmd: list[str], cwd=None) -> subprocess.CompletedProcess[str]:
                self.calls.append(list(cmd))
                if "/Create" in cmd:
                    return subprocess.CompletedProcess(cmd, 0x80070005, "", "ERROR: Access is denied.")
                return subprocess.CompletedProcess(cmd, 0, "ok", "")

        runner = DeniedRunner()
        with self.assertRaises(ServiceError) as raised:
            install_service(
                self.repo,
                platform_name="win32",
                home=self.home,
                env={"LOCALAPPDATA": str(self.root / "Local")},
                python_executable="C:/Python/python.exe",
                runner=runner,
                which=which_windows,
            )
        message = str(raised.exception)
        self.assertIn("Administrator terminal", message)
        self.assertIn("/RL LIMITED", message)
        self.assertIn("Access is denied", message)
        self.assertFalse(any("/Run" in call for call in runner.calls))

    def test_windows_create_access_denied_chinese_is_actionable(self) -> None:
        class DeniedRunner(FakeRunner):
            def __call__(self, cmd: list[str], cwd=None) -> subprocess.CompletedProcess[str]:
                self.calls.append(list(cmd))
                if "/Create" in cmd:
                    return subprocess.CompletedProcess(cmd, 1, "错误: 拒绝访问。", "")
                return subprocess.CompletedProcess(cmd, 0, "ok", "")

        with self.assertRaisesRegex(ServiceError, "Administrator terminal"):
            install_service(
                self.repo,
                platform_name="win32",
                home=self.home,
                env={"LOCALAPPDATA": str(self.root / "Local")},
                python_executable="C:/Python/python.exe",
                runner=DeniedRunner(),
                which=which_windows,
            )

    def test_windows_create_other_failure_preserves_detail(self) -> None:
        class FailedRunner(FakeRunner):
            def __call__(self, cmd: list[str], cwd=None) -> subprocess.CompletedProcess[str]:
                self.calls.append(list(cmd))
                if "/Create" in cmd:
                    return subprocess.CompletedProcess(cmd, 2, "scheduler detail", "")
                return subprocess.CompletedProcess(cmd, 0, "ok", "")

        with self.assertRaises(ServiceError) as raised:
            install_service(
                self.repo,
                platform_name="win32",
                home=self.home,
                env={"LOCALAPPDATA": str(self.root / "Local")},
                python_executable="C:/Python/python.exe",
                runner=FailedRunner(),
                which=which_windows,
            )
        self.assertIn("scheduler detail", str(raised.exception))
        self.assertNotIn("Administrator terminal", str(raised.exception))

    def test_service_validates_background_python(self) -> None:
        class BadRunner(FakeRunner):
            def __call__(self, cmd: list[str], cwd=None) -> subprocess.CompletedProcess[str]:
                self.calls.append(list(cmd))
                if any("import github_agent_bridge" in arg for arg in cmd):
                    return subprocess.CompletedProcess(cmd, 1, "", "missing")
                return subprocess.CompletedProcess(cmd, 0, "ok", "")
        runner = BadRunner()
        with self.assertRaises(ServiceError):
            install_service(
                self.repo,
                platform_name="linux",
                home=self.home,
                env={},
                python_executable="/bad/python",
                runner=runner,
                which=which_linux,
            )
        self.assertFalse(any("daemon-reload" in call for call in runner.calls))


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
        self.assertTrue(result["managed"])
        self.assertTrue(result["up_to_date"])
        self.assertFalse(result["modified"])
        self.assertEqual(self.home / ".agents" / "skills" / "github-agent-bridge", path)
        self.assertTrue((path / "SKILL.md").is_file())
        self.assertTrue((path / "agents" / "openai.yaml").is_file())
        self.assertTrue((path / ".agent-bridge-install.json").is_file())
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

    def test_modified_managed_copy_requires_force(self) -> None:
        result = install_skill(scope="user", home=self.home)
        skill_md = Path(result["path"]) / "SKILL.md"
        skill_md.write_text("modified\n", encoding="utf-8")
        status = skill_status(scope="user", home=self.home)
        self.assertTrue(status["modified"])
        self.assertFalse(status["up_to_date"])
        with self.assertRaises(SkillInstallError):
            install_skill(scope="user", home=self.home)
        repaired = install_skill(scope="user", home=self.home, force=True)
        self.assertTrue(repaired["up_to_date"])
        self.assertFalse(repaired["modified"])

    def test_unmanaged_destination_requires_force(self) -> None:
        path = self.home / ".agents" / "skills" / "github-agent-bridge"
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text("foreign\n", encoding="utf-8")
        with self.assertRaises(SkillInstallError):
            install_skill(scope="user", home=self.home)
        self.assertEqual("foreign\n", (path / "SKILL.md").read_text(encoding="utf-8"))
        forced = install_skill(scope="user", home=self.home, force=True)
        self.assertTrue(forced["managed"])
        self.assertTrue(forced["up_to_date"])

    def test_uninstall_refuses_modified_copy_without_force(self) -> None:
        result = install_skill(scope="user", home=self.home)
        path = Path(result["path"])
        (path / "SKILL.md").write_text("modified\n", encoding="utf-8")
        with self.assertRaises(SkillInstallError):
            uninstall_skill(scope="user", home=self.home)
        self.assertTrue(path.exists())
        removed = uninstall_skill(scope="user", home=self.home, force=True)
        self.assertFalse(removed["installed"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

Runner = Callable[[list[str], Optional[Path]], subprocess.CompletedProcess[str]]
Which = Callable[[str], Optional[str]]


class ServiceError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def service_slug(repo: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9.-]+", "-", repo.name).strip("-.") or "repo"
    digest = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:10]
    return f"{stem[:36]}-{digest}"


def _state_root(platform_name: str, home: Path, env: Mapping[str, str]) -> Path:
    if platform_name.startswith("win"):
        base = Path(env["LOCALAPPDATA"]) if env.get("LOCALAPPDATA") else home / "AppData" / "Local"
        return base / "github-agent-bridge" / "services"
    base = Path(env["XDG_STATE_HOME"]) if env.get("XDG_STATE_HOME") else home / ".local" / "state"
    return base / "github-agent-bridge" / "services"


def service_state_dir(
    repo: Path,
    *,
    platform_name: Optional[str] = None,
    home: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Path:
    platform_name = platform_name or sys.platform
    home = home or Path.home()
    return _state_root(platform_name, home, env or os.environ) / service_slug(repo)


def _uid_value(uid: Optional[int]) -> int:
    if uid is not None:
        return int(uid)
    getter = getattr(os, "getuid", None)
    if getter is None:
        raise ServiceError("launchd backend requires a POSIX user id")
    return int(getter())


def _systemd_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _systemd_unit(repo: Path, python_executable: str, log_dir: Path) -> str:
    return "\n".join([
        "[Unit]",
        f"Description=GitHub Agent Bridge watcher for {repo.name}",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={_systemd_quote(str(repo.resolve()))}",
        f"ExecStart={_systemd_quote(python_executable)} -m github_agent_bridge.cli watch",
        "Restart=on-failure",
        "RestartSec=5",
        "Environment=PYTHONUNBUFFERED=1",
        f"StandardOutput={_systemd_quote('append:' + str(log_dir / 'watch.log'))}",
        f"StandardError={_systemd_quote('append:' + str(log_dir / 'watch.err.log'))}",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ])


def _launchd_plist(repo: Path, python_executable: str, label: str, log_dir: Path) -> bytes:
    return plistlib.dumps({
        "Label": label,
        "ProgramArguments": [python_executable, "-m", "github_agent_bridge.cli", "watch"],
        "WorkingDirectory": str(repo.resolve()),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / "watch.log"),
        "StandardErrorPath": str(log_dir / "watch.err.log"),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }, fmt=plistlib.FMT_XML, sort_keys=True)


def _windows_wrapper(repo: Path, python_executable: str, log_dir: Path) -> str:
    return "\r\n".join([
        "@echo off",
        "setlocal",
        f'cd /d "{repo.resolve()}"',
        f'"{python_executable}" -m github_agent_bridge.cli watch >> "{log_dir / "watch.log"}" 2>> "{log_dir / "watch.err.log"}"',
        "",
    ])


def detect_service_backend(
    repo: Path,
    *,
    platform_name: Optional[str] = None,
    runner: Runner = _run,
    which: Which = shutil.which,
) -> str:
    platform_name = platform_name or sys.platform
    if platform_name.startswith("win"):
        if which("schtasks") or which("schtasks.exe"):
            return "windows-task"
        raise ServiceError("Windows Task Scheduler (`schtasks`) was not found")
    if platform_name == "darwin":
        if which("launchctl"):
            return "launchd"
        raise ServiceError("launchctl was not found")
    if platform_name.startswith("linux"):
        systemctl = which("systemctl")
        if systemctl and runner([systemctl, "--user", "show-environment"], repo).returncode == 0:
            return "systemd"
        raise ServiceError(
            "no supported Linux user service manager is available; v1.4 automatic startup requires a working `systemd --user` manager"
        )
    raise ServiceError(f"unsupported platform for watcher service: {platform_name}")


@dataclass(frozen=True)
class ServicePaths:
    backend: str
    slug: str
    state_dir: Path
    definition: Path
    label: str


def service_paths(
    repo: Path,
    backend: str,
    *,
    platform_name: Optional[str] = None,
    home: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
) -> ServicePaths:
    platform_name = platform_name or sys.platform
    home = home or Path.home()
    state_dir = service_state_dir(repo, platform_name=platform_name, home=home, env=env)
    slug = service_slug(repo)
    if backend == "systemd":
        definition = home / ".config" / "systemd" / "user" / f"github-agent-bridge-{slug}.service"
        label = definition.name
    elif backend == "launchd":
        label = f"io.github.github-agent-bridge.{slug}"
        definition = home / "Library" / "LaunchAgents" / f"{label}.plist"
    elif backend == "windows-task":
        label = f"GitHubAgentBridge-{slug}"
        definition = state_dir / "watch.cmd"
    else:
        raise ServiceError(f"unsupported service backend: {backend}")
    return ServicePaths(backend, slug, state_dir, definition, label)


def _manifest_path(paths: ServicePaths) -> Path:
    return paths.state_dir / "service.json"


def _read_manifest(state_dir: Path) -> Optional[dict[str, Any]]:
    path = state_dir / "service.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_manifest(paths: ServicePaths, repo: Path, python_executable: str) -> None:
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    _manifest_path(paths).write_text(json.dumps({
        "schema_version": 1,
        "backend": paths.backend,
        "slug": paths.slug,
        "repository": str(repo.resolve()),
        "python_executable": python_executable,
        "definition": str(paths.definition),
        "label": paths.label,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_python(repo: Path, python_executable: str, runner: Runner) -> None:
    proc = runner([python_executable, "-c", "import github_agent_bridge"], repo)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "import failed"
        raise ServiceError(f"watcher Python cannot import github_agent_bridge: {python_executable}: {detail}")


def install_service(
    repo: Path,
    *,
    backend: str = "auto",
    start: bool = True,
    platform_name: Optional[str] = None,
    home: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    python_executable: Optional[str] = None,
    uid: Optional[int] = None,
    runner: Runner = _run,
    which: Which = shutil.which,
) -> dict[str, Any]:
    platform_name = platform_name or sys.platform
    home = home or Path.home()
    env = env or os.environ
    python_executable = python_executable or sys.executable
    _validate_python(repo, python_executable, runner)
    if backend == "auto":
        backend = detect_service_backend(repo, platform_name=platform_name, runner=runner, which=which)
    paths = service_paths(repo, backend, platform_name=platform_name, home=home, env=env)
    paths.state_dir.mkdir(parents=True, exist_ok=True)

    if backend == "systemd":
        paths.definition.parent.mkdir(parents=True, exist_ok=True)
        paths.definition.write_text(_systemd_unit(repo, python_executable, paths.state_dir), encoding="utf-8")
        tool = which("systemctl") or "systemctl"
        commands = [[tool, "--user", "daemon-reload"], [tool, "--user", "enable", paths.label]]
        if start:
            commands.append([tool, "--user", "restart", paths.label])
        for cmd in commands:
            proc = runner(cmd, repo)
            if proc.returncode != 0:
                raise ServiceError(proc.stderr.strip() or f"service command failed: {' '.join(cmd)}")
    elif backend == "launchd":
        paths.definition.parent.mkdir(parents=True, exist_ok=True)
        paths.definition.write_bytes(_launchd_plist(repo, python_executable, paths.label, paths.state_dir))
        tool = which("launchctl") or "launchctl"
        launch_uid = _uid_value(uid)
        target = f"gui/{launch_uid}/{paths.label}"
        runner([tool, "bootout", target], repo)
        proc = runner([tool, "bootstrap", f"gui/{launch_uid}", str(paths.definition)], repo)
        if proc.returncode != 0:
            raise ServiceError(proc.stderr.strip() or "failed to bootstrap launchd agent")
        if start:
            proc = runner([tool, "kickstart", "-k", target], repo)
            if proc.returncode != 0:
                raise ServiceError(proc.stderr.strip() or "failed to start launchd agent")
    elif backend == "windows-task":
        paths.definition.write_bytes(_windows_wrapper(repo, python_executable, paths.state_dir).encode("utf-8"))
        tool = which("schtasks") or which("schtasks.exe") or "schtasks.exe"
        proc = runner([
            tool, "/Create", "/TN", paths.label, "/TR", str(paths.definition),
            "/SC", "ONLOGON", "/RL", "LIMITED", "/F",
        ], repo)
        if proc.returncode != 0:
            raise ServiceError(proc.stderr.strip() or "failed to create Windows scheduled task")
        if start:
            proc = runner([tool, "/Run", "/TN", paths.label], repo)
            if proc.returncode != 0:
                raise ServiceError(proc.stderr.strip() or "failed to start Windows scheduled task")
    else:
        raise ServiceError(f"unsupported service backend: {backend}")

    _write_manifest(paths, repo, python_executable)
    return service_status(
        repo, backend=backend, platform_name=platform_name, home=home, env=env,
        uid=uid, runner=runner, which=which,
    )


def service_status(
    repo: Path,
    *,
    backend: str = "auto",
    platform_name: Optional[str] = None,
    home: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    uid: Optional[int] = None,
    runner: Runner = _run,
    which: Which = shutil.which,
) -> dict[str, Any]:
    platform_name = platform_name or sys.platform
    home = home or Path.home()
    env = env or os.environ
    state_dir = service_state_dir(repo, platform_name=platform_name, home=home, env=env)
    manifest = _read_manifest(state_dir)
    if backend == "auto":
        backend = (
            str(manifest.get("backend"))
            if manifest and manifest.get("backend")
            else detect_service_backend(repo, platform_name=platform_name, runner=runner, which=which)
        )
    paths = service_paths(repo, backend, platform_name=platform_name, home=home, env=env)
    installed = bool(manifest and paths.definition.exists())
    active: Optional[bool] = None
    detail = "not installed"

    if installed and backend == "systemd":
        tool = which("systemctl") or "systemctl"
        active = runner([tool, "--user", "is-active", "--quiet", paths.label], repo).returncode == 0
        detail = "active" if active else "installed but inactive"
    elif installed and backend == "launchd":
        tool = which("launchctl") or "launchctl"
        active = runner([tool, "print", f"gui/{_uid_value(uid)}/{paths.label}"], repo).returncode == 0
        detail = "loaded" if active else "installed but not loaded"
    elif installed and backend == "windows-task":
        tool = which("schtasks") or which("schtasks.exe") or "schtasks.exe"
        installed = runner([tool, "/Query", "/TN", paths.label], repo).returncode == 0
        detail = (
            "scheduled task installed; runtime health is verified by watcher heartbeat"
            if installed else "scheduled task not found"
        )

    return {
        "backend": backend,
        "installed": installed,
        "active": active,
        "detail": detail,
        "label": paths.label,
        "definition": str(paths.definition),
        "state_dir": str(paths.state_dir),
    }


def restart_service(
    repo: Path,
    *,
    backend: str = "auto",
    platform_name: Optional[str] = None,
    home: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    uid: Optional[int] = None,
    runner: Runner = _run,
    which: Which = shutil.which,
) -> dict[str, Any]:
    status = service_status(
        repo, backend=backend, platform_name=platform_name, home=home, env=env,
        uid=uid, runner=runner, which=which,
    )
    if not status["installed"]:
        raise ServiceError("watcher service is not installed")
    backend = str(status["backend"])
    paths = service_paths(repo, backend, platform_name=platform_name, home=home, env=env)
    if backend == "systemd":
        tool = which("systemctl") or "systemctl"
        proc = runner([tool, "--user", "restart", paths.label], repo)
    elif backend == "launchd":
        tool = which("launchctl") or "launchctl"
        proc = runner([tool, "kickstart", "-k", f"gui/{_uid_value(uid)}/{paths.label}"], repo)
    else:
        tool = which("schtasks") or which("schtasks.exe") or "schtasks.exe"
        runner([tool, "/End", "/TN", paths.label], repo)
        proc = runner([tool, "/Run", "/TN", paths.label], repo)
    if proc.returncode != 0:
        raise ServiceError(proc.stderr.strip() or "failed to restart watcher service")
    return service_status(
        repo, backend=backend, platform_name=platform_name, home=home, env=env,
        uid=uid, runner=runner, which=which,
    )


def uninstall_service(
    repo: Path,
    *,
    backend: str = "auto",
    platform_name: Optional[str] = None,
    home: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    uid: Optional[int] = None,
    runner: Runner = _run,
    which: Which = shutil.which,
) -> dict[str, Any]:
    status = service_status(
        repo, backend=backend, platform_name=platform_name, home=home, env=env,
        uid=uid, runner=runner, which=which,
    )
    backend = str(status["backend"])
    paths = service_paths(repo, backend, platform_name=platform_name, home=home, env=env)

    if backend == "systemd":
        tool = which("systemctl") or "systemctl"
        runner([tool, "--user", "disable", "--now", paths.label], repo)
        paths.definition.unlink(missing_ok=True)
        runner([tool, "--user", "daemon-reload"], repo)
    elif backend == "launchd":
        tool = which("launchctl") or "launchctl"
        runner([tool, "bootout", f"gui/{_uid_value(uid)}/{paths.label}"], repo)
        paths.definition.unlink(missing_ok=True)
    elif backend == "windows-task":
        tool = which("schtasks") or which("schtasks.exe") or "schtasks.exe"
        runner([tool, "/End", "/TN", paths.label], repo)
        runner([tool, "/Delete", "/TN", paths.label, "/F"], repo)
        paths.definition.unlink(missing_ok=True)
    else:
        raise ServiceError(f"unsupported service backend: {backend}")

    _manifest_path(paths).unlink(missing_ok=True)
    return {
        "backend": backend,
        "installed": False,
        "active": False,
        "detail": "uninstalled",
        "label": paths.label,
        "definition": str(paths.definition),
        "state_dir": str(paths.state_dir),
    }

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional


Which = Callable[[str], Optional[str]]
Runner = Callable[[list[str], bool], subprocess.CompletedProcess[str]]


class DependencyInstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstallStep:
    name: str
    description: str
    command: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run(command: list[str], capture: bool = True) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {"text": True, "encoding": "utf-8"}
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return subprocess.run(command, **kwargs)


def _command_version(path: Optional[str], runner: Runner) -> Optional[str]:
    if not path:
        return None
    proc = runner([path, "--version"], True)
    if proc.returncode != 0:
        return None
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0] if text else None


def detect_environment(
    *,
    include_codex: bool = True,
    which: Which = shutil.which,
    runner: Runner = _run,
    platform_name: Optional[str] = None,
    machine: Optional[str] = None,
) -> dict[str, Any]:
    system = platform_name or platform.system()
    architecture = machine or platform.machine() or "unknown"
    git_path = which("git")
    gh_path = which("gh")
    codex_path = which("codex") if include_codex else None

    gh_authenticated = False
    if gh_path:
        proc = runner([gh_path, "auth", "status", "-h", "github.com"], True)
        gh_authenticated = proc.returncode == 0

    codex_authenticated = False
    if codex_path:
        proc = runner([codex_path, "login", "status"], True)
        codex_authenticated = proc.returncode == 0

    dispatch_ready = bool(git_path and gh_path and gh_authenticated)
    unattended_review_ready = bool(include_codex and dispatch_ready and codex_path and codex_authenticated)

    return {
        "platform": system,
        "architecture": architecture,
        "python": {
            "available": sys.version_info >= (3, 9),
            "path": sys.executable,
            "version": ".".join(str(part) for part in sys.version_info[:3]),
        },
        "git": {"available": bool(git_path), "path": git_path, "version": _command_version(git_path, runner)},
        "gh": {
            "available": bool(gh_path),
            "path": gh_path,
            "version": _command_version(gh_path, runner),
            "authenticated": gh_authenticated,
        },
        "codex": {
            "required": include_codex,
            "available": bool(codex_path),
            "path": codex_path,
            "version": _command_version(codex_path, runner),
            "authenticated": codex_authenticated,
        },
        "dispatch_ready": dispatch_ready,
        "unattended_review_ready": unattended_review_ready,
    }


def _sudo_prefix() -> list[str]:
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid) and geteuid() == 0:
        return []
    if not shutil.which("sudo"):
        raise DependencyInstallError("system packages are missing and `sudo` was not found; install them as root or rerun as root")
    return ["sudo"]


def _linux_package_manager(which: Which) -> Optional[str]:
    for command in ("apt-get", "dnf", "yum", "zypper", "pacman", "apk"):
        if which(command):
            return command
    return None


def _linux_package_names(manager: str, *, need_git: bool, need_gh: bool, need_curl: bool) -> list[str]:
    packages: list[str] = []
    if need_git:
        packages.append("git")
    if need_gh:
        packages.append("github-cli" if manager in {"pacman", "apk"} else "gh")
    if need_curl:
        packages.append("curl")
    return packages


def _powershell(which: Which) -> Optional[str]:
    return which("powershell") or which("powershell.exe") or which("pwsh")


def _default_brew_path(architecture: str) -> str:
    normalized = architecture.lower()
    return "/opt/homebrew/bin/brew" if normalized in {"arm64", "aarch64"} else "/usr/local/bin/brew"


def build_install_plan(
    status: dict[str, Any],
    *,
    include_codex: bool = True,
    which: Which = shutil.which,
) -> list[InstallStep]:
    system = str(status.get("platform") or platform.system())
    architecture = str(status.get("architecture") or platform.machine() or "unknown")
    need_git = not bool(status.get("git", {}).get("available"))
    need_gh = not bool(status.get("gh", {}).get("available"))
    need_codex = include_codex and not bool(status.get("codex", {}).get("available"))
    steps: list[InstallStep] = []

    if system == "Windows":
        if need_git or need_gh:
            winget = which("winget")
            if not winget:
                raise DependencyInstallError(
                    "WinGet (`winget`) is required to install missing Git/GitHub CLI automatically. "
                    "Install Microsoft App Installer/WinGet, then rerun `agent-bridge env install`."
                )
            common = ("--accept-source-agreements", "--accept-package-agreements", "--silent")
            if need_git:
                steps.append(InstallStep("git", "Install Git with WinGet", (winget, "install", "--id", "Git.Git", "-e", *common)))
            if need_gh:
                steps.append(InstallStep("gh", "Install GitHub CLI with WinGet", (winget, "install", "--id", "GitHub.cli", "-e", *common)))
        if need_codex:
            powershell = _powershell(which)
            if not powershell:
                raise DependencyInstallError("PowerShell is required to run the official Codex CLI installer on Windows")
            script = "irm https://chatgpt.com/codex/install.ps1 | iex"
            steps.append(InstallStep("codex", "Install Codex CLI with the official OpenAI installer", (powershell, "-NoProfile", "-ExecutionPolicy", "ByPass", "-Command", script)))
        return steps

    if system == "Linux":
        need_curl = need_codex and not bool(which("curl"))
        if need_git or need_gh or need_curl:
            manager = _linux_package_manager(which)
            if not manager:
                raise DependencyInstallError(
                    "No supported Linux package manager was found (apt-get/dnf/yum/zypper/pacman/apk). "
                    "Install Git, GitHub CLI and curl with the distribution package manager, then rerun `agent-bridge env install`."
                )
            packages = _linux_package_names(manager, need_git=need_git, need_gh=need_gh, need_curl=need_curl)
            prefix = _sudo_prefix()
            if manager == "apt-get":
                steps.append(InstallStep("packages-update", "Refresh APT package metadata", tuple(prefix + [manager, "update"])))
                command = prefix + [manager, "install", "-y", *packages]
            elif manager in {"dnf", "yum"}:
                command = prefix + [manager, "install", "-y", *packages]
            elif manager == "zypper":
                command = prefix + [manager, "--non-interactive", "install", *packages]
            elif manager == "pacman":
                command = prefix + [manager, "-S", "--needed", "--noconfirm", *packages]
            else:
                command = prefix + [manager, "add", *packages]
            steps.append(InstallStep("packages", f"Install required packages with {manager}", tuple(command)))
        if need_codex:
            sh = which("sh") or "/bin/sh"
            steps.append(InstallStep(
                "codex",
                "Install Codex CLI with the official OpenAI architecture-aware installer",
                (sh, "-c", "curl -fsSL https://chatgpt.com/codex/install.sh | sh"),
            ))
        return steps

    if system == "Darwin":
        brew = which("brew")
        if (need_git or need_gh) and not brew:
            shell = "/bin/bash"
            brew_install = 'NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
            steps.append(InstallStep("homebrew", "Install Homebrew for missing macOS packages", (shell, "-c", brew_install)))
            brew = _default_brew_path(architecture)
        packages: list[str] = []
        if need_git:
            packages.append("git")
        if need_gh:
            packages.append("gh")
        if packages:
            if not brew:
                raise DependencyInstallError("Homebrew could not be resolved for automatic Git/GitHub CLI installation")
            steps.append(InstallStep("packages", "Install Git/GitHub CLI with Homebrew", (brew, "install", *packages)))
        if need_codex:
            sh = which("sh") or "/bin/sh"
            steps.append(InstallStep(
                "codex",
                "Install Codex CLI with the official OpenAI architecture-aware installer",
                (sh, "-c", "curl -fsSL https://chatgpt.com/codex/install.sh | sh"),
            ))
        return steps

    if need_git or need_gh or need_codex:
        raise DependencyInstallError(
            f"automatic dependency installation is not supported on OS={system} architecture={architecture}; "
            "the Skill remains portable, but full zero-touch review also requires upstream GitHub CLI and Codex CLI builds for this platform"
        )
    return steps


def _prepend_path(path: Path) -> None:
    value = str(path.expanduser())
    entries = [item for item in os.environ.get("PATH", "").split(os.pathsep) if item]
    if value not in entries:
        os.environ["PATH"] = os.pathsep.join([value, *entries])


def _refresh_process_path() -> None:
    home = Path.home()
    _prepend_path(home / ".local" / "bin")
    _prepend_path(home / "bin")

    if platform.system() == "Darwin":
        _prepend_path(Path("/opt/homebrew/bin"))
        _prepend_path(Path("/usr/local/bin"))
        return

    if platform.system() != "Windows":
        return

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        _prepend_path(Path(local_app_data) / "github-agent-bridge" / "bin")

    powershell = shutil.which("powershell") or shutil.which("powershell.exe") or shutil.which("pwsh")
    if not powershell:
        return
    command = (
        "$m=[Environment]::GetEnvironmentVariable('Path','Machine');"
        "$u=[Environment]::GetEnvironmentVariable('Path','User');"
        "Write-Output ($m+';'+$u)"
    )
    proc = _run([powershell, "-NoProfile", "-Command", command], True)
    if proc.returncode == 0 and proc.stdout.strip():
        persisted = [item for item in proc.stdout.strip().split(";") if item]
        current = [item for item in os.environ.get("PATH", "").split(os.pathsep) if item]
        merged: list[str] = []
        for item in [*persisted, *current]:
            if item not in merged:
                merged.append(item)
        os.environ["PATH"] = os.pathsep.join(merged)


def apply_install_plan(steps: list[InstallStep], *, runner: Runner = _run) -> None:
    for step in steps:
        proc = runner(list(step.command), False)
        if proc.returncode != 0:
            raise DependencyInstallError(
                f"dependency step `{step.name}` failed with exit code {proc.returncode}; "
                "no readiness flag was written, so rerunning the installer is safe"
            )
    _refresh_process_path()


def login_environment(
    *,
    include_codex: bool = True,
    which: Which = shutil.which,
    runner: Runner = _run,
) -> dict[str, Any]:
    _refresh_process_path()
    status = detect_environment(include_codex=include_codex, which=which, runner=runner)
    gh_path = status["gh"].get("path")
    if gh_path and not status["gh"].get("authenticated"):
        proc = runner([str(gh_path), "auth", "login", "-h", "github.com", "-w"], False)
        if proc.returncode != 0:
            raise DependencyInstallError(f"`gh auth login` failed with exit code {proc.returncode}")

    _refresh_process_path()
    status = detect_environment(include_codex=include_codex, which=which, runner=runner)
    codex_path = status["codex"].get("path")
    if include_codex and codex_path and not status["codex"].get("authenticated"):
        proc = runner([str(codex_path), "login"], False)
        if proc.returncode != 0:
            raise DependencyInstallError(f"`codex login` failed with exit code {proc.returncode}")

    _refresh_process_path()
    return detect_environment(include_codex=include_codex, which=which, runner=runner)


def format_environment_status(status: dict[str, Any]) -> str:
    def mark(value: bool) -> str:
        return "YES" if value else "NO"

    lines = [f"Platform: {status['platform']} ({status.get('architecture', 'unknown')})"]
    lines.append(f"Python >=3.9: {mark(bool(status['python']['available']))} ({status['python']['version']})")
    lines.append(f"Git: {mark(bool(status['git']['available']))}")
    lines.append(f"GitHub CLI: {mark(bool(status['gh']['available']))}; authenticated={mark(bool(status['gh']['authenticated']))}")
    if status["codex"].get("required"):
        lines.append(f"Codex CLI: {mark(bool(status['codex']['available']))}; authenticated={mark(bool(status['codex']['authenticated']))}")
    else:
        lines.append("Codex CLI: optional for dispatch-only desktop mode")
    lines.append(f"Desktop/interactive dispatch ready: {mark(bool(status['dispatch_ready']))}")
    lines.append(f"Unattended local review ready: {mark(bool(status['unattended_review_ready']))}")
    return "\n".join(lines)


def format_install_plan(steps: list[InstallStep], status: dict[str, Any], *, include_codex: bool = True) -> str:
    lines = [
        f"Detected: {status.get('platform', 'unknown')} / {status.get('architecture', 'unknown')}",
        "Planned machine changes:",
    ]
    if steps:
        for step in steps:
            lines.append(f"  - {step.description}")
    else:
        lines.append("  - no package installation required")
    if not status["gh"].get("authenticated"):
        lines.append("  - start interactive `gh auth login` for github.com")
    if include_codex and not status["codex"].get("authenticated"):
        lines.append("  - start interactive `codex login` using the user's ChatGPT account")
    return "\n".join(lines)

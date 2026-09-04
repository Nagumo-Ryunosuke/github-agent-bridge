from __future__ import annotations

import hashlib
import shutil
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any, Optional

SKILL_NAME = "github-agent-bridge"


class SkillInstallError(RuntimeError):
    pass


def skill_destination(*, scope: str, repo: Optional[Path] = None, home: Optional[Path] = None) -> Path:
    if scope == "user":
        base = home or Path.home()
        return base / ".agents" / "skills" / SKILL_NAME
    if scope == "repo":
        if repo is None:
            raise SkillInstallError("repo scope requires a repository path")
        return repo / ".agents" / "skills" / SKILL_NAME
    raise SkillInstallError("skill scope must be user or repo")


def _bundle_root():
    return resources.files("github_agent_bridge").joinpath("skill_bundle")


def _copy_traversable(source, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            _copy_traversable(child, target)
        elif child.is_file():
            target.write_bytes(child.read_bytes())


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return ""
    files = sorted((p for p in path.rglob("*") if p.is_file()), key=lambda p: p.as_posix())
    for item in files:
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = item.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _bundle_digest() -> str:
    with tempfile.TemporaryDirectory(prefix="agent-bridge-skill-digest-") as tmp:
        path = Path(tmp) / SKILL_NAME
        _copy_traversable(_bundle_root(), path)
        return _tree_digest(path)


def skill_status(
    *, scope: str = "user", repo: Optional[Path] = None, home: Optional[Path] = None
) -> dict[str, Any]:
    destination = skill_destination(scope=scope, repo=repo, home=home)
    installed = destination.is_dir() and (destination / "SKILL.md").is_file()
    current = _tree_digest(destination) if installed else ""
    expected = _bundle_digest()
    return {
        "name": SKILL_NAME,
        "scope": scope,
        "path": str(destination),
        "installed": installed,
        "up_to_date": bool(installed and current == expected),
        "installed_digest": current or None,
        "bundle_digest": expected,
    }


def install_skill(
    *,
    scope: str = "user",
    repo: Optional[Path] = None,
    home: Optional[Path] = None,
    force: bool = False,
) -> dict[str, Any]:
    destination = skill_destination(scope=scope, repo=repo, home=home)
    before = skill_status(scope=scope, repo=repo, home=home)
    if before["installed"] and before["up_to_date"] and not force:
        return before

    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.parent / f".{SKILL_NAME}.stage"
    backup = destination.parent / f".{SKILL_NAME}.backup"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    _copy_traversable(_bundle_root(), stage)
    if not (stage / "SKILL.md").is_file():
        shutil.rmtree(stage, ignore_errors=True)
        raise SkillInstallError("bundled skill is missing SKILL.md")

    try:
        if destination.exists():
            destination.rename(backup)
        stage.rename(destination)
        shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        if destination.exists() and not before["installed"]:
            shutil.rmtree(destination, ignore_errors=True)
        if backup.exists() and not destination.exists():
            backup.rename(destination)
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return skill_status(scope=scope, repo=repo, home=home)


def uninstall_skill(
    *, scope: str = "user", repo: Optional[Path] = None, home: Optional[Path] = None
) -> dict[str, Any]:
    destination = skill_destination(scope=scope, repo=repo, home=home)
    shutil.rmtree(destination, ignore_errors=True)
    result = skill_status(scope=scope, repo=repo, home=home)
    result["up_to_date"] = False
    return result

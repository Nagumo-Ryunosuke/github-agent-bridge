from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any, Iterator, Optional

from . import __version__

SKILL_NAME = "github-agent-bridge"
MARKER_NAME = ".agent-bridge-install.json"
MANAGED_BY = "github-agent-bridge"


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
    files = sorted(
        (p for p in path.rglob("*") if p.is_file() and p.name != MARKER_NAME),
        key=lambda p: p.as_posix(),
    )
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


def _read_marker(destination: Path) -> Optional[dict[str, Any]]:
    path = destination / MARKER_NAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) and raw.get("managed_by") == MANAGED_BY else None


def _write_marker(destination: Path, bundle_digest: str) -> None:
    (destination / MARKER_NAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "managed_by": MANAGED_BY,
                "package_version": __version__,
                "bundle_digest": bundle_digest,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@contextmanager
def _install_lock(parent: Path) -> Iterator[None]:
    parent.mkdir(parents=True, exist_ok=True)
    lock = parent / f".{SKILL_NAME}.install.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise SkillInstallError(
            f"another Skill install/update appears to be running: {lock}; remove the lock only if no installer is active"
        ) from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()}\n")
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def skill_status(
    *, scope: str = "user", repo: Optional[Path] = None, home: Optional[Path] = None
) -> dict[str, Any]:
    destination = skill_destination(scope=scope, repo=repo, home=home)
    exists = destination.exists()
    installed = destination.is_dir() and (destination / "SKILL.md").is_file()
    marker = _read_marker(destination) if destination.is_dir() else None
    managed = bool(marker)
    current = _tree_digest(destination) if installed else ""
    expected = _bundle_digest()
    recorded = str(marker.get("bundle_digest") or "") if marker else ""
    modified = bool(managed and installed and recorded and current != recorded)
    return {
        "name": SKILL_NAME,
        "scope": scope,
        "path": str(destination),
        "exists": exists,
        "installed": installed,
        "managed": managed,
        "modified": modified,
        "up_to_date": bool(installed and managed and current == expected),
        "installed_digest": current or None,
        "recorded_digest": recorded or None,
        "bundle_digest": expected,
        "installed_version": marker.get("package_version") if marker else None,
    }


def install_skill(
    *,
    scope: str = "user",
    repo: Optional[Path] = None,
    home: Optional[Path] = None,
    force: bool = False,
) -> dict[str, Any]:
    destination = skill_destination(scope=scope, repo=repo, home=home)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with _install_lock(destination.parent):
        before = skill_status(scope=scope, repo=repo, home=home)
        if before["installed"] and before["managed"] and before["up_to_date"] and not force:
            return before
        if before["exists"] and not before["managed"] and not force:
            raise SkillInstallError(
                f"refusing to overwrite unmanaged Skill path: {destination}; inspect it or rerun with --force"
            )
        if before["managed"] and before["modified"] and not force:
            raise SkillInstallError(
                f"refusing to overwrite locally modified managed Skill: {destination}; rerun with --force to replace it"
            )

        stage_parent = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}.stage-", dir=str(destination.parent)))
        backup_parent = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}.backup-", dir=str(destination.parent)))
        stage = stage_parent / SKILL_NAME
        backup = backup_parent / SKILL_NAME
        try:
            _copy_traversable(_bundle_root(), stage)
            if not (stage / "SKILL.md").is_file():
                raise SkillInstallError("bundled skill is missing SKILL.md")
            expected = _tree_digest(stage)
            _write_marker(stage, expected)

            if destination.exists():
                destination.rename(backup)
            try:
                stage.rename(destination)
            except Exception:
                if backup.exists() and not destination.exists():
                    backup.rename(destination)
                raise
        finally:
            shutil.rmtree(stage_parent, ignore_errors=True)
            shutil.rmtree(backup_parent, ignore_errors=True)

    return skill_status(scope=scope, repo=repo, home=home)


def uninstall_skill(
    *,
    scope: str = "user",
    repo: Optional[Path] = None,
    home: Optional[Path] = None,
    force: bool = False,
) -> dict[str, Any]:
    destination = skill_destination(scope=scope, repo=repo, home=home)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _install_lock(destination.parent):
        before = skill_status(scope=scope, repo=repo, home=home)
        if before["exists"] and not before["managed"] and not force:
            raise SkillInstallError(
                f"refusing to remove unmanaged Skill path: {destination}; rerun with --force only if deletion is intended"
            )
        if before["managed"] and before["modified"] and not force:
            raise SkillInstallError(
                f"refusing to remove locally modified managed Skill: {destination}; rerun with --force to delete it"
            )
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
    result = skill_status(scope=scope, repo=repo, home=home)
    result["up_to_date"] = False
    return result

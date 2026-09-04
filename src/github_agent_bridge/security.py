from __future__ import annotations

import re
from pathlib import Path

SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
}

SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("generic-token", re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{16,}")),
]


def scan_text(text: str) -> list[str]:
    findings: list[str] = []
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(name)
    return findings


def validate_ai_tree(repo: Path) -> list[str]:
    root = repo / ".ai"
    findings: list[str] = []
    if not root.exists():
        return findings
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in SENSITIVE_NAMES or path.name.startswith(".env"):
            findings.append(f"sensitive filename: {path.relative_to(repo)}")
            continue
        if path.stat().st_size > 1_000_000:
            findings.append(f"oversized file (>1MB): {path.relative_to(repo)}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"binary/non-UTF8 file: {path.relative_to(repo)}")
            continue
        for kind in scan_text(text):
            findings.append(f"possible {kind}: {path.relative_to(repo)}")
    return findings

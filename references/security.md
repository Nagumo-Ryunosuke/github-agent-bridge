# Security

Do not place credentials, tokens, `.env` data, private keys, or unnecessary private data in `.ai/` artifacts.

`agent-bridge validate` performs a basic secret-pattern scan. It is a guardrail, not a replacement for repository secret scanning.

## Writer least privilege

A writer should be scoped to selected repositories and branches and should not receive merge, secret-management, repository-delete, or admin privileges merely for convenience. The included MCP writer requires an explicit repository allowlist and enforces a write-branch prefix by default.

## Local review execution

Configured local tests execute code from an implementation PR. Run the watcher only on repositories/branches you trust and in an environment appropriate for code execution. The watcher rejects cross-repository PRs and untrusted branch prefixes by default, but these checks are not a sandbox.

Final merge stays human-controlled by default.

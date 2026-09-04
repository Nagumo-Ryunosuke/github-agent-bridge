# Cross-platform Codex operation

`github-agent-bridge` keeps the Skill and watcher independent of the Codex surface.

## Skill discovery

Install the user Skill once:

```bash
agent-bridge skill install --scope user
```

The destination is `$HOME/.agents/skills/github-agent-bridge`. Codex App, CLI and IDE clients use the same user-level skill root. If a newly installed Skill is not visible immediately, restart the Codex client.

Use `--scope repo` only when you intentionally want a repository-local copy at `.agents/skills/github-agent-bridge`.

## Watcher service

```bash
agent-bridge service install
agent-bridge service status
agent-bridge service restart
agent-bridge service uninstall
```

`service install` uses the current Python interpreter so the background process imports the same installed `github-agent-bridge` package.

### Linux

Uses a per-user `systemd --user` unit under `~/.config/systemd/user`. No root service is installed. The Linux automatic backend requires a working user systemd manager.

### macOS

Uses a per-user LaunchAgent under `~/Library/LaunchAgents` and `launchctl bootstrap gui/<uid>`.

### Windows

Uses a per-user Task Scheduler task with `LIMITED` run level. A generated `.cmd` wrapper enters the repository and starts the watcher. Runtime liveness is still determined by the Git-private watcher heartbeat rather than localized Task Scheduler status text.

## Logs and identity

Each repository gets a stable service slug derived from its resolved local path. Logs and a service manifest live in a per-user state directory. Multiple repositories can therefore install independent watchers.

`agent-bridge doctor` remains the final source of truth for zero-touch readiness because it checks the watcher heartbeat in addition to configuration and executable availability.

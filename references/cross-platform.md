# Cross-platform Codex App / CLI setup

The bridge separates **Skill discovery** from the **persistent local watcher** so Codex App, CLI and IDE clients can share the same workflow.

## 1. Install the Skill once for the user

```bash
agent-bridge skill install --scope user
agent-bridge skill status --scope user
```

The installer copies real files to:

```text
$HOME/.agents/skills/github-agent-bridge
```

This is the Codex USER Skill location. Real files are used rather than a symlinked `SKILL.md`. Restart the Codex client if a newly installed Skill is not shown immediately.

A repository-local copy is also supported when desired:

```bash
agent-bridge skill install --scope repo
```

which writes `.agents/skills/github-agent-bridge` in the current repository.

## 2. Install the persistent reviewer service

From each repository that should receive automatic Codex reviews:

```bash
agent-bridge service install
agent-bridge service status
```

The default `auto` backend maps to:

| Platform | Backend | Scope |
| --- | --- | --- |
| Linux | `systemd --user` | current user |
| macOS | LaunchAgent / `launchctl` | current GUI user |
| Windows | Task Scheduler | current user, LIMITED run level |

The service uses the Python interpreter that executed `agent-bridge service install`; installation fails if that interpreter cannot import `github_agent_bridge`.

### Linux

The unit is written under `~/.config/systemd/user`. v1.4 requires a working user systemd manager for automatic Linux startup. If Codex is running inside WSL, enable WSL systemd or run the bridge from native Windows and use the Windows Task Scheduler backend.

### macOS

A LaunchAgent plist is written under `~/Library/LaunchAgents`, bootstrapped into `gui/<uid>`, and configured to restart the watcher after failures.

### Windows

A per-user scheduled task is created with `ONLOGON` and `LIMITED` run level. A generated `.cmd` wrapper changes to the repository before starting the watcher. The task does not require repository-admin or machine-admin privileges.

## 3. Runtime truth

Service-manager state is useful operational information, but `agent-bridge doctor` remains authoritative because it verifies the watcher's Git-private heartbeat in addition to GitHub access, Codex availability, writer scope, Work triggers and test policy.

```bash
agent-bridge service status
agent-bridge doctor
```

## 4. Maintenance

```bash
agent-bridge service restart
agent-bridge service uninstall
agent-bridge skill uninstall --scope user
```

Each repository has a distinct service identity derived from its resolved local path, so multiple repositories can run independent watchers for the same user.

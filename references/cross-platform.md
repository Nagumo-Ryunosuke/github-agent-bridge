# Cross-platform Codex App / CLI setup

`github-agent-bridge` separates **Skill discovery** from the **persistent local reviewer**, while giving both a single cross-platform bootstrap path.

## Recommended first install

No clone is required.

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/Nagumo-Ryunosuke/github-agent-bridge/main/scripts/bootstrap.ps1 | iex
```

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/Nagumo-Ryunosuke/github-agent-bridge/main/scripts/bootstrap.sh | bash
```

The bootstrap displays one consolidated machine-change confirmation, creates a private user virtual environment, installs/updates the bridge and shared Skill, detects missing local tooling, installs supported dependencies, then starts missing GitHub/Codex login flows.

Authentication and elevation are not bypassed. `sudo`, `gh auth login`, `codex login`, GitHub write confirmation and unattended-write confirmation remain user-controlled security boundaries.

## Environment self-check

After the package exists, the Skill should prefer these commands over a manual dependency checklist:

```bash
agent-bridge env status
agent-bridge env install
```

After the user approves the consolidated plan:

```bash
agent-bridge env install --yes
```

For Desktop-only task dispatch where the unattended reviewer is intentionally disabled:

```bash
agent-bridge env status --skip-codex
agent-bridge env install --skip-codex
```

This is not full zero-touch readiness because the persistent reviewer invokes `codex exec --ephemeral`.

## Shared Skill discovery

The recommended user Skill location is:

```text
$HOME/.agents/skills/github-agent-bridge
```

Install/update manually when needed:

```bash
agent-bridge skill install --scope user
agent-bridge skill status --scope user
```

Codex Desktop/App, Codex CLI and supported IDE clients share this user-level Skill root. Restart the client after first installation or an update if the Skill is not visible immediately.

Repository-local installation remains available:

```bash
agent-bridge skill install --scope repo
```

## Platform / architecture strategy

The Python bridge itself is architecture-neutral. The installer detects the operating system/CPU and delegates architecture-specific binaries to supported package managers and official upstream installers.

### Windows

- Python/Git/GitHub CLI: WinGet where installation is required.
- Codex CLI: official OpenAI PowerShell installer.
- Persistent reviewer: per-user Task Scheduler task with `LIMITED` run level.

### Linux

Package-manager detection covers:

```text
apt-get / dnf / yum / zypper / pacman / apk
```

Codex CLI is installed through the official OpenAI architecture-aware shell installer. The persistent reviewer uses `systemd --user` when available.

If the machine is WSL, either enable a working user systemd manager or run the bridge natively on Windows and use Task Scheduler.

### macOS

The bootstrap uses the existing Python/Homebrew environment as needed and the persistent reviewer uses a LaunchAgent under `~/Library/LaunchAgents`.

Full automation is bounded by upstream availability. If Python, GitHub CLI or Codex CLI does not provide a usable package/binary for a particular OS/CPU, the bridge must report the missing upstream capability instead of claiming success.

## Persistent reviewer service

From each repository that should receive automatic reviews:

```bash
agent-bridge service install
agent-bridge service status
agent-bridge service restart
agent-bridge service uninstall
```

The service uses the Python interpreter that executed `agent-bridge service install` and each repository gets a distinct service identity derived from its resolved local path.

## Runtime truth

Service-manager state alone is not enough. The final readiness source of truth is:

```bash
agent-bridge doctor
```

`Zero-touch ready: YES` requires the local executables/authentication, repository access, writer scope, Work triggers, test policy and a fresh long-running watcher heartbeat to all be ready.

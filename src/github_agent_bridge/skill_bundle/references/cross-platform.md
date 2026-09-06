# Cross-platform Codex operation

`github-agent-bridge` keeps Skill discovery and the persistent reviewer portable across Codex Desktop/App, Codex CLI and IDE clients.

## One-command first install

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/Nagumo-Ryunosuke/github-agent-bridge/main/scripts/bootstrap.ps1 | iex
```

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/Nagumo-Ryunosuke/github-agent-bridge/main/scripts/bootstrap.sh | bash
```

The bootstrap asks once for the consolidated machine changes, then creates a private user environment, installs the bridge, installs the shared Skill, installs missing supported dependencies and starts missing authentication flows.

Do not bypass `sudo`, `gh auth login`, `codex login`, GitHub write confirmation or unattended-write confirmation.

## Self-healing environment flow

When the Skill is invoked, prefer:

```bash
agent-bridge env status
```

If prerequisites are incomplete, show the consolidated plan once and, after approval, run:

```bash
agent-bridge env install --yes
```

Then re-run `agent-bridge env status` before continuing.

For an intentional Desktop-only dispatch setup where background Codex review is disabled:

```bash
agent-bridge env status --skip-codex
```

Do not describe this as full zero-touch readiness: the persistent reviewer invokes `codex exec --ephemeral` and therefore requires Codex CLI.

## Shared Skill root

The user Skill is installed at:

```text
$HOME/.agents/skills/github-agent-bridge
```

Codex Desktop/App, CLI and IDE clients share that location. Restart the Codex client after first install/update if necessary.

Manual maintenance:

```bash
agent-bridge skill install --scope user
agent-bridge skill status --scope user
```

Repository-local installation is available with `--scope repo`.

## Platform behavior

- Windows: WinGet/official installers; watcher uses a per-user Task Scheduler task.
- Linux: package-manager detection covers apt-get, dnf, yum, zypper, pacman and apk; watcher uses `systemd --user`.
- macOS: native/Homebrew tooling as needed; watcher uses a LaunchAgent.

The bridge itself does not hard-code a CPU architecture. Full automation is limited only by actual upstream Python, GitHub CLI and Codex CLI availability for the target OS/CPU. Report unsupported upstream combinations precisely instead of pretending readiness.

## Persistent reviewer

```bash
agent-bridge service install
agent-bridge service status
agent-bridge service restart
agent-bridge service uninstall
```

The service uses the same Python interpreter that installed it and each repository gets an independent service identity.

`agent-bridge doctor` is the final runtime source of truth because it checks executable/authentication readiness and the watcher's Git-private heartbeat in addition to repository configuration.

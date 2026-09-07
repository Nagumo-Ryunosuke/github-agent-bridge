# github-agent-bridge

**One Skill for Codex Desktop/App, Codex CLI and IDE clients. One bootstrap command installs the bridge, shared Skill and required local tooling, then the Skill self-checks the machine and asks only for security-sensitive confirmations that cannot be inferred.**

`github-agent-bridge` coordinates a GitHub-mediated development loop:

```text
Codex local analysis / dispatch
        ↓
GitHub Task PR
        ↓
ChatGPT Work implementation + tests + self-review
        ↓
Implementation PR
        ↓
Local watcher + real tests + codex exec review
        ↓
APPROVE → human merge
REVISE  → ChatGPT fixes → re-review
```

## One-command install

You do **not** need to clone this repository first.

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/Nagumo-Ryunosuke/github-agent-bridge/main/scripts/bootstrap.ps1 | iex
```

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/Nagumo-Ryunosuke/github-agent-bridge/main/scripts/bootstrap.sh | sh
```

The Unix bootstrap is POSIX-sh compatible, so it does not require Bash on minimal Linux distributions.

The bootstrap shows one consolidated machine-change confirmation and then, as needed:

- installs Python >= 3.9;
- creates a private per-user virtual environment;
- installs/updates `github-agent-bridge`;
- installs Git and GitHub CLI (`gh`);
- installs Codex CLI using the official OpenAI installer or supported native tooling;
- installs the shared Skill at `$HOME/.agents/skills/github-agent-bridge`;
- starts `gh auth login` and `codex login` when authentication is missing.

GitHub authorization, ChatGPT/Codex login, OS elevation and explicit repository write/unattended-write attestations are intentionally **not bypassed**.

After installation, restart Codex Desktop/App or Codex CLI so it reloads the Skill.

Then open any target Git repository and say:

> Use `$github-agent-bridge` for this requirement. Let ChatGPT implement it, let Codex run local tests and review it, and leave the final merge to me.

中文可直接说：

> 使用 `$github-agent-bridge`，为“我的需求”创建并发布任务，由 ChatGPT 实现，Codex 本地测试和审查，最后由我合并。

仅有 GitHub remote URL 时，安装 CLI 后可直接接入仓库：

```bash
agent-bridge connect https://github.com/OWNER/REPO.git
```

该命令会验证当前 GitHub 账号的仓库写权限，克隆或恢复本地 checkout，初始化 `.ai/`、识别测试命令并安装仓库级 Skill。重复执行会保留已有代码和桥接状态；URL 中不允许凭据，仓库不允许写入时会在克隆前停止。

## What happens automatically when the Skill is used

The installed Skill follows a self-bootstrap contract:

```text
$github-agent-bridge invoked
        ↓
agent-bridge env status
        ↓
missing local dependency?
   ├─ no  → repository setup/doctor
   └─ yes → show one consolidated install plan
               ↓
            user confirms
               ↓
        agent-bridge env install --yes
               ↓
        re-check environment
               ↓
        infer repository + tests
               ↓
        setup bootstrap / doctor
               ↓
        dispatch task
```

The Skill should not respond with a long manual checklist such as “install Git, then install gh, then install Codex”. It should detect the machine, consolidate safe installation changes into one approval, perform them, re-check readiness, and continue.

Useful environment commands:

```bash
agent-bridge env status
agent-bridge env install
agent-bridge env install --yes
```

For Desktop-only dispatch without the unattended local reviewer:

```bash
agent-bridge env status --skip-codex
agent-bridge env install --skip-codex
```

`--skip-codex` is **not** full zero-touch readiness. The persistent reviewer calls `codex exec --ephemeral`, so Codex CLI remains a runtime dependency even if you normally work only in Codex Desktop.

## Platform and architecture model

The bridge itself is pure Python and does not hard-code x86 installation paths. Bootstrap detects the OS/CPU and delegates architecture-specific binaries to upstream package managers/installers.

Primary tested operating systems:

| OS | Bootstrap / service backend |
| --- | --- |
| Windows | PowerShell + WinGet / per-user Task Scheduler |
| Linux | detected package manager / `systemd --user` |
| macOS | POSIX shell + native/Homebrew tooling / LaunchAgent |

Linux package-manager detection currently covers:

```text
apt-get / dnf / yum / zypper / pacman / apk
```

The goal is architecture-neutral behavior, but full automation cannot exceed upstream availability. If GitHub CLI, Python or Codex CLI has no usable build/package for a particular OS/CPU, the bridge must report that exact boundary rather than claiming deployment success.

## Shared Skill location

A user installation writes real files to:

```text
$HOME/.agents/skills/github-agent-bridge
```

The same directory is used by the supported local Codex surfaces:

```text
                 ~/.agents/skills/github-agent-bridge
                            │
              ┌─────────────┼─────────────┐
              ↓             ↓             ↓
       Codex Desktop     Codex CLI      Codex IDE
```

Manual Skill maintenance remains available:

```bash
agent-bridge skill install --scope user
agent-bridge skill status --scope user
agent-bridge skill uninstall --scope user
```

Repository-local Skill installation is optional:

```bash
agent-bridge skill install --scope repo
```

## Repository bootstrap

When `$github-agent-bridge` is used inside a real target repository, it should inspect the repository and infer a genuine local test command from existing project tooling whenever possible.

Manual equivalent:

```bash
agent-bridge setup bootstrap \
  --mode managed \
  --connection-name github-agent-bridge-writer \
  --test-command 'python -m unittest discover -s tests -v'
```

Do **not** blindly set these flags:

```text
--confirm-write
--confirm-unattended
--confirm-work-trigger
```

They are safety attestations. The Skill should ask only when the relevant capability actually needs human confirmation and should never fabricate the confirmation.

Bootstrap initializes `.ai/`, infers `owner/repo` from a `github.com` origin when possible, configures reviewer policy, and reports any remaining platform step.

## GitHub / ChatGPT event triggers

The unattended loop requires two repository-scoped ChatGPT Work triggers:

1. Task PR opened/ready + `agent-bridge:task` marker → ChatGPT implements.
2. PR comment containing `agent-bridge:codex-review` and `verdict=REVISE` → ChatGPT fixes.

After they have actually been created and verified:

```bash
agent-bridge setup work-trigger --confirm
```

The bridge must not mark this step complete merely because configuration files exist.

## Persistent local reviewer

From each target repository:

```bash
agent-bridge service install
agent-bridge service status
```

Automatic backend:

| Platform | Backend | Privilege |
| --- | --- | --- |
| Linux | `systemd --user` | current user |
| macOS | LaunchAgent / `launchctl` | current GUI user |
| Windows | Task Scheduler | current user, `LIMITED` |

Fallback:

```bash
agent-bridge watch
```

The watcher checks each eligible Implementation PR head SHA once, creates an isolated temporary worktree, runs configured authoritative local tests, invokes structured `codex exec --ephemeral`, and posts `APPROVE` or `REVISE` feedback.

## Readiness gate

Run:

```bash
agent-bridge doctor
```

Full unattended operation is ready only when it reports:

```text
Zero-touch ready: YES
```

The readiness gate checks, among other things:

- bridge initialization;
- GitHub origin and repository access;
- GitHub CLI installation/authentication;
- Codex CLI availability and `codex login status` authentication;
- ChatGPT/GitHub writer capability and unattended policy confirmation;
- repository allowlist;
- repository-scoped Work trigger confirmation;
- real local test policy;
- trusted implementation branch prefix;
- fresh long-running watcher heartbeat;
- human final-merge gate.

## Writer modes

ChatGPT needs a write path to create/update an implementation PR.

### `managed`

Recommended when ChatGPT has an already connected, write-capable GitHub connection.

```bash
agent-bridge setup writer \
  --mode managed \
  --connection-name github-agent-bridge-writer \
  --repository OWNER/REPO
```

Only after the actual capability is tested should the operator attest:

```bash
agent-bridge setup writer \
  --mode managed \
  --connection-name github-agent-bridge-writer \
  --repository OWNER/REPO \
  --confirm-write \
  --confirm-unattended
```

### `custom-mcp`

The optional writer MCP exposes least-privilege branch/file/PR/comment operations and intentionally omits merge, secrets, repository deletion and admin settings.

```bash
pip install 'github-agent-bridge[mcp]'
export AGENT_BRIDGE_ALLOWED_REPOS='OWNER/REPO'
export AGENT_BRIDGE_BRANCH_PREFIX='ai/'
agent-bridge-mcp
```

### `readonly`

```bash
agent-bridge setup writer --mode readonly
```

In this mode ChatGPT may plan or produce a patch, but must not claim it pushed code.

## Task lifecycle

Manual equivalent of what the Skill dispatches:

```bash
agent-bridge task create \
  --title 'Refactor tag synchronization' \
  --objective 'Unify scheduled sync, manual repair, and reconciliation.' \
  --assigned-to chatgpt \
  --reviewer codex \
  --priority high

agent-bridge drift TASK-000001
agent-bridge validate
agent-bridge publish task TASK-000001
```

ChatGPT then implements on an exact-base implementation branch and opens/updates the marked implementation PR. Codex watcher reviews each new exact head SHA. `REVISE` routes back to ChatGPT; `APPROVE` leaves the final merge to the human.

## Security boundaries

Default separation:

- **ChatGPT writer:** branch/file/PR/comment writes only.
- **Codex watcher:** local checkout, configured test execution, review/comment.
- **Human:** final merge/acceptance.

Recommended GitHub repository permissions:

```text
Metadata       read
Contents       write
Pull requests  write
Issues         write
Actions        read
```

Do not grant repository administration, secrets, deletion or merge powers merely to simplify setup.

Local tests execute implementation PR code. Use an appropriate machine/container/VM for untrusted code.

## Development / CI

The unit suite runs on Linux, macOS and Windows across Python 3.9, 3.11 and 3.13. Python 3.11 jobs also build the wheel and verify that the bundled Skill assets are included. CI additionally parses both bootstrap scripts so syntax regressions are caught on their native platforms.

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
sh -n scripts/bootstrap.sh
```

## Useful commands

```bash
agent-bridge env status
agent-bridge env install
agent-bridge skill status --scope user
agent-bridge service status
agent-bridge status
agent-bridge capabilities
agent-bridge doctor
agent-bridge doctor --json
agent-bridge watch --once
agent-bridge validate
```

See also:

- `SKILL.md`
- `references/bootstrap.md`
- `references/cross-platform.md`
- `references/automation.md`
- `references/writer-modes.md`
- `references/protocol.md`
- `references/security.md`

## License

MIT

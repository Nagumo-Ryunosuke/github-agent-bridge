# github-agent-bridge

**One Skill for Codex Desktop/App, Codex CLI and IDE clients. One bootstrap command installs the bridge, shared Skill and required local tooling. Development reasoning stays in a normal ChatGPT Web Chat; Work is optional and broker-only unless the user explicitly approves a bounded delegation.**

`github-agent-bridge` coordinates a GitHub-mediated development loop:

```text
Codex local analysis / dispatch
        ↓
GitHub Task PR
        ↓
optional ChatGPT Work event broker
        ↓
compact task handoff
        ↓
normal ChatGPT Web Chat
  design + implementation + tests + self-review
        ↓
Implementation PR
        ↓
Local watcher + real tests + codex exec review
        ↓
APPROVE → human merge
REVISE  → optional broker handoff → Chat fixes → re-review
```

## Resource-control model

ChatGPT Web Chat is the primary development surface.

A normal Chat **must never automatically invoke, create, switch to, or delegate implementation to Work** merely because a task is complex or Work is available.

Before any ad-hoc Chat-to-Work delegation:

1. Chat explains the exact capability gap.
2. Chat describes the bounded operation proposed for Work.
3. Chat asks whether the user permits that Work run.
4. Chat asks which model/reasoning level to use when the platform exposes that choice.
5. Chat must not default to the newest, strongest, or most expensive model.
6. If model selection is unavailable, Chat must disclose that the platform default Work model would be used and ask whether to proceed.
7. Work may start only after explicit approval, and control returns to Chat afterward.

Approval is per operation, not blanket permission.

GitHub event-triggered Work tasks are a separate pre-authorized automation case. They are **brokers only**: parse the GitHub event, identify the Task/PR/review state, produce a compact handoff for Chat, and stop. They must not design, edit code, run broad tests, use the GitHub writer, create/update implementation PRs, start another Work task, or escalate model/reasoning level.

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
- starts `gh auth login -w` and `codex login` when authentication is missing. Both flows use the system default browser.

GitHub authorization, ChatGPT/Codex login, OS elevation and explicit repository write/unattended-write attestations are intentionally **not bypassed**.

After installation, restart Codex Desktop/App or Codex CLI so it reloads the Skill.

Then open any target Git repository and say:

> Use `$github-agent-bridge` for this requirement. Let ChatGPT Web Chat design and implement it, let Codex run local tests and review it, and leave the final merge to me. Do not use Work unless I explicitly approve a bounded operation and model/reasoning choice.

中文可直接说：

> 使用 `$github-agent-bridge`，为“我的需求”创建并发布任务，由 ChatGPT Web 普通 Chat 负责设计和实现，Codex 本地测试和审查，最后由我合并。不要自动调用 Work；如确实需要 Work，必须先说明用途并询问我是否允许以及使用什么模型/推理级别。

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
               ↓
        normal ChatGPT Web Chat owns implementation
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

`--skip-codex` is **not** full reviewer readiness. The persistent reviewer calls `codex exec --ephemeral`, so Codex CLI remains a runtime dependency even if you normally work only in Codex Desktop.

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

Full automation cannot exceed upstream availability. If GitHub CLI, Python or Codex CLI has no usable build/package for a particular OS/CPU, the bridge must report that exact boundary rather than claiming deployment success.

## Shared Skill location

A user installation writes real files to:

```text
$HOME/.agents/skills/github-agent-bridge
```

The same directory is used by supported local Codex surfaces:

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

## Optional GitHub / Work event brokers

The bridge can use two repository-scoped GitHub event-triggered Work tasks as lightweight brokers:

1. Task PR opened/ready + `agent-bridge:task` marker → prepare a compact implementation handoff for a normal ChatGPT Web Chat.
2. PR comment containing `agent-bridge:codex-review` and `verdict=REVISE` → prepare a compact revision handoff for Chat.

Before either broker is enabled:

- show the user the intended Work model/reasoning level and obtain explicit approval;
- prefer the least costly option that can reliably parse the event and prepare the handoff;
- never default to the newest/strongest model;
- if the platform does not expose model selection, disclose that the platform default Work model will be used and ask whether to continue.

The generated broker policy explicitly forbids architecture/design work, code edits, tests, writer use, implementation PR writes, recursive Work calls and model escalation.

Render the setup text with:

```bash
agent-bridge trigger automation-setup
```

After the two brokers have actually been created and model-approved:

```bash
agent-bridge setup work-trigger --confirm
```

This confirmation authorizes only the broker role. It never authorizes primary Work implementation or future automatic Chat-to-Work delegation.

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
| Windows | Task Scheduler | current user, `LIMITED` run level |

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

`Zero-touch ready: YES` means the configured transport/writer/reviewer automation checks pass. It does **not** mean Work is authorized to perform primary implementation and it does not remove the normal Chat development step.

The readiness gate checks, among other things:

- bridge initialization;
- GitHub origin and repository access;
- GitHub CLI installation/authentication;
- Codex CLI availability and authentication;
- ChatGPT/GitHub writer capability and unattended policy confirmation;
- repository allowlist;
- optional repository-scoped Work broker confirmation;
- real local test policy;
- trusted implementation branch prefix;
- fresh long-running watcher heartbeat;
- human final-merge gate.

## Writer modes

ChatGPT Web Chat needs a write path to create/update an implementation PR.

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

ChatGPT Web Chat then implements on an exact-base implementation branch and opens/updates the marked implementation PR. Codex watcher reviews each new exact head SHA. `REVISE` routes back to Chat; an optional Work broker may summarize the event but must not fix the branch. `APPROVE` leaves the final merge to the human.

## Security boundaries

Default separation:

- **ChatGPT writer:** branch/file/PR/comment writes only.
- **Work broker:** event parsing/handoff only unless the user explicitly approves a separate bounded operation and model/reasoning choice.
- **Codex watcher:** local checkout, configured test execution, review/comment.
- **Human:** Work delegation approval and final merge/acceptance.

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

The unit suite runs on Linux, macOS and Windows across Python 3.9, 3.11 and 3.13. Python 3.11 jobs also build the wheel and verify that the bundled Skill assets are included.

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
agent-bridge trigger automation-setup
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

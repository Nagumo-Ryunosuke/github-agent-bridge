# github-agent-bridge

**GitHub carries durable context and events. ChatGPT Web/Work does high-quality planning and primary implementation. Codex performs local review, debugging, and real-environment verification.**

`github-agent-bridge` is a GitHub-native automation protocol for splitting software work across ChatGPT and Codex without repeatedly copying prompts between products.

## Target workflow

```text
User / local Codex
        |
        | analyze requirement, inspect real repo
        v
Task contract @ exact base commit
        |
        | agent-bridge publish task
        v
GitHub Task PR
        |
        | event-triggered ChatGPT Work task
        v
ChatGPT Web/Work
        |
        | architecture + implementation + tests + self-review
        v
Implementation PR
        |
        | persistent local watcher sees each new head SHA once
        v
Codex local review
        |
        +-- authoritative local tests
        +-- exact diff + surrounding code
        +-- structured adversarial review
        |
        +-- APPROVE --> human merge
        |
        +-- REVISE --> machine-marked PR comment
                            |
                            | GitHub comment trigger
                            v
                    ChatGPT Work fixes
                            |
                            +--> new PR head --> Codex re-review
```

GitHub PR head SHA is the live implementation truth. Task contracts stay pinned to an exact base commit; watcher deduplication and heartbeat are stored in Git-private state.

## v1.4: one Skill for Codex App, CLI and IDE

Codex loads user Skills from `$HOME/.agents/skills`. Install the bundled Skill once:

```bash
agent-bridge skill install --scope user
agent-bridge skill status --scope user
```

The installer copies real files to:

```text
$HOME/.agents/skills/github-agent-bridge
```

so Codex App, Codex CLI and IDE clients can use the same Skill. If a newly installed Skill is not visible immediately, restart the Codex client.

A repository-local copy is optional:

```bash
agent-bridge skill install --scope repo
```

which writes `.agents/skills/github-agent-bridge` in the current repository.

## Fast setup: bootstrap + persistent service + doctor

Install the CLI/package, then bootstrap the repository:

```bash
python -m pip install -e .

agent-bridge setup bootstrap \
  --mode managed \
  --connection-name github-agent-bridge-writer \
  --confirm-write \
  --confirm-unattended \
  --test-command 'python -m unittest discover -s tests -v' \
  --test-command 'python -m compileall -q src tests'
```

Bootstrap initializes `.ai/`, infers `owner/repo` from a github.com `origin` when possible, configures writer/reviewer policy, and prints the one ChatGPT platform step that cannot currently be created through a public CLI/API.

Create the two GitHub event-triggered tasks once in **ChatGPT Work on Web, iOS, or Android**:

1. Task PR opened/ready + `agent-bridge:task` → ChatGPT implements.
2. Codex PR comment containing `agent-bridge:codex-review` and `verdict=REVISE` → ChatGPT fixes.

Then record that setup:

```bash
agent-bridge setup work-trigger --confirm
```

Install the persistent local Codex reviewer:

```bash
agent-bridge service install
agent-bridge service status
```

Automatic service backend:

| Platform | Backend | Privilege scope |
| --- | --- | --- |
| Linux | `systemd --user` | current user |
| macOS | LaunchAgent / `launchctl` | current GUI user |
| Windows | Task Scheduler | current user, `LIMITED` |

Finally verify the whole loop:

```bash
agent-bridge doctor
```

```text
Zero-touch ready: YES
```

is the readiness gate. `doctor` verifies GitHub origin/access, `gh`, Codex CLI, writer scope, unattended permissions, Work-trigger repository scope, local test policy, trusted branch policy, and a fresh long-running watcher heartbeat.

## Service commands

```bash
agent-bridge service install
agent-bridge service status
agent-bridge service restart
agent-bridge service uninstall
```

The service is per repository. Its identity is derived from the resolved local repository path, so one user can run independent watchers for multiple repos.

The service uses the same Python interpreter that ran `service install`; installation fails if that interpreter cannot import `github_agent_bridge`.

### Linux

v1.4 uses a per-user systemd unit under `~/.config/systemd/user` and requires a working `systemd --user` manager. If Codex is running in WSL, enable WSL systemd or use a native Windows installation and the Task Scheduler backend.

### macOS

v1.4 installs a per-user LaunchAgent under `~/Library/LaunchAgents` and loads it with `launchctl`.

### Windows

v1.4 installs a per-user Task Scheduler task with `ONLOGON` and `LIMITED` run level. A generated `.cmd` wrapper enters the target repository and launches the watcher. Runtime liveness is still determined by the watcher heartbeat rather than localized Task Scheduler text.

See `references/cross-platform.md`.

## Writer modes

ChatGPT needs a write path to turn its design into an implementation PR.

### `managed` — recommended lazy mode

Use a pre-connected **write-capable** GitHub app/connection and authorize it once:

```bash
agent-bridge setup writer \
  --mode managed \
  --connection-name github-agent-bridge-writer \
  --confirm-write \
  --confirm-unattended \
  --repository OWNER/REPO
```

`--confirm-write` and `--confirm-unattended` are operator attestations. Do not set them until the actual connection has been tested. Changing writer backend or repository scope invalidates stored confirmations.

The standard read/search GitHub connection should not be treated as a writer just because all repositories were selected.

### `custom-mcp` — BYO MCP mode

This repository includes an optional minimal GitHub Writer MCP adapter:

```bash
pip install 'github-agent-bridge[mcp]'
export AGENT_BRIDGE_ALLOWED_REPOS='OWNER/REPO'
export AGENT_BRIDGE_BRANCH_PREFIX='ai/'
agent-bridge-mcp
```

Then configure:

```bash
agent-bridge setup writer \
  --mode custom-mcp \
  --mcp-server github-agent-bridge-writer \
  --confirm-write \
  --confirm-unattended \
  --repository OWNER/REPO
```

The MCP writer exposes repository/file reads, PR-comment reads, exact-SHA branch creation, atomic multi-file commits, PR create/update and PR comments. It does **not** expose merge, secrets, repository deletion or admin settings.

### `readonly`

ChatGPT can plan/review and produce patches, but must not claim it pushed code:

```bash
agent-bridge setup writer --mode readonly
```

## Starting a task from Codex

Codex should inspect the real local repository first and create a task whose primary developer is ChatGPT:

```bash
agent-bridge task create \
  --title 'Refactor tag synchronization' \
  --objective 'Unify scheduled sync, manual repair, and reconciliation.' \
  --assigned-to chatgpt \
  --reviewer codex \
  --priority high
```

Then dispatch without disturbing the current worktree:

```bash
agent-bridge drift TASK-000001
agent-bridge validate
agent-bridge publish task TASK-000001
```

The Task PR is the GitHub event that wakes ChatGPT Work.

## ChatGPT implementation contract

ChatGPT must:

- read the exact task/base/context;
- design before coding;
- branch from the exact pinned base commit;
- implement and add tests;
- self-review once before handoff;
- publish/update a marked implementation PR;
- never merge the PR itself.

Render the policy when needed:

```bash
agent-bridge trigger work-prompt TASK-000001 --phase implement
agent-bridge trigger work-prompt TASK-000001 --phase fix
```

## Codex local reviewer

For each eligible implementation PR head, the watcher:

1. rejects cross-repository PRs;
2. enforces the trusted implementation branch prefix (`ai/` by default);
3. verifies the PR head descends from the task's pinned base commit;
4. checks out the exact head in a temporary worktree;
5. runs configured local test commands;
6. invokes structured `codex exec --ephemeral` review;
7. locally validates the JSON output;
8. treats real test evidence as authoritative;
9. posts a machine-marked `APPROVE` or `REVISE` comment;
10. reviews each exact head SHA once.

A failing or missing required local test prevents unattended approval even if the model says `APPROVE`.

## Security boundaries

Default separation:

- **ChatGPT writer:** branch/file/PR/comment writes only.
- **Codex watcher:** local checkout, configured test execution, review/comment.
- **Human:** final merge/acceptance.

Recommended GitHub permissions:

```text
Metadata       read
Contents       write
Pull requests  write
Issues         write
Actions        read
```

Do not grant repository administration, secrets, deletion or merge powers just to simplify setup.

Local tests execute implementation PR code. Run the watcher on an appropriate machine/container/VM even though it rejects cross-repository PRs, enforces a trusted branch prefix and checks pinned-base ancestry.

## CI / platform support

v1.4 CI runs the full unit suite on:

- Linux
- macOS
- Windows

across Python 3.9, 3.11 and 3.13. Python 3.11 jobs additionally build a wheel and verify that the packaged Skill assets are present.

## Useful commands

```bash
agent-bridge skill install --scope user
agent-bridge skill status --scope user
agent-bridge service install
agent-bridge service status
agent-bridge status
agent-bridge capabilities
agent-bridge doctor
agent-bridge doctor --json
agent-bridge watch --once
agent-bridge validate
```

See:

- `references/bootstrap.md`
- `references/cross-platform.md`
- `references/automation.md`
- `references/writer-modes.md`
- `references/protocol.md`
- `references/security.md`

## License

MIT

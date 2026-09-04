# github-agent-bridge

**GitHub carries durable context and events. ChatGPT Web/Work does high-quality planning and primary implementation. Codex performs local review, debugging, and real-environment verification.**

`github-agent-bridge` is a GitHub-native automation protocol for splitting software work across ChatGPT and Codex without requiring the user to repeatedly copy prompts between products.

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
ChatGPT Web/Work (highest suitable model)
        |
        | architecture + implementation + tests + self-review
        v
Implementation PR  <!-- agent-bridge:implementation ... -->
        |
        | local watcher sees each new head SHA once
        v
Codex local review
        |
        +-- run trusted local test commands
        +-- inspect exact diff and surrounding code
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

The live implementation truth is the **GitHub PR head SHA**. Task contracts remain pinned to a base commit; local watcher deduplication is stored under Git's private metadata rather than committed into `.ai/`.

## Writer modes

ChatGPT needs a write path to turn its design into an implementation PR. The bridge exposes three modes:

### 1. `managed` — recommended lazy mode

Use a **pre-connected write-capable GitHub app/connection** and authorize it once. The user can then let ChatGPT Work use the connection for branches, file commits, PRs, and comments.

```bash
agent-bridge setup writer \
  --mode managed \
  --connection-name github-agent-bridge-writer \
  --confirm-write \
  --confirm-unattended \
  --repository OWNER/REPO
```

`--confirm-write` and `--confirm-unattended` are operator attestations: the CLI cannot introspect another ChatGPT session's OAuth/tool-confirmation policy. Do not set them until the connection has actually been tested.

**Important:** the standard OpenAI-built GitHub app is search/read oriented and should not be treated as a writer merely because all repositories were selected. Managed mode expects a connection that actually exposes write actions.

### 2. `custom-mcp` — BYO MCP mode

Use your own remote MCP writer. This repo includes an optional minimal GitHub Writer MCP adapter backed by authenticated `gh`:

```bash
pip install 'github-agent-bridge[mcp]'
export AGENT_BRIDGE_ALLOWED_REPOS='OWNER/REPO'
# Optional when your implementation branch policy differs from the default ai/
export AGENT_BRIDGE_BRANCH_PREFIX='ai/'
agent-bridge-mcp
```

Expose it through a supported remote MCP deployment/tunnel, connect it in ChatGPT, then configure:

```bash
agent-bridge setup writer \
  --mode custom-mcp \
  --mcp-server github-agent-bridge-writer \
  --confirm-write \
  --repository OWNER/REPO
```

The MCP adapter deliberately exposes a narrow contract: repository/file reads, PR-comment reads, exact-SHA branch creation, atomic multi-file commits, PR create/update, and PR comments. It does **not** expose merge, secrets, repository deletion, or admin settings. The server requires `AGENT_BRIDGE_ALLOWED_REPOS`; write branches default to the `ai/` prefix, and text writes are scanned for obvious secrets before GitHub API calls are made.

### 3. `readonly` — safe fallback

ChatGPT can plan/review and produce patches/artifacts, but it must not claim that it pushed code.

```bash
agent-bridge setup writer --mode readonly
```

## One-time setup

Install the CLI in the repository environment:

```bash
python -m pip install -e .
agent-bridge init
```

Configure authoritative local validation. These commands are trusted and will execute against implementation PR code:

```bash
agent-bridge setup review \
  --test-command 'python -m unittest discover -s tests -v' \
  --test-command 'python -m compileall -q src tests'
```

By default, unattended Codex approval is blocked if no local test command is configured. Use `--allow-no-tests` only when that is intentional.

Configure a writer mode, then print the two ChatGPT Work event-trigger definitions:

```bash
agent-bridge trigger automation-setup
```

Create them once in ChatGPT Work:

1. **Task PR trigger** — PR opened/ready and body contains `agent-bridge:task` → ChatGPT implements.
2. **Codex review-comment trigger** — new PR comment contains `agent-bridge:codex-review` and `verdict=REVISE` → ChatGPT fixes.

Finally, keep the local reviewer running on the development machine:

```bash
agent-bridge watch
```

For production use, run it under a user service/supervisor so it starts automatically with the machine.

## Starting a task from Codex

Codex should inspect the local repository first, then create a task whose primary developer is ChatGPT:

```bash
agent-bridge task create \
  --title 'Refactor tag synchronization' \
  --objective 'Unify scheduled sync, manual repair, and reconciliation.' \
  --assigned-to chatgpt \
  --reviewer codex \
  --priority high
```

Publish it without disturbing the user's current branch/worktree:

```bash
agent-bridge publish task TASK-000001
```

The publisher creates an isolated worktree from the pinned base SHA, copies validated `.ai/` artifacts, pushes `agent-bridge/task-000001`, and opens the marked Task PR. That PR is the event that wakes ChatGPT Work.

## ChatGPT implementation contract

For a task:

```bash
agent-bridge trigger work-prompt TASK-000001 --phase implement
```

For a fix iteration after Codex comments:

```bash
agent-bridge trigger work-prompt TASK-000001 --phase fix
```

The prompt requires ChatGPT to:

- read the exact task/base/context;
- design before coding;
- branch from the exact pinned base commit;
- implement and add tests;
- self-review once before handoff;
- publish/update an implementation PR with the machine marker;
- never merge the PR itself.

## Codex local reviewer

The watcher uses `gh` and `codex exec` non-interactively. For each eligible implementation PR head it:

1. rejects cross-repository PRs;
2. enforces the configured trusted implementation branch prefix (`ai/` by default);
3. fetches the exact PR head into a temporary worktree;
4. runs configured local test commands;
5. invokes `codex exec --ephemeral` with a structured output schema;
6. locally validates the final JSON rather than trusting model formatting alone;
7. posts a machine-marked GitHub comment;
8. records the reviewed PR head in Git-private state so the same SHA is not reviewed twice.

A failing/missing required local test prevents automatic approval even if the model says `APPROVE`.

## Security boundaries

The default design intentionally keeps these powers separate:

- **ChatGPT writer:** branch/file/PR/comment writes only.
- **Codex watcher:** local checkout, configured test execution, review/comment.
- **Human:** final merge/acceptance.

Recommended GitHub permissions for a write-capable connection:

```text
Metadata       read
Contents       write
Pull requests  write
Issues         write   # PR comments use the issue-comment API
Actions        read
```

Do not grant repository administration, secrets, deletion, or merge capabilities merely to make setup easier.

Also note that running tests from a PR executes that PR's code on your local machine. The watcher therefore refuses cross-repository PRs and enforces a trusted implementation branch prefix, but you should still run it on a machine/environment appropriate for code execution.

## Useful commands

```bash
agent-bridge status
agent-bridge capabilities
agent-bridge drift TASK-000001
agent-bridge trigger task-pr TASK-000001
agent-bridge trigger implementation-pr TASK-000001
agent-bridge watch --once
agent-bridge validate
```

## Current platform constraints

- GitHub PR activity can be used for event-triggered ChatGPT Work tasks for eligible ChatGPT plans.
- OpenAI-built apps are currently search/read oriented; write/modify actions require an appropriate write-capable/custom app path.
- Full custom MCP write support in ChatGPT is plan/workspace dependent. If it is unavailable, use managed mode with a compatible writer or fall back to readonly mode.
- ChatGPT may still request confirmation for write actions depending on app permissions, workspace-agent controls, and action context. `unattended_ready` is therefore an explicit operator confirmation, not a guarantee inferred by this CLI.

See `references/automation.md` and `references/writer-modes.md`.

## License

MIT

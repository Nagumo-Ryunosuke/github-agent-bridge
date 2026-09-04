# Zero-touch bootstrap

`github-agent-bridge` deliberately separates what the local CLI can verify from the one ChatGPT platform step that currently requires interactive setup.

## Recommended managed setup

```bash
agent-bridge setup bootstrap \
  --mode managed \
  --connection-name github-agent-bridge-writer \
  --confirm-write \
  --confirm-unattended \
  --test-command 'pytest -q'
```

When `--repository` is omitted, bootstrap attempts to infer `owner/repo` from a github.com `origin` and records it as the bridge allowlist. Re-running bootstrap preserves existing confirmations when the writer backend and repository scope are unchanged.

If the writer backend or repository scope changes, stored write/unattended confirmations are invalidated automatically. They can also be revoked explicitly with `--clear-write` and `--clear-unattended`.

The command prints the exact one-time ChatGPT Work trigger instructions when those triggers have not yet been confirmed.

After creating both event-triggered Work tasks on ChatGPT Web/iOS/Android:

```bash
agent-bridge setup work-trigger --confirm
agent-bridge watch
```

Run the watcher under a persistent user service/supervisor. Once it has emitted a fresh Git-private heartbeat, verify the complete loop:

```bash
agent-bridge doctor
```

The desktop app can display existing event-triggered tasks but currently cannot create or edit their trigger conditions.

## Custom MCP setup

```bash
agent-bridge setup bootstrap \
  --mode custom-mcp \
  --mcp-server github-enterprise-writer \
  --repository owner/repo \
  --confirm-write \
  --confirm-unattended \
  --test-command 'pytest -q'
```

The MCP backend should implement the writer contract in `references/writer-modes.md` and enforce its own repository allowlist and branch policy.

## Readiness gate

```bash
agent-bridge doctor
agent-bridge doctor --json
```

`zero_touch_ready=true` requires all critical checks to pass:

- bridge state/config initialized;
- github.com origin recognized;
- GitHub CLI installed and authenticated on the Codex machine;
- authenticated `gh` identity can actually access the current repository;
- Codex CLI executable available;
- writer write capability confirmed for the current backend/repository scope;
- unattended writer actions confirmed;
- current repository included in the bridge allowlist;
- both ChatGPT Work GitHub event triggers confirmed for the current repository scope;
- required authoritative local test policy configured;
- dedicated implementation branch prefix configured;
- long-running Codex watcher has a fresh Git-private heartbeat.

`agent-bridge watch --once` intentionally does not mark the reviewer service healthy. A one-shot poll is useful for manual diagnostics, but it is not sufficient for zero-touch operation.

The human merge gate is reported separately as a safety warning if disabled.

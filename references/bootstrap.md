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

When `--repository` is omitted, bootstrap attempts to infer `owner/repo` from a github.com `origin` and records it as the bridge allowlist.

The command prints the exact one-time ChatGPT Work trigger instructions when those triggers have not yet been confirmed.

After creating both event-triggered Work tasks on ChatGPT Web/iOS/Android:

```bash
agent-bridge setup work-trigger --confirm
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
- Codex CLI executable available;
- writer write capability confirmed;
- unattended writer actions confirmed;
- current repository included in the bridge allowlist;
- both ChatGPT Work GitHub event triggers confirmed;
- required authoritative local test policy configured;
- dedicated implementation branch prefix configured.

The human merge gate is reported separately as a safety warning if disabled.

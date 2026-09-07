# Automation bootstrap

`github-agent-bridge` deliberately separates what the local CLI can verify from the optional ChatGPT platform step used for GitHub event brokering. Primary design and implementation remain in a normal ChatGPT Web Chat.

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

The command prints the exact one-time ChatGPT Work **broker** trigger instructions when those optional triggers have not yet been confirmed.

Before creating either broker trigger:

1. Show the user the intended Work model/reasoning level and obtain explicit approval.
2. Prefer the least costly option that can reliably parse the GitHub event and prepare a compact handoff.
3. Do not choose the newest/strongest model merely because it is available.
4. If the platform does not expose model selection, disclose that the platform default Work model will be used and ask whether to continue.

The broker triggers must only parse the event and prepare a handoff for a normal ChatGPT Web Chat. They must not design, edit code, run broad tests, use the writer, create/update implementation PRs, recursively invoke Work, or escalate model/reasoning level.

After creating and model-approving both event-triggered broker tasks:

```bash
agent-bridge setup work-trigger --confirm
agent-bridge watch
```

Run the watcher under a persistent user service/supervisor. Once it has emitted a fresh Git-private heartbeat, verify the transport/review loop:

```bash
agent-bridge doctor
```

A Work-trigger confirmation authorizes only the bounded broker role. It does not authorize Work as primary developer and does not grant Chat permission to invoke Work later without a fresh explicit user/model approval.

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

`zero_touch_ready=true` requires all critical transport/writer/reviewer checks to pass:

- bridge state/config initialized;
- github.com origin recognized;
- GitHub CLI installed and authenticated on the Codex machine;
- authenticated `gh` identity can actually access the current repository;
- Codex CLI executable available;
- writer write capability confirmed for the current backend/repository scope;
- unattended writer actions confirmed;
- current repository included in the bridge allowlist;
- optional Work GitHub event brokers confirmed for the current repository scope when that automation is enabled;
- required authoritative local test policy configured;
- dedicated implementation branch prefix configured;
- long-running Codex watcher has a fresh Git-private heartbeat.

`zero_touch_ready=true` does not mean Work may perform primary implementation and does not remove the normal Chat development step.

`agent-bridge watch --once` intentionally does not mark the reviewer service healthy. A one-shot poll is useful for manual diagnostics, but it is not sufficient for persistent review automation.

The human merge gate is reported separately as a safety warning if disabled.

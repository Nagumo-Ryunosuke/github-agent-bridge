# GitHub Agent Bridge

A skill and Python CLI for relaying development from desktop Codex to **ordinary ChatGPT Web Chat**. Codex clarifies requirements and transports artifacts; browser Chat designs, implements and reviews. GitHub stores the task, code and exact commit identity. The human decides whether to merge.

## Fix for accidental Work conversations

The previous default explicitly created event-triggered **Work** tasks and ran a Codex review watcher. A prompt saying “continue in Chat” cannot turn a Work task into ordinary Chat. This version selects the browser's Chat surface instead:

- Desktop Codex preference: GPT-6 Astra (`gpt-6-astra`), questions and artifact relay only. The app model selector controls the real model; the skill cannot set it.
- Web model: preserve the model actually selected in ordinary Chat. Do not silently change it or use Work.
- Design, implementation, self-review, independent review and fixes: ordinary Chat.
- `chat prepare` creates a commit-pinned handoff packet. `chat delivered` records a browser-observed assistant acknowledgment. Preparation is not delivery, and delivery is not task completion.
- Legacy Work prompt/confirmation entry points refuse to create Work. A default Chat reviewer also blocks the Codex watcher before it accesses PRs or invokes a model.

**Current capability boundary:** browser sending/reading is performed by the active browser-capable agent using the skill. The CLI has no ChatGPT session and does not bundle an unattended GitHub-event-to-Chat adapter. `doctor` therefore reports `Zero-touch ready: NO`. No Work task, scheduled task or polling loop is created to hide that gap. Ordinary Chat's repository writer and test runtime must be verified separately; otherwise it returns a patch and explicit untested limitations.

## Install or upgrade

Python 3.9+ and Git are required for the local packet workflow. GitHub CLI is needed for repository publishing. Codex CLI and its watcher are **not required** for the ordinary Chat workflow.

```shell
python -m pip install --upgrade git+https://github.com/Nagumo-Ryunosuke/github-agent-bridge.git
agent-bridge skill install --scope user
agent-bridge skill status --scope user
```

Before a fix is merged, install from its exact branch/commit rather than `main`, or install this checkout with `python -m pip install .`. Updating root `SKILL.md` alone does not update the installed package's skill copy. Reload the app task after upgrading the installed skill.

Existing bootstrap scripts remain available for legacy full-review deployments; they can install Codex CLI and should not be used merely to set up browser Chat relay.

## Use from desktop Codex

Select GPT-6 Astra in the desktop Codex model selector, then ask:

> Use $github-agent-bridge. Only clarify my requirements and relay materials here. Have ordinary ChatGPT Web Chat design, implement and review this task. Do not create Work tasks or run a Codex reviewer.

The skill uses the connected logged-in browser. If Chrome is requested, its connection must be available; Codex's in-app browser has a separate session. Chat/Work must be checked in the visible UI: the conversation URL alone cannot distinguish them.

## CLI workflow

Run inside the target repository:

```shell
agent-bridge init
agent-bridge setup chat --url https://chatgpt.com/c/SAVED-CONVERSATION-ID --model "VISIBLE WEB MODEL LABEL"
agent-bridge task create --title "Requested change" --objective "User requirements and acceptance criteria" --reviewer chatgpt
agent-bridge chat prepare TASK-000001 --phase design
```

`setup chat` records a binding and migrates roles, not an app model selection or successful browser delivery. Read the prepared JSON and send its `prompt` through the ordinary Chat UI. Capture the assistant's `BRIDGE-ACK <digest>` and record the observed surface, URL and model:

```shell
agent-bridge chat delivered TASK-000001 --phase design --surface chat --url https://chatgpt.com/c/SAVED-CONVERSATION-ID --model "VISIBLE WEB MODEL LABEL" --reply-file assistant-reply.txt
agent-bridge chat status TASK-000001 --phase design
agent-bridge chat result TASK-000001 --phase design --result-file observed-result.json
agent-bridge chat prepare TASK-000001 --phase implement
agent-bridge chat prepare TASK-000001 --phase review --head EXACT_40_CHARACTER_PR_HEAD_SHA
agent-bridge chat prepare TASK-000001 --phase fix --head EXACT_40_CHARACTER_PR_HEAD_SHA
```

Complete instructions: [browser transport](references/browser-chat.md). A receipt is explicitly an operator/agent UI attestation, not independent server verification. The `sent` checkpoint survives browser interruptions; `result` validates and stores the completed phase without executing any returned commands. Prior Chat results carry into subsequent phase packets. Duplicate preparations reuse the packet/receipt; changed requirements or bindings invalidate it. Task code drift blocks sending. Review/fix require a full head SHA and reject a mismatch with the recorded implementation. Check the current GitHub PR head before review and again before reporting approval.

Use a separate ordinary Chat for independent review when available; provide the full contract, diff and evidence and rebind before preparing. If Chat lacks a writer or runtime, return its patch and capability gap. Local application/tests require the user's authorization; the desktop dispatcher relays failures back to Chat.

## Migration

- Upgrade both the package and installed user skill; stale installed skill instructions can still create Work.
- `setup chat` sets the reviewer to ChatGPT and clears local Work confirmations. Existing tasks retain their explicit reviewer; recreate old Codex-review tasks with `--reviewer chatgpt`.
- Previously saved platform Work tasks and already running processes are not removed by editing config. Inspect and disable them through their own controls within the user's authorization.
- The old local review implementation remains opt-in through explicit `workflow.reviewer=codex`. It is not part of the default browser Chat workflow.
- Publishing a Task PR stores a contract on GitHub; it does not wake ordinary Chat automatically.

## Development

```shell
python -m pip install -e .
python -m unittest discover -s tests -v
```

For source-only invocation set `PYTHONPATH=src`, then use `python -m github_agent_bridge ...`. Changes to `SKILL.md`, `agents/openai.yaml` and shipped references must be synchronized with `src/github_agent_bridge/skill_bundle/`.

See [writer modes](references/writer-modes.md), [protocol](references/protocol.md), and [security](references/security.md). Never put credentials in `.ai/`; merge stays human-controlled.

## Related open-source designs

We compared [codex-with-chatgpt](https://github.com/XiaoDuoYa/codex-with-chatgpt), [codex-bridge-chatgpt](https://github.com/anightmonarch/codex-bridge-chatgpt), and [codex-chatgpt-bridge](https://github.com/RPG-478/codex-chatgpt-bridge). Their checkpoint/receipt/result-validation approaches informed the handoff flow. Their usual Codex-as-executor split is not adopted: ordinary Chat still owns implementation here. See [the comparison and pinned source revisions](references/related-projects.md).

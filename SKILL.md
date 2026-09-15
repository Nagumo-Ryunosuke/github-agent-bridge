---
name: github-agent-bridge
description: Relay development requests from Codex to ordinary ChatGPT browser Chat for design, implementation and review, with commit-pinned GitHub context and observed delivery receipts. Use for ChatGPT/Codex handoff and diagnosing accidental Work task creation.
---

# GitHub Agent Bridge

## Role and model routing

- Codex is the requirements interviewer and transport: clarify the objective, collect requested repository context, relay questions/artifacts, and report observed results.
- Ordinary ChatGPT Web **Chat** owns design, implementation, test design, self-review, independent review and revisions. Preserve the web Chat model selected by the user.
- The desktop Codex dispatcher preference is GPT-6 Astra (`gpt-6-astra`). A skill and `agents/openai.yaml` cannot change the active model. Verify the app's selector/current task metadata; if unavailable, report that the model choice is unverified. Do not claim the config value selected the model.
- The human retains the merge decision. Local implementation/review/test execution is allowed only when the user explicitly requests it. Do not silently spend Codex reasoning on the delegated phases.

These defaults supersede older Work/Codex-review instructions in this package. Preserve an explicit user override.

## Prevent the Work routing bug

Ordinary Chat and ChatGPT Work are different execution surfaces. Writing “use Chat” inside a Work prompt does not change the surface.

**Never use `create_thread` with `target.type=chatgptWorkCloud`, Work automations, Work event triggers, or a Codex child task to implement an ordinary-Chat request.** The app task creation tool's cloud target creates Work; it is not a normal Chat constructor. Do not substitute schedules or polling for a missing event-to-Chat adapter.

Use a connected browser's actual Chat UI. Follow [references/browser-chat.md](references/browser-chat.md) for the transport procedure, capability gaps and receipts. If the user specifies logged-in Chrome, use that connection; Codex's in-app browser is a separate session. Never read cookies or use undocumented ChatGPT backend APIs.

## Dispatch and return

1. Locate the real repository and read its instructions. Preserve unrelated edits. Use the installed CLI, or `PYTHONPATH=src python -m github_agent_bridge` from a source checkout. Run `env status` and `doctor` to collect evidence; a missing Codex CLI/watcher is not a reason to install a reviewer for this workflow.
2. Create a task containing the user's requirements, pinned base, repository context and acceptance criteria. Use `task create ... --reviewer chatgpt`. The narrow contract must not become a locally authored architecture plan.
3. Use `chat prepare <TASK> --phase design`, then perform the browser transport. A prepared packet and a published Task PR are not delivery.
4. Relay Chat's questions to the user. Return answers to the same Chat. When the design is ready, send the `implement` packet to that Chat within the user's authorized task scope.
5. Chat may commit through its own verified writer. If it only returns a patch, report the capability gap. Apply exactly that patch locally and run supplied test commands only if the user authorized local execution; return failures to Chat for a fix. Never claim that an ordinary Chat inherits Work tools or desktop credentials.
6. Relay the exact implementation PR head and actual test evidence with `chat prepare <TASK> --phase review --head <40-char-SHA>`. Prefer a separate ordinary review Chat with the complete contract, diff and evidence when the browser supports it; bind that Chat explicitly before preparing its packet. Codex must not author the review findings.
7. Route REVISE back through the `fix` phase, then review the new exact head. Recheck the live PR head before reporting approval. Keep findings and test limitations intact; never convert unexecuted tests into a pass.
8. Record the result through the existing `task finish` / `review` state commands after observing the actual Chat output. Use `chat sent` only after the user turn is visible, and `chat result --result-file ...` to validate and persist the completed phase JSON. Resume `sent`/`delivered` phases without resending. A delivery acknowledgment is not an implementation, review approval, or merge.

## Installation and migration

The root and packaged `src/github_agent_bridge/skill_bundle` copies must stay synchronized. Upgrade the Python package from the intended branch/commit before `agent-bridge skill install --scope user`; otherwise installation simply restores the old Work instructions. Check `skill status --scope user` and reload the skill in a new app task after upgrade.

`setup chat --url <saved-chat-url> --model <observed-web-model-label>` migrates repository routing to ordinary Chat and disables stored Work confirmations. It does not select an app model, create a browser conversation, prove delivery, stop an old watcher process, or delete platform Work tasks. Inspect existing Work tasks and disable them only within the user's authorization. Old tasks that assign Codex review must be recreated with the intended reviewer.

For fresh deployment, use [references/bootstrap.md](references/bootstrap.md). For writer permissions use [references/writer-modes.md](references/writer-modes.md). Never fabricate writer attestations or copy credentials into `.ai/`.

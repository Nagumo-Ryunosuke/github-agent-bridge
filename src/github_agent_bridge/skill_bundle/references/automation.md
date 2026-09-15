# Ordinary Chat handoff

The active Codex dispatcher relays requirements and artifacts through the logged-in browser. Ordinary Chat owns design, implementation and review. See [browser-chat.md](browser-chat.md) for the actual transport and verification steps.

There is no bundled unattended GitHub-event-to-Chat adapter. Do not create Work tasks, schedules or polling as a substitute. A published Task PR is durable context, not a delivered message. `doctor` remains NO for unattended readiness.

The older Codex watcher remains available only for an explicitly configured `workflow.reviewer=codex`. It refuses to run under the default Chat reviewer and skips tasks assigned to other reviewers. Do not install it for the ordinary Chat workflow.

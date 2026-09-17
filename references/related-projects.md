# Related project comparison (2026-09-15)

These repositories were inspected as reference material, not installed or executed. The implementation here is original Python code; no upstream source or skill text was copied. All three inspected repositories carry MIT licenses. If upstream code is later copied, preserve its copyright and license notice.

| Project / inspected revision | Relevant mechanism | Decision for this repository |
| --- | --- | --- |
| [XiaoDuoYa/codex-with-chatgpt](https://github.com/XiaoDuoYa/codex-with-chatgpt/tree/9663b88753e35c76796c5bce000293e0bd22cd9e) | `src/session/state.ts` and the skill maintain conversation URLs and waiting checkpoints; official browser Chat plus read-only workspace MCP | Adopt resumable sent/received states and carry prior Chat results forward. Keep ordinary Chat responsible for implementation; do not adopt the upstream Codex-executes split or mandatory in-app-browser preference. |
| [anightmonarch/codex-bridge-chatgpt](https://github.com/anightmonarch/codex-bridge-chatgpt/tree/56e36c2feeb6705376c1d1dc50dbec52ea43d4f4) | `references/run-receipt.md` separates requested/observed models and artifact correlation from actual completion | Keep preparation, visible submission, assistant acknowledgment and completed result distinct. Digests bind artifacts, not the remote model. Respect the user's connected browser choice. |
| [RPG-478/codex-chatgpt-bridge](https://github.com/RPG-478/codex-chatgpt-bridge/tree/49384fc6534b84f0d2167ba5097a87e0a2e16b5a) | `src/response.ts` validates structured responses; `src/adapters/playwright.ts` implements browser submission and collection | Adopt a strict result contract with phase-specific verdicts. Do not import its Playwright/profile runtime: this skill uses the desktop's supported browser tool and existing authorized session. |

## What actually changed after comparison

- Added `chat sent` only after the complete submitted user turn is observed; resuming a sent packet does not create another conversation or resend it.
- Added `chat result` validation for task, phase, digest and review/fix head. Empty/partial/wrong-phase responses cannot advance the packet to returned.
- Keep returned content inert. Code and command strings are artifacts, not authorization to execute on the desktop. Review approval cannot override failed/unexecuted tests.
- Include previous phase results in subsequent packets so a new review conversation can receive the implementation report and earlier decisions.

## Capability boundary

A read-only MCP connector can help ordinary Chat inspect code but does not give it a GitHub writer or a test runtime. Browser submission remains dependent on the active desktop tool. No public ordinary-Chat creation API or unattended GitHub-event-to-Chat adapter was established by this comparison. The CLI does not claim either. The user's GPT-6 desktop dispatcher remains a model-selector choice, not a setting a skill can enforce.

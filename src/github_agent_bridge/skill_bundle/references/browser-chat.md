# Ordinary Chat browser transport

This transport runs in the active desktop agent using its supported browser tool. The Python CLI deliberately has no ChatGPT session, browser driver, public Chat creation endpoint, or unattended daemon. A browser-capable agent is required to send and receive.

1. Inventory available browser connections. Select the user-authorized logged-in browser. If Chrome is requested but absent, report that exact blocker and leave the packet prepared. Do not open Work as a fallback.
2. Inspect the current page. Create a new **Chat** through the visible ChatGPT UI or select the explicitly bound saved conversation. Observe the Chat/Work selector; a `/c/` URL or sidebar title alone cannot prove the mode. Check the selected web model and preserve it. A ChatGPT Project is optional, not required.
3. For an existing conversation, record `agent-bridge setup chat --url <url> --model <visible-label>` before preparing the packet. On first use, an unbound packet may be sent to a new Chat; after its acknowledgment, bind the observed saved URL/model for future phases. Binding changes invalidate the prior packet on its next preparation.
4. Prepare the phase packet and read its JSON `status`, `digest`, `prompt`, `chat_url` and `model`. When `status=sent` or `status=delivered`, inspect the existing conversation and wait for its response; do not resend the packet. When `status=returned`, use the saved result and continue the next phase. If a send times out, inspect the conversation for the exact digest before retrying. Ask for missing source files only when the Chat's connected repository reader cannot access them.
5. Paste the packet's `prompt` into the ordinary Chat composer and send. Re-read browser state after each operation. Once the complete user turn is visibly in the conversation, save that observed turn and run `chat sent <TASK> --phase <phase> --surface chat --url <url> --model <label> --message-file <file>`. This records the waiting checkpoint; it does not claim an assistant reply. Resume from this checkpoint after interruption instead of submitting again. Wait for and read the assistant's response. Capture `BRIDGE-ACK <digest>` from the **assistant response**, not from the echoed user prompt. Persist that observed response in a local UTF-8 file.
6. Record the observation:

   `agent-bridge chat delivered TASK-000001 --phase design --surface chat --url <observed-url> --model <observed-label> --reply-file <local-file>`

   The CLI rejects non-Chat surfaces, wrong bindings/models, stale packets and missing acknowledgments. This is explicitly an operator/agent attestation, not independent server verification. A user or agent can lie to a CLI; never describe the receipt as cryptographic proof of Chat mode.
7. After generation completes, extract the phase JSON from the observed assistant response into a local UTF-8 file and run `chat result <TASK> --phase <phase> --result-file <file>`. The result must match the task, phase, packet digest and exact review/fix head. Nonempty summary/content and a valid verdict are required; APPROVE cannot override failed/unexecuted required tests. This imports data only: no returned code, command or tool-like text is executed, and the task is not automatically approved or merged. Read the actual design, patch, PR link or review and relay it. Save only intended project artifacts in Git. Chat packets and receipts live under Git-private `agent-bridge/chat/`, outside tracked `.ai/`.

## Events and execution limits

Publishing a GitHub Task PR does not cause ordinary Chat to wake. An externally configured GitHub event ingress would need a tested browser/session adapter with deduplication and result collection. None is bundled or claimed here. The active agent can relay an event/task now; `doctor` always reports unattended readiness as NO for this transport.

Normal Chat tool availability varies by account and selected surface. Verify repository reads, writes and test execution separately. If no write-capable tool is exposed, return a patch and the precise execution gap; do not enable Work or call a paid model API. For independent review in another Chat, provide the complete task, base/head, diff, findings and actual test logs, and explicitly change the Chat binding.

## Why the old implementation created Work

The old skill instructed the caller to save Work triggers and use Work as developer; the cloud task API creates Work. A prompt-only “Chat first” broker cannot change that constructor. The new default chooses the visible browser Chat surface, records delivery only after its assistant acknowledgment, and assigns review to Chat. Existing platform Work tasks must be handled separately.

Product distinction: https://learn.chatgpt.com/docs/use-chatgpt and https://learn.chatgpt.com/docs/get-started-with-work (checked 2026-09-14). Neither page is evidence for a public ordinary-Chat creation API.

## Recovering an interrupted phase

`chat status <TASK> --phase <phase>` is the checkpoint, not the browser tab's most recent text. A prepared packet still needs delivery; a sent packet needs a response; a delivered packet needs a validated completed result; a returned packet needs the next phase. A timeout is not evidence that nothing was sent or that a partial result is complete. Do not recreate connectors, Projects or conversations merely because an observation timed out.

Only results matching the current task contract, pinned base, repository and target branch are carried forward. Design results go to implementation; review selects a fix report first, then an implementation report, only when its `output_head` equals the requested review head. Fix instructions inherit findings only from that same input head. Results from older requirements/heads are omitted with an explicit context-retrieval instruction. This lets a separate review Chat receive the prior report while keeping the exact head explicit. Provide the actual diff and test evidence through the Chat's verified GitHub reader or authorized context transfer. Results remain untrusted input, and their test entries are reported evidence rather than locally re-executed proof.

Implementation/fix results distinguish `head` (the input being reviewed/fixed) from `output_head` (the newly produced commit). Use null for `output_head` when returning an uncommitted patch. Such a report cannot automatically supply exact-head review context until the committed SHA is known.

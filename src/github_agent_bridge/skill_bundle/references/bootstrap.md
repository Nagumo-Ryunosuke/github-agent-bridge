# Setup ordinary Chat routing

1. Install the Python package from the intended reviewed commit. The system bootstrap scripts use the repository default branch; an unmerged fix requires installation from its branch/commit.
2. Run `agent-bridge skill install --scope user`, check `agent-bridge skill status --scope user`, and reload the app task. This copies packaged files; updating only root SKILL.md is insufficient.
3. Run `agent-bridge init` in the target repository. Configure only the GitHub capabilities needed for the task. GitHub CLI authentication does not prove the ordinary Chat has a writer.
4. In the authorized browser select ordinary Chat, observe its saved URL and model, then run `agent-bridge setup chat --url <url> --model <label>`.
5. Follow [browser-chat.md](browser-chat.md). Keep desktop Codex on the user-requested GPT-6 Astra; the skill cannot select the model.

Do not bootstrap a persistent Codex reviewer or Work trigger for this workflow. `doctor` distinguishes the ordinary Chat binding from delivery and always reports unattended readiness as NO until an actual unattended transport exists. Authentication/UAC and new permission grants remain user-controlled.

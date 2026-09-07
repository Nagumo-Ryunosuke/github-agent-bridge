# Windows 本地部署与使用

本项目包含三部分：给 Codex 的 Skill、`agent-bridge` Python CLI、本地自动审查 watcher。只复制 SKILL.md 不会建立 ChatGPT 与 Codex 的自动协作链路。

## 1. 准备工具

安装 Python 3.11 或 3.12、Git、GitHub CLI，以及可从终端调用的 Codex CLI。使用普通用户 PowerShell 检查：

```powershell
py --version
git --version
gh --version
codex --version
gh auth login -w
gh auth setup-git
codex login

GitHub 和 Codex 登录都会打开系统默认浏览器；Windows 通常会使用 Chrome。只有用户明确要求时才改用 Codex 内置浏览器。
gh auth status
codex login status
gh repo view Nagumo-Ryunosuke/github-agent-bridge
```

Codex App 中可以聊天不代表独立 CLI 已登录。自 1.5.0 起，`doctor` 会同时检查 Codex 可执行文件及登录状态，也可以用 `agent-bridge env status` 单独检查本机依赖。

## 2. 安装 CLI 和 Skill

下面以 `C:\dev` 为持久安装位置；目录可以修改。首次部署后台服务建议使用纯英文路径，中文路径的完整后台服务流程尚未实测。

```powershell
New-Item -ItemType Directory -Force C:\dev | Out-Null
Set-Location C:\dev
git clone https://github.com/Nagumo-Ryunosuke/github-agent-bridge.git
Set-Location C:\dev\github-agent-bridge
py -3.12 -m venv .venv
$bridgeBin = 'C:\dev\github-agent-bridge\.venv\Scripts'
& "$bridgeBin\python.exe" -m pip install -e .
& "$bridgeBin\agent-bridge.exe" skill install --scope user
& "$bridgeBin\agent-bridge.exe" skill status --scope user
```

若安装的是 Python 3.11，将 `py -3.12` 改为 `py -3.11`。这些命令不依赖激活脚本，也无需修改 PowerShell 执行策略。

用户级 Skill 安装到 `$HOME\.agents\skills\github-agent-bridge`。重启 Codex 后，在任务中用 `$github-agent-bridge` 调用。CLI 所在虚拟环境和源码目录应长期保留，后台服务会使用安装时的解释器。

如果 Git 克隆遇到 `schannel: AcquireCredentialsHandle ... SEC_E_NO_CREDENTIALS`，本次测试中以下单次设置可以解决，且不关闭证书验证：

```powershell
git -c http.sslBackend=openssl clone https://github.com/Nagumo-Ryunosuke/github-agent-bridge.git
```

## 3. 配置实际要开发的仓库

CLI 只需安装一次，bootstrap 和 watcher 则按仓库分别配置。下面仍以本项目为目标；换项目时修改工作目录、仓库名和测试命令。

```powershell
Set-Location C:\dev\github-agent-bridge
$bridgeBin = 'C:\dev\github-agent-bridge\.venv\Scripts'
$env:Path = "$bridgeBin;$env:Path"
$env:PYTHONUTF8 = '1'
agent-bridge setup bootstrap --mode readonly --repository Nagumo-Ryunosuke/github-agent-bridge --test-command 'set "PYTHONPATH=src" && "C:\dev\github-agent-bridge\.venv\Scripts\python.exe" -m unittest discover -s tests -v'
agent-bridge doctor
```

先用 readonly 跑通本地配置。这里测试命令中的 `set` 和 `&&` 由 Windows cmd 执行；显式设置 `PYTHONPATH=src` 是为了测试审查 worktree 的源码，避免 editable 安装把测试指向原始安装目录。

每次打开新的 PowerShell，需要重新设置 `$bridgeBin` 和临时 PATH，或者直接用 CLI 的完整路径。后台服务也必须能找到 `git`、`gh` 和配置的 Codex 程序；仅修改当前终端 PATH 不会永久修改计划任务的环境。

## 4. 接通 ChatGPT 写入与事件触发

本地 `gh` 登录和 ChatGPT 的 GitHub 连接是两套独立配置。先在 ChatGPT 网页端连接具有本仓库访问权和写入能力的 GitHub 工具，实际验证创建分支、提交文件、创建 PR，以及后台运行所需的授权策略。

`--connection-name` 只记录连接名称，不会创建连接、安装插件或授予 GitHub 权限。验证成功后再记录确认：

```powershell
agent-bridge setup writer --mode managed --connection-name '你的实际连接名称' --repository Nagumo-Ryunosuke/github-agent-bridge --confirm-write --confirm-unattended
agent-bridge trigger automation-setup
```

在 ChatGPT 网页端创建两项 GitHub PR 事件任务，并将仓库限定为本项目：

- 实现任务：收到任务 PR 事件后，检查 PR 正文是否包含 `agent-bridge:task`，读取任务 ID、任务文件和固定的 base commit，按 Skill 实现并自审，发布正文含 `agent-bridge:implementation task=TASK-XXXXXX` 标记的实现 PR，不合并。
- 修复任务：收到评论事件后，仅处理同时包含 `agent-bridge:codex-review` 和 `verdict=REVISE` 的评论；核对任务和提交 SHA，修复后向原实现 PR 推送新提交，不合并。

如果事件配置界面不提供正文/评论内容过滤，将上述判断写入保存的任务提示词，让无关事件直接退出。把本仓库 Skill 和完整工作说明作为可访问上下文提供给网页任务；网页任务无法直接读取本地安装目录。不要假定它能够运行你电脑上的 CLI。

官方文档确认 GitHub PR 事件触发取决于套餐和工作区设置，可在网页和移动端使用。请以账号实际可用的配置界面为准：[Scheduled tasks](https://learn.chatgpt.com/docs/automations)。如果账号没有该功能，就先手动把任务 PR 交给 ChatGPT，不能宣称已实现自动触发。

两项触发任务确实配置完成后，再执行：

```powershell
agent-bridge setup work-trigger --confirm
```

## 5. 启动本地审查

先在前台验证，以便看到错误：

```powershell
agent-bridge watch --once
agent-bridge watch
```

`--once` 只轮询一次，不表示后台服务健康。先用一个真实、范围很小的实现 PR 验证测试执行和 Codex 评论，再用 Ctrl+C 停止前台 watcher，然后安装后台服务：

```powershell
agent-bridge service install
agent-bridge service status
agent-bridge doctor
```

Windows 后端使用当前用户的计划任务。电脑需要开机、联网，相关仓库和解释器必须存在。检查 `service status` 输出的 `state_dir` 中的 `watch.log` 与 `watch.err.log`。出现 `Zero-touch ready: YES` 后仍应核对一次真实完整循环，因为 writer 和触发配置的确认值是人工记录，doctor 不会替你验证云端行为。

## 6. 每次如何使用

在 Codex 中打开目标仓库，输入：

> 使用 $github-agent-bridge，先检查当前仓库，为“具体需求”创建固定 base commit 的任务并发布 Task PR；由 ChatGPT 实现，Codex 本地测试和审查，最后由我合并。

也可以手动执行：

```powershell
agent-bridge task create --title '具体需求' --objective '明确改动范围、验收标准和测试要求' --assigned-to chatgpt --reviewer codex
agent-bridge drift TASK-000001
agent-bridge validate
agent-bridge publish task TASK-000001
```

把示例 ID 换成实际输出的 ID。发布前确认任务文件中的范围和验收要求完整。期望流程：Task PR → ChatGPT 实现 PR → 本地测试与 Codex 审查 → REVISE 后 ChatGPT 修复 → 再审查 → 人工合并。

## 本次本地验证记录（2026-09-06）

- Windows，Python 3.12；成功创建独立测试虚拟环境并 editable 安装 1.4.0。
- 原有 68 项测试通过；实际 doctor 暴露中文目录 Git 输出按 GBK 解码的崩溃。
- `run_git` 改为明确使用 UTF-8 后，新增中文目录和中文提交信息测试；70 项测试全部通过，compileall 通过。
- 在独立 smoke 仓库实际验证 readonly bootstrap、任务创建、drift、validate、仓库级 Skill 安装和状态检查。
- 当前测试终端未找到 gh，Codex CLI 显示未登录；未测试真实 GitHub 发布、ChatGPT 自动实现、后台计划任务和完整审查循环。
- 本记录中的配置演练不代表本机已经完成正式部署。

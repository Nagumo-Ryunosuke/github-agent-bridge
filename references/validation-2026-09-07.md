# 2026-09-07 本地复验

验证基线：main `060fb6d`，版本 1.5.0。环境：Windows AMD64、Python 3.12.14，独立虚拟环境。

## 基线结果

- editable 安装、76 项单元测试、compileall、wheel 构建和打包 Skill 文件检查通过。
- PowerShell 安装脚本解析通过；POSIX 脚本在 Git for Windows sh 下语法检查及 help 通过。这不等于 Linux/macOS 实机部署通过。
- 真实运行 env status、doctor：均正确报告缺少 GitHub CLI 和 Codex 未登录；doctor 新增的 codex_auth 检查有效。
- 独立 smoke 仓库中升级仓库级 Skill、查询版本状态、创建 TASK-000002 和 validate 通过。
- 上次中文 Git 路径和提交信息回归测试通过。

## 本轮修复

1. `/dev/tty` 权限可读写不代表当前进程有控制终端。旧探测在本机 Git sh 中通过，但实际打开终端失败。改为实际尝试打开终端；无终端时在安装前正确退出 2，输出交互终端不可用说明。新增 POSIX 回归测试在独立会话中验证该行为，Windows 跳过此测试，另用 Git sh 实测相同路径。
2. `include_codex=False` 原先会把 dispatch_ready 直接赋给 unattended_review_ready，导致跳过 Codex 仍显示无人值守审查就绪。现在保留分发就绪状态，但无人值守审查保持 false；相应测试已更新。
3. 更新旧 Windows 指南中“doctor 不检查登录”的过期说明。

## 尚未验证的边界

普通用户环境有 Python 和 WinGet，沙箱 PATH 无法看到它们。两种环境均未找到 gh；Codex 登录状态均为未登录。沙箱可见 App 自带 Codex 0.153.4，普通用户环境优先找到 npm Codex 0.128.0，部署时应明确选用的可执行文件。

本轮没有执行系统级依赖安装、交互登录、真实 GitHub Task PR 发布、ChatGPT 事件触发或后台计划任务。因此不能将单测通过或安装包构建成功视为全自动循环已验收。下一步应在用户登录后的普通 PowerShell 中运行 env status，再执行安装流程，并用一个小任务验证完整循环。

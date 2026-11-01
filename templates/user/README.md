# 个人级（user scope）推荐配置

从维护者 macOS 环境（Claude Code 2.1.316，2026-11）中挑出对本工作流有用、且可公开分发的部分。安装到 `~/.claude/`，对所有项目生效；**不要**放进目标项目的 `.claude/`，除非团队一致同意。

> 第三方插件 / mod 的代码不复制进本仓库，只给出来源与安装命令。安装前按 [Claude Code 插件文档](https://code.claude.com/docs/en/plugins) 审查插件源码：mod 的 hooks 模块在本机以你的权限运行。

## 插件与 Mods

| 插件 | 来源（许可） | 用途 | 对应工作流环节 |
|---|---|---|---|
| `codex@openai-codex` | [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc)（Apache-2.0） | `/codex:rescue` 把修复/第二意见交给 Codex；可选 stop-time review gate | [03 标准工作流](../../docs/03-标准工作流.md) 的“复核”：Claude 审查 → Codex 修复 → Claude 复审 |
| `blast-radius@claude-code-playground-mods` | [anthropics/claude-code-playground](https://github.com/anthropics/claude-code-playground) `claude-code/mods/`（Apache-2.0） | 拦下 `rm -rf`、`git reset --hard`、force push、migration 等高危命令，先展示影响范围再确认 | 补充 `settings.json` 的 deny/ask |
| `replay-theater@claude-code-playground-mods` | 同上 | 按 diff 逐个回放上一轮 Claude 的文件修改 | 人工 review AI 改动 |
| `token-weather@claude-code-playground-mods` | 同上（维护者未安装，可选） | 提示框上方显示上下文窗口用量预报 | 上下文管理 |
| `session-band@claude-kit` | [JohnnyVizz/claude-kit](https://github.com/JohnnyVizz/claude-kit)（MIT） | 提示框上方显示轮次、输出速度、本轮/会话成本、缓存倒计时、上下文占用 | 成本复盘（路线图阶段 3） |
| `filetree@claude-code-filetree` | [data-goblin/claude-code-filetree](https://github.com/data-goblin/claude-code-filetree)（MIT） | IDE 式文件树面板，高亮 Claude 正在读/写的文件 | 观察 Claude 的探索范围 |

安装（user scope）：

```bash
# GitHub marketplace
claude plugin marketplace add openai/codex-plugin-cc
claude plugin marketplace add JohnnyVizz/claude-kit
claude plugin marketplace add data-goblin/claude-code-filetree
claude plugin install codex@openai-codex --scope user
claude plugin install session-band@claude-kit --scope user
claude plugin install filetree@claude-code-filetree --scope user

# playground mods 以本地目录 marketplace 方式安装（需 Claude Code 2.1.287+）
git clone https://github.com/anthropics/claude-code-playground.git ~/.local/share/claude-mod-sources/claude-code-playground
claude plugin marketplace add ~/.local/share/claude-mod-sources/claude-code-playground/claude-code/mods
claude plugin install blast-radius@claude-code-playground-mods --scope user
claude plugin install replay-theater@claude-code-playground-mods --scope user
```

`codex` 插件需要本机已安装并登录 Codex CLI，安装后运行 `/codex:setup` 检查。

团队希望成员打开项目时被提示安装时，可把 [settings.plugins.json](settings.plugins.json) 中的 `extraKnownMarketplaces` / `enabledPlugins` 合并进项目 `.claude/settings.json`（只放 GitHub 来源的插件；本地目录 marketplace 无法跨机器共享）。

Mods 依赖终端 UI，Windows 原生、IDE 插件、Web 版中的可用性以各插件 README 为准。

## Skills

[skills/](skills/) 下是 [mattpocock/skills](https://github.com/mattpocock/skills)（MIT）的 3 个技能，已加中文触发词，来源与更新方法见 [skills/UPSTREAM.md](skills/UPSTREAM.md)。

| Skill | 触发 | 用途 |
|---|---|---|
| `diagnosing-bugs` | 自动：调试 / 排查 / 报错 / 跑不通 / 很慢 | 先建可复现的反馈回路，再假设 → 验证 → 修复 |
| `grilling` | 自动：拷问我 / 帮我把方案问透 | 实现前把计划追问到底，对应“计划”阶段 |
| `writing-for-agents` | 自动：写 skill / 改 CLAUDE.md | 编写 CLAUDE.md、skill、AGENTS.md 的原则 |

安装：

```bash
# macOS / Linux / WSL
cp -R templates/user/skills/{diagnosing-bugs,grilling,writing-for-agents} ~/.claude/skills/
```

```powershell
# Windows 原生（PowerShell）
Copy-Item -Recurse templates\user\skills\diagnosing-bugs,templates\user\skills\grilling,templates\user\skills\writing-for-agents "$env:USERPROFILE\.claude\skills\"
```

## 未收录

| 维护者本机有 | 不收录原因 |
|---|---|
| 语音提示 / 语音审批 hooks（TTS、PreToolUse 语音放行） | 依赖个人音频和 macOS `say`；用语音关键词放行工具调用不适合团队默认 |
| `swift-lsp`、`last30days`、`telegram` | 与 Java/Spring 工作流无关 |
| `savvy-progress@claude-kit` | 只服务于 `/savvy-flow` 多代理流程，按需安装 |
| `andrej-karpathy-skills` | 上游无许可证声明，不分发 |
| mattpocock/skills 的 `handoff`、`retro` 等 | 手动触发、通用性强但团队使用频率低；`/compact`、`/resume` 已覆盖多数交接场景。需要时从上游自行安装 |

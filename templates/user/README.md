# 个人级（user scope）配置：公司版

公司版不推荐、也不分发任何第三方插件或 mod。本目录只保留 3 个纯文本的通用 skill。

## 插件与 Mods：只用内置的

mod 在 Claude Code 进程内以你的权限运行：能读写你账号可访问的任何文件、读取环境变量与设置里的密钥、看到每一条提示词和工具调用、不经询问批准工具调用，而且不受沙箱约束（见[官方说明](https://code.claude.com/docs/en/plugins/mods/overview#what-a-mod-can-reach)）。因此公司环境的口径是：

| 类别 | 例子 | 公司版口径 |
|---|---|---|
| Claude Code 内置 | `/diff` 面板、AGENTS.md 加载、`cc-plugin-sec-default`（阻止用户安装的 mod 绕过组织的权限规则） | 可以使用，无需安装；在 `/plugin` 的 Installed → Built-in 查看 |
| Anthropic 示例 mod | [claude-code-playground](https://github.com/anthropics/claude-code-playground/tree/main/claude-code/mods) 的 `blast-radius`、`replay-theater`、`token-weather` | 官方说明为“按现状分享，不提供支持”。不默认安装；确有需要时，先用 `claude plugin validate <目录>` 列出它的 hooks 与调用，过安全审查，并由管理员统一分发 |
| 其他第三方插件 / mod | 个人或其他厂商的 GitHub 仓库 | 不安装 |

管理员可在 managed settings 中给内置守卫 `cc-plugin-sec-default` 设置 `allowManagedModsOnly` 选项来只允许组织分发的 mod、用 `strictKnownMarketplaces` 限定插件市场，示例见 [managed-settings.example.json](../managed-settings.example.json)。个人临时排查可用 `claude --safe-mode` 启动一次不加载任何已安装 mod 的会话。

## Skills

[skills/](skills/) 下是 [mattpocock/skills](https://github.com/mattpocock/skills)（MIT）的 3 个技能，已加中文触发词，来源与更新方法见 [skills/UPSTREAM.md](skills/UPSTREAM.md)。

| Skill | 触发 | 用途 |
|---|---|---|
| `diagnosing-bugs` | 自动：调试 / 排查 / 报错 / 跑不通 / 很慢 | 先建可复现的反馈回路，再假设 → 验证 → 修复 |
| `grilling` | 自动：拷问我 / 帮我把方案问透 | 实现前把计划追问到底，对应“计划”阶段 |
| `writing-for-agents` | 自动：写 skill / 改 CLAUDE.md | 编写 CLAUDE.md、skill、AGENTS.md 的原则 |

安装（推荐用脚本，已存在且内容不同的文件不会被覆盖，每个 skill 目录附带上游 MIT 许可）：

```bash
python3 scripts/install.py user            # 预演
python3 scripts/install.py user --apply    # 写入 ~/.claude/skills/
```

或手动复制：

```bash
# macOS / Linux / WSL
cp -R templates/user/skills/{diagnosing-bugs,grilling,writing-for-agents} ~/.claude/skills/
```

```powershell
# Windows 原生（PowerShell）
Copy-Item -Recurse templates\user\skills\diagnosing-bugs,templates\user\skills\grilling,templates\user\skills\writing-for-agents "$env:USERPROFILE\.claude\skills\"
```

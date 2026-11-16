---
name: workflow-retro
description: 用真实 Claude Code 会话记录对本仓库的模板做复盘（retro）：度量任务完成度，定位原因，改模板。用户说"复盘""看真实对话优化模板""模板在项目里用得怎么样"时使用。
---

# 模板复盘

改模板的依据是**导入方项目里真实发生的会话**，不是对模板的阅读印象。每条改动都要能回答：哪几个会话、哪个指标、改完预期怎么变。

会话记录属于导入方，本仓库是公开的。写进仓库的只有聚合数字和结论；项目名、路径、提示词、代码、会话 id 留在本机的 `.retro/`（已 gitignore）。

## 1. 度量

向用户确认导入方项目的路径（有 worktree 时每个都要），然后运行：

```bash
python3 .claude/skills/workflow-retro/scripts/session_metrics.py --project <路径> [--project <worktree>]... [--since 30]
```

把 `--json` 的输出存成 `.retro/<日期>.json`。`.retro/` 里有上一次的结果时，先对比同一指标的变化，再看本次的绝对值。

指标是代理，不是结论：

| 指标 | 含义 | 模板里对应的要求 |
|---|---|---|
| `verified` / `unverified` | 最后一次改代码之后，对应的检查有没有**跑通**（失败的、`-DskipTests` 的不算；子代理里跑的算） | 后端、测试、Mapper XML、迁移 → `mvnw test/verify`；JSP、模板、静态 JS/CSS → `htmx-check.mjs`、`playwright test` 或浏览器 MCP |
| `prompts` | 人输入的轮数，偏高说明返工或指令不清；为 0 是无人值守的会话 | — |
| `denials` | 被权限规则或分类器拦下的次数 | `settings.json` 的 allow / deny / ask |
| `tool errors` | 工具调用报错的比例 | 文档里的命令、脚本 |
| `system mvn` | 用了系统 `mvn` 而不是 wrapper | AGENTS.md 的构建规则 |
| `direct xlsx reads` | 直接读 Excel 设计书 | xlsx deny 规则与 `specs-ai/` |
| `skills` / `subagents` | `spring-endpoint`、`code-reviewer` 有没有被用到 | skill 与子代理的 description |

完成标准：有一份存好的 `.json`，并列出了所有 `unverified` 会话，以及 denials、tool errors、prompts 最高的会话。会话少于 5 个时，在报告开头写明样本不足，后面的结论只算线索。

## 2. 定位

对第 1 步列出的每个会话：

```bash
python3 .claude/skills/workflow-retro/scripts/session_metrics.py --project <路径> --timeline <会话 id 前 8 位>
```

时间线给出事件顺序和它在 `.jsonl` 里的行号（`agent-xxx:12` 表示子代理文件的第 12 行）。会话文件单行可能有几百 KB，不要直接读文件，用 `--excerpt` 看指定行段里 Claude 说了什么、跑了什么：

```bash
python3 .claude/skills/workflow-retro/scripts/session_metrics.py --project <路径> --excerpt <会话 id 前 8 位> <起始行> <结束行>
```

从"最后一次编辑"读到会话结束，回答一个问题：**Claude 在那一刻为什么这样做？** 要找的是它当时看到了什么、说了什么理由，而不是结果本身。`--excerpt` 的输出是会话原文，只在本机看，不写进任何文件。

先排除误判：检查其实跑了，只是换了脚本认不出的形式（自定义的启动命令、别的测试工具）。这种情况归到第 3 步的"度量误判"。

完成标准：每个列出的会话都有一句话的原因，并且引用了具体行号。读完仍说不清原因的，记为"原因不明"，不要猜。

## 3. 归因

每个原因归到下面一类，只有前五类会导致改模板：

| 类别 | 判断依据 | 改哪里 |
|---|---|---|
| 规则没加载 | 相关的路径规则在那一刻不在上下文里 | `.claude/rules/*.md` 的 `paths:` |
| 规则加载了但没被遵守 | Claude 看到了规则，仍然跳过，或给了规则没预料到的理由 | 规则的措辞与位置；能机器检查的改成权限或 CI |
| 流程本身要求的操作被拦 | 被拒的命令正是模板让它跑的 | `settings.json` |
| 模板给的命令或脚本出错 | 报错的是 `scripts/` 或文档里的命令 | 脚本、文档 |
| 该用的 skill / 子代理没触发 | 任务匹配，但没有调用 | description 的触发词 |
| 如实报告了"未验证" | 环境不具备（服务起不来、没装 Playwright），且 Claude 明说了没验证 | 不改模板；这是模板要求的行为 |
| 度量误判 | 检查实际跑通了，脚本没认出来 | 改 `session_metrics.py` 并在 `tests/test_session_metrics.py` 补一例，然后重跑第 1 步 |
| 与模板无关 | 需求变更、项目自身的 bug、用户中途改主意 | 不改 |

证据门槛：同一原因出现在至少 2 个会话，或者 1 个会话加上在 `tests/fixtures/sample-app` 里复现成功。只出现一次且无法复现的，记进 `.retro/` 留待下次。

完成标准：每个原因都有类别；达到门槛的列成改动候选，每条写明"会话数、指标、预期变化"。

## 4. 改动

把候选清单给用户确认后再动手。每条改动：

- 改模板的同时补测试；纯措辞改动无法测试时，在记录里标为"假设，待下次复盘验证"。
- 改 `.claude/rules/` 后运行 `python3 templates/project/scripts/sync_rules.py`；改 AGENTS.md 的共通规则后核对 `.github/copilot-instructions.md` 的摘要。
- 给常驻上下文的文件（AGENTS.md、CLAUDE.md、description）加内容前，先看能不能删掉或改写已有的一句来达到同样效果。

完成标准：`python3 -m unittest discover -s tests` 与 `ruff check .` 通过，`sync_rules.py --check` 无差异。

## 5. 记录

在 `docs/09-审查与修复.md` 追加一轮，只写：会话数与时间范围、各指标的聚合值、每条改动对应的类别与预期变化、未达门槛的线索条数。追加前检查这段文字里没有项目名、路径、会话 id 和任何会话原文。

完成标准：下一次复盘的人只读这一轮记录和 `.retro/` 里的 `.json`，就能判断每条改动有没有起作用。

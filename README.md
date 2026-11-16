# Claude Code 开发 AI 工作流搭建手册

[![Validate templates](https://github.com/zhuyihenzheng/claude-code-workflow/actions/workflows/validate.yml/badge.svg)](https://github.com/zhuyihenzheng/claude-code-workflow/actions/workflows/validate.yml)

[日本語](README.ja.md)

> **公司版（`company` 分支）**：默认不连接任何远程 MCP 服务、不推荐任何第三方插件或 mod、关闭 claude.ai 连接器与 Artifact 发布，并附给信息安全部门的说明。差异与导入步骤见 [12 · 公司环境](docs/12-公司环境.md)。

面向 **Java + Spring Boot 后端 / JSP、HTMX 或两者并用** 项目的 Claude Code 团队工作流，与 GitHub Copilot 共用一份 AGENTS.md。仓库包含三部分：

- **手册**（[docs/](docs/)，中文）：规划、搭建、标准回路、工具选型、避坑；
- **项目模板**（[templates/project/](templates/project/)，日文，面向日本团队）：规则、权限、子代理、skill、MCP、workflow 与两个验证脚本；
- **安装脚本**（[scripts/install.py](scripts/install.py)）：把模板非破坏性地合并进已有项目。

它是可适配的起点，不是装上即用的插件：模板在 CI 的示例应用上跑通，你的业务项目仍需自行验收。已验证与未验证的范围见[验证范围](#验证范围)。

## 一句话结论

先把三件事做对，其余都是增益：

1. **一份短而准的 `AGENTS.md`**（目标 <150 行，分团队共通规则与本系统固有信息）；CLAUDE.md 导入它，Copilot 入口引用它并保留必守摘要；
2. **一个可判定的验证回路**（JUnit/Testcontainers + `./mvnw verify` + Playwright 打开真实页面验证 HTMX/JSP 渲染）——没有回路，AI 写得再快也只是把 review 压力转嫁给人；
3. **可自动检查的约束落到工具与 CI**：permissions 限制匹配工具，验证命令显式执行；模板不启用任何 hooks，进程隔离与最小凭据另行配置，合并门禁由 CI/分支保护执行。

## 本手册的结构

| 文档 | 内容 |
|---|---|
| [01 · 总体规划](docs/01-总体规划.md) | 目标、整体架构、四阶段落地路线图、模型路由与成本策略 |
| [02 · 基础搭建](docs/02-基础搭建.md) | 安装（CLI / IntelliJ / VS Code）、目录结构、settings 分层、AGENTS.md 与工具入口、权限与沙箱 |
| [03 · 标准工作流](docs/03-标准工作流.md) | 探索 → 计划 → 实现 → 验证 → 复核 → 提交 的标准回路、上下文管理、并行与无人值守 |
| [04 · Java / Spring Boot / HTMX / JSP 专项](docs/04-java-spring-htmx-jsp.md) | 本技术栈的规范落点、jdtls 代码智能、JSP 遗留页面规则、HTMX 浏览器验证回路 |
| [05 · 工具箱：MCP / Skills / 插件 / Mods](docs/05-工具箱.md) | 逐项选型：默认 2 个 MCP，另 2 个按需启用；技能框架二选一；状态栏与用量工具；Mods 的安全边界 |
| [06 · 团队协作与 CI](docs/06-团队协作与ci.md) | Copilot 与 Claude Code 共存、多系统推广、GitHub 集成（@claude / Code Review）、AI 代码 review 政策 |
| [07 · 避坑清单](docs/07-避坑清单.md) | 可复现的模板陷阱、版本核对与证据纪律 |
| [08 · 参考来源](docs/08-参考来源.md) | 一手依据、校验工具与证据边界 |
| [09 · 审查与修复](docs/09-审查与修复.md) | 按轮次记录的问题、修复、验证结果与剩余限制（历史记录，只追加） |
| [10 · PR 指摘对应](docs/10-PR指摘对应.md) | PR #1 的 10 条 review 逐条对应，作为“修复后交给 Claude 复审”的实例 |
| [11 · Excel 设计书](docs/11-Excel设计书.md) | 省 token 的读取方案：工具实测比较、`xlsx2ai.py` 增量转换（sheet JSON + Mermaid 流程图）、MCP 的定位 |
| [templates/](templates/README.md) | 模板的前置条件、安装规则、权限语义、可选 hook 与 workflow 的说明 |
| [12 · 公司环境](docs/12-公司环境.md) | 公司版与公开版的差异、导入步骤、给管理员的 managed settings 示例；[セキュリティレビュー資料（日本語）](docs/security-review.ja.md) |
| [templates/user/](templates/user/README.md) | 个人级（`~/.claude`）：mod 的使用口径、3 个中文触发的通用 skill |

## 分阶段落地路线图（摘要）

| 阶段 | 时间 | 做什么 | 完成标志 |
|---|---|---|---|
| 0 · 准备 | 第 1–2 天 | 全员配置 IDE Copilot，TL 先接入 Claude Code；统一账号/计划与规则入口 | 先在 HTMX 系统跑通小任务，再推广 JSP 系统 |
| 1 · 基础 | 第 1 周 | 写 AGENTS.md（<150 行），配置两种工具入口；settings.json 权限白名单 + deny `.env`；统一构建/测试命令 | 新成员 clone 后按本系统说明运行；`./mvnw -Dtest=X test` 等命令写进 AGENTS.md |
| 2 · 回路 | 第 2 周 | 核对 Java LSP 依赖 + 按需启用 MCP；显式执行编译、测试与项目格式化检查（默认无 hooks）；HTMX/JSP 页面验证回路（Playwright 脚本或 MCP） | 改完代码执行验证并保留输出；页面改动有截图/断言证据 |
| 3 · 团队化 | 第 3–4 周 | 接入 GitHub App 与官方 Code Review；沉淀 2–3 个项目自研 skill；/usage 成本复盘定模型路由 | PR 有 AI 初审；团队有自己的 skill 库 |
| 4 · 进阶（按需） | 之后 | worktree 并行、`/batch` 大改、headless 脚本化、动态工作流做全库审计 | 只在真有并行/批量需求时上，不为炫技引入 |

## 快速安装到已有项目

```bash
python3 scripts/install.py project /path/to/your-project          # 预演：只打印计划，不写文件
python3 scripts/install.py project /path/to/your-project --diff   # 预演，并打印与已有文件的差异
python3 scripts/install.py project /path/to/your-project --apply  # 写入
python3 scripts/install.py user --apply                           # 个人级 skills → ~/.claude/skills
```

脚本不覆盖、不删除已有文件：settings / `.mcp.json` 做规则并集，`.gitignore` / `.gitattributes` 只补缺失行，其余内容不同的文件列为 `conflict` 留给人工合并，目标文件是符号链接时不写穿。GitHub workflows 提交后即生效且需要密钥，默认不安装，加 `--with-workflows` 才复制。规则详见[模板说明](templates/README.md#安装与适配)。

安装后目标项目多出：

```
AGENTS.md                         项目规则的唯一事实来源（Copilot 与 Claude Code 共用），填写“本システム固有情報”
CLAUDE.md                         @AGENTS.md + Claude Code 专属补充
.claude/settings.json             权限：精确的 mvnw 命令 allow，.env / 凭据 / xlsx deny，迁移目录 ask
.claude/rules/{jsp,htmx}.md       按路径加载的页面规则
.claude/agents/code-reviewer.md   只读评审子代理
.claude/skills/spring-endpoint/   新增接口 / 页面片段的标准流程
.claude/hooks/verify-stop.py      Stop hook 参考样例（未注册）
.claude/README.md                 给人看的配置说明（不进会话上下文）
.github/copilot-instructions.md   Copilot 入口摘要
.github/instructions/             由 rules 生成的 Copilot 路径指令
.mcp.json                         隔离的 Playwright（本地进程，固定版本）
scripts/sync_rules.py             rules → Copilot 指令的同步与 --check
scripts/htmx-check.mjs            真实浏览器验证 HTMX 片段替换（含登录态、会话失效）
scripts/xlsx2ai.py                Excel 设计书 → 按 sheet 拆分的 JSON / Mermaid
.gitignore / .gitattributes       补充缺失规则
```

## 验证范围

```bash
python3 -m pip install -r requirements-dev.txt     # Python 3.11+
python3 -m unittest discover -s tests -v
```

| 已在 CI 验证 | 未验证，需在目标环境验收 |
|---|---|
| 模板内容、安装脚本、规则同步、Excel 转换：Linux / macOS / Windows | 真实业务项目（多模块、Spring Security/CSRF、外部 Tomcat/WAR） |
| `htmx-check.mjs`：真实 htmx 与 Chromium（Ubuntu） | 原生 Windows 上的 Claude Code、Maven 与 MCP |
| 安装 → `./mvnw verify` → 页面检查：真实 Spring Boot + JSP + HTMX 示例应用（Ubuntu） | Claude Code 会话实际加载情况、GitHub App 与付费 Action |
| 固定版本的 Playwright MCP 与 DBHub：MCP 握手并列出工具（Ubuntu）；workflow 文件：actionlint | 两个 MCP server 的实际浏览器操作与真实数据库 |
| Stop hook 参考样例：模拟与真实 Maven（仅 POSIX） | Copilot 各入口是否读取 AGENTS.md 与路径指令 |

本地测试不调用 Claude API；缺少 Playwright 时浏览器测试会跳过，CI 中强制执行。逐轮的问题与修复记录见 [09 · 审查与修复](docs/09-审查与修复.md)，Windows 搭建见 [02 · 基础搭建](docs/02-基础搭建.md#6-windows-两条路径)。

## 许可证

MIT（模板与文档可自由用于自己的项目）。

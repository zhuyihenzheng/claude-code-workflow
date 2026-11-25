# Claude Code 开发 AI 工作流搭建手册

[![Validate templates](https://github.com/zhuyihenzheng/claude-code-workflow/actions/workflows/validate.yml/badge.svg)](https://github.com/zhuyihenzheng/claude-code-workflow/actions/workflows/validate.yml)

[日本語](README.ja.md)

面向 **Java + Spring Boot 后端 / JSP、HTMX 或两者并用** 项目的 Claude Code 团队工作流，与 GitHub Copilot 共用一份 AGENTS.md。仓库包含三部分：

- **手册**（[docs/](docs/)，中文）：规划、搭建、标准回路、工具选型、避坑；
- **项目模板**（[templates/project/](templates/project/)，日文，面向日本团队）：规则、权限、子代理、skill、MCP、workflow 与验证脚本；
- **安装脚本**（[scripts/install.py](scripts/install.py)）：把模板非破坏性地合并进已有项目。

它是可适配的起点，不是装上即用的插件：模板在 CI 的示例应用上跑通，你的业务项目仍需自行验收。已验证与未验证的范围见[验证范围](#验证范围)。

## 一句话结论

落地时优先做好以下四件事。

1. **一份短而准的 `AGENTS.md`**（目标 <150 行，分团队共通规则与本系统固有信息）；CLAUDE.md 导入它，Copilot 入口引用它并保留必守摘要；
2. **一个可判定的验证回路**（JUnit/Testcontainers + `./mvnw verify` + Playwright 打开真实页面验证 HTMX/JSP 渲染）——没有回路，AI 写得再快也只是把 review 压力转嫁给人；
3. **可自动检查的约束落到工具与 CI**：permissions 限制匹配工具，验证命令显式执行；模板不启用任何 hooks，进程隔离与最小凭据另行配置，合并门禁由 CI/分支保护执行。
4. **纠正一次，检查永久**：人纠正过的错误落到设计、类型、`guard.py` 规则或测试上，而不是再往提示词里加一行；评审从读 diff 改为先看验证证据（见 [15](docs/15-纠正变成检查.md)）。

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
| [11 · Excel 设计书](docs/11-Excel设计书.md) | 转成人和 AI 都能读的 Markdown：7 种工具在日文方眼纸设计书上的实测、`xlsx2ai.py` 的结构还原（表、标题、缩进列表、Mermaid）、Excel 设计书的画面试验观点覆盖、MCP 的定位 |
| [14 · 改修流程与画面试验](docs/14-改修流程与画面试验.md) | 设计书 → 实现 → 测试 → 画面试验 → 试验书的一条流程；整合 midscene-poc；用变更指示安全地改 Excel |
| [13 · 控制矩阵](docs/13-控制矩阵.md) | 每条要求写在哪、谁拦、谁证明、还缺什么；导入后的 `doctor` 检查 |
| [15 · 纠正变成检查](docs/15-纠正变成检查.md) | 解读演讲「All Code Is Slop (Except Mine)」：倒置的信任金字塔；`guard.py` 确定性检查、`correct` 流程、功能地图、评审看证据；刻意不做的自动合并 |
| [templates/](templates/README.md) | 模板的前置条件、安装规则、权限语义、可选 hook 与 workflow 的说明 |
| [templates/user/](templates/user/README.md) | 个人级（`~/.claude`）推荐：插件 / mods 安装清单、3 个中文触发的通用 skill |

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
python3 scripts/install.py project /path/to/your-project --apply --with-screen-tests   # 连同画面试验（midscene-poc）
python3 scripts/install.py project /path/to/your-project --apply --with-archunit        # 连同 ArchUnit 分层测试（需按 config/quality/pom-snippet.xml 改 pom）
python3 scripts/install.py project /path/to/your-project --apply --with-copilot-cloud-agent   # 仅在使用 Copilot 云端 agent 时：环境准备 workflow
python3 scripts/install.py doctor /path/to/your-project           # 导入后检查：TODO 是否填完、规则是否同步、guard 是否通过、配置有无风险
python3 scripts/install.py user --apply                           # 个人级 skills → ~/.claude/skills
```

脚本不覆盖、不删除已有文件：settings / `.mcp.json` 做规则并集，`.gitignore` / `.gitattributes` 只补缺失行，其余内容不同的文件列为 `conflict` 留给人工合并，目标文件是符号链接时不写穿。GitHub workflows 提交后即生效且需要密钥，默认不安装，加 `--with-workflows` 才复制。规则详见[模板说明](templates/README.md#安装与适配)。

### 第一次导入怎样算跑通

1. 在目标项目的 `AGENTS.md` 填好 JDK、构建命令、参考页面与启动方式，逐个处理安装器报告的 `conflict`。回到本仓库运行 `python3 scripts/install.py doctor /path/to/your-project`，处理所有 `fail`，按项目实际情况判断每条 `warn`。
2. 在目标项目根目录运行 `python3 scripts/sync_rules.py --check`、`python3 scripts/guard.py` 和 `./mvnw verify`。如果项目已有 CI，可将这三项加入现有流水线。新建 GitHub Actions 门禁可参考 [ci.yml.example](templates/project/.github/workflows/ci.yml.example)。
3. 选一张经常改动的页面，为一次成功操作和一次输入错误写下预期结果。启动应用，在浏览器执行两个用例，把命令、断言和截图路径写进功能地图。仓库里的[订单登记示例](tests/fixtures/sample-app/docs/feature-map/S01-order-new.md)展示了可重复执行的记录格式。

安装后目标项目多出：

```
AGENTS.md                         项目规则的唯一事实来源（Copilot 与 Claude Code 共用），填写“本システム固有情報”
CLAUDE.md                         @AGENTS.md + Claude Code 专属补充
.claude/settings.json             权限：精确的 mvnw 命令 allow，.env / 凭据 / xlsx deny，迁移目录 ask
.claude/rules/{jsp,htmx}.md       按路径加载的页面规则
.claude/agents/code-reviewer.md   只读评审子代理
.claude/skills/spring-endpoint/   新增接口 / 页面片段的标准流程
.claude/skills/change-flow/       改修的标准流程：设计书 → 实现 → 单体测试 → 画面试验 → 试验书
.claude/skills/correct/           被纠正后的标准流程：把错误落到设计、类型、guard 规则或测试上
.claude/skills/feature-map/       功能地图的创建与更新
.claude/hooks/verify-stop.py      Stop hook 参考样例（未注册）
.claude/README.md                 给人看的配置说明（不进会话上下文）
.github/copilot-instructions.md   Copilot 入口摘要
.github/instructions/             由 rules 生成的 Copilot 路径指令
.github/pull_request_template.md  验证证据在前的 PR 模板
.github/CODEOWNERS.example        改名后：guard 规则与基线、AI 规则的修改必须由指定的人批准（对 Copilot 也生效）
REVIEW.md                         评审顺序与观点：Claude 的评审子代理、Copilot code review 与人审共用
config/copilot/                   Copilot 的内容排除清单（与 settings 的 deny 一致）与设置说明
config/guard/rules.json           guard 规则：每条带修法、来源与真实错误样例（起始 10 条）
config/pmd/jsp-ruleset.xml        PMD 的 JSP 转义检查（NoUnsanitizedJSPExpression）
config/quality/pom-snippet.xml    加进 pom.xml 的 ArchUnit 依赖与 maven-pmd-plugin，二者都在 ./mvnw verify 中运行
docs/feature-map/README.md        功能地图的书式：一个功能一个文件，命令与合格结果
.mcp.json                         Context7 + 隔离的 Playwright
scripts/sync_rules.py             rules → Copilot 指令的同步与 --check
scripts/guard.py                  确定性检查：新违规、过期例外、写坏的规则即失败；既有违规只减不增
scripts/htmx-check.mjs            真实浏览器验证 HTMX 片段替换（含登录态、会话失效）
scripts/xlsx2ai.py                Excel 设计书 → 按 sheet 拆分的 Markdown（表、标题、缩进列表、Mermaid）与 JSON
scripts/xlsx_patch.py             按变更指示改 Excel：只动指定的单元格，其余逐字节不变
screen-tests/                     （可选）画面试验：固定版本的 midscene-poc
src/test/java/ArchitectureTest.java （可选，--with-archunit）按编译后的依赖检查分层与字段注入
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
| 画面试验：示例应用上从 GitHub 按 SHA 安装框架并实际运行；`xlsx_patch.py` 改写运行生成的试验结果（Ubuntu） | 真实业务项目上的画面试验；`change-flow` 在真实改修任务上的表现 |
| Stop hook 参考样例：模拟与真实 Maven（仅 POSIX） | Copilot 各入口是否读取 AGENTS.md 与路径指令 |
| `guard.py`：单元测试（三平台）；示例应用上通过、注入真实错误后报出修法；功能地图里的命令在运行中的应用上逐条执行（Ubuntu） | 起始规则在真实业务代码上的误报率；`correct` 在真实纠正上的表现 |
| ArchUnit 与 PMD：示例应用的 `./mvnw verify`；同包引用 guard 查不到而 ArchUnit 失败；未转义的 EL 使 PMD 失败（Ubuntu） | 多模块、既有大量违规的项目上的导入（Freezing 与 `maxAllowedViolations`） |
| Excel 设计书 → Markdown：合成工作簿的单元测试（三平台）；示例应用的 Excel 版设计书经转换后，画面试验的观点覆盖与 Markdown 原稿一致（Ubuntu） | 版式与公开样本不同的真实设计书上的还原质量 |

本地测试不调用 Claude API；缺少 Playwright 时浏览器测试会跳过，CI 中强制执行。逐轮的问题与修复记录见 [09 · 审查与修复](docs/09-审查与修复.md)，Windows 搭建见 [02 · 基础搭建](docs/02-基础搭建.md#6-windows-两条路径)。

## 用真实会话改进模板

模板改得对不对，要看它在导入方项目里的实际表现。本仓库自带一个维护用的 skill [`workflow-retro`](.claude/skills/workflow-retro/SKILL.md)：在本仓库里对 Claude Code 说“复盘”，它会度量导入方项目的会话记录、定位原因、归因后再改模板。

度量脚本也可以单独运行。它只输出次数，不输出提示词、代码或命令参数（`--excerpt` 除外，那是在本机查看原文片段用的）：

```bash
python3 .claude/skills/workflow-retro/scripts/session_metrics.py --project /path/to/your-project
python3 .claude/skills/workflow-retro/scripts/session_metrics.py --project /path/to/your-project --timeline <会话 id 前 8 位>
```

它回答的问题是“最后一次改代码之后，模板要求的检查有没有跑通”，以及返工轮数、被权限拦下的次数、skill 与评审子代理有没有被用到。这些是代理指标，结论要读对应的会话才能下。

## 许可证

MIT（模板与文档可自由用于自己的项目）。

# Claude Code 开发 AI 工作流搭建手册

> 面向 **Java + Spring Boot 后端 / JSP、HTMX 或两者并用** 项目的 Claude Code 团队工作流，支持与 GitHub Copilot 共用一份 AGENTS.md：总体规划、搭建步骤、标准开发回路、工具箱选型与可直接套用的模板。
>
> 文档与模板于 2026-10-31 完成一次源码审查与修订。它是一份可适配的手册，不是已在目标项目运行通过的插件；平台、版本、账号和依赖前提见 [模板说明](templates/README.md)，问题与验证边界见 [审查记录](docs/09-审查与修复.md) 和 [PR 指摘对应](docs/10-PR指摘对应.md)。

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
| [09 · 审查与修复](docs/09-审查与修复.md) | 原版问题、修复内容、验证结果与剩余限制 |
| [templates/](templates/) | AGENTS.md、精简 CLAUDE.md、Copilot 仓库/路径指令、settings、rules、子代理、skill、MCP 与 workflow；路径规则由 [同步脚本](scripts/sync_rules.py) 生成 |
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
python3 scripts/install.py project /path/to/your-project          # 预演：create / merge / skip / conflict
python3 scripts/install.py project /path/to/your-project --apply  # 只写入 create 与 merge
python3 scripts/install.py user --apply                           # 个人级 skills → ~/.claude/skills
```

脚本不覆盖已有文件：settings / `.mcp.json` 做规则并集，`.gitignore` / `.gitattributes` 追加缺失行，其余差异列为 conflict 由人工合并。详见[模板说明](templates/README.md#安装与适配)。

## 模板验证

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

测试使用模拟 Maven，不调用 Claude API。真实项目的构建、页面、MCP 与 GitHub App 仍需独立验收。

模板提供原生 Windows 的 `mvnw.cmd` 命令、权限与换行配置，CI 矩阵包含 Windows；真实 Windows 集成仍待验收。`verify-stop.py` 原样保留为可选的 macOS/Linux/WSL 参考样例，未注册；需要时由用户自行添加 Stop hook，示例见[模板说明](templates/README.md)。Windows 搭建见 [02 · 基础搭建](docs/02-基础搭建.md#6-windows-两条路径)。

## 许可证

MIT（模板与文档可自由用于自己的项目）。

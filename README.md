# Claude Code 开发 AI 工作流搭建手册

> 面向 **Java + Spring Boot 后端 / HTMX + CSS + JSP 服务端渲染** 项目的 Claude Code 团队工作流：总体规划、搭建步骤、标准开发回路、工具箱选型与可直接套用的模板。
>
> 文档与模板于 2026-10-31 完成一次源码审查与修订。它是一份可适配的手册，不是已在目标项目运行通过的插件；平台、版本、账号和依赖前提见 [模板说明](templates/README.md)，问题与验证边界见 [审查记录](docs/09-审查与修复.md) 和 [PR 指摘对应](docs/10-PR指摘对应.md)。

## 一句话结论

先把三件事做对，其余都是增益：

1. **一份短而准的 `CLAUDE.md`**（目标 <200 行，只写代码里看不到的事实：构建/测试命令、版本、被纠正过的坑）；
2. **一个可判定的验证回路**（JUnit/Testcontainers + `./mvnw verify` + Playwright 打开真实页面验证 HTMX/JSP 渲染）——没有回路，AI 写得再快也只是把 review 压力转嫁给人；
3. **可自动检查的约束落到工具与 CI**：hooks 提供反馈，permissions 限制匹配工具；进程隔离与最小凭据另行配置，合并门禁由 CI/分支保护执行。

## 本手册的结构

| 文档 | 内容 |
|---|---|
| [01 · 总体规划](docs/01-总体规划.md) | 目标、整体架构、四阶段落地路线图、模型路由与成本策略 |
| [02 · 基础搭建](docs/02-基础搭建.md) | 安装（CLI / IntelliJ / VS Code）、目录结构、settings 分层、CLAUDE.md 规范、权限与沙箱 |
| [03 · 标准工作流](docs/03-标准工作流.md) | 探索 → 计划 → 实现 → 验证 → 复核 → 提交 的标准回路、上下文管理、并行与无人值守 |
| [04 · Java / Spring Boot / HTMX / JSP 专项](docs/04-java-spring-htmx-jsp.md) | 本技术栈的规范落点、jdtls 代码智能、JSP 遗留页面规则、HTMX 浏览器验证回路 |
| [05 · 工具箱：MCP / Skills / 插件 / Mods](docs/05-工具箱.md) | 逐项选型：默认 2 个 MCP，另 2 个按需启用；技能框架二选一；状态栏与用量工具；Mods 的安全边界 |
| [06 · 团队协作与 CI](docs/06-团队协作与ci.md) | `.claude` 入库规范、GitHub 集成（@claude / Code Review）、AI 代码 review 政策、安全清单 |
| [07 · 避坑清单](docs/07-避坑清单.md) | 可复现的模板陷阱、版本核对与证据纪律 |
| [08 · 参考来源](docs/08-参考来源.md) | 一手依据、校验工具与证据边界 |
| [09 · 审查与修复](docs/09-审查与修复.md) | 原版问题、修复内容、验证结果与剩余限制 |
| [templates/](templates/) | 需合并适配的模板：CLAUDE.md、settings.json、rules、子代理、skill、.mcp.json、GitHub workflow |

## 分阶段落地路线图（摘要）

| 阶段 | 时间 | 做什么 | 完成标志 |
|---|---|---|---|
| 0 · 准备 | 第 1–2 天 | 全员装 CLI + IntelliJ 插件；统一账号/计划；仓库建 `.claude/` 骨架 | 每人能在项目里跑起 `claude` 并完成一次小改动 |
| 1 · 基础 | 第 1 周 | 写 CLAUDE.md（<200 行）；settings.json 权限白名单 + deny `.env`；统一构建/测试命令入口 | 新成员 clone 后开箱可用；`./mvnw -Dtest=X test` 等命令写进 CLAUDE.md |
| 2 · 回路 | 第 2 周 | 核对 Java LSP 依赖 + 按需启用 MCP；配置有界 Stop 编译反馈与项目格式化检查；HTMX/JSP 页面验证回路（Playwright 脚本或 MCP） | 改完代码自动跑验证；页面改动有截图/断言证据 |
| 3 · 团队化 | 第 3–4 周 | 接入 GitHub App 与官方 Code Review；沉淀 2–3 个项目自研 skill；/usage 成本复盘定模型路由 | PR 有 AI 初审；团队有自己的 skill 库 |
| 4 · 进阶（按需） | 之后 | worktree 并行、`/batch` 大改、headless 脚本化、动态工作流做全库审计 | 只在真有并行/批量需求时上，不为炫技引入 |

## 模板验证

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

测试使用模拟 Maven，不调用 Claude API。真实项目的构建、页面、MCP 与 GitHub App 仍需独立验收。

## 许可证

MIT（模板与文档可自由用于自己的项目）。

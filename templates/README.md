# 模板使用说明

`templates/project/` 下是一套可直接拷进 Java + Spring Boot + HTMX + JSP 项目的起点配置。

## 用法

1. 把 `templates/project/` 里的文件按原相对路径拷进你的项目根目录：
   - `CLAUDE.md` → 项目根
   - `.claude/` → 项目根（settings、rules、agents、skills）
   - `.mcp.json` → 项目根
   - `.github/workflows/claude.yml` → 项目根（按需）
2. 逐文件替换占位符：版本号（JDK / Spring Boot）、启动类名、包名、端口、数据库连接等，文中以 `<!-- TODO -->` 或大写占位标注；
3. `.claude/settings.local.json` 不要入库，记得在 `.gitignore` 里加：
   ```
   .claude/settings.local.json
   CLAUDE.local.md
   ```
4. MCP 的密钥：在 shell/CI 里导出 `CONTEXT7_API_KEY`、`DATABASE_URL` 等环境变量后再启动 Claude Code，`.mcp.json` 里只有 `${VAR}` 引用；
5. 模板是起点不是终点：CLAUDE.md 按 [02 号文档](../docs/02-基础搭建.md) 的规范持续删改——凡是 Claude 能自己读代码发现的，就不要留在里面。

## 文件清单

| 文件 | 作用 |
|---|---|
| `project/CLAUDE.md` | 项目指令模板（Java/Spring/HTMX/JSP 定制，<200 行） |
| `project/.claude/settings.json` | 权限 allow/deny + hooks（格式化、编译拦截、禁碰生产配置） |
| `project/.claude/rules/jsp.md` | JSP 路径作用域规则（`paths:` 只在编辑 JSP 时加载） |
| `project/.claude/rules/htmx.md` | HTMX 片段约定与浏览器验证要求 |
| `project/.claude/agents/code-reviewer.md` | 只读 reviewer 子代理（钉 haiku/sonnet、只给只读工具） |
| `project/.claude/skills/spring-endpoint/SKILL.md` | 自研技能示例：新增接口的标准流程（含测试与页面验证） |
| `project/.mcp.json` | 起步 4 件套：Context7 / Playwright / DBHub / GitHub |
| `project/.github/workflows/claude.yml` | `@claude` 触发与 PR 自动初审示例 |

# 04 · Java / Spring Boot / HTMX / JSP 专项

> 先说清证据边界：截至 2026 年 10 月底，**社区里没有找到直接针对 "Claude Code × JSP" 或 "HTMX + JSP" 的成文经验**。本节中 JSP 部分是把 HTMX/Thymeleaf + Spring 的公开实践与 JSP 通用最佳实践（Bauke Scholtz 等经典文）迁移过来的结论，已逐条标注为「迁移结论」；Java/Spring 与 HTMX 部分则有社区模板与文章支撑（见 [08](08-参考来源.md)）。

## 1. CLAUDE.md 里要钉死的 Java 事实

社区 Java/Spring 项目模板的共识（多份 2026 年指南一致）：

- **版本**：JDK 版本、Spring Boot 版本、构建工具与 wrapper（`./mvnw` / `./gradlew`），禁止用系统级 `mvn` 以免版本漂移；
- **命令**：全量构建、跑单个测试类、跑单个测试方法、起服务（含 profile），全部写全；
- **分层**：Controller → Service → Repository 单向依赖；构造器注入（不用字段注入）；DTO 不直接暴露 JPA 实体；
- **测试栈**：JUnit 5 + Mockito；集成测试用 Testcontainers（不要 mock 掉数据库行为的关键路径）；
- **会误导人的旧代码**：点名遗留写法（如老 JSP 对应的 Controller 风格），注明"新代码不要模仿"。

模板见 [templates/project/CLAUDE.md](../templates/project/CLAUDE.md)。

## 2. Java 的天然优势：编译器就是验证回路

Java 是对 AI 编程最友好的生态之一：强类型 + 编译器 + JUnit 提供**快速、确定**的反馈。把回路配满：

- PostToolUse hook：编辑 `.java` 后自动跑格式化（如项目已有的 formatter 插件）+ 增量编译；
- Stop hook：收工前 `./mvnw -q compile`（或定向测试）不通过则拦截（退出码 2），把错误喂回让它自己修；
- 排查疑难时再上 `/effort high`，日常 medium 足够。

## 3. 代码智能：官方 jdtls-lsp 插件优先

- 官方 marketplace 的 `jdtls-lsp` 插件让 Claude 按**符号**跳转定义/找引用、编辑后立即收到诊断，而不是 grep 全文硬读，又准又省 token；
- 前提：每位成员本机装好 jdtls 二进制（插件本身不带），团队在入职文档里写清安装步骤；
- Serena（LSP 语义编辑 MCP）对 Java 的增量价值已收窄到跨文件符号级编辑，且其 Java 后端启动明显慢、第三方安全扫描评分偏低——**先用 jdtls-lsp，不够再单独评估 Serena，不要叠装**。

## 4. HTMX 部分

- 版本与文档：CLAUDE.md 钉死 HTMX 版本；查文档走 Context7（按版本拉取）而不是靠模型记忆；
- 约定写法：片段端点与整页端点的命名/包位置、`hx-target`/`hx-swap` 的团队默认、错误响应（如 422 + 片段回填表单）的统一处理，写进 `.claude/rules/htmx.md`；
- **验证的坑**：`hx-target` 写错、swap 目标不存在时 HTMX **静默失败**——MockMvc 和 curl 只能验响应内容，验不出浏览器侧 swap 行为。所以页面改动的验收标准必须包含真实浏览器验证（下一节）。

## 5. 页面验证回路（HTMX + JSP 的唯一可靠验收方式）

```
改 Controller / JSP → ./mvnw spring-boot:run（或团队起服务命令）
→ 用官方 webapp-testing skill 驱动 Playwright MCP：
  打开页面 → 执行交互（点击 hx-get 按钮等）→ 断言目标片段已替换
  → 截图存档 + 读 console 错误
→ 截图与断言结果写进 PR 描述，才算完成
```

- Playwright MCP 是微软官方实现，以无障碍树驱动浏览器、可截图可读 console，是本项目最关键的 MCP；
- 排查 HTMX 请求头（`HX-Request`、`HX-Target`）、CSRF 403 等浏览器侧问题时，Chrome DevTools MCP（Google 官方）看网络面板更顺手，与 Playwright 二选一起步即可；
- 注意 Playwright MCP 官方声明它**不是安全边界**：用隔离浏览器 profile，只连本地/测试环境，勿连生产。

## 6. JSP 遗留页面专项规则（迁移结论）

落为 `.claude/rules/jsp.md` 并用 `paths: ["src/main/webapp/**/*.jsp"]` 限定作用域，只在碰 JSP 时加载：

- **禁止新写 scriptlet**（`<% %>` 里写 Java 代码）：新逻辑一律放 Controller/Service，JSP 只做渲染；
- 表达式用 EL + JSTL 标签；输出必须转义（防 XSS，老页面是重灾区，改到哪查到哪）；
- JSP 定位是渲染层：不查库、不写业务判断（超过 EL/JSTL 能表达的就回 Controller 准备数据）；
- 改老页面时保持**手术式修改**：只动任务相关部分，不顺手重构整页（老 JSP 缺测试覆盖，大改风险高）；
- 每个改过的页面都要过第 5 节的浏览器验证回路——JSP 没有编译期保护，渲染错误只有打开才知道；
- 中长期：新页面不再新增 JSP（团队若决定迁移模板引擎，那是独立项目，不在本工作流范围内混做）。

## 7. 数据库访问

- 用 DBHub MCP（Bytebase，一个 server 通吃 Postgres/MySQL 等，工具少、省上下文，也是 Claude Code 官方 MCP 文档里的数据库示例 server）；
- **只连开发/测试库、只读账号起步**；写操作与生产库一律不通过 MCP；
- 已归档的官方 Postgres reference server 不要再装（见 [07](07-避坑清单.md)）。

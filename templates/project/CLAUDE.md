# 项目指令（CLAUDE.md 模板）

<!-- 用法：把 TODO 换成你项目的真实值。只保留"代码里看不到的事实"，目标 <200 行。
     维护原则：被纠正过两次的坑沉淀到这里；能删的行就删，不要写架构总览。 -->

## 技术栈（版本钉死，查文档按此版本）

- JDK：<!-- TODO，如 21 -->
- Spring Boot：<!-- TODO，如 3.5.x -->
- 构建：Maven Wrapper（只用 `./mvnw`，不要用系统 mvn）
- 前端：HTMX <!-- TODO 版本，如 2.0.x --> + 服务端渲染 JSP（`src/main/webapp/`），CSS 在 `src/main/webapp/static/css/`
- 数据库：<!-- TODO，如 PostgreSQL 16 / MySQL 8 -->，集成测试用 Testcontainers

## 常用命令（写全，不要省略）

```bash
./mvnw -q compile                              # 编译
./mvnw -Dtest=OrderServiceTest test            # 跑单个测试类
./mvnw -Dtest=OrderServiceTest#createOrder test # 跑单个测试方法
./mvnw verify                                  # 全量验证（提交前）
./mvnw spring-boot:run -Dspring-boot.run.profiles=local  # 本地起服务，端口 <!-- TODO 8080 -->
```

## 代码约定

- 分层单向依赖：Controller → Service → Mapper/Repository；Controller 不直接调持久层
- 依赖注入只用构造器注入，不用字段注入（`@Autowired` 打在字段上是旧代码才有的写法）
- 持久层沿用项目实际方案（如 MyBatis Mapper / Repository），不要为了模板改成 JPA；Controller 不直接暴露持久层对象
- REST 异常按项目约定返回 JSON（如 `@RestControllerAdvice`）；JSP/HTMX 页面异常走视图处理（如 `@ControllerAdvice` + ModelAndView），不要让页面收到 JSON 错误体；不要吞异常
- 测试：JUnit 5 + Mockito；新代码必须带测试，先写失败测试再实现

## HTMX / JSP 约定

- JSP 只做渲染：禁止新写 scriptlet，逻辑放 Controller/Service；表达式用 EL + JSTL，输出必须转义
- JSP 片段返回独立 JSP 视图名（如 `fragments/order-form` → `/WEB-INF/jsp/fragments/order-form.jsp`，实际路径以 ViewResolver 为准）；不要使用 Thymeleaf 的 `:: fragment` 语法；整页与片段路由沿用既有约定
- `hx-target` 必须指向页面上真实存在的 id；改完页面必须走浏览器验证（见 .claude/rules/htmx.md）
- `<!-- TODO 老页面样例 -->` 是遗留写法，新代码不要模仿它的内联脚本风格

## 验证要求（完成标准）

- 后端改动：相关测试转绿 + `./mvnw -q compile` 通过，给出命令输出，不要只说"测试全过"
- 页面改动：起服务 → 用 Playwright 打开页面执行真实交互 → 断言片段替换成功 + 截图；MockMvc 通过不等于页面可用
- 编译失败或测试跳过必须明确报告原因，不得宣称验证通过

## 约束与边界

- 不读 `.env*` 与任何凭据文件；不连生产数据库
- 不修改 `src/main/resources/db/migration/` 下已合并的迁移文件
- 不顺手重构任务之外的代码；老 JSP 只做手术式修改
- settings 的路径规则不等于进程隔离；Bash 脚本、MCP、hooks 的权限另行控制。
- 迁移目录使用 ask 规则，新增迁移仍可经确认创建；已合并迁移是否被篡改由迁移工具校验/CI 检查。
- Stop hook 仅检查 compile：环境/超时仅警告验证未完成；确认的编译错误首次反馈，修复后仍失败则报告失败并结束；合并前仍须 CI 跑 verify。

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

- 分层单向依赖：Controller → Service → Repository；Controller 不直接调 Repository
- 依赖注入只用构造器注入，不用字段注入（`@Autowired` 打在字段上是旧代码才有的写法）
- DTO 与 JPA 实体分离，Controller 不直接返回实体
- 异常走全局 `@RestControllerAdvice`（见 `<!-- TODO 类名 -->`），不要在 Controller 里 try-catch 吞异常
- 测试：JUnit 5 + Mockito；新代码必须带测试，先写失败测试再实现

## HTMX / JSP 约定

- JSP 只做渲染：禁止新写 scriptlet，逻辑放 Controller/Service；表达式用 EL + JSTL，输出必须转义
- HTMX 片段端点返回片段视图（命名后缀 `:: fragment` 风格见 `<!-- TODO 既有样例文件 -->`），整页与片段端点分开
- `hx-target` 必须指向页面上真实存在的 id；改完页面必须走浏览器验证（见 .claude/rules/htmx.md）
- `<!-- TODO 老页面样例 -->` 是遗留写法，新代码不要模仿它的内联脚本风格

## 验证要求（完成标准）

- 后端改动：相关测试转绿 + `./mvnw -q compile` 通过，给出命令输出，不要只说"测试全过"
- 页面改动：起服务 → 用 Playwright 打开页面执行真实交互 → 断言片段替换成功 + 截图；MockMvc 通过不等于页面可用
- 收工前不得留下编译失败或未说明的跳过测试

## 红线（另在 settings.json 里有机器强制，这里是说明）

- 不读 `.env*` 与任何凭据文件；不连生产数据库
- 不修改 `src/main/resources/db/migration/` 下已合并的迁移文件
- 不顺手重构任务之外的代码；老 JSP 只做手术式修改

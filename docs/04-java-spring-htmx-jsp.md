# 04 · Java / Spring Boot / HTMX / JSP 专项

本节是根据 Spring、HTMX 与 Claude Code 文档整理的项目适配建议，不是已经在你项目上运行过的结果。真实版本、部署方式与既有约定优先。

## 1. 先写清项目事实

- JDK、Spring Boot、HTMX 与数据库版本；Maven/Gradle Wrapper 与真实构建命令。
- 启动方式：可执行应用还是外部 Tomcat/WAR；端口、context path 与测试 profile。
- 持久层：MyBatis Mapper / JPA / JDBC 沿用现状，不为套模板迁移框架。
- REST 与页面的错误响应：REST 通常是 JSON；JSP/HTMX 则需要视图或 HTML 片段，不能统一套 `@RestControllerAdvice` 导致页面收到 JSON。
- 测试：JUnit/Mockito 按现有依赖版本；数据库行为用合适的集成测试，Testcontainers 需先具备容器运行环境。

Spring Boot 的 JSP 打包/容器限制须按所用版本核对[官方说明](https://docs.spring.io/spring-boot/reference/web/servlet.html#web.servlet.embedded-container.jsp-limitations)，不要把 `spring-boot:run` 当成所有 WAR 项目唯一的启动命令。

## 2. 编译、格式化与最终门禁

- 每批改动后执行相关测试，完成前 `./mvnw verify`；compile 只提供早期反馈。
- [Stop hook](../templates/project/.claude/hooks/verify-stop.py) 对环境/超时问题只警告验证未完成，对确认的编译错误有一次修复机会及二次失败出口，不强制离线构建；详情见[模板说明](../templates/README.md)。
- formatter 必须先在项目配置。不要每次编辑一个 Java 文件就全库 `spotless:apply`，也不要用 `|| true` 吞掉失败。采用项目约定的格式化命令，并把 check 纳入 CI。
- Java LSP 可辅助导航与诊断，不能替代编译/测试；安装前核对对应语言服务器的 JDK 要求。

## 3. JSP 片段是独立视图

默认 `InternalResourceViewResolver` 按前缀与后缀定位 JSP。例如前缀 `/WEB-INF/jsp/`、后缀 `.jsp` 时：

| Controller 返回的视图名 | JSP 文件 |
|---|---|
| `orders/detail` | `/WEB-INF/jsp/orders/detail.jsp` |
| `fragments/order-form` | `/WEB-INF/jsp/fragments/order-form.jsp` |

**`orders/detail :: fragment` 不是默认 JSP 片段语法**。普通 `@Controller` 返回视图名；`@RestController` 的字符串会成为响应体，不是 JSP 视图。

整页与片段可分路由，也可依项目约定按 `HX-Request: true` 分流；同 URL 分流应处理 `Vary: HX-Request` 与历史恢复。该请求头可伪造，不能用于鉴权。

来源：[Spring JSP/JSTL](https://docs.spring.io/spring-framework/reference/web/webmvc-view/mvc-jsp.html)。

## 4. HTMX 校验失败必须验证响应替换

HTMX 2.x 默认不会 swap 422。若项目约定校验失败返回 422 + 表单 HTML，应在公共布局的 `<head>`、加载 HTMX 前合并如下配置：

```html
<meta name="htmx-config" content='{"responseHandling":[
  {"code":"204","swap":false},
  {"code":"[23]..","swap":true},
  {"code":"422","swap":true,"error":false},
  {"code":"[45]..","swap":false,"error":true},
  {"code":"...","swap":false}
]}'>
```

规则按顺序匹配，422 必须先于 `[45]..`。已有全局配置应合并，不能覆盖其他设置；不使用此机制的旧版本沿用其事件处理方式。也可沿用项目已有的 200 + 错误片段契约，重点是前后端一致。

`hx-target` 必须解析到预期元素；失败可产生 `htmx:targetError` 等事件，不能只靠 HTTP 200 判断成功。`outerHTML` 替换还须保留后续请求使用的 id。

来源：[HTMX response handling](https://htmx.org/docs/#response-handling)。

## 5. 真实页面验证

起服务后选择 **Playwright 脚本或 Playwright MCP** 执行交互。官方 `webapp-testing` skill 使用原生 Python Playwright，不依赖 MCP；团队应选能留存和重复执行断言的方式。

最少覆盖：

1. 正常加载与成功提交：目标 DOM 确实更新，无意外整页嵌套。
2. 校验失败：无效输入触发 422/既有状态码，错误提示显示且输入保留。
3. CSRF/会话过期/认证失败：遵循既有安全契约，不把登录整页注入片段。
4. 连续操作：替换后 id 与事件仍有效；检查 console、网络与 HTMX 错误事件。

断言、截图与命令输出共同构成证据；截图本身不是自动化测试。MockMvc 可验证状态、model 与视图名，但不能证明 JSP 已在实际容器渲染或浏览器 swap 成功。

## 6. JSP 与安全

- 不新增 scriptlet 业务逻辑，JSP 只渲染准备好的 model。
- HTML 文本/带引号的普通属性用合适的转义；`c:out` / `fn:escapeXml` 不是 JS、CSS、URL 上下文的通用防注入方案。URL 校验协议并编码，避免脚本内拼接不可信 EL。
- 老页面做任务内修改；新页面是否使用 JSP 由项目架构决定，不擅自迁移模板引擎。
- DBHub 仅可选连接开发/测试库，使用数据库实际限制为只读的账号。不要把生产连接交给会话。

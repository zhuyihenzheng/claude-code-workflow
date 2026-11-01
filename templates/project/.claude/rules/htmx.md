---
paths:
  - "src/main/webapp/**"
  - "src/main/java/**/controller/**"
---

# HTMX 约定（编辑页面与 Controller 时加载）

- 片段与整页使用独立 JSP 视图；可以分路由，也可以按 `HX-Request: true` 分流，沿用既有约定。同一路由分流时处理缓存的 `Vary: HX-Request` 与历史恢复请求。`HX-Request` 不是鉴权依据。
- `hx-target` 必须指向当前页面真实存在的元素 id；`hx-swap` 模式沿用团队默认（`innerHTML`），特殊需求在代码评审中说明。
- 表单校验失败沿用项目契约：HTMX 2.x 默认不 swap 422。采用 422 + 表单片段时，必须先在公共布局配置 `responseHandling` 的 422 swap 规则（规则放在 `[45]..` 之前）；否则使用项目已有的 200 + 错误片段约定。不要放开全部 4xx/5xx。
- CSRF：HTMX 请求要带上项目统一的 CSRF 头处理（全局监听或 `hx-headers`），新增页面不要漏。
- **验证铁律**：`hx-target` 写错或目标不存在时 HTMX 不会完成替换（可产生 `htmx:targetError`），MockMvc/curl 都验不出来。凡改动带 HTMX 的页面，完成标准是真实浏览器验证：打开页面 → 触发交互 → 断言目标片段内容已替换 + 无 console 错误 + 截图留存。

- 浏览器验收同时覆盖成功提交、校验失败回填，以及 CSRF/会话失效；不能把登录整页塞进片段目标。

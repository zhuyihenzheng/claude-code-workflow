---
paths:
  - "src/main/webapp/**"
  - "src/main/java/**/controller/**"
---

# HTMX 约定（编辑页面与 Controller 时加载）

- 片段端点与整页端点分开：HTMX 请求（带 `HX-Request` 头）返回片段视图，普通请求返回整页；判断方式沿用项目既有工具类（见 CLAUDE.md 中的样例）。
- `hx-target` 必须指向当前页面真实存在的元素 id；`hx-swap` 模式沿用团队默认（`innerHTML`），特殊需求在代码评审中说明。
- 表单校验失败走统一处理：返回 422 + 表单片段回填错误信息，不要整页刷新。
- CSRF：HTMX 请求要带上项目统一的 CSRF 头处理（全局监听或 `hx-headers`），新增页面不要漏。
- **验证铁律**：`hx-target` 写错或目标不存在时 HTMX 静默失败，MockMvc/curl 都验不出来。凡改动带 HTMX 的页面，完成标准是真实浏览器验证：打开页面 → 触发交互 → 断言目标片段内容已替换 + 无 console 错误 + 截图留存。

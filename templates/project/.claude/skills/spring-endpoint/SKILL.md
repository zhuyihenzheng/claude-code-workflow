---
name: spring-endpoint
description: 新增一个 Spring Boot 接口（含页面片段）的标准流程。当用户要求"新增接口/加个页面/加个查询"时使用。
---

# 新增接口标准流程

按顺序执行，每步有明确产出，不要跳步：

## 1. 确认契约
- 入参/出参、是否需要 HTMX 片段版本、权限要求；不清楚先问，不要猜。
- 参照既有样例：`<!-- TODO 填一个项目内的标杆 Controller 路径 -->` 的写法。

## 2. 先写测试（红）
- Service 层单元测试（JUnit 5 + Mockito）；
- Controller 层用 MockMvc 写契约测试，断言状态码与关键响应内容；
- 运行并确认测试以预期原因失败：`./mvnw -Dtest=<TestClass> test`。

## 3. 实现（绿）
- 顺序：DTO → Service → Repository（如需）→ Controller；
- 构造器注入；DTO 不暴露实体；异常走全局处理，不要本地吞异常。

## 4. 页面（如涉及 HTMX/JSP）
- 整页与片段端点分开；`hx-target` 指向真实 id；表单失败若使用 422，先确认公共布局已配置 422 swap（HTMX 默认不替换 422），再验证片段回填；
- JSP 禁新写 scriptlet、输出转义（见 .claude/rules/）。

## 5. 验证（完成标准，缺一不可）
- `./mvnw -Dtest=<TestClass> test` 转绿，贴输出；
- `./mvnw -q compile` 通过；
- 涉及页面：起服务后用浏览器打开页面执行真实交互，断言片段替换成功并截图；
- 最后用 code-reviewer 子代理过一遍 diff，再汇报。

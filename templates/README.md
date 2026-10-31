# 模板使用说明

这是一套待项目适配的配置起点，不是可直接启动的 Spring Boot 应用，也不是安装好的 Claude Code 插件。

## 前置条件与适用范围

- 本地 hooks：macOS / Linux / WSL、Python 3.9+、JDK，以及目标项目已有的 `pom.xml` 和可执行 `mvnw`。Windows 原生需要改用 `mvnw.cmd` 并调整进程管理，当前未支持。
- Playwright MCP：Node.js / npx、浏览器安装条件；启动后在 `/mcp` 确认连接。
- 先记录 `claude --version`，用 `/doctor`、`/permissions`、`/hooks` 检查配置。模板测试不等于在每个 Claude Code 版本上验证过。
- 本仓库不是 Maven 工程，不应在本仓库根目录运行模板的 compile hook。

## 安装与适配

1. 按相对路径合并 `project/CLAUDE.md`、`project/.claude/` 与 `project/.gitignore` 到目标项目。已有文件逐项合并，不要整目录覆盖。必须连同 `.claude/hooks/verify-stop.py` 一起复制。
2. 按实际项目填写 CLAUDE.md 的版本、样例路径、启动方式、测试类；MyBatis 项目保留 Mapper，不引入 JPA。外部 Tomcat/WAR 项目使用自己的启动与部署命令。
3. 运行目标项目的 `./mvnw -q compile`、相关测试和 `./mvnw verify`，先解决环境问题再启用 hook。
4. 按需合并 `.mcp.json`。默认只有 Context7（无密钥公共访问）和隔离 Playwright；不用的 server 直接移除。
5. DBHub / GitHub 是 [可选配置](mcp.optional.json)。只合并需要的 server，并在启动前提供 `DATABASE_URL` / `GITHUB_PERSONAL_ACCESS_TOKEN`；DBHub 只能用开发/测试库的只读账号。Context7 需要认证时可按其官方文档加 `CONTEXT7_API_KEY` header。
6. GitHub 集成需要单独安装 Claude GitHub App、配置仓库 Secret，然后选择下面的 workflow；不需要 GitHub 自动化就不复制它们。

本地 npm server 已固定为审查时 registry 返回的版本；这仅固定直接版本，不锁定全部传递依赖，不代表已完成 server 端到端兼容性验证。升级需重新验证；HTTP MCP 服务由提供商更新。

## Hook 行为与限制

- Stop hook 从脚本所在的项目根运行 `./mvnw -B -q compile`，不使用 `-o`，允许首次下载依赖；首次使用最好先手动预热依赖。
- 编译超时 90 秒，hook 外层超时 120 秒；大工程需要同时增大两处限制。超时会终止 Maven 进程组。
- 首次失败：退出码 2，附日志末尾供修复；`stop_hook_active=true` 时仍重新编译，若再次失败则用 `continue:false` / `stopReason` 明确报告失败并结束，避免反复拦截。
- 每次正常结束均会检查（包括只改文档的会话），属于简单默认策略。团队可改为按变更判断，但须覆盖暂存、未暂存、新文件与多模块情况。
- 没有默认格式化 hook：原模板的 `spotless:apply || true` 会吞错，还可能改到任务之外的文件。先确认项目已配置 formatter，再显式运行项目的格式化命令和 check；失败必须报告。
- compile 不运行测试，也不验证 JSP 渲染；**CI 的 verify、页面交互断言与分支保护才是合并门禁**。用户中断、hook 超时/禁用等场景也不能视作验证通过。

可在目标项目根手动测试（编译实际会执行）：

```bash
printf '%s\n' '{"stop_hook_active":false}' | python3 .claude/hooks/verify-stop.py
```

## 权限语义

- 默认没有 `Bash(./mvnw *)`：它会顺带允许 deploy、任意插件目标等。定向测试命令按需确认；即便允许的 Maven 命令也会执行仓库里的构建逻辑，只在信任的 checkout 中运行。
- `.env*` 规则覆盖根目录与子目录，使用项目根锚定路径。`credentials` / `secret` 文件名规则是示例，可能误伤业务类名，须按实际凭据路径调整。
- 迁移目录使用 `ask`，允许确认后新增迁移；原来的整个目录 `deny` 会把新增一起拦住。已合并迁移的不可变性由 Flyway/Liquibase 校验、CI 与人审保证。
- 路径规则不覆盖所有任意脚本/MCP/hook 的访问；两条危险 Bash deny 也不是完整命令防火墙。需 OS 沙箱、最小凭据和项目外密钥管理配合，见 [权限说明](../docs/02-基础搭建.md)。
- Hook 本身以当前用户身份运行，不能把 settings 中的工具权限当作 hook 的执行限制。

## GitHub workflows

| 文件 | 使用方式 |
|---|---|
| `project/.github/workflows/claude.yml` | `@claude` 评论/评审/新 issue 触发，可修改代码；默认 20 轮、5 美元、20 分钟 |
| `project/.github/workflows/claude-review.yml.example` | 明确需要自动评审时才改名为 `.yml`；带独立 prompt，只评审同仓库非草稿 PR，结果在 Actions 日志；15 轮、3 美元、20 分钟 |

两者保留 action 默认的触发者写权限检查与 bot 限制。预算数字是模板起点，按团队调整。美元限制不能替代账号/组织支出控制。

`id-token: write` 用于默认 GitHub App 认证。API key 使用 `anthropic_api_key`；订阅 OAuth 改成 `claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}`。不能只换 Secret 名而保留错误的 input。

自动评审模板刻意不检出 PR head 执行代码；fork PR 不运行，不为获取 secrets 改用 `pull_request_target` 执行 fork 代码。要自动发评论，按官方独立的 code-review 示例配置工具与权限。若 action 在默认配置下创建 App token，权限还取决于 App 安装授权，不能只看 workflow 的 `contents: read` 就声称完全只读。

## 本仓库验证

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

测试覆盖模拟 Maven 的成功/失败/重试/超时/子进程清理、路径含空格和子目录启动，以及 JSON、workflow 关键配置和文档相对链接。它们不调用 Claude API，不消耗模型额度，也不代替真实 Java 项目的验收。

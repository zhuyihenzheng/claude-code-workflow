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
6. GitHub 集成按下面的 workflow 分别配置认证：交互模式使用 Claude GitHub App，自动评审示例使用只读 workflow token；两者都需模型凭据。不需要 GitHub 自动化就不复制它们。

本地 npm server 已固定为审查时 registry 返回的版本；这仅固定直接版本，不锁定全部传递依赖，不代表已完成 server 端到端兼容性验证。升级需重新验证；HTTP MCP 服务由提供商更新。

## Hook 行为与限制

- Stop hook 优先使用 `CLAUDE_PROJECT_DIR`，否则从脚本调用路径定位项目根（不解析共享 hooks 的符号链接），在该根目录运行 `./mvnw -B -q compile`，不使用 `-o`，允许首次下载依赖；首次使用最好先手动预热依赖。
- 编译超时 90 秒，hook 外层超时 120 秒；大工程需要同时增大两处限制。超时和收到 SIGTERM / SIGINT / SIGHUP 时，仅在 Maven leader 仍存活时向进程组发终止信号，退出竞态的 ESRCH/EPERM 不抛异常；回收 leader 后不再向可能复用的 PGID 发信号。wrapper 提前退出后遗留的后台进程由 wrapper/调用方负责清理。SIGKILL 无法捕获，调用方须负责清理整棵进程树。
- 扫描完整日志分类：包含 Maven compiler 的 `:compile` 目标及 `Compilation failure`，且没有 `invalid target/source release` 或 `release version N not supported` 等 JDK 不匹配诊断时，首次退出码 2，仅附日志末尾最多 8000 字节供修复；`stop_hook_active=true` 时仍重新编译，若再次确认编译失败则用 `continue:false` / `stopReason` 报告失败并结束。
- 缺少 pom/wrapper、无执行权限、启动错误、超时、中断、依赖/环境错误及无法分类的非零退出：返回 0 与 `systemMessage` 警告“验证未完成”，不请求额外模型轮次，也不表示通过。超时、JDK 不匹配及未知非零退出只显示简短摘要与手动编译命令，不附原始日志。诊断识别刻意保守；自定义编译器等未识别情况需人工运行构建，CI 必须通过。
- 每次正常结束均会检查（包括只改文档的会话），属于简单默认策略。团队可改为按变更判断，但须覆盖暂存、未暂存、新文件与多模块情况。
- 没有默认格式化 hook：原模板的 `spotless:apply || true` 会吞错，还可能改到任务之外的文件。先确认项目已配置 formatter，再显式运行项目的格式化命令和 check；失败必须报告。
- compile 不运行测试，也不验证 JSP 渲染；**CI 的 verify、页面交互断言与分支保护才是合并门禁**。用户中断、hook 超时/禁用等场景也不能视作验证通过。

可在目标项目根手动测试（编译实际会执行）：

```bash
printf '%s\n' '{"stop_hook_active":false}' | python3 .claude/hooks/verify-stop.py
```

## 权限语义

- 默认没有 `Bash(./mvnw *)`：它会顺带允许 deploy、任意插件目标等。定向测试命令按需确认；即便允许的 Maven 命令也会执行仓库里的构建逻辑，只在信任的 checkout 中运行。
- `/**/.env` 和 `/**/.env.*` 覆盖根目录与子目录，不再重复列出 `/.env*`。项目 `.claude/settings.json` 的 `/` 锚定主工作目录，不是 `.claude` 目录；请从项目根/worktree 根启动。通过 `--settings` 传入的文件有不同锚定语义，见[官方权限说明](https://code.claude.com/docs/en/permissions)。`credentials` / `secret` 文件名规则是示例，可能误伤业务类名，须按实际凭据路径调整。
- 迁移目录使用 `ask`，允许确认后新增迁移；原来的整个目录 `deny` 会把新增一起拦住。已合并迁移的不可变性由 Flyway/Liquibase 校验、CI 与人审保证。
- 路径规则不覆盖所有任意脚本/MCP/hook 的访问；两条危险 Bash deny 也不是完整命令防火墙。需 OS 沙箱、最小凭据和项目外密钥管理配合，见 [权限说明](../docs/02-基础搭建.md)。
- Hook 本身以当前用户身份运行，不能把 settings 中的工具权限当作 hook 的执行限制。

## GitHub workflows

| 文件 | 使用方式 |
|---|---|
| `project/.github/workflows/claude.yml` | `@claude` 评论/评审/新 issue 触发，可修改代码；默认 20 轮、5 美元、20 分钟 |
| `project/.github/workflows/claude-review.yml.example` | 明确需要自动评审时才改名为 `.yml`；带独立 prompt，只评审同仓库非草稿 PR，结果在 Actions 日志；15 轮、3 美元、20 分钟 |

两者保留 action 默认的触发者写权限检查与 bot 限制。预算数字是模板起点，按团队调整。美元限制不能替代账号/组织支出控制。

交互模板的 `id-token: write` 用于默认 GitHub App 认证；`additional_permissions: actions: read` 与 job 的同名权限一并配置，App 安装也须允许。自动评审模板显式传入只读 `${{ github.token }}` 作为 `github_token` 和 `GH_TOKEN`，不使用 App/OIDC；先通过 `gh pr view/diff` 检查读取权限，失败就终止，不调用模型。API key 使用 `anthropic_api_key`；订阅 OAuth 改成 `claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}`。不能只换 Secret 名而保留错误的 input。

自动评审模板检出可信 base；Read/Grep/Glob 只能看到 base，以 PR diff 的新增侧 hunk 计算 HEAD 行号。缺少 diff 外的 HEAD 上下文时报告评审不完整，不猜测。它刻意不检出 PR head 执行代码；fork PR 不运行，不为获取 secrets 改用 `pull_request_target` 执行 fork 代码。要自动发评论，按官方独立的 code-review 示例配置工具与权限。交互模板创建的 App token 权限还取决于安装授权；自动评审模板显式传入 workflow token，避免继承更广的 App 权限。

## 本仓库验证

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

测试覆盖模拟 Maven 的成功/编译错误/环境错误/重试/超时/信号中断及子进程清理、环境变量/符号链接/空格/子目录路径，以及 JSON、workflow 关键配置和文档相对链接。它们不调用 Claude API，不消耗模型额度，也不代替真实 Java 项目的验收。

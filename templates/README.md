# 模板使用说明

这是一套供 Copilot 与 Claude Code 共用项目规则的配置起点，不是可直接启动的 Spring Boot 应用，也不是安装好的插件。

`project/` 下的项目模板面向日本团队，正文使用日语；本说明、`user/` 模板与仓库内手册仍保留中文。

## 前置条件与适用范围

- 模板支持 macOS / Linux / WSL 与原生 Windows 的命令和权限配置；目标项目需有 JDK、`pom.xml` 与 Maven Wrapper（`mvnw` / `mvnw.cmd`）。Windows 安装步骤见 [基础搭建](../docs/02-基础搭建.md#6-windows-两条路径)。
- 模板不启用任何 hooks，结束会话不会自动编译。保留的 `.claude/hooks/verify-stop.py` 是可选的 macOS / Linux / WSL 参考样例，需要 Python 3.9+ 和可执行 `mvnw`；它使用 POSIX 进程组，不能在原生 Windows 使用，留给用户按需改写。
- Playwright MCP：Node.js / npx、浏览器安装条件；启动后在 `/mcp` 确认连接。
- 先记录 `claude --version`，用 `/doctor`、`/permissions`、`/hooks` 检查配置。模板测试不等于在每个 Claude Code 版本上验证过。
- 规则同步脚本需要 Python 3.9+，仅使用标准库；原生 Windows 的 Python 命令可用 `py` 或已安装的 `python`。
- 本仓库不是 Maven 工程，不应在本仓库根目录运行模板的 compile hook。

## 安装与适配

1. 按相对路径合并 `project/AGENTS.md`、`project/CLAUDE.md`、`project/.claude/`、`project/.github/copilot-instructions.md`、`project/.github/instructions/`、`project/.gitignore` 与 `project/.gitattributes` 到目标项目；再把本仓库的 [scripts/sync_rules.py](../scripts/sync_rules.py) 复制到目标项目的 `scripts/sync_rules.py`。已有文件逐项合并，不要整目录覆盖。复制文件不会注册 hook。推荐用 [安装脚本](../scripts/install.py) 一次完成以上复制并预演合并（Python 3.9+，跨平台）：

   ```bash
   python3 scripts/install.py project /path/to/your-project          # 预演，只打印计划
   python3 scripts/install.py project /path/to/your-project --apply  # 写入 create / merge
   ```

   规则：目标缺失的文件原样复制（`create`，含 `scripts/sync_rules.py`）；内容相同跳过（`skip`）；`.claude/settings.json` 与 `.mcp.json` 只追加缺失的 allow/deny/ask 规则与 MCP server，已有值优先，不会写入 `hooks`（`merge`，JSON 会按 2 空格重新格式化）；`.gitignore` / `.gitattributes` 只追加缺失行并保留原换行；其余不同的文件（AGENTS.md、CLAUDE.md、rules、workflow 等）报告为 `conflict`，**不改动**，需手动对比。已有的 `Bash(./mvnw *)` 等宽泛规则或与模板 deny/ask 冲突的 allow 会在输出中提示。脚本不删除任何文件，合并后仍须 `git diff` 审查再提交。
2. AGENTS.md 的“チーム共通ルール”跨系统原样复制；只在“本システム固有情報”填写 JSP / HTMX / 两者并用、版本、样例路径、启动方式与测试类。MyBatis 项目保留 Mapper，不引入 JPA；外部 Tomcat/WAR 使用自己的部署命令。CLAUDE.md 保持 `@AGENTS.md` 导入，只放 Claude Code 配置入口。
3. 手动运行目标项目的 `./mvnw -q compile`、相关测试和 `./mvnw verify`；Windows CMD 用 `mvnw.cmd`，Git Bash 用 `./mvnw.cmd`，PowerShell 用 `.\mvnw.cmd`，参数相同。先解决环境问题，再考虑可选 hook。
4. 按需合并 `.mcp.json`。默认只有 Context7（无密钥公共访问）和隔离 Playwright；不用的 server 直接移除。
5. DBHub / GitHub 是 [可选配置](mcp.optional.json)。只合并需要的 server，并在启动前提供 `DATABASE_URL` / `GITHUB_PERSONAL_ACCESS_TOKEN`；DBHub 只能用开发/测试库的只读账号。Context7 需要认证时可按其官方文档加 `CONTEXT7_API_KEY` header。
6. GitHub 集成按下面的 workflow 分别配置认证：交互模式使用 Claude GitHub App，自动评审示例使用只读 workflow token；两者都需模型凭据。不需要 GitHub 自动化就不复制它们。

## HTMX 页面检查脚本

[`project/scripts/htmx-check.mjs`](project/scripts/htmx-check.mjs) 用 Playwright 打开真实页面：填写 → 点击 → 等待 `--expect` 目标被替换（或出现 `--contains` 文本）→ 检查 `--absent`（例如登录页文字未塞进片段）、`htmx:targetError` / `responseError` / `swapError` 等错误事件、console 错误 → 可选截图。退出码 `0` 合格、`1` 断言失败、`2` 参数/浏览器/服务不可达等“验证未完成”，不能把 2 当成通过。

```bash
npm install --no-save --no-package-lock playwright   # Playwright MCP 已要求 Node；按团队固定版本
npx playwright install chromium
node scripts/htmx-check.mjs --url http://localhost:8080/orders/new \
  --fill "#name=テスト" --click "#submit" --expect "#order-form" \
  --contains "登録しました" --absent "ログイン" --screenshot target/htmx-check/success.png
```

每次运行验证一次交互；成功提交、校验失败回填、会话失效分别运行。需要登录的页面请在脚本基础上加入团队的测试账号登录步骤（只用合成数据账号）。本仓库测试用模拟 htmx 事件的本地页面验证脚本判定逻辑，并在 CI 的 Ubuntu 浏览器 job 中强制执行；它没有加载真实 htmx 库，也不代替目标项目页面的验收。

## 规则维护与 Copilot 兼容范围

AGENTS.md 是项目规则的唯一事实来源；`.github/copilot-instructions.md` 只保留必守摘要，修改共通规则时同时核对摘要。路径细则只改 `.claude/rules/*.md`，由脚本转换 `paths:` 列表为 Copilot 的 `applyTo`，正文原样生成；不要直接编辑 `.github/instructions/` 镜像。

在本模板仓库根运行（省略参数时默认使用脚本所在仓库的 `templates/project`）：

```bash
python3 scripts/sync_rules.py
python3 scripts/sync_rules.py --check
```

复制到目标项目后，在目标项目根运行，显式传入 `.`（也可传入其他项目根路径）：

```bash
python3 scripts/sync_rules.py .
python3 scripts/sync_rules.py . --check
```

原生 Windows 将 `python3` 换为 `py` 或 `python`，参数相同。每次编辑路径规则后先生成、再 check；目标项目 CI 也应执行 `--check`，不同步时退出 1，不写文件。脚本支持现有的 `paths:` 块列表（双引号、单引号或简单无引号 glob），不解析任意 YAML；无效输入退出 2。输出 UTF-8 / LF；删除源规则后只清理带脚本标记的镜像，其他自有指令保留。

Copilot 的 IDE、agent 与 code review 是否同时读取 AGENTS.md、支持哪些路径指令取决于版本与入口，**以 GitHub 官方文档为准**：见[仓库自定义指令](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions)。部分入口可能只读取 copilot-instructions.md，因此不能只留下“去读 AGENTS.md”一句话。Claude Code 通过[官方支持的 `@path` 导入](https://code.claude.com/docs/en/memory#import-additional-files)读取 AGENTS.md；真实加载情况仍需在所用版本验收。多系统推广分工见[团队协作](../docs/06-团队协作与ci.md#6-copilot-与-claude-code-共存--多系统推广)。

本地 npm server 已固定为审查时 registry 返回的版本；这仅固定直接版本，不锁定全部传递依赖，不代表已完成 server 端到端兼容性验证。升级需重新验证；HTTP MCP 服务由提供商更新。

原生 Windows 启动 `npx` 类型的 MCP server 时，可能需要通过 `cmd /c npx ...` 调用。仅在 Windows 的目标配置中将该 server 的 `command` 改为 `cmd`，并在原 `args` 前加 `"/c", "npx"`。例如 Playwright（保留原版本和参数）：

```json
{
  "command": "cmd",
  "args": ["/c", "npx", "-y", "@playwright/mcp@0.0.83", "--isolated"]
}
```

此片段是单个 server 的配置，放在 `mcpServers.playwright` 下；[可选配置](mcp.optional.json) 中的 `npx` server 同理。仓库的跨平台 `.mcp.json` 保持原样；以目标环境 `/mcp` 实测和[官方 MCP 文档](https://code.claude.com/docs/en/mcp)为准。

## 可选 Stop hook 参考样例（默认不启用）

`settings.json` 没有 `hooks` 键。以下 JSON **仅供 macOS / Linux / WSL 用户自行选择启用**：先检查参考脚本和目标项目的手动编译，再将此 `hooks` 字段合并到目标 `.claude/settings.json` 的顶层（保留既有权限配置）。原生 Windows 需要用户先改写脚本的命令、信号与进程管理，不要直接启用本样例。

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/verify-stop.py\"",
            "timeout": 120
          }
        ]
      }
    ]
  }
}
```

以下行为仅适用于用户手动注册后的 POSIX 参考样例，不代表模板已启用：

- Stop hook 优先使用 `CLAUDE_PROJECT_DIR`，否则从脚本调用路径定位项目根（不解析共享 hooks 的符号链接），在该根目录运行 `./mvnw -B -q compile`，不使用 `-o`，允许首次下载依赖；首次使用最好先手动预热依赖。
- 编译超时 90 秒，hook 外层超时 120 秒；大工程需要同时增大两处限制。超时和收到 SIGTERM / SIGINT / SIGHUP 时，仅在 Maven leader 仍存活时向进程组发终止信号，退出竞态的 ESRCH/EPERM 不抛异常；回收 leader 后不再向可能复用的 PGID 发信号。wrapper 提前退出后遗留的后台进程由 wrapper/调用方负责清理。SIGKILL 无法捕获，调用方须负责清理整棵进程树。
- 扫描完整日志分类：包含 Maven compiler 的 `:compile` 目标及 `Compilation failure`，且没有 `invalid target/source release` 或 `release version N not supported` 等 JDK 不匹配诊断时，首次退出码 2，仅附日志末尾最多 8000 字节供修复；`stop_hook_active=true` 时仍重新编译，若再次确认编译失败则用 `continue:false` / `stopReason` 报告失败并结束。
- 缺少 pom/wrapper、无执行权限、启动错误、超时、中断、依赖/环境错误及无法分类的非零退出：返回 0 与 `systemMessage` 警告“コンパイルの検証は完了していません”，不请求额外模型轮次，也不表示通过。超时、JDK 不匹配及未知非零退出只显示简短摘要与手动编译命令，不附原始日志。诊断识别刻意保守；自定义编译器等未识别情况需人工运行构建，CI 必须通过。
- 若手动注册，样例会在每次正常结束时检查（包括只改文档的会话）。团队可改为按变更判断，但须覆盖暂存、未暂存、新文件与多模块情况。
- 没有默认格式化 hook：原模板的 `spotless:apply || true` 会吞错，还可能改到任务之外的文件。先确认项目已配置 formatter，再显式运行项目的格式化命令和 check；失败必须报告。
- compile 不运行测试，也不验证 JSP 渲染；**CI 的 verify、页面交互断言与分支保护才是合并门禁**。用户中断、hook 超时/禁用等场景也不能视作验证通过。

macOS / Linux / WSL 可在目标项目根手动测试参考样例（无需注册 hook，编译实际会执行）：

```bash
printf '%s\n' '{"stop_hook_active":false}' | python3 .claude/hooks/verify-stop.py
```

## 权限语义

- 默认没有 `Bash(./mvnw *)`：它会顺带允许 deploy、任意插件目标等。定向测试命令按需确认；即便允许的 Maven 命令也会执行仓库里的构建逻辑，只在信任的 checkout 中运行。
- Windows 的 Bash allow 同时列出 `mvnw.cmd` 与 `./mvnw.cmd` 的精确命令；[官方权限文档](https://code.claude.com/docs/en/permissions#powershell)已支持 `PowerShell(...)` 语法，因此也提供 `.\mvnw.cmd` 的同等规则。旧版 CLI 是否提供 PowerShell 工具以安装版本为准，用 `/permissions` 核对；Bash 规则不会自动匹配 PowerShell 命令。
- `/**/.env` 和 `/**/.env.*` 覆盖根目录与子目录，不再重复列出 `/.env*`。项目 `.claude/settings.json` 的 `/` 锚定主工作目录，不是 `.claude` 目录；请从项目根/worktree 根启动。通过 `--settings` 传入的文件有不同锚定语义，见[官方权限说明](https://code.claude.com/docs/en/permissions)。`credentials` / `secret` 文件名规则是示例，可能误伤业务类名，须按实际凭据路径调整。
- 官方文档说明 Windows 路径先规范化为 POSIX 形式再匹配，因此这些规则继续使用正斜杠 `/`；真实 Windows 上的 deny 匹配仍待验收，不能把模板字符串断言当成权限引擎测试。
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

测试覆盖模拟 Maven 的成功/编译错误/环境错误/重试/超时/信号中断及子进程清理、环境变量/符号链接/空格/子目录路径，以及 JSON、workflow 关键配置、agent/skill/rule frontmatter、CLAUDE.md 行数预算、文档相对链接、AGENTS.md 分层/导入与 Copilot 规则同步，和安装脚本的预演/复制/JSON 与行合并/冲突保留/CRLF 保留。它们不调用 Claude API，不消耗模型额度，也不代替真实 Java 项目的验收。

CI 矩阵包含 Linux / macOS / Windows。`tests/test_hooks.py` 仅测试 POSIX 参考脚本，在原生 Windows 整个模块跳过；模板测试在三平台运行。Windows 本地用 `py -m pip install -r requirements-dev.txt` 和 `py -m unittest discover -s tests -v`（或对应的 `python`）。尚未在真实 Windows 验收 Claude Code、Maven 或 MCP。

# GitHub Copilot で使う場合の設定（人向け）

このテンプレートの大半は GitHub Copilot でもそのまま使える。Copilot が読み込むもの、読み込まないもの、人がリポジトリの設定画面で行う作業をまとめる。

## Copilot がそのまま読み込むもの

| ファイル | Copilot の機能 |
|---|---|
| `.github/copilot-instructions.md` | Chat、クラウドエージェント、コードレビュー |
| `.github/instructions/*.instructions.md`（`.claude/rules/` から生成） | クラウドエージェント、コードレビュー |
| `AGENTS.md`、`CLAUDE.md` | クラウドエージェント、コードレビュー。`CLAUDE.md` の補足は Claude Code 専用と明記している |
| `REVIEW.md` | コードレビュー（人と Claude Code の code-reviewer も同じ基準を使う） |
| `.claude/skills/`（`spring-endpoint`、`change-flow`、`correct`、`feature-map`） | クラウドエージェント、コードレビュー、CLI、IDE のエージェントモード（IDE はバージョンによる） |
| `scripts/guard.py`、`./mvnw verify`（ArchUnit、PMD）、`specs-ai/` の Markdown | ツールに依存しない。CI の判定は Copilot が作った PR にも同じく適用される |

## 人が設定するもの

1. **コンテンツ除外**（Copilot Business / Enterprise）：`config/copilot/content-exclusion.yml` の内容を、リポジトリの Settings → Copilot → Content exclusion に貼る。`.env`、認証情報、Excel 原本を Copilot の文脈から外す。反映まで最大 30 分かかる。ファイルシステムの安全境界ではないため、機密情報をリポジトリに置かないことが前提である。
2. **クラウドエージェントの環境（任意。クラウドエージェントを使う場合だけ）**：既定では導入しない。使う場合は、インストーラーに `--with-copilot-cloud-agent` を付けて `.github/workflows/copilot-setup-steps.yml.example` を入れ、`copilot-setup-steps.yml` に名前を変えてデフォルトブランチにマージする。Python（`xlsx2ai.py` の依存）、Playwright と Chromium、Maven の依存関係が、エージェントの作業開始前に用意される。IDE の Copilot だけを使う場合は不要。
3. **人の承認が必須の範囲**：`.github/CODEOWNERS.example` を `.github/CODEOWNERS` に名前を変えて `@OWNER` を置き換え、ブランチ保護で「Require review from Code Owners」を有効にする。guard のルール・ベースライン・例外、ArchUnit と PMD のルール、AI へのルールの変更に、人の承認が必要になる。

## Copilot には効かないもの

- `.claude/settings.json` の allow／deny／ask（コマンドの許可、`.env` と Excel 原本の読み取り禁止、ベースライン更新の確認）。読み取りは上記 1、ルールとベースラインの変更は上記 3、合否は CI とブランチ保護で代替する。
- `.claude/agents/code-reviewer.md` のサブエージェント。Copilot はコードレビューが `REVIEW.md` を読む（Copilot CLI は `.claude/agents/` のエージェントも読み込む）。
- `.mcp.json` の MCP サーバー。Copilot で MCP を使う場合は Copilot 側で別に設定する。

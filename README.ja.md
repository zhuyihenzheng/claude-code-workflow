# Claude Code 開発ワークフロー構築ハンドブック

[![Validate templates](https://github.com/zhuyihenzheng/claude-code-workflow/actions/workflows/validate.yml/badge.svg)](https://github.com/zhuyihenzheng/claude-code-workflow/actions/workflows/validate.yml)

[中文](README.md)

**Java + Spring Boot（JSP / HTMX）** のプロジェクトに Claude Code をチームで導入するためのハンドブックとテンプレートです。プロジェクトルールは `AGENTS.md` を唯一の正本とし、GitHub Copilot と共用します。

| 構成 | 内容 | 言語 |
|---|---|---|
| [docs/](docs/) | 全体計画、セットアップ、標準ワークフロー、ツール選定、注意点 | 中国語 |
| [templates/project/](templates/project/) | ルール、権限設定、サブエージェント、skill、MCP、workflow、検証スクリプト | 日本語 |
| [scripts/install.py](scripts/install.py) | テンプレートを既存プロジェクトへ非破壊でマージするインストーラー | — |

そのまま動く製品ではなく、各プロジェクトに合わせて調整する出発点です。CI ではサンプルアプリで動作を確認していますが、業務プロジェクトでの受け入れ確認は別途必要です。

## 基本方針

1. **短く正確な `AGENTS.md`**（150 行未満）。チーム共通ルールとシステム固有情報を分け、`CLAUDE.md` は `@AGENTS.md` で取り込みます。
2. **判定可能な検証ループ**。JUnit と `./mvnw verify` に加え、実際のブラウザーで HTMX／JSP の描画と操作結果をアサーションで確認します。
3. **機械的に確認できる制約はツールと CI に任せる**。権限は `settings.json` で絞り、マージの可否は CI とブランチ保護で判定します。hooks は登録していません。

## 既存プロジェクトへの導入

```bash
python3 scripts/install.py project /path/to/your-project          # 予行：計画を表示するだけで、書き込まない
python3 scripts/install.py project /path/to/your-project --diff   # 予行：既存ファイルとの差分も表示する
python3 scripts/install.py project /path/to/your-project --apply  # 書き込む
```

既存ファイルは上書きも削除もしません。

| 表示 | 意味 |
|---|---|
| `create` | 存在しないファイルをコピーする |
| `merge` | `settings.json` / `.mcp.json` は不足しているルールだけを追加し、`.gitignore` / `.gitattributes` は不足している行だけを追加する |
| `conflict` | 内容が異なるファイル、またはシンボリックリンク。変更しないため、`--diff` で確認して手動でマージする |
| `optional` | GitHub workflow。コミットした時点で有効になり、シークレットが必要なため、`--with-workflows` を指定した場合のみコピーする |

導入後は、`AGENTS.md` の「本システム固有情報」の TODO（バージョン、コマンド、画面の確認手順）を記入します。設定ファイルの構成は、導入先の `.claude/README.md` に日本語で記載しています。

## 導入されるもの

```
AGENTS.md                         プロジェクトルールの唯一の正本（Copilot と共用）
CLAUDE.md                         @AGENTS.md と Claude Code 固有の補足
.claude/settings.json             権限：mvnw の完全一致のみ allow、.env・認証情報・xlsx は deny、マイグレーションは ask
.claude/rules/{jsp,htmx}.md       対象パスを扱うときだけ読み込まれる画面ルール
.claude/agents/code-reviewer.md   読み取り専用のレビュー用サブエージェント
.claude/skills/spring-endpoint/   エンドポイント／画面フラグメント追加の標準手順
.claude/hooks/verify-stop.py      Stop hook の参考サンプル（未登録、POSIX 向け）
.claude/README.md                 設定ガイド（人向け、セッションには読み込まれない）
.github/copilot-instructions.md   Copilot 向けの要約
.github/instructions/             rules から生成する Copilot のパス別指示
.mcp.json                         Context7 と Playwright（--isolated）
scripts/sync_rules.py             rules から Copilot の指示を生成し、--check で差分を検出する
scripts/htmx-check.mjs            実ブラウザーで HTMX のフラグメント置換を検証する（ログイン状態、セッション失効に対応）
scripts/xlsx2ai.py                Excel 設計書をシート単位の JSON／Mermaid に変換する
```

## 検証範囲

| CI で確認済み | 未確認（導入先で確認が必要） |
|---|---|
| テンプレートの内容、インストーラー、ルール同期、Excel 変換（Linux / macOS / Windows） | 実際の業務プロジェクト（マルチモジュール、Spring Security／CSRF、外部 Tomcat／WAR） |
| `htmx-check.mjs`（実際の htmx と Chromium、Ubuntu） | ネイティブ Windows 上の Claude Code、Maven、MCP |
| 導入 → `./mvnw verify` → 画面検証（Spring Boot + JSP + HTMX のサンプルアプリ、Ubuntu） | Claude Code のセッションでの実際の読み込み状況、GitHub App、有料の Action |
| バージョンを固定した Playwright MCP／DBHub の起動とツール一覧の取得、workflow の actionlint | Copilot の各機能が AGENTS.md とパス別指示を読み込むかどうか |

```bash
python3 -m pip install -r requirements-dev.txt     # Python 3.11+
python3 -m unittest discover -s tests -v
```

## ライセンス

MIT

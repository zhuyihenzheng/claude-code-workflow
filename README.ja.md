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
4. **一度受けた修正指示は、機械で止める**。人が直させた誤りは、プロンプトに 1 行足すのではなく、設計・型・`guard.py` のルール・テストのいずれかにします。レビューは diff の通読より先に検証の証跡を確認します（[解説](docs/15-纠正变成检查.md)、中国語）。

## 既存プロジェクトへの導入

```bash
python3 scripts/install.py project /path/to/your-project          # 予行：計画を表示するだけで、書き込まない
python3 scripts/install.py project /path/to/your-project --diff   # 予行：既存ファイルとの差分も表示する
python3 scripts/install.py project /path/to/your-project --apply  # 書き込む
python3 scripts/install.py project /path/to/your-project --apply --with-screen-tests   # 画面試験（midscene-poc）も導入する
python3 scripts/install.py doctor /path/to/your-project           # 導入後の確認：TODO の残り、ルールの同期、guard の結果、設定上のリスク
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
.claude/skills/change-flow/       改修の標準手順（設計書 → 実装 → 単体テスト → 画面試験 → 試験書）
.claude/skills/correct/           修正指示を設計・型・guard のルール・テストに変える手順
.claude/skills/feature-map/       機能マップ（docs/feature-map/）の作成・更新
.claude/hooks/verify-stop.py      Stop hook の参考サンプル（未登録、POSIX 向け）
.claude/README.md                 設定ガイド（人向け、セッションには読み込まれない）
.github/copilot-instructions.md   Copilot 向けの要約
.github/instructions/             rules から生成する Copilot のパス別指示
.github/pull_request_template.md  検証の証跡を先頭に置く PR テンプレート
config/guard/rules.json           guard のルール（直し方、由来、実際の誤りの例を持つ。初期 10 件）
docs/feature-map/README.md        機能マップの書式（1 機能 1 ファイル、コマンドと合格条件）
.mcp.json                         Context7 と Playwright（--isolated）
scripts/sync_rules.py             rules から Copilot の指示を生成し、--check で差分を検出する
scripts/guard.py                  決定的チェック：新しい違反、期限切れの例外、壊れたルールで失敗する。既存の違反は縮小だけができる
scripts/htmx-check.mjs            実ブラウザーで HTMX のフラグメント置換を検証する（ログイン状態、セッション失効に対応）
scripts/xlsx2ai.py                Excel 設計書をシート単位の JSON／Mermaid に変換する
scripts/xlsx_patch.py             変更指示どおりに Excel を書き換える（指示したセル以外は変更しない）
screen-tests/                     （任意）画面試験。バージョンを固定した midscene-poc を使用する
```

## 検証範囲

| CI で確認済み | 未確認（導入先で確認が必要） |
|---|---|
| テンプレートの内容、インストーラー、ルール同期、Excel 変換（Linux / macOS / Windows） | 実際の業務プロジェクト（マルチモジュール、Spring Security／CSRF、外部 Tomcat／WAR） |
| `htmx-check.mjs`（実際の htmx と Chromium、Ubuntu） | ネイティブ Windows 上の Claude Code、Maven、MCP |
| 導入 → `./mvnw verify` → 画面検証（Spring Boot + JSP + HTMX のサンプルアプリ、Ubuntu） | Claude Code のセッションでの実際の読み込み状況、GitHub App、有料の Action |
| バージョンを固定した Playwright MCP／DBHub の起動とツール一覧の取得、workflow の actionlint | Copilot の各機能が AGENTS.md とパス別指示を読み込むかどうか |
| `guard.py` の単体テスト（3 OS）、サンプルアプリでの合格・実際の誤りの検出、機能マップのコマンドの実行（Ubuntu） | 初期ルールの業務コードでの誤検知率、`correct` の実際の修正指示での動き |

```bash
python3 -m pip install -r requirements-dev.txt     # Python 3.11+
python3 -m unittest discover -s tests -v
```

## 実際のセッションからテンプレートを改善する

テンプレートの良し悪しは、導入先のプロジェクトでの実際の動きで判断します。このリポジトリには保守用の skill [`workflow-retro`](.claude/skills/workflow-retro/SKILL.md) があり、導入先の Claude Code のセッション記録を集計し、原因を特定・分類したうえでテンプレートを修正します。

集計スクリプトは単独でも実行できます。出力は件数のみで、プロンプト、コード、コマンドの引数は含みません（`--excerpt` はローカルで原文の一部を確認するためのもので、例外です）。

```bash
python3 .claude/skills/workflow-retro/scripts/session_metrics.py --project /path/to/your-project
```

確認できるのは、「最後にコードを変更した後、テンプレートが求める検証が成功しているか」、やり直しの回数、権限で止められた回数、skill とレビュー用サブエージェントの利用状況です。いずれも目安であり、結論は該当するセッションを読んで判断します。

## ライセンス

MIT

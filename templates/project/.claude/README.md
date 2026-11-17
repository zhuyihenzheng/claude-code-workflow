# `.claude/` 設定ガイド（人向け）

このファイルは開発者向けの説明であり、Claude Code のセッションには自動では読み込まれない。AI に常に守らせるルールはルートの `AGENTS.md` に、Claude Code 固有の補足は `CLAUDE.md` に記載する。

## 構成

| ファイル | 役割 | 変更時の注意 |
|---|---|---|
| `../AGENTS.md` | プロジェクトルールの唯一の正本（Copilot と共用） | 「チーム共通ルール」はシステムごとに書き換えない |
| `../CLAUDE.md` | 1 行目で `@AGENTS.md` を取り込み、Claude Code 固有の補足だけを置く | 毎セッション読み込まれるため、人向けの説明は書かない |
| [settings.json](settings.json) | チーム共有の権限（allow / deny / ask） | 個人の上書きは `settings.local.json`（リポジトリ管理対象外）に置く |
| `rules/*.md` | `paths:` に一致するファイルを扱うときだけ読み込まれるルール | 編集後に `python3 scripts/sync_rules.py` を実行し、Copilot 用の `.github/instructions/` を再生成する |
| `agents/code-reviewer.md` | 読み取り専用のレビュー用サブエージェント | Bash を持たないため、呼び出し側が diff を渡す |
| `skills/spring-endpoint/` | エンドポイント／画面フラグメント追加の標準手順 | TODO の参考パスをプロジェクトの実例に置き換える |
| `skills/change-flow/` | 改修の標準手順（設計書 → 実装 → 単体テスト → 画面試験 → 試験書） | 画面試験を導入していない場合は、該当ステップを `htmx-check.mjs` で代替する |
| `hooks/verify-stop.py` | Stop hook の参考サンプル（**未登録**） | 下記「Hooks」を参照 |
| `../.mcp.json` | MCP サーバー（Playwright のみ。ローカルプロセス） | リモートの MCP サービスを追加する場合は、事前に社内の承認を得る |

## 権限（settings.json）

- プロジェクトルート／worktree ルートから Claude Code を起動する。`/src/...` のようなパスはそこを基準に解決される。有効な権限は `/permissions` で確認する。
- Maven は `compile` / `test` / `verify` の完全一致のみを許可している。`Bash(./mvnw *)` のような広い許可は deploy や任意のプラグイン実行も通すため追加しない。
- deny／ask は Claude Code の組み込みツールに対する制御であり、プロセスの隔離ではない。任意のスクリプト、MCP、hooks の権限は別途管理する（OS のサンドボックス、最小権限の認証情報）。
- `bypassPermissions` モード、claude.ai コネクタ、Artifact の公開は無効としている。有効にする場合は社内の承認を得る。外部への通信の制限は、管理者が配布するサンドボックスの許可リストで行う。
- マイグレーションのディレクトリは deny ではなく ask としている。新規追加は確認のうえで行い、マージ済みファイルの不変性はマイグレーションツールと CI で検証する。

## 画面試験と Excel の修正

- `node run.mjs --engine playwright`（`--build-only`、`--only <スイート>` を含む）は許可している。`--engine ai` / `--engine midscene` / `--heal` / `--ai-assert` は画面のスクリーンショットをモデルに送信するため ask、`--update-baseline` / `--update-visual` は人だけが行うため deny としている。
- `screen-tests/baseline.json` の編集は ask、スクリーンショットを埋め込んだ `screen-tests/report.html` の Read は deny としている。AI は `結果一覧.md` を読む。
- Excel の修正は `scripts/xlsx_patch.py` の変更指示で行う。実行のたびに確認が入る（allow に追加していない）。

## Hooks

このテンプレートは hooks を登録しておらず、セッション終了時に自動でコンパイルは実行されない。検証コマンドは明示的に実行し、マージの可否は CI で判定する。

`hooks/verify-stop.py` は macOS / Linux / WSL 向けの参考サンプルである。使用する場合は内容を確認したうえで、`settings.json` に Stop hook として登録する。POSIX のプロセスグループに依存するため、ネイティブ Windows では書き換えが必要となる。

## MCP

`/mcp` で接続を確認する。Playwright は `--isolated` でブラウザーの状態を分離しているが、OS レベルのサンドボックスではない。本番環境の URL や認証情報を渡さない。

## Excel 設計書

`settings.json` は `.xlsx` / `.xlsm` の Read を deny している。`python scripts/xlsx2ai.py` が `specs/` を `specs-ai/` に変換し、AI は `specs-ai/index.md` から必要なシートだけを読む。CI では `python scripts/xlsx2ai.py --check` で変換漏れを検出できる。Excel 設計書を使用しないプロジェクトでは、スクリプトと deny ルールを削除してよい。

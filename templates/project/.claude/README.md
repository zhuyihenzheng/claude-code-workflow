# `.claude/` 設定ガイド（人向け）

このファイルは開発者向けの説明であり、Claude Code のセッションには自動では読み込まれない。AI に常に守らせるルールはルートの `AGENTS.md` に、Claude Code 固有の補足は `CLAUDE.md` に記載する。

## 構成

| ファイル | 役割 | 変更時の注意 |
|---|---|---|
| `../AGENTS.md` | プロジェクトルールの唯一の正本（Copilot と共用） | 「チーム共通ルール」はシステムごとに書き換えない |
| `../CLAUDE.md` | 1 行目で `@AGENTS.md` を取り込み、Claude Code 固有の補足だけを置く | 毎セッション読み込まれるため、人向けの説明は書かない |
| [settings.json](settings.json) | チーム共有の権限（allow / deny / ask） | 個人の上書きは `settings.local.json`（リポジトリ管理対象外）に置く |
| `rules/*.md` | `paths:` に一致するファイルを扱うときだけ読み込まれるルール | 編集後に `python3 scripts/sync_rules.py` を実行し、Copilot 用の `.github/instructions/` を再生成する |
| `agents/code-reviewer.md` | 読み取り専用のレビュー用サブエージェント | Bash を持たないため、呼び出し側が diff を渡す。確認の基準は `../REVIEW.md`（Copilot のコードレビューと共通） |
| `skills/spring-endpoint/` | エンドポイント／画面フラグメント追加の標準手順 | TODO の参考パスをプロジェクトの実例に置き換える |
| `skills/change-flow/` | 改修の標準手順（設計書 → 実装 → 単体テスト → 画面試験 → 試験書） | 画面試験を導入していない場合は、該当ステップを `htmx-check.mjs` で代替する |
| `skills/correct/` | 修正指示を設計・型・guard のルール・テストに変える手順 | ルールは `../config/guard/rules.json` に追加する |
| `skills/feature-map/` | 機能マップ（`../docs/feature-map/`）の作成・更新 | 画面を変更した PR で該当する機能ファイルも更新する |
| `../src/test/java/ArchitectureTest.java` | ArchUnit によるレイヤーとフィールドインジェクションの検査（任意、`--with-archunit`） | `../config/quality/pom-snippet.xml` の依存関係を pom.xml に追加しないとコンパイルできない |
| `../config/pmd/jsp-ruleset.xml` | PMD による JSP のエスケープ漏れ検査 | `../config/quality/pom-snippet.xml` の maven-pmd-plugin を pom.xml に追加すると `./mvnw verify` で実行される |
| `hooks/verify-stop.py` | Stop hook の参考サンプル（**未登録**） | 下記「Hooks」を参照 |
| `../.mcp.json` | MCP サーバー（Playwright のみ。ローカルプロセス） | リモートの MCP サービスを追加する場合は、事前に社内の承認を得る |

GitHub Copilot と併用する場合に Copilot へ効くもの・効かないもの、リポジトリの設定画面で行う作業は `../config/copilot/README.md` に記載している。

## 権限（settings.json）

- プロジェクトルート／worktree ルートから Claude Code を起動する。`/src/...` のようなパスはそこを基準に解決される。有効な権限は `/permissions` で確認する。
- Maven は `compile` / `test` / `verify` の完全一致のみを許可している。`Bash(./mvnw *)` のような広い許可は deploy や任意のプラグイン実行も通すため追加しない。
- deny／ask は Claude Code の組み込みツールに対する制御であり、プロセスの隔離ではない。任意のスクリプト、MCP、hooks の権限は別途管理する（OS のサンドボックス、最小権限の認証情報）。
- `bypassPermissions` モード、claude.ai コネクタ、Artifact の公開は無効としている。有効にする場合は社内の承認を得る。外部への通信の制限は、管理者が配布するサンドボックスの許可リストで行う。
- マイグレーションのディレクトリは deny ではなく ask としている。新規追加は確認のうえで行い、マージ済みファイルの不変性はマイグレーションツールと CI で検証する。

## 決定的チェック（guard）

- `python3 scripts/guard.py` は `config/guard/rules.json` のルールでコードを検査する。終了コード 0 = 違反なし、1 = 違反あり、2 = ルールまたは設定の誤り（検査未完了であり、合格ではない）。CI でも同じコマンドを実行する。
- 導入時に既存の違反が多い場合は、人が一度だけ `python3 scripts/guard.py --init-baseline` を実行し、現状を `config/guard/baseline.json` に記録してコミットする。以後、件数は縮小だけができる（`--update-baseline`）。
- 例外は違反行またはその直前の行に `guard:allow <ルールID> until=YYYY-MM-DD by=<承認者> -- <理由>` と書く。期限は 1 年以内で、期限が切れると失敗する。承認者は人であり、エージェントには書かせない。
- 検査、`--list`、`--update-baseline` は許可している。`--init-baseline` の実行と `config/guard/baseline.json` の編集は ask としている。
- ルールの追加は `correct` skill の手順で行う。`examples.bad` には実際にあった誤りを入れ、`examples.good` には誤検知しやすい正しい書き方を入れる。どちらかが期待どおりでなければ guard は終了コード 2 で止まる。
- guard は文字列の一致しか見ない。クラス間の依存は ArchUnit（`src/test/java/ArchitectureTest.java`）、JSP の構文に基づく検査は PMD（`config/pmd/jsp-ruleset.xml`）で行い、どちらも `./mvnw verify` で実行される。導入時に既存の違反が多い場合は、ArchUnit は `FreezingArchRule`、PMD は `maxAllowedViolations` で現状を記録し、以後は減らすだけにする。
- maven-pmd-plugin の設定は `<plugin>` 直下に置く。`<execution>` の中に置くと、`check` が内部で実行する解析に設定が渡らず、JSP を検査しないまま成功する。

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

`settings.json` は `.xlsx` / `.xlsm` の Read を deny している。`python scripts/xlsx2ai.py` が `specs/` を `specs-ai/` に変換し、AI は `specs-ai/index.md` から必要なシートの Markdown（`sheets/<シート>.md`：表は Markdown の表、地の文は箇条書き、図形フローは Mermaid）だけを読み、セル番地が必要なときだけ同名の JSON を読む。Markdown は人のレビューや PR の差分確認、画面試験の観点カバレッジ（`site.mjs` の `design`）にも使える。CI では `python scripts/xlsx2ai.py --check` で変換漏れを検出できる。Excel 設計書を使用しないプロジェクトでは、スクリプトと deny ルールを削除してよい。

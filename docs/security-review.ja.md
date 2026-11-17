# セキュリティレビュー資料（社内利用版）

対象：本リポジトリの `company` ブランチのテンプレートを、社内の Java / Spring Boot プロジェクトに導入する場合。
本資料は、テンプレートの内容を読んで整理したものであり、第三者によるセキュリティ監査の結果ではない。Claude Code 本体の仕様は公式ドキュメントに基づく（末尾の参照先）。バージョンにより変わるため、導入時に再確認すること。

## 1. 結論

- テンプレートは設定ファイル、Markdown、3 本のスクリプトで構成され、導入先のプロジェクト内で外部へ通信するコードは含まない。
- 既定の設定では、リモートの MCP サービス、サードパーティのプラグイン／mod、claude.ai コネクタ、Artifact の公開を使用しない。
- 最大の論点はテンプレートではなく、**Claude Code と GitHub Copilot がソースコードとプロンプトを社外の AI サービスへ送信すること**である。利用契約、接続経路、顧客の同意の確認が前提となる。
- テンプレートの権限設定は誤操作の防止策であり、セキュリティ境界ではない。境界は、管理者が配布する managed settings、OS のサンドボックス、最小権限の認証情報、リモートのブランチ保護で確保する。

## 2. データの流れ

| 送信元 | 送信先 | 送信される内容 | 既定 | 止め方 |
|---|---|---|---|---|
| Claude Code 本体 | Anthropic API（または Amazon Bedrock、Google Cloud、Microsoft Foundry、社内ゲートウェイ） | プロンプト、読み取ったソースコード、コマンドの出力 | 有効（利用の前提） | 接続経路は契約に合わせて選択する |
| Claude Code 本体 | 運用テレメトリ（Datadog） | 動作状況、エラーレポート | Anthropic API へ直接接続する場合のみ有効 | `DISABLE_TELEMETRY=1`、`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` |
| GitHub Copilot | GitHub | エディター上のコードとプロンプト | 利用する場合のみ | 契約と組織設定による |
| Playwright MCP | 指定した URL（通常は `localhost`） | ブラウザー操作 | 有効 | `.mcp.json` から削除する |
| 画面試験（`screen-tests/`、Playwright エンジン） | `site.mjs` に指定した URL | ブラウザー操作 | **未導入**（`--with-screen-tests` 指定時のみ）。導入後もモデルへの送信はない | — |
| 画面試験の AI エンジン（`--engine ai` / `midscene`、`--heal`、`--ai-assert`） | `.env` の `MIDSCENE_MODEL_*` に指定したモデル | **画面のスクリーンショット**と操作の指示文 | 使用しない（権限設定で実行のたびに確認） | `.env` にモデルを設定しない |
| claude.ai コネクタ（Gmail、Google Drive など） | 各サービス | コネクタ経由のデータ | **無効**（`disableClaudeAiConnectors`） | — |
| Artifact | claude.ai | 公開したページの内容 | **無効**（`enableArtifact: false`） | — |
| Context7、GitHub MCP、DBHub | 各サービス／開発用 DB | 検索語、リポジトリ操作、SQL | **未導入**（`templates/mcp.optional.json` に分離） | 承認後に個別に追加する |
| GitHub Actions の workflow | Anthropic API、GitHub | PR の差分、Issue の本文 | **未導入**（`--with-workflows` 指定時のみ） | — |

## 3. 外部から取得するソフトウェア

| 対象 | 取得元 | 固定方法 | 実行のタイミング |
|---|---|---|---|
| Claude Code 本体 | `downloads.claude.ai` または npm | 管理者が `requiredMinimumVersion` などで管理する | 常時 |
| `@playwright/mcp@0.0.85`（Microsoft） | `registry.npmjs.org` | 直接依存のバージョンのみ固定。推移的依存は固定していない | Claude Code の起動時（`npx`） |
| `playwright`、Chromium | npm、Playwright の配布サーバー | 導入先で固定する | `scripts/htmx-check.mjs` の実行時 |
| `midscene-poc`（画面試験フレームワーク） | `github.com`（公開リポジトリ。npm の Git 依存として取得） | コミット SHA（`4d01913b7cf3…`）で固定 | `screen-tests/` で `npm install` した場合のみ |
| `playwright@1.65.1` と Chromium | npm、Playwright の配布サーバー | 直接依存のバージョンを固定 | 同上 |
| `exstruct==0.9.0`、`excel2md==2.3.0` | PyPI | 直接依存のバージョンのみ固定 | `scripts/xlsx2ai.py` の実行時（Excel 設計書を使用する場合のみ） |
| 汎用 skill 3 件（MIT、mattpocock/skills 由来） | 本リポジトリに同梱 | 同梱済み。テキストの指示のみ | 利用者が `~/.claude/skills` に導入した場合 |

社内のミラー（npm／PyPI）がある場合は、そちらを使用する。

## 4. テンプレートが導入するファイルと実行内容

| ファイル | 実行されるか | 通信 |
|---|---|---|
| `AGENTS.md`、`CLAUDE.md`、`.claude/rules/`、`.claude/agents/`、`.claude/skills/` | テキストの指示のみ | なし |
| `.claude/settings.json` | 設定のみ。hooks は登録していない | なし |
| `.claude/hooks/verify-stop.py` | **未登録の参考サンプル**。登録しない限り実行されない | なし（Maven を起動する） |
| `scripts/sync_rules.py` | 手動または CI で実行。標準ライブラリのみ | なし |
| `scripts/xlsx2ai.py` | 手動で実行。ローカルで変換ツールを起動する | なし |
| `scripts/htmx-check.mjs` | 手動で実行。引数で渡した URL を開く | 指定した URL のみ |
| `.mcp.json` | Claude Code の起動時に Playwright MCP を起動する（初回は承認の確認が表示される） | 3 章を参照 |
| `scripts/xlsx_patch.py` | 手動で実行。変更指示（JSON）どおりにブックのセルを書き換える。標準ライブラリのみ | なし |
| `screen-tests/`（任意） | `node run.mjs` で実行。画面を操作し、試験仕様書・試験結果・`report.html`・`evidence/` を出力する。`report.html` と `evidence/` は画面のスクリーンショットを含むため、`.gitignore` でコミット対象から外している | 2 章を参照 |

インストーラー（`scripts/install.py`）は既存ファイルを上書き・削除せず、既定では計画を表示するだけで書き込まない。

## 5. テンプレートの権限設定

| 設定 | 内容 |
|---|---|
| allow | `mvnw` の `compile` / `test` / `verify` の完全一致、`git status` / `diff` / `log`、`gh pr view` / `gh issue view` のみ |
| deny | `.env*`、ファイル名に `credentials` / `secret` を含むファイル、`.xlsx` / `.xlsm` の読み取り。force push、`rm -rf /...` |
| allow（画面試験） | `node run.mjs --engine playwright`（`--build-only`、`--only` を含む） |
| ask | マイグレーションディレクトリの編集。画面試験の `baseline.json` の編集。スクリーンショットをモデルに送信する AI エンジンと `--heal` / `--ai-assert` |
| deny（画面試験） | 基準の更新（`--update-baseline` / `--update-visual`、人だけが行う）。スクリーンショットを埋め込んだ `screen-tests/report.html` の読み取り |
| その他 | `bypassPermissions` モードを無効化。claude.ai コネクタと Artifact を無効化 |

**限界**（公式ドキュメントの記載に基づく）：

- Bash の deny ルールはコマンドの文字列に対する一致であり、別の書き方（`sh -c`、フルパス指定など）は対象外となる。このため `curl` などの通信コマンドは deny にしていない（ローカルサービスの起動確認にも使用する）。外部への通信は 6 章のサンドボックスの許可リストで制限する。
- Read の deny ルールは組み込みのファイルツールと `cat` などの認識可能なコマンドに適用される。任意のスクリプトや `grep -r` による読み取りは防げない。
- `credentials` / `secret` はファイル名による推測である。実際の認証情報の配置に合わせて追加が必要となる。
- `AGENTS.md` の「顧客情報を AI ツールに渡さない」はモデルと利用者への指示であり、技術的な強制力はない。

## 6. 管理者に依頼する設定（managed settings）

プロジェクトの設定は開発者が変更できる。組織として強制する項目は managed settings で配布する。例を [`templates/managed-settings.example.json`](../templates/managed-settings.example.json) に用意している。

| キー | 目的 |
|---|---|
| `allowManagedMcpServersOnly`、`allowedMcpServers` | 許可した MCP サーバー以外を読み込ませない。例では Playwright を起動コマンドの完全一致（`serverCommand`）で許可している |
| `strictKnownMarketplaces`（空の配列） | プラグインのマーケットプレイスを追加させない |
| `pluginConfigs` の `cc-plugin-sec-default@builtin` に対する `allowManagedModsOnly` オプション | 利用者が導入した mod を読み込ませない（組み込みの mod は対象外） |
| `permissions.disableBypassPermissionsMode` | 権限確認を省略するモードを使用させない |
| `sandbox`（`allowUnsandboxedCommands: false`、`network.allowedDomains`） | Bash コマンドのファイル／ネットワークアクセスを OS レベルで制限する |
| `disableClaudeAiConnectors`、`enableArtifact` | コネクタと Artifact の公開を止める |
| `env`（`DISABLE_TELEMETRY` など） | 任意のテレメトリを止める |
| `cleanupPeriodDays` | セッション記録の保持期間を短くする |

例の値（許可ドメイン、保持日数など）は出発点であり、そのまま配布しない。`serverCommand` は引数まで完全一致のため、Playwright MCP のバージョンを上げる際は `.mcp.json` と同時に更新する。サンドボックスの許可リストでローカルサービス（`localhost`）への接続に追加の設定が必要かどうかは、配布前に確認すること。

## 7. ネットワークの許可が必要な接続先

Claude Code 本体が必要とする接続先は公式の一覧（末尾の参照先）に従う。主なものは `api.anthropic.com`、`claude.ai`、`claude.com`、`platform.claude.com`、`downloads.claude.ai` である。Amazon Bedrock などを経由する場合は、モデルへの通信と認証の接続先が変わる。

テンプレートの利用で追加になる接続先：

| 接続先 | 用途 | 不要にする方法 |
|---|---|---|
| `registry.npmjs.org` | Playwright MCP、`playwright` の取得 | 社内ミラーを使用する、または Playwright を使用しない |
| `github.com`、`codeload.github.com` | 画面試験フレームワーク（`midscene-poc`）の取得 | `npm pack` で作成した `.tgz` を社内のパッケージ置き場に置き、`screen-tests/package.json` の参照先を変更する |
| Playwright のブラウザー配布サーバー | Chromium の取得（初回のみ） | 社内で配布済みのブラウザーを `PLAYWRIGHT_CHROMIUM_EXECUTABLE` で指定する |
| `pypi.org`、`files.pythonhosted.org` | Excel 変換ツールの取得 | 社内ミラーを使用する、または Excel 変換を使用しない |
| Maven のリポジトリ | プロジェクトのビルド（既存） | — |

## 8. 残るリスクと運用上の対策

| リスク | 対策 |
|---|---|
| ソースコードや顧客情報が AI サービスへ送信される | 契約と顧客の同意を確認する。合成データを使用し、ログやスクリーンショットは事前にマスキングする |
| セッション記録（`~/.claude/projects/`）にソースコードとコマンド出力が残る | `cleanupPeriodDays` で保持期間を短くする。端末の暗号化と持ち出し制限を適用する |
| 開発者が個人でプラグイン／mod／MCP を追加する | 6 章の managed settings で制限する |
| AI が生成したコードの不具合や脆弱性 | 人によるレビュー、CI、ブランチ保護を必須とする。AI のレビューは人のレビューの代わりにしない |
| 画面試験の証跡（スクリーンショット、Excel の試験結果）に実データが写る | 合成データのテストアカウントだけを使用する。証跡を社外の AI ツールに渡さない。AI エンジンは使用前に承認を得る |
| ブラウザー操作で本番環境に接続する | Playwright には本番の URL と認証情報を渡さない。サンドボックスのネットワーク許可リストで制限する |
| 依存パッケージの改ざん | 社内ミラーと脆弱性スキャンを使用する。バージョンを上げる際は CI の結果を確認する |

## 9. 未確認の事項

- ネイティブ Windows 上での権限ルールの動作。
- managed settings の例を実際に配布した場合の動作。本リポジトリの CI では JSON としての妥当性のみを確認している。
- プロジェクトの `settings.json` に追加した無効化の設定（`bypassPermissions`、claude.ai コネクタ、Artifact）が、実際のセッションで期待どおりに動作すること。各キーの説明は公式の設定リファレンスに基づいており、セッションでの動作は確認していない。
- 多モジュール構成、Spring Security を使用する業務プロジェクトでの動作。
- 画面試験を実際の業務プロジェクトで実行した場合の動作（本リポジトリでは CI のサンプルアプリでのみ確認）。

## 参照先

- ネットワーク要件：<https://code.claude.com/docs/en/network-config>
- 設定と優先順位：<https://code.claude.com/docs/en/settings>、設定例：<https://code.claude.com/docs/en/settings-example>
- 権限ルール：<https://code.claude.com/docs/en/permissions>
- mod の権限と管理：<https://code.claude.com/docs/en/plugins/mods/overview>
- データの取り扱い：<https://code.claude.com/docs/en/data-usage>

# プロジェクトルール

## チーム共通ルール

このセクションは各システムにそのままコピーし、チームでレビューしたうえで一括して反映する。システムごとの差異は次のセクションに記載し、このセクションをシステムごとに書き換えない。両セクションを合わせて、プロジェクトルールの唯一の正本とする。

### コーディング規約

- レイヤー間の依存は Controller → Service → Mapper/Repository の一方向とする。Controller から永続化層を直接呼び出したり、永続化層のオブジェクトをそのまま公開したりしない。〔guard: controller-no-persistence〕〔ArchUnit: controllers_do_not_use_persistence, services_do_not_depend_on_controllers〕
- DI はコンストラクタインジェクションに統一し、フィールドインジェクションは使用しない。永続化層はプロジェクトで採用している方式を踏襲し、テンプレートに合わせるために JPA を導入しない。〔guard: java-no-field-injection〕〔ArchUnit: no_field_injection〕
- REST の例外はプロジェクトの規約に従って JSON で返す（例：`@RestControllerAdvice`）。画面の例外はビューで処理し（例：`@ControllerAdvice` + ModelAndView）、画面に JSON のエラーレスポンスを返さない。例外を握りつぶさない。〔guard: java-no-empty-catch, java-no-print-stack-trace〕
- テストには JUnit 5 + Mockito を使用する。新規コードには必ずテストを追加し、失敗するテストを先に作成してから実装する。結合テストには Testcontainers を使用する。テストには `@DisplayName` で確認する観点を日本語で書く（単体テスト成績書の「観点」になる）。テストを無効化して通さない。待ち合わせに固定時間の sleep を使わない（テストも本番コードも）。〔guard: test-no-disabled, java-no-thread-sleep, e2e-no-fixed-wait〕
- ビルドにはプロジェクトの Maven Wrapper を使用し、システムにインストールされた mvn は使用しない。

### 画面の実装規約と検証

- JSP は描画のみを担当する。scriptlet の新規追加は禁止する。業務ロジックは Controller/Service に配置し、式には EL + JSTL を使用する。ユーザーが操作できる値の出力は、コンテキストに応じて必ずエスケープする。〔guard: jsp-no-scriptlet〕〔PMD: NoUnsanitizedJSPExpression〕
- HTMX の画面全体と部分テンプレート（フラグメント）は別々のビューとし、既存のルーティング規約を踏襲する。JSP のフラグメントは専用の JSP ビュー名を返し、Thymeleaf の `:: fragment` 構文は使用しない。
- `hx-target` には画面上に存在する id を指定する。入力チェックエラー時はプロジェクトの仕様に従い、422 を使用する場合は 422 の swap 設定を事前に確認する。リクエストには共通の CSRF ヘッダーを付与する。`HX-Request` を認証・認可の判断根拠にしない。
- バックエンドの変更：関連テストとコンパイルが成功したことを確認し、実際のコマンド出力を提示する。コミット前に verify を全体実行し、マージ前に CI で再検証する。
- JSP の変更：サービス起動 → Playwright で画面を開く → 描画結果と実際の操作結果をアサーションで確認し、スクリーンショットを保存する。JSP/EL のエラーは実行時に検証する。
- HTMX の変更：ブラウザーで操作し、対象フラグメントの置換成功とコンソールエラーがないことをアサーションで確認して、スクリーンショットを保存する。正常時、入力チェックエラー時の再表示、CSRF エラー／セッション失効時を確認し、フラグメントにログイン画面全体を表示しない。
- MockMvc/curl の成功だけでは画面が動作することの確認にはならない。コンパイル失敗、テストのスキップ、ブラウザーでの未検証がある場合は理由を報告し、検証済みとしない。

### 修正指示と決定的チェック

- 規約末尾の〔guard: …〕は、その規約のうち `python scripts/guard.py`（ルールは `config/guard/rules.json`）が検査する部分のルール ID である。〔ArchUnit: …〕（`src/test/java/ArchitectureTest.java`）と〔PMD: …〕（`config/pmd/jsp-ruleset.xml`）は `./mvnw verify` が検査する。タグのない規約と、検査できない部分はレビューで確認する。
- 変更後とコミット前に `python scripts/guard.py` を実行し、違反は表示された直し方で直す。ルールを弱めない。例外（`config/guard/allow.json`）とベースライン（`config/guard/baseline.json`）は人だけが追加・更新する。件数を縮小する `--update-baseline` は実行してよい。
- 人から修正を指示されたら、直したうえで同じ誤りを繰り返さない仕組みを次の順で検討する：設計（正しい方法を 1 つにし、古い実装を削除する）→ 型・コンパイル → guard のルール → テスト → 文章のルール。文章だけで済ませるのは、判断が必要で機械化できないものに限る。
- 回避策を正当化するコメントやコメントアウトしたコードを残さない。直せない外部の制約は、テストかルールで表し、課題番号を記載する。〔guard: comment-workaround, java-no-commented-out-code〕
- 完了の報告では、主張ではなく証跡（実行したコマンドと結果、スクリーンショットの保存先、`docs/feature-map/` の機能 ID）を示す。画面や機能は機能マップの名称と ID で呼ぶ。
- 作業の最初に `docs/knowledge/`（用語集 `glossary.md`、コードマップ `codemap.md`）を読み、依頼の言葉と修正箇所を引く。作業の最後に、今回確かめた事実を書き戻す（`knowledge` skill）。記載が古くなっていないことは `python scripts/knowledge_check.py` が確認する。
- 設計書の表とコードの値の対応（メッセージ一覧など）は `config/spec-sync.json` に登録し、`python scripts/spec_sync.py` で一致を確認する。不一致は、設計書が正しければコードを、コードが正しければ設計書を直す。

### 制約・セキュリティ・データの取り扱い

- `.env*` および認証情報を含むファイルは読み取らず、本番データベースには接続しない。
- 顧客情報、本番データ、API キー・秘密鍵などの認証情報や機密情報を AI ツールに渡さない。貼り付け、アップロード、添付ファイル、ログ、スクリーンショット、外部サービス経由の受け渡しも禁止する。サンプルには合成データを使用し、必要なコンテキストは事前にマスキング・匿名化したうえで、人の目で確認する。
- `src/main/resources/db/migration/` 配下のマージ済みマイグレーションファイルは変更しない。追加するマイグレーションはプロジェクトの手順に従ってレビューし、マージ済みファイルはマイグレーションツールと CI で検証する。
- Excel 設計書（`specs/` の .xlsx/.xlsm）は AI ツールに直接読ませない。`python scripts/xlsx2ai.py` で生成した `specs-ai/` を `specs-ai/index.md` から開き、必要なシートの Markdown（`sheets/<シート>.md`）だけを読む。セル番地が必要なとき（変更指示を書くとき）だけ同名の `.json` を読む。原本の修正は、変更指示（JSON）を書いて `python scripts/xlsx_patch.py` で適用し、Excel を直接編集しない。原本を更新したら再生成し、生成物は手で編集しない。
- タスクの範囲外のコードを、ついでにリファクタリングしない。既存 JSP の修正は必要最小限とし、独断でテンプレートエンジンを移行しない。

## 本システム固有情報

本システムの事実と TODO のみを記載し、チーム共通ルールを緩和しない。コードからは読み取れない情報を残し、古くなった記載は速やかに更新・削除する。

### 技術スタックと画面構成（バージョンを明記し、該当バージョンのドキュメントを参照する）

- システム名／用途：<!-- TODO -->
- 画面構成：<!-- TODO：JSP / HTMX / 両方を使用。HTMX のサーバー側のビュー技術も明記する -->
- JDK：<!-- TODO：例 21 -->、Spring Boot：<!-- TODO：例 3.5.x -->
- HTMX：<!-- TODO：バージョン（例 2.0.x）。未使用の場合は対象外と記載する -->
- 画面／CSS のパス：<!-- TODO：例 src/main/webapp/、src/main/webapp/static/css/ -->
- データベース／永続化層：<!-- TODO：例 PostgreSQL 16 / MyBatis Mapper。テスト用コンテナのバージョンも記載する -->

### よく使うコマンド（動作を個別に確認してから記載する）

<!-- TODO：テストクラス／メソッド、profile、ポートを置き換える。マルチモジュールの場合はモジュール指定の引数を追加する。 -->

macOS / Linux / WSL：

```bash
./mvnw -q compile
./mvnw test
./mvnw -Dtest=OrderServiceTest test
./mvnw -Dtest=OrderServiceTest#createOrder test
./mvnw verify
./mvnw spring-boot:run -Dspring-boot.run.profiles=local
```

Windows CMD（Git Bash では `./mvnw.cmd`、PowerShell では `.\mvnw.cmd` を使用。引数は共通）：

```bat
mvnw.cmd -q compile
mvnw.cmd test
mvnw.cmd -Dtest=OrderServiceTest test
mvnw.cmd -Dtest=OrderServiceTest#createOrder test
mvnw.cmd verify
mvnw.cmd spring-boot:run -Dspring-boot.run.profiles=local
```

### 本システムの注意点と動作確認の手順

- 起動／デプロイとポート：<!-- TODO：ローカル起動コマンドが使用できるか。外部 Tomcat/WAR のデプロイコマンド -->
- 参考となる Controller／画面：<!-- TODO：実際のパス。既存画面で踏襲してはいけない実装も記載する -->
- ビューの解決とフラグメントのルーティング：<!-- TODO：ViewResolver のプレフィックス／サフィックス、画面全体／フラグメントのビュー名 -->
- HTMX の入力チェックエラー／セッションに関する仕様：<!-- TODO：200 のエラーフラグメント、または設定済みの 422 swap。未使用の場合は対象外と記載する -->
- 画面試験：<!-- TODO：`screen-tests/` の有無、アプリケーションの起動方法、データの初期化方法。未導入の場合は対象外と記載する -->
- 画面の動作確認：<!-- TODO：ローカル URL、合成データによるテストアカウントの入手先、主要操作、スクリーンショットの保存先。実際の認証情報は記載しない。HTMX 画面は `scripts/htmx-check.mjs` の実行例をここに記載する -->

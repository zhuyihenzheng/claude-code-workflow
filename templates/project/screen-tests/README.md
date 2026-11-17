# 画面試験

設計書をもとにケース（`cases.mjs`）を書き、実ブラウザーで実行して、試験仕様書・試験結果・証跡を出力する。フレームワークは [midscene-poc](https://github.com/zhuyihenzheng/midscene-poc) を、コミット SHA を固定して使用する（`package.json`。Playwright のバージョンも固定している）。

## 初回のセットアップ

```bash
cd screen-tests
npm install
npx screen-test-new-site <システム名> --dir . --url http://localhost:8080/   # site.mjs / cases.mjs / run.mjs を作成
cp .env.example .env                                                        # テストアカウントを記入（合成データのみ。コミットしない）
```

`site.mjs` の `login` を実画面に合わせ、`design` に設計書（Markdown）のパスを指定する。ブラウザーは既定で Chrome を使用する。ない場合は `npx playwright install chromium` を実行し、`.env` の `TEST_BROWSER_CHANNEL` を `chromium` にする。

GitHub から取得できない環境では、midscene-poc のリポジトリで `npm pack` を実行し、生成された `.tgz` を社内のパッケージ置き場に配置して `package.json` の参照先を変更する。

## 日常のコマンド（`screen-tests/` で実行）

| コマンド | 内容 |
|---|---|
| `node run.mjs --engine playwright --build-only` | ブラウザーを使わずに、ケースの書き方と辞書を確認し、`試験仕様書.xlsx` を生成する。`site.mjs` に `design` を指定している場合は `観点カバレッジ.md` も生成する |
| `node run.mjs --engine playwright` | Playwright エンジンで実行する（AI モデル不要）。アプリケーションは起動しておく |
| `node run.mjs --engine playwright --only 01-xxx` | 1 スイートだけ実行する |
| `npx screen-test-explore site.mjs` | 画面を採取し、`inventory/inventory.md` に入力項目・ボタン・メッセージを出力する |

`観点カバレッジ.md`（設計書の項目にケースがあるか、根拠のない期待値がないか）は、Markdown の設計書だけを対象とする。設計書の画面一覧・メッセージに加えて、「項番」と「チェック内容」の列を持つ表（入力チェック・相関チェック）の各行を拾う。チェックのキーは「見出しの番号-項番」（`### 5.2 相関チェック` の項番 6 なら `5.2-6`）で、ケースに `refs: ['5.2-6']` と書くと対応ありになる。Excel の設計書だけのプロジェクトでは生成されないため、設計書とケースの対応は観点表を作成して人が確認する。

## 結果の見方

- AI ツールと CI が読むもの：`結果一覧.md`、`不具合票ドラフト.md`、`観点カバレッジ.md`、`out/junit.xml`。
- 人が見るもの：`report.html`（スクリーンショットを埋め込んだレポート）、`試験結果.xlsx`、`evidence/`。
- 終了コードは「基準（`baseline.json`）と比べて想定外があるか」を表す。既知の NG を基準に登録できるのは人だけである（`--update-baseline`）。

ケースの書き方の規約は `node_modules/midscene-poc/.github/instructions/site-tests.instructions.md` にある。期待値は必ず設計書から取り、画面に表示されている値を期待値にしない。

## AI エンジンについて

`--engine ai`、`--engine midscene`、`--heal`、`--ai-assert` は、画面のスクリーンショットをモデルに送信する。使用する場合は、送信先と画面に写るデータについて事前に社内の承認を得る。既定の Playwright エンジンは、モデルを使用しない。

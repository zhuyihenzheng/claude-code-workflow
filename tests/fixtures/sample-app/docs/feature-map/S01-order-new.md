# S01 注文登録

利用者は名前を入力して〈登録〉を押し、注文を登録する。フォームの領域だけが置き換わり、画面全体は再読み込みしない。名前が未入力の場合は、入力済みの値を保持したままエラーメッセージ付きでフォームが再表示される。入力値は HTML として解釈されない。

## サブ機能

- `S01-1` 名前を入力して登録すると、登録結果が表示される。
- `S01-2` 名前が未入力の場合、「名前を入力してください」とともにフォームが再表示される（HTTP 422）。
- `S01-3` 名前に HTML を入力しても、文字列としてそのまま表示される。

## 到達方法

- URL：`http://localhost:8080/orders/new`（ログイン不要）。

## 操作と確認

前提：アプリケーションを `./mvnw spring-boot:run` で起動し、`http://localhost:8080/orders/new` が応答する。

- **S01-1 登録**：`node scripts/htmx-check.mjs --url http://localhost:8080/orders/new --expect '#order-form' --fill '#name=テスト太郎' --click '#submit' --contains '登録しました：テスト太郎' --screenshot target/evidence/S01/S01-1.png` が終了コード 0。`#order-form` に「登録しました：テスト太郎」が表示される。
- **S01-2 入力エラー**：`node scripts/htmx-check.mjs --url http://localhost:8080/orders/new --expect '#order-form' --click '#submit' --contains '名前を入力してください' --screenshot target/evidence/S01/S01-2.png` が終了コード 0。フォームが置き換わり、エラーメッセージが表示される。
- **S01-3 エスケープ**：`node scripts/htmx-check.mjs --url http://localhost:8080/orders/new --expect '#order-form' --fill '#name=<b id="xss">x</b>' --click '#submit' --contains '登録しました：<b id="xss">x</b>' --screenshot target/evidence/S01/S01-3.png` が終了コード 0。タグが文字列として表示される。

## 注意点

- 「登録しました」だけを `--contains` に指定すると、名前の表示漏れを見逃す。入力した名前まで含めて確認する。
- 終了コード 2 は「検証未完了」（サーバーやブラウザーに到達できない）であり、合格ではない。

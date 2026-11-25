# コードマップ

## S01 注文登録

- 画面：`src/main/webapp/WEB-INF/jsp/orders/new.jsp`、フラグメント `src/main/webapp/WEB-INF/jsp/fragments/order-form.jsp`（入力）と `src/main/webapp/WEB-INF/jsp/fragments/order-result.jsp`（結果）
- Controller：`src/main/java/com/example/demo/OrderController.java`（`newOrder`、`create`）
- 設計書：`docs/設計書.md`
- テスト：`src/test/java/com/example/demo/OrderControllerTest.java`、画面試験 `screen-tests/cases.mjs`
- 注意：名前が未入力のときは 422 とフォームのフラグメントを返す。HTMX は既定で 422 を置換しないため、`src/main/webapp/WEB-INF/jsp/orders/new.jsp` の swap 設定と組で変更する。
